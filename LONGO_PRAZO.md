# Recomendador de aportes: qualidade, valor e contrafluxo

A primeira versão trabalha somente com a carteira e os ativos acompanhados. Usa as metas salvas por classe; elas podem ser ajustadas em **Metas e aportes**. O cálculo é local, sem ordens, vendas, alteração de posições ou envio da carteira a modelos externos.

## Como a tese é usada

O [Templeton Global Equity Group](https://www.franklintempleton.com/corporate/articles/2024/equity/quality-account-an-introduction-to-the-quality-value-proposition) descreve uma abordagem de qualidade e valor: avaliar posição competitiva, estabilidade financeira e gestão, confrontando o potencial de resultados de longo prazo com o preço. Na busca por [bolsões de pessimismo](https://www.franklintempleton.com/corporate/articles/2024/equity/hunting-for-pockets-of-pessimism), o foco de curto prazo do mercado pode criar oportunidades. São descrições do processo de uma gestora, não evidência independente de rentabilidade futura.

Na pesquisa [Quality Minus Junk, de Asness, Frazzini e Pedersen](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk), características de qualidade são estudadas em diferentes países. O portfólio acadêmico compra qualidade e vende a descoberto empresas de menor qualidade. Seus resultados históricos não são a rentabilidade de uma carteira brasileira comprada, com impostos e custos, nem validam os parâmetros deste aplicativo.

A [MSCI](https://www.msci.com/indexes/group/quality-indexes) usa rentabilidade do patrimônio, estabilidade do crescimento dos lucros e alavancagem na construção de índices de qualidade. Esses indicadores ajudam a tornar o conceito verificável. O checklist desta plataforma é próprio e inclui os critérios pedidos pelo usuário; não replica os índices MSCI.

[Damodaran](https://pages.stern.nyu.edu/~adamodar/pdfiles/blog/Contrarian.pdf) distingue comprar quedas indiscriminadamente de procurar quedas maiores do que os fundamentos justificariam. A combinação de filtros de rentabilidade e risco é uma forma de investigar armadilhas de valor. Ainda é necessário atualizar o valor do negócio e explicar por que o problema seria temporário.

Também existe evidência de [valor e momentum usados em conjunto](https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere). Retirar tendência do nosso ranking base é uma escolha de desenho para esta tese; não é uma conclusão de superioridade sobre estratégias que usam momentum.

## Regras da primeira versão

1. Escolher o estilo do aporte. **Proporcional** reparte pelos déficits positivos das classes e mantém os orçamentos por meta. **Poucos destinos** prioriza até dois ativos inicialmente, permitindo que uma classe fique temporariamente acima da meta. Só entram classes com orçamento positivo na referência proporcional; os limites por emissor e setor continuam obrigatórios. Os limites de destinos são ajustáveis de 1 a 20.
2. Comparar ações brasileiras e FIIs, com cotação de até sete dias. As demais classes recebem orçamento, com produto ainda a escolher.
3. Usar a análise completa já existente. Qualidade é a proporção de critérios atendidos entre os aplicáveis; pendências entram no denominador. Preço e itens não aplicáveis ficam separados. Qualquer critério conhecido de qualidade reprovado exige revisão. A cobertura mínima inicial é 70%, ajustável entre 50% e 100%. Cobertura é disponibilidade dos dados, não probabilidade de acerto.
4. Para ações, usar o método prioritário ou complementar aplicável ao negócio, com premissas salvas/revistas em até 180 dias. Usar o teto que já inclui a margem de segurança escolhida. Entradas ainda estimadas por múltiplos precisam ser conferidas. Fórmulas de triagem não se tornam preço ideal.
5. Para FIIs, usar VPA como referência contábil de P/VP 1. Exigir P/VP abaixo de 1; acima de 1,5 é descarte obrigatório. VPA não é valor econômico nem preço de liquidação. A comparação de yield usa a fonte documentada já cadastrada; resultado conhecido abaixo da média impede sugestão, informação ausente fica explícita nas pendências. P/VP e cotação devem ter a mesma data para derivar a referência.
6. Prioridade = 50% qualidade + 35% desconto + 15% necessidade da classe. O componente de desconto cresce até 30% abaixo do valor de referência e então fica limitado a 100 pontos. O componente de necessidade mede déficit/meta em reais da classe após o aporte. A nota anterior do comparador aparece separadamente porque contém tendência.
7. Distribuir por ordem de prioridade, com unidades inteiras e orçamento em centavos. O mínimo inicial por compra é R$ 500, ajustável inclusive para zero; é um parâmetro de simulação, sem fundamento universal de custo ou rentabilidade. Respeitar os limites cadastrados por emissor e setor sobre a carteira negociada efetivamente investida após as sugestões. ON/PN/units do mesmo radical de ticker compartilham o limite; apenas uma classe recebe aporte por cenário. Dinheiro a decidir não reduz artificialmente a concentração. Em uma carteira nova, poucos destinos podem impedir uma distribuição válida.
8. Mostrar dinheiro a decidir, razões dos bloqueios e pendências. Quantidades são indicativas: taxas, spread e mudanças entre a cotação e a execução precisam ser conferidos antes de registrar uma operação.

Esses pesos, cortes e validade são escolhas iniciais do aplicativo. Não são estimados pelos estudos citados, não representam recomendação dessas instituições e não foram validados como estratégia brasileira ou de FIIs.

## Aportar em poucos destinos e revisar nos meses seguintes

A tela compara um, dois, três destinos e a divisão proporcional usando a mesma carteira, preços e valor mínimo. Mostra os valores, o saldo a decidir e a distância das metas. Distância menor mede proximidade da alocação desejada, sem medir retorno esperado. A comparação proporcional pode deixar dinheiro a decidir quando a classe ainda exige escolha de produto.

As classes que ficarem abaixo da meta aparecem como próximas prioridades. Não há garantia de compensação no mês seguinte: o próximo aporte precisa ser recalculado com preços, posições e dinheiro disponíveis naquele momento. A simulação não agenda compras futuras nem exige vender para zerar diferenças pequenas.

## Áreas dos ETFs e exposições em comum

O [DEBB11](https://www.btgpactual.com/asset-management/etf-debentures) acompanha um índice de debêntures e recebe classificação de renda fixa / crédito privado. DEB11 não é usado como um alias automático, para evitar identificar outro ativo incorretamente.

O [ABTC11](https://www.btgpactual.com/asset-management/etf/ABTC11) combina Bitcoin, renda fixa pós-fixada e títulos ligados à inflação, com pesos dinâmicos. Ele aparece relacionado a essas áreas; o seu valor integral não é tratado como valor investido em Bitcoin. Sem os pesos atuais, fica em Outros / a classificar para as metas. A categoria manual por produto continua disponível, sem criar percentuais internos fictícios.

O mapa distingue posições atuais de ativos apenas acompanhados. Bitcoin direto e um ETF relacionado podem compartilhar uma área; fundos de crédito e ETFs de debêntures podem compartilhar crédito privado. A relação é temática, não uma demonstração de ativos idênticos ou uma soma de percentuais internos. A carteira do produto pode mudar; a fonte e a data devem ser conferidas. Temas podem ser editados com fonte e data, e ativos desconhecidos não são classificados por palavras do nome. Os registros ficam no banco privado e nos backups.

## Versão com contexto

Acrescenta a leitura salva de juros, dólar, commodities, notícias e sentimento por IA quando disponível e recente. A identificação de pessimismo usa notícias de mercado/setor e distância de pelo menos 15% do máximo na série ajustada disponível. Exige pelo menos 120 observações, com última observação em até sete dias; mostra o intervalo efetivamente usado, sem apresentá-lo como um ano completo obrigatório.

O marcador de 15% é editorial. A queda é calculada inteiramente na série ajustada, sem misturar seu máximo com a cotação nominal. O cenário explica possíveis canais de impacto e o que invalidaria a tese. Dados antigos ou ausentes são identificados. O contexto não altera silenciosamente o ranking nem o orçamento e não informa chance de alta ou retorno esperado. Gerar a recomendação não inicia análise paga nem envia dados a um modelo.

## Validação de investimento ainda necessária

Os testes automatizados verificam regras, privacidade, datas, dinheiro e concentração. Não medem desempenho financeiro. Avaliar a estratégia exige dados disponíveis à época, empresas que deixaram a bolsa, ajustes societários, custos, liquidez, impostos e validação fora da amostra. Comparar com aportes pelas metas, alocação simples, índice apropriado e CDI, medindo retorno, perdas, concentração e giro. Os dados atuais do aplicativo não autorizam reconstruir recomendações históricas sem viés de antecipação.

O [Investor.gov](https://www.investor.gov/introduction-investing/getting-started/asset-allocation) descreve rebalanceamento com novos aportes e diversificação como práticas de gestão da carteira; a alocação depende do prazo e da tolerância a risco de cada pessoa.
