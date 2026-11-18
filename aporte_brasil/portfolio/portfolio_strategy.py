"""Contribution planning from user goals; scores are research priorities, not expected returns."""
from decimal import Decimal, ROUND_HALF_UP
import re

CLASSES={'rf':'Renda fixa','national':'Ações nacionais','international':'Internacional',
         'fii':'Fundos imobiliários','crypto':'Bitcoin / cripto','other':'Outros / a classificar'}
REFERENCE='https://www.gov.br/investidor/pt-br/investir/tipos-de-investimentos/etfs/como-reduzir-o-risco'

def targets(value,number):
    if value is None: return None
    if not isinstance(value,dict) or set(value)!=set(CLASSES):raise ValueError('Informe uma meta para cada classe.')
    if any(isinstance(v,bool) for v in value.values()):raise ValueError('Metas precisam ser percentuais numéricos.')
    result={k:number(v,True,0,100) for k,v in value.items()}
    if abs(sum(result.values())-100)>0.000001:raise ValueError('A soma das metas deve ser 100%.')
    return result

def overrides(value):
    if not isinstance(value,dict) or len(value)>10000:raise ValueError('Classificações inválidas.')
    if any(not re.fullmatch(r'(asset|fixed):[1-9]\d{0,10}',k) or v not in CLASSES for k,v in value.items()):
        raise ValueError('Classe ou investimento inválido.')
    return value

def classify(item,is_fixed=False):
    if is_fixed:
        if item['type'] in ('Tesouro','CDB','LCI','LCA','CRI','CRA','CDB/LCI/LCA','Fundo de renda fixa'):return 'rf'
        if item['type']=='Fundo de ações':return 'national'
        return 'other'
    typ=item.get('asset_type','stock');sector=item.get('sector','')
    if typ in ('bdr','foreign','global_stock','global_etf'):return 'international'
    if typ=='fii':return 'fii'
    if typ=='crypto':return 'crypto'
    if typ=='etf':
        from aporte_brasil.portfolio import investment_exposure
        meta=item.get('exposure') or investment_exposure.metadata({**item,'ticker':item.get('ticker','')},{})
        family=meta.get('asset_class')
        if family=='mixed':return 'other'
        if family in ('fixed_income','crypto','real_estate'):return {'fixed_income':'rf','crypto':'crypto','real_estate':'fii'}[family]
        if family=='equity':return 'national' if meta.get('scope')=='BR' else 'international' if meta.get('scope') in ('US','GLOBAL','EU','EM') else 'other'
        return {'ETF · Ações Brasil':'national','ETF · Ações exterior':'international','ETF · Renda fixa':'rf','ETF · Cripto':'crypto'}.get(sector,'other')
    return 'national'

def allocation(assets,fixed,cfg,age):
    sums={k:0.0 for k in CLASSES};items=[];issues=[];over=cfg.get('allocation_overrides',{})
    for is_fixed,rows in ((False,assets),(True,fixed)):
        for row in rows:
            ident=('fixed:' if is_fixed else 'asset:')+str(row['id'])
            cls=over.get(ident,classify(row,is_fixed));value=row['balance'] if is_fixed else row['value']
            held=is_fixed or row['position']['quantity']>0
            if held:
                sums[cls]+=value
                label=row['name'] if is_fixed else row['ticker']
                if cls=='other':issues.append(label+': confirme a classe para comparar com suas metas.')
                if is_fixed and age(row.get('balance_date'))>60:issues.append(label+': saldo do extrato com mais de 60 dias.')
                if is_fixed and any(row.get('metadata',{}).get(k,{}).get('valuation')=='cost' for k in ('treasury','bank_fixed')):
                    issues.append(label+': calculado pelo custo importado; informe o saldo atual do extrato.')
                if not is_fixed and (row.get('value_at_cost') or age(row.get('snapshots',{}).get('quote',{}).get('asof'))>7):
                    issues.append(label+': cotação ausente ou com mais de 7 dias; peso estimado.')
            items.append({'key':ident,'name':row['name'] if is_fixed else row['ticker'], 'class':cls,'value':value,'held':held,'manual':ident in over})
    total=sum(sums.values());goals=cfg.get('allocation_targets')
    return {'total':total,'classes':[{'key':k,'label':v,'value':sums[k],
        'weight':sums[k]/total*100 if total else 0,'target':goals[k] if goals else None,
        'gap':goals[k]-(sums[k]/total*100 if total else 0) if goals else None} for k,v in CLASSES.items()],
        'items':items,'issues':issues,'has_targets':goals is not None,'reference':REFERENCE}

