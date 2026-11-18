from datetime import date, timedelta
from pathlib import Path
import json
import math
import random
import sys
import unittest

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
from aporte_brasil.portfolio import asset_correlation as ac

TODAY = date(2026, 11, 17)
STAMP = '2026-11-17T22:00:00+00:00'  # after the B3 close, so the last session counts


def weekdays(n, end=TODAY - timedelta(days=1)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def prices(returns, days):
    level, out = 100.0, []
    out.append({'date': days[0].isoformat(), 'close': level})
    for d, r in zip(days[1:], returns):
        level *= math.exp(r)
        out.append({'date': d.isoformat(), 'close': level})
    return out


def market_returns(n, seed=1, vol=.012):
    rng = random.Random(seed)
    return [rng.gauss(0, vol) for _ in range(n)]


def asset(id_, ticker, closes, value=1000, kind='stock', qty=10):
    return {'id': id_, 'ticker': ticker, 'asset_type': kind, 'value': value, 'position': {'quantity': qty},
            'snapshots': {'history': {'retrieved_at': STAMP, 'data': {'prices': closes}}}}


class AssetCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.n = 300
        self.days = weekdays(self.n + 1)
        self.mkt = market_returns(self.n)
        self.bench = {'ibov': {'prices': prices(self.mkt, self.days)}}

    def test_beta_and_correlation_recover_known_relationship(self):
        rng = random.Random(7)
        own = [1.5 * m + rng.gauss(0, .004) for m in self.mkt]
        a = asset(1, 'AAAA3', prices(own, self.days))
        ac.enrich([a], self.bench, TODAY, STAMP)
        c = a['correlation_context']
        self.assertEqual(c['status'], 'ready')
        ib = c['ibov']
        self.assertEqual(ib['n'], 252)
        self.assertAlmostEqual(ib['beta'], 1.5, delta=.1)
        self.assertGreater(ib['correlation'], .9)
        lo, hi = ib['interval']
        self.assertLess(lo, ib['correlation'])
        self.assertGreater(hi, ib['correlation'])
        self.assertGreater(ib['r2'], .8)
        self.assertIn('beta 1,', c['readings'][0])
        json.dumps(c, allow_nan=False)

    def test_independent_asset_has_low_correlation(self):
        own = market_returns(self.n, seed=99)
        a = asset(1, 'BBBB3', prices(own, self.days))
        ac.enrich([a], self.bench, TODAY, STAMP)
        self.assertLess(abs(a['correlation_context']['ibov']['correlation']), .25)

    def test_up_and_down_beta_differ_for_an_asymmetric_asset(self):
        # moves 0.5x on up days of the market and 1.5x on down days
        own = [(.5 if m > 0 else 1.5) * m for m in self.mkt]
        a = asset(1, 'CCCC3', prices(own, self.days))
        ac.enrich([a], self.bench, TODAY, STAMP)
        ib = a['correlation_context']['ibov']
        self.assertAlmostEqual(ib['up_beta'], .5, delta=.05)
        self.assertAlmostEqual(ib['down_beta'], 1.5, delta=.05)
        self.assertAlmostEqual(ib['down_capture'], 1.5, delta=.05)
        self.assertLess(ib['rolling']['min'], ib['rolling']['max'] + 1e-12)
        self.assertEqual(ib['rolling']['window'], 63)

    def test_long_calendar_gaps_are_not_daily_returns(self):
        pts = prices(self.mkt, self.days)
        # drop 15 consecutive sessions in the middle of the asset history
        kept = pts[:100] + pts[115:]
        pairs = ac.paired_returns(ac.series(kept), ac.series(self.bench['ibov']['prices']))
        self.assertTrue(all(isinstance(p[1], float) for p in pairs))
        # the return across the gap would span >5 calendar days and is dropped
        self.assertEqual(len(pairs), min(252, len(kept) - 2))

    def test_short_overlap_and_flat_series(self):
        a = asset(1, 'DDDD3', prices(self.mkt, self.days)[-80:])
        ac.enrich([a], {'ibov': {'prices': prices(self.mkt, self.days)[-50:]}}, TODAY, STAMP)
        self.assertEqual(a['correlation_context']['ibov']['status'], 'short')
        flat = asset(2, 'EEEE3', [{'date': d.isoformat(), 'close': 10.0} for d in self.days])
        ac.enrich([flat], self.bench, TODAY, STAMP)
        self.assertEqual(flat['correlation_context']['ibov']['status'], 'flat')

    def test_missing_benchmark_is_reported(self):
        a = asset(1, 'FFFF3', prices(self.mkt, self.days))
        ac.enrich([a], {}, TODAY, STAMP)
        c = a['correlation_context']
        self.assertEqual(c['status'], 'missing')
        self.assertEqual(len(c['missing']), 2)

    def test_not_applicable_types_and_missing_history(self):
        crypto = asset(1, 'BTC', prices(self.mkt, self.days), kind='crypto')
        none = {'id': 2, 'ticker': 'GGGG3', 'asset_type': 'stock', 'value': 0, 'position': {'quantity': 0}, 'snapshots': {}}
        ac.enrich([crypto, none], self.bench, TODAY, STAMP)
        self.assertFalse(crypto['correlation_context']['applicable'])
        self.assertEqual(none['correlation_context']['status'], 'missing')

    def test_holdings_weighted_by_value_and_excludes_itself(self):
        rng = random.Random(3)
        twin = [m + rng.gauss(0, .002) for m in self.mkt]              # almost the market
        inverse = [-m + rng.gauss(0, .002) for m in self.mkt]          # opposite of the market
        subject = asset(1, 'SUBJ3', prices(self.mkt, self.days), value=500)
        big = asset(2, 'TWIN3', prices(twin, self.days), value=3000)
        small = asset(3, 'INVR3', prices(inverse, self.days), value=1000)
        ac.enrich([subject, big, small], self.bench, TODAY, STAMP)
        h = subject['correlation_context']['holdings']
        self.assertEqual(h['status'], 'ready')
        self.assertEqual(h['peers'], 2)
        self.assertNotIn('SUBJ3', [p['ticker'] for p in h['highest']])
        self.assertEqual(h['highest'][0]['ticker'], 'TWIN3')
        self.assertEqual(h['lowest'][0]['ticker'], 'INVR3')
        # (3000*~1 + 1000*~-1) / 4000 = ~0.5
        self.assertAlmostEqual(h['mean_correlation'], .5, delta=.05)
        self.assertAlmostEqual(sum(p['weight'] for p in h['highest']), 100, delta=1e-9)
        self.assertAlmostEqual(h['coverage'], 100, delta=1e-9)

    def test_unheld_asset_is_compared_against_held_positions(self):
        held = asset(1, 'HELD3', prices(self.mkt, self.days), value=1000)
        watched = asset(2, 'WATCH3', prices(self.mkt, self.days), value=0, qty=0)
        ac.enrich([held, watched], self.bench, TODAY, STAMP)
        h = watched['correlation_context']['holdings']
        self.assertEqual(h['status'], 'ready')
        self.assertGreater(h['mean_correlation'], .99)

    def test_garbage_benchmark_points_are_ignored(self):
        bad = {'ibov': {'prices': prices(self.mkt, self.days) + [{'date': 'x', 'close': 3}, {'date': '2026-11-16', 'close': float('nan')}, 5]}}
        a = asset(1, 'HHHH3', prices(self.mkt, self.days))
        ac.enrich([a], bad, TODAY, STAMP)
        self.assertEqual(a['correlation_context']['ibov']['status'], 'ready')
        json.dumps(a['correlation_context'], allow_nan=False)


if __name__ == '__main__':
    unittest.main()


class CacheAndSpeedTests(unittest.TestCase):
    def test_repeated_enrich_is_identical_and_changed_data_is_not_reused(self):
        days = weekdays(301)
        mkt = market_returns(300)
        bench = {'ibov': {'prices': prices(mkt, days)}}
        rng = random.Random(5)
        own = [m + rng.gauss(0, .005) for m in mkt]
        a1 = asset(1, 'AAAA3', prices(own, days))
        ac.enrich([a1], bench, TODAY, STAMP)
        first = json.dumps(a1['correlation_context'], sort_keys=True)
        a2 = asset(1, 'AAAA3', prices(own, days))
        ac.enrich([a2], bench, TODAY, STAMP)
        self.assertEqual(first, json.dumps(a2['correlation_context'], sort_keys=True))
        # a new close with the same length and a different last value must recompute
        changed = prices(own[:-1] + [own[-1] + .08], days)
        a3 = asset(1, 'AAAA3', changed)
        ac.enrich([a3], bench, TODAY, STAMP)
        self.assertNotEqual(first, json.dumps(a3['correlation_context'], sort_keys=True))

    def test_forty_held_positions_finish_quickly(self):
        import time
        days = weekdays(1260)
        mkt = market_returns(1259)
        bench = {'ibov': {'prices': prices(mkt, days)}}
        assets = []
        for i in range(60):
            rng = random.Random(100 + i)
            beta = .3 + .03 * i
            own = [beta * m + rng.gauss(0, .008) for m in mkt]
            assets.append(asset(i + 1, f'T{i:03d}3', prices(own, days), value=1000 + i, qty=10 if i < 40 else 0))
        ac._MEMO.clear()
        t0 = time.perf_counter()
        ac.enrich(assets, bench, TODAY, STAMP)
        cold = time.perf_counter() - t0
        t1 = time.perf_counter()
        ac.enrich(assets, bench, TODAY, STAMP)
        warm = time.perf_counter() - t1
        self.assertLess(cold, 30.0)       # generous: the point is that it is not quadratic-in-Python slow on a laptop
        self.assertLess(warm, cold)
        self.assertTrue(all(a['correlation_context']['status'] == 'ready' for a in assets))
