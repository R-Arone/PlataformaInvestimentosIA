"""24-hour news tone and conditional event mechanisms; no causal price predictor."""
from datetime import datetime,timedelta,timezone
import hashlib
import re
from aporte_brasil.portfolio import sector_analysis


def recent(items,clock):
    rows=[];seen=set()
    for row in items:
        try:
            stamp=datetime.fromisoformat(row['published_at'])
            if stamp.tzinfo is None:continue
        except (KeyError,TypeError,ValueError):continue
        if not clock-timedelta(hours=24)<=stamp<=clock:continue
        title=row['title'];suffix=' - '+row.get('publisher','')
        if title.endswith(suffix):title=title[:-len(suffix)]
        key=sector_analysis.fold(title)
        if key in seen:continue
        seen.add(key);rows.append(row)
    return rows


def event(row):
    text=sector_analysis.fold(row['title'])
    name=None;paths=[];watch=[]
    if re.search(r'\b(ministro|ministra|ministerio)\b',text) and re.search(r'renuncia|demissao|deixa.{0,35}(cargo|governo|ministerio)|saida',text):
        name='Mudança no governo'
        paths=[{'condition':'Se a mudança aumentar a incerteza fiscal ou alterar a condução econômica',
                'effect':'Prêmio de risco e juros futuros podem subir; real e ações podem sofrer pressão. A exposição varia por setor.'},
               {'condition':'Se houver continuidade crível ou o substituto reduzir a incerteza',
                'effect':'A reação pode ser limitada ou favorável. Uma saída já esperada pode estar incorporada nos preços.'}]
        watch=['Confirmar comunicado oficial e cargo envolvido','Identificar substituto e eventual mudança de política',
               'Conferir Ibovespa, dólar e curva de juros após a publicação']
    elif re.search(r'\b(fiscal|orcamento|deficit|divida publica|arcabouco)\b',text):
        name='Política fiscal'
        paths=[{'condition':'Se a notícia piorar a expectativa de sustentabilidade fiscal',
                'effect':'Pode elevar prêmio de risco, câmbio e retorno exigido; setores sensíveis a juros podem ser pressionados.'},
               {'condition':'Se melhorar a credibilidade fiscal, com medidas verificáveis',
                'effect':'Pode aliviar prêmio de risco. Tamanho, execução e expectativas anteriores precisam ser comparados.'}]
        watch=['Verificar anúncio oficial e dimensão da medida','Separar proposta de medida aprovada','Conferir câmbio e juros de mercado']
    elif re.search(r'\b(copom|selic|banco central|inflacao|ipca)\b',text):
        name='Juros e inflação'
        paths=[{'condition':'Se a surpresa elevar a trajetória esperada de juros reais',
                'effect':'Pode elevar custo de capital e reduzir valor presente dos fluxos; bancos e exportadores podem reagir de forma diferente.'},
               {'condition':'Se a surpresa reduzir juros esperados sem deterioração da atividade',
                'effect':'Pode favorecer ativos de maior duração e setores ligados ao crédito. O nível já esperado pelo mercado importa.'}]
        watch=['Conferir publicação do BCB/IBGE','Comparar resultado com expectativa anterior','Observar curva futura, não só a Selic atual']
    if not name:return None
    denial=bool(re.search(r'\b(nao|nega|negou|descarta|desmente)\b',text))
    uncertain='?' in text or bool(re.search(r'\b(pode|podem|podera|poderia|possivel|possibilidade|rumor|boato|deve|cogita|especula|preve|projecao|expectativa)\b',text))
    certainty='denial' if denial else 'hypothesis' if uncertain else 'reported'
    identity=sector_analysis.fold(row['title'].removesuffix(' - '+row.get('publisher','')))
    return {'id':hashlib.sha256((name+identity).encode()).hexdigest()[:24], 'kind':name,
            'headline':row,'certainty':certainty,'direction':'mixed','paths':paths,'watch':watch,
            'note':'Evento identificado no título; artigo e fato não foram confirmados automaticamente. Efeitos são condicionais, sem percentual previsto de retorno.'}


def overview(feed,sentiment,clock):
    items=recent(feed.get('headlines',[]),clock)
    classified=recent(sentiment.get('items',[]),clock) if sentiment else []
    # Scores from a different feed must not be presented as a current reading.
    titles={r['title'] for r in items}
    classified=[r for r in classified if r['title'] in titles]
    publishers=len({r['publisher'] for r in classified})
    score=sum(r['score'] for r in classified)/len(classified) if classified else None
    enough=len(classified)>=4 and publishers>=2
    tone=('positive' if score>.15 else 'negative' if score<-.15 else 'neutral') if enough else 'unknown'
    return {'asof':clock.isoformat(),'window_hours':24,'count':len(items),'classified_count':len(classified),
            'publishers':publishers,'score':score,'tone':tone,
            'model':sentiment.get('model') if sentiment else None,
            'analyzed_at':sentiment.get('analyzed_at') if sentiment else None,
            'events':[e for r in items if (e:=event(r))], 'headlines':items,
            'note':'Tom de notícias das últimas 24 horas; exige 4 títulos únicos e 2 veículos para resumir sentimento. Não determina o que acontecerá com a bolsa. Escores do classificador não são probabilidades de alta. Os canais de eventos são regras explícitas, sem previsão causal validada.'}
