"""Company viability, statement-derived evidence and dated market drivers."""
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import re
import urllib.parse
import urllib.request

import market_outlook
import sector_analysis

KINDS = ('issuer_statements', 'issuer_governance', 'issuer_drivers', 'issuer_exposure')
FLOW = ('net_income', 'revenue', 'gross_profit', 'cost_of_revenue', 'ebit', 'ebitda', 'interest_expense', 'operating_cashflow', 'free_cashflow')
BALANCE = ('equity', 'debt', 'cash', 'current_assets', 'current_liabilities', 'inventory')
FIELDS = FLOW + BALANCE
BRAPI_FIELDS = {'income-statement': {'netIncome': 'net_income', 'totalRevenue': 'revenue', 'grossProfit': 'gross_profit',
    'costOfRevenue': 'cost_of_revenue', 'ebit': 'ebit', 'cleanEbitda': 'ebitda', 'interestExpense': 'interest_expense'},
    'cash-flow': {'operatingCashFlow': 'operating_cashflow', 'freeCashFlow': 'free_cashflow'}}
B3_RULE = 'https://www.b3.com.br/pt_br/produtos-e-servicos/solucoes-para-emissores/segmentos-de-listagem/'
B3_API = 'https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/'
USD_ROLES = {'mixed': 'Exposição ainda a confirmar', 'exporter': 'Receita de exportação em dólar',
    'importer': 'Custos / importações em dólar', 'debt': 'Dívida em dólar', 'neutral': 'Exposição líquida reduzida / protegida'}
BENCHMARKS = {
    'brent': ('Petróleo Brent', 'DCOILBRENTEU', 'US$/barril', 'daily', 'EIA via FRED'),
    'iron': ('Minério de ferro', 'PIORECRUSDM', 'US$/tonelada', 'monthly', 'FMI via FRED'),
    'copper': ('Cobre', 'PCOPPUSDM', 'US$/tonelada', 'monthly', 'FMI via FRED'),
    'soy': ('Soja', 'PSOYBUSDM', 'US$/tonelada', 'monthly', 'FMI via FRED'),
    'us_rates': ('Juros efetivos nos EUA', 'DFF', '% a.a.', 'daily', 'Federal Reserve via FRED')}
DRIVER_KEYS = ('rates', 'usd', *BENCHMARKS)
SECTOR_FOCUS = {
    'bank': [('basel', 'Folga de capital', 'Compare Basileia com a exigência deste banco e acompanhe capital principal.'),
        ('npl90', 'Qualidade do crédito', 'Acompanhe atraso acima de 90 dias, renegociações e custo do crédito.'),
        ('coverage', 'Cobertura das provisões', 'Compare provisões e carteira inadimplente na mesma definição.')],
    'insurance': [('solvency', 'Solvência', 'Compare capital disponível e requerido, na mesma data e unidade.'),
        ('loss_ratio', 'Sinistralidade', 'Acompanhe sinistros/prêmios ganhos e a composição da carteira.'),
        ('combined_ratio', 'Resultado da subscrição', 'Sinistros e despesas/prêmios ganhos; acima de 100% pode indicar perda na subscrição.')],
    'financial_services': [('roe', 'Retorno das participações', 'Avalie recorrência, concentração e distribuição de caixa.'),
        ('recurring_revenue', 'Receita recorrente', 'Confirme qual parcela da receita se repete e sua definição.')],
    'utility': [('net_debt_ebitda', 'Dívida e expansão', 'Leia vencimentos, capex, covenants e concessões.'),
        ('free_cashflow', 'Caixa após investimento', 'Confira manutenção, expansão e a definição de caixa livre.'),
        ('contracted_revenue', 'Receita contratada', 'Informe a parcela contratada e acompanhe prazo, contrapartes e revisões tarifárias.')],
    'retail': [('gross_margin', 'Margem e repasse de custos', 'Compare mix de vendas, descontos e margem bruta.'),
        ('inventory_days', 'Giro do estoque', 'Dias de estoque: crescimento sem vendas pode consumir caixa.'),
        ('same_store_sales', 'Vendas mesmas lojas', 'Compare lojas e janela equivalentes; crescimento pode refletir inflação.')],
    'commodity': [('net_debt_ebitda', 'Dívida fora do pico do ciclo', 'Teste EBITDA menor e preços realizados, custos e hedges.'),
        ('gross_margin', 'Custo de produção e margem', 'Preço de referência não é o preço realizado pela empresa.'),
        ('production_growth', 'Produção e reservas', 'Acompanhe volume, reservas, custo unitário e investimento de manutenção.')],
    'metals': [('net_debt_ebitda', 'Dívida e ciclo de metais', 'Separe minério, cobre, aço e metais preciosos.'),
        ('gross_margin', 'Margem de produção', 'Custos, frete, qualidade do produto e câmbio mudam o preço realizado.'),
        ('production_growth', 'Volume produzido', 'Compare produção, reservas e capex de manutenção.')],
    'construction': [('net_debt_equity', 'Dívida e patrimônio', 'Leia recebíveis, caixa restrito, distratos e cronograma dos projetos.'),
        ('gross_margin', 'Margem dos projetos', 'Compare margem reconhecida, carteira de vendas e custos a incorrer.'),
        ('sales_velocity', 'Velocidade de vendas', 'Vendas sobre oferta (VSO) exige janela e base equivalentes.')],
    'transport': [('net_debt_ebitda', 'Dívida e arrendamentos', 'Confira a mesma base de arrendamentos e as concessões.'),
        ('operating_margin', 'Margem operacional', 'Separe combustível, tarifas, pedágios e custos de manutenção.'),
        ('utilization', 'Utilização / ocupação', 'Use a medida operacional do negócio: frota, assentos ou capacidade.')],
    'telecom': [('free_cashflow', 'Caixa após expansão de rede', 'Confira capex recorrente, espectro e arrendamentos.'),
        ('churn', 'Cancelamento de clientes', 'Compare churn na mesma janela e tipo de serviço.'),
        ('operating_margin', 'Margem e competição', 'Acompanhe ARPU, mix de clientes e custo de aquisição.')],
    'technology': [('recurring_revenue', 'Receita recorrente', 'Separe assinaturas, serviços e receitas pontuais.'),
        ('retention', 'Retenção de receita', 'Confirme se é retenção bruta ou líquida; expansão de clientes altera a leitura.'),
        ('operating_margin', 'Escala e rentabilidade', 'Avalie crescimento, remuneração em ações e conversão em caixa.')],
    'health': [('operating_margin', 'Margem do negócio', 'Separe hospitais, laboratórios e operadoras.'),
        ('receivable_days', 'Prazo dos recebíveis', 'Informe prazo médio e acompanhe glosas e inadimplência.')],
    'education': [('student_dropout', 'Evasão de alunos', 'Compare retenção, captação, modalidade e período letivo.'),
        ('receivable_days', 'Recebimento de mensalidades', 'Acompanhe descontos, inadimplência e diferença entre lucro e caixa.')],
    'food_agro': [('gross_margin', 'Margem e insumos', 'Separe produtor, processador e distribuidor; safra e clima importam.'),
        ('inventory_days', 'Estoque e capital de giro', 'Compare sazonalidade, safra e financiamento do estoque.'),
        ('production_growth', 'Volume de produção', 'Confira produto, capacidade e custos unitários.')],
    'industrial': [('gross_margin', 'Custos e margem', 'Compare mix, produtividade e capacidade de repassar custos.'),
        ('inventory_days', 'Capital de giro', 'Acompanhe estoques, pedidos e recebíveis.'),
        ('utilization', 'Uso da capacidade', 'Compare pedidos, utilização e necessidade de investimento.')],
    'general': [('operating_margin', 'Margem operacional', 'Confira recorrência e concentração de clientes.'),
        ('cash_conversion', 'Lucro que vira caixa', 'Caixa operacional/lucro na mesma janela; capital de giro pode distorcer um ano.')],
}

