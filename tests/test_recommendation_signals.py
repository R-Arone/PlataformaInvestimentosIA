"""Synthetic market series and dated forecasts; no claims of investment performance."""
import copy
from datetime import timedelta
import unittest
from unittest.mock import patch

import investment_exposure
import long_term
import portfolio_strategy
import recommendation_signals as signals
import market_signals
import test_long_term as base
import test_signals


def history(local,asset,growth=.002,count=130):
    points=[dict(date=(local.today()-timedelta(days=count-i)).isoformat(),close=10*(1+growth)**i) for i in range(count)]
    asset['snapshots']['history']=dict(asof=points[-1]['date'],retrieved_at=local.now(),source='Fictional adjusted prices',data=dict(prices=points,currency='BRL'))


def forecast(local,asset,score=80,horizon=20):
    return dict(ticker=asset['ticker'],status='ready',stale=False,asof=(local.today()-timedelta(days=1)).isoformat(),
        analyzed_at=local.now(),market='BR',currency='BRL',source='Fictional model fixture',
        horizons={str(horizon):dict(incremental=dict(status='ready',score=score,direction='up' if score>0 else 'down',trained=150))})


def established():
    local=base.LongTermTests().established_portfolio()
    for row in local.data['assets']:history(local,row)
    return local


def run(local,**opts):
    return long_term.recommend(local,dict(amount=5000,min_ticket=500,max_assets=2,allocation_style='opportunities',**opts))


