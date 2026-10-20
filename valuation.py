"""Transparent scenario arithmetic, never a price forecast or automatic trade."""
import math
import sector_analysis

FIELDS = {
    'dividend_growth': ('Crescimento dos dividendos na projeção (%)', -99, 100),
    'terminal_roe': ('ROE no período estável (%)', -100, 100),
    'payout_ratio': ('Payout durante a projeção (%)', 0, 100),
    'fcff_per_share': ('FCFF anual base por ação (R$)', 0, None),
    'fcff_growth': ('Crescimento do FCFF na projeção (%)', -99, 100),
    'fcfe_terminal_value': ('Valor residual do capital próprio ao fim da projeção (R$/ação; opcional)', 0, None),
    'fcff_terminal_value': ('EV residual ao fim da projeção (R$/ação; opcional)', 0, None),
    'wacc': ('WACC nominal (% a.a.)', .1, 100),
    'net_debt_per_share': ('Dívida líquida por ação (R$; negativa se caixa líquido)', None, None),
    'other_claims_per_share': ('Minoritários e outros ajustes ao EV por ação (R$; informe 0 se não houver)', 0, None),
    'ebitda_per_share': ('EBITDA normalizado anual por ação (R$)', 0, None),
    'target_ev_ebitda': ('EV/EBITDA de empresas comparáveis (vezes)', .1, 100),
    'target_pb': ('P/VP de empresas comparáveis (vezes)', .01, 100),
    'normalized_eps': ('LPA normalizado do ciclo, sem itens extraordinários (R$)', None, None),
    'owner_earnings_per_share': ('Owner Earnings normalizado por ação (R$)', 0, None),
    'earnings_growth': ('Crescimento sustentável do lucro para PEG (% a.a.)', .1, 100),
    'target_peg': ('PEG de referência escolhido', .01, 10),
    'nav_assets_per_share': ('Ativos a valor econômico por ação (R$)', 0, None),
    'nav_liabilities_per_share': ('Passivos e tributos do NAV por ação (R$; informe 0 se não houver)', 0, None),
    'sotp_parts_per_share': ('Soma do valor das participações por ação (R$)', 0, None),
    'sotp_adjustments_per_share': ('Dívida, tributos e custos corporativos por ação (R$; informe 0 se não houver)', 0, None),
    'holding_discount': ('Desconto de holding escolhido (%)', 0, 80),
}

# Names are stable identifiers for saved scenarios and existing clients.
FCFE = 'Fluxo de caixa descontado (FCFE)'
FCFF = 'Fluxo de caixa descontado (FCFF)'
RI = 'Lucro residual (múltiplos estágios)'
PB = 'Lucro residual (estável)'
DDM = 'DDM (dois estágios)'
PE = 'Múltiplo de lucro'
EV = 'EV/EBITDA comparável'
POLICIES = {
    'bank': ([RI, PB], [DDM, PE, 'P/VP comparável']),
    'insurance': ([RI, DDM], [PB, PE, 'P/VP comparável']),
    'utility': ([FCFF, DDM], [FCFE, 'Gordon', EV]),
    'concession': ([FCFF], [EV, FCFE]),
    'commodity': ([FCFF, FCFE], ['EPV', EV, PE]),
    'metals': ([FCFF, FCFE], ['EPV', EV, PE]),
    'technology': ([FCFF, FCFE], [PE, 'Owner Earnings']),
    'holding': (['Soma das partes', 'NAV'], []),
    'loss': ([FCFF, FCFE], ['NAV']),
    'general': ([FCFF, FCFE], [EV, PE, 'Owner Earnings', DDM]),
}
METHOD_FIELDS = {
    'Bazin':('dividends_per_share','target_yield'), 'Graham':('eps','bvps'),
    'Gordon':('dividends_per_share','required_return','growth'), PE:('eps','target_pe'),
    PB:('bvps','normalized_roe','required_return','growth'),
    FCFE:('fcfe_per_share','fcfe_growth','required_return','terminal_growth'),
    DDM:('dividends_per_share','dividend_growth','required_return','terminal_growth'),
    RI:('bvps','normalized_roe','payout_ratio','terminal_roe','required_return','terminal_growth'),
    FCFF:('fcff_per_share','fcff_growth','wacc','terminal_growth','net_debt_per_share','other_claims_per_share'),
    EV:('ebitda_per_share','target_ev_ebitda','net_debt_per_share','other_claims_per_share'),
    'P/VP comparável':('bvps','target_pb'), 'EPV':('normalized_eps','required_return'),
    'Owner Earnings':('owner_earnings_per_share','required_return'), 'PEG / Lynch':('eps','earnings_growth','target_peg'),
    'NAV':('nav_assets_per_share','nav_liabilities_per_share'),
    'Soma das partes':('sotp_parts_per_share','sotp_adjustments_per_share','holding_discount'),
}

