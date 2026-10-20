"""Retrospective monthly crisis evidence and conditional study decisions.

No fitted forecast, causal attribution or probability of surviving a crisis.
Historical prices and present financial condition deliberately have separate roles.
"""
from datetime import date
import math

EPISODES = (
    ('financial_2008', 'Crise financeira de 2008', '2007-09', '2007-10', '2009-06'),
    ('covid_2020', 'Pandemia de 2020', '2020-01', '2020-02', '2020-06'),
    ('rates_2022', 'Inflação e juros globais em 2022', '2021-12', '2022-01', '2022-12'),
)


def ordinal(month):
    return int(month[:4])*12+int(month[5:7])-1


def episode(points, baseline, start, end):
    lookup={p['month']:p for p in points}
    window=[p for p in points if baseline<=p['month']<=end]
    expected=ordinal(end)-ordinal(baseline)+1
    if baseline not in lookup or len(window)!=expected:
        return dict(status='missing', reason='Faltam meses antes ou durante o episódio; sem estimativa de recuperação.')
    peak=window[0];worst=0.;top=peak;bottom=peak
    for p in window[1:]:
        if p['value']>=peak['value']:peak=p
        loss=100*(p['value']/peak['value']-1)
        if loss<worst:worst=loss;top=peak;bottom=p
    if worst==0:
        return dict(status='no_drop',reason='Nenhuma queda observada nos fechamentos mensais deste recorte.')
    after=[p for p in points if p['month']>bottom['month']]
    first=None;confirmed=None;streak=0;previous=bottom['month']
    for p in after:
        if ordinal(p['month'])-ordinal(previous)!=1:streak=0
        if p['value']>=top['value']:
            if first is None:first=p['month']
            streak+=1
            if streak==3 and confirmed is None:confirmed=p['month']
        else:streak=0
        previous=p['month']
    last=points[-1]
    return dict(status='recovered' if confirmed else 'pending',drawdown=worst,peak=top['month'],trough=bottom['month'],
        first_recovery=first,confirmed_recovery=confirmed,
        months_to_first=ordinal(first)-ordinal(bottom['month']) if first else None,
        months_to_confirm=ordinal(confirmed)-ordinal(bottom['month']) if confirmed else None,
        observed_months=ordinal(last['month'])-ordinal(bottom['month']),through=last['month'],
        current_gap=100*(last['value']/top['value']-1),peak_value=top['value'])


def resilience(data):
    prices=data.get('prices',{}).get('points',[]);benchmark=data.get('benchmark',{}).get('points',[])
    return dict(start=prices[0]['month'] if prices else None,end=prices[-1]['month'] if prices else None,months=len(prices),
        episodes=[dict(key=key,label=label,start=start,end=end,
                       company=episode(prices,baseline,start,end),benchmark=episode(benchmark,baseline,start,end))
                  for key,label,baseline,start,end in EPISODES],
        prices=prices,benchmark=benchmark,
        note='Fechamentos mensais ajustados pelo provedor: perdas intramês podem ser maiores. Recuperação = voltar ao pico observado antes da maior queda no recorte; confirmação = três fechamentos consecutivos acima desse pico. Meses ausentes interrompem a confirmação. Empresa e índice têm picos próprios. A janela do episódio é fixa, não escolhida pelo desempenho. Recuperação da cotação não mede solvência nem prevê a próxima crise.')


