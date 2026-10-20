"""Long-term company checklist from dated public evidence, independent of opinions."""
from datetime import datetime, timezone, date
import math
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import market_brief
import company_insights

KINDS = ('issuer_profile', 'issuer_quarters', 'issuer_market_history', 'issuer_dividend_history', 'issuer_opinions') + company_insights.KINDS
CURRENCIES = ('BRL', 'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'CHF', 'AUD')


def symbol(a):
    return a['ticker'] + ('.SA' if a['asset_type'] == 'stock' else '')


def value(app, v, nonnegative=False):
    if v is None:
        return None
    if type(v) not in (int, float) or not math.isfinite(v) or nonnegative and v < 0:
        raise ValueError('Valor histórico inválido; use valores completos da demonstração.')
    return app.number(v)


def validate_snapshot(app, kind, d):
    if kind in company_insights.KINDS:
        return company_insights.validate_snapshot(app, kind, d)
    if not isinstance(d, dict) or kind not in KINDS:
        raise ValueError('Histórico da empresa inválido.')
    import re
    if not isinstance(d.get('symbol'), str) or not re.fullmatch(r'[A-Z0-9.^-]{1,24}', d['symbol']):
        raise ValueError('Empresa do histórico inválida.')
    out = dict(d)
    if kind != 'issuer_opinions':
        out['source_url'] = app.validate_url(d.get('source_url'))
        if not out['source_url']:
            raise ValueError('Informe a fonte do histórico.')
    def past(v):
        ref = app.valid_date(v)
        if ref > app.today().isoformat():
            raise ValueError('Histórico com data futura.')
        return ref
    fields = {
        'issuer_profile': {'symbol', 'name', 'sector', 'industry', 'description', 'cnpj', 'website', 'source_url'},
        'issuer_quarters': {'symbol', 'currency', 'quarters', 'source_url'},
        'issuer_market_history': {'symbol', 'currency', 'first_trade', 'average_daily_value', 'sessions', 'asof', 'source_url'},
        'issuer_dividend_history': {'symbol', 'years', 'method', 'source_url'},
        'issuer_opinions': {'symbol', 'items'},
    }
    if set(d) != fields[kind]:
        raise ValueError('Campos do histórico inválidos.')
    if 'currency' in d and d['currency'] not in CURRENCIES:
        raise ValueError('Moeda do histórico inválida.')
    if kind == 'issuer_profile':
        for key, limit in [('name', 200), ('sector', 120), ('industry', 200), ('description', 10000), ('cnpj', 30)]:
            out[key] = app.text_value(d[key], limit, key == 'name')
        out['website'] = app.validate_url(d['website'])
    elif kind == 'issuer_quarters':
        if not isinstance(d['quarters'], list) or not 1 <= len(d['quarters']) <= 28:
            raise ValueError('Informe de um a 28 trimestres isolados.')
        rows = []
        for r in d['quarters']:
            if not isinstance(r, dict) or set(r) != {'date', 'net_income', 'revenue'}:
                raise ValueError('Trimestre inválido.')
            rows.append({'date': past(r['date']), 'net_income': value(app, r['net_income']), 'revenue': value(app, r['revenue'])})
        if len({r['date'] for r in rows}) != len(rows):
            raise ValueError('Trimestre duplicado.')
        out['quarters'] = sorted(rows, key=lambda r: r['date'])
    elif kind == 'issuer_market_history':
        out['asof'] = past(d['asof'])
        out['first_trade'] = past(d['first_trade']) if d['first_trade'] else None
        if out['first_trade'] and out['first_trade'] > out['asof']:
            raise ValueError('Primeiro pregão posterior à referência.')
        out['average_daily_value'] = value(app, d['average_daily_value'], True)
        if type(d['sessions']) is not int or not 0 <= d['sessions'] <= 20:
            raise ValueError('Janela de liquidez inválida.')
    elif kind == 'issuer_dividend_history':
        out['method'] = app.text_value(d['method'], 1000, True)
        if not isinstance(d['years'], list) or not 1 <= len(d['years']) <= 6:
            raise ValueError('Informe de um a seis anos de dividend yield.')
        rows = []
        for r in d['years']:
            if not isinstance(r, dict) or set(r) != {'year', 'dy'} or type(r['year']) is not int or not 1900 <= r['year'] < app.today().year:
                raise ValueError('Ano de dividendos inválido; use anos completos.')
            rows.append({'year': r['year'], 'dy': value(app, r['dy'], True)})
        if len({r['year'] for r in rows}) != len(rows):
            raise ValueError('Ano de dividendos duplicado.')
        out['years'] = sorted(rows, key=lambda r: r['year'])
    else:
        if not isinstance(d['items'], list) or len(d['items']) > 24:
            raise ValueError('Lista de opiniões inválida.')
        items = []
        for r in d['items']:
            if not isinstance(r, dict) or set(r) != {'origin', 'title', 'text', 'author', 'date', 'url'} or r['origin'] not in ('rss', 'manual'):
                raise ValueError('Publicação inválida.')
            item = {**r, 'date': past(r['date']), 'url': app.validate_url(r['url'])}
            if not item['url']:
                raise ValueError('Informe o link da publicação.')
            for key, limit in [('title', 300), ('text', 2000), ('author', 200)]:
                item[key] = app.text_value(r[key], limit, key != 'text')
            if r['origin'] == 'rss' and item['text']:
                raise ValueError('RSS contém apenas títulos; não representa o artigo completo.')
            items.append(item)
        out['items'] = sorted(items, key=lambda r: r['date'], reverse=True)
    return out


def brapi(app, a, endpoint, **params):
    with app.connect() as c:
        token = app.settings(c).get('brapi_token', '')
    import os
    token = token or os.getenv('BRAPI_TOKEN', '')
    url = 'https://brapi.dev/api/v2/stocks/' + endpoint + '?' + urllib.parse.urlencode({'symbols': a['ticker'], **params})
    raw = app.request_json(url, token)
    matches = [r for r in raw.get('results', []) if r.get('requestedSymbol', r.get('symbol')) == a['ticker']]
    if len(matches) != 1 or matches[0].get('symbol') != a['ticker'] or matches[0].get('changed'):
        raise ValueError('Empresa da fonte não corresponde ao ticker; histórico anterior preservado.')
    return matches[0].get('data'), url


def fetch_profile(app, a):
    if a['asset_type'] == 'stock':
        try:
            d, url = brapi(app, a, 'profile')
            if not isinstance(d, dict):raise ValueError('Perfil da empresa indisponível.')
            return validate_snapshot(app, 'issuer_profile', {'symbol': symbol(a), 'name': d.get('name') or a['name'],
                'sector': d.get('sector') or '', 'industry': d.get('industry') or '',
                'description': d.get('longBusinessSummary') or d.get('description') or '', 'cnpj': d.get('cnpj') or '',
                'website': d.get('website') or '', 'source_url': url})
        except ValueError:
            import public_reports
            cnpj,d=public_reports.company_identity(app,a,with_details=True)
            return validate_snapshot(app,'issuer_profile',{'symbol':symbol(a),'name':d.get('companyName') or a['name'],
                'sector':d.get('industryClassification') or a['sector'],'industry':d.get('activity') or '',
                'description':d.get('activity') or '', 'cnpj':cnpj,'website':d.get('website') or '',
                'source_url':'https://sistemaswebb3-listados.b3.com.br/listedCompaniesPage/?language=pt-br'})
    # International classification already has its own verified, cached provider.
    with app.connect() as c: p = app.latest(c, a['id']).get('stock_profile')
    if not p:
        raise ValueError('Atualize a identificação pública deste stock para obter seu perfil.')
    d = p['data']
    return validate_snapshot(app, 'issuer_profile', {'symbol': symbol(a), 'name': d['name'], 'sector': d['sector_original'],
        'industry': d['industry'], 'description': '', 'cnpj': '', 'website': '', 'source_url': d['source_url']})


def fetch_brazil_results(app, a, period):
    d, url = brapi(app, a, 'income-statement', period=period, startDate=str(app.today().year - (11 if period == 'annual' else 6)) + '-01-01', endDate=app.today().isoformat())
    if not isinstance(d, list) or not d:
        raise ValueError('Demonstrações financeiras indisponíveis nesta fonte ou plano.')
    rows = []
    for r in d:
        if not isinstance(r, dict) or r.get('type') != ('yearly' if period == 'annual' else 'quarterly'):
            raise ValueError('A fonte misturou períodos financeiros.')
        # brapi v2 normalizes CVM Brazilian statement values to full BRL units.
        if r.get('currency', 'BRL') != 'BRL':
            raise ValueError('Moeda da demonstração brasileira não confirmada.')
        rows.append({'date': str(r.get('endDate') or '')[:10], 'net_income': value(app, r.get('netIncome')),
                     'revenue': value(app, r.get('totalRevenue'))})
    if not any(r['net_income'] is not None for r in rows):
        raise ValueError('Fonte sem resultados numéricos; histórico anterior preservado.')
    return rows, url


def fetch_quarters(app, a):
    if a['asset_type'] == 'stock':
        rows, url = fetch_brazil_results(app, a, 'quarterly')
        currency = 'BRL'
    else:
        fields = {'quarterlyNetIncome': 'net_income', 'quarterlyTotalRevenue': 'revenue'}
        query = urllib.parse.urlencode({'type': ','.join(fields), 'period1': int(datetime(app.today().year - 6, 1, 1, tzinfo=timezone.utc).timestamp()),
                                      'period2': int(datetime.now(timezone.utc).timestamp())})
        raw = app.request_json('https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/' + symbol(a) + '?' + query)
        result = raw.get('timeseries', {})
        if result.get('error') or not isinstance(result.get('result'), list):
            raise ValueError('Resultados trimestrais indisponíveis.')
        by_date = {}; currencies = set(); seen = set()
        for part in result['result']:
            meta = part.get('meta', {}); keys = meta.get('type', [])
            if meta.get('symbol') != [symbol(a)] or len(keys) != 1 or keys[0] not in fields:
                raise ValueError('Emissor dos resultados trimestrais não confirmado.')
            key = keys[0]
            for r in part.get(key, []):
                if r.get('periodType') != '3M' or (key, r.get('asOfDate')) in seen:
                    raise ValueError('Trimestres duplicados ou não isolados.')
                seen.add((key, r.get('asOfDate'))); currencies.add(r.get('currencyCode'))
                by_date.setdefault(r.get('asOfDate'), {'date': r.get('asOfDate'), 'net_income': None, 'revenue': None})[fields[key]] = value(app, r.get('reportedValue', {}).get('raw'))
        if len(currencies) != 1:
            raise ValueError('Moedas trimestrais incompatíveis.')
        currency = next(iter(currencies)); rows = list(by_date.values())
        url = 'https://finance.yahoo.com/quote/' + symbol(a) + '/financials/'
    return validate_snapshot(app, 'issuer_quarters', {'symbol': symbol(a), 'currency': currency,
        'quarters': sorted(rows, key=lambda r: r['date'])[-28:], 'source_url': url})


def fetch_market(app, a):
    raw = app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/' + symbol(a) + '?range=3mo&interval=1d')
    try:
        r = raw['chart']['result'][0]; m = r['meta']
    except (KeyError, TypeError, IndexError):
        raise ValueError('Histórico de negociação indisponível.') from None
    if m.get('symbol') != symbol(a) or m.get('instrumentType') != 'EQUITY' or m.get('currency') not in CURRENCIES:
        raise ValueError('Ticker, instrumento ou moeda de negociação não confirmados.')
    if a['asset_type'] == 'stock' and m['currency'] != 'BRL':
        raise ValueError('Ação brasileira com moeda de negociação incompatível.')
    quotes = (r.get('indicators', {}).get('quote') or [{}])[0]
    sessions = []
    for ts, close, volume in zip(r.get('timestamp', []), quotes.get('close', []), quotes.get('volume', [])):
        ref = datetime.fromtimestamp(ts, timezone.utc).date()
        # Exclude the current day's partial session, even if the market just closed.
        if ref >= app.today():
            continue
        c, v = value(app, close, True), value(app, volume, True)
        if c is not None and c > 0 and v is not None:
            sessions.append((ref.isoformat(), c * v))
    sessions = sorted(sessions)[-20:]
    if not sessions:
        raise ValueError('Histórico sem pregões completos para estimar liquidez.')
    first = m.get('firstTradeDate')
    first = datetime.fromtimestamp(first, timezone.utc).date().isoformat() if type(first) in (int, float) and first > 0 else None
    return validate_snapshot(app, 'issuer_market_history', {'symbol': symbol(a), 'currency': m['currency'], 'first_trade': first,
        'average_daily_value': sum(v for _, v in sessions) / len(sessions), 'sessions': len(sessions), 'asof': sessions[-1][0],
        'source_url': 'https://finance.yahoo.com/quote/' + symbol(a) + '/history/'})


def checklist(app, a):
    snaps = a.get('snapshots', {})
    def data(kind): return snaps.get(kind, {}).get('data') or {}
    annual = data('issuer_financials'); quarters = data('issuer_quarters'); market = data('issuer_market_history')
    rows = annual.get('years', []); required = list(range(app.today().year - 5, app.today().year))
    recent = {int(r['date'][:4]): r for r in rows if int(r['date'][:4]) in required}
    checks = []
    def add(key, label, status='unknown', detail='Informação ainda não disponível.', source='', asof=None):
        checks.append({'key': key, 'label': label, 'status': status, 'detail': detail, 'source_url': source, 'asof': asof})
    governance = data('issuer_governance')
    first = governance.get('first_listed') or market.get('first_trade')
    if first:
        try:
            cutoff = app.today().replace(year=app.today().year - 5)
        except ValueError:
            cutoff = app.today().replace(year=app.today().year - 5, day=28)
        add('listed', 'Histórico em bolsa há mais de 5 anos', 'pass' if date.fromisoformat(first) < cutoff else 'unknown',
            'Registro de listagem na fonte: ' + first + '. Pode diferir do IPO e de listagens anteriores.', governance.get('source_url') if governance.get('first_listed') else market.get('source_url', ''), first)
    else:
        add('listed', 'Histórico em bolsa há mais de 5 anos')
    q = quarters.get('quarters', [])[-20:]
    contiguous = len(q) == 20 and all(65 <= (date.fromisoformat(b['date']) - date.fromisoformat(c['date'])).days <= 115 for c, b in zip(q, q[1:]))
    fresh = bool(q) and app.age(q[-1]['date']) <= 180
    complete = contiguous and fresh and all(r['net_income'] is not None for r in q)
    failed = fresh and any(r['net_income'] is not None and r['net_income'] <= 0 for r in q)
    add('quarterly_profit', 'Lucro nos últimos 20 trimestres (5 anos)', 'fail' if failed else 'pass' if complete else 'unknown',
        f"{len(q)} de 20 trimestres disponíveis. " + ('Há lucro não positivo na janela disponível.' if failed else 'Exige 20 períodos consecutivos, recentes e com lucro positivo.'),
        quarters.get('source_url', ''), q[-1]['date'] if q else None)
    known = [r for r in rows if r['net_income'] is not None]
    add('annual_profit', 'Sem prejuízo nos exercícios anuais disponíveis', 'fail' if any(r['net_income'] < 0 for r in known) else 'pass' if known else 'unknown',
        f"{len(known)} exercício(s) consultado(s). Este recorte não comprova ausência de prejuízo em toda a história da empresa.", annual.get('source_url', ''), rows[-1]['date'] if rows else None)
    for key, label, op in [('roe', 'ROE acima de 10%', lambda v: v > 10), ('debt_equity', 'Dívida bruta menor que o patrimônio', lambda v: 0 <= v < 1)]:
        metric = a.get('sector_metrics', {}).get(key) or {}; v = metric.get('value')
        financial = key == 'debt_equity' and a.get('sector_analysis', {}).get('profile') in ('bank', 'insurance', 'financial_services')
        valid = type(v) in (int, float) and math.isfinite(v) and app.age(metric.get('asof', '')) <= 180 and not financial
        add(key, label, ('pass' if op(v) else 'fail') if valid else 'unknown',
            'Para empresas financeiras, este corte genérico exige interpretação do balanço; confira os critérios prudenciais abaixo.' if financial else
            (f"Valor: {v:g}{'%' if key == 'roe' else ' ×'}. Fonte: {metric.get('source', '')}." if valid else 'Indicador ausente ou antigo; confira a referência do balanço.'), asof=metric.get('asof'))
    for key, label in [('revenue', 'Crescimento de receita nos últimos 5 anos'), ('net_income', 'Crescimento de lucros nos últimos 5 anos')]:
        valid = len(recent) == 5 and all(recent[y].get(key) is not None for y in required)
        start = recent.get(required[0], {}).get(key); end = recent.get(required[-1], {}).get(key)
        rate = ((end / start) ** .25 - 1) * 100 if valid and start > 0 and end > 0 else None
        add('growth_' + key, label, ('pass' if rate > 0 else 'fail') if rate is not None else 'unknown',
            (f"CAGR: {rate:.2f}% a.a. entre {required[0]} e {required[-1]} (4 intervalos entre 5 exercícios)." if rate is not None else
             f"Exige os exercícios {required[0]}–{required[-1]} completos e bases inicial/final positivas; prejuízo não vira CAGR."), annual.get('source_url', ''), rows[-1]['date'] if rows else None)
    dy = data('issuer_dividend_history'); by_year = {r['year']: r['dy'] for r in dy.get('years', [])}
    have = [y for y in required if by_year.get(y) is not None]
    add('dividends', 'Dividend yield acima de 5% em cada um dos últimos 5 anos',
        'fail' if any(by_year[y] <= 5 for y in have) else 'pass' if len(have) == 5 else 'unknown',
        f"{len(have)} de 5 anos com DY anual conferido. " + (dy.get('method') or 'O DY atual de 12 meses não substitui o histórico anual. Informe a base de preço usada.'), dy.get('source_url', ''))
    liquidity = market.get('average_daily_value'); currency = market.get('currency')
    valid = liquidity is not None and market.get('sessions') == 20 and app.age(market.get('asof', '')) <= 7
    # Keep the threshold and observed turnover in the same currency; no current FX over historical prices.
    threshold = 10_000_000 if currency == 'BRL' else 2_000_000 if currency == 'USD' else None
    add('liquidity', 'Liquidez diária média acima de ' + ('R$ 10 milhões' if currency == 'BRL' or a['asset_type'] == 'stock' else 'US$ 2 milhões' if currency == 'USD' else 'limite da moeda'),
        ('pass' if liquidity > threshold else 'fail') if valid and threshold else 'unknown',
        (f"{liquidity:,.0f} {currency}/dia em {market.get('sessions')} pregões completos. Estimativa: fechamento × volume; corte de estudo na moeda local." if liquidity is not None else 'Faltam 20 pregões recentes com preço e volume.'), market.get('source_url', ''), market.get('asof'))
    counts = {s: sum(c['status'] == s for c in checks) for s in ('pass', 'fail', 'unknown')}
    return {'checks': checks, 'counts': counts, 'years': required,
        'summary': f"{counts['pass']} de {len(checks)} critérios atendidos · {counts['fail']} a revisar · {counts['unknown']} sem dados.",
        'note': 'Checklist de estudo de longo prazo. Os critérios não determinam sozinhos se o preço compensa. Opiniões online não alteram esta avaliação.'}


def enrich(app, a):
    r = a['company_research']; snaps = a.get('snapshots', {})
    r['buy_hold'] = checklist(app, a)
    r['viability'] = company_insights.viability(app, a)
    r['study'] = company_insights.complete_study(app, a)
    r['sector_focus'] = company_insights.focus(a, app.age)
    r['drivers'] = company_insights.drivers(app, a)
    r['statements'] = snaps.get('issuer_statements')
    r['governance'] = snaps.get('issuer_governance')
    for key, kind in [('profile', 'issuer_profile'), ('quarterly', 'issuer_quarters'), ('dividend_history', 'issuer_dividend_history'), ('market_history', 'issuer_market_history'), ('opinions', 'issuer_opinions')]:
        r[key] = snaps.get(kind)


def save(app, a, kind, payload, source):
    payload = validate_snapshot(app, kind, payload)
    if payload['symbol'] != symbol(a):
        raise ValueError('O histórico pertence a outra empresa.')
    asof = payload.get('asof') or (payload['quarters'][-1]['date'] if kind == 'issuer_quarters' else app.today().isoformat())
    with app.WRITE_LOCK, app.connect() as c:
        owner = c.execute('SELECT ticker,asset_type FROM assets WHERE id=? AND archived=0', (a['id'],)).fetchone()
        if not owner or symbol(dict(owner)) != payload['symbol']:
            raise ValueError('A empresa mudou durante a consulta.')
        old = app.latest(c, a['id']).get(kind, {}).get('data')
        if kind == 'issuer_governance' and source.startswith('Consulta pública') and old and payload['tag_along'] is None and old.get('tag_along') is not None:
            raise ValueError('A B3 não expõe o percentual desta classe; direito anteriormente conferido preservado. Revise o estatuto e a data.')
        if kind == 'issuer_quarters' and source.startswith('Consulta pública') and old and len(old['quarters']) > len(payload['quarters']):
            raise ValueError('Nova consulta tem menos trimestres; histórico anterior preservado.')
        if kind == 'issuer_statements' and old and source.startswith('Consulta pública'):
            # Merge absent fields/periods only when a source failed. A failure cannot erase older evidence.
            for bucket, limit in [('annual', 11), ('quarterly', 28)]:
                merged = {r['date']: dict(r) for r in old[bucket]}
                for row in payload[bucket]:
                    existing = merged.setdefault(row['date'], dict(row))
                    existing.update({k: v for k, v in row.items() if v is not None})
                payload[bucket] = sorted(merged.values(), key=lambda r: r['date'])[-limit:]
            payload['sources'] = {**old['sources'], **payload['sources']}
            payload = validate_snapshot(app, kind, payload)
        app.add_snapshot(c, a['id'], kind, payload, source, asof)
        app.log_source(c, kind + '_' + str(a['id']), a['ticker'] + ' · ' + kind.replace('issuer_', ''), payload.get('source_url', ''), asof=asof)
        if kind == 'issuer_drivers':
            for key, macro_key in [('rates','selic'), ('usd','usd')]:
                observation = payload['observations'].get(key)
                if not observation or app.age(observation['asof']) > 7: continue
                old_macro = c.execute('SELECT asof FROM macro WHERE key=?',(macro_key,)).fetchone()
                if old_macro and old_macro['asof'] > observation['asof']: continue
                c.execute('INSERT OR REPLACE INTO macro VALUES (?,?,?,?,?)',(macro_key,observation['current'],observation['asof'],observation['source'],app.now()))
                app.log_source(c,macro_key,'Selic meta · Banco Central' if key=='rates' else 'Dólar PTAX venda · Banco Central',observation['source_url'],asof=observation['asof'])


def refresh_current(app, a):
    """Refresh present metrics too; dossier updates used to skip this evidence."""
    if a['asset_type'] != 'stock':
        import stock_fundamentals
        try:
            warnings = stock_fundamentals.refresh_asset(app, a, force=True)
            return {'received': [] if warnings else ['stock_financials'], 'warnings': warnings}
        except ValueError as exc:
            return {'received': [], 'warnings': [str(exc)]}
    import public_fundamentals
    import os
    with app.connect() as c: token = app.settings(c).get('brapi_token') or os.getenv('BRAPI_TOKEN', '')
    received = {}; errors = []; supplemental = None
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [(ep, pool.submit(app.fetch_stock, a, ep, token)) for ep in ('quote', 'statistics', 'financial-data')]
        tasks.append(('fundamentus', pool.submit(public_fundamentals.fetch_detail, a['ticker'], app.today)))
        for ep, task in tasks:
            try:
                result = task.result()
                if ep == 'fundamentus': supplemental = result
                else:
                    kind, data, ref = result
                    received[kind] = (data, ref, 'brapi · stocks/'+ep)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                errors.append(ep+': '+(str(exc) if isinstance(exc, ValueError) else 'Formato público não reconhecido.'))
    if 'financial' in received and not received['financial'][1]:
        if 'statistics' in received:
            data, _, source = received['financial']; received['financial'] = (data, received['statistics'][1], source)
        else:
            received.pop('financial'); errors.append('Dados financeiros sem data contábil confirmada.')
    if supplemental:
        for kind, (data, ref) in supplemental.items():
            if kind not in received: received[kind] = (data, ref, 'Fundamentus · detalhes/'+a['ticker'])
    with app.WRITE_LOCK, app.connect() as c:
        owner = c.execute('SELECT ticker,asset_type FROM assets WHERE id=? AND archived=0', (a['id'],)).fetchone()
        if not owner or symbol(dict(owner)) != symbol(a): raise ValueError('A empresa mudou durante a consulta.')
        for kind, (data, ref, source) in received.items():
            ref = app.valid_date(ref)
            if ref > app.today().isoformat():
                errors.append(source+': referência futura, valores anteriores preservados.'); continue
            app.add_snapshot(c, a['id'], kind, data, source, ref)
            app.log_source(c, 'asset_'+str(a['id'])+'_'+kind, a['ticker']+' · '+kind,
                'https://brapi.dev/docs/acoes/dados-financeiros' if source.startswith('brapi') else public_fundamentals.BASE+'detalhes.php?papel='+a['ticker'], asof=ref)
        if supplemental and 'financial' in supplemental:
            fields = {k: v for group in ('financial', 'statistics') for k, v in supplemental.get(group, ({}, ''))[0].items() if k in app.sector_analysis.METRICS and v is not None}
            if fields:
                ref = app.valid_date(supplemental['financial'][1])
                if ref <= app.today().isoformat(): app.add_snapshot(c, a['id'], 'public', fields, 'Fundamentus · detalhes/'+a['ticker'], ref)
        for error in errors: app.log_source(c, 'issuer_current_'+str(a['id']), a['ticker']+' · consulta de indicadores', '', 'error', error=error)
    return {'received': list(received), 'warnings': errors}


def refresh(app, a, include_cvm=False):
    errors = []; received = []
    current = refresh_current(app, a)
    received.extend(current['received']); errors.extend(current['warnings'])
    statements = None
    if a['asset_type'] == 'stock':
        try:
            payload, warnings = company_insights.fetch_statements(app, a, brapi)
            save(app, a, 'issuer_statements', payload, 'Consulta pública · balanço, DRE e DFC / CVM via brapi')
            received.append('issuer_statements'); errors.extend(warnings)
            with app.connect() as c: statements = app.latest(c,a['id'])['issuer_statements']['data']
            annual = [{k:r.get(k) for k in ('date','net_income','revenue','operating_cashflow','free_cashflow')} for r in statements['annual'] if r['net_income'] is not None]
            if annual:
                import company_research
                company_research.save_annual(app,a,{'symbol':symbol(a),'currency':'BRL','years':annual,'source_url':statements['source_url']})
                received.append('issuer_financials')
        except ValueError as exc: errors.append(str(exc))
    if include_cvm and a['asset_type']=='stock':
        import public_reports
        try:
            with app.connect() as c: current=app.latest(c,a['id']).get('issuer_statements',{}).get('data',{})
            historical=not current or len(current.get('annual',[]))<11 or len(current.get('quarterly',[]))<20
            full_history=historical or any(r.get('operating_cashflow') is None for r in current.get('annual',[])[-5:])
            needed=full_history
            if not needed:
                needed=any(
                    r.get(k) is None for r in current.get('quarterly',[])[-4:] for k in ('net_income','current_assets','current_liabilities','operating_cashflow'))
            if needed:
                payload,warnings=public_reports.fetch_company(app,a,full_history=full_history)
                save(app,a,'issuer_statements',validate_snapshot(app,'issuer_statements',payload),'Consulta pública · CVM direta, DFP e ITR consolidados')
                errors.extend(warnings);received.append('cvm_direct')
                with app.connect() as c: statements=app.latest(c,a['id'])['issuer_statements']['data']
                annual=[{k:r.get(k) for k in ('date','net_income','revenue','operating_cashflow','free_cashflow')} for r in statements['annual'] if r['net_income'] is not None]
                if annual:
                    import company_research
                    company_research.save_annual(app,a,{'symbol':symbol(a),'currency':'BRL','years':annual,'source_url':payload['source_url']})
                    received.append('issuer_financials')
        except (ValueError,KeyError,TypeError) as exc:errors.append('CVM direta: '+(str(exc) if isinstance(exc,ValueError) else 'Formato não reconhecido; dados anteriores preservados.'))
    def quarters(app, a):
        if statements and any(r['net_income'] is not None for r in statements['quarterly']):
            return validate_snapshot(app,'issuer_quarters',{'symbol':symbol(a),'currency':'BRL',
                'quarters':[{k:r[k] for k in ('date','net_income','revenue')} for r in statements['quarterly']],
                'source_url':statements['sources'].get('income-statement',statements['source_url']).replace('period=annual','period=quarterly')})
        return fetch_quarters(app,a)
    for kind, fetcher in [('issuer_profile', fetch_profile), ('issuer_quarters', quarters), ('issuer_market_history', fetch_market)]:
        try:
            save(app, a, kind, fetcher(app, a), 'Consulta pública · histórico da empresa')
            received.append(kind)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            error = str(exc) if isinstance(exc, ValueError) else 'Formato da fonte não reconhecido; dados anteriores preservados.'
            errors.append(error)
            with app.WRITE_LOCK, app.connect() as c:
                app.log_source(c, kind + '_' + str(a['id']), a['ticker'] + ' · ' + kind.replace('issuer_', ''), '', 'error', error=error)
    if a['asset_type'] == 'stock':
        try:
            with app.connect() as c: profile = app.latest(c, a['id']).get('issuer_profile', {}).get('data', {})
            payload = company_insights.fetch_governance(app, a, profile)
            save(app, a, 'issuer_governance', payload, 'Consulta pública · B3 / segmento de listagem')
            received.append('issuer_governance')
        except (ValueError, KeyError, TypeError) as exc: errors.append(str(exc) if isinstance(exc, ValueError) else 'Governança B3 indisponível; confira o estatuto.')
    if include_cvm:
        try:
            import public_reports
            annual,events=public_reports.company_dividends(app,a)
            save(app,a,'issuer_dividend_history',annual,'Consulta pública · proventos e preços históricos Yahoo')
            received.append('issuer_dividend_history')
        except (ValueError,KeyError,TypeError) as exc:errors.append('Histórico de proventos: '+(str(exc) if isinstance(exc,ValueError) else 'Fonte sem série reconhecida.'))
    return {'received': received, 'warnings': errors}


def fetch_opinions(app, a):
    query = '"' + a['ticker'] + '" ' + ('(analysis OR opinion OR earnings)' if a['asset_type'] != 'stock' else '(análise OR opinião OR resultados)') + ' when:30d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': query, 'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'})
    headlines = market_brief.fetch_feed(url, datetime.now(timezone.utc))[:12]
    with app.WRITE_LOCK, app.connect() as c:
        old = app.latest(c, a['id']).get('issuer_opinions', {}).get('data', {})
        owner = c.execute('SELECT ticker,asset_type FROM assets WHERE id=? AND archived=0', (a['id'],)).fetchone()
        if not owner or symbol(dict(owner)) != symbol(a):
            raise ValueError('A empresa mudou durante a consulta.')
        manual = [r for r in old.get('items', []) if r['origin'] == 'manual'][:12]
        items = manual + [{'origin': 'rss', 'title': r['title'], 'text': '', 'author': r['publisher'], 'date': r['published_at'][:10], 'url': r['url']} for r in headlines]
        payload = validate_snapshot(app, 'issuer_opinions', {'symbol': symbol(a), 'items': items})
        app.add_snapshot(c, a['id'], 'issuer_opinions', payload, 'Google Notícias · títulos e publicações', app.today().isoformat())
        app.log_source(c, 'issuer_opinions_' + str(a['id']), a['ticker'] + ' · publicações online', url, asof=app.today().isoformat())
    return {'ok': True, 'count': len(headlines)}