def policy(asset, inputs=None):
    profile = sector_analysis.profile(asset)
    text = sector_analysis.fold(str(asset.get('sector','')))
    name = sector_analysis.fold(str(asset.get('name','')))
    if text.strip() in ('holding','holdings','participacoes') or 'holding' in name or 'participacoes' in name: profile = 'holding'
    elif 'saneamento' in text or 'concess' in text: profile = 'concession'
    eps = inputs.get('eps') if inputs is not None else asset.get('sector_metrics', {}).get('eps', {}).get('value')
    if eps is not None and eps <= 0 and profile not in ('holding', 'bank', 'insurance'): profile = 'loss'
    if inputs and inputs.get('valuation_profile','auto')!='auto':profile=inputs['valuation_profile']
    primary, secondary = POLICIES.get(profile, POLICIES['general'])
    return dict(profile=profile, primary=primary, complementary=secondary,
        reason={'bank':'Bancos: lucro excedente e capital próprio; dívida operacional não deve ser tratada como a de uma indústria.',
                'insurance':'Seguradoras: lucro excedente e dividendos, com conferência das reservas e solvência.',
                'holding':'Holdings: avalie participações separadamente e desconte dívida, tributos e custos corporativos.',
                'concession':'Concessões: projete investimentos, tarifas e prazo contratual. Perpetuidade só cabe se houver continuidade econômica justificada.',
                'loss':'Prejuízo atual: informe fluxos explícitos de recuperação; não extrapole prejuízo pelo P/L.',
                'commodity':'Negócios cíclicos: normalize preços, margens e investimentos ao longo do ciclo.',
                'metals':'Mineração e siderurgia: normalize preços, margens e investimentos ao longo do ciclo.'}.get(profile,
                'Prioridade a caixa e reinvestimento; dividendos e múltiplos servem como conferência conforme a atividade.'))

def apply_policy(result, selection):
    result['selection'] = selection
    for row in result['methods']:
        name = row['method']
        row['role'] = ('primary' if name in selection['primary'] else 'complementary' if name in selection['complementary']
                       else 'screening' if name in ('Bazin', 'Graham', 'PEG / Lynch') else 'other')
        if selection['profile'] in ('bank', 'insurance') and name in (FCFF, EV):
            row.update(role='not_applicable', value=None, ceiling=None, premium=None, classification='unknown', price_gap=None)
    # Do not count equivalent stable RI and multistage RI as independent votes.
    eligible = [m for m in result['methods'] if m['role'] in ('primary','complementary') and m['value'] is not None]
    available = {m['method']:m for m in eligible}
    chosen = next((available[n] for n in selection['primary'] if n in available), None)
    fallback = chosen is None
    chosen = chosen or next((available[n] for n in selection['complementary'] if n in available), None)
    result['suggestion'] = dict(method=chosen['method'] if chosen else None, value=chosen['value'] if chosen else None,
        ceiling=chosen['ceiling'] if chosen else None, fallback=fallback and chosen is not None,
        note='Referência condicional do primeiro método prioritário com dados; sem média entre fórmulas. O teto aplica a margem escolhida. Métodos de triagem não geram o preço sugerido.')
    result['comparison'] = comparison(eligible)
    return result

def comparison(rows):
    unique = {}
    for m in rows:
        if m['classification'] != 'unknown': unique.setdefault(m.get('family', m['method']), m)
    rows = list(unique.values()); states = {m['classification'] for m in rows}
    return dict(count=len(rows), classification=next(iter(states)) if len(rows)>=2 and len(states)==1 else 'mixed' if len(rows)>=2 else 'insufficient',
        low=min((m['value'] for m in rows), default=None), high=max((m['value'] for m in rows), default=None),
        note='Comparação entre premissas; métodos que usam as mesmas entradas não são votos independentes. Modelos equivalentes de lucro residual contam uma vez. A faixa não é intervalo estatístico de confiança.')

