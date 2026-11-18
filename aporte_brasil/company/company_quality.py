"""The user's eleven company criteria, evaluated from dated, sourced evidence."""
from datetime import date
import math
import re

KIND = 'issuer_quality_facts'
BOOL_FIELDS = ('innovation', 'obsolete_sector', 'dividend_payments', 'blue_chip',
               'good_management', 'corruption_history', 'state_controlled', 'single_client_concentration')
FACT_FIELDS = (*BOOL_FIELDS, 'founded', 'founded_year', 'sector_origin_year', 'leadership')


def validate_snapshot(app, data):
    if not isinstance(data, dict) or set(data) != {'symbol', 'facts', 'annual_metrics'}:
        raise ValueError('Evidências dos critérios inválidas.')
    if not isinstance(data['symbol'], str) or not re.fullmatch(r'[A-Z0-9.^-]{1,24}', data['symbol']):
        raise ValueError('Empresa das evidências inválida.')
    if not isinstance(data['facts'], dict) or set(data['facts']) - set(FACT_FIELDS):
        raise ValueError('Informação qualitativa não reconhecida.')
    def source(value):
        url = app.validate_url(value)
        if not url: raise ValueError('Informe a fonte da evidência.')
        return url
    def past(value):
        ref = app.valid_date(value)
        if ref > app.today().isoformat(): raise ValueError('Evidência com data futura.')
        return ref
    facts = {}
    for key, row in data['facts'].items():
        if not isinstance(row, dict) or set(row) != {'value', 'asof', 'source_url', 'note'}:
            raise ValueError('Informe valor, data, fonte e fundamento de cada informação.')
        value = row['value']; ref = past(row['asof'])
        if key in BOOL_FIELDS:
            if type(value) is not bool: raise ValueError('Use sim ou não; ausência não significa não.')
        elif key == 'founded':
            value = past(value)
            if value > ref: raise ValueError('Fundação posterior à data da evidência.')
        elif key in ('sector_origin_year','founded_year'):
            if type(value) is not int or not 1 <= value <= int(ref[:4]):
                raise ValueError('Ano de origem do setor inválido.')
        else:
            if (not isinstance(value, dict) or set(value) != {'rank', 'scope', 'metric'}
                    or type(value['rank']) is not int or not 1 <= value['rank'] <= 10000
                    or value['scope'] not in ('national', 'global')):
                raise ValueError('Informe colocação, âmbito nacional/mundial e medida do ranking.')
            value = {**value, 'metric': app.text_value(value['metric'], 300, True)}
        facts[key] = dict(value=value, asof=ref, source_url=source(row['source_url']),
                          note=app.text_value(row['note'], 1500, True))
    if not isinstance(data['annual_metrics'], list) or len(data['annual_metrics']) > 11:
        raise ValueError('Informe até onze exercícios com indicadores conferidos.')
    annual = []
    for row in data['annual_metrics']:
        if not isinstance(row, dict) or set(row) != {'date', 'roe', 'net_debt', 'ebitda', 'source_url'}:
            raise ValueError('Indicadores anuais inválidos.')
        ref = past(row['date'])
        if int(ref[:4]) >= app.today().year: raise ValueError('Use exercícios anuais completos.')
        values = {}
        for key in ('roe', 'net_debt', 'ebitda'):
            value = row[key]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('Indicador anual deve ser numérico e finito.')
            values[key] = app.number(value) if value is not None else None
        if not any(v is not None for v in values.values()): raise ValueError('Exercício sem indicadores.')
        annual.append(dict(date=ref, **values, source_url=source(row['source_url'])))
    if len({r['date'][:4] for r in annual}) != len(annual): raise ValueError('Exercício anual duplicado.')
    return dict(symbol=data['symbol'], facts=facts, annual_metrics=sorted(annual, key=lambda r:r['date']))


