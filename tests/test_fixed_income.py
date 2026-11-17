from datetime import date
from pathlib import Path
import importlib.util
import json
import sys
import unittest

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('fixed_income', ROOT / 'fixed_income.py')
fi = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fi
spec.loader.exec_module(fi)

TODAY = date(2026, 11, 17)
YEAR = 365.25


def base(**kw):
    d = dict(principal=10000, months=24, product='CDB', tax_mode='auto', indexer='Prefixado', rate=12, fee=0,
             cdi=14.5, selic=14.75, ipca=4.5)
    d.update(kw)
    return d


class FixedIncomeTests(unittest.TestCase):
    def test_prefixed_value_at_maturity_and_regressive_tax(self):
        r = fi.analyze(base(), TODAY)
        days = r['days']
        self.assertEqual(days, round(24 * fi.MONTH))
        gross = 10000 * 1.12 ** (days / YEAR)
        self.assertAlmostEqual(r['balances']['gross'], gross, places=6)
        self.assertEqual(r['balances']['tax_rate'], 15)          # more than 720 days
        self.assertAlmostEqual(r['balances']['net'], 10000 + (gross - 10000) * .85, places=6)
        self.assertAlmostEqual(r['balances']['tax'], (gross - 10000) * .15, places=6)
        self.assertEqual(r['maturity'], '2028-11-16')
        self.assertAlmostEqual(r['rates']['gross_annual'], 12, places=6)

    def test_tax_bracket_changes_with_the_horizon(self):
        short = fi.analyze(base(months=3), TODAY)['balances']['tax_rate']
        mid = fi.analyze(base(months=9), TODAY)['balances']['tax_rate']
        year = fi.analyze(base(months=18), TODAY)['balances']['tax_rate']
        self.assertEqual((short, mid, year), (22.5, 20, 17.5))

    def test_cdi_percentage_and_selic_and_ipca_plus_formulas(self):
        d365 = dict(months=None, maturity='2027-11-17')
        r = fi.analyze(base(indexer='CDI', rate=100, cdi=10, selic=10, ipca=4, **d365), TODAY)
        self.assertEqual(r['days'], 365)
        self.assertAlmostEqual(r['balances']['gross'], 10000 * 1.10 ** (365 / YEAR), places=6)
        r110 = fi.analyze(base(indexer='CDI', rate=110, cdi=10, selic=10, ipca=4, **d365), TODAY)
        daily = 1.10 ** (1 / 252) - 1
        self.assertAlmostEqual(r110['balances']['gross'], 10000 * (1 + daily * 1.1) ** (252 * 365 / YEAR), places=6)
        rs = fi.analyze(base(indexer='Selic', rate=0.1, cdi=10, selic=10, ipca=4, **d365), TODAY)
        self.assertAlmostEqual(rs['balances']['gross'], 10000 * (1.10 * 1.001) ** (365 / YEAR), places=6)
        ri = fi.analyze(base(indexer='IPCA+', rate=6, cdi=10, selic=10, ipca=4, **d365), TODAY)
        self.assertAlmostEqual(ri['balances']['gross'], 10000 * (1.04 * 1.06) ** (365 / YEAR), places=6)

    def test_100_percent_cdi_matches_the_cdi_benchmark(self):
        r = fi.analyze(base(indexer='CDI', rate=100, cdi=11, selic=11, ipca=4), TODAY)
        cdi = next(b for b in r['benchmarks'] if b['key'] == 'cdi')
        self.assertAlmostEqual(cdi['product_minus'], 0, places=6)
        self.assertFalse(cdi['beats'])

    def test_real_return_against_inflation(self):
        r = fi.analyze(base(ipca=5), TODAY)
        deflator = 1.05 ** (r['days'] / YEAR)
        net_factor = r['balances']['net'] / 10000
        self.assertAlmostEqual(r['real']['value'], 10000 * net_factor / deflator, places=6)
        self.assertAlmostEqual(r['inflation']['cumulative'], (deflator - 1) * 100, places=6)
        self.assertTrue(r['real']['beats'])
        self.assertAlmostEqual(r['real']['annual'], ((net_factor / deflator) ** (YEAR / r['days']) - 1) * 100, places=6)
        # inflation that cancels the real gain is the net nominal rate
        self.assertAlmostEqual(r['equivalence']['breakeven_inflation_annual'], r['rates']['net_annual'], places=9)
        high = fi.analyze(base(ipca=r['rates']['net_annual'] + 2), TODAY)
        self.assertFalse(high['real']['beats'])
        self.assertLess(high['real']['gain'], 0)

    def test_exempt_product_and_cdb_equivalent(self):
        r = fi.analyze(base(product='LCI', indexer='CDI', rate=90, cdi=10, selic=10, months=12), TODAY)
        self.assertEqual(r['balances']['tax'], 0)
        self.assertAlmostEqual(r['balances']['net'], r['balances']['gross'], places=9)
        eq = r['equivalence']
        t = r['equivalence']['cdb_rate'] / 100
        N = r['balances']['net'] / 10000
        G = 1 + (N - 1) / (1 - t)
        self.assertAlmostEqual(eq['cdb_gross_annual'], (G ** (YEAR / r['days']) - 1) * 100, places=6)
        self.assertGreater(eq['cdb_pct_cdi'], 90)   # a CDB must pay more than 90% to match an exempt 90%
        self.assertGreater(eq['cdb_gross_annual'], r['rates']['gross_annual'])

    def test_linear_rate_path_is_between_the_constant_cases(self):
        kw = dict(indexer='Selic', rate=0, ipca=4, months=24, tax_mode='manual', tax=0)
        down = fi.analyze(base(selic=14, selic_end=10, **kw), TODAY)['balances']['gross']
        high = fi.analyze(base(selic=14, **kw), TODAY)['balances']['gross']
        low = fi.analyze(base(selic=10, **kw), TODAY)['balances']['gross']
        mid = fi.analyze(base(selic=12, **kw), TODAY)['balances']['gross']
        self.assertLess(low, down)
        self.assertLess(down, high)
        self.assertAlmostEqual(down / mid, 1, delta=.002)

    def test_scenarios_and_expected_value(self):
        r = fi.analyze(base(indexer='CDI', rate=100, months=24), TODAY)
        by = {s['key']: s for s in r['scenarios']}
        self.assertEqual(set(by), {'low', 'base', 'high', 'inflation'})
        self.assertLess(by['low']['net'], by['base']['net'])
        self.assertLess(by['base']['net'], by['high']['net'])
        self.assertLess(by['inflation']['real'], by['base']['real'])
        self.assertAlmostEqual(by['inflation']['net'], by['base']['net'], places=6)   # CDI does not follow inflation
        self.assertAlmostEqual(by['low']['cdi_end'], 14.5 - 3)
        w = r['expected']['weights']
        self.assertAlmostEqual(sum(w.values()), 1)
        self.assertAlmostEqual(r['expected']['net'], .25 * by['low']['net'] + .5 * by['base']['net'] + .25 * by['high']['net'], places=6)

    def test_prefixed_does_not_pretend_to_move_with_rates(self):
        r = fi.analyze(base(), TODAY)
        self.assertEqual({s['key'] for s in r['scenarios']}, {'base', 'inflation'})
        self.assertIsNone(r['expected'])

    def test_ipca_plus_follows_inflation_scenario(self):
        r = fi.analyze(base(indexer='IPCA+', rate=6), TODAY)
        by = {s['key']: s for s in r['scenarios']}
        self.assertGreater(by['inflation']['net'], by['base']['net'])
        # real return barely changes: the product carries the inflation it is indexed to
        self.assertAlmostEqual(by['inflation']['real_annual'], by['base']['real_annual'], delta=.2)

    def test_poupanca_benchmark_rule(self):
        hi = fi.analyze(base(selic=14, cdi=13.9, months=12), TODAY)
        p = next(b for b in hi['benchmarks'] if b['key'] == 'poup')
        self.assertAlmostEqual(p['net'], 10000 * 1.005 ** (hi['days'] / fi.MONTH), places=4)
        lo = fi.analyze(base(selic=8, cdi=7.9, months=12), TODAY)
        p = next(b for b in lo['benchmarks'] if b['key'] == 'poup')
        self.assertAlmostEqual(p['net'], 10000 * (1 + .7 * .08 / 12) ** (lo['days'] / fi.MONTH), places=4)

    def test_cdi_is_derived_from_selic_when_missing(self):
        r = fi.analyze(base(indexer='CDI', rate=100, cdi=None, selic=14.75), TODAY)
        self.assertAlmostEqual(r['inputs']['cdi'], 14.65)

    def test_points_cover_the_path_and_end_at_the_net_balance(self):
        r = fi.analyze(base(months=30), TODAY)
        pts = r['points']
        self.assertEqual(pts[0]['month'], 0)
        self.assertAlmostEqual(pts[0]['net'], 10000)
        self.assertAlmostEqual(pts[-1]['month'], r['months'], places=6)
        self.assertAlmostEqual(pts[-1]['net'], r['balances']['net'], places=6)
        self.assertLess(pts[-1]['real'], pts[-1]['net'])
        self.assertLessEqual(len(pts), 62)

    def test_validation_messages(self):
        with self.assertRaisesRegex(ValueError, 'CDI'):
            fi.analyze(base(indexer='CDI', rate=100, cdi=None, selic=None), TODAY)
        with self.assertRaisesRegex(ValueError, 'vencimento'):
            fi.analyze(base(months=None, maturity='2026-11-01'), TODAY)
        with self.assertRaisesRegex(ValueError, 'válida'):
            fi.analyze(base(months=None, maturity='amanhã'), TODAY)
        with self.assertRaisesRegex(ValueError, 'regime tributário'):
            fi.analyze(base(product='Previdência'), TODAY)
        with self.assertRaisesRegex(ValueError, 'IR'):
            fi.analyze(base(tax_mode='manual', tax=None), TODAY)
        with self.assertRaisesRegex(ValueError, 'indexador|CDI, Selic'):
            fi.analyze(base(indexer='Manual'), TODAY)
        with self.assertRaisesRegex(ValueError, 'inválido'):
            fi.analyze(base(rate='abc'), TODAY)
        with self.assertRaisesRegex(ValueError, 'aporte'):
            fi.analyze(base(principal=0), TODAY)

    def test_missing_inflation_is_reported_not_invented(self):
        r = fi.analyze(base(ipca=None), TODAY)
        self.assertIsNone(r['real'])
        self.assertIsNone(r['inflation'])
        self.assertTrue(any('inflação' in w for w in r['warnings']))
        self.assertNotIn('ipca', {b['key'] for b in r['benchmarks']})
        self.assertNotIn('real', r['points'][-1])
        json.dumps(r, allow_nan=False)

    def test_short_horizon_warns_about_iof(self):
        r = fi.analyze(base(months=None, maturity='2026-12-01'), TODAY)
        self.assertEqual(r['days'], 14)
        self.assertTrue(any('IOF' in w for w in r['warnings']))

    def test_output_is_strict_json_for_every_indexer(self):
        for idx, rate in (('CDI', 105), ('Selic', .2), ('IPCA+', 6.5), ('Prefixado', 13)):
            json.dumps(fi.analyze(base(indexer=idx, rate=rate, selic_end=11, cdi_end=10.9, ipca_end=3.5), TODAY), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
