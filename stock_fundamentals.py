"""Public stock identity and dated financial inputs, separate from the BRL ledger."""
from datetime import datetime, timezone, timedelta
import math
import json
import urllib.parse

import international_market
import sector_analysis
import us_market
KINDS=('stock_profile','stock_financials','bdr_underlying_quote')
FIELDS={
 'trailingDilutedEPS':'eps', 'trailingNetIncome':'net_income',
 'trailingTotalRevenue':'revenue','trailingOperatingIncome':'ebit',
 'trailingOperatingCashFlow':'operating_cashflow','trailingFreeCashFlow':'free_cashflow',
 'trailingEBITDA':'ebitda','trailingInterestExpense':'interest',
 'quarterlyStockholdersEquity':'equity','quarterlyOrdinarySharesNumber':'shares',
 'quarterlyTotalDebt':'debt','quarterlyCashCashEquivalentsAndShortTermInvestments':'cash',
 'quarterlyCurrentAssets':'current_assets','quarterlyCurrentLiabilities':'current_liabilities'}
CURRENCIES={'BRL','USD','EUR','GBP','JPY','CAD','CHF','AUD','TWD','HKD','CNY','INR','KRW','SEK','NOK','DKK','ZAR','MXN','ILS','SGD'}


def bdr_listing(a):
    raw=a.get('bdr_listing','{}')
    return json.loads(raw) if isinstance(raw,str) else raw


def validate_bdr_listing(app,d):
    if not isinstance(d,dict) or set(d)!={'symbol','market','currency','source_url','asof'}:
        raise ValueError('Informe ticker, bolsa, moeda, fonte e data da empresa representada pelo BDR.')
    ticker=symbol(d['symbol'],d['market']);ref=app.valid_date(d['asof'])
    if d['currency'] not in international_market.MARKETS[d['market']]['currencies'] or ref>app.today().isoformat():
        raise ValueError('Moeda ou data da empresa do BDR incompatível.')
    url=app.validate_url(d['source_url'])
    if not url:raise ValueError('Informe a fonte que confirma a empresa representada pelo BDR.')
    return dict(symbol=ticker,market=d['market'],currency=d['currency'],source_url=url,asof=ref)


def research_identity(a):
    if a['asset_type']=='bdr':
        listing=bdr_listing(a)
        if not listing:raise ValueError('Vincule o BDR à empresa no exterior no cadastro para buscar fundamentos.')
        return listing['symbol'],listing['market']
    return a['ticker'],'US' if a['asset_type']=='foreign' else a.get('international',{}).get('listing',{}).get('market')


def symbol(ticker,market='US'):
    if not isinstance(market,str) or market not in international_market.MARKETS:raise ValueError('Bolsa da empresa inválida.')
    return us_market.symbol(ticker) if market=='US' else international_market.symbol(ticker,market)


def area(sector,industry):
    """Provider industry -> app research theme; this is not a GICS classification."""
    s=sector_analysis.fold(sector);i=sector_analysis.fold(industry)
    if s=='technology':return 'Tecnologia'
    if s=='healthcare':return 'Saúde'
    if s=='utilities':return 'Energia e saneamento'
    if s=='energy':return 'Petróleo e commodities'
    if s=='financial services':
        if 'bank' in i:return 'Bancos'
        if 'insurance' in i:return 'Seguros'
        return 'Serviços financeiros e holdings'
    if s=='basic materials':return 'Metais, mineração e siderurgia' if any(x in i for x in ('metal','steel','mining','gold','silver','copper','aluminum')) else 'Indústria e materiais'
    if s=='industrials':return 'Transportes e logística' if any(x in i for x in ('airline','railroad','shipping','logistic','transport','trucking')) else 'Indústria e equipamentos'
    if s=='communication services':return 'Telecomunicações' if 'telecom' in i else 'Comunicação e mídia'
    if s=='real estate':return 'Imobiliário'
    if s in ('consumer cyclical','consumer defensive'):
        if any(x in i for x in ('food','beverage','farm','agricultur')):return 'Alimentos e agronegócio'
        if 'education' in i:return 'Educação'
        if any(x in i for x in ('building','construction','residential')):return 'Construção e incorporação'
        if 'auto manufacturer' in i:return 'Indústria e equipamentos'
        return 'Varejo e consumo'
    return 'Não classificado'


