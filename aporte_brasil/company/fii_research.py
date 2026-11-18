"""FII dossiers from dated CVM disclosures; brick, credit and FoF stay distinct."""
from datetime import date,timedelta
from concurrent.futures import ThreadPoolExecutor
import math
import os
import re
import urllib.parse

from aporte_brasil.company import company_insights
from aporte_brasil.company import public_reports
from aporte_brasil.portfolio import sector_analysis
from aporte_brasil.company import fii_quality

KINDS=('fii_reports','fii_dividends','fii_drivers','fii_classification',fii_quality.KIND)
TYPES={'tijolo':'Imóveis · tijolo','papel':'Recebíveis · papel','hibrido':'Híbrido','fof':'Fundo de fundos','unknown':'Perfil a confirmar'}
MONTHLY=('nav','equity','shares','assets','yield_nav','amortization','obligations','securitization','cri','funds','property_assets')
QUARTER=('cash_result','cash_accumulated','declared','ipca_share','igpm_share','short_contracts')
FOCUS={
 'tijolo':('vacancy','financial_vacancy','top_property','rental_delinquency','short_contracts','distribution_cover','fund_leverage'),
 'papel':('credit_delinquency','top_credit','ltv','distribution_cover','fund_leverage'),
 'fof':('top_fund','distribution_cover','fund_leverage'),
 'hibrido':('vacancy','top_property','credit_delinquency','top_credit','distribution_cover','fund_leverage'),
 'unknown':('distribution_cover','fund_leverage')}


def url(app,v):
    v=app.text_value(v,1500,True); p=urllib.parse.urlsplit(v)
    if p.scheme not in ('http','https') or not p.netloc or p.username or p.password:raise ValueError('Informe um link público válido da fonte.')
    return v


def subtype(a):
    manual=a.get('snapshots',{}).get('fii_classification',{}).get('data',{})
    if manual.get('type'):return manual['type']
    d=a.get('snapshots',{}).get('fii_reports',{}).get('data',{})
    s=sector_analysis.fold(d.get('profile',{}).get('segment') or a.get('sector',''))
    rows=d.get('monthly',[])
    if rows and (rows[-1].get('assets') or 0)>0:
        r=rows[-1]; assets=r['assets']
        if (r.get('cri') or 0)/assets>=.6:return 'papel'
        if (r.get('funds') or 0)/assets>=.6:return 'fof'
        if (r.get('property_assets') or 0)/assets>=.6:return 'tijolo'
    if any(w in s for w in ('fundos de fundos','fundo de fundos','fof')):return 'fof'
    if any(w in s for w in ('hibrid','misto')):return 'hibrido'
    if any(w in s for w in ('papel','recebiveis')) or re.search(r'\bcri\b',s):return 'papel'
    if any(w in s for w in ('logistic','shopping','lajes','escritorio','hospital','hotel','residenc','tijolo','renda urbana')):return 'tijolo'
    if rows and (rows[-1].get('assets') or 0)>0:
        return 'hibrido'
    return 'unknown'


