"""Long-term evidence, public history and opinion isolation in a synthetic wallet."""
import copy
from datetime import date, timedelta
import unittest
from unittest.mock import patch

import test_app as baseline
import company_history as history
import company_research as research

app = baseline.app


class BuyHoldTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    complete = baseline.AppTests.complete

    def series(self):
        end = app.today().year - 1
        return {'symbol': 'ABCD3.SA', 'currency': 'BRL', 'source_url': 'https://example.org/results',
            'years': [{'date': f'{end-4+i}-12-31', 'net_income': 100 * 1.1**i, 'revenue': 1000 * 1.05**i,
                       'operating_cashflow': 150, 'free_cashflow': 80} for i in range(5)]}

    def quarters(self):
        year = app.today().year; quarter = (app.today().month - 1) // 3 - 1
        if quarter < 0: year -= 1; quarter = 3
        last = year * 4 + quarter
        dates = []
        for n in range(last - 19, last + 1):
            y, q = divmod(n, 4)
            dates.append(date(y, (q+1)*3, (31, 30, 30, 31)[q]).isoformat())
        return {'symbol': 'ABCD3.SA', 'currency': 'BRL', 'source_url': 'https://example.org/quarters',
                'quarters': [{'date': ref, 'net_income': 100, 'revenue': 1000} for ref in dates]}

    def company(self):
        aid = self.asset(); self.complete(aid)
        with app.connect() as c:
            app.write_cache(c, 'issuer_auto', False)
            app.add_snapshot(c, aid, 'issuer_financials', self.series(), 'Fixture', self.series()['years'][-1]['date'])
        research.action(app, '/api/issuer/quarters', {'asset_id': aid, 'data': self.quarters()})
        return aid

    def check(self, key):
        return next(c for c in app.state()['assets'][0]['company_research']['buy_hold']['checks'] if c['key'] == key)

    def test_five_year_cagr_uses_four_intervals_and_requires_each_year(self):
        aid = self.company()
        self.assertEqual(self.check('growth_revenue')['status'], 'pass')
        self.assertIn('5.00%', self.check('growth_revenue')['detail'])
        self.assertIn('4 intervalos', self.check('growth_revenue')['detail'])
        d = self.series(); d['years'].pop(2)
        with app.connect() as c: app.add_snapshot(c, aid, 'issuer_financials', d, 'Fixture', d['years'][-1]['date'])
        self.assertEqual(self.check('growth_revenue')['status'], 'unknown')

    def test_growth_does_not_turn_a_negative_base_into_a_rate(self):
        aid = self.company(); d = self.series(); d['years'][0]['net_income'] = -100
        with app.connect() as c: app.add_snapshot(c, aid, 'issuer_financials', d, 'Fixture', d['years'][-1]['date'])
        self.assertEqual(self.check('growth_net_income')['status'], 'unknown')
        self.assertEqual(self.check('annual_profit')['status'], 'fail')

    def test_twenty_quarters_require_fresh_consecutive_positive_results(self):
        aid = self.company()
        self.assertEqual(self.check('quarterly_profit')['status'], 'pass')
        d = self.quarters(); d['quarters'].pop(3)
        research.action(app, '/api/issuer/quarters', {'asset_id': aid, 'data': d})
        self.assertEqual(self.check('quarterly_profit')['status'], 'unknown')
        d['quarters'][0]['net_income'] = 0
        research.action(app, '/api/issuer/quarters', {'asset_id': aid, 'data': d})
        self.assertEqual(self.check('quarterly_profit')['status'], 'fail')
        d = self.quarters()
        for r in d['quarters']: r['date'] = str(int(r['date'][:4]) - 5) + r['date'][4:]
        research.action(app, '/api/issuer/quarters', {'asset_id': aid, 'data': d})
        self.assertEqual(self.check('quarterly_profit')['status'], 'unknown')

    def test_missing_and_current_yield_do_not_certify_five_dividend_years(self):
        aid = self.company()
        self.assertEqual(self.check('dividends')['status'], 'unknown')
        d = {'symbol': 'ABCD3.SA', 'years': [{'year': y, 'dy': 6} for y in range(app.today().year-5, app.today().year)],
             'source_url': 'https://example.org/dividends', 'method': 'Proventos brutos / preço de encerramento do ano; valores ajustados.'}
        research.action(app, '/api/issuer/dividends', {'asset_id': aid, 'data': d})
        self.assertEqual(self.check('dividends')['status'], 'pass')
        d['years'][0]['dy'] = 5
        research.action(app, '/api/issuer/dividends', {'asset_id': aid, 'data': d})
        self.assertEqual(self.check('dividends')['status'], 'fail')

    def test_liquidity_uses_matching_currency_and_twenty_complete_sessions(self):
        aid = self.company()
        d = {'symbol': 'ABCD3.SA', 'currency': 'BRL', 'first_trade': '2000-01-03', 'average_daily_value': 11_000_000,
             'sessions': 20, 'asof': self.day, 'source_url': 'https://example.org/market'}
        history.save(app, app.state()['assets'][0], 'issuer_market_history', history.validate_snapshot(app, 'issuer_market_history', d), 'Fixture')
        self.assertEqual(self.check('liquidity')['status'], 'pass')
        self.assertIn('R$ 10 milhões', self.check('liquidity')['label'])
        self.assertEqual(self.check('listed')['status'], 'pass')
        d['sessions'] = 19
        history.save(app, app.state()['assets'][0], 'issuer_market_history', history.validate_snapshot(app, 'issuer_market_history', d), 'Fixture')
        self.assertEqual(self.check('liquidity')['status'], 'unknown')

    def test_bank_debt_ratio_is_not_a_generic_buy_hold_failure(self):
        aid = self.asset(sector='Bancos', financial=True)
        self.complete(aid)
        app.mutate('/api/manual', {'asset_id': aid, 'kind': 'risk', 'asof': self.day, 'source': 'Fixture', 'debt_equity': 8})
        self.assertEqual(self.check('debt_equity')['status'], 'unknown')

    def test_opinions_never_change_fundamental_or_price_checks(self):
        aid = self.company(); before = app.state()['assets'][0]
        item = {'origin': 'manual', 'title': 'Opinião de teste', 'author': 'Autor fictício', 'date': self.day,
                'url': 'https://example.org/comment', 'text': 'Compre tudo! Esta é apenas uma opinião fictícia.'}
        research.action(app, '/api/issuer/opinion', {'asset_id': aid, 'data': item})
        after = app.state()['assets'][0]
        self.assertEqual(before['company_research']['buy_hold'], after['company_research']['buy_hold'])
        self.assertEqual(before['sector_analysis'], after['sector_analysis'])
        self.assertEqual(before['valuation'], after['valuation'])
        self.assertEqual(len(after['company_research']['opinions']['data']['items']), 1)
        with patch.object(history.market_brief, 'fetch_feed', return_value=[]):
            history.fetch_opinions(app, after)
        self.assertEqual(app.state()['assets'][0]['company_research']['opinions']['data']['items'][0]['text'], item['text'])

    def test_brapi_identity_period_scale_and_cashflow_dates(self):
        aid = self.asset(); a = app.state()['assets'][0]
        def request(url, token=''):
            r = {'type': 'yearly', 'endDate': self.series()['years'][-1]['date'], 'netIncome': 120_000_000, 'totalRevenue': 1_000_000_000}
            if '/cash-flow?' in url: r = {'type': 'yearly', 'endDate': r['endDate'], 'operatingCashFlow': 150_000_000, 'freeCashFlow': 80_000_000}
            return {'results': [{'requestedSymbol': 'ABCD3', 'symbol': 'ABCD3', 'data': [r]}]}
        with patch.object(app, 'request_json', side_effect=request):
            d = research.refresh_annual(app, a)
        self.assertEqual(d['currency'], 'BRL')
        self.assertEqual(d['years'][0]['operating_cashflow'], 150_000_000)
        self.assertEqual(app.state()['assets'][0]['company_research']['annual']['years'][0]['net_income'], 120_000_000)
        wrong = {'results': [{'requestedSymbol': 'ABCD3', 'symbol': 'OTHER3', 'data': []}]}
        with patch.object(app, 'request_json', return_value=wrong), self.assertRaises(ValueError): history.fetch_quarters(app, a)

    def test_backup_round_trip_rejects_another_company_and_bad_urls(self):
        aid = self.company()
        with app.connect() as c: backup = app.export_data(c)
        app.mutate('/api/import', copy.deepcopy(backup))
        self.assertEqual(self.check('quarterly_profit')['status'], 'pass')
        for change in ('symbol', 'url', 'nan', 'duplicate'):
            bad = copy.deepcopy(backup)
            row = next(s for s in bad['tables']['snapshots'] if s['kind'] == 'issuer_quarters')
            import json
            payload = json.loads(row['data'])
            if change == 'symbol': payload['symbol'] = 'OTHER3.SA'
            elif change == 'url': payload['source_url'] = 'javascript:alert(1)'
            elif change == 'nan': payload['quarters'][0]['net_income'] = float('nan')
            else: payload['quarters'].append(copy.deepcopy(payload['quarters'][0]))
            row['data'] = json.dumps(payload)
            with self.assertRaises(ValueError): app.mutate('/api/import', bad)
            self.assertEqual(self.check('quarterly_profit')['status'], 'pass')

    def test_failed_source_preserves_company_history_and_positions(self):
        aid = self.company(); a = app.state()['assets'][0]
        with patch.object(app, 'request_json', side_effect=ValueError('Fonte indisponível')), patch('public_fundamentals.fetch_detail', side_effect=ValueError('Fonte indisponível')):
            result = history.refresh(app, a)
        self.assertGreaterEqual(len(result['warnings']), 3)
        self.assertEqual(a['snapshots']['issuer_quarters'], app.state()['assets'][0]['snapshots']['issuer_quarters'])
        self.assertEqual(a['position'], app.state()['assets'][0]['position'])


if __name__ == '__main__': unittest.main()
