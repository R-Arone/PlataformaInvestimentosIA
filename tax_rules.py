"""Versioned Brazilian PF tax references, separate from an actual tax assessment."""
import calendar
from datetime import date

CHECKED='2026-10-05'
IRPF='https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/perguntas-e-respostas/dirpf/p-r-irpf-2026-v1-00-2026-04-23.pdf'
OFFSHORE='https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/lei/l14754.htm'
JCP='https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp224.htm'
DIVIDENDS='https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/agosto/receita-federal-orienta-sobre-os-procedimentos-para-o-recolhimento-do-imposto-de-renda-retido-na-fonte-sobre-lucros-e-dividendos/'

def regressive(days,short=False):
    return 22.5 if days<=180 else 20 if short or days<=360 else 17.5 if days<=720 else 15

def horizon_days(start,months):
    idx=start.year*12+start.month-1+int(months); y,m=divmod(idx,12); m+=1
    end=date(y,m,min(start.day,calendar.monthrange(y,m)[1]))
    return (end-start).days

def reference(product,days=365):
    r={'product':product,'rate':None,'checked_at':CHECKED,'source':IRPF,'scope':'Pessoa física residente no Brasil · referência geral',
       'basis':'Rendimento / ganho tributável, não o patrimônio','days':days,'automatic':False}
    if product in ('CDB','Tesouro','Fundo RF / multimercado · longo prazo'):
        r.update(rate=regressive(days),automatic=True,rule='22,5% até 180 dias; 20% de 181 a 360; 17,5% de 361 a 720; 15% acima de 720.',
                 note='Retenção no resgate/vencimento. IOF antes de 30 dias e eventos intermediários exigem cálculo próprio.')
        if product.startswith('Fundo'):
            r['note']='Regime de longo prazo precisa ser confirmado; em regra, come-cotas de 15% em maio/novembro e complemento no resgate. Cenário simplificado não reproduz come-cotas.'
    elif product=='Fundo RF / multimercado · curto prazo':
        r.update(rate=regressive(days,True),automatic=True,rule='22,5% até 180 dias; 20% acima de 180.',note='Em regra, come-cotas de 20%; confirmar classificação tributária no regulamento.')
    elif product in ('LCI','LCA','CRI','CRA'):
        r.update(rate=0,automatic=True,rule='Rendimentos isentos de IR para pessoa física, nas condições legais.',note='A regra não é estendida automaticamente a fundos que compram esses títulos.')
    elif product=='Fundo de ações':
        r.update(rate=15,automatic=True,rule='15% sobre ganhos no resgate, retido pelo administrador.',note='Sem come-cotas no regime usual de FIA; conferir enquadramento do fundo.')
    elif product in ('Ação B3','BDR','ETF · renda variável'):
        r.update(rate=15,rule='15% sobre ganho líquido em operação comum; 20% em day trade.',note='Apuração mensal; custos, prejuízos e IRRF alteram o devido. '+('Isenção de operações comuns com ações à vista quando vendas de ações no mês ≤ R$ 20 mil; não vale para day trade.' if product=='Ação B3' else 'Sem a isenção mensal de R$ 20 mil aplicável às ações.'))
    elif product=='FII':
        r.update(rate=20,rule='20% sobre ganho líquido na venda/resgate.',note='Distribuições podem ser isentas para PF se cumpridas as condições legais, inclusive negociação, mínimo de 100 cotistas e limites de participação; fora da isenção, há tributação. Não calcular só pelo ticker.')
    elif product=='ETF · renda fixa':
        r.update(rule='25%, 20% ou 15%, conforme prazo médio de repactuação da carteira: até 180; 181 a 720; acima de 720 dias.',note='Depende da carteira do ETF, não do tempo que você manteve a cota. Não presumir 15%.')
    elif product=='Ação estrangeira':
        r.update(rate=15,source=OFFSHORE,rule='Regra geral: 15% sobre rendimentos realizados de aplicações financeiras no exterior, na declaração anual.',note='Inclui regras de conversão cambial e possível crédito de imposto pago fora. O cadastro em reais não realiza a apuração fiscal.')
    elif product=='JCP':
        r.update(rate=17.5,source=JCP,rule='17,5% de IRRF para pagamento/crédito em 2026; antes, a regra geral era 15%.',note='Não descontar novamente de um valor já líquido importado do extrato.')
    elif product=='Dividendos brasileiros':
        r.update(source=DIVIDENDS,rule='Desde 2026, IRRF de 10% sobre o total quando a mesma PJ paga à mesma PF mais de R$ 50 mil no mês.',note='Há exceções de transição e tributação anual mínima para altas rendas acima de R$ 600 mil. Não há alíquota única adequada por lançamento.')
    else:
        r.update(rule='Regime precisa ser confirmado.',note='Fundos genéricos, previdência e cripto dependem de enquadramento, local, operação e/ou opção tributária. Não presumir isenção.')
    return r

PRODUCTS=['CDB','Tesouro','LCI','LCA','CRI','CRA','Fundo RF / multimercado · longo prazo','Fundo RF / multimercado · curto prazo','Fundo de ações','Ação B3','BDR','ETF · renda variável','ETF · renda fixa','FII','Ação estrangeira','JCP','Dividendos brasileiros','Previdência','Bitcoin','Fundo de investimento']

def references(): return [reference(p) for p in PRODUCTS]
