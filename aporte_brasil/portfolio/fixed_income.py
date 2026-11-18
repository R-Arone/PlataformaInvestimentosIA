"""Fixed-income calculator: value at maturity, tax, real return, and the comparison
with inflation, Selic, CDI and savings, under explicit rate paths.

Every rate path is a premise the person states. Nothing here forecasts Selic or inflation,
and the result is not the sale price or the statement balance of a security.
"""
from datetime import date, timedelta
import math

from aporte_brasil.portfolio import tax_rules

INDEXERS = ('CDI', 'Selic', 'IPCA+', 'Prefixado')
MONTH = 365.25 / 12
POUPANCA_CAP = 8.5   # Selic above this: 0.5% a month plus TR; at or below: 70% of Selic plus TR
RATE_SHOCK = 3.0     # percentage points on the final CDI/Selic of the scenario
INFLATION_SHOCK = 2.0
WEIGHTS = (.25, .50, .25)  # lower rates, informed scenario, higher rates; editable premise
METHOD = ('Taxas variam linearmente da taxa de hoje até a taxa final informada, em passos mensais; sem taxa final, ficam constantes. '
          '% do CDI capitaliza a taxa diária proporcional em 252 dias úteis por ano. Selic e IPCA+ combinam índice e taxa de forma composta. '
          'O custo anual reduz o rendimento de forma composta. O IR incide sobre o ganho total no fim, pela tabela regressiva '
          'ou pela alíquota informada. Poder de compra: saldo líquido dividido pela inflação acumulada. '
          'Poupança aproximada com TR = 0: 0,5% ao mês com Selic acima de 8,5% a.a.; 70% da Selic, caso contrário.')
NOT_INCLUDED = ('Não reproduz marcação a mercado, come-cotas, IOF, cupons, calendário de dias úteis nem regras de custódia. '
                'O resultado não é o preço de venda antecipada nem o saldo do seu extrato.')


def num(d, key, label, required=False, low=-99.0, high=1000.0):
    v = d.get(key)
    if v in (None, ''):
        if required:
            raise ValueError(f'Informe {label}.')
        return None
    if isinstance(v, bool):
        raise ValueError(f'{label}: número inválido.')
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{label}: número inválido.') from None
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f'{label}: use um valor entre {low:g} e {high:g}.')
    return n


def horizon(d, today):
    maturity = d.get('maturity')
    if maturity not in (None, ''):
        try:
            end = date.fromisoformat(str(maturity)[:10])
        except ValueError:
            raise ValueError('Vencimento: use uma data válida.') from None
        days = (end - today).days
        if not 1 <= days <= 365 * 50:
            raise ValueError('O vencimento precisa estar no futuro, em até 50 anos.')
        return days, end
    months = num(d, 'months', 'o prazo em meses', True, 1, 600)
    days = round(months * MONTH)
    return days, today + timedelta(days=days)


def steps(days):
    months = days / MONTH
    lens = []
    left = months
    while left > 1e-9:
        lens.append(min(1.0, left))
        left -= 1.0
    return months, lens


def path_value(start, end, frac):
    return start if end is None else start + (end - start) * frac


