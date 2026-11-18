"""Tesouro positions, official reference prices and explicitly approximate scenarios.

Official current redemption quotes and the daily CSV supply observed prices. Scenario cash flows use
ACT/365.25 (not the official DU/252 rounding/calendar) and never overwrite a
statement balance. No investment order or account access is performed here.
"""
from __future__ import annotations
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import io
import json
import math
import re
import threading
import unicodedata
import urllib.request
from aporte_brasil.portfolio import tax_rules

CSV_URL = 'https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv'
SOURCE = 'https://www.tesourodireto.com.br/produtos/dados-sobre-titulos/historico-de-precos-e-taxas'
CURRENT_SOURCE = 'https://www.tesourodireto.com.br/produtos/dados-sobre-titulos/rendimento-dos-titulos'
CURRENT_URL = 'https://www.tesourodireto.com.br/o/rentabilidade/resgatar'
RULES = 'https://tesourodireto.com.br/sobre-o-tesouro/regras-e-regulamento'
CUSTODY = 'https://www.b3.com.br/data/files/CC/A7/6E/11/CC543910B371F339AC094EA8/OC%20014-2024-VPC%20Pol%C3%ADtica%20de%20tarifa%C3%A7%C3%A3o%20do%20Tesouro%20Direto_cobranca_semestral.pdf'
PRODUCTS = {
    'selic': {'label':'Tesouro Selic', 'indexer':'Selic', 'flow':'single'},
    'prefixado': {'label':'Tesouro Prefixado', 'indexer':'Prefixado', 'flow':'single'},
    'prefixado_cupom': {'label':'Tesouro Prefixado com Juros Semestrais', 'indexer':'Prefixado', 'flow':'coupon', 'coupon':10},
    'ipca': {'label':'Tesouro IPCA+', 'indexer':'IPCA+', 'flow':'single'},
    'ipca_cupom': {'label':'Tesouro IPCA+ com Juros Semestrais', 'indexer':'IPCA+', 'flow':'coupon', 'coupon':6},
    'renda': {'label':'Tesouro RendA+', 'indexer':'IPCA+', 'flow':'monthly', 'payments':240},
    'educa': {'label':'Tesouro Educa+', 'indexer':'IPCA+', 'flow':'monthly', 'payments':60},
    'igpm_cupom': {'label':'Tesouro IGP-M+ com Juros Semestrais', 'indexer':'Manual', 'flow':'coupon', 'coupon':6},
    'reserva': {'label':'Tesouro Reserva', 'indexer':'Selic', 'flow':'reserve'},
}
UPDATE_LOCK = threading.Lock()
IOF = (100,96,93,90,86,83,80,76,73,70,66,63,60,56,53,50,46,43,40,36,33,30,26,23,20,16,13,10,6,3,0)


def normalized(value):
    return re.sub(r'[^A-Z0-9+]', '', unicodedata.normalize('NFKD', value.upper()).encode('ascii','ignore').decode())


def kind_for(name):
    key=normalized(name)
    for kind in ('reserva','renda','educa','igpm_cupom','prefixado_cupom','ipca_cupom','prefixado','ipca','selic'):
        label=normalized(PRODUCTS[kind]['label'])
        if key.startswith(label):return kind
    return None


