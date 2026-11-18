"""Public US-equity quotes in USD and local English financial sentiment.

The ledger remains in BRL. Native prices live in separate snapshot kinds;
today's FX rate is never applied to a historical return series.
"""
from datetime import date, datetime, timezone
import json
import math
import re
import threading
import urllib.parse

from aporte_brasil.market import extra_sources
from aporte_brasil.market import market_brief
from aporte_brasil.portfolio.portfolio_coupling import completed_prices

MODEL = 'yiyanghkust/finbert-tone'
REVISION = '4921590d3c0c3832c0efea24c8381ce0bda7844b'
EXCHANGES = {'NYQ', 'NMS', 'NGM', 'NCM', 'ASE', 'PCX', 'BTS'}
PIPE = None
PIPE_CACHE = None
LOCK = threading.Lock()


def symbol(ticker):
    if not isinstance(ticker, str) or not re.fullmatch(r'[A-Z]{1,6}(?:[.\-][A-Z]{1,2})?', ticker):
        raise ValueError('Informe um ticker americano, como AAPL, MSFT ou BRK-B.')
    return ticker.replace('.', '-')


def validate_snapshot(app, kind, data):
    if data.get('currency') != 'USD' or data.get('market') != 'US':
        raise ValueError('Dados americanos precisam identificar EUA e USD.')
    if kind == 'us_quote':
        if data.get('exchange') not in EXCHANGES:
            raise ValueError('Bolsa americana não confirmada.')
        return {'price': app.number(data.get('price'), True, .00000001), 'currency': 'USD', 'market': 'US',
                'exchange': data['exchange'], 'symbol': symbol(data.get('symbol')),
                'issuer': app.text_value(data.get('issuer', ''), 200)}
    points = data.get('prices')
    if not isinstance(points, list) or not 1 <= len(points) <= 10000:
        raise ValueError('Histórico americano inválido.')
    normalized = []
    for p in points:
        day = app.valid_date(p['date'])
        if day > app.today().isoformat():
            raise ValueError('Histórico americano com data futura.')
        normalized.append({'date': day, 'close': app.number(p['close'], True, .00000001)})
    years = data.get('years', 1)
    if type(years) is not int or years not in (1, 5) or len({p['date'] for p in normalized}) != len(normalized):
        raise ValueError('Janela ou datas do histórico americano inválidas.')
    return {'prices': sorted(normalized, key=lambda p: p['date']), 'years': years, 'currency': 'USD', 'market': 'US'}


def fetch(ticker, request, today, years=1):
    ticker = symbol(ticker)
    if years not in (1, 5):
        raise ValueError('Escolha um ou cinco anos de histórico.')
    raw = request('https://query1.finance.yahoo.com/v8/finance/chart/' + ticker + f'?range={years}y&interval=1d')
    try:
        result = raw['chart']['result'][0]
        meta = result['meta']
    except (KeyError, TypeError, IndexError):
        raise ValueError('Yahoo Finance: ação americana não encontrada.') from None
    if meta.get('symbol') != ticker or meta.get('currency') != 'USD' or meta.get('instrumentType') != 'EQUITY' or meta.get('exchangeName') not in EXCHANGES:
        raise ValueError('Yahoo Finance: ticker, ação, bolsa dos EUA ou moeda USD não confirmados.')
    source = 'Yahoo Finance · EUA/chart/' + ticker
    groups = {}
    price = extra_sources.finite(meta.get('regularMarketPrice'))
    ts = meta.get('regularMarketTime')
    if price and price > 0 and isinstance(ts, (int, float)):
        day = datetime.fromtimestamp(ts, timezone.utc).date()
        if day > today():
            raise ValueError('Cotação americana futura rejeitada.')
        groups['us_quote'] = ({'price': price, 'currency': 'USD', 'market': 'US', 'symbol': ticker,
                               'exchange': meta['exchangeName'], 'issuer': str(meta.get('longName') or meta.get('shortName') or ticker)[:200]}, day.isoformat(), source)
    adj = (result.get('indicators', {}).get('adjclose') or [{}])[0].get('adjclose', [])
    points = {}
    for timestamp, close in zip(result.get('timestamp', []), adj):
        value = extra_sources.finite(close)
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        if value and value > 0 and day <= today():
            points[day.isoformat()] = value
    if points:
        prices = [{'date': day, 'close': value} for day, value in sorted(points.items())]
        groups['us_history'] = ({'prices': prices, 'years': years, 'currency': 'USD', 'market': 'US'}, prices[-1]['date'], source)
    if not groups:
        raise ValueError('Sem cotação ou histórico ajustado dos EUA; dados anteriores preservados.')
    return groups


