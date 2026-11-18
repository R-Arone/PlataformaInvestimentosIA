"""Explainable sector screening. Limits are editable study assumptions, not fair values."""
import math
import statistics
import unicodedata

REFERENCES = [
 {'id':'fitch','title':'Fitch · Corporate Rating Criteria, 9 janeiro/2026',
  'url':'https://assets.fitchratings.com/downloadFile?reportType=report&sfReport=false&slug=corporate-finance/corporate-rating-criteria-09-01-2026',
  'note':'Metodologia profissional: capacidade de pagar dívida, geração de caixa, liquidez, modelo de negócio e ajustes por setor/arrendamentos. Os cortes do aplicativo não são ratings nem limites atribuídos à Fitch.'},
 {'id':'susep','title':'Susep · Capital Mínimo Requerido e TAP',
  'url':'https://www.gov.br/susep/pt-br/assuntos/informacoes-ao-mercado/solvencia-supervisao-prudencial/monitoramento-prudencial/capital-minimo-requerido-e-tap',
  'note':'Seguradoras: patrimônio líquido ajustado, capital mínimo requerido e adequação de passivos.'},
 {'id':'banks','title':'Damodaran · Valuing Financial Service Firms (2009)',
  'url':'https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf',
  'note':'Bancos: dívida faz parte da operação. Avaliar patrimônio, rentabilidade, provisões e capital regulatório.'},
 {'id':'bcb','title':'Banco Central · Indicadores de estabilidade financeira',
  'url':'https://www.bcb.gov.br/estabilidadefinanceira/indexestabilidadefinanceira',
  'note':'Capital deve ser comparado à exigência aplicável à instituição. Não há um mínimo único usado pelo aplicativo.'},
 {'id':'corporate','title':'Damodaran · Applied Corporate Finance, 4ª edição',
  'url':'https://www.stern.nyu.edu/~adamodar/pdfiles/acf4E/acf4Ebook.pdf',
  'note':'Retorno sobre capital, custo de capital, cobertura de juros e capacidade de endividamento dependem do negócio.'},
 {'id':'leases','title':'IFRS Foundation · IFRS 16 Effects Analysis',
  'url':'https://www.ifrs.org/-/media/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf',
  'note':'Arrendamentos alteram dívida e EBITDA. No varejo, conferir a mesma base contábil ao comparar empresas.'},
 {'id':'industry','title':'Damodaran · Debt Fundamentals by Sector, janeiro/2026 (EUA)',
  'url':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/dbtfund.html',
  'note':'Referência externa para entender diferenças entre indústrias. São dados dos EUA, com dívida bruta/EBITDA; não são medianas da B3 nem dívida líquida/EBITDA.'}
]

