"""Own-history valuation multiples: monthly closes against statements public at the time.

Each month uses only statements whose filing deadline had passed (ITR 45 days,
DFP 3 months), closes adjusted for splits but not for dividends, and figures of
the trailing 12 months. Stocks use today's share count, implied from a dated
per-share figure of the same balance; buybacks or issuances shift past levels,
so readings rely on percentiles and the median, not on a single average.
"""
from datetime import date, datetime, timedelta, timezone
import math
import statistics
import urllib.parse

from aporte_brasil.portfolio import sector_analysis

KIND = 'issuer_price_history'
KINDS = (KIND,)
WINDOWS = (3, 5, 10)
DEFAULT_WINDOW = 5
MIN_MONTHS = 24
SOURCE = 'Yahoo Finance · chart/'

METRICS = {
    'pe': ('P/L', '×', 'lower', 'Valor de mercado ÷ lucro líquido dos 12 meses do último balanço divulgado. Meses com lucro zero ou negativo ficam fora.'),
    'pvp': ('P/VP', '×', 'lower', 'Valor de mercado ÷ patrimônio líquido do último balanço divulgado.'),
    'ev_ebitda': ('EV/EBITDA', '×', 'lower', '(Valor de mercado + dívida financeira − caixa e aplicações) ÷ EBITDA de 12 meses. EBITDA zero ou negativo fica fora.'),
    'psr': ('P/Receita (PSR)', '×', 'lower', 'Valor de mercado ÷ receita líquida de 12 meses.'),
    'dy': ('Dividend yield', '%', 'higher', 'Proventos por ação com data ex nos 12 meses anteriores ÷ cotação do mês. Inclui JCP bruto quando a fonte inclui.'),
    'net_debt_ebitda': ('Dívida líquida/EBITDA', '×', 'risk', '(Dívida financeira − caixa e aplicações) ÷ EBITDA de 12 meses. Não é múltiplo de preço: mostra se a alavancagem está acima do usual da própria empresa.'),
}
FII_DEFINITIONS = {
    'pvp': 'Cotação do mês ÷ valor patrimonial por cota do último informe mensal da CVM já divulgado, corrigido por desdobramentos.',
    'dy': 'Rendimentos por cota com data ex nos 12 meses anteriores ÷ cotação do mês. Amortizações podem aparecer como proventos na fonte.',
}
FINANCIAL = ('bank', 'insurance', 'financial_services')
CYCLICAL = ('commodity', 'metals', 'food_agro', 'industrial')
SECTORS = {
    'bank': (('pvp', 'pe'), ('dy',), 'Bancos: o patrimônio é a base do capital regulatório e a dívida faz parte da operação. P/VP (lido junto com o ROE) e P/L são os múltiplos usuais; EV/EBITDA não se aplica.'),
    'insurance': (('pe', 'pvp'), ('dy',), 'Seguradoras: lucro e patrimônio. EV/EBITDA não se aplica. O resultado financeiro sobe e desce com os juros, o que muda o P/L entre ciclos.'),
    'financial_services': (('pe', 'pvp'), ('dy',), 'Serviços financeiros e holdings: lucro e patrimônio. Confirme se as receitas são recorrentes antes de comparar períodos.'),
    'utility': (('ev_ebitda', 'dy'), ('pe', 'pvp', 'net_debt_ebitda'), 'Energia e saneamento: ativos longos e dívida relevante. EV/EBITDA e dividendos são as leituras usuais. Revisões tarifárias, concessões e investimentos mudam o patamar.'),
    'commodity': (('ev_ebitda',), ('pe', 'dy', 'pvp', 'net_debt_ebitda'), 'Commodities: EV/EBITDA ao longo do ciclo. Múltiplo baixo com preços da commodity no pico costuma ser armadilha, porque o lucro cai junto com o preço.'),
    'metals': (('ev_ebitda',), ('pe', 'dy', 'pvp', 'net_debt_ebitda'), 'Mineração e siderurgia: EV/EBITDA ao longo do ciclo. Múltiplo baixo com preços no pico costuma ser armadilha, porque o lucro cai junto com o preço.'),
    'retail': (('ev_ebitda', 'pe'), ('psr', 'net_debt_ebitda'), 'Varejo: EV/EBITDA e P/L. P/Receita ajuda quando a margem oscila. Confira arrendamentos (IFRS 16) no EBITDA e na dívida.'),
    'construction': (('pvp', 'pe'), ('dy', 'net_debt_ebitda'), 'Construção e incorporação: P/VP (terrenos e obras ficam no patrimônio) e P/L.'),
    'transport': (('ev_ebitda',), ('pe', 'net_debt_ebitda'), 'Transportes e logística: capital intensivo e endividado; EV/EBITDA é a leitura usual. Confira arrendamentos.'),
    'telecom': (('ev_ebitda', 'dy'), ('pe', 'net_debt_ebitda'), 'Telecomunicações: EV/EBITDA e dividendos; investimento em rede pesa no caixa.'),
    'technology': (('pe', 'psr'), ('ev_ebitda',), 'Tecnologia: P/L e P/Receita. O crescimento muda o múltiplo justo; compare com a expectativa de crescimento (PEG).'),
    'health': (('ev_ebitda', 'pe'), ('net_debt_ebitda',), 'Saúde: EV/EBITDA e P/L; aquisições mudam a base de comparação.'),
    'education': (('ev_ebitda', 'pe'), ('net_debt_ebitda',), 'Educação: EV/EBITDA e P/L; confira arrendamentos e mudanças regulatórias.'),
    'food_agro': (('ev_ebitda', 'pe'), ('dy', 'net_debt_ebitda'), 'Alimentos e agronegócio: EV/EBITDA e P/L; ciclo de grãos e proteínas pode inflar o lucro.'),
    'industrial': (('pe', 'ev_ebitda'), ('pvp', 'dy', 'net_debt_ebitda'), 'Indústria: P/L e EV/EBITDA. Setor cíclico: o ideal é olhar o lucro normalizado.'),
    'general': (('pe', 'ev_ebitda'), ('pvp', 'dy', 'net_debt_ebitda'), 'Empresas não financeiras: P/L e EV/EBITDA; P/VP e dividendos servem de conferência.'),
    'fii': (('pvp', 'dy'), (), 'FIIs: P/VP (cota ÷ patrimônio por cota do informe CVM) e dividend yield. Compare dentro do mesmo segmento: papel, tijolo e fundos de fundos têm patamares diferentes.'),
}
REFERENCES = [
    {'title': 'Damodaran · Choosing the right multiple, tabela 35.1 (múltiplos usuais por setor)', 'url': 'https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch35e.pdf'},
    {'title': 'Damodaran · Relative valuation: escolha do múltiplo por setor', 'url': 'https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/relchoic.pdf'},
    {'title': 'CVM · Resolução 80/2022: prazos de ITR (45 dias) e DFP (3 meses)', 'url': 'https://conteudo.cvm.gov.br/legislacao/resolucoes/resol080.html'},
]
READINGS = {'well_below': 'Bem abaixo do histórico', 'below': 'Abaixo do histórico', 'typical': 'Na faixa típica',
            'above': 'Acima do histórico', 'well_above': 'Bem acima do histórico', 'unknown': 'Sem histórico suficiente'}


