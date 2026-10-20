"""Regional exposure, fund breadth, quotes and backup integration in a private fixture."""
import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import investment_exposure as x
import market_ai as ai
import test_app as baseline
import test_ai as ai_tests
from test_us_market import chart
app = baseline.app


class ExposureTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    trade = baseline.AppTests.trade

    def asset_type(self, ticker, typ):
        if typ == 'etf':
            with app.connect() as c:
                c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)', (ticker, ticker, typ, 'ETF', 0, 'Fixture', app.now()))
        return app.mutate('/api/assets', {'ticker': ticker, 'name': ticker, 'asset_type': typ, 'sector': 'Tecnologia', 'financial': False})['id']

    def analysis(self, profile='technology', scope='US', wide=False, direction='favorable'):
        r = ai_tests.AITests.analysis(self)
        r['sectors'][0].update(profile=profile, scope=scope, market_wide=wide, direction=direction)
        return ai.validate_analysis(app, r, [])

    def exposure(self, **changes):
        return {'scope': 'GLOBAL', 'profiles': [], 'focus': 'broad', 'benchmark': 'Estratégia global de teste',
                'source_url': 'https://example.org/fund', 'composition_url': 'https://example.org/fund/holdings',
                'analysis_url': 'https://example.org/fund/analysis', 'asof': app.today().isoformat(), **changes}

    def fund(self):
        app.mutate('/api/fixed', {'name': 'Fundo fictício', 'type': 'Fundo de ações', 'indexer': 'Manual',
            'invested': 100, 'balance': 100, 'balance_date': app.today().isoformat(), 'rate': 0, 'tax': 15, 'fee': 0,
            'maturity': '', 'liquidity': 'D+2', 'institution': 'Instituição confidencial'})
        return app.state()['fixed'][0]['id']

    def test_generalist_etfs_have_region_not_single_sector(self):
        for t, region in (('BOVA11', 'BR'), ('IVVB11', 'US'), ('WRLD11', 'GLOBAL')):
            self.asset_type(t, 'etf')
        rows = {a['ticker']: a for a in ai.asset_context(app.state())}
        for t, region in (('BOVA11', 'BR'), ('IVVB11', 'US'), ('WRLD11', 'GLOBAL')):
            e = rows[t]['instrument']['exposure']
            self.assertEqual(e['scope'], region)
            self.assertEqual(e['focus'], 'broad')
            self.assertEqual(e['profiles'], [])
            self.assertEqual(rows[t]['instrument']['currency'], 'BRL')
        self.assertEqual(x.effect(rows['BOVA11']['instrument']['exposure'], self.analysis('bank', 'BR'))[0], 'unknown')
        self.assertEqual(x.effect(rows['BOVA11']['instrument']['exposure'], self.analysis('general', 'BR'))[0], 'unknown')
        self.assertEqual(x.effect(rows['BOVA11']['instrument']['exposure'], self.analysis('general', 'BR', True))[0], 'favorable')
        self.assertEqual(x.effect(rows['BOVA11']['instrument']['exposure'], self.analysis('general', 'US', True))[0], 'unknown')

    def test_regional_sectors_do_not_merge_and_candidates_are_geographically_related(self):
        r = ai_tests.AITests.analysis(self)
        r['sectors'] = [{**r['sectors'][0], 'profile': 'technology', 'scope': 'BR'},
                        {**r['sectors'][0], 'profile': 'technology', 'scope': 'US', 'direction': 'unfavorable'}]
        normalized = ai.validate_analysis(app, r, [])
        self.assertEqual(len(normalized['sectors']), 2)
        refs = {r['ticker']: r for r in x.candidates(app, self.analysis())}
        self.assertIn('XLK', refs)
        self.assertIn('AAPL34', refs)
        self.assertIn('WRLD11', refs)
        self.assertNotIn('BOVA11', refs)
        self.assertEqual(refs['XLK']['direction'], 'favorable')
        self.assertEqual(refs['WRLD11']['direction'], 'unknown')
        self.assertTrue(refs['XLK']['composition_url'].startswith('https://www.ssga.com/'))
        with self.assertRaises(ValueError):
            self.analysis('technology', 'US', True)

    def test_bdr_quote_uses_own_brl_price_without_changing_ledger(self):
        aid = self.asset_type('AAPL34', 'bdr')
        self.trade(aid, qty=2, price=300)
        before = copy.deepcopy(app.state()['assets'][0]['position'])
        raw = chart('AAPL34.SA', currency='BRL', exchange='SAO')
        raw['chart']['result'][0]['meta']['regularMarketPrice'] = 83
        with patch.object(app, 'request_json', return_value=raw):
            x.refresh_bdr(app, {'id': aid, 'ticker': 'AAPL34'})
        a = app.state()['assets'][0]
        self.assertEqual(a['metrics']['price'], 83)
        for field in ('quantity', 'cost', 'average', 'realized'):
            self.assertEqual(a['position'][field], before[field])
        context = ai.asset_context(app.state())[0]['instrument']
        self.assertEqual(context['native_price'], 83)
        self.assertEqual(context['currency'], 'BRL')
        self.assertEqual(context['exposure']['scope'], 'US')
        self.assertIn('/bdrs/aapl34', context['analysis_url'])

    def test_targeted_bdr_refresh_fetches_price_only_and_preserves_on_failure(self):
        aid=self.asset_type('AAPL34','bdr')
        self.trade(aid,qty=2,price=40)
        before=copy.deepcopy(app.state()['assets'][0]['position'])
        raw=chart('AAPL34.SA',currency='BRL',exchange='SAO')
        raw['chart']['result'][0]['meta']['regularMarketPrice']=83
        app.REFRESH_LOCK.acquire()
        with patch.object(app,'request_json',return_value=raw) as request,patch.object(app,'update_catalog') as catalog:
            app.refresh_worker(aid)
        self.assertEqual(request.call_count,1)
        catalog.assert_not_called()
        a=app.state()['assets'][0]
        self.assertEqual(a['metrics']['price'],83)
        self.assertEqual(a['value'],166)
        for key in ('quantity','cost','average','realized'):
            self.assertEqual(a['position'][key],before[key])
        app.REFRESH_LOCK.acquire()
        with patch.object(app,'request_json',side_effect=ValueError('Falha de teste')):
            app.refresh_worker(aid)
        self.assertEqual(app.state()['assets'][0]['metrics']['price'],83)
        self.assertTrue(any('AAPL34' in e for e in app.JOB['errors']))
        self.assertFalse(app.JOB['running'])
        self.assertFalse(app.REFRESH_LOCK.locked())

    def test_quote_rejects_identity_currency_type_future_boolean(self):
        for edits in ({'symbol': 'MSFT'}, {'currency': 'BRL'}, {'exchangeName': 'SAO'}, {'instrumentType': 'EQUITY'},
                      {'regularMarketPrice': True}, {'regularMarketTime': None},
                      {'regularMarketTime': datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp()}):
            raw = chart('XLK', instrument='ETF', exchange='PCX')
            raw['chart']['result'][0]['meta'].update(edits)
            with patch.object(app, 'request_json', return_value=raw), self.assertRaises(ValueError):
                x.quote(app, 'XLK', 'etf', 'US')
        with patch.object(app, 'request_json', return_value=chart('XLK', instrument='ETF', exchange='PCX')):
            self.assertEqual(x.quote(app, 'XLK', 'etf', 'US')['currency'], 'USD')

    def test_generated_sector_cannot_grant_whole_market_verdict(self):
        raw=self.analysis('technology','US')
        raw['sectors'][0]['market_wide']=True
        with self.assertRaises(ValueError):
            ai.validate_analysis(app,raw,[])
        normalized=ai.validate_generated_analysis(app,raw,[])
        self.assertFalse(normalized['sectors'][0]['market_wide'])
        self.assertTrue(any('removida' in l for l in normalized['limitations']))
        self.assertEqual(x.effect(x.CATALOG['IVVB11'],normalized)[0],'unknown')

    def test_brazil_etf_equity_label_needs_independent_issuer_identity(self):
        raw=chart('BOVA11.SA', currency='BRL', exchange='SAO', instrument='EQUITY')
        with patch.object(app,'request_json',return_value=raw):
            self.assertEqual(x.quote(app,'BOVA11','etf','B3')['currency'],'BRL')
        raw['chart']['result'][0]['meta']['symbol']='FAKE11.SA'
        with patch.object(app,'request_json',return_value=raw),self.assertRaises(ValueError):
            x.quote(app,'FAKE11','etf','B3')

    def test_funds_can_save_general_exposure_links_and_backup_is_atomic(self):
        fid = self.fund()
        entity = 'fund:' + str(fid)
        ai.action(app, '/api/ai/exposure', {'entity': entity, 'exposure': self.exposure()})
        context = x.fund_context(app.state(), x.read_settings(app))
        self.assertEqual(context[0]['exposure']['scope'], 'GLOBAL')
        self.assertNotIn('Instituição confidencial', str(context))
        self.assertNotIn('balance', str(context))
        with app.connect() as c:
            exported = app.export_data(c)
        app.mutate('/api/import', copy.deepcopy(exported))
        self.assertEqual(x.read_settings(app)[entity], self.exposure())
        for edit in (lambda d: d[entity].update(source_url='javascript:alert(1)'),
                     lambda d: d[entity].update(asof='2099-01-01'),
                     lambda d: d.update({'fund:999999': self.exposure()})):
            bad = copy.deepcopy(exported)
            edit(bad['investment_exposures'])
            with self.assertRaises(ValueError):
                app.mutate('/api/import', bad)
        self.assertEqual(x.read_settings(app)[entity], self.exposure())
        legacy = copy.deepcopy(exported)
        legacy.pop('investment_exposures')
        app.mutate('/api/import', legacy)
        self.assertEqual(x.read_settings(app), {})

    def test_saved_scenario_keeps_native_usd_bdr_brl_funds_and_rejects_tampering(self):
        aid = self.asset_type('AAPL34', 'bdr')
        with app.connect() as c:
            app.add_snapshot(c, aid, 'quote', {'price': 83}, 'Cotação fictícia', app.today().isoformat())
        self.fund()
        with patch.object(ai, 'generate', return_value=(self.analysis(), 'mock-local')):
            ai.simulate(app, ai.validate_scenario(app, {'question': 'Tecnologia nos EUA'}))
        with app.connect() as c:
            exported = app.export_data(c)
        r = exported['ai_scenarios'][0]
        self.assertEqual(r['assets'][0]['direction'], 'favorable')
        self.assertEqual(r['assets'][0]['instrument']['native_price'], 83)
        self.assertEqual(len(r['funds']), 1)
        app.mutate('/api/import', copy.deepcopy(exported))
        bad = copy.deepcopy(exported)
        bad['ai_scenarios'][0]['assets'][0]['instrument']['currency'] = 'USD'
        with self.assertRaises(ValueError):
            app.mutate('/api/import', bad)

    def test_quote_batch_failures_preserve_previous_reference_and_bdr_position(self):
        aid = self.asset_type('AAPL34', 'bdr')
        self.asset_type('BOVA11','etf')
        self.trade(aid, qty=1, price=10)
        old = {'price': 99, 'currency': 'USD', 'asof': '2026-10-01', 'source': 'Fixture', 'retrieved_at': app.now()}
        with app.connect() as c:
            app.write_cache(c, 'investment_quotes', {'XLK': old})
        def fake(app, ticker, typ, market):
            if ticker == 'XLK':
                raise ValueError('Falha simulada')
            return {'price': 83, 'currency': 'USD' if market == 'US' else 'BRL', 'asof': app.today().isoformat(), 'source': 'Fixture', 'retrieved_at': app.now()}
        with patch.object(x, 'quote', side_effect=fake):
            x.refresh_quotes(app, {})
        self.assertEqual(next(a for a in app.state()['assets'] if a['ticker']=='BOVA11')['metrics']['price'],83)
        with app.connect() as c:
            self.assertEqual(app.read_cache(c, 'investment_quotes', {})['XLK'], old)
        self.assertTrue(app.state()['ai']['quote_errors'])
        self.assertEqual(app.state()['assets'][0]['position']['average'], 10)
        self.assertEqual(app.state()['assets'][0]['metrics']['price'], 83)


if __name__ == '__main__':
    unittest.main()