# operator and defaults are authored screening assumptions; references support metric selection only.
PROFILES = {
 'bank': {'label':'Bancos', 'limits':{'npl90':3, 'coverage':100}, 'refs':['banks','bcb'],
  'risks':['Qualidade do crédito e evolução da inadimplência >90 dias.', 'Provisões, concentração de carteira, exposição soberana e custo de captação.', 'Capital regulatório e liquidez; confirmar a exigência específica no relatório prudencial.']},
 'insurance': {'label':'Seguradoras e resseguradoras', 'limits':{}, 'refs':['banks','susep'],
  'risks':['Solvência deve usar o capital requerido do regulador aplicável.', 'Sinistralidade, reservas técnicas, resseguro e qualidade dos investimentos.', 'Uma bolsa, uma holding financeira e uma seguradora exigem ajustes próprios; confirme o perfil.']},
 'financial_services': {'label':'Outros serviços financeiros e holdings', 'limits':{}, 'refs':['banks','corporate'],
  'risks':['Identificar o modelo: bolsa, gestora, holding ou empresa de crédito têm riscos diferentes.', 'Receitas recorrentes, concentração, governança, patrimônio das participações e distribuição de caixa.', 'Não aplicar automaticamente Basileia de bancos ou solvência de seguradoras a esta empresa.']},
 'utility': {'label':'Energia e saneamento', 'limits':{'net_debt_ebitda':3.5,'debt_equity':1.5,'interest_coverage':2.5}, 'refs':['corporate','industry'],
  'risks':['Separar geração, transmissão e distribuição; contratos e previsibilidade de receita diferem.', 'Revisões tarifárias, concessões, vencimentos da dívida, investimento e geração de caixa.', 'Risco hidrológico, contrapartes e exposição a juros; EBITDA sozinho não mede caixa disponível.']},
 'retail': {'label':'Varejo', 'limits':{'net_debt_ebitda':2,'debt_equity':1,'interest_coverage':3,'current_ratio':1.2}, 'refs':['corporate','leases','industry'],
  'risks':['Dívida e EBITDA devem tratar arrendamentos na mesma base; conferir IFRS 16.', 'Estoque, capital de giro, sazonalidade, margem e vendas mesmas lojas.', 'Crédito ao consumidor, antecipação de recebíveis, juros e competição.']},
 'commodity': {'label':'Petróleo, mineração e commodities', 'limits':{'net_debt_ebitda':2,'debt_equity':1,'interest_coverage':3}, 'refs':['corporate','industry'],
  'risks':['Lucro e EBITDA no pico do ciclo podem produzir múltiplos aparentemente baratos.', 'Preço de commodity, câmbio, custo de produção, reservas e investimento de manutenção.', 'Testar dívida e caixa também com preços menores; riscos ambientais e interferência política.']},
 'general': {'label':'Empresas não financeiras', 'limits':{'net_debt_ebitda':3,'debt_equity':1.5,'interest_coverage':3,'current_ratio':1}, 'refs':['corporate','industry'],
  'risks':['Retorno sobre capital versus custo de capital, lucro recorrente e conversão em caixa.', 'Vencimentos, covenants, governança e concentração de clientes.', 'P/VP depende de rentabilidade e do peso de ativos intangíveis; desconto não comprova valor justo.']},
 'fii': {'label':'Fundos imobiliários', 'limits':{'vacancy':10,'top_tenant':25,'fund_leverage':20,'top_property':25,'rental_delinquency':3,'short_contracts':25,'credit_delinquency':3,'top_credit':25,'ltv':70,'top_fund':25}, 'refs':['corporate'],
  'risks':['Separar tijolo e papel: vacância é pertinente a imóveis, não a fundos de recebíveis.', 'Contratos, concentração de locatários/devedores, indexadores, crédito e vencimentos.', 'P/VP depende da qualidade e data da avaliação patrimonial; rendimento pode incluir ganhos não recorrentes.']},
 'etf': {'label':'ETFs', 'limits':{'expense_ratio':0.5,'tracking_error':2}, 'refs':['corporate'],
  'risks':['Índice seguido, composição, concentração, moeda e liquidez.', 'Taxa total e diferença de desempenho em relação ao índice, na mesma janela.', 'P/VP e dívida/EBITDA da cota não são filtros adequados para ETFs.']},
 'crypto': {'label':'Bitcoin', 'limits':{}, 'refs':[],
  'risks':['Volatilidade, custódia, liquidez e concentração da carteira.', 'Medo/ganância descreve sentimento; Bitcoin não tem patrimônio contábil ou EBITDA.']}
}
METRICS = {
 'top_property':('Maior imóvel na receita do FII','%','risk'),
 'rental_delinquency':('Inadimplência dos aluguéis divulgada','%','risk'),
 'short_contracts':('Receita com contratos vencendo em até 12 meses','%','risk'),
 'ipca_share':('Receita de contratos indexada ao IPCA','%','risk'),
 'igpm_share':('Receita de contratos indexada ao IGP-M','%','risk'),
 'credit_delinquency':('Recebíveis em atraso na carteira de CRIs','%','risk'),
 'top_credit':('Maior devedor na carteira de CRIs','%','risk'),
 'ltv':('LTV dos recebíveis na base divulgada','%','risk'),
 'top_fund':('Maior fundo na carteira de FIIs investidos','%','risk'),
 'cash_distribution_cover':('Resultado financeiro acumulado/rendimento declarado','×','risk'),
 'gross_margin':('Margem bruta','%','financial'), 'inventory_days':('Prazo médio de estoque','dias','financial'),
 'cash_conversion':('Caixa operacional/lucro líquido','×','financial'),
 'loss_ratio':('Sinistralidade','%','risk'), 'combined_ratio':('Índice combinado','%','risk'),
 'recurring_revenue':('Receita recorrente/receita total','%','risk'), 'contracted_revenue':('Receita contratada/receita total','%','risk'),
 'same_store_sales':('Crescimento de vendas mesmas lojas','%','risk'), 'production_growth':('Crescimento do volume produzido','%','risk'),
 'sales_velocity':('Velocidade de vendas (VSO)','%','risk'), 'utilization':('Utilização / ocupação da capacidade','%','risk'),
 'churn':('Cancelamento de clientes na janela','%','risk'), 'retention':('Retenção de receita na definição informada','%','risk'),
 'receivable_days':('Prazo médio dos recebíveis','dias','risk'), 'student_dropout':('Evasão de alunos','%','risk'),
 'pvp':('P/VP','×','statistics'), 'pe':('P/L','×','statistics'),
 'dy':('Dividend yield','%','statistics'),
 'dividends_per_share':('Proventos por ação (12 meses, base informada)','R$','statistics'),
 'eps':('Lucro por ação (12 meses)','R$','financial'), 'bvps':('Valor patrimonial por ação','R$','financial'),
 'payout':('Payout (proventos/lucro, mesma janela)','%','financial'),
 'roe':('ROE','%','financial'), 'net_debt_ebitda':('Dívida líquida/EBITDA','×','financial'),
 'debt_equity':('Dívida bruta/patrimônio líquido','×','financial'),
 'net_debt_equity':('Dívida líquida/patrimônio líquido','×','financial'),
 'interest_coverage':('EBIT/despesa de juros','×','financial'),
 'current_ratio':('Liquidez corrente','×','financial'), 'operating_margin':('Margem operacional','%','financial'),
 'operating_cashflow':('Fluxo de caixa operacional (12 meses)','R$','financial'),
 'free_cashflow':('Fluxo de caixa livre (12 meses)','R$','financial'),
 'roic':('ROIC','%','risk'), 'wacc':('WACC estimado','%','risk'),
 'basel':('Índice de Basileia divulgado','%','risk'), 'capital_required':('Basileia exigida para este banco','%','risk'),
 'npl90':('Inadimplência >90 dias','%','risk'), 'coverage':('Provisões/crédito inadimplente >90d','%','risk'),
 'solvency':('Capital de solvência disponível','R$','risk'), 'solvency_required':('Capital de solvência requerido','R$','risk'),
 'lease_consistent':('Dívida e EBITDA na mesma base de arrendamentos (1=sim, 0=não)','0/1','risk'),
 'vacancy':('Vacância física (FIIs de tijolo)','%','risk'), 'financial_vacancy':('Vacância financeira (FIIs de tijolo)','%','risk'), 'top_tenant':('Maior locatário/devedor na receita ou carteira','%','risk'),
 'fund_leverage':('Obrigações financeiras/PL do FII','%','risk'), 'distribution_cover':('Resultado recorrente/distribuição','×','risk'),
 'expense_ratio':('Taxa total anual do ETF','%','risk'), 'tracking_error':('Tracking error anualizado do ETF','%','risk')
}
OPERATORS = {'net_debt_ebitda':'le','debt_equity':'le','interest_coverage':'ge','current_ratio':'ge',
             'npl90':'le','coverage':'ge','vacancy':'le','top_tenant':'le','fund_leverage':'le',
             'expense_ratio':'le','tracking_error':'le'}
OPERATORS.update({k:'le' for k in ('top_property','rental_delinquency','short_contracts','credit_delinquency','top_credit','ltv','top_fund')})

