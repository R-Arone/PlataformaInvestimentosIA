"""Observed co-movement and diversification on a common, completed return panel."""
from datetime import date, datetime, timedelta, timezone
import math
import statistics
from zoneinfo import ZoneInfo

MIN_RETURNS = 63
MAX_ASSETS = 40
REFERENCES = [
    {'title': 'Choueifaty e Coignard · razão de diversificação (2008)',
     'url': 'https://www.tobam.fr/maximum-diversification/'},
    {'title': 'Meucci · Managing Diversification (2009)',
     'url': 'https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1358533'},
    {'title': 'Artigo · influência das correlações na diversificação (2008)',
     'url': 'https://arxiv.org/abs/0805.3397'}]


def completed_prices(asset, day, stamp=None, market='BR'):
    """Never interpret today's unfinished Yahoo daily candle as a completed session."""
    cutoff = day
    history = asset.get('snapshots', {}).get('history', {})
    # A cached intraday candle does not become final just because the clock
    # passed the close. It must have been collected after the close as well.
    for observed in (stamp, history.get('retrieved_at')):
        if not observed:
            continue
        try:
            local = datetime.fromisoformat(observed).astimezone(ZoneInfo('America/New_York') if market == 'US' else timezone(timedelta(hours=-3)))
        except (TypeError, ValueError):
            return {}
        observed_cutoff = local.date()
        if (local.hour, local.minute) < ((16, 30) if market == 'US' else (18, 30)):
            observed_cutoff -= timedelta(days=1)
        cutoff = min(cutoff, observed_cutoff)
    points = {}
    for p in history.get('data', {}).get('prices', [])[-6000:]:
        try:
            ref = date.fromisoformat(p['date'])
            value = p['close']
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if ref <= cutoff and math.isfinite(value) and value > 0:
                points[ref.isoformat()] = float(value)
        except (KeyError, TypeError, ValueError):
            continue
    return dict(sorted(points.items()))


