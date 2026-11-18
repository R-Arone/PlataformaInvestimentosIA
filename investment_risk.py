"""Explicit sector assumptions and local overlap/correlation for new contributions."""
from datetime import date
import math
import statistics
import sector_analysis
import investment_exposure
import portfolio_coupling as coupling
import recommendation_signals as signals
DIMENSIONS=('Previsibilidade da demanda','Recorrência da receita','Resistência ao ciclo','Flexibilidade de capital','Visibilidade competitiva/regulatória')
# Authored 1–5 starting assumptions, not measured sector performance or agency ratings.
RATINGS={'bank':(4,4,3,3,3),'insurance':(4,4,3,3,3),'financial_services':(4,3,3,4,3),
 'utility':(5,4,4,2,3),'retail':(2,2,2,2,2),'commodity':(2,2,1,1,3),'metals':(2,2,1,1,3),
 'construction':(2,2,1,2,3),'transport':(3,3,2,1,3),'telecom':(4,4,3,1,3),
 'technology':(3,4,2,4,2),'health':(4,4,3,3,3),'education':(3,3,3,3,2),
 'food_agro':(4,3,2,2,3),'industrial':(3,3,2,2,3)}
FAMILY={'bank':'financial','insurance':'financial','financial_services':'financial'}
REFERENCES=[dict(title='MSCI · setores, ciclo e correlações variáveis',url='https://www.msci.com/research-and-insights/quick-take/changing-sectors-changing-correlations'),
 dict(title='Investor.gov · diversificação entre setores e dentro dos fundos',url='https://www.investor.gov/introduction-investing/getting-started/asset-allocation'),
 dict(title='Damodaran · risco dos negócios financeiros',url='https://pages.stern.nyu.edu/adamodar/New_Home_Page/littlebook/bankvaluedriver.htm')]


def profile(a):return a.get('sector_analysis',{}).get('profile') or sector_analysis.profile(a)


def rating(a):
    key=profile(a);values=RATINGS.get(key) if a.get('asset_type') in ('stock','foreign','global_stock','bdr') else None
    score=round(sum(values)/25*100) if values else None
    return dict(profile=key,label=sector_analysis.PROFILES.get(key,{'label':a.get('sector','Não classificado')})['label'],score=score,
        dimensions=[dict(label=k,value=v,maximum=5) for k,v in zip(DIMENSIONS,values or ())],
        assessment='Demanda relativamente previsível' if score is not None and score>=70 else 'Sensível ao ciclo' if score is not None and score>=55 else 'Mais cíclico' if score is not None else 'Sem nota estrutural aplicável',
        risks=sector_analysis.PROFILES.get(key,{}).get('risks',[])[:3],references=REFERENCES,
        note='Premissa qualitativa inicial do aplicativo, não estatística de estabilidade nem previsão de retorno. Segmentos e empresas podem divergir. Bancos têm risco de crédito, liquidez e captação; a nota não supera bloqueios de qualidade.')


def group(a):
    key=profile(a);typ=a.get('asset_type');meta=a.get('exposure',{})
    if typ in ('etf','global_etf','bdr'):
        profiles={FAMILY.get(p,p) for p in meta.get('profiles',[]) if p not in ('general','etf','foreign')}
        if meta.get('focus')=='sector' and len(profiles)==1 and meta.get('source_url'):
            key=next(iter(profiles))
        else:return dict(key=sector_analysis.fold(a.get('sector') or 'Não classificado'),label=a.get('sector') or 'Não classificado')
    if typ=='fii':
        segment=sector_analysis.fold(a.get('sector','Não classificado'))
        for name,words in [('Crédito imobiliário',('papel','recebive','credito')),('Logística',('logistic',)),('Shopping',('shopping',)),('Escritórios',('laje','escritorio'))]:
            if any(w in segment for w in words):return dict(key='fii:'+sector_analysis.fold(name),label='FIIs · '+name)
        return dict(key='fii:'+segment,label='FIIs · '+a.get('sector','Não classificado'))
    if key=='general':return dict(key=sector_analysis.fold(a.get('sector') or 'Não classificado'),label=a.get('sector') or 'Não classificado')
    family=FAMILY.get(key,key)
    return dict(key='profile:'+family,label='Financeiro · bancos, seguros e serviços' if family=='financial' else sector_analysis.PROFILES.get(key,{'label':a.get('sector','Não classificado')})['label'])


