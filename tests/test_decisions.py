import copy,unittest
from datetime import timedelta
from unittest.mock import patch
import test_app as baseline
import portfolio_strategy as strategy,sector_analysis,valuation
app=baseline.app

class DecisionTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    trade=baseline.AppTests.trade
    complete=baseline.AppTests.complete

    def goals(self,**weights):
        app.mutate('/api/settings',{'allocation_targets':{k:weights.get(k,0) for k in strategy.CLASSES}})

    def test_cap_one_and_two_choose_largest_cash_deficits(self):
        self.goals(rf=40,national=30,international=20,crypto=10)
        for cap,expected in [(1,['rf']),(2,['rf','national']),('all',['rf','national','international','crypto'])]:
            for amount in (0.01,0.02,100.01):
                p=strategy.plan(app,{'amount':amount,'max_destinations':cap})
                keys=[r['class'] for r in p['destinations']]
                self.assertEqual(keys,expected[:len(keys)])
                self.assertLessEqual(len(keys),4 if cap=='all' else cap)
                self.assertEqual(round(sum(r['amount'] for r in p['destinations'])*100),round(amount*100))
        p=strategy.plan(app,{'amount':100,'max_destinations':2})
        self.assertGreater(p['distance_after'],0)

    def test_manual_two_assets_same_class_exact_split_and_no_trades(self):
        ids=[self.asset(t) for t in ('ABCD3','EFGH3')]
        for aid in ids:self.complete(aid)
        self.goals(rf=80,national=20)
        before=app.state()
        p=strategy.plan(app,{'amount':100.01,'max_destinations':2,'destinations':['asset:'+str(i) for i in ids],'first_percent':60})
        self.assertEqual([r['amount'] for r in p['destinations']],[60.01,40])
        self.assertEqual(next(r['amount'] for r in p['classes'] if r['key']=='national'),100.01)
        self.assertEqual(next(r['after_weight'] for r in p['classes'] if r['key']=='national'),100)
        self.assertTrue(p['warnings'])
        self.assertEqual(app.state()['assets'],before['assets'])

    def test_one_manual_over_target_and_generic_class(self):
        aid=self.asset();self.complete(aid);self.trade(aid)
        self.goals(rf=100)
        p=strategy.plan(app,{'amount':100,'max_destinations':1,'destinations':['asset:'+str(aid)]})
        self.assertEqual(p['destinations'][0]['amount'],100)
        self.assertGreater(p['distance_after'],0);self.assertTrue(p['warnings'])
        p=strategy.plan(app,{'amount':100,'max_destinations':1,'destinations':['class:rf']})
        self.assertFalse(p['destinations'][0]['specific'])
        self.assertLess(p['distance_after'],p['distance_before'])

    def test_invalid_or_archived_destination_duplicates_and_bad_limits(self):
        aid=self.asset();self.goals(rf=100)
        valid={'amount':10,'max_destinations':2,'destinations':['class:rf','asset:'+str(aid)]}
        for changes in ({'max_destinations':True},{'max_destinations':3},{'max_destinations':'all'},
                        {'destinations':['asset:999']},{'destinations':['class:rf','class:rf']},
                        {'first_percent':0},{'first_percent':100},{'first_percent':True},
                        {'destinations':'class:rf'}):
            with self.assertRaises(ValueError):strategy.plan(app,{**valid,**changes})
        app.mutate('/api/assets/delete',{'id':aid})
        with self.assertRaises(ValueError):strategy.plan(app,valid)

    def test_candidate_outside_manual_choices_is_not_prioritized(self):
        ids=[self.asset(t) for t in ('ABCD3','EFGH3')]
        for aid in ids:self.complete(aid)
        self.goals(national=100)
        p=strategy.plan(app,{'amount':10,'max_destinations':1,'destinations':['asset:'+str(ids[0])]})
        row=next(c for c in p['candidates'] if c['id']==ids[1]);self.assertFalse(row['eligible'])
        self.assertIn('Ativo fora dos destinos que você escolheu.',row['reasons'])

    def test_bank_imported_cost_requires_estimate_acknowledgement(self):
        f={'id':1,'name':'CDB de teste','type':'CDB','balance':100,'balance_date':self.day,'metadata':{'bank_fixed':{'valuation':'cost'}}}
        a=strategy.allocation([], [f],{'allocation_targets':None},app.age)
        self.assertIn('custo importado',a['issues'][0])

    def test_alert_uses_raw_formula_not_safety_margin_and_needs_agreement(self):
        def sample(values,price=130):
            return {'position':{'quantity':1},'valuation':{'inputs':{'price':price},'estimates':[],
                     'methods':[{'method':k,'value':v,'ceiling':v*.8 if v else None} for k,v in zip(('Bazin','Graham','Gordon'),values)]}}
        r=valuation.alert(sample([100,100,None]));self.assertEqual(r['status'],'expensive');self.assertTrue(r['held'])
        self.assertIn('venda parcial',r['action'])
        self.assertEqual(valuation.alert(sample([100,None,None]))['status'],'above')
        r=valuation.alert(sample([100,150,None]));self.assertEqual(r['status'],'above');self.assertTrue(r['disagreement'])
        self.assertEqual(valuation.alert(sample([100,100,None],90))['status'],'within')
        self.assertEqual(valuation.alert(sample([100,100,None],None))['status'],'insufficient')
        self.assertEqual(valuation.alert(sample([100,100,None]),40)['status'],'above')

    def test_stale_quote_never_triggers_sell_alert(self):
        aid=self.asset();self.complete(aid);self.trade(aid)
        with app.connect() as c:c.execute("UPDATE snapshots SET asof=? WHERE kind='quote'",((app.today()-timedelta(days=8)).isoformat(),))
        self.assertEqual(app.state()['assets'][0]['valuation_alert']['status'],'insufficient')

    def test_info_all_metrics_and_missing_period_review_and_no_peer_confusion(self):
        self.assertEqual(set(sector_analysis.METRICS),set(sector_analysis.INDICATOR_INFO))
        aid=self.asset();self.complete(aid)
        a=app.state()['assets'][0];missing={r['metric'] for r in a['indicator_coverage']}
        self.assertNotIn('pvp',missing);self.assertIn('wacc',missing)
        a['provider_references']=[{'source':'Site público','url':'https://example.org','values':{'wacc':12},'retrieved_at':app.now()}]
        r=next(r for r in sector_analysis.coverage(a,app.age) if r['metric']=='wacc')
        self.assertEqual(r['status'],'confirm');self.assertEqual(r['found'][0]['value'],12)
        # Finding an undated value does not modify the stored metric.
        self.assertIsNone(a['sector_metrics'].get('wacc'))

    def test_dated_provider_eps_bvps_and_v2_debt_ratio(self):
        aid=self.asset()
        fields={'mostRecentQuarter':self.day,'trailingEps':2.5,'bookValue':15,'priceToBook':1.3}
        payload={'results':[{'symbol':'ABCD3','data':fields}]}
        with patch.object(app,'request_json',return_value=payload):kind,data,ref=app.fetch_stock({'ticker':'ABCD3'},'statistics','')
        with app.connect() as c:app.add_snapshot(c,aid,kind,data,'brapi · stocks/statistics',ref)
        a=app.state()['assets'][0];self.assertEqual(a['sector_metrics']['eps']['value'],2.5);self.assertEqual(a['sector_metrics']['bvps']['value'],15)
        financial={'endDate':self.day,'debtToEquity':.54833394,'totalDebt':100,'totalCash':20,'ebitda':40}
        with patch.object(app,'request_json',return_value={'results':[{'symbol':'ABCD3','data':financial}]}):kind,data,ref=app.fetch_stock({'ticker':'ABCD3'},'financial-data','')
        self.assertEqual(data['debt_equity'],.54833394);self.assertEqual(data['net_debt_ebitda'],2)
        financial['ebitda']=-1
        with patch.object(app,'request_json',return_value={'results':[{'symbol':'ABCD3','data':financial}]}):self.assertIsNone(app.fetch_stock({'ticker':'ABCD3'},'financial-data','')[1]['net_debt_ebitda'])

    def test_single_metric_entry_preserves_other_metrics_and_history(self):
        aid=self.asset();self.complete(aid)
        app.mutate('/api/manual',{'asset_id':aid,'kind':'metric:wacc','wacc':12,'asof':self.day,'source':'Relatório de teste'})
        a=app.state()['assets'][0];self.assertEqual(a['sector_metrics']['wacc']['value'],12);self.assertEqual(a['sector_metrics']['roe']['value'],20)
        app.mutate('/api/settings',{'expensive_alert_percent':40});self.assertEqual(app.state()['settings']['expensive_alert_percent'],40)
        with self.assertRaises(ValueError):app.validate_settings({'expensive_alert_percent':True})