def curves(p, lens, months):
    """Cumulative growth factors at the end of every step: product, CDI, Selic, inflation, savings."""
    out = {k: [1.0] for k in ('product', 'cdi', 'selic', 'ipca', 'poup')}
    elapsed = 0.0
    for ln in lens:
        mid = (elapsed + ln / 2) / months
        cdi = path_value(p['cdi'], p['cdi_end'], mid) if p['cdi'] is not None else None
        selic = path_value(p['selic'], p['selic_end'], mid) if p['selic'] is not None else None
        ipca = path_value(p['ipca'], p['ipca_end'], mid) if p['ipca'] is not None else None
        yrs = ln / 12
        if p['indexer'] == 'CDI':
            daily = (1 + cdi / 100) ** (1 / 252) - 1
            g = (1 + daily * p['rate'] / 100) ** (252 * yrs)
        elif p['indexer'] == 'Selic':
            g = ((1 + selic / 100) * (1 + p['rate'] / 100)) ** yrs
        elif p['indexer'] == 'IPCA+':
            g = ((1 + ipca / 100) * (1 + p['rate'] / 100)) ** yrs
        else:
            g = (1 + p['rate'] / 100) ** yrs
        g /= (1 + p['fee'] / 100) ** yrs
        out['product'].append(out['product'][-1] * g)
        out['cdi'].append(out['cdi'][-1] * ((1 + cdi / 100) ** yrs if cdi is not None else math.nan))
        out['selic'].append(out['selic'][-1] * ((1 + selic / 100) ** yrs if selic is not None else math.nan))
        out['ipca'].append(out['ipca'][-1] * ((1 + ipca / 100) ** yrs if ipca is not None else math.nan))
        if selic is None:
            out['poup'].append(math.nan)
        else:
            month_rate = .005 if selic > POUPANCA_CAP else .7 * selic / 100 / 12
            out['poup'].append(out['poup'][-1] * (1 + month_rate) ** ln)
        elapsed += ln
    return out


def net_value(principal, factor, rate):
    """Balance after tax on the gain; a loss is not taxed."""
    return principal * (1 + (factor - 1) * (1 - rate / 100)) if factor > 1 else principal * factor


def annualize(factor, years):
    return (factor ** (1 / years) - 1) * 100 if factor > 0 and years > 0 else None


def tax_for(product, mode, manual, days):
    ref = tax_rules.reference(product, days)
    if mode == 'auto':
        if not ref['automatic']:
            raise ValueError('Selecione um regime tributário confirmado ou informe o IR personalizado.')
        return ref['rate'], ref
    return manual, ref


def run(p, days, principal, product, mode, manual_tax, today):
    months, lens = steps(days)
    years = days / 365.25
    cv = curves(p, lens, months)
    rate, ref = tax_for(product, mode, manual_tax, days)
    cdb_rate = tax_rules.regressive(days)
    F = cv['product'][-1]
    gross = principal * F
    net = net_value(principal, F, rate)
    result = {'tax_rate': rate, 'tax_ref': ref, 'gross': gross, 'gain': gross - principal,
              'tax': max(0., gross - principal) * rate / 100, 'net': net, 'net_gain': net - principal,
              'net_factor': net / principal, 'net_annual': annualize(net / principal, years),
              'gross_annual': annualize(F, years), 'years': years, 'curves': cv, 'cdb_rate': cdb_rate}
    ipca_f = cv['ipca'][-1]
    if math.isfinite(ipca_f):
        real_factor = (net / principal) / ipca_f
        result['inflation'] = {'cumulative': (ipca_f - 1) * 100, 'annual': annualize(ipca_f, years)}
        result['real'] = {'value': principal * real_factor, 'gain': principal * (real_factor - 1),
                          'annual': annualize(real_factor, years), 'beats': real_factor > 1}
    else:
        result['inflation'], result['real'] = None, None
    return result


def benchmarks(r, principal, product_net_factor):
    """CDI, Selic, savings and inflation over the same horizon and paths."""
    cv, rate = r['curves'], r['cdb_rate']
    out = []
    items = (('cdi', 'CDI (100%) líquido de IR regressivo', cv['cdi'][-1], rate),
             ('selic', 'Selic acumulada líquida de IR regressivo', cv['selic'][-1], rate),
             ('poup', 'Poupança (isenta, TR = 0)', cv['poup'][-1], 0.),
             ('ipca', 'Inflação (manter o poder de compra)', cv['ipca'][-1], 0.))
    for key, label, factor, tax in items:
        if not math.isfinite(factor):
            continue
        net = net_value(principal, factor, tax)
        out.append({'key': key, 'label': label, 'net': net, 'net_gain': net - principal, 'tax_rate': tax,
                    'net_annual': annualize(net / principal, r['years']),
                    'product_minus': principal * product_net_factor - net,
                    'beats': principal * product_net_factor > net + 1e-9})
    return out


