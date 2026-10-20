"""Crisis calculations and AI references use isolated synthetic data only."""
import copy
from datetime import date, timedelta
import json
import random
import unittest
from unittest.mock import patch
import company_evidence as evidence
import factor_analysis as factors
import company_research
import market_ai
import test_app as baseline
from test_factor_analysis import fixture, monthly_series
import test_ai

app=baseline.app


def points(start='2019-01',end='2023-12',values=None):
    out=[];values=values or {}
    for t in range(evidence.ordinal(start),evidence.ordinal(end)+1):
        m=f'{t//12:04d}-{t%12+1:02d}'
        out.append(dict(month=m,date=m+'-28',value=values.get(m,100)))
    return out


class CrisisTests(unittest.TestCase):
    def test_recovery_first_and_three_month_confirmation_differ(self):
        rows=points(values={'2020-03':50,'2020-04':80,'2020-05':100,'2020-06':110,'2020-07':90,'2020-08':100,'2020-09':110,'2020-10':112})
        r=evidence.episode(rows,'2020-01','2020-02','2020-06')
        self.assertEqual(r['drawdown'],-50)
        self.assertEqual(r['trough'],'2020-03')
        self.assertEqual(r['months_to_first'],2)
        self.assertEqual(r['months_to_confirm'],7)

    def test_missing_shock_month_and_ipo_are_not_resilience(self):
        for rows in (points('2021-01'),[p for p in points() if p['month']!='2020-03']):
            self.assertEqual(evidence.episode(rows,'2020-01','2020-02','2020-06')['status'],'missing')

    def test_unrecovered_is_censored_not_zero_months(self):
        rows=points(end='2021-12',values={p['month']:50 for p in points('2020-03','2021-12')})
        r=evidence.episode(rows,'2020-01','2020-02','2020-06')
        self.assertEqual(r['status'],'pending');self.assertIsNone(r['months_to_first'])
        self.assertEqual(r['observed_months'],21);self.assertEqual(r['through'],'2021-12')

    def test_missing_month_breaks_confirmation_and_peak_can_rise(self):
        rows=points(end='2020-06',values={'2020-02':120,'2020-03':60,'2020-04':120,'2020-05':120,'2020-06':120})
        rows=[p for p in rows if p['month']!='2020-05']
        # Incomplete episode has no drawdown claim.
        self.assertEqual(evidence.episode(rows,'2020-01','2020-02','2020-06')['status'],'missing')
        rows=points(end='2020-10',values={'2020-02':120,'2020-03':60,'2020-04':70,'2020-05':70,'2020-06':70,'2020-07':120,'2020-08':120,'2020-09':120,'2020-10':120})
        r=evidence.episode([p for p in rows if p['month']!='2020-08'],'2020-01','2020-02','2020-06')
        self.assertEqual(r['peak'],'2020-02');self.assertEqual(r['drawdown'],-50)
        self.assertEqual(r['months_to_first'],4);self.assertIsNone(r['months_to_confirm'])

    def test_no_drop_and_separate_market_baseline(self):
        d=dict(prices=dict(points=points()),benchmark=dict(points=points(values={'2020-03':40})))
        r=evidence.resilience(d)['episodes'][1]
        self.assertEqual(r['company']['status'],'no_drop')
        self.assertEqual(r['benchmark']['drawdown'],-60)


class EvidenceIntegrationTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    complete=baseline.AppTests.complete

    def test_long_snapshot_compatibility_limits_and_bad_years(self):
        d=fixture();self.assertNotIn('years',factors.validate_snapshot(app,d))
        d['years']=20;d['prices']['points']=points('2006-10','2026-09')
        self.assertEqual(len(factors.validate_snapshot(app,d)['prices']['points']),240)
        for value in (True,15,'20',0):
            bad=copy.deepcopy(d);bad['years']=value
            with self.assertRaises(ValueError):factors.validate_snapshot(app,bad)
        bad=copy.deepcopy(d);bad['years']=5
        with self.assertRaises(ValueError):factors.validate_snapshot(app,bad)

    def test_twenty_year_daily_sources_are_chunked_and_not_truncated(self):
        calls=[];day=app.today();start=day-timedelta(days=20*366)
        def read(url,**kwargs):
            from urllib.parse import parse_qs,urlsplit
            from datetime import datetime
            q=parse_qs(urlsplit(url).query);left=datetime.strptime(q['dataInicial'][0],'%d/%m/%Y').date();right=datetime.strptime(q['dataFinal'][0],'%d/%m/%Y').date()
            self.assertLess((right-left).days,10*365);calls.append((left,right))
            return [dict(data=(left+timedelta(days=i)).strftime('%d/%m/%Y'),valor='12') for i in range((right-left).days+1)]
        with patch.object(app,'request_json',side_effect=read):r=factors.fetch_factor(app,'rates',start,day)
        self.assertEqual(len(calls),4);self.assertGreater(len(r['points']),235)
        self.assertTrue(all(a[1]+timedelta(days=1)==b[0] for a,b in zip(calls,calls[1:])))

    def test_long_prices_use_explicit_periods_and_native_currency(self):
        stamps=[];values=[]
        from datetime import datetime,timezone
        for p in points('2006-10','2026-09'):
            for d in (p['month']+'-02',p['date']):
                stamps.append(int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp()));values.append(100)
        response={'chart':{'result':[dict(meta=dict(symbol='TEST',currency='USD',instrumentType='EQUITY',exchangeName='NMS'),timestamp=stamps,indicators={'adjclose':[{'adjclose':values}]})]}}
        with patch.object(app,'request_json',return_value=response) as request:
            r=factors.fetch_prices(app,'TEST','US',years=20)
        self.assertGreater(len(r['points']),230);self.assertIn('period1=',request.call_args.args[0]);self.assertNotIn('range=5y',request.call_args.args[0])

    def test_opposite_confirmed_recent_sign_suspends_long_badge(self):
        aid=self.asset();a=app.state()['assets'][0]
        d=fixture();d['years']=20;a['snapshots'][factors.KINDS[0]]={'data':d}
        with patch.object(factors,'analyze_series',side_effect=[[],[dict(key='usd',status='positive')],[dict(key='usd',status='negative')]]):
            factors.enrich(app,[a])
        r=a['company_research']['factor_analysis']['company'][0]
        self.assertEqual(r['status'],'unstable');self.assertEqual(r['recent_status'],'negative')

    def test_decision_requires_more_than_correlation_and_stale_data_blocks(self):
        aid=self.asset();a=app.state()['assets'][0];c=evidence.context(a,app.today())
        a=dict(company_reference=c,direction='favorable',price_stale=False)
        c.update(quality='within',valuation='below',stress='within_scenario')
        self.assertEqual(evidence.decision(a)['action'],'complete')
        c['valuation_verified']=True
        self.assertEqual(evidence.decision(a)['action'],'buy')
        for change in (dict(price_stale=True),dict(direction='mixed')):
            self.assertNotEqual(evidence.decision({**a,**change})['action'],'buy')
        c['stress']='attention';self.assertNotEqual(evidence.decision(a)['action'],'buy')
        c['valuation']='above';a['direction']='unfavorable';self.assertEqual(evidence.decision(a)['action'],'reduce')

    def test_ai_and_chatgpt_receive_company_references_without_portfolio_values(self):
        aid=self.asset(sector='Varejo');self.complete(aid)
        analysis=test_ai.AITests.analysis(self)
        captured=[]
        def generate(cfg,system,data,schema):captured.append(copy.deepcopy(data));return copy.deepcopy(analysis),'Modelo sintético'
        with patch.object(market_ai,'generate',side_effect=generate):
            market_ai.simulate(app,market_ai.validate_scenario(app,dict(question='Juros menores favorecem o consumo?',engine='llm')))
            market_ai.translate_paste(app,market_ai.validate_paste(app,dict(text='Hipótese: juros menores podem apoiar o crédito e o consumo, mas recessão e inadimplência podem inverter a tese para o varejo.')))
        self.assertIn('company_reference',captured[0]['assets'][0]);self.assertIn('company_reference',captured[1]['asset_references'][0])
        for data in captured:
            serialized=json.dumps(data)
            for key in ('"quantity"','"average_price"','"position"','"invested"'):self.assertNotIn(key,serialized)
        with app.connect() as c:r=app.read_cache(c,'ai_scenarios',[])
        market_ai.validate_saved(app,r,{a['ticker'] for a in app.state()['assets']})
        bad=copy.deepcopy(r);bad[0]['assets'][0]['decision_support']['action']='buy'
        with self.assertRaises(ValueError):market_ai.validate_saved(app,bad,{a['ticker'] for a in app.state()['assets']})
        bad=copy.deepcopy(r);bad[0]['assets'][0]['company_reference']['valuation_pvp']=float('nan')
        with self.assertRaises(ValueError):market_ai.validate_saved(app,bad,{a['ticker'] for a in app.state()['assets']})

    def test_native_quote_controls_decision_for_stocks(self):
        aid=self.asset();c=evidence.context(app.state()['assets'][0],app.today())
        c.update(quality='within',valuation='below',valuation_verified=True,stress='within_scenario')
        a=dict(company_reference=c,direction='favorable',price_stale=True,instrument=dict(native_price=20,native_asof=app.today().isoformat()))
        self.assertEqual(evidence.decision(a)['action'],'buy')
        a['price_stale']=False;a['instrument']['native_asof']=(app.today()-timedelta(days=10)).isoformat()
        self.assertNotEqual(evidence.decision(a)['action'],'buy')


if __name__=='__main__':unittest.main()
