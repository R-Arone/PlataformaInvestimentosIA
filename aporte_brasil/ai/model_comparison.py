"""Read-only, dependency-free panel for the frozen public long-term experiment.

Nothing is trained or downloaded here. Historical forecasts are never presented
as today's signals and the opt-in average cannot affect recommendations/alerts.
"""
from functools import lru_cache
import json
import math
from pathlib import Path

MODELS = ('lgb_company', 'tabpfn', 'bayes_company', 'frequency')
LABELS = {'lgb_company': 'LightGBM + empresa', 'tabpfn': 'TabPFN + empresa',
          'bayes_company': 'Bayes + empresa', 'frequency': 'Referência histórica',
          'average_two': 'Média 50/50 · experimental'}
CLASSES = ('Ficar atrás da cesta', 'Acompanhar a cesta', 'Superar a cesta')
METRICS = {'income_assets': 'Lucro / ativos · 12 meses',
           'income_equity': 'Lucro / patrimônio · 12 meses', 'equity_assets': 'Patrimônio / ativos',
           'income_growth': 'Crescimento do lucro', 'revenue_growth': 'Crescimento da receita',
           'income_margin': 'Margem líquida · 12 meses', 'operating_cash_assets': 'Caixa operacional / ativos · 12 meses',
           'long_debt_assets': 'Dívida de longo prazo / ativos', 'cash_assets': 'Caixa / ativos'}
PARAMETERS = {'market', 'horizon', 'ticker', 'origin'}


def unique_class(p):
    ranked = sorted(range(3), key=lambda i: p[i])
    return ranked[-1] if p[ranked[-1]] - p[ranked[-2]] > 1e-12 else None


def valid_probabilities(p):
    return (isinstance(p, list) and len(p) == 3
            and all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in p)
            and abs(sum(p) - 1) <= 1e-6)


def validate_bundle(data):
    if (not isinstance(data, dict) or data.get('version') != 1
            or data.get('kind') != 'public_historical_pilot'
            or any(not isinstance(data.get(key), list) for key in
                   ('rows', 'summary', 'agreement', 'model_differences', 'paired_differences'))
            or not data['rows']):
        raise ValueError('Comparativo histórico incompatível.')
    seen = set()
    contexts = set()
    for row in data['rows']:
        identity = row['market'], row['horizon'], row['origin'], row['ticker']
        if identity in seen or row['market'] not in ('BR', 'US') or row['horizon'] not in (126, 252):
            raise ValueError('Previsões históricas incompatíveis.')
        seen.add(identity)
        contexts.add((row['market'], row['horizon']))
        if not row['origin'] < row['entry_date'] < row['target_date'] <= data['asof'] or row['fundamental_available'] > row['origin']:
            raise ValueError('Datas históricas incompatíveis.')
        if type(row['label']) is not int or row['label'] not in range(3):
            raise ValueError('Classe histórica incompatível.')
        if set(row['probabilities']) != set(MODELS) or not all(valid_probabilities(p) for p in row['probabilities'].values()):
            raise ValueError('Probabilidades históricas incompatíveis.')
        if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value))
               for value in row['fundamental_values'].values()):
            raise ValueError('Indicadores históricos incompatíveis.')
    if contexts != {(market, horizon) for market in ('BR', 'US') for horizon in (126, 252)}:
        raise ValueError('Mercado ou prazo ausente no comparativo histórico.')
    for market, horizon in contexts:
        if not any(r['market'] == market and r['horizon'] == horizon
                   and (r['model_a'], r['model_b']) == ('lgb_company', 'tabpfn') for r in data['agreement']):
            raise ValueError('Histórico de concordância ausente.')
        names = {r['model'] for r in data['summary'] if r['market'] == market and r['horizon'] == horizon}
        if not set((*MODELS, 'average_two')) <= names:
            raise ValueError('Avaliação histórica ausente.')
    return data


@lru_cache(maxsize=2)
def _load(path, modified, size):
    if size > 1_000_000:
        raise ValueError('Comparativo histórico muito grande.')
    return validate_bundle(json.loads(Path(path).read_text(encoding='utf-8')))


def dataset(root):
    path = Path(root) / 'static/model-comparison-data.json'
    stat = path.stat()
    return _load(str(path.absolute()), stat.st_mtime_ns, stat.st_size)