def equivalence(r, principal):
    """Gross CDB rate that leaves the same net balance. A 100% CDI CDB equals this product when the average CDI of the period equals that rate."""
    N = r['net_factor']
    t = r['cdb_rate'] / 100
    out = {}
    if N > 1 and t < 1:
        G = 1 + (N - 1) / (1 - t)
        out['cdb_gross_annual'] = annualize(G, r['years'])
        cdi_f = r['curves']['cdi'][-1]
        if math.isfinite(cdi_f) and cdi_f > 1:
            out['cdb_pct_cdi'] = (G - 1) / (cdi_f - 1) * 100
        out['cdb_rate'] = r['cdb_rate']
    out['breakeven_inflation_annual'] = r['net_annual']
    return out


def shocked(p, rate_shock=0., inflation_shock=0.):
    q = dict(p)
    for k in ('cdi_end', 'selic_end'):
        base = p[k] if p[k] is not None else p[k[:-4]]
        q[k] = None if base is None else base + rate_shock
    base_i = p['ipca_end'] if p['ipca_end'] is not None else p['ipca']
    q['ipca_end'] = None if base_i is None else base_i + inflation_shock
    return q


def scenarios(p, days, principal, product, mode, manual_tax, today):
    needs = {'CDI': 'cdi', 'Selic': 'selic', 'IPCA+': 'ipca'}.get(p['indexer'])
    defs = (('low', 'Juros caem 3 p.p.', RATE_SHOCK * -1, 0.), ('base', 'Cenário informado', 0., 0.),
            ('high', 'Juros sobem 3 p.p.', RATE_SHOCK, 0.),
            ('inflation', 'Inflação 2 p.p. maior', 0., INFLATION_SHOCK))
    rows = []
    for key, label, rs, ish in defs:
        if key == 'inflation' and p['ipca'] is None:
            continue
        if key in ('low', 'high') and p['cdi'] is None and p['selic'] is None:
            continue
        q = shocked(p, rs, ish)
        r = run(q, days, principal, product, mode, manual_tax, today)
        rows.append({'key': key, 'label': label, 'cdi_end': q['cdi_end'], 'selic_end': q['selic_end'], 'ipca_end': q['ipca_end'],
                     'net': r['net'], 'net_gain': r['net_gain'], 'net_annual': r['net_annual'],
                     'real': r['real']['value'] if r['real'] else None,
                     'real_annual': r['real']['annual'] if r['real'] else None})
    # An indexer-free product does not move with rates: the three rate scenarios would be identical.
    if needs is None:
        rows = [x for x in rows if x['key'] in ('base', 'inflation')]
    return rows


def expected_value(rows, weights):
    by = {r['key']: r for r in rows}
    if not all(k in by for k in ('low', 'base', 'high')):
        return None
    w = dict(zip(('low', 'base', 'high'), weights))
    out = {'weights': w, 'net': sum(by[k]['net'] * w[k] for k in w)}
    out['net_annual'] = None if any(by[k]['net_annual'] is None for k in w) else sum(by[k]['net_annual'] * w[k] for k in w)
    if all(by[k]['real'] is not None for k in w):
        out['real'] = sum(by[k]['real'] * w[k] for k in w)
        out['real_annual'] = None if any(by[k]['real_annual'] is None for k in w) else sum(by[k]['real_annual'] * w[k] for k in w)
    return out


def points(p, r, principal, product, mode, manual_tax, months, lens, count=60):
    cv = r['curves']
    idx = sorted({round(i * (len(lens)) / count) for i in range(count + 1)} | {len(lens)})
    elapsed = [0.]
    for ln in lens:
        elapsed.append(elapsed[-1] + ln)
    out = []
    for i in idx:
        days = max(1, round(elapsed[i] * MONTH))
        rate = tax_rules.reference(product, days)['rate'] if mode == 'auto' else manual_tax
        factor = cv['product'][i]
        net = net_value(principal, factor, rate)
        point = {'month': elapsed[i], 'net': net, 'gross': principal * factor}
        if math.isfinite(cv['ipca'][i]):
            point['real'] = net / cv['ipca'][i]
        if math.isfinite(cv['cdi'][i]):
            point['cdi_net'] = net_value(principal, cv['cdi'][i], tax_rules.regressive(days))
        out.append(point)
    return out


