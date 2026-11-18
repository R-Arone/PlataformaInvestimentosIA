"""Own-history multiples: filing lag, share basis, splits, statistics and sector choice."""
from datetime import date, datetime, timezone
import json
import statistics
import unittest
from unittest.mock import patch

from aporte_brasil.company import multiple_history as mh
from aporte_brasil.company import valuation
from aporte_brasil.company import valuation_history
import test_app as baseline

app = baseline.app
DAY = date(2026, 11, 6)


def age(ref):
    try:
        return (DAY - date.fromisoformat(str(ref)[:10])).days
    except (ValueError, TypeError):
        return 99999


def month_list(start=(2020, 11), count=72, day=28):
    y, m = start
    out = []
    for _ in range(count):
        out.append(f'{y}-{m:02d}-{day:02d}')
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


MONTHS = month_list()
CLOSES = {ref: 10 + i % 5 for i, ref in enumerate(MONTHS)}


def quarters():
    rows = []
    for year in range(2019, 2027):
        for end in ('03-31', '06-30', '09-30', '12-31'):
            ref = f'{year}-{end}'
            if '2019-12-31' <= ref <= '2026-09-30':
                rows.append(dict(date=ref, net_income=50 if ref == '2026-06-30' else 25, revenue=250, ebitda=50,
                                 equity=1000, debt=300, cash=100))
    return rows


def price_payload(dividends=None, splits=None, months=MONTHS, closes=CLOSES, first='2020-11-02'):
    return {'symbol': 'ABCD3.SA', 'months': [{'date': d, 'close': closes[d]} for d in months],
            'dividends': dividends if dividends is not None else [{'date': f'{y}-{m}-15', 'amount': .5} for y in range(2020, 2027) for m in ('03', '09') if f'{y}-{m}-15' <= '2026-10-31'],
            'splits': splits or [], 'first_date': first, 'source_url': 'https://finance.yahoo.com/quote/ABCD3.SA/history/'}


def stock(price=8, sector='Indústria'):
    return {'id': 1, 'ticker': 'ABCD3', 'name': 'Empresa fictícia', 'asset_type': 'stock', 'sector': sector,
            'snapshots': {'quote': {'asof': DAY.isoformat(), 'data': {'price': price}},
                          'statistics': {'asof': '2026-09-30', 'retrieved_at': DAY.isoformat() + 'T12:00:00+00:00', 'source': 'Fonte sintética',
                                         'data': {'bvps': 10, 'eps': 1.25, 'pe': 6.4}},
                          'issuer_statements': {'data': {'annual': [], 'quarterly': quarters()}},
                          mh.KIND: {'data': price_payload(), 'source': 'Yahoo Finance · chart/ABCD3.SA', 'retrieved_at': DAY.isoformat()}}}


