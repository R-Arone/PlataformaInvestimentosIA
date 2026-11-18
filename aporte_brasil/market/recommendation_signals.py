"""Observed momentum and explicit reuse of dated local model forecasts."""
from datetime import date, datetime, timedelta, timezone
import math
import statistics
from aporte_brasil.portfolio.portfolio_coupling import completed_prices

HORIZONS=(1,5,20)
SUPPORTED=('stock','fii','etf','bdr','crypto')
METHOD=('Oportunidades de alta ignora metas e déficits das classes. Nota de mercado: '
        '45% retorno em 63 observações normalizado pela volatilidade, 35% distância da média de 50 '
        'e 20% proximidade do máximo nas últimas 126 observações disponíveis. '
        'Exige 64 fechamentos recentes. Sem IA, exige retorno positivo em 21 e 63 observações e preço acima da média de 50. '
        'Com IA disponível: 70% da nota sem IA + 30% da média dos escores válidos dos modelos. '
        'No modo de alta, escore de IA abaixo de 40 impede novo aporte; a partir de 60 pode indicar uma possível virada. '
        'Pesos e cortes são heurísticos, sem validação de desempenho. Sinais de 1, 5 ou 20 pregões não estimam retorno de longo prazo.')


def number(value):return type(value) in (int,float) and math.isfinite(value)


def fresh(app, value, days=7):
    try:
        if len(value)>10:
            stamp=datetime.fromisoformat(value)
            now=datetime.fromisoformat(app.now())
            if stamp.tzinfo is None or now.tzinfo is None or stamp>now:return False
            day=stamp.astimezone(timezone(timedelta(hours=-3))).date()
        else:day=date.fromisoformat(value)
        return 0<=(app.today()-day).days<=days
    except (ValueError,TypeError):return False


def market(app, asset):
    history=asset.get('snapshots',{}).get('history',{})
    result=dict(available=False,score=None,positive=False,reason='',asof=None,source=history.get('source',''),
                return21=None,return63=None,volatility=None,drawdown=None,average50=None,count=0)
    if asset.get('asset_type') not in SUPPORTED:
        result['reason']='Este modo precisa de cotação e histórico comparáveis em reais; produto não coberto.';return result
    if history.get('data',{}).get('currency') not in (None,'BRL'):
        result['reason']='Histórico em moeda diferente de reais; não misturar moedas na tendência.';return result
    day=app.today()-timedelta(days=1) if asset.get('asset_type')=='crypto' else app.today()
    points=completed_prices(asset,day,app.now())
    result['count']=len(points)
    if len(points)<64:
        result['reason']=f'Faltam fechamentos para a leitura de alta: {len(points)} de 64.';return result
    result['asof']=next(reversed(points))
    if not fresh(app,result['asof']):
        result['reason']='Histórico de preços antigo; atualize antes de avaliar a alta.';return result
    prices=list(points.values());returns=[math.log(b/a) for a,b in zip(prices[-64:],prices[-63:])]
    vol=max(.003,statistics.stdev(returns));last=prices[-1];average=statistics.mean(prices[-50:])
    r21=(last/prices[-22]-1)*100;r63=(last/prices[-64]-1)*100
    drawdown=(last/max(prices[-126:])-1)*100
    momentum=50+50*math.tanh(math.log(last/prices[-64])/(vol*math.sqrt(63)))
    trend=50+50*math.tanh(math.log(last/average)/(vol*math.sqrt(20)))
    stability=max(0,100+drawdown/30*100)
    result.update(available=True,score=round(.45*momentum+.35*trend+.20*stability,4),
                  positive=r21>0 and r63>0 and last>average,return21=r21,return63=r63,
                  volatility=vol*math.sqrt(252)*100,drawdown=drawdown,average50=average,
                  reason='Alta observada pelas regras de mercado.' if r21>0 and r63>0 and last>average else 'As regras de mercado ainda não mostram alta consistente.')
    return result


def ai(app, asset, state, horizon, observed=None):
    result=dict(available=False,score=None,models=[],reason='Ainda não há modelos locais válidos para este ativo.',horizon=horizon)
    if asset.get('asset_type')!='stock':
        result['reason']='Os modelos locais de preços deste recomendador cobrem ações brasileiras. Neste ativo, use os indicadores de mercado.';return result
    row=next((r for r in state.get('signals',{}).get('rows',[]) if r.get('ticker')==asset['ticker']),None)
    if not row:return result
    if row.get('status')!='ready':
        result['reason']=row.get('reason') or 'Modelos ainda sem histórico suficiente.';return result
    if row.get('stale',True) or not fresh(app,row.get('asof')) or not fresh(app,row.get('analyzed_at')):
        result['reason']='Modelos antigos ou calculados com dados que mudaram; atualize a IA.';return result
    if row.get('market')!='BR' or row.get('currency')!='BRL':
        result['reason']='O modelo usa outro mercado ou moeda; não foi aplicado à cotação em reais.';return result
    forecast=row.get('horizons',{}).get(str(horizon),{})
    vol=(observed or {}).get('volatility');scale=(vol/100*math.sqrt(horizon/252)*100) if number(vol) and vol>0 else None
    for key,label in (('bayesian','Bayesiano local'),('incremental','Incremental local'),('pretrained','Chronos-2')):
        model=forecast.get(key,{})
        if model.get('status')!='ready':continue
        score=None
        if key=='incremental' and number(model.get('score')) and -100<=model['score']<=100:
            score=50+model['score']/2
        elif key=='bayesian':
            probabilities=model.get('probabilities') or {}
            values=[probabilities.get(k) for k in ('down','stable','up')]
            if all(number(v) and 0<=v<=100 for v in values) and abs(sum(values)-100)<.01:
                score=50+(values[2]-values[0])/2
        elif key=='pretrained' and scale:
            values=[model.get(k) for k in ('low_return','median_return','high_return')]
            if all(number(v) and v>-100 for v in values) and values==sorted(values):
                score=50+50*math.tanh(values[1]/scale)
        if score is None:continue
        result['models'].append(dict(key=key,label=label,score=round(score,4),direction=model.get('direction','unknown'),
            asof=row['asof'],analyzed_at=row['analyzed_at'],source=row.get('source',''),trained=model.get('trained'),
            median_return=model.get('median_return') if number(model.get('median_return')) else None,
            low_return=model.get('low_return') if number(model.get('low_return')) else None,
            high_return=model.get('high_return') if number(model.get('high_return')) else None,
            evaluations=model.get('evaluations',{})))
    if result['models']:
        scores=[r['score'] for r in result['models']]
        result.update(available=True,score=sum(scores)/len(scores),reason='Modelos locais prontos e compatíveis com o ativo.',
                      disagreement=min(scores)<40 and max(scores)>60)
    else:result['reason']='Os modelos deste horizonte ainda estão aprendendo ou retornaram dados inválidos.'
    return result


def adjust(app, asset, state, opts, baseline, observed=None):
    requested=opts['mode']=='context'
    signal=ai(app,asset,state,opts.get('signal_horizon',20),observed) if requested else dict(available=False,score=None,models=[],reason='IA desligada.',horizon=opts.get('signal_horizon',20))
    applied=requested and signal['available'] and number(baseline)
    final=.7*baseline+.3*signal['score'] if applied else baseline
    return {**signal,'requested':requested,'applied':applied,'baseline':baseline,
            'final':round(final,4) if number(final) else None,
            'delta':round(final-baseline,4) if applied else 0,
            'note':'Escores de modelos experimentais, sem calibração como chance de lucro. Modelos podem compartilhar dados e não são votos independentes.'}
