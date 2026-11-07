# Plataforma de Investimentos IA · Aporte Brasil

Aplicação local para organizar investimentos, pesquisar empresas, comparar cenários e consultar dados públicos de mercado. Interface em português, executada no navegador com servidor Python no próprio computador.

## Recursos

- Carteira, operações, proventos, posições iniciais e importação de arquivos B3/CSV/Excel.
- Pesquisa de ações, FIIs, ETFs, BDRs, ativos internacionais, fundos e renda fixa.
- Indicadores financeiros, histórico das empresas, critérios por setor, valuation e exposição econômica.
- Tesouro Direto, referências de preços e taxas e simulações de venda antecipada.
- Notícias, cenários, sinais estatísticos e integração opcional com modelos de IA locais.
- Carteira criptografada com senha local, bloqueio de sessão e backups protegidos.

## Executar

Requer Python 3.11 ou superior com suporte a `sqlite3.Connection.serialize` e `deserialize`. No Windows, instale Python uma vez, clone o repositório e clique em **Abrir Aporte Brasil.cmd**. O ambiente `.venv` e as dependências básicas são preparados automaticamente, sem exigir pacotes de IA. A primeira preparação pode precisar de internet. Também é possível preparar manualmente:

```powershell
git clone https://github.com/R-Arone/PlataformaInvestimentosIA.git
cd PlataformaInvestimentosIA
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --no-browser
```

Abra **http://127.0.0.1:8765**. Na primeira execução, crie uma senha local de pelo menos 12 caracteres. A carteira começa vazia; cadastre seus próprios ativos ou importe seus arquivos pela interface.

Consultas de mercado precisam de internet; algumas fontes exigem uma chave própria, configurada nas preferências locais.

## Os 11 critérios adicionais da análise da empresa

Em **Análise da empresa → Análise completa → Os 11 critérios adicionais de longo prazo**, consulte ROE histórico, crescimento, dividendos, inovação, idade da empresa, liderança, idade do setor, blue chip, gestão, independência e dívida histórica.

ROE exige mais de 5% em cada um dos últimos cinco exercícios completos, usando lucro e patrimônio médio de dois encerramentos positivos ou uma série anual conferida. Crescimento exige CAGR de receita **ou** lucro acima de 5% a.a.: seis observações anuais delimitam os cinco intervalos. O histórico de dividendos confirma pagamentos documentados, sem exigir DY mínimo de 5%. A fundação precisa ser anterior ao aniversário de 30 anos; a data de IPO não substitui a fundação.

Setor obsoleto reprova inovação. Histórico comprovado de corrupção reprova gestão, mesmo com avaliação favorável ou registro antigo. Liderança exige a primeira colocação em ranking nacional ou mundial, com medida, escopo, data e fonte; “uma das líderes” não atende. Blue chip exige classificação fundamentada, sem inferência automática por tamanho ou índice. Independência exige ausência de controle estatal **e** de dependência de cliente único. Dívida líquida/EBITDA deve ser estritamente menor que 2× em cada um dos cinco anos, com EBITDA positivo; para financeiras, o múltiplo não é aplicado como filtro genérico e os critérios prudenciais continuam separados.

Use **Conferir informações e fontes** para registrar uma informação qualitativa por vez e **Conferir ROE e dívida por ano** para completar ou corrigir o histórico. Cada registro exige fonte e data ou exercício; as informações qualitativas exigem fundamento. Dados faltantes continuam pendentes. As evidências ficam na carteira local e nos próprios backups, fora do Git. O checklist original continua disponível e os novos critérios também entram na classificação integrada da empresa.

## Seis critérios adicionais para fundos imobiliários

Em **Análise do FII → Análise completa → Seus seis critérios para FIIs**, cada item tem **Editar**, resultado, regra, fonte e data:

- **Localização:** regiões nobres confirmadas por evidência da carteira; cidade e vacância não substituem a análise da localização.
- **Propriedades:** exige imóveis novos **e** ausência de manutenção excessiva, sem presumir um limite universal de idade ou despesas.
- **P/VP:** abaixo de 1× atende ao desconto; de 1× até 1,5× não atende. **Acima de 1,5× aciona descarte na triagem**, com aviso no selo e na lista de FIIs. Exatamente 1,5× não aciona o descarte. A regra fixa prevalece sobre os demais critérios e não executa operações.
- **Dividendos:** consistência mensal por mais de quatro anos: 49 meses completos com pagamentos positivos confirmados, ou conferência documental do intervalo e da regularidade. Amortizações, datas ex e eventos estimados não comprovam os pagamentos. Falta de coleta fica pendente.
- **Dependência:** exige conferir separadamente inquilinos/grupos econômicos e imóveis. Vários prédios não comprovam vários inquilinos. Um imóvel com 100% da receita divulgada reprova o critério.
- **Setor e yield:** compara DY do fundo com média aritmética de ao menos dois outros FIIs do mesmo tipo **e** segmento, na mesma data-base e janela de pagamentos de 12 meses. A fonte deve identificar a população ou amostra. DY patrimonial mensal e mediana não substituem essa média; a lista pessoal de acompanhamento não vira automaticamente média do mercado.

Papel e fundos de fundos mantêm os critérios de crédito e fundos investidos; os três critérios de imóveis físicos ficam como não aplicáveis. Perfil desconhecido e dados sem evidência permanecem pendentes. P/VP usa referência de até sete dias; yield comparável, até 31 dias; informações qualitativas, até 180 dias. As conferências ficam na carteira e nos backups locais, fora do repositório.

## Receber atualizações de código

Na pasta clonada, execute:

```powershell
git pull --ff-only
```

Depois clique em **Abrir Aporte Brasil.cmd** ou em **Reiniciar Aporte Brasil.cmd** (opção 1). Ambos encerram a instância anterior de forma normal e carregam o código atualizado. O botão de reinício dentro da interface também passa pelo preparador de ambiente. Se as dependências básicas mudaram, a atualização é feita no ambiente local antes de abrir. Se nada mudou, não há nova instalação de pacotes. Uma tarefa ativa pode impedir o reinício normal; conclua-a primeiro. Use o encerramento forçado apenas quando o aplicativo estiver travado.

Cada usuário mantém sua própria carteira e senha em `%LOCALAPPDATA%\AporteBrasil\data`. Clonar, atualizar o código ou reiniciar não importa a carteira do autor nem substitui a carteira existente do usuário. Cada instalação abre o arquivo local já existente e pede sua senha; uma instalação sem carteira começa vazia. As migrações de formato continuam sendo tratadas pelo aplicativo, com os backups previstos, sem publicar esses arquivos.

O autor publica alterações de código com `git commit` e `git push`, após as verificações de privacidade. Os outros usuários recebem essas alterações com `git pull`. Não compartilhe a pasta privada nem copie a carteira do autor junto com o projeto. Se o usuário já utiliza uma cópia antiga da plataforma no mesmo Windows, a pasta privada padrão continua sendo a mesma. Para trocar de computador, use o backup criptografado da própria carteira pela interface.

## IA opcional

As dependências básicas permitem abrir a aplicação sem instalar os modelos de IA. Para os recursos que utilizam os pacotes Python opcionais:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Modelos, pesos e caches são obtidos e configurados separadamente. Integrações com Ollama/llama.cpp dependem de um serviço local configurado pelo usuário. Dados ausentes e limitações das análises são indicados na interface; os resultados não executam operações financeiras.

## Privacidade desta distribuição

Este repositório contém código e testes com dados sintéticos. Não inclui bancos de dados, carteiras, listas pessoais de acompanhamento, operações, chaves de API, backups, extratos, planilhas, capturas de tela, relatórios locais ou resultados de pesquisa. Os tickers presentes no código são referências públicas de mercado ou exemplos de teste, sem posições pessoais associadas.

No Windows, os dados da aplicação ficam por padrão em `%LOCALAPPDATA%\AporteBrasil\data`, fora da pasta do código. A senha não é enviada ao GitHub. Consulte [SECURITY.md](SECURITY.md) para entender a proteção e seus limites.

O conjunto de dados do comparativo histórico experimental não é distribuído; esse painel informa que está indisponível. Ensaios e testes dependentes das bases de pesquisa locais também ficam fora desta distribuição.