def split_cents(cents,weights):
    """Exact money allocation, stable tie breaking, no independently rounded shares."""
    weights=[Decimal(str(w)) for w in weights]
    total=sum(weights)
    if total<=0:raise ValueError('Não há destino válido para este aporte.')
    raw=[Decimal(cents)*w/total for w in weights];parts=[int(x) for x in raw]
    for i in sorted(range(len(raw)),key=lambda i:raw[i]-parts[i],reverse=True)[:cents-sum(parts)]:parts[i]+=1
    return parts

def distribution(a,d,cents,number):
    cap=d.get('max_destinations','all')
    if isinstance(cap,bool) or str(cap) not in ('all','1','2'):raise ValueError('Escolha um, dois ou todos os destinos.')
    chosen=d.get('destinations',[])
    if not isinstance(chosen,list) or any(not isinstance(k,str) for k in chosen) or len(chosen)!=len(set(chosen)):
        raise ValueError('Selecione destinos diferentes.')
    lookup={r['key']:{**r,'label':r['name'],'specific':True} for r in a['items']}
    lookup.update({'class:'+r['key']:{'key':'class:'+r['key'],'class':r['key'],'label':r['label']+' · produto a escolher','specific':False,'value':r['value']} for r in a['classes']})
    if chosen:
        if cap=='all' or len(chosen)>int(cap) or any(k not in lookup for k in chosen):raise ValueError('Confira os destinos e o limite de aportes escolhidos.')
        share=number(d.get('first_percent',50),True,.01,99.99) if len(chosen)==2 else 100
        if isinstance(d.get('first_percent'),bool):raise ValueError('Informe um percentual numérico para o primeiro aporte.')
        weights=[share,100-share] if len(chosen)==2 else [100]
        destinations=[dict(lookup[k]) for k in chosen]
        method='Você escolheu os investimentos e a divisão. O cenário aceita classes acima da meta; confira os pesos depois do aporte.'
    else:
        gaps=[(r,max(0,r['target']/100*(a['total']+cents/100)-r['value'])) for r in a['classes']]
        gaps=sorted((pair for pair in gaps if pair[1]>0),key=lambda p:-p[1])
        if cap!='all':gaps=gaps[:int(cap)]
        destinations=[dict(lookup['class:'+r['key']]) for r,g in gaps];weights=[g for r,g in gaps]
        method='Classes com os maiores déficits em reais após o aporte, limitadas à quantidade escolhida. Divisão proporcional apenas entre essas classes; o produto ainda precisa ser escolhido.'
    parts=split_cents(cents,weights);by_class={k:0 for k in CLASSES};total=a['total']+cents/100
    for r,p in zip(destinations,parts):
        by_class[r['class']]+=p;r['amount']=p/100;r['after_weight']=(r['value']+p/100)/total*100
    return [r for r in destinations if r['amount']>0],by_class,method

