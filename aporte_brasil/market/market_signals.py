"""Fixed Chronos-2 inference and small chronological, incremental softmax models.

Weights and observations are JSON in the encrypted application cache, never pickle.
Opening the UI never downloads a model, fetches prices or trains anything.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import statistics
import threading
from pathlib import Path

from aporte_brasil.portfolio.portfolio_coupling import completed_prices
from aporte_brasil.market import us_market
from aporte_brasil.market import bayesian_signals
from aporte_brasil.core import history_cache

MODEL_ID = 'amazon/chronos-2'
MODEL_REVISION = '29ec3766d36d6f73f0696f85560a422f50e8498c'
HORIZONS = (1, 5, 20)
FEATURES = ('Retorno 1 pregão', 'Retorno 5 pregões', 'Retorno 20 pregões',
            'Distância da média 50', 'Média 20 versus 50', 'Volatilidade',
            'Força dos pares em 5 pregões', 'Pares disponíveis',
            'Sentimento recente', 'Sentimento disponível', 'Juros observados', 'Juros disponíveis')
VERSION = 2
MIN_TRAIN = 100
LOCK = threading.RLock()
PIPE_LOCK = threading.Lock()
PIPE = None
PIPE_CACHE = None
JOB = {'running': False, 'id': '', 'progress': '', 'error': '', 'finished_at': None}
METHOD = ('Três leituras experimentais, dados diários de pregões encerrados: B3 em BRL, EUA em USD. Chronos-2 é geral, não especializado em ações americanas; usa pesos fixos '
          'e quantis 10/50/90 de log-preços; a faixa não tem cobertura validada nos mercados acompanhados. '
          'O modelo incremental é regressão logística multiclasse com atualização por gradiente, '
          'uma passagem cronológica; só aprende após o horizonte se realizar. '
          'Faixa de estabilidade: ±0,35 × volatilidade diária × raiz do horizonte. '
          'Escores são experimentais e não são chances calibradas de alta. '
          'O bayesiano é uma regressão dinâmica normal/inversa-gama com preditores defasados e distribuição preditiva Student-t; não reproduz o modelo M6. '
          'Atualiza coeficientes e variância por desconto 0,995 a cada resultado de treino; usa alvos sem sobreposição e pelo menos 40 exemplos. '
          'Probabilidades de baixa/estabilidade/alta são estimativas não calibradas; a banda usa a volatilidade observada na origem, com piso diário 0,3%, e não a variância. '
          'Correlações de 60 retornos sofrem regularização para zero. Referências de outros setores vêm da lista atual no mesmo mercado, não de índices oficiais. '
          'Brier comparável ao incremental usa as mesmas origens, classes e bandas; os dados de treino dos dois modelos diferem. '
          'O intervalo bayesiano de 80% inclui ruído e incerteza dos coeficientes. Não há distribuição conjunta futura da carteira. '
          'Pares são da lista atual, uma classe por emissor; há viés de seleção na simulação histórica. '
          'Notícias e juros só entram nas observações gravadas daqui em diante, quando disponíveis. '
          'Pares dos EUA são separados dos brasileiros. Sentimento americano usa FinBERT-Tone em inglês; Selic não é usada como juro dos EUA. '
          'Não há fluxo de ordens nem curva futura neste modelo. Nenhuma ordem é executada.')


def is_equity(asset):
    return asset.get('asset_type') in ('stock', 'foreign')


def signal_prices(asset, day, stamp):
    return us_market.native_prices(asset, day, stamp) if asset.get('asset_type') == 'foreign' else completed_prices(asset, day, stamp)


def issuer(asset):
    if asset.get('asset_type') == 'foreign':
        return asset.get('snapshots', {}).get('us_quote', {}).get('data', {}).get('issuer') or asset['ticker']
    return asset['ticker'][:4]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def signature(points, peers, through):
    return digest([[(d, v) for d, v in points.items() if d <= through],
                   [[(d, v) for d, v in p.items() if d <= through] for p in peers]])


def probabilities(weights, features):
    logits = [sum(w*x for w, x in zip(row, [1., *features])) for row in weights]
    exp = [math.exp(max(-60, v-max(logits))) for v in logits]
    return [p/sum(exp) for p in exp]


def features_at(points, peers, i, context=None):
    dates, prices = list(points), list(points.values())
    past = prices[:i+1]
    rr = [math.log(b/a) for a, b in zip(past[-21:], past[-20:])]
    vol = max(.003, statistics.stdev(rr))
    mean20, mean50 = statistics.mean(past[-20:]), statistics.mean(past[-50:])
    ret = lambda h: math.log(past[-1]/past[-1-h])/(vol*math.sqrt(h))
    peer_returns = [math.log(p[dates[i]]/p[dates[i-5]])/(vol*math.sqrt(5))
                    for p in peers if dates[i] in p and dates[i-5] in p]
    c = context or {}
    raw = [ret(1), ret(5), ret(20), math.log(past[-1]/mean50)/(vol*math.sqrt(50)),
           math.log(mean20/mean50)/(vol*math.sqrt(20)), vol*math.sqrt(252)/.3,
           statistics.mean(peer_returns) if len(peer_returns) >= 2 else 0., float(len(peer_returns) >= 2),
           c.get('sentiment', 0.), float('sentiment' in c), c.get('rates', 0.), float('rates' in c)]
    return [max(-4., min(4., x)) for x in raw], vol


def fresh_context(asset, state, origin, day):
    context = {}
    if asset.get('asset_type') == 'foreign':
        sentiment = asset.get('us', {}).get('sentiment', {})
        if sentiment and not sentiment.get('stale') and sentiment.get('tone') != 'unknown' and sentiment.get('score') is not None:
            context['sentiment'] = sentiment['score']
        return context
    profile = asset['sector_analysis']['profile']
    sentiment = state.get('ai', {}).get('sentiment', {}).get(profile, {})
    if sentiment and not sentiment.get('stale') and sentiment.get('score') is not None and (day-date.fromisoformat(origin)).days <= 4:
        context['sentiment'] = sentiment['score']
    obs = state.get('news_reports', {}).get(profile, {}).get('macro_context', {}).get('observations', {}).get('rates')
    if obs and not obs.get('stale') and obs['asof'] <= day.isoformat() and 0 <= (day-date.fromisoformat(obs['asof'])).days <= 7:
        context['rates'] = {'up': 1., 'down': -1., 'flat': 0.}.get(obs['direction'], 0.)
    return context


def new_model():
    return {'version': VERSION, 'weights': [[0.]*(len(FEATURES)+1) for _ in range(3)],
            'trained': 0, 'counts': [0, 0, 0], 'pending': [], 'seen_date': '', 'history_hash': '',
            'metrics': {k: {'count': 0, 'brier': 0., 'baseline_brier': 0., 'correct': 0}
                        for k in ('simulated', 'live')}}


def update_model(points, peers, horizon, previous=None, context=None, forecasts=None):
    model = json.loads(json.dumps(previous)) if previous else new_model()
    reset = False
    if model.get('version') != VERSION or model.get('seen_date') and signature(points, peers, model['seen_date']) != model.get('history_hash'):
        model, reset = new_model(), True
    dates, prices = list(points), list(points.values())
    locations = {d: i for i, d in enumerate(dates)}
    if forecasts is not None:
        forecasts.update({p['date']: json.loads(json.dumps(p)) for p in model['pending']})
    for i in range(63, len(prices)):
        if dates[i] <= model['seen_date']:
            continue
        remaining = []
        for pending in model['pending']:
            start = locations[pending['date']]
            if start+horizon > i:
                remaining.append(pending)
                continue
            # Only later calendar sessions count as prospective. For delayed
            # quotes (or a same-day target), learn from the historical price
            # features alone, never from news collected after that origin.
            historical_only = False
            if pending.get('generated_at'):
                target_session = datetime.fromisoformat(dates[start+horizon]).replace(
                    tzinfo=timezone(timedelta(hours=-3)))
                historical_only = target_session <= datetime.fromisoformat(pending['generated_at'])
            realized = math.log(prices[start+horizon]/prices[start])
            label = 2 if realized > pending['band'] else 0 if realized < -pending['band'] else 1
            if pending['eligible'] and not historical_only:
                metric = model['metrics']['live' if pending['live'] else 'simulated']
                metric['count'] += 1
                metric['brier'] += sum((p-(j == label))**2 for j, p in enumerate(pending['probabilities']))
                metric['baseline_brier'] += sum((p-(j == label))**2 for j, p in enumerate(pending['baseline']))
                metric['correct'] += int(max(range(3), key=lambda j: pending['probabilities'][j]) == label)
            features = list(pending['features'])
            if historical_only:
                features[8:12] = [0., 0., 0., 0.]
            x = [1., *features]
            p = probabilities(model['weights'], features)
            rate = .04/math.sqrt(1+model['trained']/200)
            for j, row in enumerate(model['weights']):
                for k in range(len(row)):
                    row[k] += rate*((int(j == label)-p[j])*x[k]-.001*row[k])
            model['trained'] += 1
            model['counts'][label] += 1
        model['pending'] = remaining
        x, vol = features_at(points, peers, i, context if i == len(prices)-1 else None)
        p = probabilities(model['weights'], x)
        baseline = [(n+1)/(model['trained']+3) for n in model['counts']]
        model['pending'].append({'date': dates[i], 'features': x, 'band': .35*vol*math.sqrt(horizon),
                                 'probabilities': p, 'baseline': baseline, 'eligible': model['trained'] >= MIN_TRAIN,
                                 'live': i == len(prices)-1,
                                 'generated_at': (context or {}).get('_generated_at') if i == len(prices)-1 else None})
        if forecasts is not None:
            forecasts[dates[i]] = json.loads(json.dumps(model['pending'][-1]))
        model['seen_date'] = dates[i]
    model['history_hash'] = signature(points, peers, model['seen_date'])
    latest = model['pending'][-1] if model['pending'] else None
    # New news can arrive after a price forecast on the same completed close.
    # Refresh that pending forecast only; never learn its still-unrealized label.
    if latest and context is not None:
        refreshed, vol = features_at(points, peers, len(prices)-1, context)
        if refreshed != latest['features']:
            latest.update(features=refreshed, probabilities=probabilities(model['weights'], refreshed),
                          generated_at=context.get('_generated_at'), live=True)
    if latest and forecasts is not None:
        forecasts[latest['date']] = json.loads(json.dumps(latest))
    ready = model['trained'] >= MIN_TRAIN
    scores = latest['probabilities'] if latest else [1/3]*3
    winning = max(range(3), key=lambda j: scores[j])
    direction = ('unfavorable', 'neutral', 'favorable')[winning] if ready and max(scores) >= .45 else 'mixed' if ready else 'unknown'
    evaluations = {}
    for kind, m in model['metrics'].items():
        n = m['count']
        evaluations[kind] = {'count': n, 'brier': m['brier']/n if n else None,
                             'baseline_brier': m['baseline_brier']/n if n else None,
                             'accuracy': m['correct']/n*100 if n else None}
    return model, {'status': 'ready' if ready else 'learning', 'direction': direction,
                   'score': (scores[2]-scores[0])*100 if ready else None,
                   'trained': model['trained'], 'minimum': MIN_TRAIN, 'reset': reset,
                   'evaluations': evaluations, 'context_available': {'sentiment': bool(latest and latest['features'][9]),
                                                                   'rates': bool(latest and latest['features'][11])}}


def load_chronos(cache_dir):
    global PIPE, PIPE_CACHE
    cache_dir = Path(cache_dir).resolve()
    with PIPE_LOCK:
        if PIPE is not None and PIPE_CACHE == str(cache_dir):
            return PIPE
        try:
            import torch
            from chronos import Chronos2Pipeline
        except ImportError:
            raise ValueError('Chronos-2 ainda não está disponível neste Python. Prepare os pacotes de IA ou use o lançador atualizado.') from None
        cache_dir.mkdir(parents=True, exist_ok=True)
        torch.set_num_threads(min(4, torch.get_num_threads()))
        try:
            PIPE = Chronos2Pipeline.from_pretrained(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache_dir),
                                                   device_map='cpu', trust_remote_code=False,
                                                   use_safetensors=True, local_files_only=True)
        except OSError:
            try:
                PIPE = Chronos2Pipeline.from_pretrained(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache_dir),
                                                       device_map='cpu', trust_remote_code=False, use_safetensors=True)
            except Exception:
                raise ValueError('Não foi possível obter o Chronos-2. O primeiro uso baixa cerca de 480 MB; confira a conexão. O incremental continua disponível.') from None
        PIPE_CACHE = str(cache_dir)
        return PIPE


def pretrained(points, peers, cache_dir):
    pipeline = load_chronos(cache_dir)
    import numpy as np
    dates, prices = list(points)[-512:], list(points.values())[-512:]
    target = np.array([math.log(v/prices[-1]) for v in prices], dtype=np.float32)
    payload = {'target': target}
    usable = [p for p in peers if all(d in p for d in dates)]
    if len(usable) >= 2:
        payload['past_covariates'] = {'pares_setor': np.array([
            statistics.mean(math.log(p[d]/p[dates[-1]]) for p in usable) for d in dates], dtype=np.float32)}
    with PIPE_LOCK:
        q, _ = pipeline.predict_quantiles([payload], prediction_length=max(HORIZONS),
                                         quantile_levels=[.1, .5, .9], batch_size=8)
    rows = {}
    for h in HORIZONS:
        values = [float(v) for v in q[0][0, h-1].tolist()]
        if not all(math.isfinite(v) and abs(v) < 10 for v in values) or values != sorted(values):
            raise ValueError('Chronos-2 retornou uma faixa inválida; resultado descartado.')
        lo, mid, hi = [(math.exp(v)-1)*100 for v in values]
        direction = 'favorable' if lo > 0 else 'unfavorable' if hi < 0 else 'mixed'
        rows[str(h)] = {'status': 'ready', 'direction': direction, 'median_return': mid,
                        'low_return': lo, 'high_return': hi, 'sector_peers': len(usable)}
    return rows


def history_requirements(points):
    """Cold-start requirements, distinct from retained posterior observations."""
    return {'count': len(points), 'start': next(iter(points), None),
            'end': next(reversed(points), None),
            'bayesian': {str(h): {'minimum_closes': bayesian_signals.START+1+bayesian_signals.MIN_TRAIN*h,
                'missing_closes': max(0, bayesian_signals.START+1+bayesian_signals.MIN_TRAIN*h-len(points))}
                for h in HORIZONS}}


def public_state(app, c, assets):
    saved = app.read_cache(c, 'market_signal_results', {})
    all_points = {a['ticker']: signal_prices(a, app.today(), app.now()) for a in assets if is_equity(a)}
    rows = []
    for a in assets:
        if not is_equity(a):
            continue
        r = saved.get(a['ticker'])
        if r:
            r = json.loads(json.dumps(r))
            points = all_points[a['ticker']]
            peers = sector_peers(a, assets, all_points)
            factors = market_factors(a, assets, all_points)
            r['stale'] = (not points or r['asof'] != next(reversed(points)) or app.age(r['asof']) > 7
                          or r['price_hash'] != digest(points) or r.get('profile') != a['sector_analysis']['profile']
                          or r.get('status') == 'ready' and (r.get('peer_hash') != digest(peers)
                              or r.get('factor_hash') != digest(factors)
                              or r.get('bayesian_version') != bayesian_signals.VERSION))
        r = r or {'ticker': a['ticker'], 'status': 'unknown', 'reason': 'Ainda não analisado.', 'horizons': {}, 'stale': False,
                  'market': 'US' if a['asset_type']=='foreign' else 'BR'}
        r['history'] = history_requirements(all_points[a['ticker']])
        rows.append(r)
    return {'rows': rows, 'job': job_state(), 'method': METHOD, 'model_id': MODEL_ID,
            'revision': MODEL_REVISION, 'horizons': list(HORIZONS)}


def job_state():
    with LOCK:
        return dict(JOB)


def progress(message):
    with LOCK:
        JOB['progress'] = message


def sector_peers(asset, assets, all_points):
    peers, issuers = [], {issuer(asset)}
    for other in assets:
        if other['asset_type'] == asset['asset_type'] and other['sector'] == asset['sector'] and issuer(other) not in issuers:
            peers.append(all_points[other['ticker']]); issuers.add(issuer(other))
    return peers


def market_factors(asset, assets, all_points):
    """Other sectors in this watchlist/market, one series per issuer."""
    factors, issuers = {}, {issuer(asset)}
    for other in assets:
        if (other['asset_type'] == asset['asset_type'] and other['sector'] != asset['sector']
                and issuer(other) not in issuers and all_points.get(other['ticker'])):
            factors.setdefault(other['sector'], []).append(all_points[other['ticker']])
            issuers.add(issuer(other))
    return {name: factors[name] for name in sorted(factors)}


def analyze(app, inputs):
    state = app.state()
    stocks = [a for a in state['assets'] if is_equity(a) and (not inputs.get('ticker') or a['ticker'] == inputs['ticker'])
              and (not inputs.get('market') or a['asset_type'] == ('foreign' if inputs['market']=='US' else 'stock'))]
    stocks = stocks[:40]
    all_points = {a['ticker']: signal_prices(a, app.today(), app.now()) for a in state['assets'] if is_equity(a)}
    with app.connect() as c:
        stored = app.read_cache(c, 'market_signal_models', {})
        previous = app.read_cache(c, 'market_signal_results', {})
    for n, a in enumerate(stocks):
        ticker = a['ticker']
        progress(f'{ticker} · {n+1}/{len(stocks)} · aprendendo com pregões encerrados…')
        points = all_points[ticker]
        base = {'ticker': ticker, 'profile': a['sector_analysis']['profile'], 'analyzed_at': app.now(),
                'asof': next(reversed(points)) if points else None, 'price_hash': digest(points),
                'source': a.get('snapshots', {}).get('us_history' if a['asset_type']=='foreign' else 'history', {}).get('source', ''),
                'currency': 'USD' if a['asset_type']=='foreign' else 'BRL', 'market': 'US' if a['asset_type']=='foreign' else 'BR', 'horizons': {}, 'stale': False}
        if len(points) < 84 or app.age(base['asof']) > 7:
            base.update(status='unknown', reason='Precisa de pelo menos 84 fechamentos ajustados recentes. Atualize o histórico da ação.')
        else:
            peers = sector_peers(a, state['assets'], all_points)
            factors = market_factors(a, state['assets'], all_points)
            context = fresh_context(a, state, base['asof'], app.today())
            base.update(status='ready', reason='', peer_count=len(peers), context=dict(context),
                        factor_hash=digest(factors), bayesian_version=bayesian_signals.VERSION)
            context['_generated_at'] = base['analyzed_at']
            updates = {}
            bayesian_features = {}
            for h in HORIZONS:
                key = ticker+':'+str(h)
                forecasts = {}
                updates[key], incremental = update_model(points, peers, h, stored.get(key), context, forecasts)
                bayes_key = ticker+':bayes:'+str(h)
                old_bayes = stored.get(bayes_key)
                if stored.get(key) and not incremental['reset'] and (not old_bayes
                        or old_bayes.get('version') != bayesian_signals.VERSION
                        or old_bayes.get('history_hash') != bayesian_signals.signature(
                            points, peers, factors, old_bayes.get('seen_date',''))):
                    # Reconstruct a price-only chronological comparator for a
                    # new/rebuilt Bayesian history. Keep the actual saved
                    # forecasts where present and preserve the live learner.
                    replay = {}
                    update_model(points, peers, h, forecasts=replay)
                    replay.update(forecasts)
                    forecasts = replay
                updates[bayes_key], bayesian = bayesian_signals.update_model(
                    points, peers, factors, h, stored.get(bayes_key), context, forecasts, base['market'], bayesian_features)
                base['horizons'][str(h)] = {'incremental': incremental, 'bayesian': bayesian,
                    'pretrained': {'status': 'unknown', 'direction': 'unknown', 'reason': 'Chronos-2 não executado nesta consulta.'}}
            old = previous.get(ticker, {})
            same = old.get('price_hash') == base['price_hash'] and old.get('peer_hash') == digest(peers)
            base['peer_hash'] = digest(peers)
            ready_old = all(old.get('horizons', {}).get(str(h), {}).get('pretrained', {}).get('status') == 'ready' for h in HORIZONS)
            if inputs['pretrained'] or same and ready_old:
                try:
                    progress(f'{ticker} · Chronos-2 com pesos prontos (primeiro uso baixa o modelo)…')
                    project_cache = app.ROOT/'data'/'ai_models'
                    cache = project_cache if (project_cache/('models--'+MODEL_ID.replace('/', '--'))/'snapshots'/MODEL_REVISION).exists() else app.DB_PATH.parent/'ai_models'
                    forecast = {str(h): old['horizons'][str(h)]['pretrained'] for h in HORIZONS} if same and ready_old else pretrained(points, peers, cache)
                    for h in HORIZONS:
                        base['horizons'][str(h)]['pretrained'] = forecast[str(h)]
                except Exception as exc:
                    base['pretrained_error'] = str(exc) if isinstance(exc, ValueError) else 'Falha no Chronos-2; o incremental foi conservado.'
            for row in base['horizons'].values():
                directions = [r['direction'] for r in (row['pretrained'], row['incremental']) if r['status'] == 'ready']
                row['agreement'] = directions[0] if len(directions) == 2 and directions[0] == directions[1] else 'mixed' if len(directions) == 2 else 'unknown'
            stored.update(updates)
        # Re-check the public inputs before writing a result produced by a slow inference.
        with app.WRITE_LOCK, app.connect() as c:
            current = c.execute('SELECT id,ticker,sector,asset_type,archived FROM assets WHERE id=?', (a['id'],)).fetchone()
            if not current or current['archived'] or current['ticker'] != ticker or current['sector'] != a['sector']:
                continue
            live = {'snapshots': app.latest(c, a['id']), 'asset_type': current['asset_type']}
            if digest(signal_prices(live, app.today(), app.now())) != base['price_hash']:
                continue
            models = app.read_cache(c, 'market_signal_models', {})
            models.update({k: v for k, v in stored.items() if k.startswith(ticker+':')})
            results = app.read_cache(c, 'market_signal_results', {})
            results[ticker] = base
            app.write_cache(c, 'market_signal_models', models)
            app.write_cache(c, 'market_signal_results', results)
    progress('Análise concluída. Compare os modelos, as probabilidades bayesianas e a avaliação cronológica.')


def prepare_histories(app, inputs):
    """Explicit public-price download; keep positions and previous good data intact."""
    assets = app.state()['assets']
    if inputs['history']=='portfolio':
        assets = [a for a in assets if a['position']['quantity']>0
                  and a['asset_type'] in ('stock','fii','etf') and a.get('verified')]
    else:
        assets = [a for a in assets if is_equity(a) and (a['asset_type']=='foreign' or a.get('verified'))
                  and (not inputs.get('market') or a['asset_type']==('foreign' if inputs['market']=='US' else 'stock'))]
        # Include references as well as the selected ticker, subject to the same cap.
        assets.sort(key=lambda a: a['ticker']!=inputs.get('ticker'))
    assets = assets[:40]
    if not assets:
        raise ValueError('Não há ativos elegíveis para buscar histórico nesta seleção.')
    errors = []
    for n,a in enumerate(assets):
        progress(f"{a['ticker']} · {n+1}/{len(assets)} · buscando cinco anos de preços ajustados…")
        try:
            history_cache.fetch(app, {'asset_id': a['id'], 'years': 5})
        except Exception:
            # Each fetch preserves its previous snapshot on failure. Do not print
            # provider exceptions, which may include request credentials.
            errors.append(a['ticker'])
    return errors


def start(app, inputs):
    if not isinstance(inputs, dict) or set(inputs)-{'ticker', 'pretrained', 'market', 'history'} or type(inputs.get('pretrained', True)) is not bool or inputs.get('market','') not in ('','US','BR') or inputs.get('history','') not in ('','signals','portfolio'):
        raise ValueError('Parâmetros de análise inválidos.')
    inputs = {'pretrained': inputs.get('pretrained', True), **inputs}
    if 'ticker' in inputs and (not isinstance(inputs['ticker'], str) or len(inputs['ticker']) > 20):
        raise ValueError('Escolha uma ação cadastrada.')
    if inputs.get('ticker'):
        with app.connect() as c:
            row=c.execute("SELECT asset_type FROM assets WHERE ticker=? AND archived=0 AND asset_type IN ('stock','foreign')", (inputs['ticker'],)).fetchone()
            if not row or inputs.get('market') and row['asset_type'] != ('foreign' if inputs['market']=='US' else 'stock'):
                raise ValueError('Escolha uma ação cadastrada.')
    with LOCK:
        if JOB['running']:
            raise ValueError('Uma análise dos modelos já está em andamento.')
        JOB.update(running=True, id=digest(app.now())[:16], progress='Iniciando os modelos…', error='', finished_at=None)
    def run():
        try:
            errors = prepare_histories(app, inputs) if inputs.get('history') else []
            if inputs.get('history')!='portfolio':
                analyze(app, inputs)
            else:
                progress('Busca concluída. Confira as datas comuns e as posições fora do cálculo de acoplamento.')
            if errors:
                with LOCK:
                    JOB['error'] = 'Histórico não obtido para '+', '.join(errors)+'. Dados anteriores preservados; demais ativos processados.'
        except Exception as exc:
            with LOCK:
                JOB['error'] = str(exc) if isinstance(exc, ValueError) else 'Não foi possível concluir; confira os dados e tente novamente.'
        finally:
            with LOCK:
                JOB.update(running=False, finished_at=app.now())
    threading.Thread(target=run, daemon=True).start()
    return job_state()
