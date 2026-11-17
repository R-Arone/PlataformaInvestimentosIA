"""Daily Ibovespa and USD/BRL closes, fetched on request and kept in the local cache.

They only describe co-movement with each asset (beta and correlation). They are not
valuation references, and an unavailable series never blocks the rest of the analysis.
"""
from datetime import datetime, timezone
import math
import urllib.parse

CACHE = 'benchmark_prices'
MAX_AGE_DAYS = 1
YEARS = 5
MIN_POINTS = 200
SERIES = {
    'ibov': dict(symbol='^BVSP', currency='BRL', label='Ibovespa',
                 page='https://finance.yahoo.com/quote/%5EBVSP/', definition='https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/ibovespa-b3.htm'),
    'usd': dict(symbol='BRL=X', currency='BRL', label='Dólar (USD/BRL)',
                page='https://finance.yahoo.com/quote/BRL%3DX/', definition='https://finance.yahoo.com/quote/BRL%3DX/'),
}


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def url(spec):
    return 'https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(spec['symbol'], safe='') + f'?range={YEARS}y&interval=1d'


def parse(raw, spec, today):
    """Validate identity and currency, drop invalid and future points, and require a usable length."""
    try:
        r = raw['chart']['result'][0]
        meta = r['meta']
        closes = r['indicators']['quote'][0]['close']
        stamps = r['timestamp']
    except (KeyError, TypeError, IndexError):
        raise ValueError(spec['label'] + ': resposta sem série reconhecida.') from None
    if meta.get('symbol') != spec['symbol'] or meta.get('currency') != spec['currency']:
        raise ValueError(spec['label'] + ': símbolo ou moeda não confirmados.')
    points = {}
    for ts, close in zip(stamps or [], closes or []):
        if not _finite(close) or close <= 0 or not _finite(ts):
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).date()
        if day <= today:
            points[day.isoformat()] = float(close)
    if len(points) < MIN_POINTS:
        raise ValueError(f"{spec['label']}: só {len(points)} fechamentos; são necessários {MIN_POINTS}.")
    return [{'date': d, 'close': c} for d, c in sorted(points.items())]


def fresh(cache, today_fn, now_fn):
    try:
        stamp = datetime.fromisoformat(cache['retrieved_at'])
        return (datetime.fromisoformat(now_fn()) - stamp).total_seconds() < MAX_AGE_DAYS * 86400
    except (KeyError, TypeError, ValueError):
        return False


def fetch(app, force=False):
    """Refresh both series. A failure keeps the previous series for that key and is reported."""
    with app.connect() as c:
        cache = app.read_cache(c, CACHE, {})
    if cache.get('series') and fresh(cache, app.today, app.now) and not force and all(k in cache['series'] for k in SERIES):
        return {**public(cache), 'used_cache': True, 'errors': []}
    series = dict(cache.get('series') or {})
    errors = []
    for key, spec in SERIES.items():
        try:
            prices = parse(app.request_json(url(spec)), spec, app.today())
            series[key] = {'symbol': spec['symbol'], 'label': spec['label'], 'source': 'Yahoo Finance · chart/' + spec['symbol'],
                           'source_url': spec['page'], 'definition_url': spec['definition'],
                           'asof': prices[-1]['date'], 'prices': prices}
        except ValueError as exc:
            errors.append(str(exc))
    if not series:
        raise ValueError('; '.join(errors) or 'Sem séries de referência.')
    payload = {'retrieved_at': app.now(), 'series': series}
    with app.WRITE_LOCK, app.connect() as c:
        app.write_cache(c, CACHE, payload)
        for key, s in series.items():
            app.log_source(c, 'benchmark_' + key, s['label'] + ' · histórico diário para correlações', s['source_url'], asof=s['asof'])
    return {**public(payload), 'used_cache': False, 'errors': errors}


def series_for(cache):
    """{key: {'prices': [...], ...}} for the analysis; empty when nothing was fetched."""
    return (cache or {}).get('series') or {}


def public(cache):
    """Metadata only: the daily points are not sent to the browser."""
    return {'retrieved_at': (cache or {}).get('retrieved_at'),
            'series': {k: {'label': v['label'], 'asof': v['asof'], 'count': len(v['prices']), 'source': v['source'], 'source_url': v['source_url']}
                       for k, v in series_for(cache).items()}}