def plan(app,d):
    amount=app.number(d.get('amount'),True,.01,1e12)
    if isinstance(d.get('amount'),bool):raise ValueError('Informe o valor do aporte.')
    state=app.state();a=state['allocation'];cfg=state['settings']
    if not a['has_targets']:raise ValueError('Salve suas metas antes de distribuir um aporte.')
    if a['issues'] and d.get('accept_estimates') is not True:raise ValueError('Atualize os saldos e classificações ou confirme o uso das estimativas.')
    cents=int((Decimal(str(amount))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP));amount=cents/100
    destinations,alloc,method=distribution(a,d,cents,app.number)
    rows=[{**r,'amount':alloc[r['key']]/100,'after_weight':(r['value']+alloc[r['key']]/100)/(a['total']+amount)*100} for r in a['classes']]
    selected_keys={r['key'] for r in destinations};warnings=[]
    for r in destinations:
        row=next(c for c in rows if c['key']==r['class'])
        if row['after_weight']>row['target']+.01:warnings.append(r['label']+': a classe ficará acima da meta ('+format(row['after_weight'],'.2f')+'%).')
        if r['key'].startswith('asset:'):
            stock=next(s for s in state['assets'] if 'asset:'+str(s['id'])==r['key'])
            alert=stock.get('valuation_alert',{})
            if alert.get('status') in ('expensive','above'):warnings.append(stock['ticker']+': '+alert['title'])
            fails=[c['label'] for c in stock['sector_analysis']['checks'] if c['status']=='fail' and c['group']=='health']
            if fails:warnings.append(stock['ticker']+': revisar critérios de saúde — '+', '.join(fails))
            equity=sum(s['value'] for s in state['assets'])+sum(x['amount'] for x in destinations if x['key'].startswith('asset:'))
            if equity and (stock['value']+r['amount'])/equity*100>=cfg['asset_limit']:warnings.append(stock['ticker']+': o peso simulado atinge seu limite por ativo na carteira negociada.')
    candidates=[]
    for stock in state['assets']:
        if stock.get('asset_type')!='stock':continue
        checks=stock['sector_analysis']['checks'];fail=[r['label'] for r in checks if r['status']=='fail'];pending=sum(r['status']=='unknown' for r in checks)
        cls=next(r['class'] for r in a['items'] if r['key']=='asset:'+str(stock['id']))
        budget=next(r['amount'] for r in rows if r['key']==cls)
        reasons=[]
        if not budget:reasons.append('Classe sem aporte neste cenário pelas suas metas.')
        if d.get('destinations') and 'asset:'+str(stock['id']) not in selected_keys and 'class:'+cls not in selected_keys:reasons.append('Ativo fora dos destinos que você escolheu.')
        if stock.get('valuation_alert',{}).get('status')=='expensive':reasons.append('Preço elevado nos cenários por fórmula; revisar antes de aportar.')
        if stock['analysis'].get('score') is not None:
            if stock.get('weight',0)>=cfg['asset_limit']:reasons.append('Posição já atinge seu limite por ativo.')
            if stock.get('sector_weight',0)>=cfg['sector_limit']:reasons.append('Setor já atinge seu limite de concentração.')
        reasons+=fail
        score=stock['analysis'].get('score')
        if score is None:reasons+=stock['analysis'].get('problems',[])[:4]
        candidates.append({'id':stock['id'],'ticker':stock['ticker'],'class':cls,'held':stock['position']['quantity']>0,
            'score':score,'eligible':score is not None and not reasons,'pending':pending,'reasons':reasons})
    candidates.sort(key=lambda r:(not r['eligible'],-(r['score'] if r['score'] is not None else -1),r['ticker']))
    cdi=state['macro'].get('cdi');benchmark=None
    if cdi and app.age(cdi['asof'])<=7:
        p=app.projection({'principal':amount,'months':12,'product':'CDB','tax_mode':'auto','fee':0,'indexer':'CDI','rate':100,'cdi':cdi['value'],'ipca':state['macro'].get('ipca',{}).get('value')})
        benchmark={'annual_net':(p['net']/amount-1)*100,'net':p['net'],'tax':p['tax'],'cdi':cdi['value'],'asof':cdi['asof'],'source':cdi['source']}
    return {'amount':amount,'classes':rows,'destinations':destinations,'warnings':list(dict.fromkeys(warnings)),'candidates':candidates,'issues':a['issues'],'benchmark':benchmark,
        'distance_before':sum(abs(r['weight']-r['target']) for r in rows)/2,
        'distance_after':sum(abs(r['after_weight']-r['target']) for r in rows)/2,
        'method':method+' A simulação não registra compras nem vendas. A nota ordena pesquisa: 45% múltiplos relativos, 35% qualidade e 20% tendência; não estima retorno.',
        'note':'Fundos, ETFs, FIIs, Bitcoin e exterior recebem orçamento por classe, sem nota fundamentalista de empresa. Revise liquidez, prazo, custos e riscos antes de escolher o produto.'}