def tags(app,a):
    direct={group(a)['key']};meta=a.get('exposure',{})
    if a.get('asset_type') in ('etf','global_etf','bdr') and (not meta.get('source_url') or not signals.fresh(app,meta.get('asof'),365)):return direct
    return direct|{'profile:'+FAMILY.get(p,p) for p in meta.get('profiles',[]) if p not in ('general','etf','foreign')}|{'theme:'+t for t in meta.get('themes',[])}


def history(app,a):
    if a.get('asset_type') not in ('stock','fii','etf','bdr') or a.get('value_at_cost'):return {}
    if not signals.fresh(app,a.get('snapshots',{}).get('quote',{}).get('asof'),7):return {}
    if a.get('snapshots',{}).get('history',{}).get('data',{}).get('currency','BRL')!='BRL':return {}
    points=coupling.completed_prices(a,app.today(),app.now())
    return points if len(points)>=64 and signals.fresh(app,next(reversed(points)),7) else {}


class Plan:
    def __init__(self,app,state):
        self.app=app;self.assets={a['id']:a for a in state['assets']};self.groups={i:group(a) for i,a in self.assets.items()}
        self.tags={i:tags(app,a) for i,a in self.assets.items()};self.prices={i:history(app,a) for i,a in self.assets.items()};self.pairs={}
        self.values={i:max(0,a['value']) for i,a in self.assets.items()};self.limit=state['settings']['sector_limit']

    def pair(self,left,right):
        key=tuple(sorted((left,right)))
        if key not in self.pairs:
            a,b=(self.prices[i] for i in key);dates=sorted(set(a)&set(b))[-253:];result=None
            if len(dates)>=64 and signals.fresh(self.app,dates[-1],7) and all((date.fromisoformat(y)-date.fromisoformat(x)).days<=7 for x,y in zip(dates,dates[1:])):
                x=[math.log(a[y]/a[t]) for t,y in zip(dates,dates[1:])];y=[math.log(b[y]/b[t]) for t,y in zip(dates,dates[1:])]
                sx,sy=statistics.stdev(x),statistics.stdev(y)
                if min(sx,sy)>1e-10:result=dict(correlation=max(-1,min(1,coupling.covariance(x,y)/(sx*sy))),n=len(x),start=dates[0],end=dates[-1])
            self.pairs[key]=result
        return self.pairs[key]

    def assess(self,aid,values=None):
        values=self.values if values is None else values;total=sum(values.values());group=self.groups[aid]
        same=sum(v for i,v in values.items() if self.groups[i]['key']==group['key'])
        related=[i for i,v in values.items() if v>0 and self.tags[i]&self.tags[aid]]
        incidence=sum(values[i] for i in related);weight=same/total*100 if total else 0;related_weight=incidence/total*100 if total else 0
        sector_score=100*max(0,1-max(weight,related_weight)/self.limit) if total else 50
        pairs=[];covered=0;load=0
        for i,v in values.items():
            if v<=0 or not total:continue
            pair=self.pair(aid,i)
            if pair:
                covered+=v/total;load+=v/total*max(0,pair['correlation'])
                if i!=aid:pairs.append(dict(ticker=self.assets[i]['ticker'],weight=v/total*100,**pair))
        correlation_score=50+50*covered-100*load
        return dict(group=group,sector_weight=weight,sector_value=same,related_product_weight=related_weight,
            related_products=[self.assets[i]['ticker'] for i in related],score=round(.6*sector_score+.4*correlation_score,2),
            sector_score=round(sector_score,2),correlation_score=round(correlation_score,2),correlation_coverage=round(covered*100,2),
            pairs=sorted(pairs,key=lambda p:p['correlation'],reverse=True)[:4],
            note='Peso sobre a carteira negociada investida. Produtos relacionados contam pelo valor integral do produto para sinalizar sobreposição, sem estimar pesos internos. Correlações usam pares de 63–252 retornos comuns recentes em BRL; cobertura ausente recebe nota neutra, não correlação zero. Não estima risco total ou causalidade.')

    def summary(self,rows):
        before=sum(self.values.values());after=before+sum(r['amount'] for r in rows);groups={}
        for i,a in self.assets.items():
            g=self.groups[i];row=groups.setdefault(g['key'],dict(**g,before=0,contribution=0,tickers=[]))
            row['before']+=self.values[i]
            if self.values[i]>0:row['tickers'].append(a['ticker'])
        for row in rows:groups[self.groups[row['id']]['key']]['contribution']+=row['amount']
        return [dict(**r,before_weight=r['before']/before*100 if before else 0,after_weight=(r['before']+r['contribution'])/after*100 if after else 0,limit=self.limit) for r in groups.values() if r['before'] or r['contribution']]