def validate_snapshot(app,kind,d):
    if kind==fii_quality.KIND:return fii_quality.validate_snapshot(app,d)
    if not isinstance(d,dict) or not re.fullmatch(r'[A-Z0-9]{4}11',str(d.get('symbol',''))):raise ValueError('Identificação do FII inválida.')
    if kind=='fii_drivers':
        value=company_insights.validate_snapshot(app,'issuer_drivers',{**d,'symbol':d['symbol']+'.SA'})
        return {**value,'symbol':d['symbol']}
    if kind=='fii_classification':
        if set(d)!={'symbol','type','asof','source_url'} or d['type'] not in TYPES:raise ValueError('Perfil do FII inválido.')
        if app.valid_date(d['asof'])>app.today().isoformat():raise ValueError('Perfil com data futura.')
        return {**d,'source_url':url(app,d['source_url'])}
    if kind=='fii_dividends':
        if set(d)!={'symbol','items','source_url'} or not isinstance(d['items'],list) or len(d['items'])>2000:raise ValueError('Rendimentos inválidos.')
        seen=set();items=[]
        for r in d['items']:
            if set(r)!={'date','amount','type','estimated'} or r['type'] not in ('RENDIMENTO','AMORTIZAÇÃO') or not isinstance(r['estimated'],bool):raise ValueError('Evento de rendimento inválido.')
            ref=app.valid_date(r['date']);key=(ref,r['type'])
            if ref>app.today().isoformat() or key in seen or isinstance(r['amount'],bool):raise ValueError('Rendimento futuro/duplicado ou valor inválido.')
            seen.add(key);items.append({**r,'date':ref,'amount':app.number(r['amount'],True,0)})
        return {**d,'items':sorted(items,key=lambda r:(r['date'],r['type'])),'source_url':url(app,d['source_url'])}
    if kind!='fii_reports' or set(d)!={'symbol','profile','monthly','quarterly','source_url'}:raise ValueError('Informe do FII inválido.')
    p=d['profile']
    if not isinstance(p,dict) or set(p)!={'cnpj','name','segment','mandate','management','administrator','isin','started'}:raise ValueError('Identidade CVM incompleta.')
    if not re.fullmatch(r'\d{14}',p['cnpj']) or not re.fullmatch('BR'+d['symbol'][:4]+r'CTF\d{3}',p['isin']):raise ValueError('ISIN/CNPJ não correspondem ao emissor do FII.')
    p={k:app.text_value(v,300,k in ('name','cnpj','isin')) for k,v in p.items() if k!='started'}|{'started':p['started']}
    if p['started'] and app.valid_date(p['started'])>app.today().isoformat():raise ValueError('Funcionamento futuro.')
    out={**d,'profile':p,'source_url':url(app,d['source_url'])}
    for group,fields,limit in [('monthly',MONTHLY,36),('quarterly',QUARTER,12)]:
        if not isinstance(d[group],list) or len(d[group])>limit:raise ValueError('Histórico de informes excessivo.')
        seen=set();rows=[]
        for r in d[group]:
            expected={'date','source_url',*fields}|({'properties','portfolio'} if group=='quarterly' else set())
            if not isinstance(r,dict) or set(r)!=expected:raise ValueError('Campos do informe incompatíveis.')
            ref=app.valid_date(r['date'])
            if ref>app.today().isoformat() or ref in seen:raise ValueError('Informe futuro/duplicado.')
            seen.add(ref);row={'date':ref,'source_url':url(app,r['source_url'])}
            for field in fields:
                v=r[field]
                if v is not None and (type(v) not in (int,float) or not math.isfinite(v)):raise ValueError('Valor do informe inválido.')
                row[field]=app.number(v)
                if field in ('yield_nav','amortization','ipca_share','igpm_share','short_contracts') and v is not None and not 0<=v<=1:raise ValueError('Fração do informe fora de 0–1.')
                if group=='monthly' and v is not None and v<0:raise ValueError('Patrimônio/valor negativo precisa de revisão do informe.')
            if group=='quarterly':
                for collection,keys in [('properties',{'name','area','vacancy','delinquency','revenue_share','class'}),('portfolio',{'type','issuer','issuer_cnpj','name','value'})]:
                    if not isinstance(r[collection],list) or len(r[collection])>2000:raise ValueError('Carteira excessiva.')
                    row[collection]=[]
                    for item in r[collection]:
                        if set(item)!=keys:raise ValueError('Ativo do informe inválido.')
                        clean={}
                        for key,value in item.items():
                            if key in ('area','vacancy','delinquency','revenue_share','value'):
                                if value is not None and type(value) not in (int,float):raise ValueError('Medida de imóvel/carteira inválida.')
                                clean[key]=app.number(value,False,0,1 if key in ('vacancy','delinquency','revenue_share') else None)
                            else:clean[key]=app.text_value(value,300)
                        row[collection].append(clean)
            rows.append(row)
        out[group]=sorted(rows,key=lambda r:r['date'])
    return out