def _finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def _day(v):
    return date.fromisoformat(str(v)[:10])


def symbol(a):
    return a['ticker'] + '.SA'


# --- stored price history ---------------------------------------------------

def validate_snapshot(app, d):
    fields = {'symbol', 'months', 'dividends', 'splits', 'first_date', 'source_url'}
    if not isinstance(d, dict) or set(d) != fields or not isinstance(d['symbol'], str) or not d['symbol'].endswith('.SA'):
        raise ValueError('Histórico de preços para múltiplos inválido.')
    today = app.today().isoformat()

    def past(v):
        ref = app.valid_date(v)
        if ref > today:
            raise ValueError('Histórico de preços com data futura.')
        return ref
    if not isinstance(d['months'], list) or not 1 <= len(d['months']) <= 140:
        raise ValueError('Informe de 1 a 140 fechamentos mensais.')
    months = []
    for r in d['months']:
        if not isinstance(r, dict) or set(r) != {'date', 'close'} or not _finite(r['close']) or r['close'] <= 0:
            raise ValueError('Fechamento mensal inválido.')
        months.append({'date': past(r['date']), 'close': float(r['close'])})
    if len({r['date'][:7] for r in months}) != len(months):
        raise ValueError('Mês repetido no histórico de preços.')
    if not isinstance(d['dividends'], list) or len(d['dividends']) > 600:
        raise ValueError('Lista de proventos inválida.')
    dividends = []
    for r in d['dividends']:
        if not isinstance(r, dict) or set(r) != {'date', 'amount'} or not _finite(r['amount']) or r['amount'] < 0:
            raise ValueError('Provento inválido.')
        dividends.append({'date': past(r['date']), 'amount': float(r['amount'])})
    if len({r['date'] for r in dividends}) != len(dividends):
        raise ValueError('Provento duplicado na mesma data.')
    if not isinstance(d['splits'], list) or len(d['splits']) > 30:
        raise ValueError('Lista de desdobramentos inválida.')
    splits = []
    for r in d['splits']:
        if not isinstance(r, dict) or set(r) != {'date', 'ratio'} or not _finite(r['ratio']) or r['ratio'] <= 0:
            raise ValueError('Desdobramento ou grupamento inválido.')
        splits.append({'date': past(r['date']), 'ratio': float(r['ratio'])})
    first = past(d['first_date'])
    if months and first > min(r['date'] for r in months):
        raise ValueError('Início da série posterior aos fechamentos.')
    url = app.validate_url(d['source_url'])
    if url != 'https://finance.yahoo.com/quote/' + d['symbol'] + '/history/':
        raise ValueError('Fonte do histórico de preços inválida.')
    return {'symbol': d['symbol'], 'months': sorted(months, key=lambda r: r['date']), 'dividends': sorted(dividends, key=lambda r: r['date']),
            'splits': sorted(splits, key=lambda r: r['date']), 'first_date': first, 'source_url': url}


