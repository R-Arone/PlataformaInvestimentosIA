"""Sequential normal/inverse-gamma dynamic regression, implemented locally.

Direct, origin-standardized cumulative log returns; disjoint training targets.
Posterior predictive Student-t includes observation and coefficient uncertainty.
Discounts apply per matured training observation, not per calendar day. This is
not the M6 model, a PyBATS wrapper, or a multivariate portfolio distribution.
"""
from datetime import datetime
import hashlib
import json
import math
import statistics
from zoneinfo import ZoneInfo

VERSION = 2
MIN_TRAIN = 40
START = 63
STATE_DISCOUNT = .995
VAR_DISCOUNT = .995
BAND = .35
EXTRA_FEATURES = ('Correlação com pares 60', 'Correlação com outros setores 60',
                  'Retorno de outros setores 5', 'Outros setores disponíveis',
                  'Pares 5 × correlação', 'Outros setores 5 × correlação')
DIMENSION = 19  # intercept + 12 shared features + 6 sector features


def _beta_fraction(a, b, x):
    """Continued fraction for the regularized incomplete beta function."""
    tiny = 1e-300
    c, d = 1., 1.-(a+b)*x/(a+1)
    d = 1./(d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 201):
        for term in (m*(b-m)*x/((a+2*m-1)*(a+2*m)),
                     -(a+m)*(a+b+m)*x/((a+2*m)*(a+2*m+1))):
            d, c = 1.+term*d, 1.+term/c
            d = 1./(d if abs(d) > tiny else tiny)
            c = c if abs(c) > tiny else tiny
            step = d*c
            result *= step
        if abs(step-1.) < 3e-14:
            return result
    raise ValueError('A distribuição bayesiana não convergiu; resultado descartado.')


def student_cdf(value, degrees):
    if degrees <= 0 or not math.isfinite(degrees) or math.isnan(value):
        raise ValueError('Distribuição preditiva inválida.')
    if value == 0:
        return .5
    x = degrees/(degrees+value*value)
    if x == 0:
        return 0. if value < 0 else 1.
    a, b = degrees/2., .5
    front = math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)
                     + a*math.log(x)+b*math.log1p(-x)) if x < 1 else 0.
    beta = (front*_beta_fraction(a,b,x)/a if x < (a+1)/(a+b+2)
            else 1.-front*_beta_fraction(b,a,1.-x)/b)
    tail = max(0., min(1., beta))/2.
    return tail if value < 0 else 1.-tail


def student_quantile(probability, degrees):
    if not 0 < probability < 1:
        raise ValueError('Quantil inválido.')
    if probability == .5:
        return 0.
    if probability < .5:
        return -student_quantile(1-probability, degrees)
    left, right = 0., 2.
    while student_cdf(right,degrees) < probability:
        right *= 2
    for _ in range(55):
        mid = (left+right)/2
        if student_cdf(mid,degrees) < probability:
            left = mid
        else:
            right = mid
    return (left+right)/2


def new_model():
    return {'version': VERSION, 'mean': [0.]*DIMENSION,
            'covariance': [[(.25 if i == 0 else .05) if i == j else 0.
                            for j in range(DIMENSION)] for i in range(DIMENSION)],
            'degrees': 6., 'sum_squares': 6., 'trained': 0, 'counts': [0,0,0],
            'seen_date': '', 'history_hash': '', 'provenance': {}, 'origin_count': 0,
            'last_train_origin': '', 'pending': [],
            'metrics': {k: {'count': 0, 'brier': 0., 'baseline_brier': 0.,
                            'correct': 0, 'covered': 0, 'log_loss': 0.,
                            'matched_count': 0, 'matched_bayes': 0., 'matched_incremental': 0.,
                            'calibration': [[[0,0.,0] for _ in range(5)] for _ in range(3)]}
                        for k in ('simulated','live')}}