def lookup(app,ticker,market='US'):
    ticker=symbol(ticker,market)
    query=urllib.parse.urlencode({'q':ticker,'quotesCount':5,'newsCount':0})
    raw=app.request_json('https://query1.finance.yahoo.com/v1/finance/search?'+query)
    matches=[r for r in raw.get('quotes',[]) if r.get('symbol')==ticker and r.get('quoteType')=='EQUITY'
             and r.get('exchange') in international_market.MARKETS[market]['exchanges']]
    if len(matches)!=1:raise ValueError('Ticker, empresa e bolsa não confirmados. Confira a listagem informada.')
    r=matches[0];sector=r.get('sector') or '';industry=r.get('industry') or ''
    return validate_snapshot(app,'stock_profile',{'symbol':ticker,'market':market,
        'name':str(r.get('longname') or r.get('shortname') or ticker)[:150],'sector_original':sector,
        'industry':industry,'sector':area(sector,industry),'source_url':'https://finance.yahoo.com/quote/'+ticker+'/profile/'})


def validate_snapshot(app,kind,d):
    if not isinstance(d,dict):raise ValueError('Pesquisa de stock inválida.')
    if kind=='bdr_underlying_quote':return international_market.validate_snapshot(app,'international_quote',d)
    if kind=='stock_profile':
        if set(d)!={'symbol','market','name','sector_original','industry','sector','source_url'}:
            raise ValueError('Identificação de stock incompleta.')
        ticker=symbol(d['symbol'],d['market'])
        if ticker!=d['symbol']:raise ValueError('Ticker da pesquisa não normalizado.')
        out={**d,'name':app.text_value(d['name'],200,True),
             'sector_original':app.text_value(d['sector_original'],120),
             'industry':app.text_value(d['industry'],200)}
        if d['sector']!=area(out['sector_original'],out['industry']):raise ValueError('Setor não corresponde à classificação da fonte.')
        if d['source_url']!='https://finance.yahoo.com/quote/'+ticker+'/profile/':raise ValueError('Fonte de identificação inválida.')
        return out
    if kind!='stock_financials' or set(d)!={'symbol','market','series','source_url'}:
        raise ValueError('Série de indicadores inválida.')
    ticker=symbol(d['symbol'],d['market'])
    if d['source_url']!='https://finance.yahoo.com/quote/'+ticker+'/financials/' or ticker!=d['symbol']:
        raise ValueError('Emissor ou fonte dos indicadores inválidos.')
    if not isinstance(d['series'],list) or not 1<=len(d['series'])<=500:raise ValueError('Série financeira vazia ou excessiva.')
    rows=[];seen=set()
    for r in d['series']:
        if not isinstance(r,dict) or set(r)!={'field','date','period','currency','value'} or r['field'] not in FIELDS:
            raise ValueError('Observação financeira inválida.')
        ref=app.valid_date(r['date']);expected='TTM' if r['field'].startswith('trailing') else '3M'
        if ref>app.today().isoformat() or r['period']!=expected or r['currency'] not in CURRENCIES:
            raise ValueError('Data, moeda ou período financeiro incompatível.')
        if type(r['value']) not in (int,float) or not math.isfinite(r['value']):raise ValueError('Indicador financeiro não numérico.')
        key=(r['field'],ref)
        if key in seen:raise ValueError('Observação financeira duplicada.')
        seen.add(key);rows.append({**r,'value':app.number(r['value'],True)})
    return {**d,'series':sorted(rows,key=lambda r:(r['date'],r['field']))}


def fetch(app,ticker,market):
    ticker=symbol(ticker,market)
    clock=datetime.now(timezone.utc)
    query=urllib.parse.urlencode({'type':','.join(FIELDS),'period1':int((clock-timedelta(days=800)).timestamp()),
                                'period2':int(clock.timestamp())})
    raw=app.request_json('https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/'+ticker+'?'+query)
    result=raw.get('timeseries',{})
    if result.get('error') or not isinstance(result.get('result'),list):raise ValueError('Indicadores públicos indisponíveis; anteriores preservados.')
    rows=[]
    for part in result['result']:
        meta=part.get('meta',{});keys=meta.get('type',[])
        if meta.get('symbol')!=[ticker] or len(keys)!=1 or keys[0] not in FIELDS:
            raise ValueError('A fonte retornou outro ticker ou indicador.')
        for r in part.get(keys[0],[]):
            value=r.get('reportedValue',{}).get('raw')
            if value is not None:rows.append({'field':keys[0],'date':r.get('asOfDate'),'period':r.get('periodType'),
                                             'currency':r.get('currencyCode'),'value':value})
    return validate_snapshot(app,'stock_financials',{'symbol':ticker,'market':market,'series':rows,
        'source_url':'https://finance.yahoo.com/quote/'+ticker+'/financials/'})


