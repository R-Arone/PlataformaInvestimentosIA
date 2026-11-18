"""Dated macro observations and explicit conditional channels, not price forecasts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import math,re,urllib.parse
from aporte_brasil.portfolio import sector_analysis

DIRECTIONS={'favorable':'Pressão de alta no cenário','unfavorable':'Pressão de baixa no cenário',
            'mixed':'Forças em sentidos diferentes','neutral':'Sem pressão direcional neste canal',
            'unknown':'Sem base para concluir a direção'}
HORIZONS={'short':'Até 3 meses','medium':'3 a 12 meses','long':'Acima de 12 meses'}
BCB={'title':'BCB · canais de transmissão da política monetária','url':'https://www.bcb.gov.br/en/monetarypolicy/transmission_channels'}
IMF={'title':'FMI · riscos geopolíticos e estabilidade financeira (2025)','url':'https://www.imf.org/en/Publications/GFSR/Issues/2025/04/22/global-financial-stability-report-april-2025'}
DEFAULT={'rates':'observed','usd':'observed','geopolitics':'headlines','energy':'headlines','metals':'unknown','horizon':'medium'}
FACTORS={'rates':'Juros brasileiros','usd':'Dólar em reais','geopolitics':'Risco geopolítico','energy':'Petróleo / energia','metals':'Metais · ouro, prata, cobre e minério'}

def validate_scenario(app,d):
    keys=set(DEFAULT)|{'asof','source'}
    if not isinstance(d,dict) or set(d) not in (keys,keys-{'metals'}):raise ValueError('Confira os campos do cenário.')
    d={**DEFAULT,**d}
    for k in FACTORS:
        options={'up','down','flat','unknown', 'observed' if k in ('rates','usd') else 'headlines'}
        if not isinstance(d[k],str) or d[k] not in options:raise ValueError('Hipótese inválida: '+FACTORS[k])
    if not isinstance(d['horizon'],str) or d['horizon'] not in HORIZONS:raise ValueError('Horizonte inválido.')
    ref=app.valid_date(d['asof'])
    if ref>app.today().isoformat():raise ValueError('O cenário não pode ter referência futura.')
    return {**d,'asof':ref,'source':app.text_value(d['source'],500,True)}

def observation(rows,day,key,url):
    if not isinstance(rows,list) or len(rows)>120:raise ValueError('Série do BCB fora do limite esperado.')
    points={}
    for r in rows:
        try:
            ref=datetime.strptime(r['data'],'%d/%m/%Y').date();value=float(str(r['valor']).replace(',','.'))
        except (KeyError,TypeError,ValueError):continue
        if day-timedelta(days=90)<=ref<=day and math.isfinite(value) and value>0:points[ref]=value
    if not points:raise ValueError('Série sem observações válidas no período.')
    latest=max(points);earlier=[t for t in points if t<=latest-timedelta(days=30)]
    if not earlier:raise ValueError('Sem ponto anterior para comparar 30 dias.')
    previous=max(earlier);diff=points[latest]-points[previous]
    change=diff/points[previous]*100
    # Currency moves below 1% are deliberately treated as flat, not significance tests.
    delta=diff if key=='rates' else change;band=.001 if key=='rates' else 1
    direction='up' if delta>band else 'down' if delta<-band else 'flat'
    return {'current':points[latest],'previous':points[previous],'asof':latest.isoformat(),
            'previous_asof':previous.isoformat(),'change':change,'difference':diff,'direction':direction,
            'source_url':url,'source':'BCB/SGS '+('432' if key=='rates' else '1'),
            'stale':(day-latest).days>7}

def fetch_context(request_json,day,stamp):
    context={'retrieved_at':stamp,'observations':{},'errors':[]}
    def read(key,code):
        query=urllib.parse.urlencode({'formato':'json','dataInicial':(day-timedelta(days=90)).strftime('%d/%m/%Y'),'dataFinal':day.strftime('%d/%m/%Y')})
        url=f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?{query}'
        return observation(request_json(url),day,key,url)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending={key:pool.submit(read,key,code) for key,code in (('rates',432),('usd',1))}
        for key,task in pending.items():
            try:context['observations'][key]=task.result()
            except Exception as exc:context['errors'].append(FACTORS[key]+': '+(str(exc) if isinstance(exc,ValueError) else 'Fonte indisponível.'))
    return context

def headline_hints(report,day,factor):
    hints=[]
    for r in report.get('headlines',[]):
        try:
            stamp=datetime.fromisoformat(r['published_at'])
            ref=stamp.astimezone(timezone(timedelta(hours=-3))).date() if stamp.tzinfo else stamp.date()
        except (ValueError,TypeError,KeyError):continue
        if not 0<=(day-ref).days<=7:continue
        text=sector_analysis.fold(r['title'])
        if re.search(r'\b(nao|sem|nega|evita|pode|poderia|preve|previsao|espera|deve|teme)\b',text):continue
        if factor=='geopolitics':
            relevant=any(w in text for w in ('guerra','conflito','militar','sancoes','geopolit','cessar-fogo','acordo de paz','tensao'))
            up=re.search(r'escalada|ataque|intensifica|agrava|aumenta.*tens|sancoes',text)
            down=re.search(r'cessar.fogo|acordo de paz|distensao|reduz.*tens',text)
        elif factor=='metals':
            relevant=bool(re.search(r'\bouro\b|\bprata\b|\bcobre\b|minerio|\baco\b|metais',text))
            up=re.search(r'\bsobe\b|\balta\b|\bavanca\b|\bdispara\b',text)
            down=re.search(r'\bcai\b|\bqueda\b|\brecua\b|\btomba\b',text)
        else:
            relevant=bool(re.search(r'petroleo|brent|wti',text))
            up=re.search(r'\bsobe\b|\balta\b|\bavanca\b|\bdispara\b',text)
            down=re.search(r'\bcai\b|\bqueda\b|\brecua\b|\btomba\b',text)
        if relevant and bool(up)!=bool(down):hints.append({**r,'direction':'up' if up else 'down'})
    return hints[:3]

def channel(profile,factor,direction):
    """Rules authored for screening; company exposure can reverse the sector mechanism."""
    if direction=='unknown':return 'unknown','Não há uma hipótese direcional confirmada para este canal.'
    if direction=='flat':return 'neutral','Sem mudança relevante nesta hipótese; nível, expectativas e preços já incorporados ainda importam.'
    rising=direction=='up'
    if factor=='metals':
        return 'mixed','Metais '+('mais caros podem favorecer receita de produtores e elevar custos de consumidores industriais.' if rising else 'mais baratos podem pressionar receita de produtores e aliviar custos de consumidores industriais.')+' Ouro/prata, cobre, minério e aço respondem a fatores diferentes. Identifique o metal, volume, câmbio, custos e hedges; um sinal agregado não determina o preço da empresa.'
    if factor=='rates':
        if profile in ('retail','construction','utility','technology','education','health','industrial','transport','telecom','food_agro','general'):
            return ('unfavorable' if rising else 'favorable'),('Juros maiores podem reduzir consumo/investimento, elevar custo de dívida e retorno exigido.' if rising else 'Juros menores podem facilitar crédito, consumo e investimento e reduzir custo de dívida e retorno exigido.')+' O efeito depende da curva de mercado, contratos e de quanto já foi antecipado no preço.'
        if profile=='fii':return 'mixed','Juros menores podem favorecer o preço de cotas e imóveis, mas reduzir rendimentos de FIIs ligados ao CDI; juros maiores podem fazer o inverso. Separe tijolo, papel e indexadores.'
        return 'mixed','Juros afetam captação, crédito, renda financeira, demanda e valuation em sentidos diferentes. Para bancos/seguros, confira margens, provisões e carteira; para ETFs/exterior/cripto, a Selic brasileira isolada não determina preço.'
    if factor=='usd':
        if profile in ('foreign','crypto'):return ('favorable' if rising else 'unfavorable'),'Canal de conversão: se o preço em dólares ficar constante, dólar maior eleva o valor em reais, e dólar menor reduz. A cotação externa pode compensar ou inverter esse efeito.'
        return 'mixed','Dólar maior pode beneficiar receita de exportadores e encarecer insumos, importações e dívida externa; dólar menor pode fazer o inverso. A exposição cambial e os hedges do ativo precisam ser confirmados.'
    if factor=='geopolitics':
        if profile in ('commodity','metals','food_agro'):return 'mixed','Escalada pode pressionar o prêmio de risco e a demanda, mas elevar certos preços de energia/alimentos/metais preciosos. Distensão pode reduzir o prêmio de risco e também os preços dessas commodities. Separe produtor, processador e exportador.'
        if profile in ('crypto','etf','foreign'):return 'mixed','Risco geopolítico altera liquidez, moedas, aversão a risco e composição do índice. Não presume Bitcoin como proteção nem direção única para toda carteira internacional.'
        return ('unfavorable' if rising else 'favorable'),('Se a escalada for confirmada, maior prêmio de risco, custos e incerteza podem pressionar cotações.' if rising else 'Se a distensão for confirmada, menor prêmio de risco e incerteza podem favorecer cotações.')+' Inflação, atividade e acontecimentos específicos podem contrariar o canal.'
    if profile=='commodity':return 'mixed','Petróleo mais caro pode favorecer produtores e prejudicar refino, demanda ou custos. Petróleo mais barato pode inverter os efeitos. Minério e celulose não recebem automaticamente o mesmo sinal.'
    if profile=='metals':return 'mixed','Petróleo e energia alteram custos de extração, transporte e siderurgia. Repasses, contratos e o preço do metal podem compensar ou inverter esse efeito.'
    if profile in ('retail','transport','industrial','food_agro','general'):return ('unfavorable' if rising else 'favorable'),'Petróleo/energia mais caro pode elevar frete, combustíveis e custos; uma queda pode aliviar. Repasses, contratos e câmbio podem compensar o efeito.'
    return 'mixed','Energia pode afetar inflação, juros e custos em sentidos diferentes. O vínculo com este perfil não basta para indicar uma direção única.'

def recent(ref,day):
    try:return 0<=(day-datetime.fromisoformat(ref).date()).days<=7
    except (ValueError,TypeError):return False

def outlook(report,day):
    scenario=report.get('scenario') or DEFAULT;profile=report['profile'];drivers=[]
    for factor,label in FACTORS.items():
        selection=scenario.get(factor,DEFAULT[factor]);direction='unknown';refs=[];basis='Sem informação recente.';origin='unknown'
        if selection=='observed':
            obs=report.get('macro_context',{}).get('observations',{}).get(factor)
            if obs and recent(obs.get('asof'),day):
                direction=obs['direction'];origin='observed';refs=[{'title':obs['source'],'url':obs['source_url']}]
                unit='% a.a.' if factor=='rates' else 'R$/US$'
                def pt(v):return format(v,'.4f').rstrip('0').rstrip('.').replace('.',',')
                basis=f"Observado: {pt(obs['previous'])} → {pt(obs['current'])} {unit}, de {obs['previous_asof']} a {obs['asof']}. Hipótese: continuidade deste movimento; não é previsão."
            elif obs:
                basis='Última observação: '+str(obs.get('asof','sem data'))+'. Sem referência válida nos últimos 7 dias; atualize antes de inferir direção.'
                refs=[{'title':obs['source'],'url':obs['source_url']}]
        elif selection=='headlines':
            hints=headline_hints(report,day,factor);signs={h['direction'] for h in hints}
            if len(signs)==1:
                direction=next(iter(signs));origin='headline_hint';basis='Pista de manchete recente, sem leitura do artigo: '+hints[0]['title']+'. O impacto abaixo só vale se essa interpretação for confirmada.'
                refs=[{'title':h['publisher'],'url':h['url']} for h in hints]
            elif signs:basis='Manchetes recentes apontam sentidos diferentes; confirme os acontecimentos.'
        elif selection!='unknown':
            ref=scenario.get('asof','')
            if recent(ref,day):
                direction=selection;origin='user_hypothesis';basis='Hipótese informada por você em '+ref+' · '+scenario['source']+'. Não é fato verificado pelo aplicativo.'
            else:basis='Hipótese antiga; atualize a referência antes de usar a direção.'
        else:basis='Sem hipótese selecionada; canal excluído da conclusão.'
        impact,mechanism=channel(profile,factor,direction)
        drivers.append({'factor':factor,'label':label,'direction':direction,'impact':impact,'origin':origin,'basis':basis,'mechanism':mechanism,'sources':refs})
    signals={r['impact'] for r in drivers if r['impact'] not in ('unknown','neutral')}
    bias='unknown' if not signals else 'mixed' if 'mixed' in signals or len(signals)>1 else next(iter(signals))
    return {'direction':bias,'label':DIRECTIONS[bias],'confidence':'baixa','horizon':scenario.get('horizon','medium'),'drivers':drivers,
        'conclusion':{'favorable':'Há canais que podem favorecer o preço neste cenário. Confira expectativas já embutidas, valuation e fundamentos antes de estudar aporte.',
                      'unfavorable':'Há canais que podem pressionar o preço neste cenário. Revise a tese e a exposição antes de reforçar ou avaliar manutenção/venda parcial.',
                      'mixed':'Não há direção única: benefícios e pressões podem se compensar. A exposição específica do ativo pode resolver o conflito.',
                      'unknown':'Sem evidências suficientes para indicar alta ou baixa. Consulte fontes, confirme o cenário ou traga uma análise pesquisada do ChatGPT.'}[bias],
        'limitations':'Leitura condicional por regras públicas, com confiança qualitativa baixa. Não é modelo treinado, probabilidade, preço-alvo ou garantia de subida/queda. Manchetes são pistas; o mercado pode ter antecipado o cenário.',
        'monitor':['Mudança das expectativas e da curva de juros de mercado.','Resultados, dívida, contratos, câmbio e hedges específicos do ativo.','Confirmação, reversão ou agravamento dos acontecimentos citados.'],
        'references':[BCB,IMF]}