for sector, extras in {
    'bank': [('roe', 'Rentabilidade e ciclo de crédito', 'Separe resultado recorrente, provisões e custo de captação.'),
        ('payout', 'Distribuição e capital', 'Compare distribuição, lucro e capital necessário ao crescimento.')],
    'insurance': [('roe', 'Retorno e resultado financeiro', 'Separe subscrição e rendimento dos investimentos.'),
        ('payout', 'Distribuição e reservas', 'Leia solvência, reservas e a cobertura do lucro na mesma janela.')],
    'financial_services': [('operating_margin', 'Margem e modelo do negócio', 'Use apenas se a definição operacional for pertinente à bolsa, gestora ou holding.'),
        ('payout', 'Distribuição das participações', 'Compare lucro recorrente e caixa efetivamente recebido das participações.')],
    'utility': [('interest_coverage', 'Folga para pagar juros', 'Compare encargos, indexadores, vencimentos e concessões.'),
        ('roic', 'Retorno da expansão', 'Confronte ROIC e custo de capital na mesma base; caixa futuro depende dos contratos.')],
    'retail': [('operating_margin', 'Margem após despesas', 'Compare aluguel, pessoal, canais de venda e ajustes IFRS 16.'),
        ('current_ratio', 'Capital de giro e liquidez', 'Estoque parado e recebíveis não equivalem a caixa imediatamente disponível.')],
    'commodity': [('free_cashflow', 'Caixa ao longo do ciclo', 'Separe expansão, aquisições e investimento de manutenção.'),
        ('operating_margin', 'Preço realizado e custos', 'Compare produtos, frete, royalties e custo unitário.')],
    'metals': [('free_cashflow', 'Caixa e investimento de manutenção', 'Lucro no pico dos preços não demonstra caixa sustentável.'),
        ('operating_margin', 'Custos, frete e mix', 'Compare minério, aço e metais na operação específica.')],
    'construction': [('operating_cashflow', 'Caixa e entrega dos projetos', 'Compare lançamentos, vendas, recebimentos e entrega na mesma fase do ciclo.'),
        ('receivable_days', 'Recebíveis e distratos', 'Confira prazo, qualidade, financiamento e concentração.')],
    'transport': [('free_cashflow', 'Caixa após renovação da operação', 'Leia frota, manutenção, concessões e arrendamentos.'),
        ('interest_coverage', 'Juros e financiamento', 'Compare moeda, vencimentos e composição dos encargos.')],
    'telecom': [('recurring_revenue', 'Base recorrente de clientes', 'Separe serviços recorrentes, equipamentos e receitas pontuais.'),
        ('interest_coverage', 'Dívida e investimento em rede', 'Confronte encargos com capex, espectro e arrendamentos.')],
    'technology': [('free_cashflow', 'Conversão do crescimento em caixa', 'Leia despesas capitalizadas, aquisições e remuneração em ações.'),
        ('receivable_days', 'Prazo de recebimento', 'Compare expansão comercial, concentração e cobrança de contratos.')],
    'health': [('gross_margin', 'Custos de atendimento', 'Separe negócio hospitalar, diagnóstico, farmacêutico e operadora.'),
        ('utilization', 'Uso da capacidade', 'Confira leitos, unidades ou capacidade produtiva conforme o negócio.'),
        ('net_debt_ebitda', 'Dívida e aquisições', 'Acompanhe integração, arrendamentos e caixa para servir a dívida.')],
    'education': [('operating_margin', 'Margem por modalidade', 'Compare presencial, digital, mensalidades e bolsas.'),
        ('free_cashflow', 'Caixa e investimento', 'Leia captação de alunos, despesas comerciais e aquisições.'),
        ('net_debt_ebitda', 'Dívida e capacidade de pagamento', 'Compare encargos, arrendamentos e geração recorrente.')],
    'food_agro': [('free_cashflow', 'Caixa e sazonalidade', 'Compare safra, capital de giro, manutenção e expansão.'),
        ('net_debt_ebitda', 'Dívida fora do pico da safra', 'Teste preços realizados menores e custos maiores.')],
    'industrial': [('operating_margin', 'Produtividade e despesas', 'Compare mix, carteira de pedidos e capacidade de repasse.'),
        ('free_cashflow', 'Caixa após investimento', 'Leia manutenção, expansão e necessidade de capital de giro.')],
    'general': [('gross_margin', 'Margem e composição da receita', 'Compare mix, preços e custos diretos.'),
        ('interest_coverage', 'Folga para servir a dívida', 'Compare encargos e resultado operacional na mesma base.'),
        ('free_cashflow', 'Caixa após investimento', 'Separe manutenção, expansão e aquisições.')],
}.items():
    SECTOR_FOCUS[sector].extend(extras)