# Sector-specific starting points for research, not claimed Brazilian industry norms.
for ident,label,debt,coverage,risks in [
 ('construction','Construção e incorporação',2,3,['Caixa, recebíveis, distratos e vendas versus entrega de projetos.','Dívida líquida/PL e geração de caixa ajudam quando EBITDA é pouco representativo.']),
 ('transport','Transportes e logística',3,2.5,['Separar concessões, locação, rodovias, ferrovias e aviação.','Arrendamentos, utilização, tarifas e investimento de manutenção mudam a leitura da dívida.']),
 ('telecom','Telecomunicações',2.5,3,['Investimento recorrente, qualidade da rede, churn e competição.','Dívida, arrendamentos, espectro e caixa após investimento.']),
 ('technology','Tecnologia e software',2,3,['Receita recorrente, retenção, margem e conversão em caixa.','P/VP é pouco informativo para empresas com intangíveis; avaliar crescimento sem ignorar preço.']),
 ('health','Saúde',2.5,3,['Separar hospitais, laboratórios, farmacêuticas e operadoras.','Sinistralidade, glosas, capital de giro e integração de aquisições.']),
 ('education','Educação',2,3,['Captação e retenção de alunos, evasão, mensalidades e recebíveis.','Regulação, inadimplência e diferença entre lucro e caixa.']),
 ('food_agro','Alimentos e agronegócio',2.5,3,['Separar produtores, processadores e distribuidores; safra e preços alteram margens.','Câmbio, exportações, clima, estoques e capital de giro.']),
 ('industrial','Bens industriais e indústria',2.5,3,['Carteira de pedidos, utilização de capacidade e sensibilidade ao ciclo.','Capital de giro, custos, investimentos e retorno sobre o capital.'])]:
    PROFILES[ident]={'label':label,'limits':{'net_debt_ebitda':debt,'debt_equity':1,'interest_coverage':coverage,'current_ratio':1},
                     'refs':['corporate','industry'],'risks':risks+['Limites numéricos são premissas ajustáveis; conferir covenants e o segmento específico no Brasil.']}
PROFILES['metals']={'label':'Metais, mineração e siderurgia','limits':dict(PROFILES['commodity']['limits']),
 'refs':['corporate','industry'],
 'risks':['Separar ouro/prata, cobre, minério de ferro e aço; não há uma direção única para todos os metais.',
          'Demanda global/China, câmbio, custo de produção, reservas e investimento de manutenção.',
          'Ouro pode responder a juros reais e aversão a risco; cobre/minério também dependem do ciclo industrial.',
          'Testar caixa e dívida fora do pico de preços; conferir contratos, hedges e riscos ambientais.']}
PROFILES['foreign']={'label':'BDRs e ações estrangeiras · suporte básico','limits':{},'refs':[],
 'risks':['Risco de câmbio, custodiante, país e tributação.','Stocks confirmados nos EUA têm preços/históricos em USD e comparação própria. Operações permanecem em BRL; conferir balanços, valuation, custos e câmbio antes de comprar. BDRs e outros mercados mantêm suporte básico.']}
PROFILES['fixed_income']={'label':'Renda fixa e títulos','limits':{},'refs':['corporate'],'risks':['Duration e marcação a mercado; queda da Selic não garante valorização de toda carteira.','Separar pós-fixados, inflação e prefixados; revisar crédito, vencimento e custos.']}
PROFILES['crypto_market']={'label':'Mercado de criptoativos','limits':{},'refs':[],'risks':['Composição, volatilidade, custódia e liquidez.','Índice cripto diversificado não equivale a Bitcoin nem a ações de tecnologia.']}
COMPANY_PROFILES=tuple(k for k in PROFILES if k not in ('fii','etf','crypto','foreign','fixed_income','crypto_market'))
NONFINANCIAL_PROFILES=tuple(k for k in COMPANY_PROFILES if k not in ('bank','insurance','financial_services'))

def fold(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))

def profile(a):
    explicit = a.get('research_profile','auto')
    if explicit in COMPANY_PROFILES and a.get('asset_type','stock') in ('stock','foreign','global_stock','bdr'):
        return explicit
    typ = a.get('asset_type','stock')
    if typ in ('fii','etf','crypto'): return typ
    if typ=='global_etf': return 'etf'
    if typ=='bdr' and not __import__('aporte_brasil.company.stock_fundamentals',fromlist=['stock_fundamentals']).bdr_listing(a): return 'foreign'
    sector = fold(a.get('sector',''))
    name = fold(a.get('name',''))
    if 'banco' in sector or 'banc' in name: return 'bank'
    if any(x in sector for x in ('segur','ressegur')): return 'insurance'
    if a.get('financial') or any(x in sector for x in ('financeir','credito')): return 'financial_services'
    if any(x in sector for x in ('energia','saneamento','eletric')): return 'utility'
    if any(x in sector for x in ('varej','comercio','vestuario','calcado')): return 'retail'
    if any(x in sector for x in ('miner','sider','metal','aco')): return 'metals'
    if any(x in sector for x in ('petroleo','celulose','alcool','acucar')): return 'commodity'
    if any(x in sector for x in ('software','programas e servicos','servicos de ti','processamento de dados')):return 'technology'
    for ident,words in [('construction',('construcao','incorpor','imoveis')),('transport',('transporte','logistica','aluguel de carros','ferrovia','rodovia')),('telecom',('telecom','comunicac')),('technology',('tecnolog','software')),('health',('saude','hospital','farmac','diagnostic')),('education',('educacao','educacion','ensino')),('food_agro',('agro','alimento','carne','laticinio')),('industrial',('industr','maquina','equipament','material','embala'))]:
        if any(word in sector for word in words): return ident
    return 'general'

def metric(a, key, age):
    candidates=[]
    if a.get('asset_type')=='fii':
        from aporte_brasil.company import fii_research
        derived=a.get('_fii_metrics')
        if derived is None:
            derived=fii_research.derived_metrics(a);a['_fii_metrics']=derived
        item=derived.get(key)
        if item:
            s=a['snapshots']['fii_reports']
            candidates.append(({**s,'asof':item['asof'],'url':item['source_url'],
                'data':{key:item['value']},'source':s['source']+' · '+item['definition']},item['value']))
    from aporte_brasil.company import company_insights
    statement=a.get('snapshots',{}).get('issuer_statements')
    derived=a.get('_statement_metrics')
    if derived is None:
        derived=company_insights.derived_metrics(statement)
        a['_statement_metrics']=derived
    item=derived.get(key)
    if item and statement:
        candidates.append(({**statement,'asof':item['asof'],'data':{key:item['value'],'currency':item['currency']},
            'source':statement['source']+' · '+item['definition']},item['value']))
    f=a.get('stock_research',{}).get('financials')
    m=a.get('stock_research',{}).get('metrics',{}).get(key)
    if f and m:
        snapshot={**f,'kind':'stock_financials','asof':m['asof'],
            'data':{key:m['value'],'currency':m['currency']},'definition':m['definition'],
            'source':f['source']+' · '+m['definition']}
        if key in ('pe','pvp'):
            quote=__import__('aporte_brasil.company.stock_fundamentals',fromlist=['stock_fundamentals']).native_quote(a) or {}
            snapshot['retrieved_at']=quote.get('retrieved_at',snapshot['retrieved_at'])
        candidates.append((snapshot,m['value']))
    for kind in ('metric:'+key, 'risk', 'public', METRICS[key][2], *(['statistics'] if key in ('eps','bvps') else [])):
        s=a['snapshots'].get(kind,{})
        v=s.get('data',{}).get(key)
        if isinstance(v,(int,float)) and math.isfinite(v): candidates.append((s,v))
    if not candidates: return None, {}, 'Não informado ou indisponível na fonte.'
    s,v=max(candidates,key=lambda p:(p[0]['asof'],p[0].get('retrieved_at','')))
    if key in ('pvp','pe') and age(s['asof'] if s.get('kind')=='risk' or str(s.get('kind','')).startswith('metric:') else s.get('retrieved_at',''))>7:
        return None,s,'Múltiplo com preço de referência ou consulta antiga; revisar antes de comparar.'
    if age(s['asof'])>180: return None,s,'Referência com mais de 180 dias; atualizar o balanço.'
    return v,s,''

