from datetime import date, timedelta
from pathlib import Path
import importlib.util
import json
import sys
import unittest

spec = importlib.util.spec_from_file_location('price_context', Path(__file__).absolute().parents[1] / 'price_context.py')
pc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pc
spec.loader.exec_module(pc)

TODAY = date(2026, 11, 17)


def monthly(values, end=date(2026, 10, 31)):
    """Month-end closes ending at `end`, oldest first."""
    out = []
    y, m = end.year, end.month
    for v in reversed(values):
        # last day of month (y, m)
        nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
        out.append({'date': (nxt - timedelta(days=1)).isoformat(), 'close': v})
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def daily(values, end=TODAY - timedelta(days=1)):
    days = []
    d = end
    while len(days) < len(values):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return [{'date': x.isoformat(), 'close': v} for x, v in zip(reversed(days), values)]


def asset(months=None, days=None, price=None, quote_asof=TODAY, kind='stock'):
    snaps = {}
    if months is not None:
        snaps['issuer_price_history'] = {'data': {'months': months}}
    if days is not None:
        snaps['history'] = {'data': {'prices': days}}
    if price is not None:
        snaps['quote'] = {'data': {'price': price}, 'asof': quote_asof.isoformat()}
    return {'asset_type': kind, 'metrics': {'price': price}, 'snapshots': snaps}


class PriceContextTests(unittest.TestCase):
    def test_previous_visit_ends_before_the_current_stay(self):
        # 6 months at 10, 12 months at 20, 6 months at 10 again, now 10.2
        values = [10] * 6 + [20] * 12 + [10] * 6
        r = pc.analyze(asset(months=monthly(values), price=10.2), TODAY)
        level = r['levels']['monthly']
        prev = level['visit']['previous']
        self.assertEqual(prev['end'], '2025-04-30')  # 24 months ending 2026-10 start in 2024-11; index 5 is 2025-04
        self.assertEqual(prev['observations'], 6)
        self.assertEqual(level['visit']['stay_observations'], 6)
        # in between, the price reached the 20 block: +96% against the 10.2 reference
        self.assertAlmostEqual(prev['between_high']['change'], (20 / 10.2 - 1) * 100, places=6)
        self.assertGreater(prev['days_ago'], 300)

    def test_short_excursion_does_not_split_the_current_stay(self):
        values = [10] * 10 + [20] * 10 + [10, 10, 10, 15, 10, 10, 10]  # a single 15 close is one observation out of the 5% band
        r = pc.analyze(asset(months=monthly(values), price=10), TODAY)
        visit = r['levels']['monthly']['visit']
        self.assertEqual(visit['stay_observations'], 7)
        self.assertEqual(visit['previous']['observations'], 10)

    def test_never_visited_before(self):
        values = [10 + i for i in range(30)]  # monotonically rising to a new high
        r = pc.analyze(asset(months=monthly(values), price=39), TODAY)
        self.assertIsNone(r['levels']['monthly']['visit']['previous'])
        self.assertIn('não esteve antes', r['levels']['monthly']['reading'])

    def test_beyond_band_dates(self):
        values = [30] * 6 + [10] * 6 + [20] * 6 + [12] * 6
        r = pc.analyze(asset(months=monthly(values), price=12), TODAY)
        beyond = r['levels']['monthly']['beyond']
        self.assertEqual(beyond['dearer']['close'], 20)
        self.assertEqual(beyond['cheaper']['close'], 10)
        self.assertLess(beyond['cheaper']['change'], 0)
        self.assertGreater(beyond['dearer']['change'], 0)

    def test_window_stats_percentile_and_drawdown(self):
        values = list(range(20, 80)) + [40]  # 61 months, rise then crash to 40
        r = pc.analyze(asset(months=monthly(values), price=40), TODAY)
        w = r['levels']['monthly']['windows']
        self.assertTrue(w['5']['available'])
        self.assertFalse(w['10']['available'])  # series covers only ~5 years
        self.assertLess(w['5']['percentile'], 100)
        self.assertAlmostEqual(w['5']['max_drawdown']['value'], (40 / 79 - 1) * 100, places=6)
        self.assertIsNone(w['5']['max_drawdown']['recovered'])
        self.assertAlmostEqual(w['5']['high']['distance'], (40 / 79 - 1) * 100, places=6)

    def test_recovery_is_measured_from_trough(self):
        values = [50] * 10 + [30] * 4 + [55] * 40 + [50] * 10  # 64 months
        r = pc.analyze(asset(months=monthly(values), price=50), TODAY)
        dd = r['levels']['monthly']['windows']['5']['max_drawdown']
        self.assertAlmostEqual(dd['value'], (30 / 50 - 1) * 100, places=6)
        self.assertIsNotNone(dd['recovered'])
        self.assertAlmostEqual(dd['months_to_recover'], 4, delta=1)

    def test_stale_quote_falls_back_to_the_last_close(self):
        values = [10] * 6 + [20] * 12 + [10] * 6
        r = pc.analyze(asset(months=monthly(values), price=99, quote_asof=TODAY - timedelta(days=30)), TODAY)
        self.assertIsNone(r['price'])
        self.assertEqual(r['levels']['monthly']['reference'], 10)

    def test_daily_series_uses_its_own_last_close_and_flags_adjustment(self):
        values = [10] * 40 + [20] * 80 + [10] * 40 + [10.1]  # 161 sessions
        r = pc.analyze(asset(days=daily(values)), TODAY)
        level = r['levels']['daily']
        self.assertEqual(level['reference'], 10.1)
        self.assertIn('ajustado', level['label'].lower())
        self.assertEqual(level['visit']['previous']['observations'], 40)
        self.assertEqual(r['preferred'], 'daily')

    def test_monthly_is_preferred_when_both_exist(self):
        values = [10 + (i % 3) for i in range(40)]
        r = pc.analyze(asset(months=monthly(values), days=daily([10] * 200), price=10), TODAY)
        self.assertEqual(r['preferred'], 'monthly')
        self.assertEqual(set(r['levels']), {'monthly', 'daily'})

    def test_missing_or_short_history(self):
        r = pc.analyze(asset(months=monthly([10] * 5), price=10), TODAY)
        self.assertEqual(r['status'], 'missing_prices')
        self.assertIn('histórico', r['message'])
        self.assertFalse(pc.analyze({'asset_type': 'crypto'}, TODAY)['applicable'])

    def test_garbage_points_are_ignored_and_output_is_strict_json(self):
        pts = monthly([10] * 30) + [{'date': 'x', 'close': 5}, {'date': '2026-01-01', 'close': float('nan')},
                                    {'date': '2026-02-01', 'close': -1}, {'date': '2026-03-01', 'close': True}, 'lixo']
        r = pc.analyze(asset(months=pts, price=10), TODAY)
        json.dumps(r, allow_nan=False)
        self.assertEqual(r['levels']['monthly']['count'], 30)


if __name__ == '__main__':
    unittest.main()