def fetch(app, a, years=10):
    """Yahoo `close` is split-adjusted only; `adjclose` would also subtract dividends."""
    if a['asset_type'] not in ('stock', 'fii'):
        raise ValueError('Histórico de múltiplos disponível para ações e FIIs da B3.')
    ticker = symbol(a)
    start = date(app.today().year - years, app.today().month, 1)
    end = app.today() + timedelta(days=1)
    stamp = lambda d: int(datetime.combine(d, datetime.min.time(), timezone.utc).timestamp())
    query = urllib.parse.urlencode({'period1': stamp(start), 'period2': stamp(end), 'interval': '1d', 'events': 'div,splits'})
    raw = app.request_json('https://query1.finance.yahoo.com/v8/finance/chart/' + ticker + '?' + query)
    try:
        r = raw['chart']['result'][0]
    except (KeyError, TypeError, IndexError):
        raise ValueError('Yahoo sem histórico de preços reconhecido.') from None
    if r.get('meta', {}).get('symbol') != ticker or r['meta'].get('currency') != 'BRL':
        raise ValueError('Ticker ou moeda do histórico não confirmados.')
    try:
        closes = r['indicators']['quote'][0]['close']
    except (KeyError, TypeError, IndexError):
        raise ValueError('Yahoo sem fechamentos sem ajuste de proventos.') from None
    today = app.today()
    months = {}
    first = None
    for ts, close in zip(r.get('timestamp') or [], closes or []):
        if not _finite(close) or close <= 0 or not _finite(ts):
            continue
        ref = datetime.fromtimestamp(ts, timezone.utc).date()
        if ref > today:
            continue
        first = min(first or ref, ref)
        key = ref.isoformat()[:7]
        if key not in months or months[key]['date'] < ref.isoformat():
            months[key] = {'date': ref.isoformat(), 'close': float(close)}
    if len(months) < 2:
        raise ValueError('Histórico de preços curto demais para comparar múltiplos.')
    events = r.get('events') or {}
    dividends = {}
    for e in (events.get('dividends') or {}).values():
        if not isinstance(e, dict) or not _finite(e.get('date')) or not _finite(e.get('amount')) or e['amount'] < 0:
            continue
        ref = datetime.fromtimestamp(e['date'], timezone.utc).date().isoformat()
        if ref <= today.isoformat():
            dividends[ref] = dividends.get(ref, 0) + float(e['amount'])
    splits = []
    for e in (events.get('splits') or {}).values():
        if not isinstance(e, dict) or not _finite(e.get('date')):
            continue
        num, den = e.get('numerator'), e.get('denominator')
        if _finite(num) and _finite(den) and num > 0 and den > 0:
            ref = datetime.fromtimestamp(e['date'], timezone.utc).date().isoformat()
            if ref <= today.isoformat():
                splits.append({'date': ref, 'ratio': num / den})
    return validate_snapshot(app, {'symbol': ticker, 'months': sorted(months.values(), key=lambda m: m['date'])[-140:],
        'dividends': [{'date': k, 'amount': v} for k, v in sorted(dividends.items())][-600:], 'splits': splits[-30:],
        'first_date': first.isoformat(), 'source_url': 'https://finance.yahoo.com/quote/' + ticker + '/history/'})