class AnalysisTests(unittest.TestCase):
    def test_filing_lag_uses_only_published_statements(self):
        rows = mh.periods({'annual': [], 'quarterly': quarters()})
        self.assertEqual(mh._period(rows, date(2026, 7, 28), ('net_income',))['end'], date(2026, 3, 31))
        self.assertEqual(mh._period(rows, date(2026, 8, 28), ('net_income',))['end'], date(2026, 6, 30))
        # December closes the fiscal year: 3 months for the DFP.
        self.assertEqual(mh._period(rows, date(2026, 2, 28), ('net_income',))['end'], date(2025, 9, 30))
        self.assertEqual(mh._period(rows, date(2026, 4, 28), ('net_income',))['end'], date(2025, 12, 31))
        latest = mh._period(rows, DAY, ('net_income',), published=False)
        self.assertEqual(latest['end'], date(2026, 9, 30))
        self.assertEqual(latest['flows']['net_income'], 125)

    def test_annual_flows_win_and_broken_quarter_windows_are_not_summed(self):
        q = quarters()
        q = [r for r in q if r['date'] != '2025-12-31']
        rows = mh.periods({'annual': [dict(date='2025-12-31', net_income=90, revenue=None, ebitda=None, equity=900, debt=None, cash=None)], 'quarterly': q})
        dec = next(p for p in rows if p['end'] == date(2025, 12, 31))
        self.assertEqual(dec['flows']['net_income'], 90)
        self.assertIsNone(dec['flows']['revenue'])
        self.assertEqual(dec['balance']['equity'], 900)
        march = next(p for p in rows if p['end'] == date(2026, 3, 31))
        self.assertIsNone(march['flows']['net_income'])
        # A month needing March falls back to the latest complete period.
        self.assertEqual(mh._period(rows, date(2026, 5, 28), ('net_income',))['end'], date(2025, 12, 31))

    def test_stock_multiples_statistics_and_reading(self):
        r = mh.analyze(stock(), age, DAY)
        self.assertTrue(r['applicable'])
        self.assertEqual(r['profile'], 'industrial')
        self.assertEqual(r['primary'], ['pe', 'ev_ebitda'])
        self.assertAlmostEqual(r['shares']['shares'], 100)
        pe = r['metrics']['pe']
        expected = {ref: CLOSES[ref] * (.8 if ref >= '2026-08' else 1) for ref in MONTHS}
        for ref, value in pe['points']:
            self.assertAlmostEqual(value, expected[ref], places=6)
        self.assertAlmostEqual(pe['current']['value'], 6.4)
        w = pe['windows']['5']
        values = [expected[ref] for ref in MONTHS if ref >= '2021-11']
        self.assertEqual(w['count'], 60)
        self.assertAlmostEqual(w['mean'], statistics.fmean(values), places=5)
        self.assertAlmostEqual(w['median'], statistics.median(values), places=5)
        self.assertAlmostEqual(w['vs_median'], (6.4 / statistics.median(values) - 1) * 100, places=4)
        self.assertEqual(w['percentile'], 0)
        self.assertEqual(w['level'], 'well_below')
        self.assertEqual(w['signal'], 'cheap_strong')
        ev = r['metrics']['ev_ebitda']
        first = dict(ev['points'])[MONTHS[0]]
        self.assertAlmostEqual(first, (100 * CLOSES[MONTHS[0]] + 200) / 200)
        self.assertEqual(r['summary']['5']['status'], 'below')
        # Dividends need a full year of events before the first yield point.
        dy = r['metrics']['dy']
        self.assertEqual(dy['points'][0][0], '2021-11-28')
        self.assertAlmostEqual(dict(dy['points'])['2022-01-28'], 1 / CLOSES['2022-01-28'] * 100)
        self.assertAlmostEqual(dy['current']['value'], 1 / 8 * 100)
        self.assertEqual(dy['windows']['5']['signal'], 'cheap_strong')
        lev = r['metrics']['net_debt_ebitda']
        self.assertAlmostEqual(lev['current']['value'], 1)
        self.assertEqual(lev['windows']['5']['signal'], 'none')
        self.assertFalse(r['metrics']['pe']['windows']['10']['count'] < r['metrics']['pe']['windows']['5']['count'])
        self.assertNotIn('P/L calculado', ' '.join(r['warnings']))

    def test_expensive_and_insufficient_history(self):
        r = mh.analyze(stock(price=30), age, DAY)
        self.assertEqual(r['metrics']['pe']['windows']['5']['signal'], 'expensive_strong')
        self.assertEqual(r['summary']['5']['status'], 'above')
        a = stock()
        short = MONTHS[-20:]
        a['snapshots'][mh.KIND]['data'] = price_payload(months=short, first=short[0])
        r = mh.analyze(a, age, DAY)
        self.assertFalse(r['metrics']['pe']['windows']['5']['available'])
        self.assertEqual(r['metrics']['pe']['windows']['5']['level'], 'unknown')
        self.assertEqual(r['summary']['5']['status'], 'unknown')

    def test_bank_profile_skips_enterprise_multiples_and_missing_data_is_explicit(self):
        a = stock(sector='Bancos')
        r = mh.analyze(a, age, DAY)
        self.assertEqual(r['primary'], ['pvp', 'pe'])
        self.assertNotIn('ev_ebitda', r['metrics'])
        a['snapshots'].pop(mh.KIND)
        self.assertEqual(mh.analyze(a, age, DAY)['status'], 'missing_prices')
        a = stock()
        a['snapshots'].pop('statistics')
        r = mh.analyze(a, age, DAY)
        self.assertIsNone(r['shares'])
        self.assertEqual(r['metrics']['pe']['points'], [])
        self.assertTrue(r['metrics']['net_debt_ebitda']['points'])
        self.assertIn('VPA ou LPA', ' '.join(r['warnings']))
        a = stock()
        a['snapshots']['statistics']['data']['pe'] = 12
        self.assertIn('P/L calculado', ' '.join(mh.analyze(a, age, DAY)['warnings']))
        a = stock()
        a['snapshots']['quote']['asof'] = '2026-10-01'
        r = mh.analyze(a, age, DAY)
        self.assertIsNone(r['metrics']['pe']['current'])
        self.assertTrue(r['metrics']['pe']['windows']['5']['available'])
        self.assertEqual(mh.analyze({'ticker': 'IVVB11', 'asset_type': 'etf', 'sector': 'ETF'}, age, DAY)['applicable'], False)

    def test_fii_pvp_adjusts_reports_for_splits(self):
        months = MONTHS[-40:]
        reports = []
        for ref in months:
            end = ref[:8] + '28'
            reports.append({'date': end, 'nav': 100 if ref < '2024-06' else 10})
        a = {'id': 2, 'ticker': 'ABCD11', 'name': 'FII', 'asset_type': 'fii', 'sector': 'Logística',
             'snapshots': {'quote': {'asof': DAY.isoformat(), 'data': {'price': 8}},
                           'fii_reports': {'data': {'monthly': reports, 'quarterly': []}},
                           mh.KIND: {'data': price_payload(months=months, closes={ref: 9.5 for ref in months}, first=months[0],
                                                           dividends=[{'date': ref[:8] + '10', 'amount': .08} for ref in months],
                                                           splits=[{'date': '2024-06-03', 'ratio': 10}]), 'retrieved_at': DAY.isoformat(), 'source': 'Yahoo'}}}
        r = mh.analyze(a, age, DAY)
        self.assertEqual(r['primary'], ['pvp', 'dy'])
        self.assertTrue(all(abs(v - .95) < 1e-9 for _, v in r['metrics']['pvp']['points']))
        self.assertAlmostEqual(r['metrics']['pvp']['current']['value'], .8)
        self.assertEqual(r['metrics']['pvp']['windows']['3']['level'], 'well_below')
        self.assertAlmostEqual(r['metrics']['dy']['current']['value'], 12 * .08 / 8 * 100)


class StorageTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset

    def chart(self):
        ts = lambda y, m, d: int(datetime(y, m, d, 18, tzinfo=timezone.utc).timestamp())
        return {'chart': {'result': [{'meta': {'symbol': 'ABCD3.SA', 'currency': 'BRL'},
            'timestamp': [ts(2026, 9, 29), ts(2026, 9, 30), ts(2026, 10, 30), ts(2026, 10, 31)],
            'indicators': {'quote': [{'close': [20, 21, 22, None]}], 'adjclose': [{'adjclose': [15, 16, 17, 18]}]},
            'events': {'dividends': {'a': {'date': ts(2026, 9, 29), 'amount': .3}, 'b': {'date': ts(2026, 9, 29) + 60, 'amount': .2}},
                       'splits': {'c': {'date': ts(2026, 10, 30), 'numerator': 2, 'denominator': 1}}}}]}}

    def test_fetch_keeps_unadjusted_month_end_close_and_events(self):
        a = {'id': 1, 'ticker': 'ABCD3', 'asset_type': 'stock'}
        with patch.object(app, 'request_json', return_value=self.chart()) as call:
            d = mh.fetch(app, a)
        self.assertIn('events=div%2Csplits', call.call_args[0][0])
        self.assertEqual(d['months'], [{'date': '2026-09-30', 'close': 21.0}, {'date': '2026-10-30', 'close': 22.0}])
        self.assertEqual(d['dividends'], [{'date': '2026-09-29', 'amount': .5}])
        self.assertEqual(d['splits'], [{'date': '2026-10-30', 'ratio': 2.0}])
        bad = self.chart()
        bad['chart']['result'][0]['meta']['currency'] = 'USD'
        with patch.object(app, 'request_json', return_value=bad), self.assertRaises(ValueError):
            mh.fetch(app, a)

    def test_validation_rejects_future_duplicates_and_foreign_source(self):
        good = price_payload()
        self.assertEqual(len(mh.validate_snapshot(app, good)['months']), 72)
        for change in (lambda d: d['months'].append({'date': '2099-01-28', 'close': 1}),
                       lambda d: d['months'].append({'date': '2026-10-01', 'close': 1}),
                       lambda d: d.update(source_url='https://example.org/'),
                       lambda d: d['splits'].append({'date': '2025-01-01', 'ratio': 0}),
                       lambda d: d.update(extra=1)):
            bad = json.loads(json.dumps(good))
            change(bad)
            with self.assertRaises(ValueError):
                mh.validate_snapshot(app, bad)

    def test_action_state_valuation_and_backup(self):
        aid = self.asset('ABCD3', 'Indústria')
        today = app.today()
        months = month_list((today.year - 6, today.month), 72)
        months = [m for m in months if m < today.replace(day=1).isoformat()]
        closes = {ref: 10 + i % 5 for i, ref in enumerate(months)}
        q = []
        for year in range(today.year - 7, today.year + 1):
            for end in ('03-31', '06-30', '09-30', '12-31'):
                ref = f'{year}-{end}'
                if (date.fromisoformat(ref) - today).days < -60:
                    q.append(dict(date=ref, net_income=25, revenue=250, ebitda=50, equity=1000, debt=300, cash=100, gross_profit=None,
                                  cost_of_revenue=None, ebit=None, interest_expense=None, operating_cashflow=None, free_cashflow=None,
                                  current_assets=None, current_liabilities=None, inventory=None))
        q = q[-28:]
        with app.connect() as c:
            app.add_snapshot(c, aid, 'quote', {'price': 9}, 'Test fixture', today.isoformat())
            app.add_snapshot(c, aid, 'statistics', {'bvps': 10, 'eps': 1, 'pe': 9, 'pvp': .9}, 'Test fixture', q[-1]['date'])
            app.add_snapshot(c, aid, 'issuer_statements', {'symbol': 'ABCD3.SA', 'currency': 'BRL', 'annual': [], 'quarterly': q,
                             'sources': {'income-statement': 'https://example.org/'}, 'source_url': 'https://example.org/'}, 'Test fixture', q[-1]['date'])
        payload = price_payload(months=months, closes=closes, first=months[0], dividends=[])
        with patch.object(mh, 'fetch', return_value=mh.validate_snapshot(app, payload)) as fetch:
            self.assertEqual(mh.action(app, {'asset_id': aid})['received'], [mh.KIND])
            self.assertTrue(mh.action(app, {'asset_id': aid})['used_cache'])
            mh.action(app, {'asset_id': aid, 'force': True})
        self.assertEqual(fetch.call_count, 2)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM snapshots WHERE asset_id=? AND kind=?', (aid, mh.KIND)).fetchone()[0], 1)
        a = next(x for x in app.state()['assets'] if x['id'] == aid)
        h = a['multiple_history']
        self.assertEqual(h['status'], 'ok')
        self.assertAlmostEqual(h['metrics']['pe']['current']['value'], 9)
        self.assertTrue(h['metrics']['pe']['windows']['5']['available'])
        hist = a['valuation']['historical_multiples']['pe']
        self.assertTrue(hist['available'])
        self.assertIn('reconstruída', hist['note'])
        method = next(m for m in a['valuation']['methods'] if m['method'] == 'P/L histórico')
        self.assertAlmostEqual(method['value'], 1 * h['metrics']['pe']['windows']['5']['mean'], places=4)
        with self.assertRaises(ValueError):
            mh.action(app, {'asset_id': str(aid)})
        with app.connect() as c:
            exported = app.export_data(c)
        app.mutate('/api/import', exported)
        a = next(x for x in app.state()['assets'] if x['ticker'] == 'ABCD3')
        self.assertEqual(a['multiple_history']['status'], 'ok')
        bad = json.loads(json.dumps(exported))
        row = next(s for s in bad['tables']['snapshots'] if s['kind'] == mh.KIND)
        data = json.loads(row['data'])
        data['symbol'] = 'WXYZ3.SA'
        data['source_url'] = 'https://finance.yahoo.com/quote/WXYZ3.SA/history/'
        row['data'] = json.dumps(data)
        with self.assertRaises(ValueError):
            app.mutate('/api/import', bad)


if __name__ == '__main__':
    unittest.main()