class RecommendationSignalsTests(unittest.TestCase):
    def test_observed_rules_are_not_ai_and_depend_on_completed_recent_history(self):
        local=base.fixture();asset=local.data['assets'][0];history(local,asset)
        market=signals.market(local,asset)
        self.assertTrue(market['available']);self.assertTrue(market['positive']);self.assertGreater(market['score'],50)
        self.assertAlmostEqual(market['return63'],((1.002)**63-1)*100)
        history(local,asset,-.002)
        down=signals.market(local,asset);self.assertFalse(down['positive']);self.assertLess(down['score'],50)
        points=asset['snapshots']['history']['data']['prices']
        points.append(dict(date=local.today().isoformat(),close=1e6))
        points.append(dict(date=(local.today()+timedelta(days=1)).isoformat(),close=1e6))
        self.assertEqual(down,signals.market(local,asset))
        history(local,asset,count=63);self.assertFalse(signals.market(local,asset)['available'])
        history(local,asset)
        asset['snapshots']['history']['data']['prices']=points[:-15]
        self.assertFalse(signals.market(local,asset)['available'])

    def test_unknown_currency_and_asset_scope_are_explicit(self):
        local=base.fixture();asset=local.data['assets'][0];history(local,asset)
        asset['snapshots']['history']['data']['currency']='USD'
        self.assertFalse(signals.market(local,asset)['available'])
        asset['asset_type']='foreign';self.assertFalse(signals.market(local,asset)['available'])

    def test_models_must_be_ready_fresh_matching_currency_and_selected_horizon(self):
        local=base.fixture();asset=local.data['assets'][0];row=forecast(local,asset)
        local.data['signals']={'rows':[row]}
        self.assertEqual(signals.ai(local,asset,local.data,20)['score'],90)
        self.assertFalse(signals.ai(local,asset,local.data,5)['available'])
        for changes in (dict(stale=True),dict(asof='2026-06-01'),dict(asof='2026-06-16'),dict(analyzed_at='2026-06-16'),dict(currency='USD'),dict(market='US'),dict(status='unknown')):
            with self.subTest(changes=changes):
                local.data['signals']['rows']=[{**row,**changes}]
                self.assertFalse(signals.ai(local,asset,local.data,20)['available'])
        local.data['signals']['rows']=[row];asset['asset_type']='etf'
        self.assertFalse(signals.ai(local,asset,local.data,20)['available'])

    def test_invalid_predictions_never_affect_the_score_and_conflicting_models_are_visible(self):
        local=base.fixture();asset=local.data['assets'][0];row=forecast(local,asset)
        local.data['signals']={'rows':[row]};models=row['horizons']['20']
        models.update(bayesian=dict(status='ready',probabilities=dict(down=95,stable=5,up=0)),
                      pretrained=dict(status='ready',low_return=-2,median_return=1,high_return=4))
        reading=signals.ai(local,asset,local.data,20,{'volatility':25})
        self.assertEqual(len(reading['models']),3);self.assertTrue(reading['disagreement'])
        models['incremental']['score']=float('nan');models['bayesian']['probabilities']['up']=150
        models['pretrained']['low_return']=8
        self.assertFalse(signals.ai(local,asset,local.data,20,{'volatility':25})['available'])

    def test_real_ai_adjustment_changes_priority_order_and_money(self):
        local=established();first,second=local.data['assets'][:2]
        local.data['signals']={'rows':[forecast(local,first,-100),forecast(local,second,100)]}
        before=copy.deepcopy(local.data)
        plan=run(local,mode='context')
        self.assertEqual(local.data,before)
        effect=plan['ai_effect'];self.assertEqual(effect['applied_count'],2)
        self.assertTrue(effect['ranking_changed']);self.assertTrue(effect['allocation_changed'])
        rejected=next(r for r in plan['candidates'] if r['id']==first['id'])
        self.assertFalse(rejected['eligible']);self.assertEqual(rejected['amount'],0)
        chosen=plan['candidates'][0];self.assertEqual(chosen['id'],second['id']);self.assertGreater(chosen['amount'],0)
        self.assertAlmostEqual(chosen['priority'],.7*chosen['market_signal']['score']+.3*100,places=3)
        self.assertTrue(all(r['after_issuer_weight']<=20 for r in plan['candidates'] if r['amount']))
        self.assertEqual(plan['invested']+plan['unassigned'],5000)
        self.assertEqual(sum(r['budget'] for r in plan['classes']),5000)
        # Comparison cards must use the selected IA rather than quietly reverting to base.
        chosen_ids={d['id'] for c in plan['comparisons'] if c['allocation_style']=='opportunities' for d in c['destinations']}
        self.assertNotIn(first['id'],chosen_ids)

    def test_ai_also_changes_the_fundamental_versions_and_cannot_override_quality(self):
        local=established();a,b=local.data['assets'][:2]
        local.data['signals']={'rows':[forecast(local,a,-100),forecast(local,b,100)]}
        plan=long_term.recommend(local,dict(amount=5000,mode='context',allocation_style='gradual',min_ticket=500,max_assets=2))
        self.assertTrue(plan['ai_effect']['allocation_changed']);self.assertEqual(plan['candidates'][0]['id'],b['id'])
        b['company_research']['study']['groups'][0]['checks'][0]['status']='fail'
        blocked=next(r for r in run(local,mode='context')['candidates'] if r['id']==b['id'])
        self.assertTrue(blocked['ai']['applied']);self.assertFalse(blocked['eligible']);self.assertEqual(blocked['amount'],0)

    def test_no_model_means_honest_identical_fallback(self):
        local=established();p=run(local,mode='context');other=run(local,mode='base')
        self.assertEqual([(r['id'],r['amount'],r['priority']) for r in p['candidates']],[(r['id'],r['amount'],r['priority']) for r in other['candidates']])
        self.assertEqual(p['ai_effect']['applied_count'],0);self.assertFalse(p['ai_effect']['allocation_changed'])
        self.assertTrue(all(not r['ai']['applied'] and r['ai']['reason'] for r in p['candidates']))

    def test_opportunities_ignore_missing_zero_and_overweight_class_goals(self):
        local=established()
        local.data['settings']['allocation_targets'].update(national=0,rf=100)
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],local.data['settings'],local.age)
        p=run(local);self.assertGreater(p['invested'],0)
        self.assertTrue(all(r['components']['rebalance']==0 for r in p['candidates']))
        self.assertEqual(next(r for r in p['classes'] if r['key']=='national')['ideal_budget'],0)
        local.data['settings']['allocation_targets']=None
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],local.data['settings'],local.age)
        p=run(local);self.assertGreater(p['invested'],0);self.assertIsNone(p['distance_after'])
        self.assertFalse(p['has_targets']);self.assertFalse(p['next_classes']);self.assertEqual(len(p['comparisons']),3)
        self.assertTrue(all(c['distance_after'] is None for c in p['comparisons']))

    def test_opportunities_dont_require_value_discount_but_cannot_override_risk_or_quote(self):
        local=established();asset=local.data['assets'][0]
        asset['valuation']['suggestion'].update(value=5,ceiling=4)
        p=run(local);row=next(r for r in p['candidates'] if r['id']==asset['id'])
        self.assertTrue(row['eligible']);self.assertTrue(row['price_warnings'])
        asset['snapshots']['quote']['asof']='2026-06-01'
        row=next(r for r in run(local)['candidates'] if r['id']==asset['id']);self.assertFalse(row['eligible'])
        local=base.fixture(2)
        for asset in local.data['assets']:history(local,asset)
        self.assertEqual(run(local)['invested'],0)  # No dilution with unspent cash.

    def test_positive_ai_can_flag_a_turn_but_has_to_be_available(self):
        local=established();asset=local.data['assets'][0];history(local,asset,-.001)
        self.assertFalse(next(r for r in run(local)['candidates'] if r['id']==asset['id'])['eligible'])
        local.data['signals']={'rows':[forecast(local,asset,100)]}
        self.assertTrue(next(r for r in run(local,mode='context')['candidates'] if r['id']==asset['id'])['eligible'])
        local.data['signals']['rows'][0]['stale']=True
        self.assertFalse(next(r for r in run(local,mode='context')['candidates'] if r['id']==asset['id'])['eligible'])

    def test_etf_uses_its_area_and_market_without_inventing_company_quality_or_ai(self):
        local=established();asset=local.data['assets'][0]
        asset.update(asset_type='etf',ticker='ABTC11',sector='ETF · Bitcoin e renda fixa')
        asset.pop('company_research');asset['exposure']=investment_exposure.metadata(asset,{})
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],local.data['fixed'],local.data['settings'],local.age)
        row=next(r for r in run(local,mode='context',accept_estimates=True)['candidates'] if r['id']==asset['id'])
        self.assertTrue(row['eligible']);self.assertIsNone(row['quality']);self.assertFalse(row['ai']['applied'])
        asset['exposure']={'focus':'unknown'}
        self.assertFalse(next(r for r in run(local,accept_estimates=True)['candidates'] if r['id']==asset['id'])['eligible'])

    def test_fii_mandatory_discard_survives_positive_market_and_no_goals(self):
        local=established();asset=local.data['assets'][0];asset['asset_type']='fii'
        asset['fii_research']=asset.pop('company_research')
        for pvp,eligible in ((1.4,True),(1.5,True),(1.50001,False)):
            asset['snapshots']['statistics']={'asof':local.today().isoformat(),'data':{'pvp':pvp}}
            with patch.object(local,'age',lambda value:(local.today()-base.date.fromisoformat(value[:10])).days if value else 99999):
                row=next(r for r in run(local)['candidates'] if r['id']==asset['id'])
            self.assertEqual(row['eligible'],eligible)

    def test_horizon_validation(self):
        for value in (True,2,20.0,'20.0',None):
            with self.subTest(value=value),self.assertRaises(ValueError):long_term.options(base.fixture(),dict(amount=1,signal_horizon=value))
        self.assertEqual(long_term.options(base.fixture(),dict(amount=1,signal_horizon='5'))['signal_horizon'],5)

    def test_utc_next_day_is_valid_in_brazil_but_future_instant_is_not(self):
        local=base.fixture()
        with patch.object(local,'now',lambda:'2026-06-16T01:00:00+00:00'):
            self.assertTrue(signals.fresh(local,'2026-06-16T00:30:00+00:00'))
            self.assertFalse(signals.fresh(local,'2026-06-16T02:00:00+00:00'))
            self.assertFalse(signals.fresh(local,'2026-06-16'))
            self.assertFalse(signals.fresh(local,'2026-06-15T22:00:00'))