def derived_metrics(a):
    snap=a.get('snapshots',{}).get('fii_reports');out={}
    if not snap:return out
    d=snap['data'];monthly=d['monthly'];quarterly=d['quarterly']
    def put(key,value,row,definition):
        if value is not None:out[key]={'value':value,'asof':row['date'],'source_url':row['source_url'],'definition':definition}
    if monthly:
        row=monthly[-1];put('bvps',row['nav'],row,'VPA do informe mensal da CVM, em reais por cota.')
        quote=a.get('snapshots',{}).get('quote',{});price=quote.get('data',{}).get('price')
        if (row['nav'] or 0)>0 and isinstance(price,(int,float)) and price>0:
            try:fresh=(date.today()-date.fromisoformat(quote['asof'])).days<=7 and (date.today()-date.fromisoformat(row['date'])).days<=90
            except (KeyError,ValueError):fresh=False
            if fresh:
                put('pvp',price/row['nav'],row,'Preço da cota de '+quote['asof']+' ÷ VPA CVM de '+row['date']+'. Referências preservadas; avaliações patrimoniais podem ter defasagem.')
        events=a.get('snapshots',{}).get('fii_dividends',{}).get('data',{}).get('items',[])
        if quote and isinstance(price,(int,float)) and price>0:
            ref=date.fromisoformat(quote['asof']);window=ref-timedelta(days=365)
            eligible=[r for r in events if r['type']=='RENDIMENTO' and not r['estimated'] and window.isoformat()<r['date']<=ref.isoformat()]
            if eligible and min(r['date'] for r in events)<=window.isoformat():
                put('dy',sum(r['amount'] for r in eligible)/price*100,{'date':quote['asof'],'source_url':a['snapshots']['fii_dividends']['data']['source_url']},'Rendimentos por cota com datas de pagamento confirmadas em 12 meses ÷ preço da cota. Amortizações e eventos estimados excluídos.')
        if (row['equity'] or 0)>0 and row['obligations'] is not None and row['securitization'] is not None:
            put('fund_leverage',(row['obligations']+row['securitization'])/row['equity']*100,row,
                'Obrigações de aquisição de imóveis + securitização de recebíveis ÷ PL; não é passivo total. Campos vazios não equivalem a zero.')
    if quarterly:
        row=quarterly[-1];props=[p for p in row['properties'] if sector_analysis.fold(p['class'])=='imoveis para renda acabados']
        if props and all((p['area'] or 0)>0 and p['vacancy'] is not None for p in props):
            put('vacancy',sum(p['area']*p['vacancy'] for p in props)/sum(p['area'] for p in props)*100,row,
                'Vacância física ponderada pela área de todos os imóveis para renda acabados do informe trimestral.')
        if props and all(p['revenue_share'] is not None for p in props):
            put('top_property',max(p['revenue_share'] for p in props)*100,row,'Maior imóvel como participação da receita total do FII; não é concentração de inquilino.')
        if props and all(p['revenue_share'] is not None and p['delinquency'] is not None for p in props) and sum(p['revenue_share'] for p in props)>0:
            put('rental_delinquency',sum(p['revenue_share']*p['delinquency'] for p in props)/sum(p['revenue_share'] for p in props)*100,row,
                'Inadimplência dos imóveis para renda acabados ponderada por participação de receita informada; não é inadimplência de CRI.')
        for key in ('ipca_share','igpm_share','short_contracts'):
            put(key,row[key]*100 if row[key] is not None else None,row,'Participação na receita do FII divulgada no informe trimestral, fração convertida para %.')
        # Financial result can include sales. Never pass it off as recurring distribution cover.
        if (row['declared'] or 0)>0 and row['cash_accumulated'] is not None:
            put('cash_distribution_cover',row['cash_accumulated']/row['declared'],row,
                'Resultado financeiro acumulado ÷ rendimentos declarados na janela trimestre/semestre do informe. Inclui eventos não recorrentes; não substitui cobertura recorrente.')
        portfolio=[p for p in row['portfolio'] if p['value'] is not None and p['value']>=0]
        if len(portfolio)==len(row['portfolio']) and portfolio:
            for kind,key in [('cri','top_credit'),('fii','top_fund')]:
                positions=[p for p in portfolio if (kind=='cri' and 'cri' in sector_analysis.fold(p['type'])) or (kind=='fii' and sector_analysis.fold(p['type']) in ('fii','cotas de fii'))]
                if positions and all(p['issuer_cnpj'] or p['issuer'] for p in positions) and sum(p['value'] for p in positions)>0:
                    total=sum(p['value'] for p in positions);issuers={}
                    for p in positions:
                        issuer=p['issuer_cnpj'] or p['issuer'];issuers[issuer]=issuers.get(issuer,0)+p['value']
                    # Securitizer is often not the ultimate debtor: do not infer top_credit.
                    if kind=='fii':put(key,max(issuers.values())/total*100,row,'Maior fundo investido ÷ total das posições em FIIs divulgadas, agrupadas por emissor. Não inclui ativos fora dessa classe.')
    return out


