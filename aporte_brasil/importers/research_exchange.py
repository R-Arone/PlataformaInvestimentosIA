"""Strict, user-reviewed JSON return from a research assistant. No order interface."""
import hashlib,json,time
from aporte_brasil.portfolio import sector_analysis

FORMAT='aporte-analysis-v1'
OUTLOOK_DIRECTIONS={'favorable','unfavorable','mixed','unknown'}
OUTLOOK_FACTORS={'rates','usd','geopolitics','energy','metals','inflation','growth','regulation','fundamentals'}
def template(day,profile='general'):
    return {'format':FORMAT,'asof':day,'profile':profile,'summary':'Resumo sucinto, fatos e inferências separados.',
      'risks':['Risco a investigar'],'actions':[{'ticker':'','action':'investigar','reason':'Próximo passo de pesquisa, sem ordem financeira.'}],
      'indicators':[], 'sources':[{'title':'Título da fonte consultada','url':'https://www.bcb.gov.br/','asof':day}],
      'outlooks':[{'ticker':'','direction':'unknown','horizon':'medium','confidence':'baixa',
        'conclusion':'Sem evidências suficientes para indicar alta ou baixa. Substitua pelo parecer pesquisado.',
        'drivers':[],'invalidation':[]}]}

def validate(app,raw,tickers=None):
    if isinstance(raw,str):
        raw=raw.strip()
        if raw.startswith('```') and raw.endswith('```'):raw=raw[raw.find('\n')+1:-3].strip()
        if len(raw)>100_000:raise ValueError('Resposta muito grande.')
        try:raw=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Número inválido.')))
        except ValueError:raise ValueError('Cole o JSON no padrão aporte-analysis-v1; texto livre não é aplicado.')
    keys={'format','asof','profile','summary','risks','actions','indicators','sources'}
    if not isinstance(raw,dict) or set(raw) not in (keys,keys|{'outlooks'}) or raw.get('format')!=FORMAT:raise ValueError('Estrutura inesperada. Use o modelo; campos de ordens/quantidades não são aceitos.')
    if not isinstance(raw['profile'],str) or raw['profile'] not in sector_analysis.PROFILES:raise ValueError('Perfil de setor inválido.')
    def day(v):
        v=app.valid_date(v)
        if v>app.today().isoformat():raise ValueError('Data futura na análise.')
        return v
    def txt(v,limit):return app.text_value(v,limit,True)
    def array(k,limit):
        if not isinstance(raw[k],list) or len(raw[k])>limit:raise ValueError('Lista inválida: '+k)
        return raw[k]
    if tickers is None:
        with app.connect() as c:tickers={r['ticker'] for r in c.execute('SELECT ticker FROM assets WHERE archived=0')}
    out={'format':FORMAT,'asof':day(raw['asof']),'profile':raw['profile'],'summary':txt(raw['summary'],3000),
         'risks':[txt(v,500) for v in array('risks',10)],'actions':[],'indicators':[],'sources':[]}
    for v in array('actions',20):
        if not isinstance(v,dict) or set(v)!={'ticker','action','reason'} or v['action'] not in ('investigar','acompanhar','aguardar','diversificar'):raise ValueError('Ações devem ser tarefas de pesquisa, sem compra/venda automática.')
        if v['ticker'] and v['ticker'] not in tickers:raise ValueError('Ticker não cadastrado: '+str(v['ticker'])[:20])
        out['actions'].append({'ticker':v['ticker'],'action':v['action'],'reason':txt(v['reason'],500)})
    seen=set()
    for v in array('indicators',50):
        if not isinstance(v,dict) or set(v)!={'ticker','metric','value','asof','source_url','definition'}:raise ValueError('Indicador fora do padrão.')
        if v['ticker'] not in tickers or v['metric'] not in sector_analysis.METRICS:raise ValueError('Ativo/indicador não cadastrado ou permitido.')
        if (v['ticker'],v['metric']) in seen:raise ValueError('Indicador repetido na resposta.')
        seen.add((v['ticker'],v['metric']))
        if isinstance(v['value'],bool) or not isinstance(v['value'],(int,float)):raise ValueError('Valor do indicador deve ser número ou deve ser omitido.')
        out['indicators'].append({**v,'value':app.number(v['value'],True,-1e15,1e15),'asof':day(v['asof']),
            'source_url':app.validate_url(v['source_url']),'definition':txt(v['definition'],500)})
        if not out['indicators'][-1]['source_url']:raise ValueError('Indicador precisa de link de fonte verificável.')
    for v in array('sources',20):
        if not isinstance(v,dict) or set(v)!={'title','url','asof'}:raise ValueError('Fonte fora do padrão.')
        url=app.validate_url(v['url'])
        if not url:raise ValueError('Informe o link da fonte.')
        out['sources'].append({'title':txt(v['title'],200),'url':url,'asof':day(v['asof'])})
    if 'outlooks' in raw:
        out['outlooks']=[];seen=set();source_dates={s['url']:s['asof'] for s in out['sources']}
        for v in array('outlooks',20):
            fields={'ticker','direction','horizon','confidence','conclusion','drivers','invalidation'}
            if not isinstance(v,dict) or set(v)!=fields:raise ValueError('Parecer fora do padrão; não aceita ordens ou probabilidades.')
            if not isinstance(v['ticker'],str) or v['ticker'] and v['ticker'] not in tickers:raise ValueError('Ativo do parecer não cadastrado.')
            if v['ticker'] in seen:raise ValueError('Parecer repetido para o mesmo ativo/setor.')
            seen.add(v['ticker'])
            if not isinstance(v['direction'],str) or v['direction'] not in OUTLOOK_DIRECTIONS:raise ValueError('Direção inválida no parecer.')
            if v['horizon'] not in ('short','medium','long') or v['confidence'] not in ('baixa','moderada','alta'):raise ValueError('Horizonte/confiança inválidos no parecer.')
            if not isinstance(v['drivers'],list) or len(v['drivers'])>8 or not isinstance(v['invalidation'],list) or len(v['invalidation'])>5:raise ValueError('Fatores/condições fora do limite.')
            if v['direction']!='unknown' and (not v['drivers'] or not v['invalidation']):raise ValueError('Parecer direcional precisa de fatores com fontes e condições para rever a conclusão.')
            drivers=[]
            for x in v['drivers']:
                if not isinstance(x,dict) or set(x)!={'factor','impact','fact','interpretation','source_urls'}:raise ValueError('Fator do parecer fora do padrão.')
                if not isinstance(x['factor'],str) or x['factor'] not in OUTLOOK_FACTORS or not isinstance(x['impact'],str) or x['impact'] not in OUTLOOK_DIRECTIONS:raise ValueError('Fator/impacto inválido.')
                if not isinstance(x['source_urls'],list) or not 1<=len(x['source_urls'])<=3:raise ValueError('Cada fator precisa de 1 a 3 links de fontes conferíveis.')
                urls=[app.validate_url(url) for url in x['source_urls']]
                if any(not url or url not in source_dates or source_dates[url]>out['asof'] for url in urls):raise ValueError('Link do fator precisa constar em sources, com data até a referência da análise.')
                drivers.append({**x,'fact':txt(x['fact'],600),'interpretation':txt(x['interpretation'],600),'source_urls':urls})
            out['outlooks'].append({**v,'conclusion':txt(v['conclusion'],1000),'drivers':drivers,'invalidation':[txt(s,500) for s in v['invalidation']]})
    return out