def fresh(snapshot, hours=24):
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['retrieved_at'])).total_seconds()
        return 0 <= elapsed < hours * 3600
    except (KeyError, TypeError, ValueError):
        return False


def refresh(app, a, force=False):
    with app.connect() as c:
        row = c.execute('SELECT ticker,asset_type,archived FROM assets WHERE id=?', (a['id'],)).fetchone()
        if not row or row['archived'] or row['ticker'] != a['ticker']:
            raise ValueError('O ativo mudou; consulte novamente.')
        old = app.latest(c, a['id']).get(KIND)
    if old and fresh(old) and not force:
        return {'received': [], 'used_cache': True}
    payload = fetch(app, a)
    source = SOURCE + payload['symbol'] + ' · fechamentos sem ajuste de proventos'
    with app.WRITE_LOCK, app.connect() as c:
        row = c.execute('SELECT ticker,archived FROM assets WHERE id=?', (a['id'],)).fetchone()
        if not row or row['archived'] or row['ticker'] != a['ticker']:
            raise ValueError('O ativo mudou durante a consulta.')
        # One complete window replaces the previous one; vintages are never stitched.
        c.execute('DELETE FROM snapshots WHERE asset_id=? AND kind=?', (a['id'], KIND))
        app.add_snapshot(c, a['id'], KIND, payload, source, payload['months'][-1]['date'])
        app.log_source(c, KIND + '_' + str(a['id']), a['ticker'] + ' · histórico de preços e proventos para múltiplos', payload['source_url'], asof=payload['months'][-1]['date'])
    return {'received': [KIND], 'used_cache': False}


def action(app, d):
    if not isinstance(d, dict) or type(d.get('asset_id')) is not int or not isinstance(d.get('force', False), bool):
        raise ValueError('Escolha um ativo válido.')
    with app.connect() as c:
        row = c.execute('SELECT * FROM assets WHERE id=? AND archived=0', (d['asset_id'],)).fetchone()
    if not row or row['asset_type'] not in ('stock', 'fii') or not row['verified']:
        raise ValueError('Histórico de múltiplos disponível para ações e FIIs verificados da B3.')
    return refresh(app, dict(row), d.get('force', False))


# --- statements available at each date ----------------------------------------

def periods(statements):
    """Trailing-12-month flows and balances by period end, with the filing lag."""
    if not statements:
        return []
    flows_keys = ('net_income', 'ebitda', 'revenue')
    balance_keys = ('equity', 'debt', 'cash')
    out = {}
    for row in statements.get('annual', []):
        end = _day(row['date'])
        out[end] = {'end': end, 'lag': 90, 'flows': {k: row.get(k) for k in flows_keys},
                    'balance': {k: row.get(k) for k in balance_keys}, 'basis': 'exercício anual'}
    quarters = statements.get('quarterly', [])
    for i, row in enumerate(quarters):
        end = _day(row['date'])
        window = quarters[max(0, i - 3):i + 1]
        consecutive = len(window) == 4 and all(65 <= (_day(y['date']) - _day(x['date'])).days <= 115 for x, y in zip(window, window[1:]))
        flows = {k: sum(r[k] for r in window) if consecutive and all(_finite(r.get(k)) for r in window) else None for k in flows_keys}
        balance = {k: row.get(k) for k in balance_keys}
        if end in out:
            # Audited annual flows win; a quarter only fills missing fields.
            for k in flows_keys:
                if out[end]['flows'][k] is None:
                    out[end]['flows'][k] = flows[k]
            for k in balance_keys:
                if out[end]['balance'][k] is None:
                    out[end]['balance'][k] = balance[k]
        else:
            out[end] = {'end': end, 'lag': 90 if end.month == 12 else 45, 'flows': flows, 'balance': balance, 'basis': '4 trimestres isolados'}
    return sorted(out.values(), key=lambda p: p['end'])


