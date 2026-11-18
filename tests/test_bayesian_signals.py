"""Independent distribution checks, chronology and same-origin comparisons."""
import copy
from datetime import date, timedelta
import math
import unittest
from unittest.mock import patch

from aporte_brasil.market import bayesian_signals as bayes
from aporte_brasil.market import market_signals as signals
import test_signals as existing
from test_signals import series


class BayesianMathTests(unittest.TestCase):
    def test_student_distribution_matches_closed_form_cauchy(self):
        for x in (-100.,-4.,-1.,-.01,0.,.01,1.,4.,100.):
            self.assertAlmostEqual(bayes.student_cdf(x,1),.5+math.atan(x)/math.pi,places=12)
        for p in (.01,.1,.5,.9,.99):
            self.assertAlmostEqual(bayes.student_quantile(p,1),math.tan(math.pi*(p-.5)),places=10)

    def test_student_two_degrees_and_known_quantiles(self):
        for x in (-9.,-1.,0.,1.,9.):
            expected=.5+x/(2*math.sqrt(2+x*x))
            self.assertAlmostEqual(bayes.student_cdf(x,2),expected,places=12)
        self.assertAlmostEqual(bayes.student_quantile(.975,10),2.2281388519649385,places=8)
        for n in (6,20,100,200):
            self.assertEqual(bayes.student_cdf(0,n),.5)
            self.assertAlmostEqual(bayes.student_cdf(2,n)+bayes.student_cdf(-2,n),1.)

    def test_conjugate_posterior_matches_batch_intercept_formula(self):
        model=bayes.new_model()
        targets=[.4,-.2,.8,.1]
        features=[0.]*(bayes.DIMENSION-1)
        with patch.object(bayes,'STATE_DISCOUNT',1.),patch.object(bayes,'VAR_DISCOUNT',1.):
            for value in targets:bayes.learn(model,features,value)
            # Independent batch normal/inverse-gamma posterior, prior precision=4.
            posterior_precision=4+len(targets)
            mean=sum(targets)/posterior_precision
            d=6+sum(v*v for v in targets)-posterior_precision*mean*mean
            self.assertAlmostEqual(model['mean'][0],mean)
            self.assertAlmostEqual(model['covariance'][0][0],1/posterior_precision)
            self.assertAlmostEqual(model['sum_squares'],d)
            self.assertAlmostEqual(model['degrees'],6+len(targets))
            pred=bayes.predictive(model,features)
            self.assertAlmostEqual(pred['scale']**2,d/model['degrees']*(1+1/posterior_precision))

    def test_full_predictive_includes_coefficient_uncertainty(self):
        model=bayes.new_model()
        x=[0.]*(bayes.DIMENSION-1)
        prior=bayes.predictive(model,x)
        for i in range(100):bayes.learn(model,x,.25+(.2 if i%2 else -.2))
        posterior=bayes.predictive(model,x)
        self.assertLess(posterior['scale'],prior['scale'])
        self.assertGreater(posterior['positive_probability'],.5)
        self.assertAlmostEqual(sum(posterior['probabilities']),1.)

    def test_only_matured_disjoint_targets_train_and_repeat_is_idempotent(self):
        points=series(950)
        for h in signals.HORIZONS:
            model,report=bayes.update_model(points,[],{},h)
            expected=(len(points)-1-bayes.START-h)//h+1
            self.assertEqual(model['trained'],expected)
            again,same=bayes.update_model(points,[],{},h,model)
            self.assertEqual(model,again)
            self.assertEqual(report,same)
            self.assertAlmostEqual(sum(report['probabilities'].values()),100.)
            self.assertLessEqual(report['low_return'],report['median_return'])
            self.assertLessEqual(report['median_return'],report['high_return'])
            self.assertFalse(report['calibrated'])

    def test_appended_history_matches_full_pass_and_same_origin_comparator(self):
        points=series(430)
        prefix=dict(list(points.items())[:300])
        first,log={},{}
        inc,_=signals.update_model(prefix,[],5,forecasts=first)
        initial,_=bayes.update_model(prefix,[],{},5,incremental=first)
        signals.update_model(points,[],5,inc,forecasts=log)
        extended,report=bayes.update_model(points,[],{},5,initial,incremental=log)
        full_log={}
        signals.update_model(points,[],5,forecasts=full_log)
        full,whole=bayes.update_model(points,[],{},5,incremental=full_log)
        self.assertEqual(extended,full)
        self.assertEqual(report,whole)
        e=report['evaluations']['simulated']
        self.assertGreater(e['matched_count'],0)
        self.assertEqual(e['matched_count'],e['count'])
        self.assertEqual(sum(c['count'] for c in e['calibration'][0]),e['count'])

    def test_historical_features_do_not_see_future_sector_prices(self):
        points=series(300)
        peers=[series(300,direction=.8),series(300,direction=.5)]
        factors={'Outro setor':[series(300,direction=-1)]}
        i=180
        before=bayes.features_at(points,peers,factors,i)
        mutated=copy.deepcopy(factors)
        for d in list(points)[i+1:]:mutated['Outro setor'][0][d]*=10
        self.assertEqual(before,bayes.features_at(points,peers,mutated,i))
        coverage=before[2]
        self.assertAlmostEqual(coverage['sector_correlation'],2/3)
        self.assertAlmostEqual(coverage['other_sectors_correlation'],-2/3)

    def test_corrections_to_other_sectors_reset_posterior(self):
        points=series(400)
        factors={'Outro':[series(400,direction=.5)]}
        model,_=bayes.update_model(points,[],factors,5)
        corrected=copy.deepcopy(factors)
        corrected['Outro'][0][next(iter(points))]*=1.01
        rebuilt,result=bayes.update_model(points,[],corrected,5,model)
        fresh,_=bayes.update_model(points,[],corrected,5)
        self.assertTrue(result['reset'])
        self.assertEqual(rebuilt,fresh)

    def test_same_close_context_refresh_does_not_train_and_delayed_context_is_discarded(self):
        points=series(425)
        initial,_=bayes.update_model(points,[],{},5)
        context={'sentiment':.8,'_generated_at':'2026-10-06T22:00:00+00:00'}
        updated,report=bayes.update_model(points,[],{},5,initial,context)
        self.assertEqual(updated['mean'],initial['mean'])
        self.assertEqual(updated['trained'],initial['trained'])
        self.assertTrue(report['coverage']['sentiment'])
        again,_=bayes.update_model(points,[],{},5,updated,context)
        self.assertEqual(updated,again)
        # 424 is a selected origin for horizon=1, and its target is already past.
        prefix=dict(list(points.items())[:-1])
        delayed,_=bayes.update_model(prefix,[],{},1,context=context)
        extended,result=bayes.update_model(points,[],{},1,delayed)
        full,_=bayes.update_model(points,[],{},1)
        self.assertEqual(extended['mean'],full['mean'])
        self.assertEqual(result['evaluations']['live']['count'],0)

    def test_prospective_target_is_evaluated_only_after_it_matures(self):
        points=series(400,end=date(2026,10,5))
        prefix=dict(list(points.items())[:-1])
        origin=next(reversed(prefix))
        model,report=bayes.update_model(prefix,[],{},1,context={'_generated_at':origin+'T22:00:00+00:00'})
        self.assertEqual(report['evaluations']['live']['count'],0)
        extended,report=bayes.update_model(points,[],{},1,model)
        self.assertEqual(report['evaluations']['live']['count'],1)
        self.assertEqual(extended['metrics']['live']['count'],1)

    def test_insufficient_history_never_presents_prior_as_ready_probabilities(self):
        _,report=bayes.update_model(series(250),[],{},20)
        self.assertEqual(report['status'],'learning')
        self.assertIsNone(report['probabilities'])

    def test_shared_feature_cache_preserves_each_horizon_forecast(self):
        points=series(400)
        factors={'Outro':[series(400,direction=-1)]}
        cache={}
        for h in signals.HORIZONS:
            cached,report=bayes.update_model(points,[],factors,h,feature_cache=cache)
            full,expected=bayes.update_model(points,[],factors,h)
            self.assertEqual(cached,full)
            self.assertEqual(report,expected)

    def test_rolling_window_preserves_learning_phase_and_detects_retained_corrections(self):
        points=series(500)
        prefix=dict(list(points.items())[:450])
        rolled=dict(list(points.items())[25:])
        for h in signals.HORIZONS:
            previous,_=bayes.update_model(prefix,[],{},h)
            updated,report=bayes.update_model(rolled,[],{},h,previous)
            full,_=bayes.update_model(points,[],{},h)
            self.assertFalse(report['reset'])
            self.assertEqual(updated['trained'],full['trained'])
            self.assertEqual(updated['mean'],full['mean'])
            self.assertEqual(updated['pending'],full['pending'])
            corrected=dict(rolled);corrected[list(corrected)[100]]*=1.01
            _,changed=bayes.update_model(corrected,[],{},h,updated)
            self.assertTrue(changed['reset'])


