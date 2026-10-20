"""Bounded public alternatives. Undated fundamentals stay in a reviewable reference."""
from datetime import datetime,timezone
from html.parser import HTMLParser
import html,json,math,re,urllib.request
import sector_analysis

SITES={'status':('Status Invest','https://statusinvest.com.br/acoes/'),
       'investidor':('Investidor10','https://investidor10.com.br/acoes/')}

def source_url(source,ticker):
    if source.startswith('Yahoo Finance · EUA'):return 'https://finance.yahoo.com/quote/'+ticker.replace('.', '-')+'/'
    if source.startswith('Yahoo Finance'):return 'https://finance.yahoo.com/quote/'+ticker+'.SA/'
    for label,base in SITES.values():
        if source.startswith(label):return base+ticker.lower()
    return ''
STATUS_KEYS={'p_l':'pe','p_vp':'pvp','dy':'dy','lpa':'eps','vpa':'bvps','roe':'roe','roic':'roic',
 'dividaliquida_patrimonioliquido':'net_debt_equity','dividaliquida_ebitda':'net_debt_ebitda',
 'liquidezcorrente':'current_ratio','margemebit':'operating_margin','payout':'payout'}
INVEST_KEYS={'p/l':'pe','p/vp':'pvp','dy':'dy','dividend yield':'dy','lpa':'eps','vpa':'bvps','roe':'roe','roic':'roic',
 'divida liquida / ebitda':'net_debt_ebitda','divida liquida/ebitda':'net_debt_ebitda',
 'divida liquida / pl':'net_debt_equity','divida liquida/pl':'net_debt_equity',
 'liquidez corrente':'current_ratio','margem ebit':'operating_margin','payout':'payout'}

def finite(v):
    try: n=float(v)
    except (ValueError,TypeError): return None
    return n if math.isfinite(n) and abs(n)<1e15 else None

class Page(HTMLParser):
    def __init__(self): super().__init__();self.canonical='';self.inputs={};self.values={};self.quote_date=''
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='link' and a.get('rel')=='canonical': self.canonical=a.get('href','')
        if tag=='input' and a.get('id')=='indicator-current': self.inputs['indicators']=a.get('value','')
        if a.get('data-indicator') and 'data-current-value' in a:
            self.values[sector_analysis.fold(a['data-indicator'])]=finite(a['data-current-value'])
        if 'last-update' in a.get('class','').split():
            m=re.search(r'ultima atualizacao (\d{2}/\d{2}/\d{4})',sector_analysis.fold(a.get('data-content','')))
            if m:self.quote_date=m[1]

def page_reference(name,raw,ticker,today):
    parser=Page();parser.feed(raw)
    source,base=SITES[name];url=base+ticker.lower()+('/' if name=='investidor' else '')
    if parser.canonical.rstrip('/')!=url.rstrip('/'): raise ValueError(source+': identidade do ticker não confirmada.')
    vals={}
    if name=='status':
        try: records=json.loads(parser.inputs.get('indicators',''))
        except (ValueError,TypeError): raise ValueError('Status Invest: formato dos indicadores não reconhecido.')
        if not isinstance(records,list): raise ValueError('Indicadores inválidos.')
        for row in records:
            if isinstance(row,dict) and row.get('Key') in STATUS_KEYS: vals[STATUS_KEYS[row['Key']]]=finite(row.get('Value'))
        m=re.search(r'Soma total de proventos[^>]*>.*?<span[^>]*class="sub-value"[^>]*>\s*R\$\s*([\d.,]+)',raw,re.S)
        if m:vals['dividends_per_share']=finite(m[1].replace('.','').replace(',','.'))
    else:
        vals={target:parser.values[k] for k,target in INVEST_KEYS.items() if k in parser.values}
    vals={k:v for k,v in vals.items() if v is not None}
    if not vals: raise ValueError(source+': sem indicadores reconhecidos.')
    groups={}
    if name=='investidor' and parser.quote_date:
        ref=datetime.strptime(parser.quote_date,'%d/%m/%Y').date()
        if ref>today(): raise ValueError('Investidor10: cotação futura rejeitada.')
        m=re.search(r'<span\s+title="Cotação">.*?<span\s+class="value">\s*R\$\s*([\d.,]+)',raw,re.S)
        price=finite(m[1].replace('.','').replace(',','.')) if m else None
        if price and price>0:groups['quote']=({'price':price,'change':None},ref.isoformat(),source+' · página/'+ticker)
    return {'groups':groups,'reference':{'source':source,'url':url,'values':vals,'balance_asof':None,
        'note':'Página sem data contábil vinculada aos indicadores extraídos. Valores para conferência; confirme o período no RI antes de incorporá-los ao checklist.'}}

def fetch_page(name,ticker,today):
    if not re.fullmatch('[A-Z0-9]{4,12}',ticker): raise ValueError('Ticker inválido.')
    url=SITES[name][1]+ticker.lower()+('/' if name=='investidor' else '')
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 AporteBrasil/1.0'}),timeout=8) as r: raw=r.read(3_000_001)
        if len(raw)>3_000_000:raise ValueError('Página excedeu o limite.')
        return page_reference(name,raw.decode('utf-8'),ticker,today)
    except (OSError,UnicodeError): raise ValueError(SITES[name][0]+' indisponível; fonte seguinte e dados anteriores mantidos.')

def yahoo(ticker,request,today,include_history=True,years=1):
    symbol=ticker+'.SA'
    window=str(years)+'y' if include_history else '5d'
    raw=request('https://query1.finance.yahoo.com/v8/finance/chart/'+symbol+'?range='+window+'&interval=1d')
    try:r=raw['chart']['result'][0];meta=r['meta']
    except (KeyError,TypeError,IndexError):raise ValueError('Yahoo Finance: resposta sem série reconhecida.')
    if meta.get('symbol')!=symbol or meta.get('currency')!='BRL':raise ValueError('Yahoo Finance: ticker/moeda não confirmados.')
    groups={};timestamp=meta.get('regularMarketTime');price=finite(meta.get('regularMarketPrice'))
    if timestamp and price and price>0:
        ref=datetime.fromtimestamp(timestamp,timezone.utc).date()
        if ref>today():raise ValueError('Yahoo Finance: cotação futura rejeitada.')
        groups['quote']=({'price':price,'change':finite(meta.get('regularMarketChangePercent'))},ref.isoformat(),'Yahoo Finance · chart/'+symbol)
    # Only adjusted closes: never substitute the raw series in technical trends.
    adj=(r.get('indicators',{}).get('adjclose') or [{}])[0].get('adjclose',[])
    pts=[]
    for ts,close in zip(r.get('timestamp',[]),adj):
        v=finite(close);ref=datetime.fromtimestamp(ts,timezone.utc).date()
        if v is not None and v>0 and ref<=today():pts.append({'date':ref.isoformat(),'close':v})
    pts=sorted({p['date']:p for p in pts}.values(),key=lambda p:p['date'])
    if pts and include_history:groups['history']=({'prices':pts,'years':years},pts[-1]['date'],'Yahoo Finance · chart/'+symbol)
    if not groups:raise ValueError('Yahoo Finance: cotação e histórico ajustado ausentes.')
    return groups