def _period(rows, when, fields, published=True, stale=460):
    """Latest period with every field, already public at `when` (filing lag)."""
    for p in reversed(rows):
        if p['end'] > when or published and p['end'] + timedelta(days=p['lag']) > when:
            continue
        if (when - p['end']).days > stale:
            return None
        values = {**p['flows'], **p['balance']}
        if all(_finite(values.get(k)) for k in fields):
            return p
    return None


def _company_value(key, price, shares, p):
    f, b = p['flows'], p['balance']
    cap = price * shares
    if key == 'pe':
        return cap / f['net_income'] if f['net_income'] > 0 else None
    if key == 'pvp':
        return cap / b['equity'] if b['equity'] > 0 else None
    if key == 'psr':
        return cap / f['revenue'] if f['revenue'] > 0 else None
    if key == 'ev_ebitda':
        return (cap + b['debt'] - b['cash']) / f['ebitda'] if f['ebitda'] > 0 else None
    if key == 'net_debt_ebitda':
        return (b['debt'] - b['cash']) / f['ebitda'] if f['ebitda'] > 0 else None
    return None


NEEDS = {'pe': ('net_income',), 'pvp': ('equity',), 'psr': ('revenue',), 'ev_ebitda': ('ebitda', 'debt', 'cash'), 'net_debt_ebitda': ('ebitda', 'debt', 'cash')}


def implied_shares(a, rows):
    """Shares = equity ÷ published book value per share (or 12m profit ÷ EPS) at the same balance date."""
    found = []
    for kind in ('statistics', 'public', 'financial'):
        s = a.get('snapshots', {}).get(kind)
        if not s:
            continue
        try:
            ref = _day(s.get('asof'))
        except (TypeError, ValueError):
            continue
        near = [p for p in rows if abs((p['end'] - ref).days) <= 7]
        if not near:
            continue
        p = near[-1]
        data = s.get('data', {})
        bvps, eps = data.get('bvps'), data.get('eps')
        equity, profit = p['balance'].get('equity'), p['flows'].get('net_income')
        if _finite(bvps) and bvps > 0 and _finite(equity) and equity > 0:
            found.append({'asof': ref.isoformat(), 'priority': 1, 'shares': equity / bvps, 'source': s.get('source', kind),
                          'basis': 'Patrimônio do balanço de ' + p['end'].isoformat() + ' ÷ VPA publicado'})
        if _finite(eps) and eps > 0 and _finite(profit) and profit > 0:
            found.append({'asof': ref.isoformat(), 'priority': 0, 'shares': profit / eps, 'source': s.get('source', kind),
                          'basis': 'Lucro de 12 meses até ' + p['end'].isoformat() + ' ÷ LPA publicado'})
    if not found:
        return None
    chosen = max(found, key=lambda x: (x['asof'], x['priority']))
    peers = [x['shares'] for x in found if x['asof'] == chosen['asof'] and x is not chosen]
    warning = ''
    if any(abs(x / chosen['shares'] - 1) > .2 for x in peers):
        warning = 'O número de ações implícito no VPA e no LPA diverge mais de 20%; confira classes de ações e units antes de usar os níveis absolutos.'
    return {**{k: chosen[k] for k in ('asof', 'shares', 'source', 'basis')}, 'warning': warning}


# --- statistics ------------------------------------------------------------------

def _round(v):
    return float(f'{v:.8g}')


