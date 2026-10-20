"""International listings: domicile, economic exposure and trading currency are distinct.

Native quotes never overwrite a BRL portfolio price without a dated FX quote.
The existing US-equity forecasting pipeline remains restricted to its own universe.
"""
from datetime import datetime, timezone, date
import re
import urllib.parse

TYPES = ('global_stock', 'global_etf')
KINDS = ('international_listing', 'international_quote', 'international_fx')
MARKETS = {
    'US': {'label':'EUA', 'suffix':'', 'exchanges':{'NYQ','NMS','NGM','NCM','ASE','PCX','BTS'}, 'currencies':{'USD'}},
    'LSE': {'label':'Londres', 'suffix':'.L', 'exchanges':{'LSE'}, 'currencies':{'USD','GBP','EUR'}},
    'XETRA': {'label':'Xetra · Alemanha', 'suffix':'.DE', 'exchanges':{'GER'}, 'currencies':{'EUR'}},
    'AMS': {'label':'Euronext · Amsterdã', 'suffix':'.AS', 'exchanges':{'AMS'}, 'currencies':{'EUR'}},
}
CURRENCIES = ('USD','EUR','GBP')
VANGUARD = 'https://www.vanguard.co.uk/professional/product/etf/equity/9679/ftse-all-world-ucits-etf-usd-accumulating'
ISHARES = 'https://www.ishares.com/uk/individual/en/products/253743/CSSPX'
PRESETS = {
    'VWRA.L': {'name':'Vanguard FTSE All-World · acumulação', 'market':'LSE', 'currency':'USD', 'domicile':'IE', 'isin':'IE00BK5BQT80', 'distribution':'accumulating', 'scope':'GLOBAL', 'benchmark':'FTSE All-World', 'source_url':VANGUARD},
    'VWRP.L': {'name':'Vanguard FTSE All-World · acumulação', 'market':'LSE', 'currency':'GBP', 'domicile':'IE', 'isin':'IE00BK5BQT80', 'distribution':'accumulating', 'scope':'GLOBAL', 'benchmark':'FTSE All-World', 'source_url':VANGUARD},
    'CSPX.L': {'name':'iShares Core S&P 500 UCITS · acumulação', 'market':'LSE', 'currency':'USD', 'domicile':'IE', 'isin':'IE00B5BMR087', 'distribution':'accumulating', 'scope':'US', 'benchmark':'S&P 500', 'source_url':ISHARES},
}
for ticker,market in (('VWCE.DE','XETRA'),('VWCE.AS','AMS')):
    PRESETS[ticker]={**PRESETS['VWRA.L'],'market':market,'currency':'EUR'}
LISTING_KEYS = {'symbol','market','currency','domicile','isin','distribution','source_url','asof'}


def symbol(ticker, market):
    if not isinstance(market,str) or market not in MARKETS or not isinstance(ticker,str):
        raise ValueError('Escolha uma das bolsas internacionais disponíveis.')
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}',ticker):
        raise ValueError('Ticker internacional inválido.')
    suffix=MARKETS[market]['suffix']
    if suffix and (not ticker.endswith(suffix) or '.' in ticker[:-len(suffix)]):
        raise ValueError('Use o símbolo completo da bolsa, com '+suffix+'.')
    if not suffix and not re.fullmatch(r'[A-Z]{1,6}(?:-[A-Z]{1,2})?',ticker):
        raise ValueError('Use o símbolo americano, como AAPL ou BRK-B.')
    return ticker