def predictive(model, features):
    x = [1., *features]
    rx = [sum(c*v for c,v in zip(row,x))/STATE_DISCOUNT for row in model['covariance']]
    q = 1.+sum(a*b for a,b in zip(x,rx))
    degrees = VAR_DISCOUNT*model['degrees']
    variance_scale = model['sum_squares']/model['degrees']*q
    mean = sum(a*b for a,b in zip(x,model['mean']))
    if variance_scale <= 0 or not all(math.isfinite(v) for v in (variance_scale,mean,degrees)):
        raise ValueError('Estado bayesiano inválido; refaça a análise.')
    scale = math.sqrt(variance_scale)
    down = student_cdf((-BAND-mean)/scale,degrees)
    up = 1.-student_cdf((BAND-mean)/scale,degrees)
    return {'probabilities': [down, max(0.,1.-down-up), up],
            'positive_probability': 1.-student_cdf(-mean/scale,degrees),
            'mean': mean, 'scale': scale, 'degrees': degrees}


def learn(model, features, target):
    x = [1., *features]
    covariance = [[v/STATE_DISCOUNT for v in row] for row in model['covariance']]
    rx = [sum(c*v for c,v in zip(row,x)) for row in covariance]
    q = 1.+sum(a*b for a,b in zip(x,rx))
    error = target-sum(a*b for a,b in zip(x,model['mean']))
    model['mean'] = [m+r*error/q for m,r in zip(model['mean'],rx)]
    model['covariance'] = [[covariance[i][j]-rx[i]*rx[j]/q
                             for j in range(DIMENSION)] for i in range(DIMENSION)]
    model['degrees'] = VAR_DISCOUNT*model['degrees']+1.
    model['sum_squares'] = VAR_DISCOUNT*model['sum_squares']+error*error/q
    model['trained'] += 1


def _reference_return(group, first, last):
    values = [math.log(p[last]/p[first]) for p in group if first in p and last in p]
    return statistics.mean(values) if values else None


def _correlation(points, group, dates):
    pairs = []
    for first,last in zip(dates,dates[1:]):
        other = _reference_return(group,first,last)
        if other is not None:
            pairs.append((math.log(points[last]/points[first]),other))
    n = len(pairs)
    if n < 30:
        return None,n
    xs,ys = zip(*pairs)
    mx,my = statistics.mean(xs),statistics.mean(ys)
    dx,dy = [v-mx for v in xs],[v-my for v in ys]
    denominator = math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    if denominator < 1e-16:
        return None,n
    # Fixed shrinkage towards zero reduces extremes with short histories.
    value = sum(a*b for a,b in zip(dx,dy))/denominator*n/(n+30)
    return max(-1.,min(1.,value)),n


def features_at(points, peers, factors, i, context=None):
    from aporte_brasil.market.market_signals import features_at as shared_features
    features,vol = shared_features(points,peers,i,context)
    dates = list(points)
    window = dates[max(0,i-60):i+1]
    other = [p for group in factors.values() for p in group]
    sector_corr,sector_n = _correlation(points,peers,window) if len(peers)>=2 else (None,0)
    market_corr,market_n = _correlation(points,other,window) if other else (None,0)
    recent = _reference_return(other,dates[i-5],dates[i])
    normalized = max(-4.,min(4.,recent/(vol*math.sqrt(5)))) if recent is not None else 0.
    sc,mc = sector_corr or 0.,market_corr or 0.
    features += [sc,mc,normalized,float(recent is not None),sc*features[6],mc*normalized]
    return features,vol,{'sector_correlation': sector_corr, 'sector_observations': sector_n,
                         'other_sectors_correlation': market_corr, 'other_observations': market_n,
                         'other_sectors': sorted(factors), 'peer_count': len(peers),
                         'sentiment': bool(features[9]), 'rates': bool(features[11])}


def signature(points, peers, factors, through):
    trim = lambda p: [(d,v) for d,v in p.items() if d <= through]
    value = [trim(points),[trim(p) for p in peers],
             [(s,[trim(p) for p in group]) for s,group in sorted(factors.items())]]
    return hashlib.sha256(json.dumps(value,allow_nan=False).encode()).hexdigest()