def action(app,path,d):
    if path=='/api/research/template':
        profile=d.get('profile','general')
        if profile not in sector_analysis.PROFILES:raise ValueError('Perfil de setor inválido.')
        return template(app.today().isoformat(),profile)
    if path=='/api/research/preview':
        record=validate(app,d.get('text','')); token=app.secrets.token_urlsafe(24)
        for k in list(app.CSV_PREVIEWS):
            if app.CSV_PREVIEWS[k]['expires']<time.time():del app.CSV_PREVIEWS[k]
        if len(app.CSV_PREVIEWS)>30:app.CSV_PREVIEWS.pop(next(iter(app.CSV_PREVIEWS)))
        app.CSV_PREVIEWS[token]={'kind':'research','record':record,'expires':time.time()+900}
        return {'token':token,'record':record}
    if path!='/api/research/commit':raise ValueError('Consulta inválida.')
    plan=app.CSV_PREVIEWS.get(d.get('token'))
    if not plan or plan['kind']!='research' or plan['expires']<time.time():raise ValueError('Prévia expirou; confira novamente.')
    if any(not isinstance(d.get(k,False),bool) for k in ('apply_indicators','verified_sources')):raise ValueError('Opções de aplicação/conferência inválidas.')
    record=validate(app,plan['record'])
    if d.get('apply_indicators') and d.get('verified_sources') is not True:raise ValueError('Confirme a conferência das fontes e períodos antes de aplicar indicadores.')
    ident=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with app.WRITE_LOCK,app.connect() as c:
        reports=app.read_cache(c,'research_reports',[])
        old=next((r for r in reports if r['id']==ident),None)
        if d.get('apply_indicators') and not (old and old.get('indicators_applied')):
            for v in record['indicators']:
                aid=c.execute('SELECT id FROM assets WHERE ticker=? AND archived=0',(v['ticker'],)).fetchone()['id']
                app.add_snapshot(c,aid,'metric:'+v['metric'],{v['metric']:v['value']},'Conferido pelo usuário · '+v['source_url'],v['asof'])
        reports=[r for r in reports if r['id']!=ident]
        reports.append({'id':ident,'saved_at':app.now(),'record':record,'indicators_applied':bool(d.get('apply_indicators') or old and old.get('indicators_applied'))})
        app.write_cache(c,'research_reports',reports[-100:])
    app.CSV_PREVIEWS.pop(d['token'],None)
    return {'saved':True,'indicators_applied':bool(d.get('apply_indicators'))}