def analyze(d, today, weights=WEIGHTS):
    """`d` fields: principal, months or maturity, product, tax_mode, tax, indexer, rate, fee,
    cdi/selic/ipca (today) and cdi_end/selic_end/ipca_end (final value of the path)."""
    if not isinstance(d, dict):
        raise ValueError('Dados inválidos.')
    principal = num(d, 'principal', 'o valor do aporte', True, .01, 1e12)
    days, maturity = horizon(d, today)
    indexer = d.get('indexer')
    if indexer not in INDEXERS:
        raise ValueError('Escolha CDI, Selic, IPCA+ ou prefixado.')
    p = {'indexer': indexer, 'rate': num(d, 'rate', 'a taxa do investimento', True, -50, 1000),
         'fee': num(d, 'fee', 'o custo anual', False, 0, 100) or 0.}
    for k, label in (('cdi', 'o CDI'), ('selic', 'a Selic'), ('ipca', 'a inflação')):
        p[k] = num(d, k, label)
        p[k + '_end'] = num(d, k + '_end', label + ' final')
    if p['cdi'] is None and p['selic'] is not None:
        p['cdi'] = p['selic'] - .10   # CDI trades about 0.10 p.p. under the Selic target
        if p['selic_end'] is not None and p['cdi_end'] is None:
            p['cdi_end'] = p['selic_end'] - .10
    needed = {'CDI': ('cdi', 'o CDI'), 'Selic': ('selic', 'a Selic'), 'IPCA+': ('ipca', 'a inflação')}.get(indexer)
    if needed and p[needed[0]] is None:
        raise ValueError(f'Informe {needed[1]} no cenário.')
    product = d.get('product') or 'CDB'
    mode = 'auto' if d.get('tax_mode') == 'auto' else 'manual'
    manual = num(d, 'tax', 'o IR', mode == 'manual', 0, 100)
    r = run(p, days, principal, product, mode, manual, today)
    months, lens = steps(days)
    rows = scenarios(p, days, principal, product, mode, manual, today)
    warnings = []
    if days < 30:
        warnings.append('Prazo menor que 30 dias: pode incidir IOF regressivo sobre o rendimento, que esta calculadora não reproduz.')
    if mode == 'auto' and not r['tax_ref'].get('automatic', True):
        warnings.append('O regime tributário deste produto não é automático.')
    if r['real'] is None:
        warnings.append('Sem inflação informada: o ganho real não pode ser calculado.')
    if p['selic'] is None and p['cdi'] is None:
        warnings.append('Sem CDI ou Selic informados: a comparação com juros não pode ser calculada.')
    result = {
        'inputs': {'principal': principal, 'product': product, 'indexer': indexer, 'rate': p['rate'], 'fee': p['fee'],
                   'tax_mode': mode, 'cdi': p['cdi'], 'cdi_end': p['cdi_end'], 'selic': p['selic'], 'selic_end': p['selic_end'],
                   'ipca': p['ipca'], 'ipca_end': p['ipca_end']},
        'days': days, 'months': days / MONTH, 'years': r['years'], 'maturity': maturity.isoformat(),
        'balances': {'principal': principal, 'gross': r['gross'], 'gain': r['gain'], 'tax': r['tax'], 'tax_rate': r['tax_rate'],
                     'net': r['net'], 'net_gain': r['net_gain']},
        'rates': {'gross_annual': r['gross_annual'], 'net_annual': r['net_annual']},
        'tax_reference': r['tax_ref'],
        'inflation': r['inflation'], 'real': r['real'],
        'benchmarks': benchmarks(r, principal, r['net_factor']),
        'equivalence': equivalence(r, principal),
        'scenarios': rows, 'expected': expected_value(rows, weights),
        'points': points(p, r, principal, product, mode, manual, months, lens),
        'warnings': warnings, 'method': METHOD, 'not_included': NOT_INCLUDED,
    }
    return result