def provenance(points, peers, factors):
    """Per-session fingerprints let a rolling window drop its oldest prefix.

    Retained observations must still match exactly; additions in the past,
    internal omissions and corrections rebuild the posterior. No prices are
    duplicated in the model cache. Factor order/structure is part of each hash.
    """
    return {d: hashlib.sha256(json.dumps([v,[p.get(d) for p in peers],
        [(s,[p.get(d) for p in group]) for s,group in sorted(factors.items())]],
        allow_nan=False).encode()).hexdigest() for d,v in points.items()}


def history_changed(model, current):
    if not model.get('seen_date'):
        return False
    old = model.get('provenance',{})
    through = model['seen_date']
    first = min(current) if current else ''
    if through not in current or not old:
        return True
    if any(d<=through and old.get(d)!=value for d,value in current.items()):
        return True
    return any(d>=first and d not in current for d in old)


def _historical_only(pending, target_date, market):
    if not pending.get('generated_at'):
        return False
    generated = datetime.fromisoformat(pending['generated_at']).astimezone(
        ZoneInfo('America/New_York' if market=='US' else 'America/Sao_Paulo'))
    # Conservative: same-session outcomes cannot establish prospective evidence.
    return target_date <= generated.date().isoformat()


def _record(metric, pending, realized, label):
    p = pending['prediction']['probabilities']
    brier = sum((v-float(j==label))**2 for j,v in enumerate(p))
    metric['count'] += 1
    metric['brier'] += brier
    metric['baseline_brier'] += sum((v-float(j==label))**2 for j,v in enumerate(pending['baseline']))
    metric['correct'] += int(max(range(3),key=lambda j:p[j])==label)
    metric['log_loss'] -= math.log(max(1e-15,p[label]))
    pred = pending['prediction']
    tail = student_cdf((realized/pending['normalizer']-pred['mean'])/pred['scale'],pred['degrees'])
    metric['covered'] += int(.1 <= tail <= .9)
    for j,value in enumerate(p):
        cell = metric['calibration'][j][min(4,int(value*5))]
        cell[0] += 1; cell[1] += value; cell[2] += int(label==j)
    inc = pending.get('incremental')
    if inc and inc.get('eligible'):
        metric['matched_count'] += 1
        metric['matched_bayes'] += brier
        metric['matched_incremental'] += sum((v-float(j==label))**2 for j,v in enumerate(inc['probabilities']))


