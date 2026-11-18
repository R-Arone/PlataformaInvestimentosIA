"""Per-asset co-movement: Ibovespa and dollar (beta, correlation, stability, up/down days)
and the asset's correlation with the other positions in the portfolio.

Everything is observed over the recent past on common trading days. A correlation or
beta describes how the price moved, not why, and it changes from one period to the next.
"""
from datetime import date, timedelta
import math
import statistics

from aporte_brasil.portfolio import portfolio_coupling

WINDOW = 252          # most recent paired returns used
MIN_RETURNS = 63
MIN_SIDE = 20         # minimum days on each side of the market for up/down statistics
ROLLING = 63
MAX_GAP_DAYS = 5      # a return across a longer calendar gap is not a daily return
TAIL = WINDOW + 80    # rows kept per series: enough to pair 252 returns despite holidays
CACHE_LIMIT = 20000
_MEMO = {}            # (key) -> result; keys carry the first and last rows, so new data never reuses an old answer
BENCHMARKS = {
    'ibov': dict(label='Ibovespa', unit='índice em pontos'),
    'usd': dict(label='Dólar (USD/BRL)', unit='reais por dólar'),
}
TYPES = ('stock', 'fii', 'etf')
HOLD_TYPES = TYPES  # only BRL-priced products enter the portfolio comparison


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def series(points):
    """Sorted (date, close) with positive finite closes from [{'date','close'}]."""
    out = {}
    for p in points or []:
        if not isinstance(p, dict):
            continue
        try:
            d = date.fromisoformat(str(p.get('date'))[:10])
        except ValueError:
            continue
        c = p.get('close')
        if _finite(c) and c > 0:
            out[d] = float(c)
    return sorted(out.items())


def memo(key, compute):
    if key not in _MEMO:
        if len(_MEMO) >= CACHE_LIMIT:
            _MEMO.clear()
        _MEMO[key] = compute()
    return _MEMO[key]


def fingerprint(rows):
    return (len(rows), rows[0], rows[-1]) if rows else (0,)


def paired_returns(left, right, max_gap=MAX_GAP_DAYS):
    """Log returns between consecutive common dates; gaps longer than `max_gap` days are dropped."""
    other = right if isinstance(right, dict) else dict(right)
    common = [(d, c, other[d]) for d, c in left if d in other]
    out = []
    for (d0, a0, b0), (d1, a1, b1) in zip(common, common[1:]):
        if (d1 - d0).days <= max_gap:
            out.append((d1, math.log(a1 / a0), math.log(b1 / b0)))
    return out[-WINDOW:]


def moments(x, y):
    """Sample covariance and variances in one pass (statistics.variance is far slower on 252 points)."""
    n = len(x)
    mx, my = math.fsum(x) / n, math.fsum(y) / n
    sxy = sxx = syy = 0.0
    for a, b in zip(x, y):
        da, db = a - mx, b - my
        sxy += da * db
        sxx += da * da
        syy += db * db
    return sxy / (n - 1), sxx / (n - 1), syy / (n - 1)


def correlation(x, y):
    if len(x) < 3:
        return None
    cov, vx, vy = moments(x, y)
    if vx < 1e-14 or vy < 1e-14:
        return None
    return max(-1., min(1., cov / math.sqrt(vx * vy)))


def interval(r, n):
    """95% interval for a correlation by Fisher's z; undefined for tiny samples or |r| = 1."""
    if r is None or n < 10 or abs(r) >= .999:
        return None
    z, se = math.atanh(r), 1 / math.sqrt(n - 3)
    return [math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)]


def beta_stats(asset_r, market_r):
    """Sensitivity of the asset to the benchmark, with up/down-day splits."""
    n = len(asset_r)
    cov, vm, va = moments(market_r, asset_r)
    if vm < 1e-14 or va < 1e-14:
        return None
    r = correlation(market_r, asset_r)
    beta = cov / vm
    out = {'n': n, 'correlation': r, 'interval': interval(r, n), 'beta': beta, 'r2': r * r if r is not None else None,
           'volatility': math.sqrt(va * 252) * 100, 'benchmark_volatility': math.sqrt(vm * 252) * 100,
           'up_beta': None, 'down_beta': None, 'up_capture': None, 'down_capture': None, 'up_days': 0, 'down_days': 0}
    up = [(m, a) for m, a in zip(market_r, asset_r) if m > 0]
    down = [(m, a) for m, a in zip(market_r, asset_r) if m < 0]
    out.update(up_days=len(up), down_days=len(down))
    for key, side in (('up', up), ('down', down)):
        if len(side) >= MIN_SIDE:
            ms, as_ = [m for m, _ in side], [a for _, a in side]
            # beta inside one side of the market is noisy; the capture ratio is also reported
            c, v, _ = moments(ms, as_)
            out[key + '_beta'] = c / v if v > 1e-14 else None
            mean_m = statistics.fmean(ms)
            out[key + '_capture'] = statistics.fmean(as_) / mean_m if abs(mean_m) > 1e-12 else None
    return out


