from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import json
import sys
import threading
import unittest

ROOT = Path(__file__).absolute().parents[1]
spec = importlib.util.spec_from_file_location('benchmark_prices', ROOT / 'benchmark_prices.py')
bp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bp
spec.loader.exec_module(bp)

TODAY = date(2026, 11, 17)


def chart(symbol='^BVSP', currency='BRL', n=300, future=0, bad_at=()):
    days, d = [], TODAY
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days = days[::-1]
    stamps = [int(datetime(x.year, x.month, x.day, 12, tzinfo=timezone.utc).timestamp()) for x in days]
    closes = [100 + i * .1 for i in range(n)]
    for i in bad_at:
        closes[i] = None
    for k in range(future):
        stamps.append(int(datetime(2026, 12, 1 + k, 12, tzinfo=timezone.utc).timestamp()))
        closes.append(999.)
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': currency}, 'timestamp': stamps,
                                  'indicators': {'quote': [{'close': closes}]}}]}}


class FakeApp:
    """Just enough of app.py for fetch(): cache in a dict, scripted network answers."""
    WRITE_LOCK = threading.Lock()

    def __init__(self, answers):
        self.store, self.answers, self.calls, self.logged = {}, answers, [], []
        self.clock = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)

    @contextmanager
    def connect(self):
        yield self

    def read_cache(self, c, key, default):
        return json.loads(self.store[key]) if key in self.store else default

    def write_cache(self, c, key, value):
        self.store[key] = json.dumps(value, allow_nan=False)

    def log_source(self, c, key, label, url, status='ok', asof='', error=''):
        self.logged.append((key, asof))

    def today(self):
        return TODAY

    def now(self):
        return self.clock.isoformat()

    def request_json(self, url):
        self.calls.append(url)
        a = self.answers['ibov' if 'BVSP' in url else 'usd']
        if isinstance(a, Exception):
            raise a
        return a


class BenchmarkPriceTests(unittest.TestCase):
    def test_parse_drops_invalid_and_future_points(self):
        pts = bp.parse(chart(n=300, future=3, bad_at=(5, 6)), bp.SERIES['ibov'], TODAY)
        self.assertEqual(len(pts), 298)
        self.assertLessEqual(pts[-1]['date'], TODAY.isoformat())
        self.assertEqual(pts, sorted(pts, key=lambda p: p['date']))

    def test_parse_rejects_wrong_identity_currency_and_short_series(self):
        with self.assertRaisesRegex(ValueError, 'não confirmados'):
            bp.parse(chart(symbol='^GSPC'), bp.SERIES['ibov'], TODAY)
        with self.assertRaisesRegex(ValueError, 'não confirmados'):
            bp.parse(chart(currency='USD'), bp.SERIES['ibov'], TODAY)
        with self.assertRaisesRegex(ValueError, 'necessários'):
            bp.parse(chart(n=50), bp.SERIES['ibov'], TODAY)
        with self.assertRaisesRegex(ValueError, 'reconhecida'):
            bp.parse({'chart': {'result': None}}, bp.SERIES['ibov'], TODAY)

    def test_fetch_stores_both_and_serves_the_cache_afterwards(self):
        app = FakeApp({'ibov': chart(), 'usd': chart('BRL=X')})
        r = bp.fetch(app)
        self.assertFalse(r['used_cache'])
        self.assertEqual(set(r['series']), {'ibov', 'usd'})
        self.assertNotIn('prices', r['series']['ibov'])        # points stay on the server
        self.assertEqual(len(app.calls), 2)
        self.assertIn('%5EBVSP', app.calls[0])                  # the caret is encoded
        again = bp.fetch(app)
        self.assertTrue(again['used_cache'])
        self.assertEqual(len(app.calls), 2)
        self.assertEqual(set(bp.series_for(json.loads(app.store[bp.CACHE]))), {'ibov', 'usd'})
        forced = bp.fetch(app, force=True)
        self.assertFalse(forced['used_cache'])
        self.assertEqual(len(app.calls), 4)

    def test_expired_cache_is_refreshed(self):
        app = FakeApp({'ibov': chart(), 'usd': chart('BRL=X')})
        bp.fetch(app)
        app.clock += timedelta(days=2)
        self.assertFalse(bp.fetch(app)['used_cache'])

    def test_one_failure_keeps_the_other_series_and_reports(self):
        app = FakeApp({'ibov': chart(), 'usd': ValueError('Fonte indisponível')})
        r = bp.fetch(app)
        self.assertEqual(set(r['series']), {'ibov'})
        self.assertEqual(r['errors'], ['Fonte indisponível'])

    def test_failure_does_not_erase_a_previous_series(self):
        app = FakeApp({'ibov': chart(), 'usd': chart('BRL=X')})
        bp.fetch(app)
        app.answers['usd'] = ValueError('Sem rede')
        app.clock += timedelta(days=3)
        r = bp.fetch(app)
        self.assertEqual(set(r['series']), {'ibov', 'usd'})
        self.assertEqual(r['errors'], ['Sem rede'])

    def test_all_failing_raises(self):
        app = FakeApp({'ibov': ValueError('a'), 'usd': ValueError('b')})
        with self.assertRaisesRegex(ValueError, 'a; b'):
            bp.fetch(app)
        self.assertEqual(app.store, {})


if __name__ == '__main__':
    unittest.main()