def stats(values, current):
    n = len(values)
    if n < MIN_MONTHS:
        return {'available': False, 'count': n}
    ordered = sorted(values)
    mean = statistics.fmean(values)
    median = statistics.median(values)
    sd = statistics.stdev(values) if n > 1 else 0
    q = statistics.quantiles(ordered, n=4, method='inclusive')
    out = {'available': True, 'count': n, 'mean': mean, 'median': median, 'stdev': sd, 'min': ordered[0], 'max': ordered[-1],
           'p25': q[0], 'p75': q[2], 'vs_mean': None, 'vs_median': None, 'zscore': None, 'percentile': None}
    if _finite(current):
        out.update(vs_mean=(current / mean - 1) * 100 if mean > 0 else None,
                   vs_median=(current / median - 1) * 100 if median > 0 else None,
                   zscore=(current - mean) / sd if sd > 0 else None,
                   percentile=(sum(v < current for v in values) + .5 * sum(v == current for v in values)) / n * 100)
    return out


def reading(s):
    if not s.get('available') or s.get('percentile') is None or s.get('vs_median') is None:
        return 'unknown'
    p, dev = s['percentile'], s['vs_median']
    if p <= 20 and dev <= -10:
        return 'well_below'
    if p <= 40 and dev < 0:
        return 'below'
    if p >= 80 and dev >= 10:
        return 'well_above'
    if p >= 60 and dev > 0:
        return 'above'
    return 'typical'


def signal(direction, level):
    """Valuation signal from the multiple's position; leverage is risk, not price."""
    if level == 'unknown' or direction == 'risk':
        return 'none'
    cheap = level in ('well_below', 'below') if direction == 'lower' else level in ('well_above', 'above')
    rich = level in ('well_above', 'above') if direction == 'lower' else level in ('well_below', 'below')
    strong = level in ('well_below', 'well_above')
    return ('cheap_strong' if strong else 'cheap') if cheap else ('expensive_strong' if strong else 'expensive') if rich else 'neutral'


def summary(metrics, primary, years):
    assessed = []
    for key in primary:
        m = metrics.get(key)
        if not m:
            continue
        s = m['windows'][str(years)]
        if s.get('signal', 'none') != 'none':
            assessed.append((m['label'], s['signal']))
    cheap = [l for l, s in assessed if s.startswith('cheap')]
    rich = [l for l, s in assessed if s.startswith('expensive')]
    if not assessed:
        status, text = 'unknown', 'Sem histórico suficiente nos indicadores principais do setor para esta janela.'
    elif len(cheap) == len(assessed):
        status, text = 'below', 'Abaixo do próprio histórico nos indicadores principais do setor (' + ', '.join(cheap) + ').'
    elif len(rich) == len(assessed):
        status, text = 'above', 'Acima do próprio histórico nos indicadores principais do setor (' + ', '.join(rich) + ').'
    elif cheap and rich:
        status, text = 'mixed', 'Sinais mistos: abaixo em ' + ', '.join(cheap) + ' e acima em ' + ', '.join(rich) + '.'
    elif cheap:
        status, text = 'partly_below', 'Parcialmente abaixo do histórico (' + ', '.join(cheap) + '); os demais indicadores principais estão na faixa típica.'
    elif rich:
        status, text = 'partly_above', 'Parcialmente acima do histórico (' + ', '.join(rich) + '); os demais indicadores principais estão na faixa típica.'
    else:
        status, text = 'typical', 'Na faixa típica do próprio histórico nos indicadores principais do setor.'
    return {'status': status, 'text': text, 'assessed': len(assessed)}


# --- analysis ----------------------------------------------------------------------

def _price(a, age):
    quote = a.get('snapshots', {}).get('quote', {})
    price = quote.get('data', {}).get('price')
    if _finite(price) and price > 0 and age(quote.get('asof')) <= 7:
        return {'value': price, 'asof': quote['asof']}
    return None


def _dividends_12m(events, when):
    start = (when - timedelta(days=365)).isoformat()
    return sum(r['amount'] for r in events if start < r['date'] <= when.isoformat())


def _split_factor(splits, after):
    factor = 1.0
    for s in splits:
        if s['date'] > after:
            factor *= s['ratio']
    return factor