def data_plan(result, origins, saved):
    labels=dict(eps='LPA observado',bvps='VPA observado',dividends_per_share='DPS observado',
        normalized_roe='ROE sustentável',fcfe_per_share='FCFE por ação',fcfe_growth='Crescimento projetado do FCFE',
        required_return='Custo do capital próprio',growth='Crescimento estável',terminal_growth='Crescimento terminal',target_pe='P/L comparável')
    labels.update({k:spec[0] for k,spec in FIELDS.items()})
    guidance={
        'eps':'Lucro atribuível à classe ÷ média ponderada de ações diluídas. Dê preferência ao LPA publicado; confira desdobramentos e período.',
        'bvps':'Patrimônio atribuível aos acionistas da classe ÷ ações em circulação da mesma data; confira direitos diferentes entre ON/PN e units.',
        'dividends_per_share':'Some proventos por ação em 12 meses, ajustados por eventos societários. Separe extraordinários, dividendos/JCP e valor bruto/líquido.',
        'required_return':'Estime com taxa livre de risco compatível com prazo/moeda + beta × prêmio de mercado, documentando risco-país sem duplicá-lo. Selic corrente não substitui Ke automaticamente.',
        'wacc':'Pondere custo do capital próprio e dívida pelo valor de mercado; ajuste imposto e benefício fiscal efetivo. Mesma moeda e inflação dos fluxos.',
        'fcfe_per_share':'DFC e notas: CFO após juros − CapEx + captação líquida de dívida, dividido pelas ações diluídas. Ajuste classificação dos juros e arrendamentos.',
        'fcff_per_share':'EBIT × (1−imposto operacional) + depreciação − CapEx − Δcapital de giro operacional, dividido pelas ações diluídas. Não é apenas caixa operacional.',
        'owner_earnings_per_share':'Lucro + despesas sem caixa − CapEx de manutenção − reinvestimento necessário no capital de giro. CapEx total não identifica manutenção.',
        'net_debt_per_share':'Dívida financeira − caixa disponível na mesma data ÷ ações diluídas. Caixa líquido pode ser negativo; confira caixa restrito e arrendamentos.',
        'other_claims_per_share':'Minoritários, preferenciais e outros direitos ainda não incluídos na dívida, na mesma base do EV. Informe zero apenas se confirmado.',
        'nav_assets_per_share':'Reavalie ativos individualmente a valor econômico com laudos, preços e data; divida pelo número de ações compatível.',
        'nav_liabilities_per_share':'Inclua passivos, contingências e tributos de realização ainda não considerados nos ativos. Divida pela mesma base de ações.',
        'sotp_parts_per_share':'Avalie cada negócio ou participação, aplique o percentual detido e converta sua soma para valor por ação da holding.',
        'sotp_adjustments_per_share':'Dívida da holding, tributos e valor presente dos custos corporativos. Não duplique ajustes já descontados nas participações.',
        'holding_discount':'Premissa editável apoiada em governança, liquidez e histórico do desconto. Não é desconto observado tomado como valor justo.',
    }
    keys=['eps','bvps','dividends_per_share']
    for method in result['methods']:
        if method['role'] in ('primary','complementary'):
            keys.extend(k for k in method['requirements'] if k not in keys)
    out=[]
    for key in keys:
        present=result['inputs'].get(key) is not None
        guide=guidance.get(key)
        if not guide:
            guide=('Empresas comparáveis do mesmo segmento, período e normas contábeis; ajuste crescimento, risco e rentabilidade. Não copie o múltiplo atual da própria ação.' if key.startswith('target_') else
                   'Compare vários anos e um ciclo completo; remova extraordinários, mantendo ajustes negativos e positivos. O histórico não garante a recorrência futura.' if key in ('normalized_eps','normalized_roe','terminal_roe','ebitda_per_share') else
                   'Use reinvestimento, crescimento da economia e retorno sobre capital como testes de consistência. Crescimento terminal precisa ser menor que a taxa de desconto; não extrapole um pico do ciclo.' if 'growth' in key else
                   'Cenário explícito a conferir. Informe fonte, período e justificativa nas notas das premissas; dado ausente não vira zero.')
        out.append(dict(field=key,label=labels.get(key,key),status='available' if present else 'missing',
            source=origins.get(key,{}).get('source','Premissa salva por você' if present else ''),
            asof=origins.get(key,{}).get('asof',saved.get('saved_at','')[:10] if present else ''),guidance=guide))
    return out