def covariance(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    return sum((a-mx)*(b-my) for a, b in zip(x, y))/(len(x)-1)


def analyze(assets, fixed, day, stamp=None):
    held = [a for a in assets if a['position']['quantity'] > 0 and a['value'] > 0]
    traded = sum(a['value'] for a in held)
    total = traded + sum(f.get('balance', 0) for f in fixed)
    result = {'status': 'unknown', 'assets': [], 'excluded': [], 'matrix': [], 'pairs': [],
              'coverage': 0, 'total_coverage': 0, 'count': 0, 'traded_value': traded,
              'held_count': len(held), 'eligible_count': 0, 'common_closes': 0,
              'minimum_closes': MIN_RETURNS+1, 'history': [],
              'mean_correlation': None, 'diversification_ratio': None, 'risk_reduction': None,
              'effective_holdings': None, 'portfolio_volatility': None,
              'references': REFERENCES,
              'method': 'Correlação de retornos logarítmicos, 63 a 252 observações comuns, pesos atuais. '
                        'Média entre pares ponderada por wᵢwⱼ; DR = soma(wᵢσᵢ)/σ da carteira. '
                        '1/soma(wᵢ²) mede concentração dos pesos, não apostas independentes. '
                        'Não implementa o número efetivo de apostas de Meucci. '
                        'Usa só posições com cotação e histórico recentes na mesma moeda (BRL); '
                        'fundos fora da bolsa e títulos sem série de preços ficam fora. '
                        'ETFs/FIIs usam a cota, sem abrir seus componentes.'}
    panel = []
    for a in sorted(held, key=lambda a: a['value'], reverse=True):
        points = completed_prices(a, day, stamp)
        quote = a.get('snapshots', {}).get('quote', {})
        reason = None
        if len(panel) >= MAX_ASSETS:
            reason = 'Limite de 40 posições por cálculo.'
        elif a.get('value_at_cost') or not quote.get('asof') or not 0 <= (day-date.fromisoformat(quote['asof'])).days <= 7:
            reason = 'Cotação ausente ou antiga; peso de mercado não confirmado.'
        elif a.get('asset_type') in ('foreign', 'bdr', 'crypto'):
            reason = 'O acoplamento exige histórico comparável em BRL. Para stocks em USD, falta a série histórica de câmbio.'
        elif len(points) < MIN_RETURNS+1:
            reason = 'Menos de 64 fechamentos ajustados.'
        elif (day-date.fromisoformat(next(reversed(points)))).days > 7:
            reason = 'Histórico com mais de sete dias.'
        if reason:
            result['excluded'].append({'ticker': a['ticker'], 'reason': reason})
        else:
            panel.append((a, points))
        result['history'].append({'ticker': a['ticker'], 'count': len(points),
            'start': next(iter(points), None), 'end': next(reversed(points), None), 'reason': reason})
    covered = sum(a['value'] for a, _ in panel)
    result.update(eligible_count=len(panel), coverage=covered/traded*100 if traded else 0,
                  total_coverage=covered/total*100 if total else 0)
    if len(panel) < 2:
        result['reason'] = 'São necessárias duas posições com histórico e cotação válidos.'
        return result
    dates = sorted(set.intersection(*(set(p) for _, p in panel)))[-253:]
    result['common_closes'] = len(dates)
    # A common panel is mandatory: pairwise deletion can create an invalid covariance matrix.
    if len(dates) < MIN_RETURNS+1 or (day-date.fromisoformat(dates[-1])).days > 7:
        result['reason'] = 'Não há 64 fechamentos comuns recentes entre as posições elegíveis.'
        return result
    if any((date.fromisoformat(b)-date.fromisoformat(a)).days > 7 for a, b in zip(dates, dates[1:])):
        result['reason'] = 'Há lacunas superiores a sete dias no histórico comum; complete os dados.'
        return result
    returns = [[math.log(p[b]/p[a]) for a, b in zip(dates, dates[1:])] for _, p in panel]
    vols = [statistics.stdev(r) for r in returns]
    if any(s < 1e-10 for s in vols):
        result['reason'] = 'Uma série é constante; correlação e risco não podem ser estimados.'
        return result
    weights = [a['value']/covered for a, _ in panel]
    cov = [[covariance(x, y) for y in returns] for x in returns]
    matrix = [[max(-1., min(1., c/(vols[i]*vols[j]))) for j, c in enumerate(row)] for i, row in enumerate(cov)]
    terms = [weights[i]*weights[j]*cov[i][j] for i in range(len(panel)) for j in range(len(panel))]
    variance = math.fsum(terms)
    # A perfect offset may leave a tiny positive residual through float cancellation.
    # Scale tolerance by the terms, so legitimately small variances remain measurable.
    if abs(variance) <= 64*math.ulp(1.)*math.fsum(abs(t) for t in terms):
        variance = 0.
    sigma = math.sqrt(max(0, variance))
    marginal_sum = sum(w*s for w, s in zip(weights, vols))
    pairs = [{'left': panel[i][0]['ticker'], 'right': panel[j][0]['ticker'],
              'correlation': matrix[i][j], 'weight': weights[i]*weights[j]}
             for i in range(len(panel)) for j in range(i+1, len(panel))]
    mean = sum(p['weight']*p['correlation'] for p in pairs)/sum(p['weight'] for p in pairs)
    result.update(status='ready', reason='', count=len(dates)-1, start=dates[0], end=dates[-1],
                  mean_correlation=mean, matrix=matrix, pairs=sorted(pairs, key=lambda p: p['correlation'], reverse=True),
                  diversification_ratio=marginal_sum/sigma if sigma > 1e-10 else None,
                  risk_reduction=max(0., 1-sigma/marginal_sum)*100,
                  effective_holdings=1/sum(w*w for w in weights), portfolio_volatility=sigma*math.sqrt(252)*100,
                  assets=[{'ticker': a['ticker'], 'weight': w*100, 'volatility': v*math.sqrt(252)*100,
                           'risk_contribution': w*sum(c*w2 for c, w2 in zip(cov[i], weights))/variance*100 if variance > 1e-20 else None}
                          for i, ((a, _), w, v) in enumerate(zip(panel, weights, vols))])
    return result