def update_model(points, peers, factors, horizon, previous=None, context=None, incremental=None, market='BR', feature_cache=None):
    if horizon not in (1,5,20):
        raise ValueError('Horizonte bayesiano inválido.')
    model = json.loads(json.dumps(previous)) if previous else new_model()
    fingerprints = provenance(points,peers,factors)
    reset = model.get('version')!=VERSION or history_changed(model,fingerprints)
    if reset:
        model = new_model()
    dates,prices = list(points),list(points.values())
    locations = {d:i for i,d in enumerate(dates)}
    for i in range(START,len(dates)):
        if dates[i] <= model['seen_date']:
            continue
        remaining = []
        for pending in model['pending']:
            start = locations[pending['date']]
            if start+horizon > i:
                remaining.append(pending)
                continue
            if not pending['selected']:
                continue
            realized = math.log(prices[start+horizon]/prices[start])
            label = 2 if realized>pending['band'] else 0 if realized< -pending['band'] else 1
            historical = _historical_only(pending,dates[start+horizon],market)
            if pending['eligible'] and not historical:
                _record(model['metrics']['live' if pending['live'] else 'simulated'],pending,realized,label)
            features = list(pending['features'])
            if historical:
                features[8:12] = [0.,0.,0.,0.]
            learn(model,features,realized/pending['normalizer'])
            model['counts'][label] += 1
            model['last_train_origin'] = pending['date']
        model['pending'] = remaining
        if feature_cache is not None and dates[i] in feature_cache:
            features,vol,coverage = feature_cache[dates[i]]
        else:
            features,vol,coverage = features_at(points,peers,factors,i,context if i==len(dates)-1 else None)
            if feature_cache is not None:
                feature_cache[dates[i]] = features,vol,coverage
        model['pending'].append({'date': dates[i], 'features': features,
            'normalizer': vol*math.sqrt(horizon), 'band': BAND*vol*math.sqrt(horizon),
            'prediction': predictive(model,features), 'coverage': coverage,
            'baseline': [(n+1)/(model['trained']+3) for n in model['counts']],
            'selected': model['origin_count']%horizon==0, 'eligible': model['trained']>=MIN_TRAIN,
            'live': i==len(dates)-1, 'generated_at': (context or {}).get('_generated_at') if i==len(dates)-1 else None,
            'incremental': (incremental or {}).get(dates[i])})
        model['seen_date'] = dates[i]
        model['origin_count'] += 1
    model['history_hash'] = signature(points,peers,factors,model['seen_date'])
    model['provenance'] = {d:v for d,v in fingerprints.items() if d<=model['seen_date']}
    latest = model['pending'][-1] if model['pending'] else None
    if latest and context is not None:
        features,vol,coverage = features_at(points,peers,factors,len(dates)-1,context)
        if features != latest['features']:
            latest.update(features=features,prediction=predictive(model,features),coverage=coverage,
                          generated_at=context.get('_generated_at'),live=True,
                          incremental=(incremental or {}).get(latest['date']))
    return model,report(model,latest,reset)


def report(model, latest, reset=False):
    ready = model['trained']>=MIN_TRAIN and latest is not None
    result = {'status': 'ready' if ready else 'learning', 'direction': 'unknown',
              'trained': model['trained'], 'minimum': MIN_TRAIN, 'reset': reset,
              'probabilities': None, 'calibrated': False,
              'coverage': latest['coverage'] if latest else {}, 'evaluations': {}}
    for kind,metric in model['metrics'].items():
        n,matched = metric['count'],metric['matched_count']
        result['evaluations'][kind] = {'count': n, 'brier': metric['brier']/n if n else None,
            'baseline_brier': metric['baseline_brier']/n if n else None,
            'accuracy': metric['correct']/n*100 if n else None,
            'interval_coverage': metric['covered']/n*100 if n else None,
            'log_loss': metric['log_loss']/n if n else None, 'matched_count': matched,
            'matched_bayes_brier': metric['matched_bayes']/matched if matched else None,
            'matched_incremental_brier': metric['matched_incremental']/matched if matched else None,
            'calibration': [[{'count': c, 'predicted': s/c*100 if c else None,
                             'observed': o/c*100 if c else None} for c,s,o in cells]
                            for cells in metric['calibration']]}
    if ready:
        pred,normalizer = latest['prediction'],latest['normalizer']
        p = pred['probabilities']
        winning = max(range(3),key=lambda j:p[j])
        q = student_quantile(.9,pred['degrees'])
        percent = lambda v: math.expm1(v)*100
        values = [normalizer*(pred['mean']-q*pred['scale']),normalizer*pred['mean'],
                  normalizer*(pred['mean']+q*pred['scale']),-latest['band'],latest['band']]
        if any(not math.isfinite(v) or abs(v)>10 for v in values):
            result.update(status='unknown',reason='Faixa preditiva extrema; resultado descartado.')
            return result
        lo,mid,hi,bandlo,bandhi = [percent(v) for v in values]
        result.update(direction=('unfavorable','neutral','favorable')[winning] if max(p)>=.45 else 'mixed',
            probabilities={'down':p[0]*100,'stable':p[1]*100,'up':p[2]*100},
            positive_probability=pred['positive_probability']*100,median_return=mid,
            low_return=lo,high_return=hi,band_low=bandlo,band_high=bandhi,
            degrees=pred['degrees'])
    return result