def derive(data,quote,age):
    """Every ratio joins an exact reference date and compatible reporting currencies."""
    series=data['series'];by={k:{} for k in FIELDS.values()}
    for r in series:by[FIELDS[r['field']]][r['date']]=r
    out={}
    def put(key,value,ref,currency,definition,basis):
        if value is not None and math.isfinite(value):out[key]={'value':value,'asof':ref,'currency':currency,'definition':definition,'basis':basis}
    for key in ('eps','operating_cashflow','free_cashflow'):
        if by[key]:
            r=by[key][max(by[key])];put(key,r['value'],r['date'],r['currency'],'Valor divulgado para os últimos 12 meses (TTM).',[r])
    def combine(keys,key,fn,definition):
        refs=set.intersection(*(set(by[k]) for k in keys))
        for ref in sorted(refs,reverse=True):
            rows=[by[k][ref] for k in keys]
            currencies={r['currency'] for k,r in zip(keys,rows) if k!='shares'}
            if len(currencies)!=1:continue
            value=fn(*[r['value'] for r in rows])
            if value is not None:put(key,value,ref,next(iter(currencies)),definition,rows)
            return
    positive_div=lambda a,b:a/b if b>0 else None
    combine(('equity','shares'),'bvps',positive_div,'Patrimônio/ações ordinárias no encerramento; estimativa por ação. Conferir classe, ADR e recompras.')
    combine(('debt','equity'),'debt_equity',positive_div,'Dívida total/patrimônio positivo no mesmo encerramento. Conferir arrendamentos.')
    combine(('debt','cash','equity'),'net_debt_equity',lambda d,c,e:(d-c)/e if e>0 else None,'(Dívida total − caixa e aplicações de curto prazo)/patrimônio positivo.')
    combine(('debt','cash','ebitda'),'net_debt_ebitda',lambda d,c,e:(d-c)/e if e>0 else None,'(Dívida total − caixa e aplicações de curto prazo)/EBITDA TTM positivo; mesma data. Conferir arrendamentos.')
    combine(('current_assets','current_liabilities'),'current_ratio',positive_div,'Ativo circulante/passivo circulante positivo no mesmo encerramento.')
    combine(('ebit','revenue'),'operating_margin',lambda a,b:100*a/b if b>0 else None,'Lucro operacional TTM/receita TTM, em percentual.')
    combine(('ebit','interest'),'interest_coverage',positive_div,'Lucro operacional TTM/despesa de juros TTM positiva.')
    for ref in sorted(set(by['net_income'])&set(by['equity']),reverse=True):
        income=by['net_income'][ref];end=by['equity'][ref]
        previous=[r for r in by['equity'].values() if 350<=(datetime.fromisoformat(ref)-datetime.fromisoformat(r['date'])).days<=380
                  and r['currency']==end['currency']]
        if previous and income['currency']==end['currency']:
            start=min(previous,key=lambda r:abs((datetime.fromisoformat(ref)-datetime.fromisoformat(r['date'])).days-365))
            average=(start['value']+end['value'])/2
            if start['value']>0 and end['value']>0:
                put('roe',100*income['value']/average,ref,end['currency'],'Lucro líquido TTM/patrimônio médio do início e fim de 12 meses. Recompras podem distorcer o ROE.',[income,start,end])
        break
    if quote and 0<=age(quote['asof'])<=7:
        q=quote['data']
        for base,key in (('eps','pe'),('bvps','pvp')):
            m=out.get(base)
            if m and m['value']>0 and q['currency']==m['currency'] and 0<=age(m['asof'])<=180 and m['asof']<=quote['asof']:
                put(key,q['price']/m['value'],quote['asof'],q['currency'],'Preço nativo dividido por '+base.upper()+' de '+m['asof']+'. Conferir classe/ADR e ajustes por desdobramento.',m['basis'])
    return out