def analyze(assets,cfg,macros,age):
    def median(a,key):
        seen={}; records=[]
        for b in assets:
            if b['id']==a['id'] or b['sector']!=a['sector'] or profile(b)!=profile(a) or b['asset_type']!=a['asset_type']: continue
            if a['asset_type']=='fii':
                from aporte_brasil.company import fii_research
                if fii_research.subtype(a)!=fii_research.subtype(b):continue
            if a['asset_type']=='global_stock' and b.get('international',{}).get('listing',{}).get('market')!=a.get('international',{}).get('listing',{}).get('market'): continue
            issuer=b['ticker'][:4] if b['asset_type']=='stock' else b['ticker']
            own=a['ticker'][:4] if a['asset_type']=='stock' else a['ticker']
            if issuer==own or issuer in seen: continue
            v,s,reason=metric(b,key,age)
            if v is not None and (key not in ('pvp','pe') or v>0):
                seen[issuer]=1; records.append({'ticker':b['ticker'],'value':v,'asof':s['asof'],'source':s['source']})
        return statistics.median(r['value'] for r in records) if len(records)>=2 else None,records
    for a in assets:
        ident=profile(a); p=PROFILES[ident]; limits={**p['limits'],**cfg.get('sector_rules',{}).get(ident,{})}
        checks=[]
        def check(key,op,limit,label=None,explanation='',other=None):
            v,s,reason=metric(a,key,age)
            refs=[{k:s.get(k,'') for k in ('asof','source','retrieved_at')}] if s else []
            if other:
                limit,s2,r2=metric(a,other,age)
                if s2: refs.append({k:s2.get(k,'') for k in ('asof','source','retrieved_at')})
                if limit is None: reason=r2
                if s and s2 and s['asof']!=s2['asof']: reason='As duas métricas precisam da mesma data de referência.'; limit=None
                if key in ('solvency','roic') and s and s2 and s.get('data',{}).get('currency','BRL')!=s2.get('data',{}).get('currency','BRL'):
                    reason='As duas métricas precisam da mesma moeda ou base de cálculo.'; limit=None
                if limit is not None and limit<=0: reason='O parâmetro de comparação precisa ser positivo.'; limit=None
            med, peers=median(a,key) if key in ('pvp','pe','roe','net_debt_ebitda','debt_equity','operating_margin') else (None,[])
            if op=='peer': limit=med
            if key in ('pvp','pe') and v is not None and v<=0: reason='Múltiplo não positivo: não representa um desconto comparável.'; v=None
            if key in ('debt_equity','current_ratio') and v is not None and v<0: reason='Denominador patrimonial ou circulante inválido; revisar balanço.'; v=None
            if key in ('coverage','npl90','vacancy','top_tenant','fund_leverage','expense_ratio','tracking_error','top_property','rental_delinquency','short_contracts','credit_delinquency','top_credit','ltv','top_fund') and v is not None and v<0:
                reason='Indicador negativo incompatível com esta definição; revisar a fonte.'; v=None
            if key in ('npl90','vacancy','top_tenant','top_property','rental_delinquency','short_contracts','credit_delinquency','top_credit','top_fund') and v is not None and v>100:
                reason='Percentual acima de 100%; conferir unidade e definição.'; v=None
            if key=='lease_consistent' and v not in (None,0,1):
                reason='Use 1 para confirmado ou 0 para não confirmado.'; v=None
            if key=='vacancy' and ident=='fii' and any(word in fold(a.get('sector','')) for word in ('papel','recebiveis','cri')):
                reason='Vacância de imóveis não se aplica a este fundo de recebíveis; avaliar crédito e concentração.'; v=None
            if op=='peer' and limit is None: reason='Inclua ao menos duas outras empresas com dados recentes do mesmo setor e perfil.'
            if key=='net_debt_ebitda' and ident=='retail':
                basis,_,_=metric(a,'lease_consistent',age)
                if basis!=1: v=None; reason='Confirme que dívida e EBITDA usam a mesma base de arrendamentos (IFRS 16).'
            status='unknown' if v is None or limit is None else 'pass' if (v<=limit if op in ('le','peer') else v>=limit if op=='ge' else v>limit) else 'fail'
            checks.append({'metric':key,'label':label or METRICS[key][0], 'unit':(s.get('data',{}).get('currency','BRL') if s else a.get('snapshots',{}).get('issuer_financials',{}).get('data',{}).get('currency',a.get('international',{}).get('listing',{}).get('currency','USD'))) if METRICS[key][1]=='R$' and a['asset_type'] in ('foreign','global_stock','bdr') else METRICS[key][1],
                'value':v,'limit':limit,'operator':op,'status':status,'reason':reason if status=='unknown' else explanation,
                'references':refs,'median':med,'peers':peers,'note':explanation,
                'group':'valuation' if op=='peer' else 'health'})
        if ident in (*COMPANY_PROFILES,'fii'):
            check('pvp','peer',None,'P/VP ≤ mediana dos seus pares','Comparação de preço relativo; avaliar qualidade do patrimônio e rentabilidade.')
        if ident in COMPANY_PROFILES:
            check('pe','peer',None,'P/L ≤ mediana dos seus pares','Lucro recorrente e ciclo precisam de revisão.')
            if a['asset_type']=='stock':
                selic=macros.get('selic',{}); hurdle=selic.get('value')
                if age(selic.get('asof',''))>7: hurdle=None
                check('roe','ge',hurdle+cfg['risk_premium'] if hurdle is not None else None,
                      'ROE ≥ Selic + prêmio de estudo','Triagem de rentabilidade contábil; não estima retorno da ação nem substitui o custo de capital.')
                checks[-1]['group']='opportunity'
                if selic:
                    checks[-1]['references'].append({k:selic.get(k,'') for k in ('asof','source','retrieved_at')})
                if hurdle is None: checks[-1]['reason']='Selic ausente ou com referência superior a 7 dias; atualizar para comparar.'
            check('roe','gt',0,'Rentabilidade patrimonial positiva','ROE positivo é um requisito básico; avaliar recorrência, risco e custo do capital. Não garante saúde financeira.')
        if ident=='bank':
            check('basel','ge',None,'Capital regulatório ≥ exigência deste banco',other='capital_required')
        if ident=='insurance':
            check('solvency','ge',None,'Capital disponível ≥ capital requerido',other='solvency_required')
        for key,limit in limits.items():
            if ident=='fii':
                from aporte_brasil.company import fii_research
                typ=fii_research.subtype(a)
                if key in ('vacancy','top_tenant') and typ not in ('tijolo','hibrido'):continue
                if key not in ('top_tenant','fund_leverage') and key not in fii_research.FOCUS[typ]:continue
            check(key,OPERATORS[key],limit,explanation='Limite inicial de estudo, editável. Não é mediana do setor, covenant ou regra regulatória.')
        if ident in NONFINANCIAL_PROFILES:
            check('operating_cashflow','gt',0,'Fluxo de caixa operacional positivo','Conferir recorrência, capital de giro e período de 12 meses.')
            check('roic','ge',None,'ROIC ≥ WACC',other='wacc',explanation='Mesma base, período e moeda; WACC é uma estimativa informada por você.')
        if ident=='retail': check('lease_consistent','ge',1,'Arrendamentos comparáveis','1 = base consistente confirmada no relatório; 0 = revisar.')
        if ident=='fii':
            from aporte_brasil.company import fii_research
            typ=fii_research.subtype(a)
            check('distribution_cover','ge',1,'Resultado recorrente cobre a distribuição','Usar a mesma janela de resultado e distribuição; o resultado financeiro com vendas não comprova recorrência.')
        risks=p['risks']
        if a['asset_type'] in ('foreign','global_stock','bdr'):
            risks=[x.replace('no Brasil','no mercado da empresa') for x in risks]+['Limites de estudo por negócio; confirmar contabilidade, moeda e exigência do regulador do país. O ROE não é comparado à Selic brasileira.']
        a['sector_analysis']={'profile':ident,'label':p['label'],'risks':risks,'checks':checks,
            'references':[r for r in REFERENCES if r['id'] in p['refs'] and (a['asset_type'] not in ('foreign','global_stock','bdr') or r['id'] not in ('bcb','susep'))],
            'counts':{status:sum(x['status']==status and x['group']=='health' for x in checks) for status in ('pass','fail','unknown')},
            'valuation_counts':{status:sum(x['status']==status and x['group']!='health' for x in checks) for status in ('pass','fail','unknown')}}
    return assets

