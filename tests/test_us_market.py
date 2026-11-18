"""US currency identity, chronology, model isolation and reviewable candidates."""
import copy
from datetime import date, datetime, timezone
import json
import unittest
from unittest.mock import patch

from aporte_brasil.market import us_market as us
from aporte_brasil.market import market_signals as signals
from aporte_brasil.portfolio import portfolio_coupling as coupling
from aporte_brasil.core import history_cache
import test_app as baseline
from test_signals import series
app = baseline.app


def chart(ticker='AAPL', currency='USD', exchange='NMS', instrument='EQUITY'):
    points = series(250, end=app.today())
    stamps = [int(datetime.fromisoformat(d).replace(hour=14,tzinfo=timezone.utc).timestamp()) for d in points]
    return {'chart': {'result': [{'meta': {'symbol': ticker, 'currency': currency, 'exchangeName': exchange,
        'instrumentType': instrument, 'regularMarketPrice': 100, 'regularMarketTime': stamps[-1], 'longName': ticker+' Incorporated'},
        'timestamp': stamps, 'indicators': {'adjclose': [{'adjclose': list(points.values())}], 'quote': [{'close': [900]*len(stamps)}]}}]}}


class ParsingTests(unittest.TestCase):
    def test_rejects_wrong_currency_exchange_symbol_or_instrument(self):
        for raw in (chart(currency='EUR'),chart(exchange='LSE'),chart(ticker='WRONG'),chart(instrument='ETF')):
            with self.assertRaises(ValueError):us.fetch('AAPL',lambda _:raw,app.today)

    def test_normalizes_share_class_and_uses_adjusted_prices_only(self):
        r=us.fetch('BRK.B',lambda _:chart('BRK-B'),app.today)
        self.assertEqual(r['us_quote'][0]['symbol'],'BRK-B')
        self.assertTrue(all(p['close']!=900 for p in r['us_history'][0]['prices']))
        for invalid in ('AAPL/secret','http://example.org','AAPL34','BTC-USD'):
            with self.assertRaises(ValueError):us.symbol(invalid)

    def test_no_unadjusted_fallback(self):
        raw=chart();raw['chart']['result'][0]['indicators'].pop('adjclose')
        self.assertNotIn('us_history',us.fetch('AAPL',lambda _:raw,app.today))

    def test_new_york_cutoff_handles_daylight_saving_and_winter(self):
        for day,before,after in [(date(2026,10,6),'2026-10-06T20:15:00+00:00','2026-10-06T20:35:00+00:00'),
                                 (date(2026,1,6),'2026-01-06T21:15:00+00:00','2026-01-06T21:35:00+00:00')]:
            a={'snapshots':{'history':{'data':{'prices':[{'date':day.isoformat(),'close':100}]}}}}
            self.assertEqual(coupling.completed_prices(a,day,before,market='US'),{})
            self.assertEqual(len(coupling.completed_prices(a,day,after,market='US')),1)

    def test_us_peers_exclude_self_duplicate_issuer_and_brazil(self):
        def a(ticker,typ='foreign',issuer=None):
            return {'ticker':ticker,'sector':'Tecnologia','asset_type':typ,
                    'snapshots':{'us_quote':{'data':{'issuer':issuer or ticker}}}}
        main=a('GOOG',issuer='Alphabet');others=[main,a('GOOGL',issuer='Alphabet'),a('AAPL'),a('MSFT'),a('ABCD3','stock')]
        points={v['ticker']:{'2026-10-05':1} for v in others}
        self.assertEqual(len(signals.sector_peers(main,others,points)),2)

    def test_us_context_never_uses_selic_or_brazilian_sentiment(self):
        a={'asset_type':'foreign','us':{'sentiment':{'score':.7,'tone':'positive','stale':False}}}
        r=signals.fresh_context(a,{'macro':{'selic':{'value':99}}},'2026-10-05',date(2026,10,6))
        self.assertEqual(r,{'sentiment':.7})


class IntegrationTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    trade=baseline.AppTests.trade

    def foreign(self,ticker='AAPL'):
        return app.mutate('/api/assets',{'ticker':ticker,'asset_type':'foreign','name':ticker,'sector':'Tecnologia','financial':False})['id']

    def prepare(self):
        aid=self.foreign()
        with app.connect() as c:c.execute('INSERT INTO macro VALUES (?,?,?,?,?)',('usd',5,self.day,'BCB sintético',app.now()))
        with patch.object(app,'request_json',return_value=chart()):us.refresh_asset(app,{'id':aid,'ticker':'AAPL'})
        return aid

    def test_native_usd_quote_converts_value_but_never_rewrites_ledger(self):
        aid=self.prepare();self.trade(aid,qty=2,price=400)
        state=app.state();a=state['assets'][0]
        self.assertTrue(a['us']['verified'])
        self.assertEqual(a['us']['quote']['data']['price'],100)
        self.assertEqual(a['metrics']['price'],500)
        self.assertEqual(a['position']['average'],400)
        self.assertEqual(a['value'],1000)
        self.assertNotIn('history',a['snapshots'])
        self.assertEqual(a['snapshots']['us_history']['data']['currency'],'USD')
        self.assertEqual(state['coupling']['coverage'],0)

    def test_no_recent_fx_keeps_brl_value_and_saves_usd_separately(self):
        aid=self.foreign()
        with app.connect() as c:app.add_snapshot(c,aid,'quote',{'price':321},'Manual',self.day)
        with patch.object(app,'request_json',return_value=chart()):warnings=us.refresh_asset(app,{'id':aid,'ticker':'AAPL'})
        self.assertTrue(warnings)
        self.assertEqual(app.state()['assets'][0]['metrics']['price'],321)
        self.assertEqual(app.state()['assets'][0]['us']['quote']['data']['price'],100)

    def test_us_models_use_native_usd_and_keep_holdings_unchanged(self):
        aid=self.prepare();self.trade(aid)
        before=app.state()['assets'][0]['position']
        signals.analyze(app,{'ticker':'AAPL','pretrained':False,'market':'US'})
        state=app.state();r=state['signals']['rows'][0]
        self.assertEqual(r['currency'],'USD')
        self.assertEqual(r['horizons']['5']['incremental']['status'],'ready')
        self.assertEqual(state['assets'][0]['position'],before)
        self.assertEqual(state['us_market']['candidates']['5'][0]['status'],'unknown')

    def test_candidate_requires_two_current_models_and_has_fundamental_pending(self):
        self.prepare()
        forecasts={str(h):{'status':'ready','direction':'favorable','median_return':2.,'low_return':1.,'high_return':3.} for h in signals.HORIZONS}
        with patch.object(signals,'pretrained',return_value=forecasts):signals.analyze(app,{'pretrained':True,'market':'US'})
        with app.connect() as c:
            results=app.read_cache(c,'market_signal_results',{})
            for h in results['AAPL']['horizons'].values():h['incremental']['direction']='favorable'
            app.write_cache(c,'market_signal_results',results)
        state=app.state();r=state['us_market']['candidates']['5'][0]
        self.assertEqual(r['status'],'candidate');self.assertTrue(r['pending'])
        a=copy.deepcopy(state['assets'][0]);a['us']['sentiment']={'tone':'negative','stale':False}
        self.assertEqual(us.rank([a],state['signals'],5)[0]['status'],'mixed')
        a['us']['quote_stale']=True
        self.assertEqual(us.rank([a],state['signals'],5)[0]['status'],'unknown')

    def test_backup_preserves_native_currency_and_clears_us_news(self):
        self.prepare()
        with app.connect() as c:
            app.write_cache(c,'us_news',{'AAPL':{'sentiment':{'score':.8}}})
            backup=app.export_data(c)
        app.mutate('/api/import',backup)
        a=app.state()['assets'][0]
        self.assertEqual(a['snapshots']['us_history']['data']['currency'],'USD')
        self.assertEqual(a['us']['sentiment'],{})
        bad=copy.deepcopy(backup)
        for s in bad['tables']['snapshots']:
            if s['kind']=='us_history':
                payload=json.loads(s['data']);payload['currency']='BRL';s['data']=json.dumps(payload)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)

    def test_five_year_history_does_not_shrink_on_subsequent_one_year_request(self):
        aid=self.prepare()
        with patch.object(app,'request_json',return_value=chart()):history_cache.fetch(app,{'asset_id':aid,'years':5,'force':True})
        r=history_cache.fetch(app,{'asset_id':aid,'years':1})
        self.assertTrue(r['used_cache']);self.assertEqual(r['years'],5)


if __name__=='__main__':unittest.main()