def native_quote(a):
    return a.get('snapshots',{}).get('bdr_underlying_quote' if a['asset_type']=='bdr' else 'us_quote' if a['asset_type']=='foreign' else 'international_quote')


def enrich(a,age):
    if a['asset_type'] not in ('foreign','global_stock','bdr'):return
    if a['asset_type']=='bdr':
        a['bdr']={'listing':bdr_listing(a),'quote':native_quote(a),
            'note':'Fundamentos, múltiplos e correlações referem-se à ação da empresa no exterior, na moeda indicada. A cotação e a posição do BDR são em BRL. Paridade, câmbio e custos do programa podem alterar o retorno do recibo.'}
        if not a['bdr']['listing']:return
    snaps=a['snapshots'];p=snaps.get('stock_profile');f=snaps.get('stock_financials');q=native_quote(a)
    metrics=derive(f['data'],q,age) if f else {}
    a['stock_research']={'profile':p,'financials':f,'metrics':metrics,
        'currency':next((m['currency'] for key,m in metrics.items() if key=='eps'),None),
        'auto_sector':bool(a.get('auto_sector',0)),
        'note':'Setor e indústria são informados pela fonte pública e traduzidos para os temas do aplicativo. Bolsa americana não significa receita concentrada nos EUA. Confira área econômica, países e pesos nos relatórios.'}


def refresh_asset(app,a,force=False):
    ticker,market=research_identity(a)
    if not market:
        with app.connect() as c:market=app.latest(c,a['id']).get('international_listing',{}).get('data',{}).get('market')
    ticker=symbol(ticker,market);warnings=[]
    with app.connect() as c:old=app.latest(c,a['id'])
    loaders=[('stock_profile',lambda:lookup(app,ticker,market),7),('stock_financials',lambda:fetch(app,ticker,market),1)]
    quote_refs={}
    if a['asset_type']=='bdr':
        def load_quote():
            raw=app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?range=5d&interval=1d')
            data,ref=international_market.parse_quote(app,a,bdr_listing(a),raw)
            quote_refs['asof']=ref
            return {**data}
        loaders.insert(0,('bdr_underlying_quote',load_quote,0))
    for kind,loader,ttl in loaders:
        if not force and old.get(kind) and app.age(old[kind]['retrieved_at'])<ttl:continue
        try:
            data=loader();ref=quote_refs['asof'] if kind=='bdr_underlying_quote' else app.today().isoformat() if kind=='stock_profile' else max(r['date'] for r in data['series'])
            with app.WRITE_LOCK,app.connect() as c:
                current=c.execute('SELECT * FROM assets WHERE id=?',(a['id'],)).fetchone()
                if not current or current['archived'] or current['ticker']!=a['ticker'] or current['asset_type']!=a['asset_type']:
                    raise ValueError('Cadastro alterado durante a consulta; tente novamente.')
                if a['asset_type']=='global_stock' and app.latest(c,a['id']).get('international_listing',{}).get('data',{}).get('market')!=market:
                    raise ValueError('Bolsa alterada durante a consulta.')
                if a['asset_type']=='bdr' and bdr_listing(dict(current))!=bdr_listing(a):
                    raise ValueError('Vínculo do BDR alterado durante a consulta.')
                app.add_snapshot(c,a['id'],kind,data,'Yahoo Finance · stocks/'+ticker,ref)
                if kind=='stock_profile' and current['auto_sector']:
                    if data['sector']!='Não classificado':c.execute('UPDATE assets SET sector=? WHERE id=?',(data['sector'],a['id']))
                    previous=old.get(kind,{}).get('data',{}).get('name')
                    if current['name'] in (a['ticker'],previous):c.execute('UPDATE assets SET name=? WHERE id=?',(data['name'],a['id']))
                app.log_source(c,kind+'_'+str(a['id']),a['ticker']+' · '+('setor e indústria' if kind=='stock_profile' else 'cotação da empresa' if kind=='bdr_underlying_quote' else 'indicadores'),data.get('source_url','https://finance.yahoo.com/quote/'+ticker+'/'),asof=ref)
        except ValueError as exc:
            warnings.append(str(exc))
            with app.WRITE_LOCK,app.connect() as c:app.log_source(c,kind+'_'+str(a['id']),a['ticker']+' · pesquisa pública',
                'https://finance.yahoo.com/quote/'+ticker+'/','error',error=str(exc))
    return warnings