def valid_isin(value):
    if not value: return True
    if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]',value): return False
    digits=''.join(str(ord(c)-55) if c.isalpha() else c for c in value)
    return sum((n*2//10+n*2%10) if i%2 else n for i,n in enumerate(map(int,reversed(digits))))%10==0


def listing(app,ticker,d):
    if not isinstance(d,dict) or set(d)!=LISTING_KEYS:
        raise ValueError('Informe bolsa, moeda, domicílio e fonte da listagem internacional.')
    if not isinstance(d['currency'],str): raise ValueError('Moeda de negociação inválida.')
    if symbol(ticker,d['market']) != d['symbol'] or d['currency'] not in MARKETS[d['market']]['currencies']:
        raise ValueError('Ticker ou moeda incompatível com a bolsa informada.')
    for k in ('domicile','isin','distribution','source_url','asof'): app.text_value(d[k],1500)
    if d['domicile']!='UNKNOWN' and not re.fullmatch(r'[A-Z]{2}',d['domicile']):
        raise ValueError('Domicílio: use o código de país ou A conferir.')
    if not valid_isin(d['isin']): raise ValueError('ISIN inválido; confira o documento do emissor.')
    if d['distribution'] not in ('accumulating','distributing','unknown','not_applicable'):
        raise ValueError('Política de distribuição inválida.')
    app.validate_url(d['source_url'])
    if not d['source_url']: raise ValueError('Informe o link do emissor ou da bolsa para conferir o cadastro.')
    if app.valid_date(d['asof'])>app.today().isoformat(): raise ValueError('Referência de cadastro futura.')
    preset=PRESETS.get(ticker)
    if preset and any(d[k]!=preset[k] for k in ('market','currency','domicile','isin','distribution')):
        raise ValueError('Esta listagem conhecida precisa corresponder à classe publicada pelo emissor.')
    return dict(d)


def validate_snapshot(app,kind,data):
    if not isinstance(data,dict): raise ValueError('Dados internacionais inválidos.')
    if kind=='international_listing': return listing(app,data.get('symbol'),data)
    if kind=='international_fx':
        if set(data)!={'symbol','currency','rate','target'} or data['currency'] not in CURRENCIES or data['symbol']!=data['currency']+'BRL=X' or data['target']!='BRL':
            raise ValueError('Câmbio internacional inválido.')
        if isinstance(data['rate'],bool): raise ValueError('Taxa de câmbio inválida.')
        return {**data,'rate':app.number(data['rate'],True,.00000001)}
    if kind!='international_quote' or set(data)!={'symbol','market','currency','price','exchange','instrument_type','issuer','raw_currency','scale'}:
        raise ValueError('Cotação internacional inválida.')
    symbol(data['symbol'],data['market'])
    m=MARKETS[data['market']]
    if not isinstance(data['currency'],str) or not isinstance(data['exchange'],str) or data['currency'] not in m['currencies'] or data['exchange'] not in m['exchanges'] or data['instrument_type'] not in ('ETF','EQUITY'):
        raise ValueError('Bolsa, moeda ou tipo não confirmado na cotação.')
    expected=.01 if data['raw_currency']=='GBp' and data['currency']=='GBP' else 1
    if data['raw_currency'] not in (data['currency'],'GBp') or data['raw_currency']=='GBp' and data['currency']!='GBP' or type(data['scale']) not in (int,float) or data['scale']!=expected:
        raise ValueError('Unidade monetária da cotação inválida.')
    if isinstance(data['price'],bool): raise ValueError('Preço inválido.')
    return {**data,'price':app.number(data['price'],True,.00000001),'issuer':app.text_value(data['issuer'],200,True)}


def parse_quote(app,a,l,raw):
    try: meta=raw['chart']['result'][0]['meta']
    except (KeyError,TypeError,IndexError): raise ValueError('Cotação internacional indisponível.') from None
    currency='GBP' if meta.get('currency')=='GBp' else meta.get('currency')
    expected='ETF' if a['asset_type']=='global_etf' else 'EQUITY'
    if meta.get('symbol')!=l['symbol'] or currency!=l['currency'] or meta.get('instrumentType')!=expected:
        raise ValueError('Ticker, moeda ou tipo diferente do cadastro; preço anterior preservado.')
    stamp=meta.get('regularMarketTime')
    if type(stamp) not in (int,float): raise ValueError('Data da cotação ausente.')
    day=datetime.fromtimestamp(stamp,timezone.utc).date().isoformat()
    if day>app.today().isoformat(): raise ValueError('Cotação futura rejeitada.')
    scale=.01 if meta['currency']=='GBp' else 1
    if isinstance(meta.get('regularMarketPrice'),bool): raise ValueError('Preço inválido.')
    price=app.number(meta.get('regularMarketPrice'),True,.00000001)*scale
    data={'symbol':l['symbol'],'market':l['market'],'currency':currency,'price':price,'exchange':meta.get('exchangeName'),
          'instrument_type':expected,'issuer':str(meta.get('longName') or meta.get('shortName') or l['symbol'])[:200],
          'raw_currency':meta['currency'],'scale':scale}
    return validate_snapshot(app,'international_quote',data),day


def fetch_fx(app,currency):
    ticker=currency+'BRL=X'
    try: m=app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/'+ticker+'?range=5d&interval=1d')['chart']['result'][0]['meta']
    except (KeyError,TypeError,IndexError): raise ValueError('Câmbio público indisponível.') from None
    if m.get('symbol')!=ticker or m.get('currency')!='BRL' or m.get('instrumentType')!='CURRENCY':
        raise ValueError('Par de câmbio não confirmado.')
    if type(m.get('regularMarketTime')) not in (int,float): raise ValueError('Câmbio sem data.')
    day=datetime.fromtimestamp(m['regularMarketTime'],timezone.utc).date().isoformat()
    if day>app.today().isoformat(): raise ValueError('Câmbio futuro.')
    return validate_snapshot(app,'international_fx',{'symbol':ticker,'currency':currency,'rate':m.get('regularMarketPrice'),'target':'BRL'}),day


def brl_conversion(app,data):
    """Keep the original conversion evidence across backup restoration."""
    keys={'native_price','native_currency','native_asof','fx_rate','fx_asof'}
    if not keys & set(data): return {}
    if not keys <= set(data) or data['native_currency'] not in CURRENCIES:
        raise ValueError('Referência de conversão BRL incompleta.')
    if isinstance(data['native_price'],bool) or isinstance(data['fx_rate'],bool):
        raise ValueError('Preço ou câmbio inválido na conversão BRL.')
    native=app.number(data['native_price'],True,.00000001)
    rate=app.number(data['fx_rate'],True,.00000001)
    for key in ('native_asof','fx_asof'):
        if app.valid_date(data[key])>app.today().isoformat(): raise ValueError('Conversão com referência futura.')
    if abs((date.fromisoformat(data['native_asof'])-date.fromisoformat(data['fx_asof'])).days)>4:
        raise ValueError('Datas incompatíveis na conversão BRL.')
    value=app.number(data.get('price'),True,.00000001)
    if abs(value-native*rate)>max(.000001,value*1e-9): raise ValueError('Conversão BRL não corresponde ao preço e câmbio declarados.')
    return {**{k:data[k] for k in keys},'native_price':native,'fx_rate':rate}


def refresh_asset(app,a):
    with app.connect() as c: snapshot=app.latest(c,a['id']).get('international_listing')
    if not snapshot: raise ValueError('Complete a listagem internacional antes de consultar.')
    l=listing(app,a['ticker'],snapshot['data'])
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(l['symbol'],safe='')+'?range=5d&interval=1d'
    data,day=parse_quote(app,a,l,app.request_json(url))
    warnings=[]; fx=None
    try: fx,fx_day=fetch_fx(app,l['currency'])
    except ValueError: warnings.append('Preço nativo salvo; câmbio indisponível. Referência BRL anterior preservada.')
    source='Yahoo Finance · internacional/chart/'+l['symbol']
    with app.WRITE_LOCK,app.connect() as c:
        current=c.execute('SELECT * FROM assets WHERE id=?',(a['id'],)).fetchone()
        if not current or current['archived'] or current['ticker']!=a['ticker'] or current['asset_type']!=a['asset_type'] or app.latest(c,a['id']).get('international_listing',{}).get('data')!=l:
            raise ValueError('Cadastro alterado durante a consulta; atualize novamente.')
        app.add_snapshot(c,a['id'],'international_quote',data,source,day)
        if fx: app.add_snapshot(c,a['id'],'international_fx',fx,'Yahoo Finance · câmbio/'+fx['symbol'],fx_day)
        if fx and 0<=app.age(fx_day)<=7 and 0<=app.age(day)<=7 and abs((date.fromisoformat(day)-date.fromisoformat(fx_day)).days)<=4:
            app.add_snapshot(c,a['id'],'quote',{'price':data['price']*fx['rate'],'change':None,'native_price':data['price'],'native_currency':l['currency'],
                'native_asof':day,'fx_rate':fx['rate'],'fx_asof':fx_day},source+' + câmbio datado · conversão BRL',min(day,fx_day))
        elif fx: warnings.append('Preço nativo salvo; datas do câmbio e da cotação não permitem conversão BRL recente.')
        c.execute('UPDATE assets SET verified=1 WHERE id=?',(a['id'],))
        app.log_source(c,'international_'+str(a['id']),a['ticker']+' · '+MARKETS[l['market']]['label'],'https://finance.yahoo.com/quote/'+l['symbol']+'/',asof=day)
    return warnings


def enrich(a):
    if a['asset_type'] not in TYPES: return
    snaps=a['snapshots']; l=snaps.get('international_listing',{}).get('data',{})
    a['international']={'listing':l,'quote':snaps.get('international_quote'), 'fx':snaps.get('international_fx'),
        'analysis_url':'https://finance.yahoo.com/quote/'+urllib.parse.quote(a['ticker'],safe='')+'/',
        'composition_url':l.get('source_url','')}


def public_state():
    return {'markets':{k:v['label'] for k,v in MARKETS.items()},'currencies':list(CURRENCIES),
        'presets':[{'ticker':k,**v} for k,v in PRESETS.items()]}