def validate_rules(d,number):
    if not isinstance(d,dict): raise ValueError('Critérios por setor inválidos.')
    out={}
    for p,rules in d.items():
        if p not in PROFILES or not isinstance(rules,dict): raise ValueError('Perfil de análise inválido.')
        out[p]={}
        for key,v in rules.items():
            if key not in PROFILES[p]['limits']: raise ValueError('Indicador não configurável para esse perfil.')
            out[p][key]=number(v,True,0,1000)
    return out

def health_guide(cfg):
    return {'profiles':[{ 'id':ident,'label':p['label'],'limits':{**p['limits'],**cfg.get('sector_rules',{}).get(ident,{})},
        'risks':p['risks'],'references':[r for r in REFERENCES if r['id'] in set(p['refs']+(['fitch'] if ident in NONFINANCIAL_PROFILES else []))]}
        for ident,p in PROFILES.items()],
        'principles':[
          {'metric':'net_debt_ebitda','rule':'Abaixo do corte de prudência do perfil; testar também EBITDA menor e vencimentos.','basis':'Corte editável do aplicativo, não consenso oficial brasileiro.'},
          {'metric':'interest_coverage','rule':'Acima de 1× cobre juros pelo EBIT; o corte maior do perfil cria folga de estudo.','basis':'Relação contábil. Não confundir EBIT/juros com EBITDA/juros ou EBITDAR/encargos fixos.'},
          {'metric':'current_ratio','rule':'1× equivale a ativo circulante igual ao passivo circulante; verificar liquidez real de estoque/recebíveis.','basis':'Relação contábil, com cortes editáveis por perfil.'},
          {'metric':'roic','rule':'ROIC ≥ custo de capital (WACC), na mesma base/período.','basis':'Criação de valor econômico, referência Damodaran.'},
          {'metric':'operating_cashflow','rule':'Caixa operacional positivo e recorrente; conferir investimento e serviço da dívida.','basis':'Capacidade de gerar caixa, referência Fitch/Damodaran.'},
          {'metric':'pvp','rule':'Não há P/VP universal saudável. Relacionar preço a rentabilidade, risco e qualidade do patrimônio.','basis':'Valuation, separado da saúde financeira.'},
          {'metric':'dy','rule':'DY elevado não garante dividendo sustentável. Verificar recorrência, payout e caixa após investimentos.','basis':'Rendimento histórico, separado da saúde financeira.'}],
        'market_examples':[
          {'profiles':['utility'],'title':'Energia · leitura profissional no Brasil, 2T26','asof':'2026-09-14','source':'XP Credit Research','url':'https://conteudos.xpi.com.br/renda-fixa/relatorios/temporada-de-resultados-renda-fixa-2o-trimestre-de-2026/','text':'A XP descreve 1,7× da Axia como confortável e 3,6× da Engie como ainda elevado. Na Equatorial, considera saudável 3,1× na definição de covenant, mas registra 3,6× excluindo ganho de venda. São avaliações de emissores específicos, não limites para todo o setor.'},
          {'profiles':['commodity','food_agro'],'title':'Commodities · geração de caixa muda a interpretação','asof':'2026-09-14','source':'XP Credit Research','url':'https://conteudos.xpi.com.br/renda-fixa/relatorios/temporada-de-resultados-renda-fixa-2o-trimestre-de-2026/','text':'A XP avalia positivamente o crédito da São Martinho com dívida líquida/EBITDA ajustado de 1,59×; a razão passa a 3,9× ao descontar investimento de manutenção. Na Raízen, 5,2× e falta de recorrência dos resultados recebem avaliação de crédito preocupante.'},
          {'profiles':['retail'],'title':'Varejo · ajustes e caixa antes do múltiplo','asof':'2026-09-14','source':'XP Credit Research','url':'https://conteudos.xpi.com.br/renda-fixa/relatorios/temporada-de-resultados-renda-fixa-2o-trimestre-de-2026/','text':'No 2T26, a XP destaca baixa alavancagem e distância dos covenants no Grupo Mateus, apesar da pressão operacional. Para Assaí e GPA, separa ganhos tributários não recorrentes da operação e observa capital de giro. Não publica um P/VP saudável universal.'}
        ],
        'note':'Faixas de prudência para triagem por negócio. Não são uma certificação de saúde nem consenso do mercado. As fontes sustentam a metodologia; limites numéricos do aplicativo são escolhas editáveis e exigem confirmação no segmento/RI.'}