def alert(asset,threshold=30):
    """Flag disagreement with scenario assumptions, never assert intrinsic value."""
    v=asset.get('valuation',{});price=v.get('inputs',{}).get('price')
    unique={}
    for m in v.get('methods',[]):
        if price and m['value'] is not None and m['value']>0 and m.get('role','primary') in ('primary','complementary'):
            unique.setdefault(m.get('family',m['method']),m)
    rows=[{'method':m['method'],'value':m['value'],'premium':(price/m['value']-1)*100} for m in unique.values()]
    high=[m for m in rows if m['premium']>=threshold]
    above=[m for m in rows if m['premium']>0]
    status='insufficient' if not rows else 'expensive' if len(rows)>=2 and len(high)==len(rows) else 'above' if above else 'within'
    held=asset.get('position',{}).get('quantity',0)>0
    title={'insufficient':'Sem base recente para alerta de preço','expensive':'Preço muito acima dos cenários calculáveis','above':'Preço acima de pelo menos um cenário','within':'Preço dentro dos cenários calculáveis'}[status]
    action=('Revisar manutenção ou possível venda parcial' if held else 'Revisar antes de fazer novo aporte') if status=='expensive' else 'Conferir premissas e qualidade do negócio'
    return {'status':status,'title':title,'action':action,'models':rows,'threshold':threshold,'held':held,
        'estimated':bool(v.get('estimates')),'disagreement':bool(above) and any(r['premium']<0 for r in rows),
        'note':'Alerta baseado nas suas premissas: usa o valor bruto de cada fórmula, antes da margem de segurança. Para “muito acima”, exige pelo menos duas fórmulas e todas acima do corte. Não representa consenso nem ordem de venda. Revise tese, balanço, dividendos recorrentes, alternativas, IR e custos.'}

def for_asset(asset,saved,number,age):
    """Auto-fill only dated observations; explicitly label algebraic estimates."""
    inputs=dict(saved.get('inputs',{}));origins={};estimates=[]
    price=asset['metrics'].get('price') if age(asset.get('snapshots',{}).get('quote',{}).get('asof'))<=7 else None
    inputs['price']=price
    for k in ('eps','bvps','dividends_per_share'):
        manual=inputs.get(k)
        m=asset.get('sector_metrics',{}).get(k,{})
        if manual is not None and manual!='':origins[k]={'source':'Premissa salva por você','asof':saved.get('saved_at','')[:10]};continue
        inputs[k]=m.get('value') if age(m.get('asof'))<=550 else None
        if inputs[k] is not None:origins[k]={'source':m.get('source',''),'asof':m.get('asof','')}
    for field,metric in (('eps','pe'),('bvps','pvp'),('dividends_per_share','dy')):
        m=asset.get('sector_metrics',{}).get(metric,{})
        if inputs.get(field) is None and price and age(m.get('asof'))<=550 and m.get('value') is not None and m['value']>0:
            inputs[field]=price*m['value']/100 if metric=='dy' else price/m['value']
            estimates.append(field)
            origins[field]={'source':'Estimativa pela cotação e '+metric.upper()+' publicado · '+m.get('source',''), 'asof':m.get('asof','')}
    inputs.setdefault('target_yield',6);inputs.setdefault('safety_margin',20)
    result=calculate(inputs,number)
    apply_policy(result,policy(asset,result['inputs']))
    result.update(origins=origins,estimates=estimates,has_saved=bool(saved))
    result['basis_note']='Estimativas por múltiplos podem usar bases de preços diferentes: confira LPA, VPA e proventos no RI. DY é passado e não garante dividendos futuros. Campos vazios ficam sem cálculo.'
    result['data_plan'] = data_plan(result,origins,saved)
    result['field_catalog'] = {k:dict(label=v[0],min=v[1],max=v[2]) for k,v in FIELDS.items()}
    return result