def refresh_asset(app, asset, years=1):
    groups = fetch(asset['ticker'], app.request_json, app.today, years)
    warnings = []
    with app.WRITE_LOCK, app.connect() as c:
        current = c.execute('SELECT ticker,asset_type,archived FROM assets WHERE id=?', (asset['id'],)).fetchone()
        if not current or current['archived'] or current['asset_type'] != 'foreign' or current['ticker'] != asset['ticker']:
            raise ValueError('Cadastro alterado durante a consulta; atualize novamente.')
        for kind, (data, day, source) in groups.items():
            app.add_snapshot(c, asset['id'], kind, validate_snapshot(app, kind, data), source, day)
        # USD quote and BRL valuation have separate references. No ledger rewrite.
        fx = c.execute("SELECT * FROM macro WHERE key='usd'").fetchone()
        quote = groups.get('us_quote')
        if quote and fx and 0 <= app.age(fx['asof']) <= 7 and abs((date.fromisoformat(quote[1])-date.fromisoformat(fx['asof'])).days) <= 4:
            app.add_snapshot(c, asset['id'], 'quote', {'price': quote[0]['price'] * fx['value'],
                'change': None, 'usd_price': quote[0]['price'], 'usd_asof': quote[1], 'fx_rate': fx['value'],
                'fx_asof': fx['asof'], 'fx_source': fx['source']}, quote[2] + ' + BCB/SGS 1 · conversão BRL', min(quote[1], fx['asof']))
        elif quote:
            warnings.append('Cotação USD salva; conversão BRL aguarda câmbio recente. Valor anterior em reais preservado.')
        app.log_source(c, 'us_' + str(asset['id']), asset['ticker'] + ' · EUA', 'https://finance.yahoo.com/quote/' + symbol(asset['ticker']) + '/', asof=groups.get('us_history', groups.get('us_quote'))[1])
    return warnings


def native_prices(asset, day, stamp):
    snapshot = asset.get('snapshots', {}).get('us_history', {})
    if snapshot.get('data', {}).get('currency') != 'USD' or snapshot.get('data', {}).get('market') != 'US':
        return {}
    return completed_prices({'snapshots': {'history': snapshot}}, day, stamp, market='US')


def classify(texts, cache_dir):
    """Upstream .bin is loaded with restricted weights_only, never remote code."""
    global PIPE, PIPE_CACHE
    if not texts:
        return []
    with LOCK:
        import torch
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer
        from huggingface_hub import hf_hub_download
        if tuple(int(n) for n in torch.__version__.split('+')[0].split('.')[:2]) < (2, 6):
            raise ValueError('FinBERT-Tone exige torch 2.6 ou posterior.')
        if PIPE is None or PIPE_CACHE != str(cache_dir):
            try:
                args = {'revision': REVISION, 'cache_dir': str(cache_dir), 'trust_remote_code': False}
                tokenizer = AutoTokenizer.from_pretrained(MODEL, **args)
                cfg = AutoConfig.from_pretrained(MODEL, **args)
                model = AutoModelForSequenceClassification.from_config(cfg, trust_remote_code=False)
                path = hf_hub_download(MODEL, 'pytorch_model.bin', revision=REVISION, cache_dir=str(cache_dir))
                weights = torch.load(path, map_location='cpu', weights_only=True)
                weights.pop('bert.embeddings.position_ids', None)
                model.load_state_dict(weights, strict=True)
                model.eval()
                PIPE, PIPE_CACHE = (tokenizer, model), str(cache_dir)
                torch.set_num_threads(min(4, torch.get_num_threads()))
            except Exception:
                raise ValueError('FinBERT-Tone indisponível; primeiro uso baixa cerca de 440 MB. Dados anteriores preservados.') from None
        tokenizer, model = PIPE
        results = []
        with torch.inference_mode():
            for start in range(0, len(texts), 8):
                inputs = tokenizer(texts[start:start+8], return_tensors='pt', padding=True, truncation=True, max_length=256)
                for row in torch.softmax(model(**inputs).logits, dim=-1).tolist():
                    # Fixed checkpoint: neutral=0, positive=1, negative=2.
                    results.append({'positive': row[1], 'negative': row[2], 'neutral': row[0]})
        return results


def feed(ticker, name, clock):
    query = f'"{symbol(ticker)}" "{name[:80]}" (stock OR earnings OR revenue) when:7d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    found = market_brief.fetch_feed(url, clock)
    unique = {(n['title'], n['publisher']): n for n in found}
    return {'profile': 'foreign', 'ticker': ticker, 'retrieved_at': clock.isoformat(),
            'headlines': sorted(unique.values(), key=lambda n: n['published_at'], reverse=True)[:12],
            'sources': [{'name': 'Google News · inglês/EUA', 'url': url}], 'errors': []}


