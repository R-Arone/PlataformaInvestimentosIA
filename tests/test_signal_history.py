"""History expansion, cold-start thresholds and reasons for missing coupling."""
from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bayesian_signals as bayes
import market_signals as signals
import portfolio_coupling as coupling
from test_signals import series, asset
import test_signals as existing
from test_app import app


class HistoryTests(unittest.TestCase):
    def test_cold_start_thresholds_match_matured_nonoverlapping_targets(self):
        for h,required in ((1,104),(5,264),(20,864)):
            points=series(required)
            before=dict(list(points.items())[:-1])
            _,short=bayes.update_model(before,[],{},h)
            _,ready=bayes.update_model(points,[],{},h)
            self.assertEqual(short['trained'],39)
            self.assertIsNone(short['probabilities'])
            self.assertEqual(ready['status'],'ready')
            need=signals.history_requirements(before)['bayesian'][str(h)]
            self.assertEqual(need,{'minimum_closes':required,'missing_closes':1})

    def rows(self):
        return [dict(id=i,ticker=t,asset_type=k,verified=v,position={'quantity':q})
                for i,t,k,v,q in ((1,'AAAA3','stock',1,1),(2,'BBBB3','stock',1,0),
                                  (3,'ETF11','etf',1,1),(4,'AAPL','foreign',1,1),
                                  (5,'BAD3','stock',0,1))]

    def test_signals_fetches_selected_and_references_preserving_holdings(self):
        rows=self.rows();app=SimpleNamespace(state=lambda:{'assets':rows})
        with patch.object(signals.history_cache,'fetch',return_value={}) as fetch:
            self.assertEqual(signals.prepare_histories(app,{'history':'signals','ticker':'BBBB3'}),[])
        self.assertEqual([c.args[1] for c in fetch.call_args_list],
                         [{'asset_id':2,'years':5},{'asset_id':1,'years':5},{'asset_id':4,'years':5}])
        self.assertEqual(rows,self.rows())

    def test_portfolio_fetch_excludes_watchlist_unverified_and_usd(self):
        app=SimpleNamespace(state=lambda:{'assets':self.rows()})
        with patch.object(signals.history_cache,'fetch',return_value={}) as fetch:
            signals.prepare_histories(app,{'history':'portfolio'})
        self.assertEqual([c.args[1]['asset_id'] for c in fetch.call_args_list],[1,3])

    def test_failed_fetch_continues_with_other_references(self):
        app=SimpleNamespace(state=lambda:{'assets':self.rows()})
        with patch.object(signals.history_cache,'fetch',side_effect=[ValueError('no data'),{},{}]) as fetch:
            errors=signals.prepare_histories(app,{'history':'signals'})
        self.assertEqual(errors,['AAAA3'])
        self.assertEqual(fetch.call_count,3)

    def test_background_download_finishes_before_analysis_and_reports_failures(self):
        app=SimpleNamespace(now=lambda:'2026-10-06T22:00:00+00:00')
        events=[]
        class InlineThread:
            def __init__(self,target,daemon):self.target=target
            def start(self):self.target()
        with patch.object(signals,'JOB',dict(running=False)),patch.object(signals.threading,'Thread',InlineThread), \
             patch.object(signals,'prepare_histories',side_effect=lambda *a:events.append('fetch') or ['AAAA3']), \
             patch.object(signals,'analyze',side_effect=lambda *a:events.append('analyze')):
            job=signals.start(app,{'history':'signals','pretrained':False})
            self.assertEqual(events,['fetch','analyze'])
            self.assertFalse(job['running'])
            self.assertIn('AAAA3',job['error'])
            self.assertIn('preservados',job['error'])

    def test_portfolio_download_does_not_run_forecasting(self):
        app=SimpleNamespace(now=lambda:'2026-10-06T22:00:00+00:00')
        class InlineThread:
            def __init__(self,target,daemon):self.target=target
            def start(self):self.target()
        with patch.object(signals,'JOB',dict(running=False)),patch.object(signals.threading,'Thread',InlineThread), \
             patch.object(signals,'prepare_histories',return_value=[]),patch.object(signals,'analyze') as analyze:
            job=signals.start(app,{'history':'portfolio','pretrained':False})
            self.assertFalse(job['running'])
            analyze.assert_not_called()

    def test_coupling_reports_individual_history_and_common_dates(self):
        day=date(2026,10,6);stamp='2026-10-06T22:00:00+00:00'
        a=asset('AAAA3',series(80));b=asset('BBBB3',series(50))
        result=coupling.analyze([a,b],[],day,stamp)
        self.assertEqual(result['held_count'],2)
        self.assertEqual(result['eligible_count'],1)
        self.assertEqual([r['count'] for r in result['history']],[80,50])
        # Individually long histories with only 60 shared dates remain unknown.
        dates=series(140);keys=list(dates)
        a=asset('AAAA3',{d:v for d,v in dates.items() if d not in keys[60:100]})
        b=asset('BBBB3',{d:v for d,v in dates.items() if d not in keys[20:60]})
        result=coupling.analyze([a,b],[],day,stamp)
        self.assertEqual(result['eligible_count'],2)
        self.assertEqual(result['common_closes'],60)
        self.assertEqual(result['status'],'unknown')
        self.assertEqual(result['minimum_closes'],64)


class DownloadIntegrationTests(unittest.TestCase):
    setUp=existing.IntegrationTests.setUp
    tearDown=existing.IntegrationTests.tearDown
    asset=existing.IntegrationTests.asset
    trade=existing.IntegrationTests.trade
    prepare=existing.IntegrationTests.prepare

    def test_download_expands_short_history_and_unlocks_twenty_day_model(self):
        aid=self.prepare();self.trade(aid)
        end=app.today()-timedelta(days=1)
        short=series(100,end=end);long=series(1000,end=end)
        with app.connect() as c:
            c.execute("DELETE FROM snapshots WHERE asset_id=? AND kind='history'",(aid,))
            app.add_snapshot(c,aid,'history',{'prices':[{'date':d,'close':v} for d,v in short.items()],
                'years':1},'Yahoo Finance · chart/AAAA3.SA',next(reversed(short)))
        signals.analyze(app,{'pretrained':False})
        before=app.state()
        self.assertEqual(before['signals']['rows'][0]['history']['count'],100)
        self.assertEqual(before['signals']['rows'][0]['horizons']['20']['bayesian']['status'],'learning')
        result={'history':({'prices':[{'date':d,'close':v} for d,v in long.items()],'years':5},
                           next(reversed(long)),'Yahoo Finance · chart/AAAA3.SA')}
        with patch.object(signals.history_cache.extra_sources,'yahoo',return_value=result), \
             patch.object(signals,'pretrained',side_effect=AssertionError('No model download')):
            self.assertEqual(signals.prepare_histories(app,{'history':'signals'}),[])
            signals.analyze(app,{'pretrained':False})
        after=app.state()
        self.assertEqual(after['signals']['rows'][0]['history']['count'],1000)
        self.assertEqual(after['signals']['rows'][0]['horizons']['20']['bayesian']['status'],'ready')
        self.assertEqual(before['assets'][0]['position'],after['assets'][0]['position'])
        with app.connect() as c:
            saved=app.latest(c,aid)['history']
        with patch.object(signals.history_cache.extra_sources,'yahoo',side_effect=ValueError('Source failed')):
            with self.assertRaises(ValueError):signals.history_cache.fetch(app,{'asset_id':aid,'years':5,'force':True})
        with app.connect() as c:self.assertEqual(saved,app.latest(c,aid)['history'])


if __name__=='__main__':unittest.main()