REFERENCES=[
 {'title':'Bazin · Faça Fortuna com Ações, explicado no guia Suno, cap. 6','url':'https://www.sunoresearch.com.br/wp-content/uploads/2018/09/Ebook_Apreenda_como_investir_em_dividendos-1.pdf'},
 {'title':'Damodaran · Dividend Discount Models (Gordon)','url':'https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch13.pdf'},
 {'title':'Graham · número defensivo, derivação dos limites de P/L e P/VP','url':'https://www.grahamvalue.com/quick-reference'}]
REFERENCES += [
 {'title':'CFA Institute · lucro residual, patrimônio e custo do capital próprio','url':'https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation'},
 {'title':'Damodaran · fluxo de caixa livre para o acionista (FCFE)','url':'https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch14.pdf'},
 {'title':'Damodaran · lucro excedente e avaliação de instituições financeiras','url':'https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf'},
 {'title':'Damodaran · avaliação por múltiplos','url':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valuation/val.htm'}]

def calculate(d,number):
    def n(k,lo=None,hi=None):
        if isinstance(d.get(k),bool):raise ValueError('Premissa numérica inválida: '+k)
        return number(d.get(k),False,lo,hi)
    price=n('price',.00000001);dps=n('dividends_per_share',0);eps=n('eps');bvps=n('bvps')
    target=n('target_yield',.1,100);required=n('required_return',.1,100);growth=n('growth',-99,30)
    margin=n('safety_margin',0,80) or 0
    tolerance=n('fair_tolerance',0,30)
    tolerance=10 if tolerance is None else tolerance
    multiple=n('target_pe',.1,200);roe=n('normalized_roe',-100,100)
    fcfe=n('fcfe_per_share',0);fg=n('fcfe_growth',-99,100);tg=n('terminal_growth',-99,30)
    years=n('forecast_years',1,10)
    years=5 if years is None else years
    if int(years)!=years:raise ValueError('Use um número inteiro de anos de projeção.')
    years=int(years)
    extra={k:n(k,v[1],v[2]) for k,v in FIELDS.items()}
    def forecast(key):
        raw=d.get(key)
        if raw in (None,'') or raw==[]:return []
        if isinstance(raw,str):raw=[v.strip().replace(',','.') for v in raw.replace(';','\n').splitlines() if v.strip()]
        if not isinstance(raw,list) or not 1<=len(raw)<=10:raise ValueError('Informe de 1 a 10 fluxos anuais separados por ponto e vírgula ou quebra de linha.')
        out=[]
        for value in raw:
            if isinstance(value,bool):raise ValueError('Fluxo anual inválido.')
            parsed=number(value,True,-1e12,1e12)
            out.append(parsed)
        return out
    fcfe_path,fcff_path=forecast('fcfe_forecast'),forecast('fcff_forecast')
    notes=d.get('assumption_notes','')
    if not isinstance(notes,str) or len(notes)>4000:raise ValueError('Notas de premissas devem ter até 4.000 caracteres.')
    chosen_profile=d.get('valuation_profile','auto')
    if not isinstance(chosen_profile,str) or chosen_profile not in ('auto',*POLICIES):raise ValueError('Tipo de empresa para avaliação inválido.')
    methods=[]
    def result(method,value,reason,formula,needs=(),family=None):
        if value is not None and (not math.isfinite(value) or value<=0):value=None
        ceiling=value*(1-margin/100) if value is not None else None
        premium=round((price/value-1)*100,10) if price and value else None
        if premium==0:premium=0.0
        status=('below' if premium < -tolerance else 'within' if abs(premium)<=tolerance
                else 'expensive' if premium>=30 else 'above') if premium is not None else 'unknown'
        methods.append({'method':method,'value':value,'ceiling':ceiling,'reason':reason,'formula':formula,
            'missing':[k for k in needs if d.get(k) in (None,'')], 'family':family or method,
            'premium':premium,'classification':status,
            'price_gap':(ceiling-price)/price*100 if price and ceiling is not None else None})
    result('Bazin',dps/(target/100) if dps is not None and dps>0 and target else None,
           'DPS anual e yield exigido positivos são necessários. Os 6% históricos são uma premissa editável; não equivalem ao retorno exigido no Brasil atual.', 'DPS anual ÷ (yield exigido / 100)')
    result('Graham',math.sqrt(22.5*eps*bvps) if eps is not None and bvps is not None and eps>0 and bvps>0 else None,
           'Usar LPA e VPA positivos e compatíveis. O número defensivo é incompleto sem qualidade, estabilidade e histórico; pouco útil para negócios ricos em intangíveis.', '√(22,5 × LPA × VPA)')
    eligible=dps is not None and dps>0 and required is not None and growth is not None and required>growth
    result('Gordon',dps*(1+growth/100)/((required-growth)/100) if eligible else None,
           'DPS representa a base anual D0. Exige retorno maior que crescimento e crescimento sustentável de longo prazo; próximo da taxa exigida torna a fórmula muito sensível.', 'D0 × (1 + g) ÷ (retorno exigido − g), taxas decimais',family='dividends')
    pe_eps=extra['normalized_eps'] if extra['normalized_eps'] is not None else eps
    result('Múltiplo de lucro',pe_eps*multiple if pe_eps is not None and pe_eps>0 and multiple else None,
           'LPA positivo e normalizado × P/L de referência escolhido por você. Compare empresas do mesmo segmento e período; não usa automaticamente o P/L atual da própria ação como referência de valor justo.',
           'LPA normalizado × P/L de referência' if extra['normalized_eps'] is not None else 'LPA observado × P/L de referência (confira normalização)')
    eligible=bvps is not None and bvps>0 and roe is not None and growth is not None and required is not None and required>growth and roe>growth
    result('Lucro residual (estável)',bvps*(roe-growth)/(required-growth) if eligible else None,
           'Versão estável do lucro excedente: assume ROE constante, patrimônio contábil consistente e distribuição do lucro após reinvestimento. Exige ROE maior que crescimento e retorno exigido maior que crescimento. Útil para estudar bancos; mudanças no capital regulatório e na qualidade dos ativos podem invalidar as premissas.',
           'VPA × (ROE normalizado − g) ÷ (retorno exigido − g)',family='residual_income')
    eligible=fcfe is not None and fcfe>0 and fg is not None and tg is not None and required is not None and required>tg
    value=None
    explicit_terminal=extra['fcfe_terminal_value']
    if required is not None and ((explicit_terminal is not None and (fcfe_path or (fcfe is not None and fg is not None))) or
            (not fcfe_path and eligible) or (fcfe_path and fcfe_path[-1]>0 and tg is not None and required>tg)):
        discount=1+required/100
        flows=fcfe_path or [fcfe*(1+fg/100)**t for t in range(1,years+1)]
        terminal=explicit_terminal if explicit_terminal is not None else flows[-1]*(1+tg/100)/((required-tg)/100)
        value=sum(v/discount**t for t,v in enumerate(flows,1))+terminal/discount**len(flows)
    result('Fluxo de caixa descontado (FCFE)',value,
           'Informe fluxo de caixa livre para o acionista por ação, após dívida e reinvestimento, em moeda nominal compatível com o custo do capital próprio. Não confunda com caixa operacional nem FCFF da empresa; não desconta dívida novamente. Crescimento terminal deve ser sustentável e menor que o retorno exigido. Entradas são suas projeções, não previsões aprendidas.',
           'Σ FCFEₜ ÷ (1 + Ke)ᵗ + valor residual ÷ (1 + Ke)ⁿ' if explicit_terminal is not None else
           'Σ FCFEₜ ÷ (1 + k)ᵗ + [FCFEₙ × (1 + g terminal) ÷ (k − g terminal)] ÷ (1 + k)ⁿ')
    def discounted(base, growth_rate, rate, terminal, path=None, residual=None):
        if rate is None or (residual is None and (terminal is None or rate<=terminal)):return None
        if not path and (base is None or base<=0 or growth_rate is None):return None
        flows=path or [base*(1+growth_rate/100)**t for t in range(1,years+1)]
        if residual is None and flows[-1]<=0:return None
        terminal_value=residual if residual is not None else flows[-1]*(1+terminal/100)/((rate-terminal)/100)
        return sum(v/(1+rate/100)**t for t,v in enumerate(flows,1))+terminal_value/(1+rate/100)**len(flows)
    result(DDM,discounted(dps,extra['dividend_growth'],required,tg),
        'Dividendos D0, crescimento explícito e terminal; teste payout e capacidade de reinvestimento. Não presume que um dividendo extraordinário se repete.',
        'Σ Dₜ/(1+Ke)ᵗ + Dₙ₊₁/(Ke−g)/(1+Ke)ⁿ',('dividends_per_share','dividend_growth','required_return','terminal_growth'),family='dividends')
    value=None
    tr=extra['terminal_roe'];payout=extra['payout_ratio']
    if bvps is not None and bvps>0 and roe is not None and payout is not None and required is not None and tg is not None and required>tg and tr is not None and tr>tg and tr>0:
        book=bvps;value=book
        for t in range(1,years+1):
            profit=book*roe/100
            value+=(profit-book*required/100)/(1+required/100)**t
            book+=profit*(1-payout/100)
            if book<=0:value=None;break
        if value is not None:value+=book*(tr-required)/(required-tg)/(1+required/100)**years
    result(RI,value,'VPA inicial + lucros excedentes. Patrimônio evolui por lucro retido (clean surplus); ROE estável e crescimento terminal exigem payout compatível. Confira OCI, emissões, recompras e capital regulatório.',
        'VPA₀ + Σ[(ROEₜ−Ke)×VPAₜ₋₁]/(1+Ke)ᵗ + VPAₙ×(ROE∞−Ke)/(Ke−g)/(1+Ke)ⁿ',
        ('bvps','normalized_roe','payout_ratio','terminal_roe','required_return','terminal_growth'),'residual_income')
    debt,claims=extra['net_debt_per_share'],extra['other_claims_per_share']
    ev=discounted(extra['fcff_per_share'],extra['fcff_growth'],extra['wacc'],tg,fcff_path,extra['fcff_terminal_value'])
    bridge=lambda value: value-debt-claims if value is not None and debt is not None and claims is not None else None
    result(FCFF,bridge(ev),'FCFF descontado ao WACC gera EV; subtrai dívida líquida, minoritários e outros direitos uma única vez. Informe zero explicitamente nos ajustes inexistentes. Projeções explícitas aceitam prejuízos iniciais, com último fluxo positivo. Perpetuidade exige continuidade após contratos/concessões.',
        '[VP(FCFF) + VP(terminal)] − dívida líquida/ação − outros direitos/ação',('wacc','terminal_growth','net_debt_per_share','other_claims_per_share'))
    ebitda,mult=extra['ebitda_per_share'],extra['target_ev_ebitda']
    result(EV,bridge(ebitda*mult if ebitda is not None and ebitda>0 and mult else None),
        'EBITDA normalizado e múltiplo de pares; confira arrendamentos/IFRS 16 e dívida da mesma data. Não substitui caixa após CapEx.',
        'EBITDA/ação × EV/EBITDA referência − dívida líquida/ação − outros direitos/ação',('ebitda_per_share','target_ev_ebitda','net_debt_per_share','other_claims_per_share'))
    result('P/VP comparável',bvps*extra['target_pb'] if bvps is not None and bvps>0 and extra['target_pb'] else None,
        'Compare ROE, risco, qualidade dos ativos e capital. P/VP justificado corresponde ao lucro residual estável acima.', 'VPA × P/VP de referência',('bvps','target_pb'))
    neps=extra['normalized_eps'];owner=extra['owner_earnings_per_share']
    result('EPV',neps/(required/100) if neps is not None and neps>0 and required else None,
        'Versão de capital próprio sem crescimento: lucro distribuível normalizado após despesas e reinvestimento de manutenção. Lucro contábil sem ajustes não comprova caixa distribuível.',
        'LPA distribuível normalizado ÷ Ke',('normalized_eps','required_return'))
    result('Owner Earnings',owner/(required/100) if owner is not None and owner>0 and required else None,
        'Capitaliza a geração distribuível sem crescimento. Estime CapEx de manutenção e capital de giro necessário; não use automaticamente todo o caixa de investimento como CapEx.',
        'Owner Earnings/ação ÷ Ke, sem crescimento',('owner_earnings_per_share','required_return'))
    eg,peg=extra['earnings_growth'],extra['target_peg']
    result('PEG / Lynch',eps*eg*peg if eps is not None and eps>0 and eg and peg else None,
        'Triagem com crescimento em pontos percentuais (10 para 10%). Não calcula valor intrínseco e não serve para lucro negativo ou crescimento temporário do ciclo.',
        'LPA × crescimento do lucro (%) × PEG referência',('eps','earnings_growth','target_peg'))
    def assets_value(a,b):return extra[a]-extra[b] if extra[a] is not None and extra[b] is not None else None
    result('NAV',assets_value('nav_assets_per_share','nav_liabilities_per_share'),
        'Ativos a valor econômico, não simplesmente contábil; retire passivos, impostos de realização e custos sem duplicá-los.',
        'Ativos econômicos/ação − passivos e tributos/ação',('nav_assets_per_share','nav_liabilities_per_share'))
    parts=assets_value('sotp_parts_per_share','sotp_adjustments_per_share');hd=extra['holding_discount']
    result('Soma das partes',parts*(1-hd/100) if parts is not None and hd is not None else None,
        'Cada participação deve ser valor de capital próprio atribuível à holding. Retire ajustes corporativos antes do desconto; não duplique dívida das subsidiárias já considerada nos valores.',
        '(Σ valor atribuível das participações/ação − ajustes corporativos/ação) × (1−desconto)',('sotp_parts_per_share','sotp_adjustments_per_share','holding_discount'))
    reverse=dict(growth=None,status='missing',note='Crescimento anual do FCFE que iguala o preço, mantendo Ke, g terminal e prazo fixos. Não é previsão; não entra no preço sugerido.')
    if price and fcfe and required is not None and tg is not None and required>tg:
        lo,hi=-99.,100.
        if discounted(fcfe,lo,required,tg)<=price<=discounted(fcfe,hi,required,tg):
            for _ in range(80):
                mid=(lo+hi)/2
                if discounted(fcfe,mid,required,tg)<price:lo=mid
                else:hi=mid
            reverse.update(growth=(lo+hi)/2,status='solved')
        else:reverse['status']='outside_range'
    for row in methods:
        needs=list(METHOD_FIELDS[row['method']])
        if row['method']==PE and extra['normalized_eps'] is not None:needs=['normalized_eps','target_pe']
        if row['method']==FCFE and fcfe_path:needs=[k for k in needs if k not in ('fcfe_per_share','fcfe_growth')]
        if row['method']==FCFF and fcff_path:needs=[k for k in needs if k not in ('fcff_per_share','fcff_growth')]
        if row['method']==FCFE and extra['fcfe_terminal_value'] is not None:needs=[k for k in needs if k!='terminal_growth']
        if row['method']==FCFF and extra['fcff_terminal_value'] is not None:needs=[k for k in needs if k!='terminal_growth']
        row['requirements']=needs
        row['missing']=[k for k in needs if d.get(k) in (None,'')]
    return {'methods':methods,'comparison':comparison(methods),'reverse_dcf':reverse,
            'field_catalog':{k:dict(label=v[0],min=v[1],max=v[2]) for k,v in FIELDS.items()},
            'inputs':dict(price=price,dividends_per_share=dps,eps=eps,bvps=bvps,target_yield=target,required_return=required,growth=growth,safety_margin=margin,
            fair_tolerance=tolerance,target_pe=multiple,normalized_roe=roe,fcfe_per_share=fcfe,fcfe_growth=fg,terminal_growth=tg,forecast_years=years,
            **extra,fcfe_forecast=fcfe_path,fcff_forecast=fcff_path,assumption_notes=notes,valuation_profile=chosen_profile),
            'dividend_yield':dps/price*100 if price and dps is not None else None,
            'payout':dps/eps*100 if dps is not None and eps is not None and eps>0 else None,
            'stress_bazin':dps*.75/(target/100) if dps is not None and dps>0 and target else None,
            'references':REFERENCES,'note':'Cenários por premissas, não preço esperado ou consenso de analistas. DPS deve ser por ação, não o total de proventos recebidos por você. Confirme base bruto/líquido e JCP. Valores nominais em reais; não há previsão de dividendos, IR ou negociação automática.'}