def save(app,a,kind,d,source):
    d=validate_snapshot(app,kind,d)
    if d['symbol']!=a['ticker']:raise ValueError('Dados de outro FII.')
    with app.WRITE_LOCK,app.connect() as c:
        owner=c.execute('SELECT ticker,asset_type FROM assets WHERE id=? AND archived=0',(a['id'],)).fetchone()
        if not owner or owner['ticker']!=d['symbol'] or owner['asset_type']!='fii':raise ValueError('O FII mudou durante a consulta.')
        previous=app.latest(c,a['id']).get(kind,{}).get('data',{})
        if kind=='fii_reports' and previous:
            if previous['profile']['cnpj']!=d['profile']['cnpj']:raise ValueError('CNPJ divergente; histórico anterior preservado.')
            for group in ('monthly','quarterly'):
                merged={r['date']:r for r in previous[group]}
                for r in d[group]:
                    old=merged.get(r['date'],{})
                    merged[r['date']]={**old,**{k:v for k,v in r.items() if v is not None}} if old else dict(r)
                d[group]=sorted(merged.values(),key=lambda r:r['date'])[-(36 if group=='monthly' else 12):]
        if kind=='fii_dividends' and previous:
            merged={(r['date'],r['type']):r for r in previous['items']}
            merged.update({(r['date'],r['type']):r for r in d['items']});d['items']=sorted(merged.values(),key=lambda r:r['date'])[-2000:]
        refs=[r['date'] for g in ('monthly','quarterly','items') for r in d.get(g,[])]
        ref=max(refs) if refs else d.get('asof',app.today().isoformat())
        app.add_snapshot(c,a['id'],kind,d,source,ref)
        app.log_source(c,kind+'_'+str(a['id']),a['ticker']+' · pesquisa de FII',d.get('source_url',''),asof=ref)


