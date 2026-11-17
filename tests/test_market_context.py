"""Price history, correlations and fixed-income calculator wired into the app (synthetic data only)."""
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import http.client
import importlib.util
import json
import math
import random
import sys
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('aporte', Path(__file__).absolute().parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
import benchmark_prices


def weekdays(n, end):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def walk(returns, start=20.0):
    level, out = start, [start]
    for r in returns:
        level *= math.exp(r)
        out.append(level)
    return out


def chart(symbol, closes, days, currency='BRL'):
    from datetime import datetime, timezone
    stamps = [int(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp()) for d in days]
    return {'chart': {'result': [{'meta': {'symbol': symbol, 'currency': currency}, 'timestamp': stamps,
                                  'indicators': {'quote': [{'close': closes}]}}]}}


class MarketContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tmp-test-', dir=app.ROOT / 'tests')
        self.old_path = app.DB_PATH
        app.DB_PATH = Path(self.tmp.name) / 'carteira.sqlite3'
        with patch.object(app, 'ROOT', Path(self.tmp.name)):
            app.init_db()
        self.today = app.today()
        self.days = weekdays(400, self.today - timedelta(days=1))
        rng = random.Random(11)
        self.market = [rng.gauss(0, .012) for _ in range(len(self.days) - 1)]
        with app.connect() as c:
            c.execute("UPDATE settings SET value='false' WHERE key='auto_refresh'")
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB_PATH = self.old_path
        self.tmp.cleanup()

    def post(self, path, data):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
        c.request('POST', path, json.dumps(data), {'Content-Type': 'application/json', 'X-CSRF-Token': app.CSRF})
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        return r.status, body

    def stock(self, ticker, beta, seed, qty=10, monthly=True):
        with app.connect() as c:
            c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)', (ticker, ticker, 'stock', 'Indústria', 0, 'Test fixture', app.now()))
        aid = app.mutate('/api/assets', {'ticker': ticker, 'name': ticker, 'sector': 'Indústria', 'financial': False})['id']
        if qty:
            app.mutate('/api/trades', {'asset_id': aid, 'side': 'buy', 'quantity': qty, 'price': 20, 'fees': 0, 'date': self.today.isoformat()})
        rng = random.Random(seed)
        closes = walk([beta * m + rng.gauss(0, .006) for m in self.market])
        pts = [{'date': d.isoformat(), 'close': v} for d, v in zip(self.days, closes)]
        with app.connect() as c:
            app.add_snapshot(c, aid, 'quote', {'price': closes[-1]}, 'Test fixture', self.today.isoformat())
            app.add_snapshot(c, aid, 'history', {'prices': pts, 'years': 5}, 'Test fixture', self.days[-1].isoformat())
            if monthly:
                # 120 month-end closes ending in the month of the last daily close, in the real payload format
                last = self.days[-1]
                y, m = last.year, last.month
                ends = []
                for _ in range(120):
                    ends.append((y, m))
                    y, m = (y, m - 1) if m > 1 else (y - 1, 12)
                ends.reverse()
                mrng = random.Random(seed + 50)
                level, series = 12.0, []
                for i, (yy, mm) in enumerate(ends):
                    level *= math.exp(mrng.gauss(.004, .06))
                    day = last if i == len(ends) - 1 else (self.today.replace(year=yy, month=mm, day=1) + timedelta(days=27))
                    series.append({'date': day.isoformat(), 'close': closes[-1] if i == len(ends) - 1 else level})
                payload = {'symbol': ticker + '.SA', 'months': series, 'dividends': [], 'splits': [], 'first_date': series[0]['date'],
                           'source_url': 'https://finance.yahoo.com/quote/' + ticker + '.SA/history/'}
                app.add_snapshot(c, aid, 'issuer_price_history', payload, 'Test fixture', series[-1]['date'])
        return aid

    def asset(self, ticker):
        return next(a for a in app.state()['assets'] if a['ticker'] == ticker)

    def bench_answers(self):
        rng = random.Random(3)
        ibov = walk(self.market, 120000)
        usd = walk([-.3 * m + rng.gauss(0, .005) for m in self.market], 5.0)
        def request(url):
            if 'BVSP' in url:
                return chart('^BVSP', ibov, self.days)
            return chart('BRL=X', usd, self.days)
        return request

    def test_state_has_price_context_and_missing_benchmarks_are_explained(self):
        self.stock('AAAA3', 1.0, 1)
        self.stock('BBBB3', .5, 2)
        s = app.state()
        a = next(x for x in s['assets'] if x['ticker'] == 'AAAA3')
        pc = a['price_context']
        self.assertEqual(pc['status'], 'ready')
        self.assertEqual(set(pc['levels']), {'monthly', 'daily'})
        self.assertEqual(pc['preferred'], 'monthly')
        self.assertEqual(pc['levels']['monthly']['reference'], pc['price'])   # fresh quote is the reference
        self.assertTrue(pc['levels']['daily']['windows']['1']['available'])
        cc = a['correlation_context']
        self.assertTrue(cc['applicable'])
        self.assertEqual(len(cc['missing']), 2)                     # no Ibovespa or dollar series fetched yet
        self.assertEqual(cc['holdings']['status'], 'ready')
        self.assertEqual(cc['holdings']['peers'], 1)
        self.assertEqual(s['benchmark_info']['series'], {})
        json.dumps({'p': pc, 'c': cc, 'b': s['benchmark_info']}, allow_nan=False)

    def test_benchmark_route_stores_series_and_feeds_correlations(self):
        self.stock('AAAA3', 1.2, 1)
        with patch.object(app, 'request_json', side_effect=self.bench_answers()):
            status, body = self.post('/api/prices/benchmarks', {'force': True})
        self.assertEqual(status, 200)
        self.assertEqual(set(body['series']), {'ibov', 'usd'})
        self.assertNotIn('prices', json.dumps(body))                 # daily points never go to the browser
        s = app.state()
        self.assertEqual(set(s['benchmark_info']['series']), {'ibov', 'usd'})
        self.assertNotIn('"prices"', json.dumps(s['benchmark_info']))
        cc = next(x for x in s['assets'] if x['ticker'] == 'AAAA3')['correlation_context']
        self.assertEqual(cc['ibov']['status'], 'ready')
        self.assertAlmostEqual(cc['ibov']['beta'], 1.2, delta=.15)
        self.assertGreater(cc['ibov']['correlation'], .8)
        self.assertEqual(cc['usd']['status'], 'ready')
        self.assertLess(cc['usd']['correlation'], 0)                 # the dollar series moves against the market
        self.assertEqual(cc['missing'], [])
        with app.connect() as c:
            self.assertTrue(c.execute("SELECT 1 FROM source_log WHERE key='benchmark_ibov'").fetchone())

    def test_benchmark_failure_is_a_clean_error_and_state_still_works(self):
        aid = self.stock('AAAA3', 1.0, 1)
        with patch.object(app, 'request_json', side_effect=ValueError('Fonte indisponível')):
            status, body = self.post('/api/prices/benchmarks', {'force': True})
        self.assertEqual(status, 400)
        self.assertIn('Fonte indisponível', body['error'])
        self.assertEqual(self.asset('AAAA3')['id'], aid)

    def test_benchmark_force_must_be_the_boolean_true(self):
        self.stock('AAAA3', 1.0, 1)
        calls = []
        def request(url):
            calls.append(url)
            return self.bench_answers()(url)
        with patch.object(app, 'request_json', side_effect=request):
            self.post('/api/prices/benchmarks', {'force': 'yes'})
            first = len(calls)
            self.post('/api/prices/benchmarks', {'force': 'yes'})
        self.assertEqual(first, 2)
        self.assertEqual(len(calls), 2)                              # second call served from the cache

    def test_fixed_income_route(self):
        status, body = self.post('/api/fixed/analyze', {'principal': 10000, 'months': 24, 'product': 'CDB', 'tax_mode': 'auto', 'indexer': 'CDI',
                                                        'rate': 105, 'fee': 0, 'cdi': 14.65, 'selic': 14.75, 'ipca': 4.5, 'selic_end': 11, 'cdi_end': 10.9})
        self.assertEqual(status, 200)
        self.assertEqual(body['balances']['tax_rate'], 15)
        self.assertGreater(body['balances']['net'], 10000)
        self.assertEqual({s['key'] for s in body['scenarios']}, {'low', 'base', 'high', 'inflation'})
        self.assertIsNotNone(body['real'])
        json.dumps(body, allow_nan=False)
        status, body = self.post('/api/fixed/analyze', {'principal': 10000, 'months': 24, 'indexer': 'Manual', 'rate': 1})
        self.assertEqual(status, 400)
        self.assertIn('Escolha', body['error'])
        status, body = self.post('/api/fixed/analyze', {'principal': 'abc', 'months': 24, 'indexer': 'CDI', 'rate': 100})
        self.assertEqual(status, 400)

    def test_every_script_and_stylesheet_in_the_page_is_served(self):
        import re
        html = (app.ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        sources = re.findall(r'<(?:script|link)[^>]*?(?:src|href)="(/[^"]+)"', html)
        self.assertIn('/price-context.js', sources)
        self.assertIn('/fixed-income.js', sources)
        for src in sources:
            c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            c.request('GET', src)
            r = c.getresponse()
            body = r.read()
            c.close()
            self.assertEqual(r.status, 200, src)
            self.assertTrue(body, src)
            if src.endswith('.js'):
                self.assertTrue(r.getheader('Content-Type').startswith('application/javascript'), src)

    def test_routes_require_the_same_csrf_protection_as_the_others(self):
        for path in ('/api/fixed/analyze', '/api/prices/benchmarks'):
            c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            c.request('POST', path, '{}', {'Content-Type': 'application/json', 'X-CSRF-Token': 'wrong'})
            self.assertEqual(c.getresponse().status, 403)
            c.close()


if __name__ == '__main__':
    unittest.main()
