# Plataforma de Investimentos IA · Aporte Brasil

Aplicação local para organizar investimentos, pesquisar empresas, comparar cenários e consultar dados públicos de mercado. A interface em português roda no navegador no Windows e no aplicativo de teste para Android.

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

## Android

O aplicativo roda localmente no Android 7.0 ou superior, em aparelhos ARM64 e emuladores x86-64. A carteira do celular fica no armazenamento privado do aplicativo. A sincronização com o PC e a transferência de dados entre o APK de teste e o futuro APK de distribuição ainda estão pendentes. Use dados fictícios durante os testes.

### Instalar ou atualizar o APK de teste

1. Gere o APK pelo procedimento abaixo ou receba o arquivo `.apk` de quem compilou o projeto.
2. Copie o arquivo para o celular por USB e abra pelo gerenciador de arquivos. Se o Android solicitar, autorize a instalação para esse gerenciador. Depois da instalação, você pode revogar a permissão.
3. Abra **Aporte Brasil (teste)**. Para instalar uma versão nova, abra o novo APK e escolha **Atualizar**. Mantenha o aplicativo anterior instalado para conservar a carteira local.

Para testar pelo cabo USB, ative a depuração USB no aparelho e autorize o computador. Com o `adb` do Android SDK Platform-Tools disponível no terminal, rode na raiz do repositório:

```powershell
adb devices
adb install -r .\android\app\build\outputs\apk\debug\app-debug.apk
```

Use `adb install -r -t` se o pacote foi criado com **Run** no Android Studio e estiver marcado como `testOnly`. Para abrir o arquivo diretamente no celular, prefira o APK gerado por **Generate APK(s)** ou pelo `assembleDebug` no terminal. Se uma atualização falhar por assinatura incompatível, gere o APK com a mesma chave instalada no aparelho. Desinstalar apaga os dados locais do aplicativo.

### Gerar um APK novo