def validate_snapshot(app, kind, d):
    if not isinstance(d, dict) or kind not in KINDS or not isinstance(d.get('symbol'), str) or not re.fullmatch(r'[A-Z0-9.^-]{1,24}', d['symbol']):
        raise ValueError('Dados de análise da empresa inválidos.')
    def past(ref):
        ref = app.valid_date(ref)
        if ref > app.today().isoformat(): raise ValueError('Análise com data futura.')
        return ref
    def url(ref):
        ref = app.validate_url(ref)
        if not ref: raise ValueError('Informe o link da fonte.')
        return ref
    def number(v):
        if v is None: return None
        if type(v) not in (float, int) or not math.isfinite(v): raise ValueError('Indicador inválido.')
        return app.number(v)
    out = dict(d)
    if kind == 'issuer_statements':
        if set(d) != {'symbol', 'currency', 'annual', 'quarterly', 'sources', 'source_url'} or d['currency'] != 'BRL':
            raise ValueError('Campos ou moeda das demonstrações inválidos.')
        out['source_url'] = url(d['source_url'])
        if not isinstance(d['sources'], dict) or not d['sources'] or set(d['sources']) - {'income-statement', 'balance-sheet', 'cash-flow'}:
            raise ValueError('Fontes das demonstrações inválidas.')
        out['sources'] = {k: url(v) for k, v in d['sources'].items()}
        for bucket, limit in [('annual', 11), ('quarterly', 28)]:
            if not isinstance(d[bucket], list) or len(d[bucket]) > limit: raise ValueError('Série de demonstrações inválida.')
            rows = []
            for r in d[bucket]:
                if not isinstance(r, dict) or set(r) != {'date', *FIELDS}: raise ValueError('Período financeiro inválido.')
                values = {k: number(r[k]) for k in FIELDS}
                if any(values[k] is not None and values[k] < 0 for k in BALANCE if k != 'equity'):
                    raise ValueError('Saldo de ativo ou dívida negativo incompatível com a definição.')
                rows.append({'date': past(r['date']), **values})
            if len({r['date'] for r in rows}) != len(rows) or bucket == 'annual' and len({r['date'][:4] for r in rows}) != len(rows):
                raise ValueError('Períodos duplicados nas demonstrações.')
            out[bucket] = sorted(rows, key=lambda r: r['date'])
        if not out['annual'] and not out['quarterly']: raise ValueError('Demonstrações sem períodos.')
    elif kind == 'issuer_governance':
        if set(d) != {'symbol', 'segment', 'tag_along', 'asof', 'first_listed', 'source_url', 'rule_url', 'method'}:
            raise ValueError('Campos de governança inválidos.')
        out.update(asof=past(d['asof']), first_listed=past(d['first_listed']) if d['first_listed'] else None,
            segment=app.text_value(d['segment'], 100), tag_along=number(d['tag_along']),
            source_url=url(d['source_url']), rule_url=url(d['rule_url']), method=app.text_value(d['method'], 1000, True))
        if out['tag_along'] is not None and not 0 <= out['tag_along'] <= 100: raise ValueError('Tag along deve estar entre 0 e 100%.')
    elif kind == 'issuer_exposure':
        if set(d) != {'symbol', 'usd_role', 'commodities', 'asof', 'source_url', 'note'} or not isinstance(d['usd_role'], str) or d['usd_role'] not in USD_ROLES:
            raise ValueError('Exposição da empresa inválida.')
        if not isinstance(d['commodities'], list) or len(d['commodities']) > 4 or any(not isinstance(k, str) or k not in BENCHMARKS or k == 'us_rates' for k in d['commodities']) or len(set(d['commodities'])) != len(d['commodities']):
            raise ValueError('Commodities de acompanhamento inválidas.')
        out.update(asof=past(d['asof']), source_url=url(d['source_url']), note=app.text_value(d['note'], 1000, True))
    else:
        if set(d) != {'symbol', 'observations', 'warnings', 'source_url'} or not isinstance(d['observations'], dict) or set(d['observations']) - set(DRIVER_KEYS):
            raise ValueError('Contexto de mercado inválido.')
        out['source_url'] = url(d['source_url']); out['observations'] = {}
        for key, obs in d['observations'].items():
            fields = {'current', 'previous', 'asof', 'previous_asof', 'source_url', 'source', 'unit', 'frequency'}
            if not isinstance(obs, dict) or set(obs) != fields or obs['frequency'] not in ('daily', 'monthly'):
                raise ValueError('Observação de mercado inválida.')
            record = {**obs, 'current': number(obs['current']), 'previous': number(obs['previous']), 'asof': past(obs['asof']),
                'previous_asof': past(obs['previous_asof']), 'source_url': url(obs['source_url']),
                'source': app.text_value(obs['source'], 100, True), 'unit': app.text_value(obs['unit'], 40, True)}
            if record['current'] is None or record['previous'] is None or min(record['current'], record['previous']) <= 0 or record['previous_asof'] >= record['asof']:
                raise ValueError('Valores ou datas da comparação inválidos.')
            if key in ('rates', 'usd') and (record['frequency'], record['unit']) != ('daily', '% a.a.' if key == 'rates' else 'R$/US$'):
                raise ValueError('Base da série do Banco Central inválida.')
            if key in BENCHMARKS and (record['frequency'], record['unit']) != (BENCHMARKS[key][3], BENCHMARKS[key][2]):
                raise ValueError('Base da série de referência inválida.')
            out['observations'][key] = record
        if not isinstance(d['warnings'], list) or len(d['warnings']) > 12: raise ValueError('Avisos de mercado inválidos.')
        out['warnings'] = [app.text_value(w, 500, True) for w in d['warnings']]
    return out


def _first(row, *keys):
    return next((row[k] for k in keys if row.get(k) is not None), None)


def _balance(row):
    # Parent CVM loans accounts already include their children (debentures/leases).
    pair = ('loansAndFinancing', 'longTermLoansAndFinancing') if all(row.get(k) is not None for k in ('loansAndFinancing', 'longTermLoansAndFinancing')) else ('shortLongTermDebt', 'longTermDebt')
    debt = sum(row[k] for k in pair) if all(type(row.get(k)) in (int, float) for k in pair) else None
    cash = row.get('cash')
    if cash is not None and row.get('shortTermInvestments') is not None: cash += row['shortTermInvestments']
    return {'equity': _first(row, 'shareholdersEquity', 'totalStockholderEquity'), 'debt': debt, 'cash': cash,
        'current_assets': _first(row, 'totalCurrentAssets'), 'current_liabilities': _first(row, 'currentLiabilities', 'totalCurrentLiabilities'), 'inventory': row.get('inventory')}


def fetch_statements(app, a, brapi):
    if a['asset_type'] != 'stock': raise ValueError('Demonstrações CVM se aplicam às ações brasileiras; stocks usam sua fonte internacional.')
    buckets = {'annual': {}, 'quarterly': {}}; sources = {}; warnings = []
    def read(endpoint, period):
        return brapi(app, a, endpoint, period=period, startDate=f'{app.today().year-11 if period == "annual" else app.today().year-6}-01-01', endDate=app.today().isoformat())
    requests = [(ep, period) for period in buckets for ep in ('income-statement', 'balance-sheet', *(['cash-flow'] if period == 'annual' else []))]
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [(ep, period, pool.submit(read, ep, period)) for ep, period in requests]
        for ep, period, task in tasks:
            try:
                rows, url = task.result()
                if not isinstance(rows, list) or not rows or len(rows) > 80: raise ValueError('Série indisponível na fonte ou no plano.')
                seen = set(); accepted = []
                for row in rows:
                    if not isinstance(row, dict) or row.get('type') != ('yearly' if period == 'annual' else 'quarterly') or row.get('currency', 'BRL') != 'BRL':
                        raise ValueError('Moeda ou período da fonte não confirmado.')
                    ref = app.valid_date(str(row.get('endDate') or '')[:10])
                    if ref in seen or ref > app.today().isoformat(): raise ValueError('Período duplicado ou futuro.')
                    seen.add(ref)
                    vals = _balance(row) if ep == 'balance-sheet' else {dest: row.get(src) for src, dest in BRAPI_FIELDS[ep].items()}
                    if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in vals.values()):
                        raise ValueError('Valor da demonstração inválido.')
                    accepted.append((ref, vals))
                for ref, vals in accepted: buckets[period].setdefault(ref, {'date': ref, **dict.fromkeys(FIELDS)}).update(vals)
                sources.setdefault(ep, url)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                warnings.append(ep + ' / ' + period + ': ' + (str(exc) if isinstance(exc, ValueError) else 'Formato não reconhecido.'))
    # A quarterly balance is a point-in-time statement. Its exact year-end date
    # can fill a missing annual balance; flow values are never substituted here.
    for ref, row in buckets['annual'].items():
        quarter_balance = buckets['quarterly'].get(ref, {})
        for key in BALANCE:
            if row[key] is None and quarter_balance.get(key) is not None: row[key] = quarter_balance[key]
    payload = {'symbol': a['ticker']+'.SA', 'currency': 'BRL', **{period: sorted(rows.values(), key=lambda r: r['date'])[-(11 if period == 'annual' else 28):] for period, rows in buckets.items()},
        'sources': sources, 'source_url': sources.get('income-statement') or next(iter(sources.values()), '')}
    return validate_snapshot(app, 'issuer_statements', payload), warnings


def _window(rows):
    q = rows[-4:]
    return q if len(q) == 4 and all(65 <= (date.fromisoformat(b['date']) - date.fromisoformat(a['date'])).days <= 115 for a, b in zip(q, q[1:])) else []