O script `packaging/Install.ps1` foi excluído porque o Windows impediu sua leitura e revisão. A geração de instalador fica indisponível nesta distribuição. Use a execução Python descrita acima.

## Publicar alterações com segurança

```powershell
git config core.hooksPath .githooks
python tools/check_git_safety.py
python tools/check_git_safety.py --history --ref HEAD
```

O `.gitignore` exclui dados, documentos, imagens, arquivos de ambiente e artefatos gerados. Os hooks verificam uma lista permitida de código, assinaturas de bancos e arquivos binários, credenciais reconhecíveis, e-mails pessoais e caminhos de usuário. O pre-push confere os caminhos de todos os commits das referências enviadas, incluindo arquivos posteriormente removidos.

Não adicione dados reais ao código, aos testes, aos commits ou às issues. A revisão automática é uma camada adicional e não substitui a revisão manual de conteúdo. Para separar uma nova cópia do código aprovado de uma instalação com dados locais, use `python tools/export_source.py CAMINHO_DE_UMA_PASTA_VAZIA`.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Os testes usam carteiras temporárias e registros sintéticos. Recursos opcionais de IA podem exigir suas dependências para testes específicos. Arquivos temporários e registros dos testes não fazem parte do repositório.

## Recomendação do próximo aporte

Em **Recomendar aporte**, informe dinheiro novo e escolha entre qualidade/desconto pelas metas e **Oportunidades de alta · ignorar balanceamento**. O segundo estilo prioriza sinais de mercado mesmo em classes acima da meta e funciona sem metas cadastradas. Usa carteira + ativos acompanhados; os limites por emissor/setor e os filtros documentados de qualidade de ações/FIIs continuam valendo.

Escolha **Sem IA** ou **Com IA**. Com modelos locais válidos, a IA passa a influenciar a nota, a ordem e os valores sugeridos; **O que a IA mudou?** compara o resultado com e sem os modelos. **Atualizar IA local e recomendar** busca histórico público e calcula os modelos locais de preços para ações brasileiras, com progresso. Sem modelos válidos, a tela informa que usou apenas as regras sem IA. ETFs, FIIs, BDRs e Bitcoin podem usar indicadores de mercado no modo de alta, sem receber previsões de empresa inventadas. Os modelos de 1, 5 ou 20 pregões são experimentais e não projetam o retorno de vários anos. Consulte [método, fontes e limites](LONGO_PRAZO.md).

## Contrafluxo para o próximo aporte

A tela **Recomendar aporte** começa em **Contrafluxo · qualidade e quedas**. **Atualizar bolsa e dólar** consulta o Ibovespa e o dólar BCB, com fonte, data e retornos em diferentes janelas, e recalcula o aporte informado. Uma queda relevante da bolsa pode priorizar ações acompanhadas de qualidade abaixo do teto; uma queda do dólar indica estudar os produtos relacionados ao exterior que já estão na seleção. Uma queda isolada não comprova preço barato.

O painel separa ideias de mercado, produtos aprovados nos filtros e valores efetivamente sugeridos. Mantém limites de concentração, mínimo por compra e poucos destinos, sem exigir rebalancear tudo neste mês. Sem produto aprovado, o dinheiro fica a decidir. Ações/FIIs preservam filtros de qualidade e preço; ETFs amplos cobertos têm regra própria, sem nota de empresa inventada. Sem sinais ou dados suficientes, a razão fica explícita. O modo de alta e as estratégias anteriores continuam disponíveis. Consulte [fontes, cortes e limites do método](LONGO_PRAZO.md).

## ETFs por área e aportes com poucos destinos

A plataforma identifica áreas publicadas dos ETFs e mostra onde já existe posição e onde há apenas acompanhamento. DEBB11 aparece como debêntures / crédito privado; ABTC11 combina Bitcoin e renda fixa com pesos variáveis, sem presumir exposição integral a Bitcoin. A categoria do produto para metas pode ser ajustada manualmente; essa escolha não cria pesos da composição.