def analyze(a, age, today):
    """Monthly own-history multiples and their position, by the sector's usual indicators."""
    profile = sector_analysis.profile(a)
    base = {'applicable': False, 'profile': profile, 'default_window': DEFAULT_WINDOW, 'windows': list(WINDOWS)}
    if a.get('asset_type') not in ('stock', 'fii') or profile not in SECTORS:
        return {**base, 'status': 'not_applicable', 'message': 'Comparação com o próprio histórico disponível para ações e FIIs da B3.'}
    primary, secondary, note = SECTORS[profile]
    label = sector_analysis.PROFILES.get(profile, {}).get('label', profile)
    result = {**base, 'applicable': True, 'profile_label': label, 'sector_note': note, 'primary': list(primary), 'secondary': list(secondary),
              'metrics': {}, 'summary': {}, 'warnings': [], 'references': REFERENCES,
              'caveats': ['Múltiplo abaixo da média não prova que a ação está barata: lucro no pico do ciclo, piora das perspectivas ou juros mais altos que a média do período também derrubam múltiplos.',
                          'Cada mês usa só balanços já divulgados nos prazos da CVM (ITR em 45 dias, DFP em 3 meses), para não usar informação que ainda não existia.',
                          'A comparação é com a própria empresa. Mudança de negócio, aquisições, cisões ou de padrão contábil quebram a comparabilidade.']}
    snap = a.get('snapshots', {}).get(KIND)
    price = _price(a, age)
    result['price'] = price
    if not snap:
        result.update(status='missing_prices', message='Busque o histórico de preços e proventos (10 anos) para montar as séries mensais.')
        return result
    d = snap['data']
    result['history'] = {'start': d['months'][0]['date'], 'end': d['months'][-1]['date'], 'months': len(d['months']), 'source': snap.get('source', ''),
                         'retrieved_at': snap.get('retrieved_at', ''), 'url': d['source_url'], 'splits': d['splits']}
    month_start = today.replace(day=1).isoformat()
    months = [m for m in d['months'] if m['date'] < month_start]
    first = _day(d['first_date'])
    series = {}
    current = {}
    if profile == 'fii':
        result['caveats'][1] = 'Cada mês usa só o informe mensal da CVM que já tinha sido divulgado (até 30 dias após o mês de referência).'
        reports = sorted(a.get('snapshots', {}).get('fii_reports', {}).get('data', {}).get('monthly', []), key=lambda r: r['date'])
        navs = [r for r in reports if _finite(r.get('nav')) and r['nav'] > 0]

        def nav_at(when, published=True):
            for r in reversed(navs):
                end = _day(r['date'])
                if end <= when and (not published or end + timedelta(days=30) <= when) and (when - end).days <= 120:
                    return r['nav'] / _split_factor(d['splits'], r['date'])
            return None
        if not navs:
            result['warnings'].append('Sem informes mensais da CVM guardados: atualize a pesquisa do FII para obter o P/VP histórico.')
        for m in months:
            when = _day(m['date'])
            nav = nav_at(when)
            if nav:
                series.setdefault('pvp', []).append((m['date'], m['close'] / nav))
            if (when - timedelta(days=365)) >= first:
                series.setdefault('dy', []).append((m['date'], _dividends_12m(d['dividends'], when) / m['close'] * 100))
        if price:
            when = _day(price['asof'])
            nav = nav_at(when, published=False)
            if nav:
                current['pvp'] = (price['value'] / nav, price['asof'], 'Cotação ÷ VPA do último informe CVM')
            if (when - timedelta(days=365)) >= first:
                current['dy'] = (_dividends_12m(d['dividends'], when) / price['value'] * 100, price['asof'], 'Rendimentos com data ex em 12 meses ÷ cotação')
    else:
        rows = periods(a.get('snapshots', {}).get('issuer_statements', {}).get('data'))
        keys = [k for k in (*primary, *secondary) if k != 'dy']
        shares = implied_shares(a, rows) if rows else None
        result['shares'] = shares
        if not rows:
            result['warnings'].append('Sem demonstrações guardadas: atualize a pesquisa da empresa para calcular P/L, P/VP e EV/EBITDA históricos.')
        elif not shares:
            result['warnings'].append('Sem VPA ou LPA publicado na mesma data de um balanço guardado; os múltiplos de preço ficam pendentes. Atualize os indicadores da empresa.')
        if shares and shares['warning']:
            result['warnings'].append(shares['warning'])
        for key in keys:
            if key != 'net_debt_ebitda' and not shares:
                continue
            for m in months:
                p = _period(rows, _day(m['date']), NEEDS[key])
                v = _company_value(key, m['close'], shares['shares'] if shares else 1, p) if p else None
                if v is not None:
                    series.setdefault(key, []).append((m['date'], v))
            if price:
                p = _period(rows, _day(price['asof']), NEEDS[key], published=False)
                v = _company_value(key, price['value'], shares['shares'] if shares else 1, p) if p else None
                if v is not None:
                    current[key] = (v, price['asof'], 'Cotação de ' + price['asof'] + ' · balanço de ' + p['end'].isoformat() + ' (' + p['basis'] + ')')
        if 'dy' in (*primary, *secondary):
            for m in months:
                when = _day(m['date'])
                if (when - timedelta(days=365)) >= first:
                    series.setdefault('dy', []).append((m['date'], _dividends_12m(d['dividends'], when) / m['close'] * 100))
            if price and (_day(price['asof']) - timedelta(days=365)) >= first:
                current['dy'] = (_dividends_12m(d['dividends'], _day(price['asof'])) / price['value'] * 100, price['asof'], 'Proventos com data ex em 12 meses ÷ cotação')
        published = a.get('snapshots', {}).get('statistics', {})
        pe = current.get('pe')
        if pe and _finite(published.get('data', {}).get('pe')) and published['data']['pe'] > 0 and age(published.get('retrieved_at', '')) <= 7:
            if abs(pe[0] / published['data']['pe'] - 1) > .25:
                result['warnings'].append(f"P/L calculado ({pe[0]:.1f}×) difere mais de 25% do publicado pela fonte ({published['data']['pe']:.1f}×). Confira número de ações, classes/units e o lucro usado.")
    if price is None:
        result['warnings'].append('Sem cotação dos últimos 7 dias: o valor atual fica pendente; o histórico continua visível.')
    for key in (*primary, *secondary):
        name, unit, direction, definition = METRICS[key]
        points = series.get(key, [])
        cur = current.get(key)
        windows = {}
        for years in WINDOWS:
            start = date(today.year - years, today.month, 1).isoformat()
            s = stats([v for ref, v in points if ref >= start], cur[0] if cur else None)
            s['start'] = next((ref for ref, _ in points if ref >= start), None)
            s['level'] = reading(s)
            s['reading'] = READINGS[s['level']]
            s['signal'] = signal(direction, s['level'])
            windows[str(years)] = {k: _round(v) if _finite(v) and not isinstance(v, bool) and k not in ('count',) else v for k, v in s.items()}
        result['metrics'][key] = {'key': key, 'label': name, 'unit': unit, 'direction': direction, 'role': 'primary' if key in primary else 'secondary',
            'definition': FII_DEFINITIONS.get(key, definition) if profile == 'fii' else definition,
            'current': {'value': _round(cur[0]), 'asof': cur[1], 'basis': cur[2]} if cur else None,
            'points': [[ref, _round(v)] for ref, v in points], 'windows': windows}
    for years in WINDOWS:
        result['summary'][str(years)] = summary(result['metrics'], primary, years)
    result['status'] = 'ok' if any(m['points'] for m in result['metrics'].values()) else 'missing_statements'
    if profile in CYCLICAL:
        result['warnings'].append('Setor cíclico: compare com cuidado. Múltiplo baixo perto do pico do ciclo costuma anteceder queda de lucro.')
    return result


def valuation_series(asset, key, years=DEFAULT_WINDOW):
    """Same shape as valuation_history.series, from the rebuilt monthly multiples."""
    h = asset.get('multiple_history') or {}
    m = h.get('metrics', {}).get(key)
    if not m:
        return None
    w = m['windows'].get(str(years), {})
    if not w.get('available'):
        return None
    start = w['start']
    rows = [{'date': ref, 'value': v, 'source': 'Reconstruído · cotação mensal × balanço já divulgado'} for ref, v in m['points'] if ref >= start]
    return dict(available=True, count=w['count'], start=rows[0]['date'], end=rows[-1]['date'], mean=w['mean'], median=w['median'], observations=rows,
                note=f'Série mensal reconstruída em {years} anos: fechamento do mês × número atual de ações ÷ balanço já divulgado na data (ITR 45 dias, DFP 3 meses). Média histórica é comparação relativa, não valor justo.')