def rolling(asset_r, market_r, window=ROLLING):
    """Last, lowest and highest correlation over rolling windows, to show how stable it is."""
    if len(asset_r) < 2 * window:
        return None
    values = []
    for i in range(window, len(asset_r) + 1):
        r = correlation(market_r[i - window:i], asset_r[i - window:i])
        if r is not None:
            values.append(r)
    if len(values) < window:
        return None
    return {'window': window, 'count': len(values), 'last': values[-1], 'min': min(values), 'max': max(values),
            'spread': max(values) - min(values)}


def benchmark_block(asset_rows, bench_rows):
    return memo(('bench', fingerprint(asset_rows), fingerprint(bench_rows)), lambda: _benchmark_block(asset_rows, bench_rows))


def _benchmark_block(asset_rows, bench_rows):
    pairs = paired_returns(asset_rows, bench_rows)
    if len(pairs) < MIN_RETURNS:
        return {'status': 'short', 'n': len(pairs), 'reason': f'Só {len(pairs)} retornos em comum; são necessários {MIN_RETURNS}.'}
    a = [p[1] for p in pairs]
    m = [p[2] for p in pairs]
    stats = beta_stats(a, m)
    if stats is None:
        return {'status': 'flat', 'n': len(pairs), 'reason': 'Uma das séries não varia; correlação e beta não podem ser estimados.'}
    stats.update(status='ready', start=pairs[0][0].isoformat(), end=pairs[-1][0].isoformat(), rolling=rolling(a, m))
    return stats


def br(value, places=2, sign=False):
    """Decimal comma, as the interface shows numbers."""
    return format(value, ('+' if sign else '') + f'.{places}f').replace('.', ',')


def beta_text(stats, label):
    if not stats or stats.get('status') != 'ready':
        return None
    b, r = stats['beta'], stats['correlation']
    strength = 'forte' if abs(r) >= .7 else 'moderada' if abs(r) >= .4 else 'fraca'
    direction = 'no mesmo sentido' if r >= 0 else 'em sentido oposto'
    text = f"Correlação {strength} ({br(r, 2, True)}) {direction} de {label}; beta {br(b)}: em dias típicos, para cada 1% de variação de {label}, o preço variou {br(b)}% (R² {stats['r2'] * 100:.0f}%)."
    if stats.get('down_beta') is not None and stats.get('up_beta') is not None:
        text += f" Em dias de queda de {label} o beta foi {br(stats['down_beta'])}; em dias de alta, {br(stats['up_beta'])}."
    return text


def pair_correlation(left, right, right_map):
    def compute():
        pairs = paired_returns(left, right_map)
        if len(pairs) < MIN_RETURNS:
            return None, len(pairs)
        return correlation([x[1] for x in pairs], [x[2] for x in pairs]), len(pairs)
    # Correlation is symmetric: one entry serves (A, B) and (B, A).
    return memo(('pair',) + tuple(sorted((fingerprint(left), fingerprint(right)))), compute)


