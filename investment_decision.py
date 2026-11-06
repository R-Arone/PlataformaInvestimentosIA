"""Evidence behind a compact contribution card; no price target is invented."""
import copy
import urllib.parse
import recommendation_signals
import sector_analysis


def investor_link(a):
    route={'stock':'acoes','fii':'fundos-imobiliarios','etf':'etfs'}.get(a.get('asset_type'))
    return 'https://investidor10.com.br/'+route+'/'+urllib.parse.quote(a['ticker'].lower(),safe='')+'/' if route else None


def explain(app,a,row,state):
    study=a.get('fii_research' if a['asset_type']=='fii' else 'company_research',{}).get('study',{})
    groups=[dict(key=g['key'],label=g.get('label',g['key']),checks=[{k:copy.deepcopy(c[k]) for k in ('key','label','status','detail','asof','source_url','references','provenance') if k in c} for c in g.get('checks',[])]) for g in study.get('groups',[]) if g['key']!='price']
    observed=row.get('market_signal') or recommendation_signals.market(app,a)
    area=(row.get('contraflow') or {}).get('area')
    benchmark=next((m for m in state.get('contribution_context',{}).get('markets',[]) if m['key']==area),None)
    profile=a.get('sector_analysis',{}).get('profile') or sector_analysis.profile(a)
    keys=(['pvp','pe','roe','dy','basel','npl90'] if profile in ('bank','insurance','financial_services') else
          ['pvp','dy','vacancy','distribution_cover'] if a['asset_type']=='fii' else
          ['pe','roe','roic','operating_margin','net_debt_ebitda','dy'] if profile=='technology' else
          ['pe','pvp','roe','net_debt_ebitda','dy'])
    indicators=[]
    for key in keys:
        meta=a.get('sector_metrics',{}).get(key,{})
        label,unit,_=sector_analysis.METRICS[key]
        indicators.append(dict(key=key,label=label,unit=unit,value=meta.get('value'),asof=meta.get('asof'),source=meta.get('source'),reason=meta.get('reason','Dado ainda não disponível.')))
    valuation=a.get('valuation',{});selection=valuation.get('selection',{})
    preferred=(valuation.get('suggestion') or {}).get('method') or next(iter(selection.get('primary',[])),None)
    method=next((m for m in valuation.get('methods',[]) if m['method']==preferred),{})
    plan=[r for r in valuation.get('data_plan',[]) if r.get('field') in method.get('requirements',[])]
    needed=[dict(key=r['field'],label=r.get('label'),guidance=r.get('guidance'),asof=r.get('asof')) for r in plan if r.get('status')=='missing']
    inputs=[dict(key=r['field'],label=r.get('label'),value=copy.deepcopy(valuation.get('inputs',{}).get(r['field'])),asof=r.get('asof'),source=r.get('source'),estimated=r['field'] in valuation.get('estimates',[])) for r in plan]
    reading=row['price'].get('reading',{});fallen=bool((row.get('contraflow') or {}).get('active'))
    summary=('Queda observada; ainda falta demonstrar o valor.' if fallen and reading.get('status','unknown')=='unknown' else
             ('Desconto patrimonial; confira qualidade e riscos do fundo.' if a['asset_type']=='fii' else 'Desconto com margem; confira os bloqueios de qualidade.') if reading.get('status')=='cheap' and not row['eligible'] else
             'Passou nos filtros; aporte limitado pela carteira e pelo número de destinos.' if row['eligible'] else
             'Há critérios a resolver antes de um novo aporte.')
    return dict(summary=summary,investor10=investor_link(a),decline=copy.deepcopy(observed),benchmark=copy.deepcopy(benchmark),
        indicators=indicators,quality_groups=groups,preferred_method=preferred,method_reason=selection.get('reason'),needed_inputs=needed,
        method_details=dict(formula=method.get('formula'),reason=method.get('reason'),inputs=inputs),
        value_note='Queda mede preço relativo ao passado; barato exige uma referência fundamental com premissas conferidas. P/L ou P/VP isolado não resolve essa comparação.',generated_at=app.now())