def add_months(day, count):
    year,month=divmod(day.year*12+day.month-1+count,12);month+=1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def validate_profile(app, value, reference=None):
    if not isinstance(value,dict):raise ValueError('Dados do Tesouro inválidos.')
    for key in ('quantity','purchase_rate'):
        if isinstance(value.get(key),bool):raise ValueError('Número inválido nos dados do Tesouro.')
    kind=value.get('kind')
    if not isinstance(kind,str) or kind not in PRODUCTS:raise ValueError('Escolha o tipo de Tesouro.')
    ref=reference or app.today()
    maturity=app.valid_date(value.get('maturity'),True)
    conversion=app.valid_date(value.get('conversion'),True)
    if PRODUCTS[kind]['flow']=='monthly':
        if not conversion:raise ValueError('Informe a data de conversão em renda.')
        start=date.fromisoformat(conversion)
        if (start.month,start.day)!=(1,15):raise ValueError('A conversão de RendA+ e Educa+ ocorre em 15 de janeiro do ano do título.')
        expected=add_months(start,PRODUCTS[kind]['payments']-1).isoformat()
        if maturity and maturity!=expected:raise ValueError('O vencimento deve ser a última parcela, não a data de conversão.')
        maturity=expected
    elif kind!='reserva' and not maturity:
        raise ValueError('Informe o vencimento exato do título conforme o extrato.')
    if PRODUCTS[kind]['flow']!='monthly':conversion=''
    if kind=='reserva':maturity=''
    if maturity and not (date(2000,1,1)<=date.fromisoformat(maturity)<=date(2200,12,31)):
        raise ValueError('Vencimento fora do intervalo permitido.')
    if PRODUCTS[kind]['flow']=='coupon':
        end=date.fromisoformat(maturity)
        allowed=((1,1),(7,1)) if kind in ('prefixado_cupom','igpm_cupom') else ((5,15),(8,15))
        if (end.month,end.day) not in allowed:raise ValueError('Confira o vencimento do título com juros semestrais no extrato.')
    purchase=app.valid_date(value.get('purchase_date'),True)
    if purchase and (date.fromisoformat(purchase)>ref or maturity and purchase>=maturity):
        raise ValueError('A liquidação da compra deve ser anterior ao vencimento e não pode ser futura.')
    single=value.get('single_lot',False)
    if not isinstance(single,bool):raise ValueError('Confirmação de compra única inválida.')
    if single and not purchase:raise ValueError('Informe a liquidação da compra única para estimar o IR.')
    basis=value.get('balance_basis','gross')
    if basis not in ('gross','net'):raise ValueError('Identifique se o saldo é bruto ou líquido.')
    quantity=app.number(value.get('quantity'),False,.00000001,1e9)
    rate=app.number(value.get('purchase_rate'),False,-50,1000)
    if kind=='reserva':quantity=rate=None
    return {'version':1,'kind':kind,'maturity':maturity,'conversion':conversion,
            'quantity':quantity,'purchase_date':purchase,'single_lot':single,
            'purchase_rate':rate,'balance_basis':basis}


def suggested(f, catalog):
    old=f.get('metadata',{}).get('tesouro_position')
    if old:return old
    kind=kind_for(f['name'])
    if not kind:return None
    year=re.search(r'\b(20\d\d|21\d\d)\b',f['name'])
    maturity=f.get('maturity','');conversion=''
    if kind in ('renda','educa') and year:
        conversion=year[0]+'-01-15'
        maturity=add_months(date.fromisoformat(conversion),PRODUCTS[kind]['payments']-1).isoformat()
    elif not maturity and year:
        matches=[q for q in catalog if q['kind']==kind and q['maturity'][:4]==year[0]]
        if len(matches)==1:maturity=matches[0]['maturity']
    ledger=f.get('metadata',{}).get('treasury',{})
    return {'version':1,'kind':kind,'maturity':maturity,'conversion':conversion,
            'quantity':ledger.get('quantity') or None,'purchase_date':'','single_lot':False,
            'purchase_rate':f['rate'] if f.get('rate_known') else None,'balance_basis':'gross'}


def identity(p):return p['kind']+'|'+p['maturity']


def quotes_for(market):
    """Latest observation per exact title; daily base prices remain separate."""
    merged={identity(q):q for q in market.get('quotes',[])}
    for q in market.get('live_quotes',[]):
        old=merged.get(identity(q))
        if not old or (q['asof'],q.get('asof_at',''))>=(old['asof'],old.get('asof_at','')):
            merged[identity(q)]=q
    return sorted(merged.values(),key=lambda q:(q['kind'],q['maturity']))