A tela inicia em **Contrafluxo**, com até dois destinos e mínimo por compra ajustável (inclusive zero). **Poucos destinos** continua disponível para qualidade/desconto pelas metas. Compare um, dois, três destinos e a divisão proporcional. As metas por classe podem ficar temporariamente desequilibradas; limites por emissor e setor continuam obrigatórios. As classes abaixo da meta aparecem para revisão no próximo aporte, sem agendar compras ou prever preços. O método completo e as fontes estão em [LONGO_PRAZO.md](LONGO_PRAZO.md).

## Navegação por tarefa

O menu principal reúne seis áreas:

- **Início:** resumo do patrimônio e atalhos para o próximo passo.
- **Carteira:** posições, operações e proventos; diversificação fica em detalhes.
- **Analisar ativos:** uma lista de ações, FIIs, ETFs, Bitcoin e exterior, com filtros e uma análise por ativo. O comparador mostra os mesmos dados lado a lado, sem outro ranking de aporte.
- **Aportar:** um único fluxo para sugerir dinheiro novo. Metas e limites são configuração; destinos, critérios e comparação de divisões ficam em opções recolhidas. Simuladores continuam acessíveis nesta área.
- **Mercado:** notícias e contexto; modelos de IA, cenários, pesquisa externa e alertas são ferramentas complementares.
- **Configurações:** preferências, backup, importação, fontes e restauração de registros removidos.

Os antigos links de stocks dos EUA e de outras bolsas levam à mesma lista filtrada. Os demais links especializados continuam funcionando dentro da área correspondente. A organização da interface não altera posições, operações, indicadores salvos, critérios ou cálculos do recomendador.

Na barra superior, **Bloquear carteira** continua disponível diretamente. **Reiniciar aplicativo** e **Encerrar aplicativo** ficam no menu **Aplicativo**. Na sugestão de aporte, controles de modelos aparecem junto da opção Com IA; demais ajustes ficam recolhidos.


## Notas visíveis, análise em lote e cenário atual

Carteira e Analisar ativos voltam a mostrar nota de qualidade, preço de referência aplicável e fatores associados. **Analisar todos os ativos** executa uma rodada com avaliação própria de empresas, FIIs e ETFs, mostrando pendências por produto. Em Mercado, **Analisar todos os setores** permite consultar o catálogo inteiro ou apenas os setores acompanhados, com notícias, indicadores e interpretação opcional por IA local com fontes.

Em Aportar, **Atualizar indicadores** inclui juros brasileiros e americanos, inflação e commodities com data e frequência. **Analisar cenário atual** traz a leitura setorial para revisar o aporte. A pesquisa ampliada depende da chave de busca configurada e não envia posições ou valores. O contexto não altera automaticamente os pesos da alocação; a influência numérica dos modelos de preços é mostrada separadamente.

O dossiê da empresa inclui relações com atrasos fixos, comparações descritivas de subida/queda, amostras e intervalos, sem selecionar o atraso mais favorável. Veja [método e limitações](LONGO_PRAZO.md).


## Valor, setores e acessibilidade

A lista e o aporte exibem **Barato com margem**, **Caro pelas premissas**, **Perto do valor estimado**, desconto sem margem ou valor inconclusivo, usando o método prioritário adequado ao negócio. FIIs mostram desconto/prêmio patrimonial; ETFs não recebem valor justo de empresa. As notas estruturais de setor são premissas qualitativas explicadas, separadas da qualidade da empresa.

O contrafluxo fundamental passa a combinar 35% qualidade, 25% valor/desconto, 15% queda observada, 5% necessidade da classe, 10% setor e 10% diversificação. Considera os grupos setoriais equivalentes que já existem na carteira, produtos relacionados e pares com histórico comparável; o próximo destino reconsidera as compras já propostas. Mostra os pesos por setor antes/depois, preservando os limites sobre o dinheiro efetivamente investido. Sem histórico, a nota de correlação é neutra e a cobertura é informada. Veja o [método e as limitações](LONGO_PRAZO.md).

Em **Configurações → Cores e acessibilidade**, ative o modo daltônico: ciano para positivos, roxo para negativos, incluindo correlações e gráficos, com sinais e rótulos preservados. A preferência fica salva no banco local.


## Preenchimento geral de dados e origem da pesquisa

