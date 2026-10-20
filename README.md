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

Requer Python 3.11 ou superior com suporte a `sqlite3.Connection.serialize` e `deserialize`.

```powershell
git clone https://github.com/R-Arone/PlataformaInvestimentosIA.git
cd PlataformaInvestimentosIA
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --no-browser
```

Abra **http://127.0.0.1:8765**. Na primeira execução, crie uma senha local de pelo menos 12 caracteres. A carteira começa vazia; cadastre seus próprios ativos ou importe seus arquivos pela interface.

No Windows, também é possível usar **Abrir Aporte Brasil.cmd** depois de preparar o ambiente. Consultas de mercado precisam de internet; algumas fontes exigem uma chave própria, configurada nas preferências locais.

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
