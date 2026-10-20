import copy,json,unittest,base64
from datetime import timedelta
from unittest.mock import patch
import b3_import,extra_sources,history_cache,portfolio_strategy,valuation
from test_research import workbook
import test_app as baseline
app=baseline.app

class PlanningTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    trade=baseline.AppTests.trade
    complete=baseline.AppTests.complete

    def goals(self,**weights):
        return {k:weights.get(k,0) for k in portfolio_strategy.CLASSES}

    def sheet(self,rows):
        headers=['Entrada/Saída','Data','Movimentação','Produto','Instituição','Quantidade','Preço unitário','Valor da Operação']
        return {'xlsx':base64.b64encode(workbook([('Movimentação',[headers]+rows)])).decode(),'filename':'extrato.xlsx'}

    def test_explicit_confirmation_exclusions_and_repeated_file(self):
        self.asset('ABCD3')
        d=self.sheet([['Entrada',self.day,'Compra','ABCD3','XP',10,20,200],['Entrada',self.day,'Compra','ABCD3','XP','inválido',20,200]])
        p=b3_import.preview(app,d)
        self.assertIsNone(p['token']);self.assertEqual(p['error_count'],1)
        self.assertIn('Quantidade',p['error_details'][0]['reason'])
        self.assertEqual(len(app.state()['assets'][0]['trades']),0)
        p=b3_import.preview(app,{**d,'skip_invalid':True})
        self.assertIsNotNone(p['token']);self.assertEqual(p['added'],1);self.assertEqual(p['ignored_count'],1)
        self.assertEqual(len(app.state()['assets'][0]['trades']),0)
        with self.assertRaisesRegex(ValueError,'Confirme as operações'):b3_import.commit(app,{'token':p['token'],'ack_ignored':True})
        with self.assertRaisesRegex(ValueError,'eventos excluídos'):b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        r=b3_import.commit(app,{'token':p['token'],'confirm_records':True,'ack_ignored':True})
        self.assertEqual(r['added'],1);self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)
        again=b3_import.preview(app,{**d,'filename':'outro-nome.xlsx','skip_invalid':True})
        self.assertEqual(len(again['previous_imports']),1);self.assertEqual(again['added'],0);self.assertEqual(again['skipped'],1)
        b3_import.commit(app,{'token':again['token'],'confirm_records':True,'ack_ignored':True})
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(len(app.state()['import_receipts']),2)
        p=b3_import.preview(app,{**d,'skip_invalid':True});self.assertEqual(p['skipped'],1)

    def test_excluding_invalid_purchase_does_not_allow_oversell(self):
        self.asset('ABCD3')
        d=self.sheet([['Entrada',self.day,'Compra','ABCD3','XP','bad',20,200],['Saída',self.day,'Venda','ABCD3','XP',5,25,125]])
        p=b3_import.preview(app,{**d,'skip_invalid':True})
        self.assertIsNone(p['token']);self.assertTrue(p['errors']);self.assertEqual(len(app.state()['assets'][0]['trades']),0)

    def test_goal_sum_and_empty_defaults(self):
        self.assertIsNone(app.state()['settings']['allocation_targets'])
        with self.assertRaises(ValueError):app.validate_settings({'allocation_targets':self.goals(rf=70,national=20)})
        with self.assertRaises(ValueError):app.validate_settings({'allocation_targets':self.goals(rf=True,national=99)})
        app.mutate('/api/settings',{'allocation_targets':self.goals(rf=60,national=40)})
        self.assertEqual(app.state()['allocation']['classes'][0]['target'],60)

    def test_new_money_deficits_no_sale_and_exact_cents(self):
        aid=self.asset();self.trade(aid,qty=10,price=20);self.complete(aid)
        app.mutate('/api/settings',{'allocation_targets':self.goals(rf=60,national=40)})
        p=portfolio_strategy.plan(app,{'amount':100})
        self.assertEqual(sum(r['amount'] for r in p['classes']),100)
        self.assertEqual(next(r for r in p['classes'] if r['key']=='national')['amount'],0)
        self.assertEqual(next(r for r in p['classes'] if r['key']=='rf')['amount'],100)
        self.assertEqual(app.state()['assets'][0]['position']['quantity'],10)
        app.mutate('/api/settings',{'allocation_targets':self.goals(rf=33.33,national=33.33,international=33.34)})
        # Zero portfolio and fractional allocation: a cent may go to just one class.
        self.trade(aid,'sell',qty=10,price=20)
        for amount in (.01,.02,100.01):
            p=portfolio_strategy.plan(app,{'amount':amount});self.assertAlmostEqual(sum(r['amount'] for r in p['classes']),amount)

    def test_missing_prices_block_unconfirmed_estimates(self):
        aid=self.asset();self.trade(aid)
        app.mutate('/api/settings',{'allocation_targets':self.goals(rf=50,national=50)})
        with self.assertRaisesRegex(ValueError,'estimativas'):portfolio_strategy.plan(app,{'amount':10})
        p=portfolio_strategy.plan(app,{'amount':10,'accept_estimates':True});self.assertTrue(p['issues'])
        self.assertFalse(p['candidates'][0]['eligible'])

    def test_etfs_fixed_products_and_manual_exposure(self):
        for sector,expected in [('ETF · Ações exterior','international'),('ETF · Renda fixa','rf'),('ETF · Cripto','crypto'),('ETF · A definir','other')]:
            self.assertEqual(portfolio_strategy.classify({'asset_type':'etf','sector':sector}),expected)
        self.assertEqual(portfolio_strategy.classify({'type':'Fundo multimercado'},True),'other')
        aid=self.asset();self.trade(aid);self.complete(aid)
        app.mutate('/api/settings',{'allocation_overrides':{'asset:'+str(aid):'international'}})
        row=app.state()['allocation']['items'][0];self.assertEqual(row['class'],'international');self.assertTrue(row['manual'])

    def test_cdi_net_reference_is_dated_and_taxed(self):
        app.mutate('/api/settings',{'allocation_targets':self.goals(rf=100)})
        app.mutate('/api/macro/manual',{'cdi':12,'asof':self.day,'source':'Teste'})
        p=portfolio_strategy.plan(app,{'amount':1000})
        self.assertAlmostEqual(p['benchmark']['annual_net'],9.9)
        with app.connect() as c:c.execute("UPDATE macro SET asof=?",((app.today()-timedelta(days=8)).isoformat(),))
        self.assertIsNone(portfolio_strategy.plan(app,{'amount':100})['benchmark'])

    def test_history_fresh_cache_no_request_and_five_years_preserved(self):
        aid=self.asset();self.complete(aid)
        with patch.object(app,'request_json',side_effect=AssertionError('must not fetch')):
            self.assertTrue(history_cache.fetch(app,{'asset_id':aid,'years':1})['used_cache'])
        pts=[{'date':self.day,'close':30}]
        with patch.object(extra_sources,'yahoo',return_value={'history':({'prices':pts,'years':5},self.day,'Yahoo Finance · chart/ABCD3.SA')}) as provider:
            r=history_cache.fetch(app,{'asset_id':aid,'years':5});self.assertFalse(r['used_cache']);self.assertEqual(provider.call_args.args[-1],5)
        with patch.object(app,'request_json',side_effect=AssertionError('must not fetch')):
            self.assertEqual(history_cache.fetch(app,{'asset_id':aid,'years':1})['years'],5)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(app.state()['assets'][0]['history_info']['years'],5)

    def test_history_snapshot_compaction_preserves_manual_and_accounting_dates(self):
        aid=self.asset();pts=[{'date':self.day,'close':20}]
        with app.connect() as c:
            for price in (20,20,21):app.add_snapshot(c,aid,'history',{'prices':[{'date':self.day,'close':price}]},'Yahoo Finance · chart/ABCD3.SA',self.day)
            app.add_snapshot(c,aid,'history',{'prices':pts},'Manual · arquivo',self.day)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM snapshots WHERE kind='history'").fetchone()[0],2)
            old=(app.today()-timedelta(days=90)).isoformat()
            app.add_snapshot(c,aid,'financial',{'roe':10},'Fundamentus · detalhes/ABCD3',old)
            app.add_snapshot(c,aid,'financial',{'roe':15},'Fundamentus · detalhes/ABCD3',self.day)
        self.assertEqual(len(app.state()['assets'][0]['fundamental_history']['roe']),2)

    def test_yahoo_quote_only_never_replaces_long_history(self):
        from datetime import datetime,timezone,time
        # A fixed time on the Brazilian reference date also works after midnight UTC.
        timestamp=datetime.combine(app.today(),time(12),timezone.utc).timestamp()
        payload={'chart':{'result':[{'meta':{'symbol':'ABCD3.SA','currency':'BRL','regularMarketPrice':10,'regularMarketTime':timestamp},'timestamp':[], 'indicators':{}}]}}
        urls=[]
        result=extra_sources.yahoo('ABCD3',lambda url:urls.append(url) or payload,app.today,False,5)
        self.assertNotIn('history',result);self.assertIn('range=5d',urls[0])

    def test_automatic_valuation_estimates_are_labelled_and_saved_inputs_win(self):
        aid=self.asset();self.complete(aid)
        a=app.state()['assets'][0];v=a['valuation']
        self.assertIn('eps',v['estimates']);self.assertIn('dividends_per_share',v['estimates'])
        self.assertAlmostEqual(v['inputs']['eps'],2);self.assertAlmostEqual(v['methods'][0]['value'],10)
        self.assertIsNone(v['methods'][2]['value'])
        saved={'inputs':{'dividends_per_share':3,'eps':4,'bvps':25,'target_yield':6,'safety_margin':20},'saved_at':app.now()}
        v=valuation.for_asset(a,saved,app.number,app.age)
        self.assertEqual(v['methods'][0]['value'],50);self.assertEqual(v['estimates'],[])

    def test_valuation_old_prices_or_missing_metrics_do_not_invent_values(self):
        aid=self.asset();self.complete(aid)
        with app.connect() as c:c.execute("UPDATE snapshots SET asof=? WHERE kind='quote'",((app.today()-timedelta(days=8)).isoformat(),))
        v=app.state()['assets'][0]['valuation'];self.assertIsNone(v['inputs']['price'])
        self.assertTrue(all(m['value'] is None for m in v['methods']))

if __name__=='__main__':unittest.main()