1. Instale o [Android Studio](https://developer.android.com/studio). No **SDK Manager**, instale **Android API 37.0**, **Build-Tools 36.0.0** e **Android SDK Platform-Tools**. Use o JDK do Android Studio para o Gradle.
2. Instale [Python 3.12 para Windows](https://www.python.org/downloads/release/python-31210/). Para descobrir o caminho do executável, rode `py -3.12 -c "import sys; print(sys.executable)"` no PowerShell.
3. Abra a pasta `android` do repositório no Android Studio. Se o Gradle não localizar o Python 3.12, acrescente a linha a seguir em `android/local.properties`, preservando `sdk.dir` e usando o caminho real do executável com barras `/`.

   ```properties
   aporte.buildPython=C:/caminho/para/python.exe
   ```

4. Sincronize o Gradle. Para gerar o arquivo, escolha **Build → Generate Bundle(s) / APK(s) → Generate APK(s)** com a variante `debug`. Para rodar direto, selecione o celular USB ou o emulador e clique em **Run**. A primeira compilação precisa de internet para o Gradle e as dependências do Python.

#### Compilar pelo terminal, sem Android Studio

Instale um JDK compatível com o Gradle 9.3.1 (o build foi testado com Java 25), o Python 3.12 e as [ferramentas de linha de comando do SDK](https://developer.android.com/tools/sdkmanager). Use `sdkmanager` para instalar o SDK da API 37, Build-Tools 36.0.0 e Platform-Tools. Em `android/local.properties`, configure `sdk.dir=C:/caminho/para/Android/Sdk` e, se necessário, `aporte.buildPython` conforme o exemplo acima.

No PowerShell, a partir da raiz do repositório, aponte `JAVA_HOME` para o JDK instalado. O preparo baixa e verifica o JAR oficial do Gradle, que fica fora do Git.

```powershell
$env:JAVA_HOME = "C:\caminho\para\o\jdk"
Set-Location .\android
.\prepare-wrapper.ps1
.\gradlew.bat :app:assembleDebug
```

Se você já instalou o Android Studio, pode usar a pasta `jbr` dele como `JAVA_HOME`.

O APK de teste fica em `android/app/build/outputs/apk/debug/app-debug.apk`. O Gradle inclui o `app.py`, o pacote `aporte_brasil/` e os arquivos da interface em `static/` a cada compilação. Depois de atualizar o código, gere um novo APK para incorporá-lo ao Android.

### Assinatura e atualizações de distribuição

- **Durante o desenvolvimento**, use a variante `debug` (`br.aporte.app.spike`) no mesmo PC. Assim, o Gradle pode reutilizar a chave de depuração. O APK de teste deste projeto mantém o identificador usado pelo protótipo anterior.
- **Para instalar e atualizar no uso pessoal**, gere um APK `release` (`br.aporte.app`) em **Build → Generate Signed App Bundle or APK → APK**. Crie a chave de assinatura uma vez, guarde o arquivo e uma cópia segura fora do repositório e use a mesma chave em todas as atualizações. Aumente `versionCode` em `android/app/build.gradle.kts` a cada release e ajuste `versionName` para a versão visível.
- **Para publicar na Google Play**, gere um `release` no formato **Android App Bundle** (`.aab`) e configure o **Play App Signing**. Guarde a chave de upload fora do Git. Se quiser distribuir o mesmo app também por APK direto, planeje a assinatura antes do primeiro lançamento para manter as atualizações compatíveis entre os dois canais. [Guia de assinatura do Android](https://developer.android.com/studio/publish/app-signing?hl=pt-br).

O Android preserva os dados em atualizações feitas sobre o mesmo identificador de aplicativo, com assinatura compatível. As variantes `debug` e `release` instalam lado a lado e têm carteiras independentes. Referências oficiais: [gerar e assinar builds](https://developer.android.com/studio/publish/app-signing), [regras de atualização](https://developer.android.com/google/play/app-updates) e [instalação com adb](https://developer.android.com/tools/adb).

### Compartilhar com amigos

| Caminho | Quem recebe | Custo e atualização |
| --- | --- | --- |
| **Teste interno da Google Play** | Até 100 testadores por app. Adicione os e-mails na Play Console, publique o `.aab` em **Teste interno** e compartilhe o link de adesão. | Taxa única de **US$ 25** para abrir a conta de desenvolvedor. A instalação é gratuita para os testadores e a Play Store pode atualizar o app conforme as preferências de cada aparelho. [Cadastro](https://support.google.com/googleplay/android-developer/answer/6112435?hl=pt-BR) · [Teste interno](https://support.google.com/googleplay/android-developer/answer/9845334?hl=pt-BR) · [Atualizações automáticas](https://support.google.com/googleplay/answer/113412?hl=pt-BR) |
| **Distribuição limitada fora da Play Store** | Até 20 dispositivos autorizados por convite no **Android Developer Console**. Envie aos convidados o APK `release` assinado. | Conta gratuita. Cada pessoa instala manualmente o novo APK para atualizar. [Distribuição limitada do Android](https://support.google.com/android-developer-console/answer/16640817) |

Para um grupo pequeno que quer atualizações pela loja, comece com upload manual no **Teste interno**. A lista de convidados restringe o acesso pela loja. Mantenha as chaves de assinatura fora do Git e teste com dados fictícios até validar backup e restauração no Android.

### Automatizar a compilação com GitHub Actions

O repositório pode continuar privado. Um fluxo futuro pode compilar uma versão quando você criar uma tag, como `v0.1.0`. No GitHub Free, a franquia inclui **2.000 minutos mensais** em executores padrão e **500 MB** de armazenamento de artefatos. Sem um meio de pagamento válido cadastrado, o uso é bloqueado ao consumir a franquia. [Preços e franquias do GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Se usar GitHub Releases, anexe o APK assinado à release e inclua o SHA-256 gerado com `Get-FileHash -Algorithm SHA256 CAMINHO_DO_APK`. Em um repositório privado, a release segue as permissões de leitura do repositório. Para entregar o APK a amigos sem dar acesso ao código, use um dos canais acima. [Acesso às releases no GitHub](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

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

## Integração com a B3 por arquivo

A importação lê os extratos baixados da Área do Investidor; nada é enviado à B3. A API oficial da Área do Investidor é contratada apenas por empresas licenciadas, por isso o caminho para pessoa física continua sendo o arquivo.

- **Negociação e Movimentação:** compras, vendas, proventos, Tesouro, CDB, LCI e LCA, com prévia antes de salvar.
- **Eventos corporativos da Movimentação:** desdobramento, grupamento, bonificação em ativos e fração retirada para leilão mudam a quantidade sem criar compra ou venda. A prévia mostra a quantidade antes e depois, a proporção e pede confirmação. O desdobramento dilui o preço médio; o grupamento mantém o custo total; a bonificação exige o custo atribuído do fato relevante quando o extrato não o traz; a fração sai pelo preço médio. Se a proporção não bater com o fato relevante, informe a quantidade depois do evento. Leilão de fração, incorporação, cisão e troca de código continuam para revisão manual. Os eventos aparecem no detalhe do ativo e podem ser excluídos.
- **Conferir com o extrato de Posição:** em **Configurações → Importar dados**, envie o Excel de Extratos → Posição. A comparação é somente leitura: mostra por ativo e instituição o que confere, o que difere, o que só existe na B3 ou só na carteira local, com a causa provável (evento não importado, nome de instituição, compra/venda faltante). A carteira é calculada até a data da posição.

- **Atualizar saldos da renda fixa:** no mesmo extrato de Posição (abas Tesouro Direto e Renda Fixa), a tela mostra o que será atualizado e, depois da sua confirmação, grava saldo, data do saldo e vencimento (apenas se estiver vazio) dos produtos que você já tem. Taxa, indexador e imposto não vêm do extrato e não são alterados. Produtos só na B3 são criados apenas se você marcar, com valor investido desconhecido. O formato das colunas foi construído a partir da estrutura conhecida do extrato e ainda precisa ser conferido com um arquivo real.
- **Notas de corretagem (histórico anterior a 11/2019):** a B3 não tem dados anteriores a 01/11/2019. Envie os PDFs de notas SINACOR (ou cole o texto). O app lê os negócios, divide os custos da nota entre eles pelo valor, confere o líquido da nota e pede o ticker de cada nome de ativo (as notas trazem o nome, não o código). Depois segue para a mesma prévia e confirmação da B3. Para PDFs instale `.\.venv\Scripts\python.exe -m pip install pypdf`; PDFs protegidos pedem a senha (normalmente os primeiros dígitos do CPF), usada só para abrir o arquivo. Notas escaneadas como imagem não têm texto e não são lidas. Use a data limite 2019-10-31 para não duplicar o período que a B3 já cobre.
- **Meu Pluggy (opcional):** conector desligado até você usar, para ler investimentos e operações das conexões feitas no Meu Pluggy (Open Finance). Seus dados passam pela Pluggy, só o endereço api.pluggy.ai é contatado, as credenciais não são guardadas e as operações seguem para a prévia com confirmação. A qualidade dos dados varia por instituição.

Backups exportados passam ao formato `aporte-brasil-v7`, que inclui os eventos corporativos; backups anteriores continuam aceitos.

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

## Estrutura do código

`app.py` (servidor e entrada do aplicativo) fica na raiz, junto dos lançadores `.cmd`/`.ps1`. Os demais módulos ficam no pacote `aporte_brasil/`, um subpacote por área:

- `core/`: cofre de dados privados, ciclo de vida do processo, instalador, cache de histórico e notificações.
- `market/`: mercado, notícias, sinais, monitor, contexto de preços, benchmarks e fontes extras.
- `ai/`: análise com IA local e comparação de modelos.
- `company/`: pesquisa e qualidade de empresas e FIIs, fundamentos, valuation, múltiplos e eventos corporativos.
- `portfolio/`: posições, estratégia de aporte, risco, exposição, correlação, longo prazo, tributação, Tesouro e renda fixa.
- `importers/`: importação de B3, CSV, Tesouro, notas de corretagem, pesquisa colada e conector Pluggy.

Novos módulos entram em `aporte_brasil/<área>/` e na lista `MODULES` de `tools/check_git_safety.py`, que é a lista de arquivos permitidos no Git. Os módulos se importam por `from aporte_brasil.<área> import <módulo>`.

O projeto `android/` inicia esse mesmo servidor Python dentro do aplicativo e abre a interface em uma WebView local. O código do Android entra na lista explícita `ANDROID_FILES`. Chaves, APKs, o Wrapper binário e configurações locais são excluídos.

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

## Múltiplos vs. histórico da própria empresa

Para ações e FIIs da B3, o detalhe do ativo, a aba "Preço e valor" do aporte e a página de cenários de preço mostram o múltiplo atual contra a média e a mediana mensais de 3, 5 ou 10 anos, com percentil e desvios-padrão.

- Cada setor destaca os indicadores usuais (por exemplo: bancos P/VP e P/L; energia e saneamento EV/EBITDA e dividend yield; commodities EV/EBITDA; varejo EV/EBITDA, P/L e P/Receita; FIIs P/VP e dividend yield). Dívida líquida/EBITDA aparece como contexto de risco, não como sinal de preço.
- Série mensal: fechamento do mês sem ajuste de proventos (Yahoo, 10 anos) × balanço que já estava divulgado naquela data (ITR 45 dias, DFP 3 meses). Ações usam o número atual de ações implícito no VPA/LPA publicados; FIIs usam o VPA do informe mensal da CVM, corrigido por desdobramentos.
- A leitura usa percentil e mediana; múltiplo abaixo do histórico não prova que a ação está barata. Quando a série observada de P/L ou P/VP é curta, os métodos "P/L histórico" e "P/VP histórico" usam a série reconstruída.