def analyze_sentiment(app, inputs):
    from aporte_brasil.ai import market_ai
    assets = [a for a in app.state()['assets'] if a['asset_type'] == 'foreign' and (not inputs.get('ticker') or a['ticker'] == inputs['ticker'])][:40]
    cache = app.ROOT / 'data' / 'ai_models'
    reports, errors = {}, []
    for i, asset in enumerate(assets):
        ticker = asset['ticker']
        market_ai.progress(f'{ticker} · notícias em inglês · {i+1}/{len(assets)}')
        try:
            symbol(ticker)
            if not asset.get('us', {}).get('verified'):
                raise ValueError('Atualize primeiro os dados para confirmar a ação americana.')
            report = feed(ticker, asset['us']['quote']['data']['issuer'], datetime.now(timezone.utc))
            items = market_ai.recent_headlines(report, datetime.now(timezone.utc))
            market_ai.progress(f'{ticker} · FinBERT-Tone com pesos prontos…')
            classified = classify([n['title'] for n in items], cache)
            result = market_ai.summarize_sentiment(report, items, classified, app.now(), MODEL, 'huggingface')
            result.update(revision=REVISION, ticker=ticker,
                method='FinBERT-Tone: tom de títulos financeiros em inglês, janela de sete dias. Pré-treinado em relatórios 10-K/10-Q, resultados e analistas. Mínimo de quatro títulos e dois veículos; cortes editoriais ±0,15. Não prevê retorno nem valida o impacto individual da notícia.')
            reports[ticker] = {'feed': report, 'sentiment': result}
        except ValueError as exc:
            errors.append(ticker + ': ' + str(exc))
    with app.WRITE_LOCK, app.connect() as c:
        saved = app.read_cache(c, 'us_news', {})
        active = {r['ticker'] for r in c.execute("SELECT ticker FROM assets WHERE archived=0 AND asset_type='foreign'")}
        saved.update({k: v for k, v in reports.items() if k in active})
        app.write_cache(c, 'us_news', saved)
    if not reports and errors:
        raise ValueError('; '.join(errors[:3]))
    market_ai.progress('Notícias dos EUA analisadas.' + (' Pendências: ' + '; '.join(errors[:3]) if errors else ''))


def enrich(app, c, asset):
    if asset['asset_type'] != 'foreign':
        return
    q = asset['snapshots'].get('us_quote', {})
    verified = q.get('data', {}).get('currency') == 'USD' and q.get('data', {}).get('market') == 'US' and q.get('data', {}).get('exchange') in EXCHANGES
    news = app.read_cache(c, 'us_news', {}).get(asset['ticker'], {})
    sentiment = json.loads(json.dumps(news.get('sentiment', {})))
    if sentiment:
        sentiment['stale'] = app.age(sentiment['analyzed_at']) > 1
    asset['us'] = {'verified': verified, 'quote': q, 'quote_stale': not q or not 0<=app.age(q['asof'])<=7, 'sentiment': sentiment,
                   'news': news.get('feed', {}), 'currency': 'USD', 'market': 'US'}


def rank(assets, signals, horizon):
    by_ticker = {r['ticker']: r for r in signals['rows']}
    rows = []
    for a in assets:
        if a['asset_type'] != 'foreign':
            continue
        saved = by_ticker.get(a['ticker'], {})
        h = saved.get('horizons', {}).get(str(horizon), {})
        quote = a.get('us', {}).get('quote', {})
        reasons, priority, status = [], 0, 'unknown'
        models = [h.get(k, {}) for k in ('pretrained', 'incremental')]
        ready = a.get('us', {}).get('verified') and quote and not a['us'].get('quote_stale') and not saved.get('stale') and all(m.get('status') == 'ready' for m in models)
        if ready:
            directions = [m['direction'] for m in models]
            if directions == ['favorable', 'favorable']:
                status, priority = 'candidate', 70
                reasons.append('Os dois modelos apontam viés de alta neste horizonte.')
            elif 'unfavorable' in directions:
                status, priority = 'contrary', 10
                reasons.append('Há leitura de baixa; revisar antes de considerar entrada.')
            else:
                status, priority = 'mixed', 30
                reasons.append('Leituras sem concordância de alta.')
            sentiment = a.get('us', {}).get('sentiment', {})
            if sentiment.get('tone') == 'negative' and not sentiment.get('stale'):
                priority = max(0, priority-20)
                if status == 'candidate':
                    status = 'mixed'
                reasons.append('Cobertura recente negativa: verificar eventos e efeitos.')
        else:
            reasons.append('Atualize cotação, histórico e os dois modelos; dados insuficientes ou antigos.')
        rows.append({'ticker': a['ticker'], 'status': status, 'priority': priority, 'reasons': reasons,
                     'pending': ['Conferir lucros, fluxo de caixa e dívida no balanço.', 'Comparar valuation com empresas semelhantes.',
                                 'Revisar câmbio, custos, liquidez e concentração.'], 'asof': saved.get('asof'), 'currency': 'USD'})
    return sorted(rows, key=lambda r: (-r['priority'], r['ticker']))


def public_state(app, c, assets):
    root = app.ROOT / 'data' / 'ai_models'
    return {'model': MODEL, 'revision': REVISION,
            'prepared': (root / ('models--'+MODEL.replace('/', '--')) / 'snapshots' / REVISION / 'pytorch_model.bin').is_file(),
            'method': 'Prioridade editorial de pesquisa, não probabilidade: concordância de alta=70, leitura de baixa=10, demais leituras=30; notícia negativa recente reduz 20. Falta de dados=0. Não mede valor justo, adequação pessoal nem retorno. Fundamentais e riscos precisam ser conferidos antes de comprar.'}
