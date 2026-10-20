"""Dated investment exposures and public instrument quotes, independent of holdings."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import copy
import re
import international_market
import sector_analysis
import us_market

REGIONS = {'BR': 'Brasil', 'US': 'Estados Unidos', 'GLOBAL': 'Global', 'EU': 'Europa', 'EM': 'Emergentes', 'UNKNOWN': 'A conferir'}
FOCUS = {'broad': 'Mercado amplo', 'sector': 'Setorial', 'mixed': 'Várias exposições', 'unknown': 'A conferir'}
CLASSES = {'equity':'Renda variável · ações','fixed_income':'Renda fixa','crypto':'Criptoativos','real_estate':'Imobiliário','mixed':'Multimercado','unknown':'A conferir'}
CVM = 'https://cvmweb.cvm.gov.br/SWB/Sistemas/SCW/CPublica/FormBuscaPartic.aspx?TpConsulta=5'
CDA = 'https://dados.cvm.gov.br/dataset/fi-doc-cda'
SSGA = 'https://www.ssga.com/us/en/intermediary/capabilities/equities/sector-investing/select-sector-etfs'
B3 = 'https://www.b3.com.br/pt_br/noticias/bdr-8AA8D0CC9E28FC2E019EB37004F01F47.htm'
CHECKED = '2026-10-06'


def entry(ticker, name, typ, market, scope, profiles, focus, benchmark, url, asset_class='equity'):
    return {'ticker': ticker, 'name': name, 'type': typ, 'market': market,
            'currency': 'USD' if market == 'US' else 'BRL', 'scope': scope,
            'profiles': profiles, 'focus': focus, 'benchmark': benchmark, 'asset_class':asset_class,
            'source_url': url, 'asof': CHECKED, 'composition_url': url, 'analysis_url': ''}


CATALOG = {r['ticker']: r for r in [
    entry('BOVA11', 'iShares Ibovespa', 'etf', 'B3', 'BR', [], 'broad', 'Ibovespa', 'https://www.blackrock.com/br/products/251816/ishares-ibovespa-fundo-de-ndice-fund'),
    entry('IVVB11', 'iShares S&P 500', 'etf', 'B3', 'US', [], 'broad', 'S&P 500 em reais', 'https://www.blackrock.com/br/products/251902/ishares-sp-500-fundo-de-investimento-em-cotas-de-fundo-de-indice'),
    entry('WRLD11', 'Investo FTSE Global Equities', 'etf', 'B3', 'GLOBAL', [], 'broad', 'FTSE Global All Cap / VT', 'https://www.investoetf.com/etf/wrld11/'),
    entry('IMAB11','It Now IMA-B','etf','B3','BR',['fixed_income'],'sector','IMA-B · títulos públicos indexados à inflação','https://www.itnow.com.br/imab11/','fixed_income'),
    entry('LFTB11','Investo Tesouro Selic e IPCA+','etf','B3','BR',['fixed_income'],'sector','MarketVector Brazil Treasury 760 Day Target Duration','https://www.investoetf.com/etf/lftb11/','fixed_income'),
    entry('HASH11','Hashdex Nasdaq CME Crypto Index','etf','B3','GLOBAL',['crypto_market'],'sector','Nasdaq CME Crypto Index','https://hashdex.com/pt-BR/products/HASH11/','crypto'),
    entry('EEM', 'iShares MSCI Emerging Markets', 'etf', 'US', 'EM', [], 'broad', 'MSCI Emerging Markets', 'https://www.ishares.com/us/products/239637/ishares-core-msci-emerging-markets-etf'),
    *[entry(t, name, 'etf', 'US', 'US', p, 'sector', index, SSGA) for t, name, p, index in (
        ('XLK', 'State Street Technology', ['technology'], 'Technology Select Sector'),
        ('XLF', 'State Street Financial', ['bank', 'insurance', 'financial_services'], 'Financial Select Sector'),
        ('XLE', 'State Street Energy', ['commodity'], 'Energy Select Sector'),
        ('XLV', 'State Street Health Care', ['health'], 'Health Care Select Sector'),
        ('XLI', 'State Street Industrial', ['industrial'], 'Industrial Select Sector'),
        ('XLU', 'State Street Utilities', ['utility'], 'Utilities Select Sector'))],
    *[entry(t, name, 'bdr', 'B3', 'US', ['technology'], 'sector', 'Empresa estrangeira; BDR negociado em reais', B3)
      for t, name in (('AAPL34', 'Apple'), ('MSFT34', 'Microsoft'), ('GOGL34', 'Alphabet'))]
]}
for ticker, area in {'XLK': 'technology', 'XLF': 'financial', 'XLE': 'energy', 'XLV': 'health-care', 'XLI': 'industrial', 'XLU': 'utilities'}.items():
    CATALOG[ticker]['composition_url'] = f'https://www.ssga.com/us/en/individual/etfs/state-street-{area}-select-sector-spdr-etf-{ticker.lower()}'
META_KEYS = {'scope', 'profiles', 'focus', 'benchmark', 'source_url', 'asof', 'composition_url', 'analysis_url'}

def meta_fields(d):
    return {k:copy.deepcopy(d[k]) for k in META_KEYS | ({'asset_class'} if 'asset_class' in d else set())}


def links(ticker, typ, market='B3'):
    if typ == 'crypto':
        return 'https://www.coinbase.com/price/bitcoin', ''
    if market == 'US':
        return 'https://finance.yahoo.com/quote/' + us_market.symbol(ticker) + '/', ''
    path = {'stock': 'acoes', 'bdr': 'bdrs', 'etf': 'etfs', 'fii': 'fundos-imobiliarios'}.get(typ)
    return ('https://statusinvest.com.br/' + path + '/' + ticker.lower(), '') if path else (CVM, CDA)


def is_fund(f):
    return 'fundo' in f['type'].lower() or f['type'] == 'Previdência'


def targets(s):
    return [{'entity': 'asset:' + a['ticker'], 'name': a['ticker'] + ' · ' + a['name']} for a in s['assets']] + [
        {'entity': 'fund:' + str(f['id']), 'name': f['name'] + ' · ' + f['type']} for f in s['fixed'] if is_fund(f)]


def validate_meta(app, meta):
    if not isinstance(meta, dict) or set(meta) not in (META_KEYS, META_KEYS|{'asset_class'}) or not isinstance(meta['scope'], str) or not isinstance(meta['focus'], str) or meta['scope'] not in REGIONS or meta['focus'] not in FOCUS:
        raise ValueError('Exposição inválida.')
    if 'asset_class' in meta and (not isinstance(meta['asset_class'],str) or meta['asset_class'] not in CLASSES):
        raise ValueError('Área de investimento inválida.')
    profiles = meta['profiles']
    if not isinstance(profiles, list) or len(profiles) > 12 or any(not isinstance(p, str) or p not in sector_analysis.PROFILES or p in ('etf', 'foreign', 'crypto') for p in profiles):
        raise ValueError('Escolha os setores econômicos da exposição.')
    if meta['focus'] in ('sector', 'mixed') and not profiles:
        raise ValueError('Uma exposição setorial precisa identificar pelo menos um setor.')
    family = meta.get('asset_class')
    allowed = {'fixed_income': {'fixed_income'}, 'crypto': {'crypto_market'}, 'real_estate': {'fii'}}
    if family in allowed and set(profiles) - allowed[family]:
        raise ValueError('Os setores precisam corresponder à área de investimento escolhida.')
    if family == 'equity' and set(profiles) & {'fixed_income', 'crypto_market', 'fii'}:
        raise ValueError('Renda variável de ações precisa de setores de empresas.')
    out = {**meta, 'profiles': list(dict.fromkeys(profiles)), 'benchmark': app.text_value(meta['benchmark'], 200), 'asof': app.text_value(meta['asof'], 10)}
    for key in ('source_url', 'analysis_url', 'composition_url'):
        out[key] = app.validate_url(meta[key])
    if out['asof'] and app.valid_date(out['asof']) > app.today().isoformat():
        raise ValueError('Exposição com data futura.')
    if meta['focus'] != 'unknown' and (not out['source_url'] or not out['asof']):
        raise ValueError('Informe a fonte e a data da exposição que conferiu.')
    return out


def validate_saved(app, saved, entities):
    if not isinstance(saved, dict) or len(saved) > 500:
        raise ValueError('Exposições do backup inválidas.')
    for entity, meta in saved.items():
        if entity not in entities:
            raise ValueError('Exposição não corresponde a um ativo ou fundo do backup.')
        validate_meta(app, meta)
    return saved


def metadata(a, saved):
    entity = 'asset:' + a['ticker']
    if entity in saved:
        return {**saved[entity], 'asset_class': saved[entity].get('asset_class', CATALOG.get(a['ticker'], {}).get('asset_class', 'unknown')), 'basis': 'Conferido pelo usuário'}
    typ = a['asset_type']
    known = CATALOG.get(a['ticker'])
    if known and known['type'] == typ:
        return {**meta_fields(known), 'basis': 'Objetivo publicado pelo emissor / B3'}
    if typ in international_market.TYPES:
        intl=a.get('international',{}); l=intl.get('listing',{}); preset=international_market.PRESETS.get(a['ticker']) if typ=='global_etf' else None
        analysis,composition=intl.get('analysis_url',''),intl.get('composition_url','')
        if preset:
            return {'scope':preset['scope'],'profiles':[],'focus':'broad','benchmark':preset['benchmark'],'source_url':preset['source_url'],
                'asof':'2026-10-06','composition_url':composition,'analysis_url':analysis,'basis':'Objetivo publicado pelo emissor; conferir carteira atual','asset_class':'equity'}
        if typ=='global_stock':
            return {'scope':'UNKNOWN',
                'profiles':[sector_analysis.profile(a)],'focus':'sector','benchmark':'','source_url':l.get('source_url',''),'asof':l.get('asof',''),
                'composition_url':composition,'analysis_url':analysis,'basis':'Setor informado; configure a região pelas receitas e exposição efetiva','asset_class':'equity'}
        return {'scope':'UNKNOWN','profiles':[],'focus':'unknown','benchmark':'','source_url':'','asof':'','composition_url':composition,
                'analysis_url':analysis,'basis':'Exposição não configurada','asset_class':'unknown'}
    analysis, composition = links(a['ticker'], typ, 'US' if typ == 'foreign' else 'B3')
    out = {'scope': 'UNKNOWN', 'profiles': [], 'focus': 'unknown', 'benchmark': '', 'source_url': '',
           'asof': '', 'composition_url': composition, 'analysis_url': analysis, 'basis': 'Exposição não configurada', 'asset_class':'unknown'}
    if typ in ('stock', 'foreign', 'fii'):
        out.update(scope='US' if typ == 'foreign' else 'BR',
                   profiles=[sector_analysis.profile({**a, 'asset_type': 'stock'})] if typ != 'fii' else ['fii'],
                   focus='sector', asset_class='real_estate' if typ=='fii' else 'equity', basis='Setor informado no cadastro; conferir exposição efetiva')
    return out


def instrument(a, saved):
    meta = metadata(a, saved)
    if a['asset_type'] in international_market.TYPES:
        intl=a.get('international',{}); q=intl.get('quote') or {}
        return {'type':a['asset_type'],'currency':intl.get('listing',{}).get('currency','USD'),'native_price':q.get('data',{}).get('price'),
            'native_asof':q.get('asof'),'native_source':q.get('source'),'exposure':meta,'analysis_url':meta['analysis_url'] or intl.get('analysis_url',''),
            'composition_url':meta['composition_url'] or intl.get('composition_url','')}
    quote = a.get('us', {}).get('quote', {}) if a['asset_type'] == 'foreign' else a.get('snapshots', {}).get('quote', {})
    currency = 'USD' if a['asset_type'] == 'foreign' else 'BRL'
    analysis, composition = links(a['ticker'], a['asset_type'], 'US' if currency == 'USD' else 'B3')
    return {'type': a['asset_type'], 'currency': currency, 'native_price': quote.get('data', {}).get('price'),
            'native_asof': quote.get('asof'), 'native_source': quote.get('source'), 'exposure': meta,
            'analysis_url': meta['analysis_url'] or analysis, 'composition_url': meta['composition_url'] or composition}


def validate_snapshot_meta(app, meta):
    if not isinstance(meta, dict) or set(meta) - {'basis','asset_class'} != META_KEYS:
        raise ValueError('Metadados de exposição inválidos.')
    plain = meta_fields(meta)
    if meta.get('basis') == 'Setor informado no cadastro; conferir exposição efetiva' and not plain['source_url'] and not plain['asof']:
        plain = {**plain, 'source_url': CVM, 'asof': app.today().isoformat()}
    validate_meta(app, plain)
    if 'basis' in meta:
        app.text_value(meta['basis'], 300, True)


def validate_quote(app, q):
    if not q:
        return
    if not isinstance(q, dict) or set(q) != {'price', 'currency', 'asof', 'source', 'retrieved_at'} or q['currency'] not in ('USD', 'BRL') or isinstance(q['price'], bool):
        raise ValueError('Cotação do instrumento inválida.')
    app.number(q['price'], True, .00000001)
    if app.valid_date(q['asof']) > app.today().isoformat():
        raise ValueError('Cotação futura no cenário.')
    app.text_value(q['source'], 500, True)
    app.text_value(q['retrieved_at'], 100, True)


def validate_instrument(app, d):
    if not isinstance(d, dict) or set(d) != {'type', 'currency', 'native_price', 'native_asof', 'native_source', 'exposure', 'analysis_url', 'composition_url'} or d['type'] not in ('stock', 'fii', 'etf', 'bdr', 'foreign', 'crypto', *international_market.TYPES) or d['currency'] not in ('USD', 'BRL','EUR','GBP'):
        raise ValueError('Instrumento do cenário inválido.')
    if (d['type'] in international_market.TYPES and d['currency'] not in international_market.CURRENCIES or d['type'] not in international_market.TYPES and d['currency'] != ('USD' if d['type'] == 'foreign' else 'BRL')) or isinstance(d['native_price'], bool):
        raise ValueError('Moeda do instrumento inválida.')
    app.number(d['native_price'], low=0)
    if d['native_asof'] and app.valid_date(d['native_asof']) > app.today().isoformat():
        raise ValueError('Cotação nativa futura.')
    if d['native_source'] is not None:
        app.text_value(d['native_source'], 500)
    validate_snapshot_meta(app, d['exposure'])
    for key in ('analysis_url', 'composition_url'):
        app.validate_url(d[key])


def validate_record_extras(app, record):
    from market_outlook import DIRECTIONS
    for key in ('funds', 'candidates'):
        if key in record and (not isinstance(record[key], list) or len(record[key]) > 150):
            raise ValueError('Lista de exposições do cenário inválida.')
    for f in record.get('funds', []):
        if not isinstance(f, dict) or set(f) != {'entity', 'name', 'type', 'cnpj', 'exposure', 'direction', 'coverage', 'quote'} or not re.fullmatch(r'fund:[1-9]\d*', f['entity']) or f['direction'] not in DIRECTIONS:
            raise ValueError('Fundo do cenário inválido.')
        for key, maximum in (('name', 200), ('type', 100), ('cnpj', 25), ('coverage', 300)):
            app.text_value(f[key], maximum)
        validate_snapshot_meta(app, f['exposure'])
        validate_quote(app, f['quote'])
    for r in record.get('candidates', []):
        keys = set(next(iter(CATALOG.values()))) | {'quote', 'direction', 'coverage', 'matched'}
        if not isinstance(r, dict) or set(r) not in (keys,keys-{'asset_class'}) or not re.fullmatch(r'[A-Z0-9.\-]{1,15}', r['ticker']) or r['type'] not in ('bdr', 'etf') or r['market'] not in ('B3', 'US') or r['direction'] not in DIRECTIONS or r['currency'] != ('USD' if r['market'] == 'US' else 'BRL'):
            raise ValueError('Referência de ETF/BDR inválida.')
        validate_meta(app, meta_fields(r))
        validate_quote(app, r['quote'])
        if r['quote'] and r['quote']['currency'] != r['currency']:
            raise ValueError('Moeda da referência não corresponde ao produto.')
        app.text_value(r['name'], 200, True)
        app.text_value(r['coverage'], 300, True)
        if not isinstance(r['matched'], list) or len(r['matched']) > 40:
            raise ValueError('Correspondência setorial inválida.')
        for m in r['matched']:
            if not isinstance(m, dict) or set(m) != {'profile', 'scope', 'direction'} or m['profile'] not in sector_analysis.PROFILES or m['scope'] not in REGIONS or m['direction'] not in DIRECTIONS:
                raise ValueError('Correspondência setorial inválida.')


def read_settings(app):
    with app.connect() as c:
        return app.read_cache(c, 'investment_exposures', {})


def fund_context(s, saved):
    rows = []
    for f in s['fixed']:
        if is_fund(f):
            meta = saved.get('fund:' + str(f['id'])) or {'scope': 'UNKNOWN', 'profiles': [], 'focus': 'unknown', 'benchmark': '',
                'source_url': '', 'asof': '', 'composition_url': CDA, 'analysis_url': CVM}
            points = f.get('metadata', {}).get('quotes', {}).get('points', [])
            last = max(points, key=lambda p: p['date']) if points else None
            raw = f.get('metadata', {}).get('quotes', {})
            q = {'price': last['value'], 'currency': 'BRL', 'asof': last['date'], 'source': raw['source'], 'retrieved_at': raw['retrieved_at']} if last else {}
            rows.append({'entity': 'fund:' + str(f['id']), 'name': f['name'], 'type': f['type'], 'cnpj': f.get('cnpj', ''), 'exposure': meta,
                         'direction': 'unknown', 'coverage': 'Composição a conferir', 'quote': q})
    return rows[:150]


def target_records(assets, fixed, saved):
    rows = []
    for a in assets:
        info = instrument(a, saved)
        rows.append({'entity': 'asset:' + a['ticker'], 'ticker': a['ticker'], 'name': a['name'],
                     'type': a['asset_type'], 'exposure': info['exposure'], 'currency': info['currency'],
                     'price': info['native_price'], 'price_asof': info['native_asof'], 'price_source': info['native_source'],
                     'analysis_url': info['analysis_url'], 'composition_url': info['composition_url']})
    for f in fund_context({'fixed': fixed}, saved):
        q = f['quote']
        rows.append({'entity': f['entity'], 'ticker': '', 'name': f['name'], 'type': 'fund', 'exposure': f['exposure'],
                     'currency': 'BRL', 'price': q.get('price'), 'price_asof': q.get('asof'), 'price_source': q.get('source'),
                     'analysis_url': f['exposure']['analysis_url'] or CVM, 'composition_url': f['exposure']['composition_url'] or CDA})
    return rows


def effect(meta, analysis):
    """No single-sector verdict for a diversified fund without weights/coverage."""
    if meta['scope'] == 'UNKNOWN' or meta['focus'] == 'unknown':
        return 'unknown', 'Exposição a configurar', []
    matched = []
    direct = []
    for sector in analysis['sectors']:
        region = sector.get('scope', 'BR')
        fits_region = region == meta['scope'] or region == 'GLOBAL' or meta['scope'] == 'GLOBAL'
        family=meta.get('asset_class','equity')
        fits_sector = (meta['focus'] == 'broad' and family == 'equity') or sector['profile'] in meta['profiles'] or (
            meta['focus']=='broad' and sector['profile']=={'fixed_income':'fixed_income','crypto':'crypto_market','real_estate':'fii'}.get(family))
        if fits_region and fits_sector and region != 'UNKNOWN':
            matched.append({'profile': sector['profile'], 'scope': region, 'direction': sector['direction']})
            if region == meta['scope'] or region == 'GLOBAL':
                direct.append(sector)
    if not matched:
        return 'unknown', 'Não detalhado neste cenário', []
    if meta['focus'] == 'broad' and meta.get('asset_class','equity') == 'mixed':
        return 'unknown', 'Multimercado; conferir classes, composição e pesos', matched
    if meta['focus'] == 'broad' and meta.get('asset_class','equity') == 'equity':
        direct = [s for s in direct if s['profile'] == 'general' and s.get('market_wide') is True]
        if not direct:
            return 'unknown', 'Relação parcial; conferir pesos e outros setores', matched
    elif set(meta['profiles']) - {s['profile'] for s in direct}:
        return 'unknown', 'Relação parcial; conferir composição e pesos', matched
    directions = {s['direction'] for s in direct}
    direction = 'unknown' if not directions or 'unknown' in directions else 'mixed' if len(directions) > 1 else next(iter(directions))
    return direction, 'Leitura condicional da exposição; sem pesos individuais', matched


def attach(assets, funds, analysis):
    for a in assets:
        a['direction'], a['coverage'], _ = effect(a['instrument']['exposure'], analysis)
    for f in funds:
        f['direction'], f['coverage'], _ = effect(f['exposure'], analysis)


def public_catalog(app, c):
    quotes = app.read_cache(c, 'investment_quotes', {})
    return [{**copy.deepcopy(r), 'quote': quotes.get(t, {})} for t, r in CATALOG.items()]


def candidates(app, analysis):
    with app.connect() as c:
        catalog = public_catalog(app, c)
    rows = []
    for r in catalog:
        direction, coverage, matched = effect(r, analysis)
        if not matched:
            continue
        analysis_url, _ = links(r['ticker'], r['type'], r['market'])
        rows.append({**r, 'analysis_url': analysis_url, 'direction': direction, 'coverage': coverage, 'matched': matched})
    return rows


def quote(app, ticker, typ, market):
    if market == 'B3' and not re.fullmatch(r'[A-Z][A-Z0-9]{3}\d{2}', ticker):
        raise ValueError('Ticker B3 inválido.')
    symbol = us_market.symbol(ticker) if market == 'US' else ticker + '.SA'
    data = app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/' + symbol + '?range=5d&interval=1d')
    try:
        meta = data['chart']['result'][0]['meta']
    except (KeyError, TypeError, IndexError):
        raise ValueError('Cotação pública indisponível.') from None
    currency = 'USD' if market == 'US' else 'BRL'
    types = {'ETF'} if typ == 'etf' else {'EQUITY'}
    # Yahoo labels these B3 ETFs as EQUITY. Accept that label only when the
    # exact instrument is independently identified by the issuer catalog.
    known = CATALOG.get(ticker, {})
    if typ == 'etf' and market == 'B3' and known.get('type') == 'etf' and known.get('market') == 'B3':
        types.add('EQUITY')
    if meta.get('symbol') != symbol or meta.get('currency') != currency or meta.get('instrumentType') not in types or meta.get('exchangeName') not in (us_market.EXCHANGES if market == 'US' else {'SAO'}):
        raise ValueError('Ticker, produto, bolsa ou moeda da cotação não confirmados.')
    timestamp = meta.get('regularMarketTime')
    if type(timestamp) not in (int, float):
        raise ValueError('Cotação sem data de referência.')
    try:
        day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        raise ValueError('Data da cotação inválida.') from None
    if day > app.today().isoformat():
        raise ValueError('Cotação futura rejeitada.')
    if isinstance(meta.get('regularMarketPrice'), bool):
        raise ValueError('Preço da cotação inválido.')
    return {'price': app.number(meta.get('regularMarketPrice'), True, .00000001), 'currency': currency,
            'asof': day, 'source': 'Yahoo Finance · chart/' + symbol, 'retrieved_at': app.now()}


def refresh_bdr(app, asset):
    q = quote(app, asset['ticker'], 'bdr', 'B3')
    with app.WRITE_LOCK, app.connect() as c:
        row = c.execute('SELECT ticker,asset_type,archived FROM assets WHERE id=?', (asset['id'],)).fetchone()
        if not row or row['ticker'] != asset['ticker'] or row['asset_type'] != 'bdr' or row['archived']:
            raise ValueError('Cadastro alterado durante a consulta.')
        app.add_snapshot(c, asset['id'], 'quote', {'price': q['price'], 'change': None}, q['source'], q['asof'])
        app.log_source(c, 'bdr_' + str(asset['id']), asset['ticker'] + ' · BDR em reais', 'https://finance.yahoo.com/quote/' + asset['ticker'] + '.SA/', asof=q['asof'])
    return q


def refresh_quotes(app, inputs):
    import market_ai
    s = app.state()
    bdrs = {a['ticker']: a for a in s['assets'] if a['asset_type'] == 'bdr'}
    tracked = {a['ticker']: a for a in s['assets'] if a['asset_type'] in ('bdr', 'etf')}
    requested = {t: (r['type'], r['market']) for t, r in CATALOG.items()}
    requested.update({t: ('bdr', 'B3') for t in bdrs})
    if len(requested) > 80:
        raise ValueError('Atualize os BDRs da carteira pelo botão Atualizar mercado; esta consulta aceita até 80 instrumentos.')
    saved, errors = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(quote, app, t, typ, market): t for t, (typ, market) in requested.items()}
        for i, future in enumerate(as_completed(jobs), 1):
            ticker = jobs[future]
            market_ai.progress(f'Cotações de ETFs e BDRs · {i}/{len(jobs)} · {ticker}')
            try:
                saved[ticker] = future.result()
            except Exception as exc:
                errors.append(ticker + ': ' + (str(exc) if isinstance(exc, ValueError) else 'Cotação indisponível; referência anterior preservada.'))
    with app.WRITE_LOCK, app.connect() as c:
        previous = app.read_cache(c, 'investment_quotes', {})
        previous.update(saved)
        app.write_cache(c, 'investment_quotes', previous)
        app.write_cache(c, 'investment_quote_errors', errors)
        for ticker, asset in tracked.items():
            q = saved.get(ticker)
            current = c.execute('SELECT ticker,asset_type,archived FROM assets WHERE id=?', (asset['id'],)).fetchone()
            if q and current and current['ticker'] == ticker and current['asset_type'] == asset['asset_type'] and not current['archived']:
                app.add_snapshot(c, asset['id'], 'quote', {'price': q['price'], 'change': None}, q['source'], q['asof'])
    if not saved:
        raise ValueError('Não foi possível atualizar as cotações. Referências anteriores preservadas; veja as pendências no painel.')
    market_ai.progress(f'{len(saved)} cotações atualizadas.' + (f' {len(errors)} pendências; confira o painel.' if errors else ''))


def save(app, d):
    if not isinstance(d, dict) or set(d) != {'entity', 'exposure'}:
        raise ValueError('Exposição inválida.')
    if d['entity'] not in {t['entity'] for t in targets(app.state())}:
        raise ValueError('Escolha um ativo ou fundo cadastrado.')
    meta = validate_meta(app, d['exposure'])
    with app.WRITE_LOCK, app.connect() as c:
        saved = app.read_cache(c, 'investment_exposures', {})
        saved[d['entity']] = meta
        app.write_cache(c, 'investment_exposures', saved)
    return {'ok': True}