def derived_metrics(snapshot):
    if not snapshot: return {}
    d = snapshot['data']; rows = d['quarterly']; annual = d['annual']; out = {}
    def put(key, v, ref, definition):
        if v is not None and math.isfinite(v): out[key] = {'value': v, 'asof': ref, 'currency': d['currency'], 'definition': definition}
    def derive(row, income, previous):
        ref = row['date']; equity, debt, cash = (row[k] for k in ('equity', 'debt', 'cash'))
        def ratio(n, den): return n / den if n is not None and den is not None and den > 0 else None
        put('debt_equity', ratio(debt, equity), ref, 'Empréstimos/financiamentos circulantes + não circulantes ÷ PL; sem somar novamente subcontas de arrendamentos.')
        net = debt-cash if debt is not None and cash is not None else None
        put('net_debt_equity', ratio(net, equity), ref, 'Dívida financeira menos caixa e aplicações de curto prazo da fonte ÷ PL; conferir caixa restrito.')
        put('current_ratio', ratio(row['current_assets'], row['current_liabilities']), ref, 'Ativo circulante ÷ passivo circulante do mesmo balanço.')
        def total(k): return sum(r[k] for r in income) if income and all(r[k] is not None for r in income) else None
        revenue, net_income, ebit, ebitda = (total(k) for k in ('revenue', 'net_income', 'ebit', 'ebitda'))
        put('operating_cashflow',total('operating_cashflow'),ref,'Caixa operacional na mesma janela anual ou 4 trimestres isolados consecutivos; acumulados são isolados antes da soma.')
        if net_income is not None and net_income>0:
            put('cash_conversion',ratio(total('operating_cashflow'),net_income),ref,'Caixa operacional ÷ lucro líquido na mesma janela anual ou 12 meses.')
        put('net_debt_ebitda', ratio(net, ebitda), ref, 'Dívida líquida ÷ soma do cleanEbitda de 4 trimestres isolados (ou exercício anual). EBITDA padronizado da fonte; confira ajustes e IFRS 16.')
        for key, num in [('operating_margin', ebit), ('gross_margin', total('gross_profit'))]:
            v = ratio(num, revenue); put(key, v*100 if v is not None else None, ref, 'Resultado ÷ receita em 12 meses, períodos isolados e consecutivos.')
        interest = total('interest_expense')
        put('interest_coverage', ratio(ebit, abs(interest) if interest is not None else None), ref, 'EBIT ÷ despesa de juros explícita em 12 meses; resultado financeiro líquido não substitui juros.')
        if previous and previous['equity'] is not None and equity is not None and min(equity, previous['equity']) > 0:
            roe = ratio(net_income, (equity+previous['equity'])/2)
            put('roe', roe*100 if roe is not None else None, ref, 'Lucro consolidado de 12 meses ÷ média do PL consolidado atual e 12 meses antes; inclui minoritários na base divulgada.')
        cogs = total('cost_of_revenue')
        if previous and previous['inventory'] is not None and row['inventory'] is not None and min(previous['inventory'], row['inventory']) >= 0:
            put('inventory_days', ratio((previous['inventory']+row['inventory'])/2*365, abs(cogs) if cogs is not None else None), ref, 'Estoque médio atual/12 meses antes ÷ custo da receita em 12 meses × 365; conferir sazonalidade.')
    # Annual flow values are never relabelled as a recent quarterly TTM.
    for i, row in enumerate(annual):
        previous = next((r for r in annual[:i] if r['date'] == str(int(row['date'][:4])-1)+row['date'][4:]), None)
        derive(row, [row], previous)
        for key in ('operating_cashflow', 'free_cashflow'):
            put(key, row[key], row['date'], 'Exercício anual da DFC; caixa livre da brapi = caixa operacional + todo o caixa de investimento, incluindo aquisições/desinvestimentos.')
        if row['net_income'] is not None and row['net_income'] > 0 and row['operating_cashflow'] is not None:
            put('cash_conversion', row['operating_cashflow']/row['net_income'], row['date'], 'Caixa operacional ÷ lucro líquido do mesmo exercício anual.')
    if rows:
        latest = rows[-1]; previous = next((r for r in rows if r['date'] == str(int(latest['date'][:4])-1)+latest['date'][4:]), None)
        derive(latest, _window(rows), previous)
    return out


def fetch_governance(app, a, company_profile):
    if a['asset_type'] != 'stock': raise ValueError('Governança B3 se aplica às ações brasileiras.')
    def read(route, **params):
        encoded = base64.b64encode(json.dumps({'language': 'pt-br', **params}, separators=(',', ':')).encode()).decode()
        url = B3_API+route+'/'+encoded
        raw = app.request_json(url)
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except (ValueError, TypeError): raise ValueError('Cadastro B3 com formato não reconhecido.') from None
        if not isinstance(raw, dict): raise ValueError('Cadastro B3 sem objeto de empresa.')
        return raw, url
    search, _ = read('GetInitialCompanies', pageNumber=1, pageSize=100, company=a['ticker'][:4])
    if not isinstance(search.get('results'), list) or any(not isinstance(r, dict) for r in search['results']):
        raise ValueError('Busca B3 sem lista de emissores válida.')
    matches = [r for r in search['results'] if r.get('issuingCompany') == a['ticker'][:4] and r.get('status') == 'A']
    if len(matches) != 1: raise ValueError('Emissor não identificado de forma única na B3.')
    listed = matches[0]
    detail, url = read('GetDetail', codeCVM=listed['codeCVM'])
    if not isinstance(detail.get('otherCodes', []), list) or any(not isinstance(r, dict) for r in detail.get('otherCodes', [])):
        raise ValueError('B3 sem lista de classes válida.')
    codes = {r.get('code') for r in detail.get('otherCodes', [])} | {detail.get('code')}
    cnpj = lambda v: re.sub(r'\D', '', v or '').zfill(14)
    expected = company_profile.get('cnpj') or listed.get('cnpj')
    if not expected or a['ticker'] not in codes or detail.get('issuingCompany') != a['ticker'][:4] or cnpj(detail.get('cnpj')) != cnpj(expected):
        raise ValueError('Ticker ou CNPJ divergente entre cadastro e B3.')
    segment = detail.get('market') or ''; normal = sector_analysis.fold(segment)
    tag_along = 100 if normal == 'novo mercado' and a['ticker'].endswith('3') or normal in ('nivel 2', 'n2') and re.fullmatch(r'[A-Z]{4}[345678]', a['ticker']) else None
    first = None
    try:
        candidate = datetime.strptime(listed.get('dateListing', ''), '%d/%m/%Y').date()
        if candidate <= app.today(): first = candidate.isoformat()
    except (ValueError, TypeError): pass
    return validate_snapshot(app, 'issuer_governance', {'symbol': a['ticker']+'.SA', 'segment': segment, 'tag_along': tag_along,
        'asof': app.today().isoformat(), 'first_listed': first, 'source_url': url, 'rule_url': B3_RULE,
        'method': 'Ticker e CNPJ conferidos no cadastro B3. 100% inferido apenas para classe elegível no Novo Mercado/Nível 2 pela regra do segmento; outras classes/units exigem conferir o estatuto.'})


def annual_evidence(a):
    """Merge dated annual evidence without losing field provenance or manual corrections."""
    snaps = a.get('snapshots', {})
    by_date = {}
    annual_sources = [(snaps.get('issuer_financials', {}), 'years'), (snaps.get('issuer_statements', {}), 'annual')]
    for snap, bucket in sorted(annual_sources, key=lambda pair: pair[0].get('retrieved_at', '')):
        for r in snap.get('data', {}).get(bucket, []):
            row = by_date.setdefault(r['date'], {'date': r['date'], '_sources': {}})
            for key, value in r.items():
                if key == 'date' or value is None: continue
                row[key] = value
                endpoint = 'cash-flow' if key in ('operating_cashflow', 'free_cashflow') else 'income-statement'
                row['_sources'][key] = snap.get('data', {}).get('sources', {}).get(endpoint) or snap.get('data', {}).get('source_url', '')
    return sorted(by_date.values(), key=lambda r: r['date'])