class RecommendationModelIntegrationTests(unittest.TestCase):
    setUp=base.baseline.AppTests.setUp
    tearDown=base.baseline.AppTests.tearDown
    asset=base.baseline.AppTests.asset

    def test_actual_local_model_cache_is_reused_without_retraining_or_database_mutation(self):
        app=base.app;aid=self.asset()
        points=test_signals.series(280,end=app.today()-timedelta(days=1))
        with app.connect() as c:
            app.add_snapshot(c,aid,'history',{'prices':[dict(date=d,close=v) for d,v in points.items()]},'Fictional prices',next(reversed(points)))
            app.add_snapshot(c,aid,'quote',{'price':100},'Fictional quote',app.today().isoformat())
        with patch.object(app,'request_json',side_effect=AssertionError('No network')):
            market_signals.analyze(app,{'market':'BR','pretrained':False})
        with app.connect() as c:before=c.serialize()
        with patch.object(app,'request_json',side_effect=AssertionError('No network')):
            result=long_term.recommend(app,dict(amount=5000,mode='context',allocation_style='opportunities'))
        self.assertEqual(result['ai_effect']['applied_count'],1,result['candidates'][0]['ai']['reason'])
        model=result['candidates'][0]['ai']
        self.assertTrue(model['applied']);self.assertIn('incremental',[r['key'] for r in model['models']])
        self.assertEqual(model['horizon'],20)
        with app.connect() as c:self.assertEqual(c.serialize(),before)


if __name__=='__main__':unittest.main()
