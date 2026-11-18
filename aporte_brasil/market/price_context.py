"""Where today's price sits in its own history: previous visits to the same level,
percentile in the window, distance from highs and lows, and time under water.

Pure functions over the series the app already stores. Nothing here estimates a
fair price or a future return: a level the stock visited before says what the
market paid then, not what the company is worth now.
"""
from datetime import date, timedelta
import math
import statistics

WINDOWS = (1, 3, 5, 10)
# (band, minimum out-of-band observations that separate two visits, minimum points per window year)
SERIES_RULES = {
    'daily': dict(band=3.0, min_gap=10, per_year=120),
    'monthly': dict(band=5.0, min_gap=2, per_year=9),
}
SERIES_LABELS = {
    'daily': 'Diário · ajustado por proventos',
    'monthly': 'Mensal · fechamento sem ajuste de proventos',
}
SERIES_NOTES = {
    'daily': 'Preços passados ajustados por proventos ficam menores que os vistos na tela naquela data; use para comparar formato e distância, não o preço exato.',
    'monthly': 'Fechamento do último pregão de cada mês, ajustado só por desdobramentos e grupamentos. Picos e vales dentro do mês não aparecem.',
}
METHOD = ('Faixa de preço: fechamento a até ±{band}% do preço de referência. Uma visita é uma sequência de fechamentos na faixa; '
          'saídas curtas (menos de {gap} observações) não encerram a visita. Percentil: parcela dos fechamentos da janela abaixo do preço atual. '
          'Drawdown: queda em relação ao maior fechamento da janela.')


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _day(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def clean(points):
    """Sorted, de-duplicated (date, close) pairs with positive finite closes."""
    seen = {}
    for p in points or []:
        if not isinstance(p, dict):
            continue
        d, c = _day(p.get('date')), p.get('close')
        if d and _finite(c) and c > 0:
            seen[d] = float(c)
    return sorted(seen.items())


def _ago(day, today):
    return max(0, (today - day).days)


def _pct(a, b):
    return (a / b - 1) * 100


def last_visit(rows, ref, band, min_gap, today):
    """Most recent visit to the band around `ref` before the current stay in it."""
    inb = [abs(_pct(c, ref)) <= band for _, c in rows]
    last = len(rows) - 1
    if last < 0 or not inb[last]:
        # The reference is not the last close (fresh quote vs. older series): no "current stay" to anchor.
        stay_start = last + 1
        j = last
    else:
        j = last
    while True:
        while j >= 0 and inb[j]:
            j -= 1
        stay_start = j + 1
        k = j
        while k >= 0 and not inb[k]:
            k -= 1
        if k >= 0 and j - k < min_gap:
            j = k
            continue
        break
    stay = rows[stay_start:] if stay_start <= last else []
    out = {'stay_start': rows[stay_start][0].isoformat() if stay else None,
           'stay_observations': len(stay), 'previous': None}
    if k < 0:
        return out
    s = k
    while s > 0 and inb[s - 1]:
        s -= 1
    between = rows[k + 1:stay_start] if stay_start > k + 1 else []
    low = min(between, key=lambda r: r[1]) if between else None
    high = max(between, key=lambda r: r[1]) if between else None
    out['previous'] = {
        'start': rows[s][0].isoformat(), 'end': rows[k][0].isoformat(), 'close': rows[k][1],
        'days_ago': _ago(rows[k][0], today), 'observations': k - s + 1,
        'between_low': {'date': low[0].isoformat(), 'close': low[1], 'change': _pct(low[1], ref)} if low else None,
        'between_high': {'date': high[0].isoformat(), 'close': high[1], 'change': _pct(high[1], ref)} if high else None,
    }
    return out


def last_beyond(rows, ref, band, today):
    """Most recent close at least `band`% below and at least `band`% above the reference."""
    result = {}
    for key, test in (('cheaper', lambda c: c <= ref * (1 - band / 100)), ('dearer', lambda c: c >= ref * (1 + band / 100))):
        hit = next(((d, c) for d, c in reversed(rows) if test(c)), None)
        result[key] = {'date': hit[0].isoformat(), 'close': hit[1], 'change': _pct(hit[1], ref), 'days_ago': _ago(hit[0], today)} if hit else None
    return result


def window_stats(rows, ref, years, today, per_year):
    cutoff = today - timedelta(days=round(365.25 * years))
    part = [(d, c) for d, c in rows if d >= cutoff]
    # A window is only reported when the series really covers it (first point within ~5% of the span).
    covered = bool(part) and (part[0][0] - cutoff).days <= max(35, 0.05 * 365.25 * years)
    if not covered or len(part) < per_year * years:
        return {'years': years, 'available': False, 'count': len(part)}
    closes = [c for _, c in part]
    hi = max(part, key=lambda r: r[1])
    lo = min(part, key=lambda r: r[1])
    below = sum(c < ref for c in closes) + .5 * sum(c == ref for c in closes)
    peak = part[0][1]
    peak_day = part[0][0]
    worst = {'drawdown': 0.0, 'peak': peak_day, 'trough': peak_day}
    for d, c in part:
        if c > peak:
            peak, peak_day = c, d
        dd = _pct(c, peak)
        if dd < worst['drawdown']:
            worst = {'drawdown': dd, 'peak': peak_day, 'trough': d}
    # Recovery of the worst drop: first close at or above the pre-drop peak after the trough.
    peak_close = dict(part)[worst['peak']]
    recovered = next((d for d, c in part if d > worst['trough'] and c >= peak_close), None)
    return {
        'years': years, 'available': True, 'count': len(part), 'start': part[0][0].isoformat(),
        'percentile': below / len(closes) * 100,
        'median': statistics.median(closes), 'vs_median': _pct(ref, statistics.median(closes)),
        'high': {'date': hi[0].isoformat(), 'close': hi[1], 'distance': _pct(ref, hi[1]), 'days_ago': _ago(hi[0], today)},
        'low': {'date': lo[0].isoformat(), 'close': lo[1], 'distance': _pct(ref, lo[1]), 'days_ago': _ago(lo[0], today)},
        'max_drawdown': {'value': worst['drawdown'], 'peak': worst['peak'].isoformat(), 'trough': worst['trough'].isoformat(),
                         'recovered': recovered.isoformat() if recovered else None,
                         'months_to_recover': round((recovered - worst['trough']).days / 30.44, 1) if recovered else None},
    }


def reading(level, series):
    """One factual sentence; never a buy or sell signal."""
    prev = level['visit'].get('previous')
    unit = 'mês/ano' if series == 'monthly' else 'dia'
    if not prev:
        return 'Neste histórico, o preço não esteve antes nesta faixa.'
    end = date.fromisoformat(prev['end'])
    months = prev['days_ago'] / 30.44
    when = f"{end.month:02d}/{end.year}" if series == 'monthly' else end.strftime('%d/%m/%Y')
    span = f"{months:.0f} meses" if months >= 2 else f"{prev['days_ago']} dias"
    text = f"A última visita a esta faixa (±{level['band']:g}%) terminou em {when}, há {span}."
    lo, hi = prev.get('between_low'), prev.get('between_high')
    if lo and hi:
        text += f" Desde então, os fechamentos foram de {lo['change']:+.0f}% a {hi['change']:+.0f}% em relação ao preço de referência."
    return text


def build_level(rows, ref, rule, today, key):
    level = {
        'series': key, 'label': SERIES_LABELS[key], 'note': SERIES_NOTES[key],
        'count': len(rows), 'start': rows[0][0].isoformat(), 'end': rows[-1][0].isoformat(),
        'reference': ref, 'band': rule['band'], 'min_gap': rule['min_gap'],
        'visit': last_visit(rows, ref, rule['band'], rule['min_gap'], today),
        'beyond': last_beyond(rows, ref, rule['band'], today),
        'windows': {str(y): window_stats(rows, ref, y, today, rule['per_year']) for y in WINDOWS},
        'method': METHOD.format(band=f"{rule['band']:g}", gap=rule['min_gap']),
    }
    level['reading'] = reading(level, key)
    return level


def analyze(asset, today):
    """`asset` is a state asset: metrics.price plus snapshots.history / issuer_price_history."""
    result = {'applicable': asset.get('asset_type') in ('stock', 'fii', 'etf'), 'status': 'unknown', 'levels': {}, 'price': None,
              'caveat': 'Um preço já visitado antes mostra o que o mercado pagou naquele momento. Não indica valor justo, nem que o preço voltará a esse nível.'}
    if not result['applicable']:
        return result
    snaps = asset.get('snapshots') or {}
    quote = (snaps.get('quote') or {}).get('data') or {}
    quote_asof = _day((snaps.get('quote') or {}).get('asof'))
    price = (asset.get('metrics') or {}).get('price')
    price = price if _finite(price) and price > 0 else quote.get('price')
    fresh_quote = _finite(price) and price > 0 and quote_asof and 0 <= (today - quote_asof).days <= 7
    result['price'] = float(price) if fresh_quote else None
    result['price_asof'] = quote_asof.isoformat() if quote_asof else None
    daily = clean(((snaps.get('history') or {}).get('data') or {}).get('prices'))
    monthly = clean(((snaps.get('issuer_price_history') or {}).get('data') or {}).get('months'))
    if len(monthly) >= 24:
        ref = float(price) if fresh_quote else monthly[-1][1]
        result['levels']['monthly'] = build_level(monthly, ref, SERIES_RULES['monthly'], today, 'monthly')
    if len(daily) >= 130:
        # Adjusted series: the reference is its own last close, so the comparison stays on one basis.
        result['levels']['daily'] = build_level(daily, daily[-1][1], SERIES_RULES['daily'], today, 'daily')
    result['status'] = 'ready' if result['levels'] else 'missing_prices'
    result['preferred'] = 'monthly' if 'monthly' in result['levels'] else 'daily' if 'daily' in result['levels'] else None
    if result['status'] == 'missing_prices':
        result['message'] = 'Falta histórico de preços. Busque o histórico de 5 anos ou o de múltiplos (10 anos) para ver visitas anteriores a este preço.'
    return result