def viability(app, a):
    snaps = a.get('snapshots', {}); d = snaps.get('issuer_statements', {}).get('data', {})
    annual = annual_evidence(a)
    annual_sources = [(snaps.get('issuer_financials', {}), 'years'), (snaps.get('issuer_statements', {}), 'annual')]
    profile = a['sector_analysis']['profile']; checks = []
    def add(key, label, status, detail, source='', asof=None):
        checks.append(dict(key=key, label=label, status=status, detail=detail, source_url=source, asof=asof))
    required = list(range(app.today().year-10, app.today().year)); years = {int(r['date'][:4]): r for r in annual}
    profit = [years[y]['net_income'] for y in required if y in years and years[y].get('net_income') is not None]
    profit_source = next((s.get('data', {}).get('source_url') for s,bucket in sorted(annual_sources, key=lambda pair: pair[0].get('retrieved_at', ''), reverse=True) if any(r.get('net_income') is not None for r in s.get('data', {}).get(bucket,[]))), '')
    failing = [str(y) for y in required if years.get(y, {}).get('net_income') is not None and years[y]['net_income'] <= 0]
    add('profit10', 'Lucros consistentes por 10 anos', 'fail' if failing else 'pass' if len(profit) == 10 else 'unknown',
        f'{len(profit)} de 10 exercícios com lucro informado ({required[0]}–{required[-1]}). Exige lucro positivo em cada ano.'+(' Lucro não positivo em '+', '.join(failing)+'.' if failing else ''), profit_source)
    if profile in sector_analysis.NONFINANCIAL_PROFILES:
        # The asset carries the user's configured sector cut in its health check.
        cut = next((c['limit'] for c in a['sector_analysis']['checks'] if c['metric'] == 'net_debt_ebitda'), None)
        cut = cut if cut is not None else sector_analysis.PROFILES[profile]['limits'].get('net_debt_ebitda', 3)
        observed = []
        for y in range(app.today().year-5, app.today().year):
            row = years.get(y, {}); debt, cash, ebitda = (row.get(k) for k in ('debt', 'cash', 'ebitda'))
            if all(v is not None for v in (debt, cash, ebitda)) and debt >= 0 and cash >= 0 and ebitda > 0:
                observed.append((y, (debt-cash)/ebitda))
        cut_label = format(cut, 'g').replace('.', ',')
        add('leverage5', f'Dívida líquida/EBITDA até {cut_label}× por 5 anos', 'fail' if any(v > cut for _, v in observed) else 'pass' if len(observed) == 5 else 'unknown',
            f'{len(observed)} de 5 exercícios comparáveis. '+('; '.join(f'{y}: {v:.2f}×' for y, v in observed) or 'Balanço e EBITDA anual ainda incompletos.')+' Corte do perfil setorial, editável; EBITDA padronizado da fonte, conferir arrendamentos e ajustes.', d.get('source_url', ''))
    gov = snaps.get('issuer_governance', {}).get('data', {}); pct = gov.get('tag_along')
    applicable = a['asset_type'] == 'stock'; fresh = gov and app.age(gov['asof']) <= 365
    add('tag_along', 'Tag along de 100% nesta classe de ação', 'na' if not applicable else ('pass' if pct == 100 else 'fail') if fresh and pct is not None else 'unknown',
        'Direito da classe na B3; não se aplica automaticamente a ações no exterior.' if not applicable else
        (f'{pct:g}% · {gov.get("segment", "")}. '+gov['method'] if fresh and pct is not None else 'Consulte o segmento B3 ou confirme o direito desta classe no estatuto; nenhum percentual presumido pelo final do ticker.'), gov.get('source_url', ''), gov.get('asof'))
    health = [c for c in a['sector_analysis']['checks'] if c['group'] == 'health']
    count = {s: sum(c['status'] == s for c in health) for s in ('pass', 'fail', 'unknown')}
    add('sector_health', 'Saúde financeira nos critérios do setor', 'fail' if count['fail'] else 'unknown' if count['unknown'] or not health else 'pass',
        f'{a["sector_analysis"]["label"]}: {count["pass"]} atendem, {count["fail"]} a revisar, {count["unknown"]} pendentes. Financeiras usam capital, crédito e solvência; perenidade do setor não garante viabilidade.')
    counts = {s: sum(c['status'] == s for c in checks) for s in ('pass', 'fail', 'unknown', 'na')}
    status = 'review' if counts['fail'] else 'incomplete' if counts['unknown'] else 'within'
    labels = {'within': 'Dentro dos critérios de estudo', 'review': 'Pontos de atenção', 'incomplete': 'Avaliação incompleta'}
    return {'status': status, 'label': labels[status], 'checks': checks, 'counts': counts,
        'coverage': f'{counts["pass"]+counts["fail"]} de {len(checks)-counts["na"]} critérios com dados suficientes',
        'note': 'Classificação própria do aplicativo, baseada nos critérios acima. Não certifica a empresa nem determina se a cotação compensa. Um critério reprovado prevalece; pendências impedem o selo positivo.'}