def context(a,day):
    research=a.get('company_research',{});model=research.get('fundamental_model',{})
    quality=model.get('quality',{});valuation=model.get('valuation',{});stress=model.get('stress',{})
    factor=research.get('factor_analysis',{});parameters=model.get('parameters',{})
    scenarios=valuation.get('scenarios',[]);base=next((r for r in scenarios if r['label']=='Escolhido'),{})
    dates=[valuation.get(key,{}).get('asof') for key in ('observed_roe','observed_pvp')]
    fresh=all(d and 0<=(day-date.fromisoformat(d)).days<=370 for d in dates)
    rows=[]
    for r in factor.get('company',[]):
        if r['status'] not in ('positive','negative'):continue
        current=r.get('current');delta=current.get('difference') if current and current.get('fresh') else None
        pressure='unknown' if delta is None else 'flat' if abs(delta)<1e-8 else 'support' if (delta>0)==(r['status']=='positive') else 'pressure'
        rows.append(dict(key=r['key'],label=r['label'],status=r['status'],n=r['n'],start=r['start'],end=r['end'],
            recent_status=r.get('recent_status',r['status']),pressure=pressure,
            observed_asof=current.get('date') if current else None,difference=delta,source_url=r['source_url']))
    crises=[]
    for r in factor.get('resilience',{}).get('episodes',[]):
        c=r['company'];crises.append(dict(key=r['key'],label=r['label'],status=c['status'],drawdown=c.get('drawdown'),
            months_to_first=c.get('months_to_first'),months_to_confirm=c.get('months_to_confirm'),through=c.get('through')))
    facts=factor.get('scope',{}).get('facts',[])
    return dict(asof=day.isoformat(),currency=factor.get('currency') or ('USD' if a.get('asset_type')=='foreign' else 'BRL'),
        quality=quality.get('status','incomplete'),quality_counts=quality.get('counts',{'pass':0,'fail':0,'unknown':0,'na':0}),
        failed_checks=[r['label'] for r in quality.get('checks',[]) if r['status']=='fail'][:8],
        valuation=base.get('classification','unknown'),valuation_pvp=base.get('pvp'),
        valuation_premises={k:base.get(k) for k in ('roe','cost_of_equity','growth')},
        valuation_verified=bool(fresh and base.get('pvp') is not None and model.get('saved_at') and parameters.get('sustainable_roe') is not None and parameters.get('cost_of_equity') is not None),
        valuation_asof=min(dates) if all(dates) else None,
        stress=stress.get('status','incomplete'),history_years=factor.get('years',5),history_asof=factor.get('asof'),
        factors=rows[:14],crises=crises,
        business=[dict(text=r.get('text','')[:400],asof=r.get('asof') or None,source_url=r.get('source_url','')) for r in facts[:3]])


def decision(a):
    c=a.get('company_reference');action='complete';reasons=[]
    if not c:
        return dict(action=action,reasons=['Sem referências da empresa para este cenário.'],conditions=['Atualizar fundamentos e conferir a tese.'])
    if c['quality']=='incomplete':reasons.append('Qualidade com dados pendentes.')
    if not c['valuation_verified']:reasons.append('Preço exige premissas explícitas e indicadores recentes.')
    native=a.get('instrument')
    stale=a.get('price_stale',True)
    if native:
        ref=native.get('native_asof');price=native.get('native_price')
        stale=not ref or type(price) not in (int,float) or not math.isfinite(price) or price<=0 or not 0<=(date.fromisoformat(c['asof'])-date.fromisoformat(ref)).days<=7
    if stale:reasons.append('Cotação na moeda de negociação precisa de atualização.')
    eligible=c['valuation_verified'] and not stale
    if eligible and a['direction']=='favorable' and c['quality']=='within' and c['valuation']=='below' and c['stress'] in ('within_scenario','na'):
        action='buy';reasons=['Cenário favorável para a exposição; qualidade atende aos critérios.', 'P/VP abaixo da hipótese escolhida e sem alerta no teste financeiro disponível.']
    elif eligible and a['direction']=='unfavorable' and (c['quality']=='review' or c['valuation']=='above'):
        action='reduce';reasons=['Cenário desfavorável para a exposição.', 'Critérios financeiros a revisar ou P/VP acima da hipótese escolhida.']
    elif not reasons:
        action='watch';reasons=['Os critérios não concordam o suficiente para estudar compra ou redução.']
    if c['stress']=='attention':reasons.append('O cenário financeiro de estresse aponta fragilidade.')
    if c['factors']:reasons.append('Fatores históricos servem como contexto; associação contemporânea não antecipa o retorno.')
    return dict(action=action,reasons=reasons[:6],conditions=['Confirmar produtos, insumos, dívida, margens e fatos do cenário.',
        'Comparar outros modelos de valor e conferir as premissas, concentração e horizonte antes de decidir.'])


def attach(assets):
    for a in assets:
        if 'company_reference' in a:a['decision_support']=decision(a)