def query_values(query):
    if not isinstance(query, dict) or set(query) - PARAMETERS or any(not isinstance(v, str) or len(v) > 40 for v in query.values()):
        raise ValueError('Escolha mercado, prazo, empresa e data do comparativo.')
    market = query.get('market', 'US') or 'US'
    horizon = query.get('horizon', '126') or '126'
    if market not in ('BR', 'US') or horizon not in ('126', '252'):
        raise ValueError('Escolha Brasil ou EUA e um prazo de 6 ou 12 meses.')
    return market, int(horizon), query.get('ticker', ''), query.get('origin', '')


def public_state(root, query, average_enabled=False):
    market, horizon, ticker, origin = query_values(query)
    enabled = average_enabled is True
    try:
        data = dataset(root)
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unavailable', 'average_enabled': enabled,
                'reason': 'O teste histórico de longo prazo não está disponível nesta versão.'}
    rows = [r for r in data['rows'] if r['market'] == market and r['horizon'] == horizon]
    tickers = sorted({r['ticker'] for r in rows})
    origins = sorted({r['origin'] for r in rows}, reverse=True)
    ticker = ticker or tickers[0]
    if ticker not in tickers:
        raise ValueError('Esta empresa não participa deste teste. Escolha uma empresa da amostra.')
    origins_for_ticker = [day for day in origins if any(r['ticker'] == ticker and r['origin'] == day for r in rows)]
    origin = origin or origins_for_ticker[0]
    selected = next((r for r in rows if r['ticker'] == ticker and r['origin'] == origin), None)
    if selected is None:
        raise ValueError('Não existe previsão histórica para esta empresa e data.')
    probabilities = {name: list(selected['probabilities'][name]) for name in MODELS}
    if enabled:
        probabilities['average_two'] = [(a + b) / 2 for a, b in zip(probabilities['lgb_company'], probabilities['tabpfn'])]
    a, b = (unique_class(probabilities[name]) for name in ('lgb_company', 'tabpfn'))
    agreement_status = 'ambiguous' if a is None or b is None else 'agree' if a == b else 'disagree'
    names = (*MODELS, 'average_two') if enabled else MODELS
    context = lambda r: r['market'] == market and r['horizon'] == horizon
    historical = next(r for r in data['agreement'] if context(r) and (r['model_a'], r['model_b']) == ('lgb_company', 'tabpfn'))
    return {'status': 'ready', 'kind': 'historical', 'asof': data['asof'],
            'source_sha256': data['source_sha256'], 'average_enabled': enabled,
            'selection': {'market': market, 'horizon': str(horizon), 'ticker': ticker, 'origin': origin},
            'options': {'tickers': tickers, 'origins': origins_for_ticker},
            'company': {'ticker': ticker, 'sector': selected['sector'], 'period': selected['fundamental_period'],
                        'available': selected['fundamental_available'],
                        'metrics': [{'key': k, 'label': label, 'value': selected['fundamental_values'].get(k)} for k, label in METRICS.items()]},
            'forecast': {'origin': origin, 'entry_date': selected['entry_date'], 'target_date': selected['target_date'],
                         'observed_class': selected['label'], 'observed_label': CLASSES[selected['label']],
                         'models': [{'id': name, 'label': LABELS[name], 'probabilities': probabilities[name],
                                     'class': unique_class(probabilities[name])} for name in names]},
            'current_agreement': {'status': agreement_status, 'class': a if agreement_status == 'agree' else None,
                'probability_distance': sum(abs(x - y) for x, y in zip(probabilities['lgb_company'], probabilities['tabpfn'])) / 2},
            'history': {'market': market, 'horizon': horizon, 'tickers': tickers,
                        'count': len(rows), 'dates': len(origins), 'agreement': historical,
                        'models': [r for r in data['summary'] if context(r) and r['model'] in names],
                        'paired_differences': [r for r in data['model_differences'] if context(r)]
                            + [r for r in data['paired_differences'] if context(r) and enabled and r['model'] == 'average_two']},
            'class_labels': list(CLASSES),
            'limitations': ['Amostra fixa de 12 empresas sobreviventes, em poucos setores.',
                            'Concordância é uma relação entre modelos; não é confiança de acerto futuro.',
                            'Probabilidades experimentais; calibração ainda não demonstrada.',
                            'Os percentuais de eficácia medem redução de erro, não rentabilidade.',
                            'Reprodução histórica; este seguimento reutiliza o teste anterior.',
                            'Os indicadores financeiros são históricos e usam ativos e patrimônio no fim do período.']}