class BayesianIntegrationTests(unittest.TestCase):
    setUp=existing.IntegrationTests.setUp
    tearDown=existing.IntegrationTests.tearDown
    asset=existing.IntegrationTests.asset
    trade=existing.IntegrationTests.trade
    prepare=existing.IntegrationTests.prepare

    def test_local_model_is_saved_alongside_incremental_without_chronos_or_holdings_changes(self):
        from test_app import app
        self.prepare('AAAA3');self.prepare('BBBB3')
        self.trade(1)
        before=app.state()['assets']
        with patch.object(signals,'pretrained',side_effect=AssertionError('Should not download')):
            signals.analyze(app,{'pretrained':False})
        state=app.state()
        self.assertEqual(before,state['assets'])
        b=state['signals']['rows'][0]['horizons']['1']['bayesian']
        self.assertEqual(b['status'],'ready')
        self.assertAlmostEqual(sum(b['probabilities'].values()),100.)
        with app.connect() as c:
            models=app.read_cache(c,'market_signal_models',{})
        self.assertIn('AAAA3:bayes:20',models)
        signals.analyze(app,{'pretrained':False})
        with app.connect() as c:self.assertEqual(models,app.read_cache(c,'market_signal_models',{}))
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(data))
        with app.connect() as c:self.assertEqual(app.read_cache(c,'market_signal_models',{}),{})

    def test_other_sector_changes_mark_forecast_stale_and_us_is_separate(self):
        from test_app import app
        self.prepare('AAAA3');self.prepare('BBBB3')
        with app.connect() as c:c.execute("UPDATE assets SET sector='Outro' WHERE ticker='BBBB3'")
        signals.analyze(app,{'ticker':'AAAA3','pretrained':False})
        row=app.state()['signals']['rows'][0]
        self.assertFalse(row['stale'])
        self.assertEqual(row['horizons']['1']['bayesian']['coverage']['other_sectors'],['Outro'])
        with app.connect() as c:c.execute("UPDATE assets SET sector='Mudou' WHERE ticker='BBBB3'")
        self.assertTrue(app.state()['signals']['rows'][0]['stale'])
        with app.connect() as c:before=app.read_cache(c,'market_signal_models',{})['AAAA3:5']
        signals.analyze(app,{'ticker':'AAAA3','pretrained':False})
        refreshed=app.state()['signals']['rows'][0]['horizons']['5']['bayesian']
        self.assertTrue(refreshed['reset'])
        self.assertGreater(refreshed['evaluations']['simulated']['matched_count'],0)
        with app.connect() as c:after=app.read_cache(c,'market_signal_models',{})['AAAA3:5']
        self.assertEqual(before,after)
        assets=[{'ticker':'AAPL','asset_type':'foreign','sector':'Tech'},
                {'ticker':'MSFT','asset_type':'foreign','sector':'Tech'},
                {'ticker':'JPM','asset_type':'foreign','sector':'Bancos'},
                {'ticker':'BBAS3','asset_type':'stock','sector':'Bancos'}]
        factors=signals.market_factors(assets[0],assets,{a['ticker']:series(100) for a in assets})
        self.assertEqual(list(factors),['Bancos'])
        self.assertEqual(len(factors['Bancos']),1)


if __name__=='__main__':unittest.main()