def complete_study(app, a):
    """One explainable checklist; price, news and operational monitoring keep their scope."""
    r = a['company_research']; profile = a['sector_analysis']['profile']
    nonfinancial = profile in sector_analysis.NONFINANCIAL_PROFILES
    groups = {k: {'key': k, 'label': label, 'checks': []} for k, label in [
        ('requested', 'Os 11 critérios adicionais de longo prazo'),
        ('history', 'Histórico e crescimento'), ('returns', 'Rentabilidade e geração de caixa'),
        ('income', 'Dividendos e negociação'), ('governance', 'Governança e proteção do acionista'),
        ('sector', 'Saúde financeira · '+a['sector_analysis']['label']), ('price', 'Preço e custo de oportunidade')]}
    def add(group, check): groups[group]['checks'].append(dict(check))
    for check in r.get('requested_quality', {}).get('checks', []):
        add('requested', check)
    for check in r['buy_hold']['checks']:
        key = check['key']
        group = 'income' if key in ('dividends', 'liquidity') else 'returns' if key == 'roe' else 'sector' if key == 'debt_equity' else 'history'
        item = dict(check)
        if key == 'debt_equity' and not nonfinancial:
            item.update(status='na', detail='Dívida faz parte da operação financeira. Use capital, crédito e solvência nos critérios próprios abaixo.')
        add(group, item)
    for check in r['viability']['checks']:
        if check['key'] != 'sector_health': add('governance' if check['key'] == 'tag_along' else 'sector' if check['key'] == 'leverage5' else 'history', check)
    for check in a['sector_analysis']['checks']:
        if check['group'] == 'health' and check['metric'] == 'roe': continue
        references = check.get('references', [])
        urls = [ref.get('url') for ref in references if ref.get('url')]
        _, evidence, _ = sector_analysis.metric(a, check['metric'], app.age)
        if evidence.get('url'): urls.insert(0, evidence['url'])
        value = check['value']; limit = check['limit']
        observed = f'Valor: {value:g} {check["unit"]}. ' if value is not None else ''
        if limit is not None: observed += f'Referência de comparação: {limit:g} {check["unit"]}. '
        dates = [ref['asof'] for ref in references if ref.get('asof')]
        add('sector' if check['group'] == 'health' else 'price', {
            'key': 'sector_'+check['metric']+'_'+check['group'], 'label': check['label'], 'status': check['status'],
            'detail': observed+check['reason']+' '+check.get('note', '')+' '+
                ' '.join('Fonte: '+ref['source']+'.' for ref in references if ref.get('source')), 'source_url': urls[0] if urls else '',
            'asof': min(dates) if dates else None})
    def authored(group, key, label, status, detail, row=None, field=None):
        row = row or {}
        add(group, dict(key=key, label=label, status=status, detail=detail,
            asof=row.get('date'), source_url=row.get('_sources', {}).get(field, '')))
    years = {int(row['date'][:4]): row for row in annual_evidence(a)}
    required = range(app.today().year-5, app.today().year); latest = years.get(app.today().year-1, {})
    if nonfinancial:
        cash = [years[y]['operating_cashflow'] for y in required if years.get(y, {}).get('operating_cashflow') is not None]
        authored('returns', 'cash5', 'Caixa operacional positivo em cada um dos últimos 5 anos',
            'fail' if any(v <= 0 for v in cash) else 'pass' if len(cash) == 5 else 'unknown',
            f'{len(cash)} de 5 exercícios completos com fluxo informado. Corte de estudo: caixa operacional > 0 em cada ano. Confira capital de giro, sazonalidade e aquisições.', latest, 'operating_cashflow')
        fcf = latest.get('free_cashflow')
        authored('returns', 'free_cash_last', 'Caixa livre positivo no último exercício completo',
            'unknown' if fcf is None else 'pass' if fcf > 0 else 'fail',
            f'Exercício esperado: {app.today().year-1}. '+(f'Caixa livre: {fcf:g}. ' if fcf is not None else 'Fluxo anual ainda ausente. ')+
            'Corte de estudo: > 0. Valor negativo também pode refletir expansão ou aquisições; leia o fluxo de investimento antes de concluir.', latest, 'free_cashflow')
        ocf, profit = latest.get('operating_cashflow'), latest.get('net_income')
        conversion = ocf/profit if ocf is not None and profit is not None and profit > 0 else None
        authored('returns', 'cash_profit', 'Caixa operacional cobre o lucro do último exercício',
            'unknown' if conversion is None else 'pass' if conversion >= 1 else 'fail',
            (f'Caixa operacional/lucro: {conversion:.2f}×. ' if conversion is not None else 'Exige caixa e lucro positivo no mesmo exercício. ')+
            'Referência de estudo: ≥ 1×. Capital de giro pode deslocar caixa entre anos; este corte não prova qualidade ou fraude contábil.', latest, 'operating_cashflow')
        v, snap, reason = sector_analysis.metric(a, 'operating_margin', app.age)
        authored('returns', 'operating_margin_positive', 'Margem operacional positiva na referência recente',
            'unknown' if v is None else 'pass' if v > 0 else 'fail',
            (f'Margem operacional: {v:g}%. ' if v is not None else reason+' ')+
            'Corte de estudo: > 0. Confira itens extraordinários, mix e ciclo. Não há uma margem mínima universal para setores.',
            {'date': snap.get('asof'), '_sources': {'operating_margin': snap.get('url') or snap.get('data', {}).get('source_url', '')}}, 'operating_margin')
    payout, snap, reason = sector_analysis.metric(a, 'payout', app.age)
    authored('income', 'payout_covered', 'Proventos cobertos pelo lucro na mesma janela',
        'unknown' if payout is None or payout < 0 else 'pass' if payout <= 100 else 'fail',
        (f'Payout informado: {payout:g}%. ' if payout is not None else reason+' ')+
        'Corte de estudo: entre 0% e 100%, com lucro positivo e proventos na mesma janela. Confira reservas, pagamentos extraordinários e caixa; payout baixo não comprova bons dividendos.',
        {'date': snap.get('asof'), '_sources': {'payout': snap.get('url') or snap.get('data', {}).get('source_url', '')}}, 'payout')
    quality = [c for key, g in groups.items() if key != 'price' for c in g['checks']]
    def counts(rows): return {s: sum(c['status'] == s for c in rows) for s in ('pass', 'fail', 'unknown', 'na')}
    measured = counts(quality); price = counts(groups['price']['checks'])
    status = 'review' if measured['fail'] else 'incomplete' if measured['unknown'] else 'within'
    return {'groups': list(groups.values()), 'counts': measured, 'price_counts': price,
        'total': len(quality)-measured['na'], 'status': status,
        'coverage': f'{measured["pass"]+measured["fail"]} de {len(quality)-measured["na"]} critérios da empresa com dados',
        'summary': f'{measured["pass"]} atendem · {measured["fail"]} a revisar · {measured["unknown"]} pendentes',
        'label': {'within':'Dentro dos critérios de estudo','review':'Pontos de atenção','incomplete':'Avaliação incompleta'}[status],
        'note': 'Checklist próprio inspirado no estudo buy and hold, acrescido de critérios do setor e caixa. A contagem mostra cobertura, sem pesos ou nota de confiança. Preço e custo de oportunidade são avaliados à parte. Notícias e opiniões ajudam a investigar riscos e não aprovam critérios contábeis.'}


def focus(a, age):
    result = []
    for key, title, reading in SECTOR_FOCUS.get(a['sector_analysis']['profile'], SECTOR_FOCUS['general']):
        v, snap, reason = sector_analysis.metric(a, key, age)
        where, sources = sector_analysis.indicator_source(key)
        result.append({'metric': key, 'title': title, 'reading': reading, 'value': v, 'unit': sector_analysis.METRICS[key][1],
            'asof': snap.get('asof'), 'source': snap.get('source'), 'reason': reason, 'where': where, 'sources': sources})
    return result