def refresh(app,a):
    received=[];warnings=[]
    with app.connect() as c:token=app.settings(c).get('brapi_token') or os.getenv('BRAPI_TOKEN','')
    from aporte_brasil.market import extra_sources
    # The dossier refresh must fetch the current price too, without requiring a global update.
    groups={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks=[('quote',pool.submit(app.fetch_stock,a,'quote',token)),
               ('indicators',pool.submit(app.fetch_fii,a,app.request_json,token,app.valid_date,app.clean,app.today)),
               ('yahoo',pool.submit(extra_sources.yahoo,a['ticker'],app.request_json,app.today,False))]
        for key,task in tasks:
            try:
                result=task.result()
                if key=='yahoo':
                    for kind,value in result.items():
                        if kind not in groups or value[1]>groups[kind][1]:groups[kind]=value
                else:
                    kind,data,ref=result;groups[kind]=(data,ref,'brapi · '+('fii/indicators' if key=='indicators' else 'stocks/quote'))
            except (ValueError,KeyError,TypeError) as exc:
                if key!='yahoo':warnings.append(key+': '+(str(exc) if isinstance(exc,ValueError) else 'Fonte sem formato reconhecido.'))
    with app.WRITE_LOCK,app.connect() as c:
        owner=c.execute('SELECT ticker,asset_type FROM assets WHERE id=? AND archived=0',(a['id'],)).fetchone()
        if not owner or owner['ticker']!=a['ticker'] or owner['asset_type']!='fii':raise ValueError('O FII mudou durante a consulta.')
        for kind,(data,ref,source) in groups.items():
            app.add_snapshot(c,a['id'],kind,data,source,ref);received.append(kind)
            app.log_source(c,'asset_'+str(a['id'])+'_'+kind,a['ticker']+' · '+kind,extra_sources.source_url(source,a['ticker']) or 'https://brapi.dev/docs/fiis/indicadores',asof=ref)
    try:
        payload,errors=public_reports.fetch_fii(a,app.today());save(app,a,'fii_reports',payload,'CVM · informes mensais e trimestrais')
        received.append('fii_reports');warnings.extend(errors)
    except (ValueError,KeyError,TypeError) as exc:warnings.append(str(exc) if isinstance(exc,ValueError) else 'Formato CVM não reconhecido; histórico anterior preservado.')
    try:
        query=urllib.parse.urlencode({'symbols':a['ticker'],'startDate':str(app.today().year-5)+'-01-01','endDate':app.today().isoformat()})
        raw=app.request_json('https://brapi.dev/api/v2/fii/dividends?'+query,token)
        rows=raw.get('dividends')
        if not isinstance(rows,list) or any(r.get('symbol')!=a['ticker'] for r in rows):raise ValueError('Rendimentos sem identidade confirmada.')
        events={}
        for r in rows:
            label=r.get('label');ref=str(r.get('paymentDate') or '')[:10]
            if label not in ('RENDIMENTO','AMORTIZAÇÃO'):continue
            amount=public_reports.numeric(r.get('rate'))
            if amount is None:continue
            event=events.setdefault((ref,label),{'date':ref,'type':label,'amount':0,'estimated':False})
            event['amount']+=amount;event['estimated']|='backfilled' in str(r.get('remarks') or '').lower()
        events={key:r for key,r in events.items() if r['date'] and r['date']<=app.today().isoformat()}
        if not events:raise ValueError('Sem eventos históricos de rendimentos na fonte.')
        save(app,a,'fii_dividends',{'symbol':a['ticker'],'items':list(events.values()),'source_url':'https://brapi.dev/docs/fiis/dividendos'},'brapi · rendimentos de FIIs')
        received.append('fii_dividends')
    except (ValueError,KeyError,TypeError) as exc:
        warnings.append('Rendimentos brapi: '+(str(exc) if isinstance(exc,ValueError) else 'Fonte sem formato reconhecido.')+' Dados detalhados podem exigir plano Pro; tentando a série pública Yahoo.')
        try:
            events,prices,splits=public_reports.market_dividends(app,a)
            if not events:raise ValueError('Sem eventos públicos de rendimentos.')
            items=[{'date':ref,'amount':amount,'type':'RENDIMENTO','estimated':True} for ref,amount in events.items()]
            save(app,a,'fii_dividends',{'symbol':a['ticker'],'items':items,'source_url':'https://finance.yahoo.com/quote/'+a['ticker']+'.SA/history/'},'Yahoo · eventos de proventos por data ex, pagamentos/amortizações a conferir')
            received.append('fii_dividends')
        except (ValueError,KeyError,TypeError) as fallback:warnings.append('Rendimentos Yahoo: '+(str(fallback) if isinstance(fallback,ValueError) else 'Sem eventos reconhecidos.'))
    try:
        from aporte_brasil.company import multiple_history
        received.extend(multiple_history.refresh(app,a)['received'])
    except (ValueError,KeyError,TypeError) as exc:warnings.append('Histórico de preços para P/VP e DY: '+(str(exc) if isinstance(exc,ValueError) else 'Formato da fonte não reconhecido; dados anteriores preservados.'))
    with app.WRITE_LOCK,app.connect() as c:
        app.write_cache(c,'fii_attempt_'+str(a['id']),{'at':app.now(),'warnings':warnings})
    return {'received':received,'warnings':warnings}


def study(app,a):
    profile=subtype(a); groups={k:{'key':k,'label':label,'checks':[]} for k,label in
        [('requested_fii','Seus seis critérios para FIIs'),('history','Patrimônio e histórico'),('income','Resultado e rendimentos'),('sector','Riscos do segmento · '+TYPES[profile]),('price','Preço e comparação') ]}
    requested=fii_quality.assess(app,a,profile)
    groups['requested_fii']['checks']=requested['checks']
    d=a.get('snapshots',{}).get('fii_reports',{}).get('data',{});monthly=d.get('monthly',[]);quarterly=d.get('quarterly',[])
    def add(group,key,label,status,detail,row=None):
        row=row or {};groups[group]['checks'].append({'key':key,'label':label,'status':status,'detail':detail,'asof':row.get('date'),
            'source_url':row.get('source_url',d.get('source_url',''))})
    latest=monthly[-1] if monthly else {};fresh=bool(latest) and app.age(latest['date'])<=90
    classification=a.get('snapshots',{}).get('fii_classification',{}).get('data',{})
    profile_reference={'date':classification['asof'],'source_url':classification['source_url']} if classification else latest
    add('history','profile_known','Perfil do fundo identificado','unknown' if profile=='unknown' else 'pass',
        'Usa o perfil conferido, a composição patrimonial ou o segmento divulgado. Quando o perfil é desconhecido, confirme o regulamento para selecionar os critérios próprios do negócio.',profile_reference)
    add('history','nav_positive','Patrimônio líquido e VPA positivos','unknown' if not fresh or latest.get('equity') is None or latest.get('nav') is None else 'pass' if min(latest['equity'],latest['nav'])>0 else 'fail','Exige informe mensal recente (até 90 dias) e patrimônio positivo; valor contábil não confirma preço de venda dos ativos.',latest)
    recent=[r for r in monthly if app.age(r['date'])<=400];months={r['date'][:7] for r in recent}
    expected=app.today().year*12+app.today().month-1
    complete=all(f'{n//12:04d}-{n%12+1:02d}' in months for n in range(expected-12,expected))
    add('history','monthly12','Últimos 12 informes mensais disponíveis','pass' if complete else 'unknown',f'{len(months)} meses recentes encontrados. Exige os 12 meses anteriores completos; atraso de divulgação continua pendente.',latest)
    started=d.get('profile',{}).get('started')
    add('history','operating5','Fundo em funcionamento há mais de 5 anos','unknown' if not started else 'pass' if (app.today()-date.fromisoformat(started)).days>365.25*5 else 'fail','Data de funcionamento na CVM. Não equivale à primeira negociação na bolsa.',{'date':started})
    q=quarterly[-1] if quarterly else {};value=q.get('cash_result') if q and app.age(q['date'])<=180 else None
    add('income','cash_positive','Resultado financeiro trimestral positivo','unknown' if value is None else 'pass' if value>0 else 'fail','Resultado financeiro do informe trimestral; vendas, ganhos e perdas podem ser extraordinários. Não é lucro recorrente.',q)
    for key,op,limit,label in [('cash_distribution_cover','ge',1,'Resultado financeiro acumulado cobre o declarado'),('distribution_cover','ge',1,'Resultado recorrente cobre a distribuição')]:
        v,s,reason=sector_analysis.metric(a,key,app.age)
        add('income',key,label,'unknown' if v is None else 'pass' if v>=limit else 'fail',
            (f'{v:.2f}×. ' if v is not None else reason+' ')+('Pode incluir vendas e reservas; a janela acumulada do informe não comprova recorrência.' if key=='cash_distribution_cover' else 'Exige definição recorrente no relatório do gestor e mesma janela de distribuição.'),{'date':s.get('asof'),'source_url':s.get('url','')})
    items=a.get('snapshots',{}).get('fii_dividends',{}).get('data',{}).get('items',[])
    rend=[r for r in items if r['type']=='RENDIMENTO' and r['amount']>0 and app.age(r['date'])<=400]
    paymentmonths={r['date'][:7] for r in rend if not r['estimated']}
    payments=all(f'{n//12:04d}-{n%12+1:02d}' in paymentmonths for n in range(expected-12,expected))
    add('income','payments12','Rendimentos registrados nos últimos 12 meses','pass' if payments else 'unknown',f'{len(paymentmonths)} meses com pagamentos positivos disponíveis. Amortizações são excluídas. Eventos reconstruídos do informe têm mês de referência, sem data real de pagamento confirmada.',rend[-1] if rend else {})
    for c in a['sector_analysis']['checks']:
        if c['metric']=='distribution_cover':continue
        v=c['value'];limit=c['limit'];_,s,_=sector_analysis.metric(a,c['metric'],app.age)
        add('price' if c['group']!='health' else 'sector',c['metric'],c['label'],c['status'],
            (f'Valor: {v:g}{c["unit"]}. ' if v is not None else '')+(f'Corte de estudo: {limit:g}{c["unit"]}. ' if limit is not None else '')+c['reason']+' '+c['note'],{'date':s.get('asof'),'source_url':s.get('url','')})
    quality=[c for k,g in groups.items() if k!='price' for c in g['checks'] if c.get('scope')!='price']
    counts={s:sum(c['status']==s for c in quality) for s in ('pass','fail','unknown','na')};total=len(quality)-counts['na']
    discard=requested['screening']['discard']
    status='review' if counts['fail'] or discard else 'incomplete' if counts['unknown'] else 'within'
    price_checks=groups['price']['checks']+[c for c in requested['checks'] if c.get('scope')=='price']
    price={s:sum(c['status']==s for c in price_checks) for s in counts}
    return {'groups':list(groups.values()),'counts':counts,'price_counts':price,'total':total,'status':status,
        'screening':requested['screening'],
        'label':'Descartado: P/VP acima de 1,5' if discard else {'review':'Pontos de atenção','incomplete':'Avaliação incompleta','within':'Dentro dos critérios de estudo'}[status],
        'coverage':f'{counts["pass"]+counts["fail"]} de {total} critérios do FII com dados',
        'summary':('Descarte pela sua regra de preço. ' if discard else '')+f'{counts["pass"]} atendem · {counts["fail"]} a revisar · {counts["unknown"]} pendentes',
        'note':'Critérios próprios por tipo de fundo. Lucro, ROE, EBITDA e tag along de empresas não são cobrados dos FIIs. Sua regra fixa de P/VP acima de 1,5 aciona descarte na triagem; os demais cortes gerais continuam ajustáveis. Preço e notícias não aprovam a qualidade dos ativos.'}


def enrich(app,a,c):
    if a['asset_type']!='fii':return
    typ=subtype(a);focus=[]
    for key in FOCUS[typ]:
        v,s,reason=sector_analysis.metric(a,key,app.age);where,sources=sector_analysis.indicator_source(key)
        info=sector_analysis.INDICATOR_INFO[key]
        focus.append({'metric':key,'title':info['label'],'reading':info['reading'],'value':v,'unit':info['unit'],'asof':s.get('asof'),'source':s.get('source'),'reason':reason,'where':where,'sources':sources})
    drivers=company_insights.drivers(app,{**a,'snapshots':{**a['snapshots'],'issuer_drivers':a['snapshots'].get('fii_drivers',{})}})
    for r in drivers['rows']:
        r['explanation']='Juros maiores podem elevar o desconto exigido e os custos de obrigações. Em CRIs ligados ao CDI, podem elevar a receita nominal, enquanto o risco de crédito precisa de revisão. Juros menores podem inverter esses canais; preços também dependem da curva longa, prêmios e qualidade dos ativos.' if r['key']=='rates' else 'O dólar pode afetar custos de construção e a atividade dos locatários/devedores; confirme a exposição dos contratos. Não há efeito direto uniforme sobre os FIIs.'
    drivers['note']='Canais de impacto para FIIs, sem projeção de preço. Compare Selic e curva longa, CDI/IPCA dos recebíveis, reajustes dos aluguéis e capacidade de pagamento. IPCA e IGP-M exibidos abaixo são pesos dos contratos divulgados, não previsões de inflação.'
    a['fii_research']={'type':typ,'type_label':TYPES[typ],'types':TYPES,'reports':a['snapshots'].get('fii_reports'),
        'dividends':a['snapshots'].get('fii_dividends'),'quality_facts':a['snapshots'].get(fii_quality.KIND),'study':study(app,a),'sector_focus':focus,'drivers':drivers,
        'attempt':app.read_cache(c,'fii_attempt_'+str(a['id']),{}),'news_context':None}


def action(app,path,d):
    if not isinstance(d,dict) or isinstance(d.get('asset_id'),bool):raise ValueError('Pedido do FII inválido.')
    aid=int(app.number(d.get('asset_id'),True,1));a=next((a for a in app.state()['assets'] if a['id']==aid and a['asset_type']=='fii'),None)
    if not a:raise ValueError('Escolha um FII cadastrado.')
    if path in ('/api/fii/research','/api/fii/drivers'):
        if set(d)!={'asset_id'}:raise ValueError('Pedido do FII inválido.')
        if path.endswith('/research'):return {'ok':True,**refresh(app,a)}
        adapted={**a,'ticker':a['ticker'],'snapshots':{**a['snapshots'],'issuer_drivers':a['snapshots'].get('fii_drivers',{})}}
        payload=company_insights.fetch_drivers(app,adapted);payload['symbol']=a['ticker']
        save(app,a,'fii_drivers',payload,'Banco Central · fatores de mercado do FII');return {'ok':True,'warnings':payload['warnings']}
    kind={'/api/fii/classification':'fii_classification','/api/fii/quality-facts':fii_quality.KIND}.get(path)
    if not kind or set(d)!={'asset_id','data'}:raise ValueError('Ação do FII inválida.')
    save(app,a,kind,d['data'],'Manual · critérios conferidos do FII' if kind==fii_quality.KIND else 'Manual · perfil conferido do FII');return {'ok':True}
