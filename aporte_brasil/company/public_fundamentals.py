"""Dated public company data. Never equate EV/EBITDA with net debt/EBITDA."""
from html.parser import HTMLParser
from datetime import datetime
import re
import urllib.request
from aporte_brasil.portfolio import sector_analysis

BASE = 'https://www.fundamentus.com.br/'

class Cells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.cells=[]; self.parts=None
    def handle_starttag(self, tag, attrs):
        if tag in ('td','th'): self.parts=[]
    def handle_data(self, data):
        if self.parts is not None: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.parts is not None:
            self.cells.append(' '.join(' '.join(self.parts).split())); self.parts=None

def fetch_html(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 AporteBrasil/1.0'}),timeout=8) as r:
            raw=r.read(4_000_001)
        if len(raw)>4_000_000: raise ValueError('Página excedeu o limite de leitura.')
        return raw.decode('iso-8859-1')
    except OSError:
        raise ValueError('Fundamentus indisponível; dados anteriores preservados.')

def parse_detail(html,ticker,today):
    parser=Cells(); parser.feed(html); cells=parser.cells
    pairs={}
    for i,label in enumerate(cells[:-1]):
        if label.startswith('?'):
            pairs.setdefault(sector_analysis.fold(label.lstrip('?').strip()),cells[i+1])
    if pairs.get('papel')!=ticker: raise ValueError('Página não corresponde ao ticker solicitado.')
    def num(key):
        raw=pairs.get(sector_analysis.fold(key),'').replace('%','').replace('.','').replace(',','.').strip()
        if not re.fullmatch(r'-?\d+(\.\d+)?',raw): return None
        return float(raw)
    def dated(key):
        try: value=datetime.strptime(pairs[sector_analysis.fold(key)],'%d/%m/%Y').date()
        except (KeyError,ValueError): raise ValueError('Fundamentus sem data verificável de cotação/balanço.')
        if value>today(): raise ValueError('Fonte retornou data futura.')
        return value.isoformat()
    quote_date,period=dated('Data últ cot'),dated('Últ balanço processado')
    equity,debts=num('Patrim. Líq'),num('Dív. Bruta')
    finance={'roe':num('ROE'),'current_ratio':num('Liquidez Corr'),'operating_margin':num('Marg. EBIT'),'eps':num('LPA'),'bvps':num('VPA'),
             'debt_equity':debts/equity if equity and equity>0 and debts is not None else None,
             'net_debt_equity':num('Dív Líq / Patrim'),'roic':num('ROIC')}
    # This site publishes EV/EBITDA, not debt/EBITDA. No substitution is allowed.
    fresh_quote=(today()-datetime.fromisoformat(quote_date).date()).days<=7
    return {'quote':({'price':num('Cotação'),'change':num('Dia')},quote_date),
            'statistics':({'pvp':num('P/VP') if fresh_quote else None,'pe':num('P/L') if fresh_quote else None,'dy':num('Div. Yield')},period),
            'financial':(finance,period)}

def fetch_detail(ticker,today):
    if not re.fullmatch(r'[A-Z0-9]{4,12}',ticker): raise ValueError('Ticker brasileiro inválido.')
    return parse_detail(fetch_html(BASE+'detalhes.php?papel='+ticker),ticker,today)

def parse_universe(html):
    parser=Cells(); parser.feed(html); cells=parser.cells
    records=[]
    # Locate ticker rows by the first cell, independent of menus/headings.
    for i,ticker in enumerate(cells):
        if not re.fullmatch(r'[A-Z]{4}\d{1,2}',ticker) or i+21>=len(cells): continue
        row=cells[i:i+22]
        def n(k):
            try: return float(row[k].replace('%','').replace('.','').replace(',','.'))
            except ValueError: return None
        if n(18) is None or n(18)<=0: continue
        records.append({'ticker':ticker,'pvp':n(3),'pe':n(2),'roe':n(17),'net_debt_equity':n(20),
                        'current_ratio':n(15),'roic':n(16),'operating_margin':n(13),'liquidity':n(18)})
    if len(records)<10: raise ValueError('Tabela pública mudou de formato; referência anterior preservada.')
    return records
