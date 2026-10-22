# Recomendador de aportes: qualidade, valor e contrafluxo

A primeira versão trabalha somente com a carteira e os ativos acompanhados. Usa as metas salvas por classe; elas podem ser ajustadas em **Metas e aportes**. O cálculo é local, sem ordens, vendas, alteração de posições ou envio da carteira a modelos externos.

## Como a tese é usada

O [Templeton Global Equity Group](https://www.franklintempleton.com/corporate/articles/2024/equity/quality-account-an-introduction-to-the-quality-value-proposition) descreve uma abordagem de qualidade e valor: avaliar posição competitiva, estabilidade financeira e gestão, confrontando o potencial de resultados de longo prazo com o preço. Na busca por [bolsões de pessimismo](https://www.franklintempleton.com/corporate/articles/2024/equity/hunting-for-pockets-of-pessimism), o foco de curto prazo do mercado pode criar oportunidades. São descrições do processo de uma gestora, não evidência independente de rentabilidade futura.

Na pesquisa [Quality Minus Junk, de Asness, Frazzini e Pedersen](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk), características de qualidade são estudadas em diferentes países. O portfólio acadêmico compra qualidade e vende a descoberto empresas de menor qualidade. Seus resultados históricos não são a rentabilidade de uma carteira brasileira comprada, com impostos e custos, nem validam os parâmetros deste aplicativo.

A [MSCI](https://www.msci.com/indexes/group/quality-indexes) usa rentabilidade do patrimônio, estabilidade do crescimento dos lucros e alavancagem na construção de índices de qualidade. Esses indicadores ajudam a tornar o conceito verificável. O checklist desta plataforma é próprio e inclui os critérios pedidos pelo usuário; não replica os índices MSCI.

[Damodaran](https://pages.stern.nyu.edu/~adamodar/pdfiles/blog/Contrarian.pdf) distingue comprar quedas indiscriminadamente de procurar quedas maiores do que os fundamentos justificariam. A combinação de filtros de rentabilidade e risco é uma forma de investigar armadilhas de valor. Ainda é necessário atualizar o valor do negócio e explicar por que o problema seria temporário.

Também existe evidência de [valor e momentum usados em conjunto](https://www.aqr.com/insights/research/journal-article/value-and-momentum-everywhere). Retirar tendência do nosso ranking base é uma escolha de desenho para esta tese; não é uma conclusão de superioridade sobre estratégias que usam momentum.

## Regras da primeira versão

1. Dividir o aporte proporcionalmente aos déficits positivos das classes após incluir o dinheiro novo. Não aumentar uma classe acima da meta para compensar falta de oportunidades em outra.
2. Comparar ações brasileiras e FIIs, com cotação de até sete dias. As demais classes recebem orçamento, com produto ainda a escolher.
3. Usar a análise completa já existente. Qualidade é a proporção de critérios atendidos entre os aplicáveis; pendências entram no denominador. Preço e itens não aplicáveis ficam separados. Qualquer critério conhecido de qualidade reprovado exige revisão. A cobertura mínima inicial é 70%, ajustável entre 50% e 100%. Cobertura é disponibilidade dos dados, não probabilidade de acerto.
4. Para ações, usar o método prioritário ou complementar aplicável ao negócio, com premissas salvas/revistas em até 180 dias. Usar o teto que já inclui a margem de segurança escolhida. Entradas ainda estimadas por múltiplos precisam ser conferidas. Fórmulas de triagem não se tornam preço ideal.
5. Para FIIs, usar VPA como referência contábil de P/VP 1. Exigir P/VP abaixo de 1; acima de 1,5 é descarte obrigatório. VPA não é valor econômico nem preço de liquidação. A comparação de yield usa a fonte documentada já cadastrada; resultado conhecido abaixo da média impede sugestão, informação ausente fica explícita nas pendências. P/VP e cotação devem ter a mesma data para derivar a referência.
6. Prioridade = 50% qualidade + 35% desconto + 15% necessidade da classe. O componente de desconto cresce até 30% abaixo do valor de referência e então fica limitado a 100 pontos. O componente de necessidade mede déficit/meta em reais da classe após o aporte. A nota anterior do comparador aparece separadamente porque contém tendência.
7. Distribuir por ordem de prioridade, com unidades inteiras e orçamento em centavos. Respeitar os limites cadastrados por emissor e setor sobre a carteira negociada efetivamente investida após as sugestões. ON/PN/units do mesmo radical de ticker compartilham o limite; apenas uma classe recebe aporte por cenário. Dinheiro a decidir não reduz artificialmente a concentração. Em uma carteira nova, poucos destinos podem impedir uma distribuição válida.
8. Mostrar dinheiro a decidir, razões dos bloqueios e pendências. Quantidades são indicativas: taxas, spread e mudanças entre a cotação e a execução precisam ser conferidos antes de registrar uma operação.

Esses pesos, cortes e validade são escolhas iniciais do aplicativo. Não são estimados pelos estudos citados, não representam recomendação dessas instituições e não foram validados como estratégia brasileira ou de FIIs.

## Versão com contexto

Acrescenta a leitura salva de juros, dólar, commodities, notícias e sentimento por IA quando disponível e recente. A identificação de pessimismo usa notícias de mercado/setor e distância de pelo menos 15% do máximo na série ajustada disponível. Exige pelo menos 120 observações, com última observação em até sete dias; mostra o intervalo efetivamente usado, sem apresentá-lo como um ano completo obrigatório.

O marcador de 15% é editorial. A queda é calculada inteiramente na série ajustada, sem misturar seu máximo com a cotação nominal. O cenário explica possíveis canais de impacto e o que invalidaria a tese. Dados antigos ou ausentes são identificados. O contexto não altera silenciosamente o ranking nem o orçamento e não informa chance de alta ou retorno esperado. Gerar a recomendação não inicia análise paga nem envia dados a um modelo.

## Validação de investimento ainda necessária

Os testes automatizados verificam regras, privacidade, datas, dinheiro e concentração. Não medem desempenho financeiro. Avaliar a estratégia exige dados disponíveis à época, empresas que deixaram a bolsa, ajustes societários, custos, liquidez, impostos e validação fora da amostra. Comparar com aportes pelas metas, alocação simples, índice apropriado e CDI, medindo retorno, perdas, concentração e giro. Os dados atuais do aplicativo não autorizam reconstruir recomendações históricas sem viés de antecipação.

O [Investor.gov](https://www.investor.gov/introduction-investing/getting-started/asset-allocation) descreve rebalanceamento com novos aportes e diversificação como práticas de gestão da carteira; a alocação depende do prazo e da tolerância a risco de cada pessoa.