def news_context(app, a, reports, sentiments):
    """Surface the existing news research without treating a sector headline as an issuer fact."""
    profile = a['sector_analysis']['profile']
    if a['asset_type'] not in ('stock','fii'):
        return {'available': False, 'sections': [], 'themes': [],
            'note': 'Consulte notícias e relatórios do mercado de listagem desta empresa. A cobertura brasileira de mercado e setor não é aplicada a este stock.'}
    clock = datetime.fromisoformat(app.now()).astimezone(timezone.utc)
    sections = []; all_items = []
    for key in dict.fromkeys((profile, 'general')):
        report = reports.get(key, {}); items = []; seen = set()
        for item in report.get('headlines', []):
            try:
                stamp = datetime.fromisoformat(item['published_at'])
                if stamp.tzinfo is None or not timedelta(0) <= clock-stamp.astimezone(timezone.utc) <= timedelta(days=7): continue
            except (KeyError, TypeError, ValueError): continue
            if item['url'] in seen: continue
            seen.add(item['url']); items.append(dict(item))
        items.sort(key=lambda item: item['published_at'], reverse=True)
        items = items[:8]; all_items.extend(items)
        sentiment = sentiments.get(key)
        if sentiment:
            sentiment = dict(sentiment)
            sentiment['stale'] = bool(sentiment.get('stale') or not items or app.age(report.get('retrieved_at', '')) > 1)
        sections.append({'profile': key, 'label': sector_analysis.PROFILES[key]['label'] if key != 'general' else 'Mercado brasileiro',
            'items': items, 'retrieved_at': report.get('retrieved_at'), 'stale': app.age(report.get('retrieved_at', '')) > 1,
            'sentiment': sentiment, 'errors': report.get('errors', [])})
    all_items = list({item['url']: item for item in all_items}.values())
    if a['asset_type']=='fii':
        import fii_research
        fii_type=fii_research.subtype(a)
        focus_keys=list(fii_research.FOCUS[fii_type])
    else:focus_keys = [row[0] for row in SECTOR_FOCUS.get(profile, SECTOR_FOCUS['general'])]
    relevant = set(focus_keys) | {check['metric'] for check in a['sector_analysis']['checks']}
    themes = []
    for key, label, words, metrics, reading in [
        ('rates', 'Juros e financiamento', ('juros', 'selic', 'copom'),
         ('npl90', 'coverage', 'basel') if profile == 'bank' else ('interest_coverage', 'net_debt_ebitda', 'roic'),
         'Compare custo de captação, indexadores e vencimentos. Mudança na taxa básica não é a mesma mudança em toda a curva.'),
        ('usd', 'Dólar e comércio exterior', ('dolar', 'cambio', 'exporta', 'importa'),
         ('gross_margin', 'operating_margin'), 'Confira receitas, insumos e dívida em moeda estrangeira, contratos e hedge.'),
        ('commodities', 'Commodities e produção', ('petroleo', 'minerio', 'cobre', 'soja', 'safra', 'aco'),
         ('gross_margin', 'production_growth', 'free_cashflow'), 'Compare volume, preço realizado e custo unitário. Produtores e consumidores podem sentir efeitos opostos.'),
        ('credit', 'Crédito e inadimplência', ('credito', 'inadimpl', 'provis'),
         ('npl90', 'coverage', 'basel') if profile == 'bank' else ('receivable_days', 'current_ratio', 'operating_cashflow'),
         'Confronte qualidade do crédito, recebíveis, provisões e necessidade de capital de giro.'),
        ('regulation', 'Regulação e contratos', ('tarifa', 'concess', 'regula', 'anatel', 'aneel'),
         ('contracted_revenue', 'free_cashflow') if profile == 'utility' else ('operating_margin', 'free_cashflow'),
         'Leia o ato ou contrato original e confira vigência, reajustes, obrigações de investimento e a exposição da empresa.'),
        ('demand', 'Demanda e atividade', ('consumo', 'vendas', 'demanda', 'producao', 'pib'),
         tuple(row[0] for row in SECTOR_FOCUS.get(profile, SECTOR_FOCUS['general'])[:3]),
         'Compare volume, preços, capacidade e margens da empresa com o período anterior; crescimento do setor não garante ganho de participação.'),
        ('geopolitics', 'Geopolítica e risco de mercado', ('guerra', 'conflito', 'geopolit', 'sancoes'),
         ('gross_margin', 'free_cashflow'), 'Confira países, energia, rotas, fornecedores e moeda dos contratos. Não conclua o impacto individual pela manchete.')]:
        # Match complete words or explicit word stems: "aço" must not match "espaço".
        stems = {'dolar', 'exporta', 'importa', 'inadimpl', 'provis', 'concess', 'regula', 'geopolit'}
        matching = [item for item in all_items if any(re.search(r'\b'+re.escape(word)+(r'\w*' if word in stems else 's?')+r'\b',
            sector_analysis.fold(item['title'])) for word in words)]
        if matching:
            if profile=='fii':
                metrics={'rates':('fund_leverage','distribution_cover','credit_delinquency','short_contracts'),
                         'credit':('credit_delinquency','top_credit','ltv','rental_delinquency','top_tenant','distribution_cover'),
                         'demand':('vacancy','financial_vacancy','rental_delinquency','credit_delinquency','distribution_cover'),
                         'regulation':('short_contracts','ltv','top_tenant','fund_leverage','distribution_cover')}.get(key,
                         ('rental_delinquency','credit_delinquency','distribution_cover','fund_leverage'))
                reading={'rates':'Confira custo das obrigações, curva longa, reajustes de contratos e prêmio exigido. Em papel, CDI maior pode elevar receita nominal, enquanto crédito e preço da cota precisam de revisão.',
                         'credit':('Confira atrasos de aluguéis, renegociações, capacidade de pagamento dos locatários e concentração dos contratos.' if fii_type=='tijolo' else
                                   'Confira risco e concentração dos fundos investidos e a qualidade do crédito de suas carteiras.' if fii_type=='fof' else
                                   'Confira atrasos dos devedores finais, garantias, provisões e concentração. Securitizadora não identifica sozinha o risco do crédito.'),
                         'demand':('Compare ocupação, receita dos imóveis, renovação de contratos e capacidade de pagamento dos locatários.' if fii_type=='tijolo' else
                                   'Confira atividade e capacidade de pagamento dos devedores, qualidade dos recebíveis e resultados dos fundos investidos; conforme o perfil da carteira.'),
                         'regulation':'Confira os contratos, regulamento e atos oficiais; leia as regras aplicáveis ao segmento do fundo.'}.get(key,'Confira a exposição dos locatários, devedores, custos de construção e contratos; a manchete não demonstra impacto uniforme no FII.')
            if profile in ('bank', 'insurance', 'financial_services'):
                metrics = ('basel', 'npl90', 'coverage', 'roe') if profile == 'bank' else ('solvency', 'combined_ratio', 'roe') if profile == 'insurance' else ('roe', 'recurring_revenue', 'payout')
                if key == 'commodities': reading = 'Confira a exposição da carteira e dos clientes ao ciclo de commodities. O preço de referência não demonstra ganho ou perda nesta instituição.'
                if key == 'usd': reading = 'Confira posições cambiais, receitas internacionais, investimentos e a exposição dos clientes; considere proteção e capital regulatório.'
                if key == 'credit' and profile != 'bank': reading = 'Confira risco de crédito dos investimentos e contrapartes, perdas e capital. Não aplique os indicadores de inadimplência bancária a outro modelo de negócio.'
            metrics = tuple(metric for metric in metrics if metric in relevant) or tuple(focus_keys[:3])
            themes.append({'key': key, 'label': label, 'reading': reading, 'items': matching[:3],
                'metrics': [{'key': metric, 'label': sector_analysis.METRICS[metric][0]} for metric in metrics]})
    return {'available': True, 'sections': sections, 'themes': themes,
        'note': 'Temas identificados nos títulos dos últimos 7 dias, sem leitura integral dos artigos. São pistas para conferir a empresa, sem causalidade ou direção de preço demonstrada. Sentimento de mercado/setor não é avaliação de confiabilidade da companhia e não altera o checklist.'}


def request_text(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'AporteBrasil/1.0 (public financial research)'})
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000: raise ValueError('Série pública excede o limite de consulta.')
        return data.decode('utf-8-sig')
    except (OSError, UnicodeError) as exc: raise ValueError('Série pública indisponível; última observação preservada.') from exc


def fred_observation(key, day):
    label, series, unit, frequency, source = BENCHMARKS[key]
    url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?'+urllib.parse.urlencode({'id': series, 'cosd': (day-timedelta(days=365)).isoformat(), 'coed': day.isoformat()})
    rows = csv.DictReader(io.StringIO(request_text(url)))
    if rows.fieldnames != ['observation_date', series]: raise ValueError('Identidade da série FRED não confirmada.')
    points = {}
    for r in rows:
        try: ref = date.fromisoformat(r['observation_date']); v = float(r[series])
        except (ValueError, TypeError, KeyError): continue
        if day-timedelta(days=365) <= ref <= day and v > 0 and math.isfinite(v):
            # Monthly averages must represent a completed month, not a daily quote.
            if frequency == 'monthly' and (ref.year, ref.month) >= (day.year, day.month): continue
            points[ref] = v
    if len(points) < 2: raise ValueError('Faltam duas observações para comparar a série.')
    latest = max(points)
    older = [r for r in points if r < latest and (frequency == 'monthly' or r <= latest-timedelta(days=30))]
    if not older: raise ValueError('Falta ponto anterior para comparação de 30 dias.')
    previous = max(older)
    return {'current': points[latest], 'previous': points[previous], 'asof': latest.isoformat(), 'previous_asof': previous.isoformat(),
        'unit': unit, 'frequency': frequency, 'source': source+' · '+series, 'source_url': 'https://fred.stlouisfed.org/series/'+series}


