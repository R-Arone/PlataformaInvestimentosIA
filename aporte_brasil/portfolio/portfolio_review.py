"""Local position review: observed criterion losses and supported price alerts."""
import hashlib
import json
from aporte_brasil.portfolio import investment_value
from aporte_brasil.portfolio import investment_decision

CACHE='portfolio_review_history'


def checks(a):
    return [c for g in a.get('fii_research' if a['asset_type']=='fii' else 'company_research',{}).get('study',{}).get('groups',[]) if g['key']!='price' for c in g.get('checks',[]) if c['status']!='na']


def rules(a,settings):
    return hashlib.sha256(json.dumps([settings.get('sector_rules',{}),a.get('research_profile'),a.get('sector_analysis',{}).get('profile')],sort_keys=True).encode()).hexdigest()


def price_alert(app,a,cases,threshold):
    p=investment_value.reference(app,a,cases);price=p['price'];reading=p['reading'];unique={}
    if reading['status']=='unknown':return dict(status='unknown',models=[],threshold=threshold,reason='Sem valor recente e conferível para avaliar saída por preço.')
    if a.get('asset_type')=='fii' and p.get('pvp',0)>1.5:
        return dict(status='product_rule',models=[],threshold=1.5,price=price,asof=p['asof'],quote_asof=p['quote_asof'],reason='P/VP acima de 1,5: conferir a regra de descarte definida para FIIs e reavaliar a posição; VPA não é valor justo.')
    valuation=a.get('valuation',{})
    for m in valuation.get('methods',[]):
        value=m.get('value')
        if m.get('role') not in ('primary','complementary') or not investment_value.numeric(value) or value<=0 or set(m.get('requirements',[]))&set(valuation.get('estimates',[])):continue
        unique.setdefault(m.get('family',m['method']),dict(method=m['method'],value=value,premium=(price/value-1)*100))
    models=list(unique.values());high=[m for m in models if m['premium']>=threshold]
    status='expensive' if len(models)>=2 and len(high)==len(models) else 'limited' if models and high else 'within'
    return dict(status=status,models=models,threshold=threshold,price=price,asof=p['asof'],quote_asof=p['quote_asof'],
        reason='Preço muito acima de todos os métodos aplicáveis conferíveis: revisar a posição e a hipótese de redução.' if status=='expensive' else 'Há cenário elevado, mas a evidência é limitada ou os métodos divergem.' if status=='limited' else 'Sem alerta forte de saída por preço pelas premissas disponíveis.')


def evaluate(app,assets,settings,cases,cache):
    cache=cache if isinstance(cache,dict) else {};history=cache.get('baselines',{});events=cache.get('events',[]);rows=[]
    for a in assets:
        if a.get('position',{}).get('quantity',0)<=0:continue
        current=checks(a);failed=[dict(key=c['key'],label=c['label'],detail=c.get('detail',''),asof=c.get('asof'),source_url=c.get('source_url','')) for c in current if c['status']=='fail']
        old=history.get(str(a['id']),{});old=old if old.get('ticker')==a['ticker'] else {};lost=[]
        for c in failed:
            event=next((e for e in reversed(events) if e['asset_id']==a['id'] and e['ticker']==a['ticker'] and e['key']==c['key']),None)
            if old.get('checks',{}).get(c['key'])=='pass':event=dict(asset_id=a['id'],ticker=a['ticker'],key=c['key'],label=c['label'],at=app.now(),kind='lost' if old.get('rules')==rules(a,settings) else 'rule_changed')
            if event:lost.append({**event,**c})
        price=price_alert(app,a,cases,settings.get('expensive_alert_percent',30))
        if failed or price['status'] in ('expensive','limited','product_rule'):rows.append(dict(id=a['id'],ticker=a['ticker'],name=a['name'],failed=failed,lost=lost,price=price,investor10=investment_decision.investor_link(a),priority='review_position' if lost or price['status'] in ('expensive','product_rule') else 'review_criteria'))
    return dict(rows=rows,since=cache.get('since'),generated_at=app.now(),note='A comparação de perda começa quando esta versão registra a carteira. Falta de dados não vira reprovação. Alertas pedem revisão da tese; custo, imposto, alternativa de investimento e premissas entram na decisão de reduzir uma posição.')


def record(app,d):
    if d!={}:raise ValueError('A revisão usa somente a carteira local, sem receber posições externas.')
    scope=str(app.DB_PATH);state=app.state()
    with app.WRITE_LOCK,app.connect() as c:
        if str(app.DB_PATH)!=scope:raise ValueError('O banco mudou; atualize a carteira.')
        cache=app.read_cache(c,CACHE,{});result=evaluate(app,state['assets'],state['settings'],state.get('valuation_cases',{}),cache);events=cache.get('events',[])
        for row in result['rows']:
            for event in row['lost']:
                key=(event['asset_id'],event['ticker'],event['key'],event['at'])
                if not any((e['asset_id'],e['ticker'],e['key'],e['at'])==key for e in events):events.append(event)
        baselines={str(a['id']):dict(ticker=a['ticker'],rules=rules(a,state['settings']),checks={r['key']:r['status'] for r in checks(a)}) for a in state['assets'] if a.get('position',{}).get('quantity',0)>0}
        cache=dict(since=cache.get('since') or app.now(),baselines=baselines,events=events[-100:]);app.write_cache(c,CACHE,cache);result['since']=cache['since'];return result