def assess(app, asset):
    snaps = asset.get('snapshots', {})
    saved = snaps.get(KIND, {}).get('data', {})
    facts = saved.get('facts', {})
    required = list(range(app.today().year-5, app.today().year))
    manual = {int(r['date'][:4]): r for r in saved.get('annual_metrics', [])}
    statements = snaps.get('issuer_statements', {}).get('data', {})
    rows = {int(r['date'][:4]): r for r in statements.get('annual', [])}
    checks = []
    def add(key, label, status='unknown', detail='Faltam dados e fonte para conferir este critério.', refs=()):
        refs = sorted({(r.get('asof') or r.get('date') or '', r.get('source_url', '')) for r in refs if r})
        checks.append(dict(key='quality_'+key, label=label, status=status, detail=detail,
            source_url=next((url for _,url in refs if url), ''),
            asof=min((ref for ref,_ in refs if ref), default=None),
            references=[{'asof':ref, 'url':url} for ref,url in sorted(refs) if url]))
    def fact(key, fresh=True):
        row = facts.get(key)
        return row if row and (not fresh or 0 <= app.age(row['asof']) <= 365) else None
    def boolean(key):
        row = fact(key)
        return row['value'] if row else None
    def historical(metric):
        observed = []; references = []
        for year in required:
            value = None; row = rows.get(year, {}); prev = rows.get(year-1, {})
            supplied = manual.get(year, {})
            if metric == 'roe':
                if supplied.get('roe') is not None:
                    value = supplied['roe']; reference = supplied
                else:
                    profit, equity, previous = row.get('net_income'), row.get('equity'), prev.get('equity')
                    if profit is not None and equity is not None and previous is not None and equity > 0 and previous > 0:
                        if 300 <= (date.fromisoformat(row['date'])-date.fromisoformat(prev['date'])).days <= 430:
                            value = profit/((equity+previous)/2)*100
                    reference = {'date':row.get('date'), 'source_url':statements.get('sources',{}).get('balance-sheet') or statements.get('source_url','')}
            else:
                override = supplied.get('net_debt') is not None or supplied.get('ebitda') is not None
                if override:
                    debt, ebitda = supplied.get('net_debt'), supplied.get('ebitda'); reference = supplied
                else:
                    debt = row['debt']-row['cash'] if row.get('debt') is not None and row.get('cash') is not None else None
                    ebitda = row.get('ebitda'); reference = {'date':row.get('date'), 'source_url':statements.get('source_url','')}
                if debt is not None and ebitda is not None and ebitda > 0: value = debt/ebitda
            if value is not None and math.isfinite(value):
                observed.append((year, value)); references.append(reference)
        return observed, references
    roe, refs = historical('roe')
    status = 'fail' if any(v <= 5 for _,v in roe) else 'pass' if len(roe) == 5 else 'unknown'
    add('roe5', 'ROE historicamente maior que 5%?', status,
        f'{len(roe)} de 5 exercícios completos ({required[0]}–{required[-1]}). Exige ROE > 5% em cada ano; 5% exatos não atendem. '
        'Cálculo automático: lucro anual / patrimônio médio entre dois encerramentos positivos. O ROE atual não substitui o histórico. '+
        '; '.join(f'{year}: {value:.2f}%' for year,value in roe), refs)

    # Six observations delimit five full annual growth intervals. Never mix currencies.
    start_year, end_year = required[0]-1, required[-1]
    candidates = [(snaps.get('issuer_financials', {}), 'years'), (snaps.get('issuer_statements', {}), 'annual')]
    rates = {}; rate_refs = []
    for metric in ('revenue', 'net_income'):
        for snap,bucket in sorted(candidates, key=lambda pair:pair[0].get('retrieved_at',''), reverse=True):
            data = snap.get('data', {}); series = {int(r['date'][:4]):r for r in data.get(bucket, [])}
            window = [series.get(year, {}).get(metric) for year in range(start_year,end_year+1)]
            if len(window) != 6 or any(v is None for v in window): continue
            # A newer complete correction invalidates the old base; do not revive
            # an older, positive series when the current base is nonpositive.
            if window[0] <= 0 or window[-1] <= 0: break
            rate = math.expm1((math.log(window[-1])-math.log(window[0]))/5)*100
            if not math.isfinite(rate): continue
            rates[metric] = rate
            rate_refs.append({'date':series[end_year]['date'], 'source_url':data.get('source_url','')})
            break
    above = lambda value:value > 5 and not math.isclose(value,5,abs_tol=1e-10,rel_tol=1e-10)
    status = 'pass' if any(above(v) for v in rates.values()) else 'fail' if len(rates) == 2 else 'unknown'
    add('growth5', 'Receita ou lucro crescem mais de 5% ao ano nos últimos 5 anos?', status,
        f'CAGR de {start_year} a {end_year}: seis exercícios, cinco intervalos. Basta receita OU lucro acima de 5% a.a. '
        'Exige a série anual e extremos positivos, na mesma moeda. Prejuízo inicial/final não vira CAGR. '+
        '; '.join(('Receita' if key=='revenue' else 'Lucro')+f': {value:.4f}% a.a.' for key,value in rates.items()), rate_refs)

    dividend = fact('dividend_payments', fresh=False)
    dy = snaps.get('issuer_dividend_history', {}).get('data', {})
    paid = [r['year'] for r in dy.get('years', []) if r.get('dy') is not None and r['dy'] > 0]
    complete_zero = all(any(r['year']==year and r.get('dy')==0 for r in dy.get('years', [])) for year in required)
    status = 'pass' if paid or dividend and dividend['value'] is True else 'fail' if complete_zero or boolean('dividend_payments') is False else 'unknown'
    add('dividends', 'A empresa tem histórico de pagamento de dividendos?', status,
        ('Pagamentos documentados em '+', '.join(map(str,paid))+'. ' if paid else '')+
        'Histórico de pagamentos, sem exigir DY mínimo de 5% nem prometer continuidade. Dividendos da sua carteira não são usados como histórico da empresa.',
        [dividend, {'source_url':dy.get('source_url','')}])
    obsolete = fact('obsolete_sector', fresh=False)
    innovation = boolean('innovation')
    status = 'fail' if obsolete and obsolete['value'] is True or innovation is False else 'pass' if innovation is True and boolean('obsolete_sector') is False else 'unknown'
    add('innovation', 'Investe amplamente em pesquisa e inovação?', status,
        'Setor classificado como obsoleto: SEMPRE NÃO. Para SIM, confirme investimento amplo e que o setor não é obsoleto, com fonte e fundamento. '+
        ('Setor obsoleto confirmado. ' if obsolete and obsolete['value'] is True else '')+
        (fact('innovation',False) or {}).get('note',''), [obsolete, fact('innovation',False)])
    founded = fact('founded', fresh=False)
    if founded:
        origin = date.fromisoformat(founded['value']); today = app.today()
        years = today.year-origin.year-((today.month,today.day)<(origin.month,origin.day))
        # More than 30 years means strictly after the thirtieth anniversary.
        cutoff = (today.year-30,today.month,today.day)
        status = 'pass' if (origin.year,origin.month,origin.day)<cutoff else 'fail'
        add('age30', 'Tem mais de 30 anos de mercado desde a fundação?', status,
            f'Fundação: {origin.isoformat()}; {years} anos completos. A data de IPO/listagem não substitui a fundação.', [founded])
    elif fact('founded_year',False):
        founded=fact('founded_year',False);age=app.today().year-founded['value']
        add('age30','Tem mais de 30 anos de mercado desde a fundação?', 'pass' if age>30 else 'fail' if age<30 else 'unknown',
            f"Ano de fundação: {founded['value']}; dia e mês não informados. No ano do 30º aniversário, o ano sozinho não comprova o critério.",[founded])
    else:add('age30','Tem mais de 30 anos de mercado desde a fundação?')
    leader = fact('leadership')
    add('leader', 'É líder nacional ou mundial, na primeira colocação?',
        'pass' if leader and leader['value']['rank']==1 else 'fail' if leader else 'unknown',
        ('Colocação: '+str(leader['value']['rank'])+' · '+('nacional' if leader['value']['scope']=='national' else 'mundial')+' · medida: '+leader['value']['metric']+'. ' if leader else '')+
        'Somente a primeira colocada atende. Top 3, uma das líderes, porte e fama não comprovam liderança.', [leader])
    sector = fact('sector_origin_year', fresh=False)
    age = app.today().year-sector['value'] if sector else None
    add('sector100', 'O setor tem mais de 100 anos?', 'pass' if age is not None and age>100 else 'fail' if age is not None and age<100 else 'unknown',
        (f'Origem documentada do setor: {sector["value"]}. ' if sector else '')+
        'Use a história do setor específico, não a idade da empresa. No ano do centenário, só o ano não comprova que o aniversário já passou.', [sector])
    blue = fact('blue_chip')
    add('blue_chip', 'A empresa é uma blue chip?', 'pass' if blue and blue['value'] else 'fail' if blue else 'unknown',
        'Exige classificação explícita, fonte, mercado e fundamento. Tamanho, liquidez ou presença em índice, isoladamente, não confirmam blue chip. '+(blue or {}).get('note',''), [blue])
    corruption = fact('corruption_history', fresh=False); management = boolean('good_management')
    status = 'fail' if corruption and corruption['value'] is True or management is False else 'pass' if management is True and boolean('corruption_history') is False else 'unknown'
    add('management', 'A empresa tem boa gestão?', status,
        'Histórico de corrupção comprovado: SEMPRE NÃO, mesmo com avaliação favorável da gestão ou registro antigo. '
        'Ausência de notícia não comprova ausência de corrupção; leia o escopo da fonte. '+(corruption or {}).get('note',''),
        [corruption, fact('good_management',False)])
    state, client = boolean('state_controlled'), boolean('single_client_concentration')
    add('independent', 'É livre de controle estatal e de concentração em cliente único?',
        'fail' if state is True or client is True else 'pass' if state is False and client is False else 'unknown',
        'Exige as duas condições: sem controle estatal E sem dependência de cliente único. Um dos riscos comprovado reprova; um campo ausente não vira NÃO.',
        [fact('state_controlled',False), fact('single_client_concentration',False)])
    debt, refs = historical('debt')
    financial = asset.get('sector_analysis',{}).get('profile') in ('bank','insurance','financial_services')
    status = 'na' if financial else 'fail' if any(v >= 2 for _,v in debt) else 'pass' if len(debt)==5 else 'unknown'
    add('debt5', 'Dívida líquida/EBITDA menor que 2 em cada um dos últimos 5 anos?', status,
        ('Dívida integra a operação financeira; este múltiplo não é usado como filtro genérico. Confira capital, crédito e solvência. ' if financial else '')+
        f'{len(debt)} de 5 exercícios comparáveis. Corte fixo < 2×; 2× exatos não atendem. Exige EBITDA positivo; dívida líquida negativa representa caixa líquido. '+
        '; '.join(f'{year}: {value:.3f}×' for year,value in debt), refs)
    return {'checks':checks, 'facts':saved, 'years':required, 'growth_years':[start_year,end_year]}