def suggested_commodities(a):
    profile = a['sector_analysis']['profile']
    if profile == 'metals': return ['iron', 'copper', 'brent']
    if profile == 'commodity': return ['brent']
    if profile == 'food_agro': return ['soy', 'brent']
    if profile in ('industrial', 'transport', 'retail'): return ['brent']
    return []


def fetch_drivers(app, a):
    old = a.get('snapshots', {}).get('issuer_drivers', {}).get('data', {}); observations = dict(old.get('observations', {})); warnings = []
    context = market_outlook.fetch_context(app.request_json, app.today(), app.now())
    warnings.extend(context['errors'])
    for k, o in context['observations'].items():
        observations[k] = {key: o[key] for key in ('current', 'previous', 'asof', 'previous_asof', 'source', 'source_url')}
        observations[k].update(unit='% a.a.' if k == 'rates' else 'R$/US$', frequency='daily')
    exposure = a.get('snapshots', {}).get('issuer_exposure', {}).get('data', {})
    keys = exposure.get('commodities', suggested_commodities(a))
    if a['asset_type'] in ('foreign', 'global_stock'): keys = keys+['us_rates']
    # Keep observations only for the selected benchmarks, including failures preserved above.
    observations = {k: v for k, v in observations.items() if k in ('rates', 'usd', *keys)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [(key, pool.submit(fred_observation, key, app.today())) for key in keys]
        for key, task in tasks:
            try: observations[key] = task.result()
            except ValueError as exc: warnings.append(BENCHMARKS[key][0]+': '+str(exc))
    return validate_snapshot(app, 'issuer_drivers', {'symbol': a['ticker']+('.SA' if a['asset_type'] == 'stock' else ''),
        'observations': observations, 'warnings': warnings, 'source_url': 'https://www.bcb.gov.br/estabilidadefinanceira/selic'})


def drivers(app, a):
    snaps = a.get('snapshots', {}); snapshot = snaps.get('issuer_drivers'); exposure = snaps.get('issuer_exposure', {}).get('data', {})
    observations = snapshot.get('data', {}).get('observations', {}) if snapshot else {}; rows = []
    keys = ['rates', 'usd'] + exposure.get('commodities', suggested_commodities(a))
    if a['asset_type'] in ('foreign', 'global_stock'): keys.append('us_rates')
    for key in keys:
        obs = observations.get(key); fresh = bool(obs) and app.age(obs['asof']) <= (100 if obs['frequency'] == 'monthly' else 7)
        label = {'rates': 'Selic meta', 'usd': 'Dólar PTAX'}.get(key) or BENCHMARKS[key][0]
        channel_key = 'rates' if key == 'us_rates' else key
        diff = obs['current']-obs['previous'] if obs else None
        change = diff/obs['previous']*100 if obs else None
        direction = 'unknown' if not fresh else 'up' if change > .01 else 'down' if change < -.01 else 'flat'
        if channel_key in ('rates', 'usd'):
            scenario_direction = direction if direction in ('up', 'down') else 'up'
            _, explanation = market_outlook.channel(a['sector_analysis']['profile'], channel_key, scenario_direction)
            if key == 'rates' and a['asset_type'] == 'stock':
                profile = a['sector_analysis']['profile']
                if profile in ('metals', 'commodity'):
                    explanation = ('Juros menores podem aliviar o custo da dívida em reais e o retorno exigido nos projetos.' if direction == 'down' else 'Juros maiores podem elevar o custo da dívida em reais e o retorno exigido nos projetos.')+' A demanda e a dívida em dólar também dependem dos juros externos, do câmbio e do ciclo da commodity.'
                elif profile == 'bank':
                    explanation = 'Juros alteram rendimentos dos empréstimos e o custo de captação em ritmos diferentes. Confira margem financeira, demanda por crédito, inadimplência e provisões; a direção do lucro depende da carteira.'
                elif profile == 'insurance':
                    explanation = 'Juros mudam a renda dos investimentos e o valor de ativos e passivos de longo prazo. Confira duration, reservas, sinistralidade e reinvestimento; a renda financeira e a marcação a mercado podem reagir em sentidos diferentes.'
            if key == 'rates' and a['asset_type'] != 'stock': explanation = 'Selic afeta custo de oportunidade em reais e o câmbio. A taxa local do país e a curva de juros da empresa precisam de análise própria.'
            if key == 'us_rates': explanation = 'Juros nos EUA afetam crédito em dólar, demanda, câmbio e desconto dos fluxos. A taxa efetiva não representa a curva futura nem substitui os juros do país da empresa.'
            role = exposure.get('usd_role', 'mixed') if app.age(exposure.get('asof', '')) <= 365 else 'mixed'
            if key == 'usd' and role != 'mixed':
                explanation = {'exporter': 'Dólar maior pode elevar receitas de exportação em reais, se preços e volumes externos forem mantidos. Insumos, frete, dívida em moeda estrangeira e hedge podem compensar.',
                    'importer': 'Dólar maior pode encarecer insumos e importações. Estoques, contratos, repasse de preços e hedge podem amortecer o efeito.',
                    'debt': 'Dólar maior pode elevar dívida e serviço da dívida em reais. Receita em dólar, prazo e hedge podem reduzir a exposição líquida.',
                    'neutral': 'A exposição líquida foi informada como reduzida/protegida. Confira prazo e efetividade dos hedges; a proteção pode mudar.'}[role]
                if direction == 'down':
                    explanation = {'exporter': 'Dólar menor pode reduzir receitas de exportação em reais, se preços e volumes externos forem mantidos. Insumos, frete, dívida em moeda estrangeira e hedge podem compensar.',
                        'importer': 'Dólar menor pode baratear insumos e importações. Estoques, contratos, repasse de preços e hedge podem alterar o prazo do efeito.',
                        'debt': 'Dólar menor pode reduzir dívida e serviço da dívida em reais. Receita em dólar, prazo e hedge podem compensar.',
                        'neutral': explanation}[role]
        else:
            explanation = f'{label} mais caro pode beneficiar produtores e elevar custos de consumidores desse insumo. Uma queda pode inverter os canais. Volume, qualidade, contratos, frete, câmbio e hedge determinam o efeito na empresa.'
            if direction == 'down': explanation = f'{label} mais barato pode pressionar a receita de produtores e aliviar custos de consumidores desse insumo. Volume, qualidade, contratos, frete, câmbio e hedge determinam o efeito na empresa.'
            if key == 'brent' and a['sector_analysis']['profile'] in ('retail','transport','industrial','food_agro','utility'):
                explanation = ('Petróleo mais barato pode aliviar combustível, frete e alguns custos de produção.' if direction == 'down' else 'Petróleo mais caro pode pressionar combustível, frete e alguns custos de produção.')+' O vínculo depende da operação, dos contratos, do repasse de preços e do câmbio; o Brent não é o preço final pago pela empresa.'
        rows.append({'key': key, 'label': label, 'observation': obs, 'fresh': fresh, 'direction': direction,
            'change': change, 'difference': diff, 'explanation': explanation,
            'basis': 'Exposição informada com fonte' if exposure else 'Fator sugerido pelo setor; confirme o vínculo com a empresa'})
    return {'rows': rows, 'warnings': snapshot.get('data', {}).get('warnings', []) if snapshot else [],
        'exposure': exposure, 'usd_roles': USD_ROLES, 'benchmarks': {k: v[0] for k, v in BENCHMARKS.items() if k != 'us_rates'},
        'note': 'Observações históricas e canais condicionais de impacto. Não projetam lucro, cotação ou recomendação de compra. Commodities mensais são médias de referência e podem ter atraso na divulgação.'}