def parse_current(payload, today):
    if isinstance(payload,(str,bytes)):payload=json.loads(payload)
    if not isinstance(payload,dict) or not isinstance(payload.get('TesouroLegado'),list):
        raise ValueError('Formato das cotações atuais mudou.')
    quotes={}
    for group in ('TesouroLegado','Tesouro24x7'):
        rows=payload.get(group,[])
        if not isinstance(rows,list):raise ValueError('Formato das cotações atuais mudou.')
        for row in rows:
            if not isinstance(row,dict):continue
            try:
                name=row['treasuryBondName']
                if not isinstance(name,str):continue
                kind=kind_for(name)
                if not kind:continue
                maturity=date.fromisoformat(row['maturityDate'][:10])
                stamp=datetime.fromisoformat(row['lastMarketPricingDate'])
                if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone(timedelta(hours=-3)))
                stamp=stamp.astimezone(timezone(timedelta(hours=-3)))
                if stamp.date()>today or maturity<=stamp.date() or not date(2000,1,1)<=maturity<=date(2200,12,31):continue
                def price(key):
                    n=row.get(key)
                    if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<n<1e9:return None
                    return n
                def rate(key):
                    raw=row.get(key,'')
                    if not isinstance(raw,str):return None
                    if normalized(raw)=='SELIC':return 0.
                    match=re.search(r'([+-]?\s*\d+(?:[.,]\d+)?)\s*%',raw)
                    if not match:return None
                    n=float(match[1].replace(' ','').replace(',','.'))
                    return n if -50<=n<=1000 else None
                sell=price('unitaryRedemptionValue')
                if sell is None:continue
                buy=price('unitaryInvestmentValue')
                q={'kind':kind,'maturity':maturity.isoformat(),'asof':stamp.date().isoformat(),
                   'asof_at':stamp.isoformat(),'source':CURRENT_SOURCE,'reference':'current',
                   'sell_price':sell,'sell_rate':rate('redemptionProfitabilityFeeIndexerName'),
                   'buy_price':buy,'buy_rate':rate('investmentProfitabilityIndexerName') if buy else None,
                   'base_price':None}
                old=quotes.get(identity(q))
                if old and old['asof_at']==q['asof_at'] and old!=q:raise ValueError('Cotações atuais conflitantes para o mesmo título.')
                if not old or q['asof_at']>old['asof_at']:quotes[identity(q)]=q
            except (KeyError,TypeError,OverflowError):continue
            except ValueError as exc:
                if str(exc).startswith('Cotações atuais conflitantes'):raise
                continue
    if not quotes:raise ValueError('A fonte não trouxe cotações atuais válidas.')
    return sorted(quotes.values(),key=lambda q:(q['kind'],q['maturity']))


