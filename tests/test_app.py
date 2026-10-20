import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import timedelta

spec = importlib.util.spec_from_file_location('aporte', Path(__file__).absolute().parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name]=app
spec.loader.exec_module(app)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tmp-test-', dir=app.ROOT / 'tests')
        assert Path(self.tmp.name).absolute().parent == (app.ROOT / 'tests').absolute()
        self.old_path = app.DB_PATH
        app.DB_PATH = Path(self.tmp.name)/'carteira.sqlite3'
        # A clean checkout has no local market bootstrap. Never read installation
        # data during setup; provide only the public identities used by tests.
        with patch.object(app, 'ROOT', Path(self.tmp.name)):
            app.init_db()
        with app.connect() as c:
            for ticker,kind,sector in (('PETR4','stock','Petróleo e gás'),
                                       ('VALE3','stock','Mineração'),
                                       ('IVVB11','etf','ETF · Ações exterior')):
                c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',
                          (ticker,'Exemplo sintético '+ticker,kind,sector,0,'Test fixture',app.now()))
        self.day = app.today().isoformat()

    def tearDown(self):
        app.DB_PATH = self.old_path
        self.tmp.cleanup()

    def asset(self, ticker='ABCD3', sector='Indústria', financial=False):
        with app.connect() as c:
            c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)',(ticker,ticker,'stock',sector,int(financial),'Test fixture',app.now()))
        return app.mutate('/api/assets', {'ticker': ticker, 'name': ticker, 'sector': sector, 'financial': financial})['id']

    def trade(self, aid, side='buy', qty=10, price=20, fees=0, dt=None):
        return app.mutate('/api/trades', {'asset_id': aid, 'side': side, 'quantity': qty,
            'price': price, 'fees': fees, 'date': dt or self.day})

    def complete(self, aid, pvp=1, pe=10, debt=1, roe=20):
        with app.connect() as c:
            app.add_snapshot(c,aid,'quote',{'price':20},'Test fixture',self.day)
            app.add_snapshot(c,aid,'statistics',{'pvp':pvp,'pe':pe,'dy':3},'Test fixture',self.day)
            app.add_snapshot(c,aid,'financial',{'roe':roe,'net_debt_ebitda':debt},'Test fixture',self.day)
            pts=[{'date':(app.today()-timedelta(days=239-i)).isoformat(),'close':10+i*.1} for i in range(240)]
            app.add_snapshot(c,aid,'history',{'prices':pts},'Test fixture',self.day)

    def test_weighted_average_realized_and_sale_rollback(self):
        aid=self.asset()
        self.trade(aid,qty=10,price=20,fees=2)
        self.trade(aid,qty=10,price=30,fees=2)
        self.trade(aid,'sell',qty=5,price=40,fees=1)
        a=app.state()['assets'][0]
        self.assertAlmostEqual(a['position']['average'],25.2)
        self.assertAlmostEqual(a['position']['quantity'],15)
        self.assertAlmostEqual(a['position']['realized'],73)
        with self.assertRaises(ValueError):
            self.trade(aid,'sell',qty=16,price=30)
        self.assertEqual(len(app.state()['assets'][0]['trades']),3)

    def test_backdated_sale_and_delete_rollback(self):
        aid=self.asset()
        self.trade(aid)
        self.trade(aid,'sell',qty=5)
        buy_id=app.state()['assets'][0]['trades'][0]['id']
        with self.assertRaises(ValueError):
            app.mutate('/api/trades/delete',{'id':buy_id})
        with self.assertRaises(ValueError):
            self.trade(aid,'sell',qty=1,dt=(app.today()-timedelta(days=1)).isoformat())
        self.assertEqual(len(app.state()['assets'][0]['trades']),2)

    def test_persistence_sources_and_missing_quote(self):
        aid=self.asset()
        self.trade(aid)
        app.mutate('/api/manual',{'asset_id':aid,'kind':'statistics','asof':self.day,'source':'Annual report','pvp':1,'pe':10,'dy':''})
        app.init_db()
        a=app.state()['assets'][0]
        self.assertTrue(a['value_at_cost'])
        self.assertEqual(a['value'],200)
        self.assertIsNone(a['metrics']['dy'])
        self.assertEqual(a['snapshots']['statistics']['source'],'Manual · Annual report')
        self.assertIsNone(a['analysis']['score'])

    def test_low_valuation_quality_and_incomplete_filters(self):
        a,b=self.asset(),self.asset('EFGH3')
        self.complete(a,1,10)
        self.complete(b,2,20)
        st=app.state()
        self.assertGreater(st['assets'][0]['analysis']['score'],st['assets'][1]['analysis']['score'])
        self.assertEqual(st['assets'][0]['peer_count'],1)
        with app.connect() as c:
            app.add_snapshot(c,a,'financial',{'roe':20,'net_debt_ebitda':4},'Test fixture',self.day)
        self.assertIsNone(app.state()['assets'][0]['analysis']['score'])
        with app.connect() as c:
            app.add_snapshot(c,b,'statistics',{'pvp':-1,'pe':-2},'Test fixture',self.day)
        self.assertIsNone(app.state()['assets'][1]['analysis']['score'])

    def test_financial_and_concentration_excluded(self):
        a,b=self.asset(financial=True),self.asset('EFGH3')
        self.complete(a);self.complete(b)
        self.assertIsNone(app.state()['assets'][0]['analysis']['score'])
        self.trade(a)
        self.assertTrue(any('Setor' in p for p in app.state()['assets'][1]['analysis']['problems']))

    def test_old_data_excluded(self):
        a,b=self.asset(),self.asset('EFGH3')
        self.complete(a);self.complete(b)
        with app.connect() as c:
            app.add_snapshot(c,a,'quote',{'price':20},'Test fixture',(app.today()-timedelta(days=8)).isoformat())
        self.assertIsNone(app.state()['assets'][0]['analysis']['score'])

    def test_cdi_daily_and_ipca_multiplicative(self):
        base={'principal':1000,'months':12,'tax':15,'fee':0,'cdi':12,'selic':13,'ipca':4}
        p=app.projection({**base,'indexer':'CDI','rate':100})
        self.assertAlmostEqual(p['gross'],1120,places=7)
        self.assertAlmostEqual(p['net'],1102,places=7)
        self.assertAlmostEqual(p['real'],1102/1.04,places=7)
        p=app.projection({**base,'indexer':'CDI','rate':120})
        expected=1000*(1+((1.12)**(1/252)-1)*1.2)**252
        self.assertAlmostEqual(p['gross'],expected,places=7)
        p=app.projection({**base,'indexer':'IPCA+','rate':6})
        self.assertAlmostEqual(p['gross'],1102.4,places=7)
        with self.assertRaises(ValueError):
            app.projection({**base,'indexer':'CDI','rate':100,'cdi':None})

    def test_export_restore_and_no_secret(self):
        aid=self.asset();self.trade(aid);self.complete(aid)
        app.mutate('/api/settings',{'brapi_token':'private-test-token','asset_limit':25})
        with app.connect() as c:
            exported=app.export_data(c)
        self.assertNotIn('private-test-token',json.dumps(exported))
        self.asset('EFGH3')
        app.mutate('/api/import',exported)
        self.assertEqual(len(app.state()['assets']),1)
        self.assertTrue(app.state()['settings']['has_token'])
        self.assertEqual(app.state()['settings']['asset_limit'],25)
        self.assertTrue(list(Path(self.tmp.name).glob('antes-restauracao-*.sqlite3')))
        bad=json.loads(json.dumps(exported))
        bad['tables']['trades'][0]['side']='sell'
        with self.assertRaises(ValueError):
            app.mutate('/api/import',bad)
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)

    def test_invalid_and_future_inputs(self):
        for n in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):app.number(n)
        with self.assertRaises(ValueError):app.mutate('/api/assets',{'ticker':'INVALID'})
        aid=self.asset()
        future=(app.today()+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):self.trade(aid,dt=future)
        with self.assertRaises(ValueError):app.mutate('/api/manual',{'asset_id':aid,'kind':'quote','price':30,'asof':future,'source':'Test'})
        with self.assertRaises(ValueError):app.mutate('/api/history',{'asset_id':aid,'source':'Test','prices':[{'date':self.day,'close':1},{'date':self.day,'close':2}]})

    def test_provider_mapping_and_future_rejection(self):
        asset={'ticker':'PETR4'}
        payload={'results':[{'requestedSymbol':'PETR4','symbol':'PETR4','data':{'priceToBook':1.2,'trailingPE':6,'dividendYield':.07,'mostRecentQuarter':self.day}}]}
        with patch.object(app,'request_json',return_value=payload):
            kind,d,ref=app.fetch_stock(asset,'statistics','')
            self.assertAlmostEqual(d['dy'],7)
            self.assertEqual(ref,self.day)
        payload['results'][0]['data']={'regularMarketPrice':50,'regularMarketTime':(app.today()+timedelta(days=1)).isoformat()+'T12:00:00Z'}
        with patch.object(app,'request_json',return_value=payload),self.assertRaises(ValueError):
            app.fetch_stock(asset,'quote','')


if __name__=='__main__':
    unittest.main()