# Plain-language definitions. These describe metrics, never universal buy/sell limits.
_INFO={
 'top_property':('Maior participação de um imóvel na receita total do FII × 100.','Concentração de imóvel difere de inquilino; avalie localização e qualidade dos contratos.'),
 'rental_delinquency':('Inadimplência dos imóveis ponderada pela participação na receita divulgada × 100.','Confira a definição e recuperação dos atrasos; não é risco de crédito de CRI.'),
 'short_contracts':('Participação da receita de contratos com vencimento em até 12 meses × 100.','Avalie renovação, multa e revisional; o vencimento não implica automaticamente perda da receita.'),
 'ipca_share':('Participação da receita de contratos indexada ao IPCA × 100.','É composição dos contratos, não taxa de inflação nem projeção de rendimento.'),
 'igpm_share':('Participação da receita de contratos indexada ao IGP-M × 100.','Confira reajuste, defasagem e capacidade de pagamento dos locatários.'),
 'credit_delinquency':('Recebíveis em atraso ÷ carteira de CRIs × 100, na janela do gestor.','Confira dias de atraso, renegociações, provisões e garantias; não use a inadimplência de aluguéis.'),
 'top_credit':('Exposição ao maior devedor final ÷ carteira de CRIs × 100.','Securitizadora não é necessariamente o devedor; agrupe exposições do mesmo grupo econômico.'),
 'ltv':('Saldo dos créditos ÷ valor das garantias, na ponderação do gestor × 100.','Exige avaliação, senioridade e data das garantias; patrimônio do FII não substitui as garantias dos CRIs.'),
 'top_fund':('Maior fundo investido ÷ total da carteira de FIIs divulgada × 100.','Confira carteira completa, concentração indireta e taxas dos fundos investidos.'),
 'cash_distribution_cover':('Resultado financeiro acumulado ÷ rendimentos declarados na janela do informe CVM.','Pode incluir vendas e itens extraordinários; não comprova cobertura por resultado recorrente.'),
 'gross_margin':('Lucro bruto ÷ receita na mesma janela × 100.','Compare mix, preços, custos e recorrência; não existe uma margem ideal universal.'),
 'inventory_days':('Estoque médio do balanço atual e de 12 meses antes ÷ custo da receita em 12 meses × 365.','Avalie sazonalidade, obsolescência e mix; mais dias podem consumir caixa.'),
 'cash_conversion':('Caixa operacional ÷ lucro líquido positivo, na mesma janela.','Capital de giro e itens sem efeito caixa alteram a relação; um ano não comprova recorrência.'),
 'loss_ratio':('Sinistros ÷ prêmios ganhos × 100, na definição da seguradora.','Confira resseguro, despesas e base bruta/líquida; compare o mesmo ramo.'),
 'combined_ratio':('Sinistros e despesas ÷ prêmios ganhos × 100, na definição da fonte.','Acima de 100% pode indicar perda na subscrição; renda financeira e diferenças metodológicas importam.'),
 'recurring_revenue':('Receita classificada como recorrente ÷ receita total × 100.','Confirme definição, contratos, renovação e concentração de clientes.'),
 'contracted_revenue':('Receita coberta por contratos ÷ receita total × 100.','Leia vigência, reajuste, contrapartes e exposição ao mercado livre.'),
 'same_store_sales':('Variação de vendas das mesmas lojas, na janela e perímetro divulgados × 100.','Inflação, fechamento e abertura de lojas mudam a leitura; não compare bases diferentes.'),
 'production_growth':('Variação do volume produzido entre janelas equivalentes × 100.','Use o mesmo produto, unidade e período; preço maior não equivale a volume maior.'),
 'sales_velocity':('Vendas ÷ oferta disponível (VSO) × 100, na definição da incorporadora.','Confira janela, distratos e base bruta/líquida de vendas.'),
 'utilization':('Volume usado ÷ capacidade disponível × 100, segundo a operação.','Compare a mesma medida: frota, assentos ou capacidade fabril; não misture negócios.'),
 'churn':('Clientes cancelados ÷ base de clientes na janela divulgada × 100.','Churn mensal e anual não são intercambiáveis; confira serviço, base e metodologia.'),
 'retention':('Receita mantida da mesma coorte de clientes ÷ receita inicial × 100.','Retenção líquida pode superar 100% por expansão; retenção bruta exclui expansão.'),
 'receivable_days':('Prazo médio de recebimento em dias, conforme relatório.','Confira método, atrasos, glosas e sazonalidade.'),
 'student_dropout':('Alunos evadidos ÷ base de alunos, na definição divulgada × 100.','Compare modalidade e período letivo; transferências e formaturas exigem tratamento próprio.'),
 'pvp':('Preço da ação ÷ valor patrimonial por ação (VPA).','1× equivale ao patrimônio contábil por ação. Um valor baixo pode refletir ativos ruins ou baixa rentabilidade; um valor alto pode refletir qualidade e intangíveis.'),
 'pe':('Preço da ação ÷ lucro por ação dos últimos 12 meses (LPA).','Quanto se paga pelo lucro histórico. Lucro negativo ou extraordinário e ciclos distorcem a comparação; não é prazo garantido de retorno.'),
 'dy':('Proventos por ação da janela anual ÷ preço de referência × 100.','É rendimento passado. Verifique se inclui JCP, se a base é bruta/líquida e se pagamentos excepcionais elevaram o valor.'),
 'dividends_per_share':('Dividendos e outros proventos elegíveis por ação em 12 meses.','Use o valor por ação, ajustado a desdobramentos. Não use o total recebido na sua carteira; confirme quais pagamentos entram na janela.'),
 'eps':('Lucro atribuível aos acionistas ÷ número médio de ações na janela de 12 meses.','LPA: compare a mesma classe, base básica/diluída e período. Lucro não recorrente pode inflar o preço calculado por Graham.'),
 'bvps':('Patrimônio líquido atribuível aos acionistas ÷ número de ações na data do balanço.','VPA: é valor contábil, não preço de liquidação. Confira a classe de ação, minoritários, intangíveis e patrimônio negativo.'),
 'payout':('Proventos por ação ÷ lucro por ação na mesma janela × 100.','Acima de 100% pode consumir reservas ou refletir itens excepcionais. Lucro não positivo não dá uma razão comparável.'),
 'roe':('Lucro líquido ÷ patrimônio líquido médio × 100, na base divulgada.','Rentabilidade contábil dos acionistas. Alavancagem e patrimônio reduzido podem inflar o resultado; ROE não é retorno esperado da ação.'),
 'net_debt_ebitda':('Dívida financeira menos caixa elegível ÷ EBITDA dos últimos 12 meses.','Triagem de alavancagem: quanto maior, maior a dependência de geração de caixa. Exige EBITDA positivo; dívida negativa pode indicar caixa líquido. Não se aplica da mesma forma a bancos. Não confundir com EV/EBITDA.'),
 'debt_equity':('Dívida financeira bruta ÷ patrimônio líquido.','Quanto de dívida há para cada real de patrimônio. Exige patrimônio positivo; não inclui automaticamente todos os passivos e não substitui dívida líquida/EBITDA.'),
 'net_debt_equity':('Dívida financeira menos caixa elegível ÷ patrimônio líquido.','Razão líquida, diferente de dívida bruta/PL. Confira caixa restrito, arrendamentos e patrimônio positivo.'),
 'interest_coverage':('EBIT ÷ despesas de juros, na mesma janela.','1× cobre os juros pelo resultado operacional antes de juros e impostos. Não confundir despesa de juros com resultado financeiro líquido nem com cobertura por EBITDA.'),
 'current_ratio':('Ativo circulante ÷ passivo circulante.','1× significa valores contábeis iguais. Estoques e recebíveis podem não virar caixa a tempo; bancos precisam de indicadores próprios.'),
 'operating_margin':('EBIT ÷ receita líquida × 100.','Margem operacional antes de juros e impostos. Compare recorrência, mesmo período e mesmo negócio.'),
 'operating_cashflow':('Caixa líquido gerado pelas atividades operacionais nos últimos 12 meses.','Leia a DFC: lucro positivo pode coexistir com saída de caixa. Sazonalidade e capital de giro importam; some períodos sem duplicar valores acumulados.'),
 'free_cashflow':('Caixa operacional menos investimentos considerados na definição da fonte.','Caixa após investimentos. A definição varia; confirme capex de manutenção/expansão, arrendamentos e período antes de comparar.'),
 'roic':('Lucro operacional após impostos ÷ capital investido, na definição da fonte.','Compare com WACC na mesma base, período e moeda. Ajustes de caixa, goodwill e arrendamentos alteram o indicador.'),
 'wacc':('Média ponderada do custo de capital próprio e da dívida após impostos.','É uma estimativa de custo de capital. Não é igual à Selic e não pode ser deduzida de P/VP; explicite taxas, pesos, moeda e premissas.'),
 'basel':('Capital prudencial (PR) ÷ ativos ponderados pelo risco (RWA) × 100.','Compare com a exigência específica do banco e seus adicionais. Capital principal e nível I são medidas complementares.'),
 'capital_required':('Exigência total de capital usada na comparação com o índice de Basileia deste banco.','Informe a exigência divulgada para a instituição e a mesma data; não há um percentual único que substitua todos os adicionais regulatórios.'),
 'npl90':('Crédito com atraso superior a 90 dias ÷ carteira de crédito × 100.','Indicador de inadimplência. Compare mesmo perímetro e metodologia; provisões, renegociações e mudanças contábeis importam.'),
 'coverage':('Provisões para perdas ÷ crédito inadimplente na definição divulgada × 100.','Confira o denominador (por exemplo, atrasos >90 dias). Não misture coberturas com diferentes conceitos de perda.'),
 'solvency':('Capital disponível para cobrir riscos, segundo o relatório regulatório da seguradora.','Informe valor monetário na mesma unidade e data do capital requerido. Não confundir com índice percentual de solvência.'),
 'solvency_required':('Capital requerido para cobrir os riscos da seguradora.','Compare com capital disponível segundo a mesma definição regulatória; informe reais, não milhares sem conversão.'),
 'lease_consistent':('Confirmação de que dívida e EBITDA usam uma base consistente de arrendamentos (IFRS 16).','1 = você confirmou no relatório; 0 = precisa revisar. Não é uma razão financeira nem uma informação inferida automaticamente.'),
 'financial_vacancy':('Receita potencial não recebida por vacância ÷ receita potencial × 100.','Use a definição do gestor: não equivale à área vaga e não deve substituir automaticamente a vacância física.'),
 'vacancy':('Área vaga ÷ área locável × 100, usando vacância física.','Vacância física difere da financeira. Para FIIs de papel, o risco principal é de crédito, não de área vazia.'),
 'top_tenant':('Participação do maior locatário na receita do fundo × 100.','Concentração: confira contratos, garantias e definição no relatório. Em fundos de papel, use análise própria de devedores.'),
 'fund_leverage':('Obrigações financeiras do fundo ÷ patrimônio líquido × 100, na base divulgada.','Confira vencimentos, garantias, caixa e definição de obrigações; não equivale à alavancagem de uma empresa operacional.'),
 'distribution_cover':('Resultado recorrente elegível ÷ rendimentos distribuídos na mesma janela.','1× cobre a distribuição pelo resultado dessa definição. Ganhos de venda ou reservas podem sustentar distribuição temporariamente.'),
 'expense_ratio':('Despesas anuais totais ÷ patrimônio médio do ETF × 100.','Confira se é despesa total ou apenas administração e se há taxas nos fundos investidos. Veja lâmina e regulamento.'),
 'tracking_error':('Volatilidade anualizada da diferença entre os retornos do ETF e do índice.','Mede consistência de acompanhamento, não o retorno médio perdido. Não confundir com tracking difference; compare a mesma janela.'),
}
_COMPANY_SOURCE={'title':'CVM · balanços e resultados trimestrais','url':'https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr'}
_PROVIDER_SOURCE={'title':'brapi · campos e cobertura de fundamentos','url':'https://brapi.dev/docs/acoes/dados-financeiros'}
_BANK_SOURCE={'title':'BCB · IF.data','url':'https://www3.bcb.gov.br/ifdata/?lang=1'}
_FUND_SOURCE={'title':'B3 · documentos de fundos (FNET)','url':'https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM'}
_REG_SOURCE={'title':'Susep · dados e estatísticas','url':'https://www.gov.br/susep/pt-br/assuntos/dados-e-estatisticas'}
_DDM_SOURCE={'title':'Damodaran · modelos de dividendos','url':'https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch13.pdf'}

