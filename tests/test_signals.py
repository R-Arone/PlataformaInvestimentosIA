"""Chronology, common-panel risk, optional inference and portfolio isolation."""
import copy
from datetime import date, timedelta
import math
import unittest
from unittest.mock import patch

import market_signals as signals
import portfolio_coupling as coupling
import market_outlook
import market_brief
import sector_analysis
import test_app as baseline
app = baseline.app


def series(n=300, direction=1, end=None):
    end = end or date(2026, 10, 5)
    days = []
    while len(days) < n:
        if end.weekday() < 5:
            days.append(end.isoformat())
        end -= timedelta(days=1)
    level, rows = 100., {}
    for i, day in enumerate(reversed(days)):
        level *= math.exp(direction*(.008*math.sin(i*.43)+.002*math.cos(i*.71)))
        rows[day] = level
    return rows


def asset(ticker, points, value=100, day='2026-10-06'):
    return {'ticker': ticker, 'asset_type': 'stock', 'value': value, 'value_at_cost': False,
            'position': {'quantity': 1}, 'sector': 'Teste', 'sector_analysis': {'profile': 'general'},
            'snapshots': {'quote': {'asof': day}, 'history': {'source': 'Sintético', 'data': {
                'prices': [{'date': d, 'close': v} for d, v in points.items()]}}}}


class MathTests(unittest.TestCase):
    day = date(2026, 10, 6)
    stamp = '2026-10-06T22:00:00+00:00'

    def test_correlated_positions_give_no_diversification_and_weights_matter(self):
        points = series()
        r = coupling.analyze([asset('AAAA3', points, 300), asset('BBBB3', points, 100)], [], self.day, self.stamp)
        self.assertEqual(r['status'], 'ready')
        self.assertAlmostEqual(r['mean_correlation'], 1)
        self.assertAlmostEqual(r['diversification_ratio'], 1)
        self.assertAlmostEqual(r['risk_reduction'], 0)
        self.assertAlmostEqual(r['effective_holdings'], 1.6)
        self.assertAlmostEqual(r['assets'][0]['risk_contribution'], 75)

    def test_negative_correlation_can_offset_risk_without_inventing_infinite_ratio(self):
        r = coupling.analyze([asset('AAAA3', series()), asset('BBBB3', series(direction=-1))], [], self.day, self.stamp)
        self.assertAlmostEqual(r['mean_correlation'], -1)
        self.assertAlmostEqual(r['risk_reduction'], 100)
        self.assertIsNone(r['diversification_ratio'])

    def test_coverage_excludes_cost_weights_watchlist_and_nonpriced_products(self):
        a, b = asset('AAAA3', series()), asset('BBBB3', series(), 200)
        missing = asset('MISS3', {}, 100);missing['value_at_cost'] = True
        watched = asset('WATCH3', series(), 0);watched['position']['quantity'] = 0
        r = coupling.analyze([a,b,missing,watched], [{'balance':600}], self.day, self.stamp)
        self.assertEqual(r['status'], 'ready')
        self.assertEqual(len(r['excluded']), 1)
        self.assertAlmostEqual(r['coverage'], 75)
        self.assertAlmostEqual(r['total_coverage'], 30)

    def test_common_panel_rejects_sparse_overlap_and_constant_prices(self):
        a = asset('AAAA3', series())
        b = asset('BBBB3', series(end=date(2025, 1, 1)))
        self.assertEqual(coupling.analyze([a,b], [], self.day, self.stamp)['status'], 'unknown')
        constant = asset('CCCC3', {d: 100 for d in series()})
        self.assertEqual(coupling.analyze([a,constant], [], self.day, self.stamp)['status'], 'unknown')

    def test_unfinished_candle_is_excluded_until_brazilian_cutoff(self):
        a = asset('AAAA3', {'2026-10-05': 10, '2026-10-06': 20, '2026-10-07': 30})
        self.assertEqual(coupling.completed_prices(a,self.day,'2026-10-06T20:00:00+00:00'), {'2026-10-05':10})
        self.assertEqual(len(coupling.completed_prices(a,self.day,self.stamp)), 2)

    def test_incremental_only_trains_matured_targets_and_is_idempotent(self):
        points = series(230)
        for h in signals.HORIZONS:
            model, report = signals.update_model(points, [], h)
            self.assertEqual(model['trained'], len(points)-63-h)
            self.assertEqual(len(model['pending']), h)
            again, same = signals.update_model(points, [], h, model)
            self.assertEqual(model, again)
            self.assertEqual(report['score'], same['score'])

    def test_appended_history_matches_a_single_chronological_pass(self):
        points = series(280)
        prefix = dict(list(points.items())[:215])
        initial, _ = signals.update_model(prefix, [], 5)
        extended, _ = signals.update_model(points, [], 5, initial)
        full, _ = signals.update_model(points, [], 5)
        self.assertEqual(extended['weights'], full['weights'])
        self.assertEqual(extended['trained'], full['trained'])
        self.assertEqual(extended['pending'][-1]['probabilities'], full['pending'][-1]['probabilities'])

    def test_news_only_applies_to_saved_current_origin_and_corrections_rebuild(self):
        points = series(200)
        model, _ = signals.update_model(points, [], 20, context={'sentiment':.8,'rates':-1})
        self.assertFalse(any(p['features'][9] for p in model['pending'][:-1]))
        self.assertEqual(model['pending'][-1]['features'][9],1)
        corrected = dict(points);corrected[next(iter(corrected))] *= 1.02
        rebuilt, result = signals.update_model(corrected, [], 20, model)
        self.assertTrue(result['reset'])
        self.assertEqual(rebuilt['trained'], model['trained'])

    def test_delayed_quotes_never_train_future_context_or_count_past_target_as_live(self):
        points = series(200)
        prefix = dict(list(points.items())[:-3])
        initial, _ = signals.update_model(prefix, [], 1, context={
            'sentiment': .8, '_generated_at': '2026-10-06T22:00:00+00:00'})
        updated, result = signals.update_model(points, [], 1, initial)
        full, _ = signals.update_model(points, [], 1)
        self.assertEqual(updated['trained'], full['trained'])
        self.assertEqual(updated['weights'], full['weights'])
        self.assertEqual(result['evaluations']['live']['count'], 0)

    def test_same_close_new_news_refreshes_only_the_pending_forecast(self):
        points=series(230)
        model,_=signals.update_model(points,[],5)
        updated,report=signals.update_model(points,[],5,model,{'sentiment':.8,'_generated_at':'2026-10-06T12:00:00+00:00'})
        self.assertEqual(updated['trained'],model['trained'])
        self.assertEqual(updated['weights'],model['weights'])
        self.assertEqual(updated['pending'][:-1],model['pending'][:-1])
        self.assertTrue(report['context_available']['sentiment'])
        again,_=signals.update_model(points,[],5,updated,{'sentiment':.8,'_generated_at':'2026-10-06T13:00:00+00:00'})
        self.assertEqual(again,updated)


class IntegrationTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    trade = baseline.AppTests.trade

    def prepare(self,ticker='AAAA3'):
        aid = self.asset(ticker)
        points = series(end=app.today()-timedelta(days=1))
        with app.connect() as c:
            app.add_snapshot(c,aid,'history',{'prices':[{'date':d,'close':v} for d,v in points.items()]},'Teste sintético',next(reversed(points)))
            app.add_snapshot(c,aid,'quote',{'price':100},'Teste sintético',self.day)
        return aid

    def test_inference_failure_keeps_incremental_and_does_not_change_holdings(self):
        aid=self.prepare();self.trade(aid)
        before=app.state()['assets']
        with patch.object(signals,'pretrained',side_effect=ValueError('Modelo indisponível')):
            signals.analyze(app, {'ticker':'AAAA3','pretrained':True})
        state=app.state()
        self.assertEqual(before,state['assets'])
        r=state['signals']['rows'][0]
        self.assertIn('Modelo indisponível',r['pretrained_error'])
        self.assertEqual(r['horizons']['5']['incremental']['status'],'ready')
        self.assertEqual(r['horizons']['5']['agreement'],'unknown')
        with app.connect() as c:
            model=app.read_cache(c,'market_signal_models',{})
        signals.analyze(app, {'ticker':'AAAA3','pretrained':False})
        with app.connect() as c:self.assertEqual(model,app.read_cache(c,'market_signal_models',{}))

    def test_pretrained_cache_reuse_and_peer_changes_mark_the_result_stale(self):
        self.prepare('AAAA3');self.prepare('BBBB3');self.prepare('CCCC3')
        forecast={str(h):{'status':'ready','direction':'favorable','median_return':2.,'low_return':.1,'high_return':4.,'sector_peers':2} for h in signals.HORIZONS}
        with patch.object(signals,'pretrained',return_value=forecast) as call:
            signals.analyze(app, {'ticker':'AAAA3','pretrained':True})
            signals.analyze(app, {'ticker':'AAAA3','pretrained':True})
            self.assertEqual(call.call_count,1)
        self.assertFalse(app.state()['signals']['rows'][0]['stale'])
        with app.connect() as c:c.execute("UPDATE assets SET sector='Outro setor' WHERE ticker='BBBB3'")
        self.assertTrue(app.state()['signals']['rows'][0]['stale'])

    def test_restore_clears_derived_models_from_a_replaced_portfolio(self):
        self.prepare()
        signals.analyze(app,{'ticker':'AAAA3','pretrained':False})
        with app.connect() as c:data=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(data))
        with app.connect() as c:self.assertEqual(app.read_cache(c,'market_signal_models',{}),{})

    def test_metals_profile_news_channel_and_legacy_scenario(self):
        self.assertEqual(sector_analysis.profile({'sector':'Mineração','name':'Teste','asset_type':'stock'}),'metals')
        self.assertIn('metals',market_brief.TOPICS)
        old={**market_outlook.DEFAULT,'asof':self.day,'source':'Hipótese de teste'};old.pop('metals')
        normalized=market_outlook.validate_scenario(app,old)
        self.assertEqual(normalized['metals'],'unknown')
        self.assertEqual(market_outlook.channel('metals','metals','up')[0],'mixed')
        headline={'title':'Ouro sobe e cobre cai','published_at':self.day+'T12:00:00+00:00','publisher':'Teste','url':'https://example.org/'}
        self.assertEqual(market_outlook.headline_hints({'headlines':[headline]},app.today(),'metals'),[])


if __name__=='__main__':unittest.main()
