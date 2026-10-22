"""Only fictional holdings; public objectives are independent of the private wallet."""
import copy
import unittest
import investment_exposure as exposure
import market
import portfolio_strategy
import test_exposure as exposure_tests
import test_app as baseline
app=baseline.app


class EtfAreasTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    trade=baseline.AppTests.trade
    analysis=exposure_tests.ExposureTests.analysis

    def etf(self,ticker):
        with app.connect() as c:
            c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)',(ticker,'ETF fictício '+ticker,'etf','ETF · A definir',0,'Synthetic fixture',app.now()))
        return app.mutate('/api/assets',{'ticker':ticker})['id']

    def test_debentures_etf_is_fixed_income_and_unknown_ticker_is_not_guessed(self):
        aid=self.etf('DEBB11')
        state=app.state();a=state['assets'][0]
        self.assertEqual(a['sector'],'ETF · Debêntures / crédito privado')
        self.assertIn('debentures',a['exposure']['themes'])
        self.assertEqual(state['allocation']['items'][0]['class'],'rf')
        self.assertNotIn('DEB11',exposure.CATALOG)
        rows=market.normalize_catalog({'results':[dict(symbol='DEBB11',subType='etf',exchange='B3',isActive=True)]},app.now())
        self.assertEqual(rows[0]['sector'],a['sector'])
        other=exposure.metadata(dict(ticker='TSTX11',name='Nome fictício com Bitcoin e debêntures',asset_type='etf'),{})
        self.assertEqual(other['focus'],'unknown');self.assertEqual(exposure.area_keys(other),[])

    def test_abtc_is_related_to_bitcoin_and_fixed_income_without_invented_weights(self):
        aid=self.etf('ABTC11');self.trade(aid,qty=10,price=100)
        state=app.state();a=state['assets'][0]
        self.assertEqual(a['exposure']['asset_class'],'mixed')
        self.assertEqual(set(a['exposure']['profiles']),{'fixed_income','crypto_market'})
        self.assertEqual(state['allocation']['items'][0]['class'],'other')
        bitcoin=next(g for g in state['exposure_areas'] if g['key']=='theme:bitcoin')
        self.assertTrue(bitcoin['has_position']);self.assertTrue(bitcoin['members'][0]['partial'])
        self.assertNotIn('weight',bitcoin);self.assertNotIn('exposure_value',bitcoin['members'][0])
        app.mutate('/api/settings',{'allocation_overrides':{'asset:'+str(aid):'crypto'}})
        self.assertEqual(app.state()['allocation']['items'][0]['class'],'crypto')
        self.assertEqual(app.state()['assets'][0]['exposure']['asset_class'],'mixed')

    def test_direct_bitcoin_and_etf_watchlist_are_distinct_and_sales_remove_presence(self):
        self.etf('ABTC11')
        btc=app.mutate('/api/assets',{'ticker':'BTC','name':'Bitcoin','asset_type':'crypto'})['id']
        self.trade(btc,qty=.01,price=100000)
        state=app.state();group=next(g for g in state['exposure_areas'] if g['key']=='theme:bitcoin')
        self.assertEqual(group['held_count'],1);self.assertEqual(group['watched_count'],1)
        self.assertEqual(next(m for m in group['members'] if m['held'])['name'],'BTC')
        self.trade(btc,'sell',qty=.01,price=100000)
        group=next(g for g in app.state()['exposure_areas'] if g['key']=='theme:bitcoin')
        self.assertFalse(group['has_position']);self.assertEqual(group['held_count'],0)

    def test_no_position_does_not_mean_area_owned(self):
        self.etf('DEBB11')
        group=next(g for g in app.state()['exposure_areas'] if g['key']=='theme:debentures')
        self.assertFalse(group['has_position']);self.assertEqual(group['watched_count'],1)

    def test_theme_source_validation_and_backward_compatible_backup(self):
        self.etf('TSTX11')
        meta=dict(scope='GLOBAL',profiles=['crypto_market','fixed_income'],focus='mixed',asset_class='mixed',
            benchmark='Estratégia fictícia',asof=self.day,source_url='https://example.org/source',
            composition_url='https://example.org/portfolio',analysis_url='',themes=['bitcoin','inflation_bonds'])
        exposure.save(app,dict(entity='asset:TSTX11',exposure=meta))
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(backup))
        self.assertEqual(exposure.read_settings(app)['asset:TSTX11']['themes'],meta['themes'])
        for edit in (dict(themes=['unknown']),dict(themes=['bitcoin','bitcoin']),dict(themes=['bitcoin'],profiles=['fixed_income']),
                     dict(focus='unknown',source_url='',asof='')):
            with self.subTest(edit=edit),self.assertRaises(ValueError):exposure.validate_meta(app,{**meta,**edit})
        legacy=copy.deepcopy(backup);legacy['investment_exposures']['asset:TSTX11'].pop('themes')
        app.mutate('/api/import',legacy)
        self.assertNotIn('themes',exposure.read_settings(app)['asset:TSTX11'])

    def test_historical_scenarios_without_new_optional_metadata_still_validate(self):
        records=exposure.candidates(app,self.analysis('crypto_market','GLOBAL'))
        self.assertTrue(any(r['ticker']=='ABTC11' for r in records))
        exposure.validate_record_extras(app,{'candidates':records})
        for row in records:
            row.pop('themes',None);row.pop('asset_class',None)
        exposure.validate_record_extras(app,{'candidates':records})

    def test_area_computation_never_changes_positions_or_writes_to_wallet(self):
        self.etf('DEBB11')
        with app.connect() as c:before=c.serialize()
        self.assertTrue(app.state()['exposure_areas'])
        with app.connect() as c:self.assertEqual(before,c.serialize())


if __name__=='__main__':unittest.main()