def validate_context(app,c):
    keys={'asof','currency','quality','quality_counts','failed_checks','valuation','valuation_pvp','valuation_premises','valuation_verified','valuation_asof','stress','history_years','history_asof','factors','crises','business'}
    if not isinstance(c,dict) or set(c)!=keys:raise ValueError('Referências da empresa inválidas.')
    for k in ('asof','valuation_asof','history_asof'):
        if c[k] is not None and app.valid_date(c[k])>app.today().isoformat():raise ValueError('Referência futura da empresa.')
    if c['currency'] not in ('BRL','USD','EUR','GBP') or c['quality'] not in ('within','review','incomplete') or c['valuation'] not in ('below','above','near','unknown') or c['stress'] not in ('attention','incomplete','within_scenario','na') or type(c['valuation_verified']) is not bool or type(c['history_years']) is not int or c['history_years'] not in (5,10,20):raise ValueError('Critérios da empresa inválidos.')
    if not isinstance(c['quality_counts'],dict) or set(c['quality_counts'])!={'pass','fail','unknown','na'} or any(type(v) is not int or not 0<=v<=50 for v in c['quality_counts'].values()):raise ValueError('Contagem de qualidade inválida.')
    def number(v,low=None,high=None):
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or low is not None and v<low or high is not None and v>high):raise ValueError('Número inválido na referência da empresa.')
    number(c['valuation_pvp'],0,1e8)
    if not isinstance(c['valuation_premises'],dict) or set(c['valuation_premises'])!={'roe','cost_of_equity','growth'}:raise ValueError('Premissas de valor inválidas.')
    for v in c['valuation_premises'].values():number(v,-100,1000)
    for k,limit in (('failed_checks',8),('factors',14),('crises',3),('business',3)):
        if not isinstance(c[k],list) or len(c[k])>limit:raise ValueError('Referências fora do limite.')
    for text in c['failed_checks']:app.text_value(text,300,True)
    seen=set()
    for r in c['factors']:
        if not isinstance(r,dict) or set(r)!={'key','label','status','n','start','end','recent_status','pressure','observed_asof','difference','source_url'} or r['key'] in seen or r['key'] not in ('rates','usd','brent','iron','copper','soy','us_rates','dollar_index','inflation','activity','us_inflation','us_activity','long_yield','credit_spread','volatility','gas','nickel') or r['status'] not in ('positive','negative') or r['pressure'] not in ('unknown','flat','support','pressure') or type(r['n']) is not int or not 36<=r['n']<=240:raise ValueError('Fator da empresa inválido.')
        seen.add(r['key']);app.text_value(r['label'],100,True);app.text_value(r['recent_status'],30,True)
        for k in ('start','end'):app.valid_date(r[k]+'-01')
        if r['start']>r['end'] or r['end']>=c['asof'][:7]:raise ValueError('Período do fator inválido.')
        if r['observed_asof'] is not None and app.valid_date(r['observed_asof'])>c['asof']:raise ValueError('Fator futuro.')
        number(r['difference']);app.validate_url(r['source_url'])
    seen=set()
    for r in c['crises']:
        if not isinstance(r,dict) or set(r)!={'key','label','status','drawdown','months_to_first','months_to_confirm','through'} or r['key'] not in {p[0] for p in EPISODES} or r['key'] in seen or r['status'] not in ('missing','no_drop','recovered','pending'):raise ValueError('Episódio de crise inválido.')
        seen.add(r['key']);app.text_value(r['label'],100,True);number(r['drawdown'],-100,0)
        for k in ('months_to_first','months_to_confirm'):number(r[k],1,240)
        if r['through'] is not None and app.valid_date(r['through']+'-01')>c['asof']:raise ValueError('Crise com data futura.')
    for r in c['business']:
        if not isinstance(r,dict) or set(r)!={'text','asof','source_url'}:raise ValueError('Atividade da empresa inválida.')
        app.text_value(r['text'],400);app.validate_url(r['source_url'])
        if r['asof'] is not None and app.valid_date(r['asof'])>c['asof']:raise ValueError('Atividade com data futura.')
    return c