def fetch_current():
    req=urllib.request.Request(CURRENT_URL,headers={'User-Agent':'Mozilla/5.0 (compatible; AporteBrasil/14)','Accept':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:data=response.read(2_000_001)
        if len(data)>2_000_000:raise ValueError('Cotações atuais excederam o limite de leitura.')
        return data
    except (OSError,TimeoutError) as exc:raise ValueError('Cotações atuais indisponíveis.') from exc


def parse_csv(payload, today, requests=()):
    """Keep latest rows and purchase-day references; reject invalid/future rows."""
    if isinstance(payload,bytes):
        try:payload=payload.decode('utf-8-sig')
        except UnicodeDecodeError:payload=payload.decode('cp1252')
    reader=csv.DictReader(io.StringIO(payload),delimiter=';')
    required={'Tipo Titulo','Data Vencimento','Data Base','Taxa Compra Manha','Taxa Venda Manha','PU Compra Manha','PU Venda Manha','PU Base Manha'}
    if not required.issubset(reader.fieldnames or []):raise ValueError('Formato da base do Tesouro mudou; a referência anterior foi preservada.')
    latest={};history={};targets={}
    for ident,day in requests:targets.setdefault(ident,set()).add(day)
    for row in reader:
        kind=kind_for(row['Tipo Titulo'])
        if not kind or kind=='reserva':continue
        try:
            maturity=datetime.strptime(row['Data Vencimento'],'%d/%m/%Y').date()
            asof=datetime.strptime(row['Data Base'],'%d/%m/%Y').date()
            if asof>today or maturity<asof:continue
            def num(key,price=False):
                raw=row[key].strip().replace('.','').replace(',','.')
                if not raw:return None
                n=float(raw)
                if not math.isfinite(n) or not (-50<=n<=1000 if not price else 0<n<1e9):return None
                return n
            q={'kind':kind,'maturity':maturity.isoformat(),'asof':asof.isoformat(),
               'buy_rate':num('Taxa Compra Manha'),'sell_rate':num('Taxa Venda Manha'),
               'buy_price':num('PU Compra Manha',True),'sell_price':num('PU Venda Manha',True),
               'base_price':num('PU Base Manha',True)}
            if not q['base_price'] and not q['sell_price']:continue
            ident=identity(q)
            if ident not in latest or q['asof']>latest[ident]['asof']:latest[ident]=q
            elif q['asof']==latest[ident]['asof'] and q!=latest[ident]:
                raise ValueError('Há referências conflitantes na base do Tesouro; confira a fonte.')
            for target in targets.get(ident,()):
                delta=(date.fromisoformat(target)-asof).days
                key=ident+'|'+target
                if 0<=delta<=7 and (key not in history or q['asof']>history[key]['asof']):
                    history[key]=q
        except (TypeError,OverflowError):continue
        except ValueError as exc:
            if str(exc).startswith('Há referências'):raise
            continue
    if not latest:raise ValueError('A base não trouxe preços válidos; a referência anterior foi preservada.')
    return {'quotes':sorted(latest.values(),key=lambda q:(q['kind'],q['maturity'])),'history':history,'source':SOURCE}


def fetch_csv():
    req=urllib.request.Request(CSV_URL,headers={'User-Agent':'AporteBrasil/14','Accept':'text/csv'})
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            data=response.read(32_000_001)
        if len(data)>32_000_000:raise ValueError('Base do Tesouro excedeu o limite de leitura.')
        return data
    except (OSError,TimeoutError) as exc:raise ValueError('Não foi possível consultar o Tesouro. A referência anterior foi preservada.') from exc


def update(app):
    if not UPDATE_LOCK.acquire(blocking=False):raise ValueError('A consulta do Tesouro já está em andamento.')
    try:
        with app.connect() as c:
            previous=app.read_cache(c,'tesouro_market',{})
            rows=[dict(r) for r in c.execute("SELECT * FROM fixed WHERE type='Tesouro' AND archived=0")]
        targets=[]
        for f in rows:
            f['metadata']=json.loads(f['metadata']);p=suggested(f,quotes_for(previous))
            if p and p.get('maturity') and p.get('purchase_date'):targets.append((identity(p),p['purchase_date']))
            if p and p.get('maturity') and not p.get('quantity'):targets.append((identity(p),f['balance_date']))
        result=dict(previous);warnings=[];success=0
        with ThreadPoolExecutor(max_workers=2) as pool:
            daily=pool.submit(lambda:parse_csv(fetch_csv(),app.today(),targets))
            live=pool.submit(lambda:parse_current(fetch_current(),app.today()))
            try:
                data=daily.result();success+=1
                merged={identity(q):q for q in previous.get('quotes',[])}
                for q in data['quotes']:
                    if identity(q) not in merged or q['asof']>=merged[identity(q)]['asof']:merged[identity(q)]=q
                result['quotes']=sorted(merged.values(),key=lambda q:(q['kind'],q['maturity']))
                history=dict(previous.get('history',{}))
                for key,q in data['history'].items():
                    if key not in history or q['asof']>=history[key]['asof']:history[key]=q
                result.update(history=history,source=SOURCE)
            except (ValueError,OSError):warnings.append('Histórico diário indisponível; referências anteriores preservadas.')
            try:
                data=live.result();success+=1
                merged={identity(q):q for q in previous.get('live_quotes',[])}
                for q in data:
                    if identity(q) not in merged or q['asof_at']>=merged[identity(q)]['asof_at']:merged[identity(q)]=q
                result['live_quotes']=list(merged.values());result['live_retrieved_at']=app.now()
            except (ValueError,OSError):warnings.append('Cotações atuais indisponíveis; confira a data da referência exibida.')
        if not success:raise ValueError('Não foi possível consultar o Tesouro. As referências anteriores foram preservadas.')
        result.update(retrieved_at=app.now(),warnings=warnings)
        with app.WRITE_LOCK,app.connect() as c:app.write_cache(c,'tesouro_market',result)
        quotes=quotes_for(result)
        return {'count':len(quotes),'asof':max(q['asof'] for q in quotes),
                'asof_at':max((q.get('asof_at','') for q in quotes),default='') or None,
                'retrieved_at':result['retrieved_at'],'warnings':warnings}
    finally:UPDATE_LOCK.release()


def enrich(f, market, today):
    if f['type']!='Tesouro':return
    catalog=quotes_for(market);p=suggested(f,catalog)
    quote=next((q for q in catalog if p and (identity(q)==identity(p) or p['kind']=='reserva' and q['kind']=='reserva')),None)
    qty=p.get('quantity') if p else None
    quantity_source='informada' if qty else None
    ledger=f['metadata'].get('treasury',{})
    if p and not qty and ledger.get('quantity',0)>0:
        qty=ledger['quantity'];quantity_source='histórico importado'
    balance_quote=market.get('history',{}).get(identity(p)+'|'+f['balance_date']) if p else None
    if not balance_quote:
        balance_quote=next((q for q in market.get('quotes',[]) if p and identity(q)==identity(p) and q['asof']==f['balance_date']),None)
    if (p and not qty and p.get('balance_basis')=='gross' and ledger.get('valuation')!='cost'
        and balance_quote and balance_quote['asof']==f['balance_date'] and balance_quote.get('base_price') and f['balance']>0):
        qty=f['balance']/balance_quote['base_price'];quantity_source='estimada pelo saldo bruto e preço na mesma data'
    result={'profile':p,'configured':bool(f['metadata'].get('tesouro_position')),'quote':quote,
            'quantity':qty,'quantity_source':quantity_source,
            'market_value':qty*(quote.get('base_price') or quote.get('sell_price')) if qty and quote and (quote.get('base_price') or quote.get('sell_price')) else None,
            'sale_gross':qty*quote['sell_price'] if qty and quote and quote.get('sell_price') else None,
            'stale':not quote or (today-date.fromisoformat(quote['asof'])).days>(1 if quote.get('reference')=='current' else 7),
            'older_than_today':bool(quote and quote['asof']<today.isoformat())}
    result['quantity_mismatch']=bool(qty and ledger.get('quantity') is not None and abs(qty-ledger['quantity'])>1e-7)
    if p and p.get('purchase_date'):
        result['historical']=market.get('history',{}).get(identity(p)+'|'+p['purchase_date'])
    f['tesouro']=result


def public_state(market):
    return {'products':PRODUCTS,'quotes':quotes_for(market),'retrieved_at':market.get('retrieved_at'),
            'warnings':market.get('warnings',[]),'current_source':CURRENT_SOURCE,
            'source':SOURCE,'rules':RULES,'custody':CUSTODY}


def save(app, d):
    p=validate_profile(app,d)
    label=PRODUCTS[p['kind']]['label']
    title_date=p['conversion'] or p['maturity']
    name=label+(' '+title_date[:4] if title_date else '')
    payload={k:d.get(k,'') for k in ('id','institution','invested','balance','balance_date','notes')}
    payload['balance_date']=payload['balance_date'] or app.today().isoformat()
    payload['institution']=payload['institution'] or 'Não informada'
    payload.update(name=name,type='Tesouro',indexer=PRODUCTS[p['kind']]['indexer'],
                   maturity=p['maturity'],rate=p['purchase_rate'] if p['kind']!='igpm_cupom' else '',tax='',fee='',
                   tesouro_profile=p)
    return app.mutate('/api/fixed-simple',payload)


def schedule(p, asof, horizon=None):
    """Undiscounted cash-flow weights per original unit of face/VNI."""
    kind=p['kind'];spec=PRODUCTS[kind];end=date.fromisoformat(p['maturity']) if p['maturity'] else horizon
    if not end:return []
    rows=[]
    if spec['flow']=='monthly':
        start=date.fromisoformat(p['conversion']);n=spec['payments']
        weight=math.floor(100/n*1e6)/1e8
        for i in range(n):
            day=add_months(start,i)
            if day>asof:rows.append({'date':day.isoformat(),'principal':weight if i<n-1 else 1-(n-1)*weight,'coupon':0})
    elif spec['flow']=='coupon':
        day=end;weight=math.sqrt(1+spec['coupon']/100)-1
        while day>asof:
            rows.append({'date':day.isoformat(),'principal':1 if day==end else 0,'coupon':weight})
            day=add_months(day,-6)
    elif end>asof:rows=[{'date':end.isoformat(),'principal':1,'coupon':0}]
    return sorted(rows,key=lambda r:r['date'])


def years(start,end):return (date.fromisoformat(end)-start).days/365.25


def pv(flows, rate, start):
    return sum((r['principal']+r['coupon'])/(1+rate/100)**years(start,r['date']) for r in flows)


def sale_net(app,f,p,gross,day,costs=0,override=None):
    eligible=None
    if p['purchase_date']:
        eligible=p['kind'] not in ('renda','educa') or (day-date.fromisoformat(p['purchase_date'])).days>=60
    if override is not None:
        if override>gross:raise ValueError('O resgate líquido informado não pode superar o valor bruto da venda.')
        return {'net':override,'basis':'Resgate líquido informado; impostos e custos já descontados','ir':None,'iof':None,'costs':None,'eligible':eligible}
    if not p['single_lot'] or not p['purchase_date'] or not f['invested_known']:
        return {'net':None,'basis':'Informe o resgate líquido ou confirme custo remanescente e liquidação de uma compra única.','eligible':eligible}
    days=(day-date.fromisoformat(p['purchase_date'])).days
    if days<0:raise ValueError('A referência de preço é anterior à liquidação da compra.')
    gain=max(0,gross-f['invested']);iof=gain*(IOF[days]/100 if days<30 else 0)
    rate=tax_rules.regressive(days);ir=max(0,gain-iof)*rate/100
    eligible=p['kind'] not in ('renda','educa') or days>=60
    return {'net':max(0,gross-iof-ir-costs),'basis':'Estimativa para compra única com custo fiscal remanescente informado',
            'ir':ir,'iof':iof,'ir_rate':rate,'costs':costs,'days':days,'eligible':eligible}


def simulate(app,f,d,market):
    f=dict(f);f['metadata']=json.loads(f['metadata']) if isinstance(f['metadata'],str) else f['metadata']
    p=f['metadata'].get('tesouro_position')
    if not p:raise ValueError('Complete a identificação do Tesouro antes de simular.')
    p=validate_profile(app,p);spec=PRODUCTS[p['kind']];today=app.today()
    enrich(f,market,today);info=f['tesouro'];quote=info['quote']
    mode=d.get('valuation','statement')
    if mode not in ('statement','market'):raise ValueError('Escolha a referência da simulação.')
    warnings=[];rate_quote=None
    if info['quantity_mismatch']:warnings.append('A quantidade cadastrada difere da quantidade restante no histórico B3. Confira transferências, amortizações e novas operações antes de usar o preço oficial.')
    if info['quantity_source']=='estimada pelo saldo bruto e preço na mesma data':warnings.append('A quantidade foi estimada dividindo o saldo bruto pelo preço oficial na mesma data. Saldo intradiário, arredondamentos ou pagamentos podem causar diferenças; confira a quantidade no extrato.')
    if mode=='market':
        if info['sale_gross'] is None:raise ValueError('Informe quantidade e consulte uma referência de venda para este vencimento.')
        gross=info['sale_gross'];asof=date.fromisoformat(quote['asof']);rate=quote.get('sell_rate')
        rate_quote=quote
        if info['stale']:warnings.append('O preço oficial deste título tem mais de sete dias. Não representa uma oferta atual de resgate.')
    else:
        ledger=f['metadata'].get('treasury',{})
        if ledger.get('valuation')=='cost':raise ValueError('O registro ainda está pelo custo importado. Informe o saldo de mercado do extrato para simular.')
        if p['balance_basis']=='net':raise ValueError('Informe um saldo bruto para projetar os fluxos. O saldo líquido pode ser usado no campo de resgate líquido.')
        gross=f['balance'];asof=date.fromisoformat(f['balance_date'])
        rate=app.number(d.get('market_rate'),False,-50,1000)
        if (today-asof).days>7:warnings.append('O saldo do extrato tem mais de sete dias. Atualize-o antes de decidir.')
    if gross<=0:raise ValueError('Informe uma posição com valor bruto maior que zero.')
    if p['purchase_date'] and asof<date.fromisoformat(p['purchase_date']):raise ValueError('A referência deve ser posterior à liquidação da compra.')
    # A price quote's yield and a statement from another day are not combined silently.
    if rate is None and quote and quote['asof']==asof.isoformat():
        rate=quote.get('sell_rate')
        rate_quote=quote
        if mode=='statement' and quote.get('asof_at'):
            warnings.append('Usamos a taxa oficial publicada no mesmo dia do saldo. Como o extrato não informa horário, diferenças intradiárias podem afetar a aproximação.')
    if p['kind']=='reserva':rate=0
    if rate is None:raise ValueError('Informe a taxa de mercado desse título na data do saldo, ou use a referência oficial.')
    end=date.fromisoformat(p['maturity']) if p['maturity'] else date.fromisoformat(app.valid_date(d.get('horizon') or add_months(asof,12).isoformat()))
    if end<=asof:raise ValueError('A data final precisa ser posterior à referência da simulação.')
    if (end-asof).days>36525:raise ValueError('Prazo da simulação limitado a 100 anos.')
    flows=schedule(p,asof,end)
    if not flows:raise ValueError('Não há pagamentos futuros nesta referência.')
    base=pv(flows,rate,asof)
    # Anchor to the position's observed price: no invented VNA or estimated quantity.
    known_quantity=info['quantity'] if info['quantity_source'] in ('informada','histórico importado') else None
    face=1000*known_quantity if p['kind'] in ('prefixado','prefixado_cupom') and known_quantity else gross/base
    if p['kind'] in ('prefixado','prefixado_cupom') and known_quantity and abs(face*base/gross-1)>.03:
        warnings.append('A taxa e a quantidade informadas não reproduzem aproximadamente o saldo deste Prefixado. Confira esses dados e a data do saldo; os pagamentos usam R$ 1.000 de principal por título.')
    with app.connect() as c:macros={r['key']:dict(r) for r in c.execute('SELECT * FROM macro')}
    assumptions={}
    def scenario(key,macro_key=None,default=None,low=-50,high=100):
        raw=d.get(key);source='informada';ref=None
        if raw in (None,''):
            observed=macros.get(macro_key,{}) if macro_key else {}
            if observed.get('asof','')<=today.isoformat() and observed.get('value') is not None:
                raw=observed['value'];source='referência atual usada como cenário constante';ref=observed['asof']
            else:raw=default;source='premissa padrão' if default is not None else 'não informada'
        value=app.number(raw,False,low,high)
        assumptions[key]={'value':value,'source':source,'asof':ref}
        return value
    inflation=scenario('inflation','ipca' if spec['indexer']=='IPCA+' else None) if spec['indexer']=='IPCA+' or p['kind']=='igpm_cupom' else None
    selic=scenario('selic','selic') if p['kind'] in ('selic','reserva') else None
    growth=inflation if p['kind'] in ('ipca','ipca_cupom','renda','educa','igpm_cupom') else selic if p['kind'] in ('selic','reserva') else 0
    future_ir=scenario('future_ir',default=15,low=0)/100
    future_cost=scenario('future_cost',default=0,low=0,high=gross*10)
    sale_cost=scenario('sale_cost',default=0,low=0,high=gross)
    alternative=scenario('alternative_rate')
    override=app.number(d.get('sale_net'),False,0,gross)
    net=sale_net(app,f,p,gross,asof,sale_cost,override)
    if p['kind'] in ('renda','educa') and p['purchase_date'] and (today-date.fromisoformat(p['purchase_date'])).days<60:
        net['eligible']=False
        warnings.append('Esta compra ainda está na carência de 60 dias para venda. A comparação é hipotética.')
    if net.get('eligible') is False:warnings.append('A venda não estava liberada por carência na data de referência.')
    if p['kind'] in ('renda','educa'):
        warnings.append('RendA+/Educa+: custódia de venda depende do tempo de permanência; isenção dos fluxos depende da renda total. Informe os custos ou o resgate líquido do extrato. Na fase de renda, use o custo fiscal ainda não amortizado.')
    else:warnings.append('Custódia e tarifas não são presumidas: informe custos pendentes de venda e futuros de manutenção, ou utilize o resgate líquido do extrato. Selic/Reserva têm regras de isenção por investidor.')
    warnings.append('Fluxos e sensibilidade usam dias corridos/365,25 e taxa constante. Não reproduzem DU/252, feriados, arredondamentos ou VNA/VNI oficial. O fluxo nominal é uma aproximação calibrada ao saldo/preço informado.')
    warnings.append('IR futuro é uma premissa efetiva sobre rendimentos. Cupons são tratados como rendimento; custo remanescente é distribuído nas amortizações. Não constitui apuração fiscal e pode diferir em compras com ágio ou eventos anteriores.')
    warnings.append('A taxa da alternativa deve ser líquida de impostos e custos, incluindo o novo prazo de IR após reinvestir. Pagamentos intermediários da manutenção são reinvestidos à mesma taxa líquida até a data final.')
    cost=f['invested'] if f['invested_known'] else None
    remaining=sum(r['principal'] for r in flows)
    projected=[]
    if growth is None:warnings.append('Sem premissa para o indexador e sem referência macroeconômica disponível, mostramos a sensibilidade aos juros. Informe o índice futuro para projetar pagamentos e comparar a venda.')
    for r in flows if growth is not None else []:
        t=years(asof,r['date']);factor=(1+growth/100)**t
        principal=face*r['principal']*factor;coupon=face*r['coupon']*factor
        basis=cost*r['principal']/remaining if cost is not None else None
        taxable=max(0,principal-basis)+coupon if basis is not None else None
        tax=taxable*future_ir if taxable is not None else None
        amount=principal+coupon
        projected.append({'date':r['date'],'gross':amount,'principal':principal,'coupon':coupon,
                          'ir':tax,'net':amount-tax if tax is not None else None})
    def future_value(amount,start,r):return amount*(1+r/100)**years(start,end.isoformat())
    def held_value(r):
        return sum(future_value(v['net'],date.fromisoformat(v['date']),r) for v in projected)-future_cost
    comparison=None;threshold=None
    if cost is not None and net['net'] is not None and projected:
        def difference(r):return future_value(net['net'],asof,r)-held_value(r)
        lo,hi=-50.,100.
        if difference(lo)*difference(hi)<=0:
            for _ in range(70):
                mid=(lo+hi)/2
                if difference(lo)*difference(mid)<=0:hi=mid
                else:lo=mid
            threshold=(lo+hi)/2
        if alternative is not None:
            keep=held_value(alternative);sell=future_value(net['net'],asof,alternative);delta=sell-keep
            comparison={'keep':keep,'sell':sell,'difference':delta,'breakeven_net_rate':threshold,
                        'reading':'Vender e reinvestir termina acima neste cenário' if delta>0 else 'Manter termina acima neste cenário' if delta<0 else 'As alternativas empatam neste cenário',
                        'eligible':net.get('eligible'),'alternative_rate':alternative,'future_cost':future_cost}
        else:warnings.append('Retorno da nova aplicação não informado. A taxa de empate indica o retorno líquido necessário para igualar as alternativas neste cenário.')
    elif cost is None or net['net'] is None:
        warnings.append('A comparação líquida precisa do custo fiscal remanescente e do valor líquido de resgate. Sem esses dados, mostramos apenas os fluxos brutos e a sensibilidade.')
    stress=[]
    if p['kind']!='reserva':
        shock=scenario('shock',default=1,low=.01,high=20)
        for delta in (-shock,0,shock):
            target=rate+delta
            if target<=-50:continue
            value=gross*pv(flows,target,asof)/base
            stress.append({'rate':target,'delta_pp':delta,'gross':value,'change':(value/gross-1)*100})
    curve=None
    if p['purchase_rate'] is not None and p['kind']!='reserva':
        curve=face*pv(flows,p['purchase_rate'],asof)
    return {'asof':asof.isoformat(),'asof_at':quote.get('asof_at') if mode=='market' and quote else None,
            'end':end.isoformat(),'kind':p['kind'],'label':spec['label'],
            'valuation':mode,'gross':gross,'market_rate':rate,'sale':net,'comparison':comparison,
            'flows':projected,'flow_count':len(projected),'gross_payments':sum(v['gross'] for v in projected) if projected else None,
            'breakeven_net_rate':threshold,'assumptions':assumptions,
            'stress':stress,'at_contract_rate':curve,'warnings':list(dict.fromkeys(warnings)),
            'source':rate_quote.get('source',SOURCE) if rate_quote else SOURCE,'rules':RULES,'custody':CUSTODY}


def action(app,path,d):
    if path=='/api/tesouro/update':return update(app)
    if path=='/api/tesouro/save':return save(app,d)
    if path=='/api/tesouro/simulate':
        fid=int(app.number(d.get('id'),True,1,1e9))
        with app.connect() as c:
            f=c.execute("SELECT * FROM fixed WHERE id=? AND type='Tesouro' AND archived=0",(fid,)).fetchone()
            market=app.read_cache(c,'tesouro_market',{})
        if not f:raise ValueError('Tesouro não encontrado.')
        return simulate(app,dict(f),d,market)
    raise ValueError('Operação de Tesouro desconhecida.')
