"""Explainable company model: accounting evidence, residual value and operating stress.

No learned probability of a price rise or survival is produced. Scenarios are
user assumptions; missing inputs stay missing and financial firms use their own
prudential checks instead of an industrial debt/EBIT model.
"""
from datetime import date
import math
import re

import sector_analysis
import stock_fundamentals
KINDS = ('issuer_model_assumptions',)
DEFAULTS = dict(cost_of_equity=None, long_growth=3.0, sustainable_roe=None,
                revenue_shock=-20.0, variable_cost_share=70.0,
                rate_shock=3.0, floating_debt_share=50.0)
BOUNDS = dict(cost_of_equity=(1, 60), long_growth=(0, 15), sustainable_roe=(-100, 100),
              revenue_shock=(-80, 0), variable_cost_share=(0, 100),
              rate_shock=(0, 30), floating_debt_share=(0, 100))
REFERENCES = [
    {'title': 'Damodaran · P/VP, ROE e crescimento', 'url': 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/pbv.html'},
    {'title': 'Damodaran · cenários e dificuldade financeira', 'url': 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/distresspaper.htm'},
    {'title': 'AQR · Quality Minus Junk', 'url': 'https://www.aqr.com/-/media/AQR/Documents/Insights/Working-Papers/Quality-Minus-Junk.pdf'},
]
FINANCIAL = ('bank', 'insurance', 'financial_services')


def finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def parameters(p):
    if not isinstance(p, dict) or set(p) != set(DEFAULTS):
        raise ValueError('Informe todas as premissas do modelo da empresa.')
    out = {}
    for key, (low, high) in BOUNDS.items():
        v = p[key]
        if v is None and key in ('cost_of_equity', 'sustainable_roe'):
            out[key] = None
        elif not finite(v) or not low <= v <= high:
            raise ValueError('Premissa fora da faixa permitida: '+key+'.')
        else:
            out[key] = float(v)
    if out['cost_of_equity'] is not None and out['long_growth'] >= out['cost_of_equity']:
        raise ValueError('Crescimento de longo prazo deve ser menor que o retorno exigido.')
    return out


def validate_snapshot(app, d):
    if (not isinstance(d, dict) or set(d) != {'symbol', 'asof', 'parameters'}
            or not isinstance(d['symbol'], str) or not re.fullmatch(r'[A-Z0-9.^-]{1,24}', d['symbol'])):
        raise ValueError('Premissas da empresa inválidas.')
    ref = app.valid_date(d['asof'])
    if ref > app.today().isoformat():
        raise ValueError('Premissas com data futura.')
    return dict(symbol=d['symbol'], asof=ref, parameters=parameters(d['parameters']))


def records(a):
    """Exact date/currency joins. Annual and international TTM stay separate."""
    snaps = a.get('snapshots', {})
    merged = {}
    candidates = [('issuer_financials', 'years'), ('issuer_statements', 'annual')]
    for kind, bucket in sorted(candidates, key=lambda item: snaps.get(item[0], {}).get('retrieved_at', '')):
        snap = snaps.get(kind, {}); d = snap.get('data', {})
        for row in d.get(bucket, []):
            key = row['date'], d['currency']
            target = merged.setdefault(key, dict(date=key[0], currency=key[1], period='annual', sources={}))
            for field, v in row.items():
                if field == 'date' or not finite(v):
                    continue
                target[field] = v
                endpoint = ('cash-flow' if field in ('operating_cashflow', 'free_cashflow') else
                            'balance-sheet' if field in ('equity', 'debt', 'cash', 'current_assets', 'current_liabilities') else 'income-statement')
                target['sources'][field] = d.get('sources', {}).get(endpoint) or d.get('source_url', '')
    annual = sorted(merged.values(), key=lambda row: (row['date'], row['currency']))
    trailing = {}
    d = snaps.get('stock_financials', {}).get('data', {})
    for row in d.get('series', []):
        field = stock_fundamentals.FIELDS.get(row['field'])
        if not field or not finite(row['value']):
            continue
        if field == 'interest': field = 'interest_expense'
        key = row['date'], row['currency']
        target = trailing.setdefault(key, dict(date=key[0], currency=key[1], period='TTM', sources={}))
        target[field] = row['value']; target['sources'][field] = d['source_url']
    return annual, sorted(trailing.values(), key=lambda row: (row['date'], row['currency']))


def metric(a, key):
    row = a.get('sector_metrics', {}).get(key, {})
    return row if finite(row.get('value')) else {}


def latest_record(rows):
    if not rows:
        return {}
    last = max(row['date'] for row in rows)
    candidates = [row for row in rows if row['date'] == last]
    # A reporting-currency transition needs reconciliation, not an arbitrary pick.
    return candidates[0] if len({row['currency'] for row in candidates}) == 1 else {}


def quality(app, a, annual):
    profile = a['sector_analysis']['profile']; checks = []
    def add(key, label, status, detail, value=None, unit='', asof=None, sources=None):
        checks.append(dict(key=key, label=label, status=status, detail=detail, value=value,
                           unit=unit, asof=asof, sources=list(dict.fromkeys(s for s in sources or [] if s))))
    health = [c for c in a['sector_analysis']['checks'] if c['group'] == 'health']
    roe = metric(a, 'roe')
    add('profitability', 'Rentabilidade do patrimônio', 'unknown' if not roe else 'pass' if roe['value'] > 0 else 'fail',
        'ROE positivo é apenas um sinal contábil. Compare com o retorno exigido, recorrência e patrimônio médio.',
        roe.get('value'), '%', roe.get('asof'))
    latest = latest_record(annual)
    same = [r for r in annual if r['currency'] == latest.get('currency')]
    previous = next((r for r in reversed(same) if 350 <= (date.fromisoformat(latest['date'])-date.fromisoformat(r['date'])).days <= 380), {}) if latest else {}
    rev, old = latest.get('revenue'), previous.get('revenue')
    growth = 100*(rev/old-1) if finite(rev) and finite(old) and rev > 0 and old > 0 else None
    fresh = bool(latest and 0 <= app.age(latest['date']) <= 455)
    add('growth', 'Evolução da receita anual', 'unknown' if growth is None or not fresh else 'pass' if growth > 0 else 'fail',
        'Comparação de dois exercícios completos, com mesma moeda e encerramentos separados por cerca de 12 meses. Crescimento nominal; confirme inflação, aquisições e volume.',
        growth if fresh else None, '%', latest.get('date'), [latest.get('sources', {}).get('revenue'), previous.get('sources', {}).get('revenue')])
    if profile in FINANCIAL:
        add('cash', 'Caixa operacional', 'na', 'Fluxo operacional de uma instituição financeira não recebe o mesmo corte de uma indústria.')
    else:
        cash, profit = latest.get('operating_cashflow'), latest.get('net_income')
        conversion = cash/profit if finite(cash) and finite(profit) and profit > 0 and fresh else None
        add('cash', 'Conversão do lucro em caixa', 'unknown' if conversion is None else 'pass' if conversion >= 1 else 'fail',
            'Caixa operacional/lucro do mesmo exercício. Corte de estudo: pelo menos 1×. Capital de giro ou expansão podem explicar uma leitura abaixo do corte.',
            conversion, '×', latest.get('date'), [latest.get('sources', {}).get('operating_cashflow'), latest.get('sources', {}).get('net_income')])
    statuses = [c['status'] for c in health]
    add('safety', 'Saúde nos critérios próprios do setor', 'fail' if 'fail' in statuses else 'unknown' if not statuses or 'unknown' in statuses else 'pass',
        f'{sum(s=="pass" for s in statuses)} atendem, {sum(s=="fail" for s in statuses)} a revisar e {sum(s=="unknown" for s in statuses)} pendentes; cortes definidos no aplicativo e editáveis por setor.')
    count = {s: sum(c['status'] == s for c in checks) for s in ('pass', 'fail', 'unknown', 'na')}
    return dict(checks=checks, counts=count, status='review' if count['fail'] else 'incomplete' if count['unknown'] else 'within',
                note='Diagnóstico próprio, inspirado nas dimensões de qualidade da literatura. Não reproduz o fator QMJ nem o Piotroski F-Score; contagens não são probabilidades de alta.')


def residual_value(a, p):
    observed_roe, observed_pvp = metric(a, 'roe'), metric(a, 'pvp')
    roe = p['sustainable_roe'] if p['sustainable_roe'] is not None else observed_roe.get('value')
    k, g = p['cost_of_equity'], p['long_growth']
    result = dict(status='incomplete', roe=roe, roe_origin='Premissa escolhida' if p['sustainable_roe'] is not None else 'ROE histórico usado como hipótese',
                  observed_roe=observed_roe, observed_pvp=observed_pvp, scenarios=[],
                  note='P/VP do cenário = (ROE sustentável − crescimento)/(retorno exigido − crescimento). Hipótese de crescimento estável, reinvestimento coerente e patrimônio contábil útil. Taxas nominais na moeda do emissor. Cenários não são previsão de cotação nem intervalo de confiança.')
    if k is None or roe is None:
        result['reason'] = 'Informe retorno exigido e confirme o ROE sustentável para calcular as hipóteses de valor.'
        return result
    for name, r, cost, growth in [('Adverso', roe-3, k+2, g), ('Escolhido', roe, k, g), ('Favorável', roe+3, k-2, g)]:
        valid = cost > growth and r > growth
        fair = (r-growth)/(cost-growth) if valid else None
        current = observed_pvp.get('value')
        gap = 100*(fair/current-1) if fair is not None and current is not None and current > 0 else None
        classification = ('unknown' if gap is None else 'below' if current < fair*.9 else
                          'above' if current > fair*1.1 else 'near')
        result['scenarios'].append(dict(label=name, roe=r, cost_of_equity=cost, growth=growth, pvp=fair,
            difference=gap, classification=classification,
            reason='' if valid else 'Crescimento deve ficar abaixo do retorno exigido e do ROE; reinvestimento entre 0% e 100%.'))
    base = result['scenarios'][1]
    result.update(status='ready' if base['pvp'] is not None else 'incomplete',
                  reason='Faixa de comparação de ±10% ao redor de cada hipótese; não estima retorno futuro.')
    if a['sector_analysis']['profile'] in ('technology', 'financial_services'):
        result['reason'] += ' Patrimônio pode ser pouco representativo de intangíveis e participações; complemente com outros modelos.'
    return result


def operating_stress(app, a, annual, trailing, p):
    if a['sector_analysis']['profile'] in FINANCIAL:
        prudential = [c for c in a['sector_analysis']['checks'] if c['group'] == 'health']
        return dict(status='na', rows=[], checks=prudential,
                    reason='Bancos, seguradoras e outros serviços financeiros usam capital, crédito e solvência do seu perfil. Este simulador de despesas, EBIT e dívida industrial não se aplica.')
    rows = annual if a['asset_type'] == 'stock' else trailing
    candidates = [r for r in rows if 'revenue' in r or 'ebit' in r]
    base = latest_record(candidates)
    result = dict(status='incomplete', rows=[], base=base, missing=[],
                  note='Receita sofre o choque escolhido; a parcela variável das despesas operacionais sem depreciação acompanha a receita e a parcela fixa permanece. Juros adicionais = dívida × parcela flutuante × choque de taxa. Depreciação (EBITDA menos EBIT) permanece constante quando comparável; sem EBITDA, a simulação usa despesas totais e permanece incompleta. Não projeta câmbio, hedge, impostos, capex, capital de giro ou amortização do principal; não calcula probabilidade de sobrevivência.')
    required = ('revenue', 'ebit', 'debt', 'cash', 'interest_expense', 'ebitda')
    result['missing'] = [key for key in required if not finite(base.get(key))]
    revenue, ebit = base.get('revenue'), base.get('ebit')
    if not base or not 0 <= app.age(base['date']) <= 455 or not finite(revenue) or revenue <= 0 or not finite(ebit) or ebit > revenue:
        result['reason'] = 'Faltam receita e EBIT comparáveis e recentes, na mesma data e moeda. Atualize a ficha ou informe a demonstração.'
        return result
    debt, cash, interest, ebitda = (base.get(key) for key in ('debt', 'cash', 'interest_expense', 'ebitda'))
    expense = revenue-ebit
    dep = ebitda-ebit if finite(ebitda) and 0 <= ebitda-ebit <= expense else None
    variable_base = expense-dep if dep is not None else expense
    extra = (debt*p['floating_debt_share']/100*p['rate_shock']/100 if finite(debt) and debt >= 0 else
             0 if p['rate_shock'] == 0 or p['floating_debt_share'] == 0 else None)
    shocked_interest = abs(interest)+extra if finite(interest) and extra is not None else None
    cut = next((c['limit'] for c in a['sector_analysis']['checks'] if c['metric'] == 'net_debt_ebitda' and c['limit'] is not None), None)
    for label, shock, cost_interest in [('Base contábil', 0, abs(interest) if finite(interest) else None),
                                       ('Cenário escolhido', p['revenue_shock'], shocked_interest)]:
        stressed_revenue = revenue*(1+shock/100)
        stressed_ebit = stressed_revenue-variable_base*((1-p['variable_cost_share']/100)+p['variable_cost_share']/100*(1+shock/100))-(dep or 0)
        new_ebitda = stressed_ebit+dep if dep is not None else None
        coverage = stressed_ebit/cost_interest if cost_interest is not None and cost_interest > 0 else None
        leverage = (debt-cash)/new_ebitda if finite(debt) and finite(cash) and min(debt,cash) >= 0 and new_ebitda is not None and new_ebitda > 0 else None
        result['rows'].append(dict(label=label, revenue=stressed_revenue, ebit=stressed_ebit,
            margin=100*stressed_ebit/stressed_revenue, interest=cost_interest, interest_coverage=coverage,
            ebitda=new_ebitda, net_debt_ebitda=leverage))
    shocked = result['rows'][1]
    adverse = shocked['ebit'] <= 0 or (shocked['interest_coverage'] is not None and shocked['interest_coverage'] < 1)
    adverse = adverse or (shocked['net_debt_ebitda'] is not None and cut is not None and shocked['net_debt_ebitda'] > cut)
    zero_interest = shocked_interest == 0 and debt == 0
    complete = (not result['missing'] and debt >= 0 and cash >= 0 and dep is not None and shocked['ebitda'] > 0
                and (shocked['interest_coverage'] is not None or zero_interest))
    result.update(status='attention' if adverse else 'incomplete' if not complete else 'within_scenario',
                  leverage_limit=cut, reason='Folga operacional no cenário, sem avaliação completa da liquidez ou dos vencimentos. Campos ausentes impedem uma conclusão favorável completa.')
    return result


def analyze(app, a):
    saved = a.get('snapshots', {}).get(KINDS[0], {}).get('data')
    p = parameters(saved['parameters']) if saved else dict(DEFAULTS)
    annual, trailing = records(a)
    q = quality(app, a, annual)
    return dict(version=1, name='Modelo fundamental por cenários', parameters=p, saved_at=saved.get('asof') if saved else None,
                quality=q, valuation=residual_value(a,p), stress=operating_stress(app,a,annual,trailing,p),
                references=REFERENCES, business_questions=[
                    'Quais produtos e segmentos geram receita e lucro? Há concentração de clientes?',
                    'A receita é recorrente? A empresa consegue repassar custos e manter margens?',
                    'O crescimento vem de volume, preços ou aquisições? Exige novos investimentos?',
                    'Quais contratos, commodities, moedas e riscos regulatórios afetam este negócio?'],
                note='Modelo determinístico de estudo, sem treinamento. Saúde, preço e cenário de crise permanecem separados. Falta de dados não equivale a dívida zero ou empresa segura.')


def enrich(app, a):
    if a['asset_type'] in ('stock', 'foreign', 'global_stock', 'bdr'):
        a['company_research']['fundamental_model'] = analyze(app, a)