def indicator_source(key):
    if key in ('top_property','rental_delinquency','short_contracts','ipca_share','igpm_share','top_fund','cash_distribution_cover'):
        return 'Informe trimestral estruturado da CVM e relatório do gestor, com a mesma janela e definição.',[{'title':'CVM · informes trimestrais de FIIs','url':'https://dados.cvm.gov.br/dataset/fii-doc-inf_trimestral'},_FUND_SOURCE]
    if key in ('credit_delinquency','top_credit','ltv'):
        return 'Relatório gerencial de crédito do gestor: devedor final, atrasos, garantias e data. O informe agregado não permite presumir esses dados.',[_FUND_SOURCE]
    if key in ('loss_ratio','combined_ratio','recurring_revenue','contracted_revenue','same_store_sales','production_growth','sales_velocity','utilization','churn','retention','receivable_days','student_dropout'):
        return 'Relatório de resultados / operacional no RI da empresa. Confirme definição e janela; esta medida não é inferida do lucro ou do setor.',[_COMPANY_SOURCE]
    if key in ('basel','capital_required','npl90','coverage'):return 'Relatório de riscos / Pilar 3 e resultados do banco; IF.data como consulta complementar.',[_BANK_SOURCE]
    if key in ('solvency','solvency_required'):return 'Relatório de solvência da seguradora e dados regulatórios da Susep.',[_REG_SOURCE]
    if key in ('vacancy','financial_vacancy','top_tenant','fund_leverage','distribution_cover'):return 'Relatório gerencial do FII, com unidade, período e definição; FNET reúne documentos.',[_FUND_SOURCE]
    if key in ('expense_ratio','tracking_error'):return 'Lâmina, regulamento e relatório do gestor do ETF. Tracking error exige uma série comparável ao índice.',[_FUND_SOURCE]
    if key=='wacc':return 'Premissa de valuation documentada por você ou por uma pesquisa identificada, com base e moeda.',[_DDM_SOURCE]
    return 'brapi e páginas públicas quando cobertas; confirme janela e ajustes no RI e nas demonstrações da CVM.',[_PROVIDER_SOURCE,_COMPANY_SOURCE]

