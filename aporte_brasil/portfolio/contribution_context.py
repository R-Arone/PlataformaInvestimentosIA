"""Bounded, optional priority adjustments; evidence never bypasses purchase filters."""
from aporte_brasil.company import business_drivers
from aporte_brasil.market import recommendation_signals as signals

MODES=('economic','scenario')


def selected_scenario(app,state,opts):
    if opts.get('mode')!='scenario':return None
    row=next((r for r in state.get('ai',{}).get('scenarios',[]) if r['id']==opts.get('scenario_id')),None)
    if not row or row.get('inputs',{}).get('engine')!='llm':raise ValueError('Escolha um cenário salvo gerado por IA; os cenários mecânicos não entram nesta opção.')
    if not signals.fresh(app,row.get('created_at'),30):raise ValueError('Revise ou gere novamente o cenário de IA; validade de 30 dias para ponderar o aporte.')
    original=row.get('import_context',{}).get('asof')
    if original and not signals.fresh(app,original,30):raise ValueError('A análise original importada tem mais de 30 dias; revise as hipóteses antes de ponderar.')
    return row


def evaluate(app,state,a,opts,priority):
    indicators={i['key']:i for i in state.get('contribution_context',{}).get('indicators',[]) if i.get('observation')}
    correlations=[];business=[];observations=[];factor_data=a.get('company_research',{}).get('factor_analysis',{})
    for key,item in indicators.items():
        o=item['observation'];fresh=o.get('fresh') and signals.fresh(app,o.get('date'),100 if item.get('frequency')=='monthly' else 10)
        if fresh and o.get('direction') in ('up','down','flat'):observations.append(dict(key=key,label=item['label'],value=o.get('value'),direction=o['direction'],difference=o.get('difference'),asof=o['date'],source_url=item['source_url']))
    current={r['key']:r for r in observations}
    for f in factor_data.get('company',[]):
        o=current.get(f['key']);status=f.get('status');recent=f.get('recent_status',status)
        if not o or status not in ('positive','negative') or recent!=status or f.get('n',0)<36 or not signals.fresh(app,str(f.get('end',''))+'-01',110):continue
        sign=0 if o['direction']=='flat' else (1 if (o['direction']=='up')==(status=='positive') else -1)
        correlations.append(dict(key=f['key'],label=f.get('label',o['label']),sign=sign,direction=o['direction'],status=status,n=f['n'],start=f.get('start'),end=f['end'],asof=o['asof'],source_url=o['source_url'],note='Associação histórica da cotação; não demonstra causa nem antecipa alta.'))
    for r in business_drivers.active(a,app.age):
        o=current.get(r['factor']);sign=None
        if r['share']!=0 and o and r['sensitivity'] in ('benefits','hurts'):sign=0 if o['direction']=='flat' else 1 if (o['direction']=='up')==(r['sensitivity']=='benefits') else -1
        business.append(dict(id=r['id'],segment=r['segment'],basis=r['basis'],share=r['share'],factor=r['factor'],label=business_drivers.FACTORS[r['factor']],sensitivity=r['sensitivity'],mechanism=r['mechanism'],sign=sign,asof=r['asof'],observed_asof=o['asof'] if o else None,source_url=r['source_url'],note='Exposição do resultado operacional revisada; pode existir sem correlação da cotação.'))
    # Multiple segments can overlap: one net directional vote per factor, never sum shares.
    business_signs={}
    for r in business:
        if r['sign'] is not None:business_signs.setdefault(r['factor'],[]).append(r['sign'])
    net=[sum(v)/len(v) for v in business_signs.values()]
    correlation_score=sum(r['sign'] for r in correlations)/len(correlations) if correlations else 0
    business_score=sum(net)/len(net) if net else 0
    economic_score=50+25*correlation_score+25*business_score
    economic_points=(economic_score-50)*.1 if opts.get('mode') in MODES else 0
    scenario=selected_scenario(app,state,opts);scenario_reading=None;scenario_points=0
    if scenario:
        item=next((r for r in scenario.get('assets',[]) if r['ticker']==a['ticker']),None)
        direction=item.get('direction') if item else 'unknown'
        # No ticker coverage means no automatic extrapolation from a generic sector opinion.
        score={'favorable':100,'unfavorable':0,'mixed':50,'neutral':50}.get(direction)
        scenario_points=(score-50)*opts.get('scenario_weight',10)/100 if score is not None else 0
        scenario_reading=dict(id=scenario['id'],question=scenario['inputs']['question'],model=scenario['model'],created_at=scenario['created_at'],direction=direction,score=score,weight=opts.get('scenario_weight',10),
            assumptions=scenario['analysis'].get('assumptions',[]),invalidation=scenario['analysis'].get('invalidation',[]),sources=[dict(title=s['title'],url=s['url']) for s in scenario.get('sources',[])],note='Hipótese condicional escolhida, não previsão. Ativo sem cobertura explícita no cenário recebe ajuste zero.')
    requested=economic_points+scenario_points;delta=max(-10,min(10,requested));final=(max(0,min(100,priority+delta)) if opts.get('mode') in MODES else priority) if priority is not None else None
    effect=round(final-priority,4) if priority is not None else 0
    return dict(mode=opts.get('mode','base'),observations=observations,correlations=correlations,business=business,economic_score=round(economic_score,2),economic_points=round(economic_points,4),scenario=scenario_reading,scenario_points=round(scenario_points,4),adjustment=effect,priority_before=priority,priority_after=round(final,4) if final is not None else None,
        applied=opts.get('mode') in MODES and bool(correlations or net or scenario_points),
        note='Ponderação experimental: contexto econômico até ±5 pontos, dividido entre associação da cotação e negócio revisado; cenário selecionado até metade do peso escolhido em pontos. Ajuste combinado limitado a ±10. Sem evidência recente, ajuste zero. Qualidade, valor, cobertura e limites continuam obrigatórios.')