Use **Completar dados das empresas** na lista ou **Completar dados faltantes** no checklist. O fluxo consulta os históricos públicos e pode pesquisar os campos restantes com IA local e busca configurada. Propostas têm trecho, fonte e período; podem ser editadas e revisadas em lote antes de entrar nos critérios. A marca **✦ Pesquisa IA** distingue origem revisada e alterações suas. Registros manuais são preservados e fontes indisponíveis continuam sinalizadas.

A qualidade destaca os critérios comprovados sobre o total aplicável, junto da cobertura: sem dados e critério negativo são situações diferentes. A prioridade de aporte mantém a base conservadora e os bloqueios. Nos fatores associados, positivo/negativo têm cores próprias; ausência de evidência fica neutra. O modo daltônico usa **ciano e roxo**, incluindo gráficos e correlações. Veja [método, fontes e limitações](LONGO_PRAZO.md).

## Aporte explicado e posições para revisar

Os cartões de Aportar ficam compactos, com quatro áreas clicáveis: queda, preço/valor, qualidade e setor/carteira. Os detalhes mostram indicadores, fórmula, premissas, fontes, dados faltantes e critérios individuais. **Investidor10** abre diretamente a página da ação, FII ou ETF brasileiro. Queda e valor fundamental são avaliados separadamente; falta de referência continua explícita.

Em **Início** e **Carteira**, **Posições para revisar** reúne reprovações atuais, critérios perdidos desde o início do acompanhamento local e alertas de preço pelas premissas salvas. Mudança de regra e falta de dados têm tratamentos distintos. Preço muito acima dos modelos exige ao menos duas famílias aplicáveis com entradas conferíveis; bases limitadas ficam identificadas. FIIs preservam a regra própria de P/VP acima de 1,5. O painel ajuda a revisar manutenção ou redução, sem executar vendas. Veja [regras e limites](LONGO_PRAZO.md).

## Escolher o cálculo e preencher perguntas

Em **Aportar → Está barato?**, escolha Automático, Bazin, Graham ou outro método disponível para a ação, preencha os valores e salve. A referência e o teto ficam visíveis no cartão e entram na nova simulação. Há média/mediana histórica de P/L e P/VP quando existe uma amostra suficiente de múltiplos datados; cotação antiga isolada não vira valor justo.

**Preencher automaticamente** consulta fontes públicas e, quando configurada, a busca com IA. O cadastro CVM completa constituição jurídica e controle por CNPJ confirmado na B3; sugestões interpretativas vêm com trecho, fonte e marca ✦ para revisão em lote. Campos existentes são preservados.

**Configurações → Ollama · pesquisa e análises** permite detectar modelos, escolher o modelo local e cadastrar a chave do Ollama Web Search. A análise roda pela conexão local; a busca na internet exige a chave da conta Ollama. As notas e os modelos estatísticos mantêm seus próprios cálculos. Veja [métodos e limitações](LONGO_PRAZO.md).


## Integrações, cobertura e cenários no aporte

**Integrações**, na barra superior, abre diretamente a configuração do Ollama, modelo local, chave de busca web e estado das fontes. A internet usa o Ollama Web Search / Web Fetch; a análise usa a conexão local configurada.

A qualidade passa a destacar **critérios comprovados / total**, com cobertura e contagens separadas de atendidos, reprovados e sem informação. Três positivos em vinte critérios mostram **3/20 comprovados, cobertura 15%, análise inconclusiva**, sem sugerir 100% de segurança.

**De que o negócio depende?** pesquisa por IA segmentos, crédito PF/PJ/agro, receitas, custos, dívida e insumos com fontes. Propostas operacionais podem ser editadas e revisadas; só as revisadas ponderam o contexto, independentemente da correlação da ação.

Em Aportar, **Fundamentos + contexto econômico** e **Cenário de IA + fundamentos** ficam separados das regras e dos modelos de preços. A opção de cenário permite criar ou escolher uma hipótese salva, ajustar o peso e conferir a mudança da prioridade. Indicadores antigos ou exposições não revisadas não recebem pontos. Os filtros de compra e limites da carteira continuam. Veja [método, fontes e limites](LONGO_PRAZO.md).
