"""Descriptive historical multiples from dated observations, never past-price targets."""
import math
import statistics

METHODS={'P/L histórico':('pe','eps'),'P/VP histórico':('pvp','bvps')}


def series(asset,key,age):
    months={}
    for r in asset.get('fundamental_history',{}).get(key,[]):
        value=r.get('value');ref=r.get('date','');days=age(ref)
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0 or not 31<=days<=1826:continue
        if ref>months.get(ref[:7],{}).get('date',''):months[ref[:7]]=r
    rows=sorted(months.values(),key=lambda r:r['date'])
    ready=len(rows)>=12 and age(rows[0]['date'])-age(rows[-1]['date'])>=730
    values=[r['value'] for r in rows]
    return dict(available=ready,count=len(rows),start=rows[0]['date'] if rows else None,end=rows[-1]['date'] if rows else None,
        mean=statistics.mean(values) if ready else None,median=statistics.median(values) if ready else None,observations=rows,
        note='Última observação de cada mês, entre 31 dias e cinco anos atrás; exige 12 meses distintos e ao menos dois anos de amplitude. Média histórica é comparação relativa, não valor justo. Mudanças de lucro, juros e risco podem invalidar a comparação.')


def attach(result,asset,age):
    stat=result['inputs'].get('historical_stat','mean');margin=result['inputs']['safety_margin'];price=result['inputs']['price']
    histories={key:series(asset,key,age) for key,_ in METHODS.values()}
    result['historical_multiples']=histories
    for name,(key,base) in METHODS.items():
        h=histories[key];value=result['inputs'].get(base);multiple=h[stat]
        value=value*multiple if type(value) in (int,float) and value>0 and multiple is not None else None
        premium=(price/value-1)*100 if price and value else None
        result['methods'].append(dict(method=name,value=value,ceiling=value*(1-margin/100) if value else None,
            reason=h['note'],formula=('LPA atual × ' if key=='pe' else 'VPA atual × ')+('média' if stat=='mean' else 'mediana')+' histórica do '+('P/L' if key=='pe' else 'P/VP'),
            family='historical_multiples',requirements=[base],missing=([base] if result['inputs'].get(base) is None else [])+([] if h['available'] else ['historical_'+key]),
            premium=premium,classification='unknown' if premium is None else 'below' if premium<0 else 'above',price_gap=None))
    return result
