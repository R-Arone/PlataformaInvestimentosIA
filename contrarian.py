"""Dated market pullbacks linked to the user's universe; no market-bottom forecast."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import math
import urllib.parse

import investment_exposure
from portfolio_coupling import completed_prices
import recommendation_signals as signals

CACHE='allocation_market_context'
INDICATORS=('rates','us_rates','inflation','brent','iron','copper','soy','long_yield')
IBOV='https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/ibovespa-b3.htm'
BCB='https://dadosabertos.bcb.gov.br/dataset/1-taxa-de-cambio---livre---dolar-americano-venda---diario'
IVVB=investment_exposure.CATALOG['IVVB11']['source_url']
METHOD=('Contrafluxo: ações/FIIs usam 40% qualidade documentada, 30% desconto, 20% quedas relevantes '
        'do ativo/mercado e 10% necessidade da classe (referência, sem bloquear classes acima da meta). '
        'Preserva qualidade, cobertura mínima, preço dentro do teto e limites de concentração. '
        'ETF amplo brasileiro ou IVVB11 com composição documentada usa 70% sinal de contrafluxo e 30% necessidade, '
        'sem nota de empresa ou valor justo inventados. Exige queda relevante, não apenas uma oscilação diária. '
        'Com IA válida, aplica o ajuste de 70% nota sem IA + 30% escore dos modelos locais. '
        'Cortes e pesos são heurísticos, sem backtest. Queda não confirma preço barato nem recuperação futura.')


def finite(v):return type(v) in (int,float) and math.isfinite(v) and v>0


def index_snapshot(request,day,stamp):
    url='https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?range=1y&interval=1d'
    raw=request(url)
    try:
        result=raw['chart']['result'][0];meta=result['meta']
        if meta.get('symbol')!='^BVSP' or meta.get('currency')!='BRL' or meta.get('instrumentType')!='INDEX':raise ValueError()
        dates=result['timestamp'];closes=result['indicators']['quote'][0]['close']
    except (KeyError,TypeError,IndexError,ValueError):raise ValueError('Ibovespa sem identidade, moeda ou série confirmadas.')
    if not isinstance(dates,list) or not isinstance(closes,list) or len(dates)>500 or len(dates)!=len(closes):
        raise ValueError('Série do Ibovespa fora do formato esperado.')
    points=[]
    for ts,close in zip(dates,closes):
        try:
            ref=datetime.fromtimestamp(ts,timezone.utc).astimezone(timezone(timedelta(hours=-3))).date()
            if finite(close) and day-timedelta(days=400)<=ref<=day:points.append({'date':ref.isoformat(),'close':close})
        except (ValueError,TypeError,OverflowError,OSError):continue
    return dict(source='Yahoo Finance · Ibovespa B3 (^BVSP)',source_url=url,definition_url=IBOV,
                retrieved_at=stamp,data={'prices':points,'currency':'BRL'})


def fx_snapshot(request,day,stamp):
    query=urllib.parse.urlencode({'formato':'json','dataInicial':(day-timedelta(days=400)).strftime('%d/%m/%Y'),
                                  'dataFinal':(day-timedelta(days=1)).strftime('%d/%m/%Y')})
    url='https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados?'+query
    rows=request(url)
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('Série do dólar fora do formato esperado.')
    points=[]
    for row in rows:
        try:
            ref=datetime.strptime(row['data'],'%d/%m/%Y').date()
            value=float(str(row['valor']).replace(',','.'))
            if math.isfinite(value) and value>0 and day-timedelta(days=400)<=ref<day:points.append(dict(date=ref.isoformat(),close=value))
        except (KeyError,TypeError,ValueError):continue
    return dict(source='BCB/SGS 1 · dólar venda (R$/US$)',source_url=url,definition_url=BCB,
                retrieved_at=stamp,data={'prices':points,'currency':'BRL'})


def pullback(app,snapshot,kind):
    result=dict(key=kind,label='Bolsa brasileira · Ibovespa' if kind=='brazil' else 'Dólar em reais',
                available=False,active=False,severity=0,asof=None,start=None,count=0,latest=None,
                return1=None,return21=None,return63=None,drawdown=None,
                source=snapshot.get('source',''),source_url=snapshot.get('source_url',''),definition_url=snapshot.get('definition_url',''),
                reason='Atualize bolsa e dólar para consultar esta referência.')
    pts=completed_prices({'snapshots':{'history':snapshot}},app.today()-timedelta(days=1) if kind=='usd' else app.today(),app.now())
    pts={d:v for d,v in pts.items() if signals.fresh(app,d,400)}
    if len(pts)<64:
        result['reason']=f'Histórico insuficiente: {len(pts)} de 64 fechamentos necessários.';return result
    dates=list(pts);values=list(pts.values());last=values[-1];window=values[-252:]
    result.update(asof=dates[-1],start=dates[max(0,len(dates)-252)],count=len(window))
    if not signals.fresh(app,dates[-1]):result['reason']='Referência antiga ou futura; atualize antes de usá-la.';return result
    r21=(last/values[-22]-1)*100;dd=(last/max(window)-1)*100
    month_cut,peak_cut=(3,5) if kind=='usd' else (5,10)
    active=r21<=-month_cut+1e-9 or dd<=-peak_cut+1e-9
    result.update(available=True,active=active,latest=last,return1=(last/values[-2]-1)*100,return21=r21,
                  return63=(last/values[-64]-1)*100,drawdown=dd,
                  severity=min(100,max(0,-r21/(month_cut*2)*100,-dd/(peak_cut*2)*100)) if active else 0,
                  reason=('Queda relevante para estudar contrafluxo, sem confirmar fundo ou recuperação.' if active else
                          'Sem queda relevante pelos cortes usados; uma oscilação diária não ativa a tese.'),
                  rule=f'Retorno de 21 observações ≤ -{month_cut}% ou distância do máximo de até 252 observações ≤ -{peak_cut}%.')
    return result


def public_state(app,cached):
    import factor_analysis
    indicators=[]
    for key in INDICATORS:
        series=cached.get('indicators',{}).get(key,{});meta=factor_analysis.FACTORS[key]
        observed=factor_analysis.recent(series,meta,app.today()) if series else None
        indicators.append(dict(key=key,label=meta['label'],unit=meta['unit'],frequency=meta['frequency'],
            source_url=series.get('source_url'),available=bool(observed),observation=observed))
    return dict(markets=[pullback(app,cached.get('markets',{}).get(key,{}),key) for key in ('brazil','usd')],
                indicators=indicators,
                errors=cached.get('errors',[]),retrieved_at=cached.get('retrieved_at'),
                note='Referências independentes da carteira: Ibovespa e dólar BCB. O máximo usa até 252 observações disponíveis. PTAX é referência, não taxa de remessa. Valores antigos não recebem data nova quando a consulta falha.')


def refresh(app,data):
    if not isinstance(data,dict) or data not in ({},{'indicators':True}) or ('indicators' in data and data['indicators'] is not True):raise ValueError('A atualização recebe apenas a opção de indicadores, sem ativos ou saldos.')
    fetched={};indicators={};errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks={key:pool.submit(fn,app.request_json,app.today(),app.now()) for key,fn in (('brazil',index_snapshot),('usd',fx_snapshot))}
        if data.get('indicators'):
            import factor_analysis
            tasks.update({key:pool.submit(factor_analysis.fetch_factor,app,key,app.today()-timedelta(days=400),app.today()) for key in INDICATORS})
        for key,task in tasks.items():
            try:
                snapshot=task.result()
                if key in INDICATORS:
                    if not factor_analysis.recent(snapshot,factor_analysis.FACTORS[key],app.today()):raise ValueError('Sem observação para comparar.')
                    indicators[key]=snapshot;continue
                if not pullback(app,snapshot,key)['available']:raise ValueError('Série insuficiente ou antiga; referência anterior preservada.')
                fetched[key]=snapshot
            except Exception:
                label='Bolsa brasileira' if key=='brazil' else 'Dólar' if key=='usd' else factor_analysis.FACTORS[key]['label']
                errors.append(label+': consulta indisponível ou sem série recente suficiente; dados anteriores preservados.')
    with app.WRITE_LOCK,app.connect() as c:
        previous=app.read_cache(c,CACHE,{})
        cached=dict(markets={**previous.get('markets',{}),**fetched},indicators={**previous.get('indicators',{}),**indicators},errors=errors,retrieved_at=app.now())
        app.write_cache(c,CACHE,cached)
    return public_state(app,cached)


def exposure(asset,app=None):
    meta=asset.get('exposure') or investment_exposure.metadata(asset,{})
    known=bool(meta.get('source_url') and meta.get('asof') and meta.get('focus')!='unknown'
               and (app is None or signals.fresh(app,meta['asof'],365)))
    if asset.get('asset_type')=='stock':return 'brazil'
    if asset.get('asset_type')=='etf' and known and meta.get('focus')=='broad' and meta.get('asset_class')=='equity':
        if meta.get('scope')=='BR':return 'brazil'
        # Exact documented product, not an inference from region or trading currency.
        if asset['ticker']=='IVVB11' and meta.get('scope')=='US':return 'usd'
    return None


def candidate(app,asset,state,observed):
    area=exposure(asset,app)
    markets={m['key']:m for m in state.get('contribution_context',{}).get('markets',[])}
    market=markets.get(area,{})
    own=observed or {};dd=own.get('drawdown');r21=own.get('return21')
    own_active=bool(own.get('available') and (r21<=-5+1e-9 or dd<=-10+1e-9))
    own_severity=min(100,max(0,-r21/10*100,-dd/20*100)) if own_active else 0
    market_active=bool(market.get('available') and market.get('active'))
    # Cheaper FX is not enough to declare the ETF's foreign portfolio cheap.
    if area=='usd':market_active=market_active and own_active
    score=max(own_severity,market.get('severity',0) if market_active else 0)
    reasons=[]
    if own_active:reasons.append(f'O ativo caiu {r21:.2f}% em 21 observações e está {dd:.2f}% abaixo do máximo recente disponível.')
    if market_active:reasons.append(('Bolsa brasileira em queda relevante; estudar empresas de qualidade com desconto.' if area=='brazil' else
                                     'Dólar e cota do ETF em queda: estudar exposição ao exterior, conferindo também o preço do S&P 500.'))
    if not reasons:reasons.append('Sem queda relevante confirmada no ativo ou no mercado relacionado. Não forçar aporte apenas por uma oscilação.')
    return dict(active=own_active or market_active,score=round(score,4),area=area,own_active=own_active,market_active=market_active,
                reasons=reasons,asset_asof=own.get('asof'),market_asof=market.get('asof'),
                market_source=market.get('source'),market_source_url=market.get('source_url'),
                note='Potencial de recuperação é uma hipótese. Quedas podem continuar; confira resultados, dívida, governança e o que invalidaria a tese.')


def ideas(app,state,rows,universe):
    result=[];assets=state.get('assets',[])
    for market in state.get('contribution_context',{}).get('markets',[]):
        key=market['key'];related=[]
        for a in assets:
            if universe=='held' and a.get('position',{}).get('quantity',0)<=0:continue
            region=exposure(a,app)
            foreign=a.get('asset_type') in ('foreign','bdr','global_stock','global_etf')
            meta=a.get('exposure',{})
            if region==key or key=='usd' and (foreign or meta.get('scope') in ('US','GLOBAL') and meta.get('asset_class')=='equity'):
                related.append(a['ticker'])
        eligible=[r for r in rows if r['eligible'] and r['ticker'] in related]
        result.append(dict(key=key,active=market.get('active',False),available=market.get('available',False),
            title=('Bolsa caiu: priorizar estudo de qualidade com desconto' if key=='brazil' else 'Dólar caiu: estudar aporte no exterior') if market.get('active') else market['label'],
            explanation=('A queda ampla pode abrir oportunidade nas ações acompanhadas que continuam saudáveis e abaixo do teto.' if key=='brazil' else
                         'O dólar está abaixo do máximo recente da série. Isso pode reduzir o custo em reais de montar exposição ao exterior em relação àquele nível. Não garante que ações/ETFs estejam baratos; confira preço externo, proteção cambial e custos de remessa.'),
            related=related,eligible=[r['ticker'] for r in eligible],suggested=sum(r['amount'] for r in eligible),
            pending=('Nenhum produto relacionado na seleção atual; ideia de área, sem compra ou valor destinado.' if not related else
                     'Sem produto aprovado para compra neste método; confira a análise específica. A exposição regional não confirma exposição cambial sem proteção.' if not eligible else
                     'Os valores efetivos aparecem nas sugestões, sujeitos aos limites e ao mínimo por compra.')))
    return result
