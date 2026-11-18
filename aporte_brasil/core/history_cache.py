"""Small, persistent adjusted-price cache. Opening a chart never fetches the network."""
import json
from datetime import datetime, timezone
from aporte_brasil.market import extra_sources
from aporte_brasil.market import us_market

def fresh(snapshot, years=1):
    if not snapshot or snapshot['data'].get('years',1)<years: return False
    try:
        elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(snapshot['retrieved_at'])).total_seconds()
        return 0<=elapsed<86400
    except (ValueError,TypeError): return False

def info(snapshot):
    if not snapshot: return {'points':0,'bytes':0,'cached':False}
    pts=snapshot['data'].get('prices',[])
    return {'points':len(pts),'bytes':len(json.dumps(snapshot['data']).encode()),
            'start':pts[0]['date'] if pts else None,'end':pts[-1]['date'] if pts else None,
            'years':snapshot['data'].get('years',1),'retrieved_at':snapshot['retrieved_at'],
            'source':snapshot['source'],'cached':fresh(snapshot)}

def fetch(app,d):
    aid=int(d['asset_id']);years=d.get('years',1)
    if isinstance(years,bool) or years not in (1,5) or not isinstance(d.get('force',False),bool):
        raise ValueError('Escolha um ou cinco anos de histórico.')
    with app.connect() as c:
        row=c.execute('SELECT * FROM assets WHERE id=? AND archived=0',(aid,)).fetchone()
        if not row or row['asset_type'] != 'foreign' and (not row['verified'] or row['asset_type'] not in ('stock','fii','etf')):
            raise ValueError('Histórico automático disponível para ações, FIIs e ETFs verificados da B3.')
        kind = 'us_history' if row['asset_type']=='foreign' else 'history'
        snapshot=app.latest(c,aid).get(kind)
        # A short request must not shrink a previously saved five-year series.
        years=max(years,snapshot['data'].get('years',1) if snapshot else 1)
        if fresh(snapshot,years) and not d.get('force'):return {**info(snapshot),'used_cache':True}
        ticker=row['ticker']
    result=us_market.fetch(ticker,app.request_json,app.today,years) if kind=='us_history' else extra_sources.yahoo(ticker,app.request_json,app.today,True,years)
    if kind not in result:raise ValueError('Fonte sem preços ajustados; histórico anterior preservado.')
    data,ref,source=result[kind]
    with app.WRITE_LOCK,app.connect() as c:
        current=c.execute('SELECT ticker,archived FROM assets WHERE id=?',(aid,)).fetchone()
        if not current or current['archived'] or current['ticker']!=ticker:raise ValueError('O ativo mudou; consulte novamente.')
        app.add_snapshot(c,aid,kind,data,source,ref)
        if kind=='us_history' and 'us_quote' in result:
            q,qd,qs=result['us_quote'];app.add_snapshot(c,aid,'us_quote',q,qs,qd)
        return {**info(app.latest(c,aid)[kind]),'used_cache':False}

def observations(app,c,aid):
    """Accounting series by accounting date, not by the date the site was visited."""
    result={}
    keys=('roe','net_debt_ebitda','debt_equity','roic','operating_cashflow','pe','pvp')
    kinds=('financial','public','risk',*('metric:'+k for k in keys))
    for row in c.execute('SELECT kind,data,asof,source,retrieved_at FROM snapshots WHERE asset_id=? AND kind IN ('+','.join('?' for _ in kinds)+') ORDER BY id',(aid,*kinds)):
        for k,v in json.loads(row['data']).items():
            if k in keys and isinstance(v,(int,float)) and not isinstance(v,bool):
                result.setdefault(k,{})[row['asof']]={'date':row['asof'],'value':v,'source':row['source']}
    for key in ('pe','pvp'):
        if key in result:
            months={}
            for r in sorted(result[key].values(),key=lambda r:r['date']):months[r['date'][:7]]=r
            result[key]=months
    return {k:sorted(v.values(),key=lambda p:p['date'])[-100:] for k,v in result.items()}