def holdings_block(asset, peers):
    """Pairwise correlation with the other positions, weighted by current value."""
    rows = peers['rows'].get(asset['id'])
    if rows is None:
        return {'status': 'unavailable', 'reason': 'Sem histórico recente deste ativo.'}
    result = []
    for p in peers['list']:
        if p['id'] == asset['id']:
            continue
        r, n = pair_correlation(rows, peers['rows'][p['id']], peers['maps'][p['id']])
        if r is not None:
            result.append({'ticker': p['ticker'], 'correlation': r, 'n': n, 'value': p['value']})
    if not result:
        return {'status': 'unavailable', 'reason': 'Nenhuma outra posição tem 63 retornos em comum com este ativo.'}
    total = sum(r['value'] for r in result)
    mean = sum(r['correlation'] * r['value'] for r in result) / total
    others = sum(p['value'] for p in peers['list'] if p['id'] != asset['id'])
    ordered = sorted(result, key=lambda r: r['correlation'])
    for r in result:
        r['weight'] = r.pop('value') / total * 100
    return {'status': 'ready', 'mean_correlation': mean, 'peers': len(result),
            'coverage': total / others * 100 if others > 0 else None,
            'highest': sorted(result, key=lambda r: -r['correlation'])[:3], 'lowest': ordered[:3],
            'reading': ('Move-se junto com o restante da carteira' if mean >= .6 else
                        'Movimento parcialmente ligado à carteira' if mean >= .3 else
                        'Pouco ligado ao restante da carteira' if mean > -.1 else 'Tende a andar em sentido oposto ao da carteira')}


def peers_panel(assets, day, stamp):
    """Completed BRL closes of the products held today, shared by every asset's comparison."""
    held = [a for a in assets if a['position']['quantity'] > 0 and a['value'] > 0 and a['asset_type'] in HOLD_TYPES and not a.get('value_at_cost')]
    rows, maps, usable = {}, {}, []
    for a in sorted(held, key=lambda a: -a['value'])[:portfolio_coupling.MAX_ASSETS]:
        pts = portfolio_coupling.completed_prices(a, day, stamp)
        if len(pts) >= MIN_RETURNS + 1:
            rows[a['id']] = [(date.fromisoformat(d), c) for d, c in list(pts.items())[-TAIL:]]
            maps[a['id']] = dict(rows[a['id']])
            usable.append(a)
    return {'rows': rows, 'maps': maps, 'list': usable}


def analyze(asset, rows, benchmarks, peers):
    result = {'applicable': True, 'status': 'ready', 'ibov': None, 'usd': None, 'holdings': None, 'readings': [], 'missing': [],
              'method': ('Retornos logarítmicos diários entre pregões consecutivos em comum, últimos 252 no máximo (mínimo 63). '
                         'Beta = covariância com o índice ÷ variância do índice. Intervalo de 95% pela transformação de Fisher. '
                         'Dias de alta e de queda separam os retornos pelo sinal do índice no dia. '
                         'Correlação com a carteira é a média das correlações par a par ponderada pelo valor atual das demais posições.'),
              'caveat': 'Correlação e beta mudam entre períodos e não indicam causa. Ativos com pouca liquidez podem mostrar correlação baixa só por negociar menos.'}
    for key in BENCHMARKS:
        b = benchmarks.get(key)
        if not b:
            result['missing'].append(f"Sem série de {BENCHMARKS[key]['label']}. Busque Ibovespa e dólar para ver esta comparação.")
            continue
        result[key] = benchmark_block(rows, b)
        result['readings'].append(beta_text(result[key], BENCHMARKS[key]['label']))
    result['holdings'] = holdings_block(asset, peers) if peers['list'] else None
    result['readings'] = [t for t in result['readings'] if t]
    if all((result[k] or {}).get('status') != 'ready' for k in BENCHMARKS) and (result['holdings'] or {}).get('status') != 'ready':
        result['status'] = 'missing'
    return result


def enrich(assets, benchmarks, day, stamp=None):
    """Attach `correlation_context` to every stock, FII and ETF that has recent history."""
    parsed = {k: series((v or {}).get('prices')) for k, v in (benchmarks or {}).items() if k in BENCHMARKS}
    peers = peers_panel(assets, day, stamp)
    for a in assets:
        a['correlation_context'] = {'applicable': False}
        if a['asset_type'] not in TYPES:
            continue
        pts = portfolio_coupling.completed_prices(a, day, stamp)
        rows = [(date.fromisoformat(d), c) for d, c in list(pts.items())[-TAIL:]]
        if len(rows) < MIN_RETURNS + 1:
            a['correlation_context'] = {'applicable': True, 'status': 'missing', 'readings': [], 'missing': [
                'Falta histórico de 5 anos (ou de 1 ano) deste ativo para calcular correlações.']}
            continue
        view = dict(peers)
        view['rows'] = {**peers['rows'], a['id']: rows}
        view['maps'] = {**peers['maps'], a['id']: dict(rows)}
        a['correlation_context'] = analyze(a, rows, parsed, view)
        a['correlation_context']['history_end'] = rows[-1][0].isoformat()