INDICATOR_INFO={k:{'label':METRICS[k][0],'unit':METRICS[k][1],'meaning':v[0],'reading':v[1],
                   'where':indicator_source(k)[0],'sources':indicator_source(k)[1]} for k,v in _INFO.items()}

def coverage(a,age):
    """Missing usable values only; insufficient peer samples are not missing metrics."""
    p=a['sector_analysis']['profile']
    keys=set(c['metric'] for c in a['sector_analysis']['checks'])
    from aporte_brasil.company import company_insights
    keys.update(row[0] for row in company_insights.SECTOR_FOCUS.get(p,[]))
    if p in COMPANY_PROFILES:keys.update(('dy','eps','bvps','dividends_per_share','payout'))
    if p=='fii':
        from aporte_brasil.company import fii_research
        typ=fii_research.subtype(a)
        keys.update(('pvp','dy','bvps','cash_distribution_cover',*fii_research.FOCUS[typ]))
        if typ in ('tijolo','hibrido'):keys.update(('financial_vacancy','ipca_share','igpm_share'))
    if p=='bank':keys.add('capital_required')
    if p=='insurance':keys.add('solvency_required')
    if p in NONFINANCIAL_PROFILES:keys.add('wacc')
    rows=[]
    for key in METRICS:
        if key not in keys:continue
        v,s,reason=metric(a,key,age)
        blocked=next((c['reason'] for c in a['sector_analysis']['checks'] if c['metric']==key and c['value'] is None and c['status']=='unknown'),None)
        # Credit funds have no physical vacancy to fetch.
        if key in ('vacancy','financial_vacancy') and any(w in fold(a.get('sector','')) for w in ('papel','recebiveis','cri')):continue
        if v is not None and not blocked:continue
        found=[{'index':i,'source':r['source'],'url':r['url'],'value':r['values'][key],'retrieved_at':r.get('retrieved_at','')} for i,r in enumerate(a.get('provider_references',[])) if r.get('values',{}).get(key) is not None]
        where,sources=indicator_source(key)
        if a['asset_type'] in ('foreign','global_stock','global_etf'):
            url=a.get('international',{}).get('composition_url') or 'https://finance.yahoo.com/quote/'+a['ticker']+'/'
            where='Use o relatório do emissor e o regulador aplicável no país. Confirme período, definição e moeda da demonstração; informe valores monetários completos. ETFs: lâmina, índice e relatório de acompanhamento.'
            sources=[{'title':'Emissor / demonstrações internacionais','url':url}]
        rows.append({'metric':key,'label':METRICS[key][0],'reason':blocked or reason,
                     'status':'confirm' if found or v is not None else 'stale' if s else 'missing',
                     'found':found,'where':where,'sources':sources})
    return rows
