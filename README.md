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

Em **Recomendar aporte**, informe dinheiro novo e escolha a versão base ou base + contexto. Usa carteira + ativos acompanhados e suas metas por classe, com qualidade documentada, referência de preço, margem de segurança e limites de concentração após as sugestões. Classes sem produto escolhido e valores sem oportunidade ficam a decidir. Consulte [o método e a pesquisa sobre qualidade e contrafluxo](LONGO_PRAZO.md).
