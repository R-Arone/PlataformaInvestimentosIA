"""Known coefficients, misleading level trends, monthly alignment and issuer isolation."""
import copy
import json
import math
import random
import unittest
from datetime import date
from unittest.mock import patch

import test_app as baseline
from aporte_brasil.company import factor_analysis as model
from aporte_brasil.company import company_research

app=baseline.app


def periods(n=60):
    return [f'{(2021*12+9+i)//12:04d}-{(2021*12+9+i)%12+1:02d}' for i in range(n)]


def monthly_series(changes,start=100,rate=False):
    values=[];value=start
    for i,month in enumerate(periods(len(changes)+1)):
        if i:value=value+changes[i-1] if rate else value*math.exp(changes[i-1]/100)
        values.append(dict(month=month,date=model.month_end(month).isoformat(),value=value))
    return dict(points=values,source_url='https://example.org/series')


def fixture(symbol='ABCD3.SA',mk='BR',direction=1,n=59):
    rng=random.Random(18);x=[rng.uniform(-3,3) for _ in range(n)];m=[rng.uniform(-2,2) for _ in range(n)]
    y=[direction*1.2*a+.5*b+rng.gauss(0,.05) for a,b in zip(x,m)]
    key='usd' if mk=='BR' else 'dollar_index'
    return dict(symbol=symbol,market=mk,currency=model.MARKETS[mk]['currency'],asof='2026-10-10',
                prices=monthly_series(y),benchmark=monthly_series(m),factors={key:monthly_series(x)},warnings=[],source_url='https://example.org/prices')


class FactorAnalysisTests(unittest.TestCase):
    asset=baseline.AppTests.asset

    def setUp(self):
        self.clock=patch.object(app,'today',return_value=date(2026,10,10));self.clock.start()
        baseline.AppTests.setUp(self)

    def tearDown(self):
        baseline.AppTests.tearDown(self);self.clock.stop()

    def analysis(self,d,day=date(2026,10,10)):
        return model.analyze_series(model.changes(d['prices']['points']),model.changes(d['benchmark']['points']),d['factors'],d['market'],day)

    def test_known_positive_and_negative_slopes_and_equal_shock_units(self):
        for sign in (1,-1):
            row=next(r for r in self.analysis(fixture(direction=sign)) if r['key']=='usd')
            self.assertEqual(row['status'],'positive' if sign>0 else 'negative')
            self.assertEqual(row['n'],59)
            self.assertAlmostEqual(row['effect'],sign*1.2*100*math.log(1.1),delta=.06)
            self.assertTrue(all(b*sign>0 for b in row['halves']))
            self.assertNotIn('probability',row)

    def test_general_bull_market_is_removed_in_controlled_regression(self):
        rng=random.Random(7);m=[rng.gauss(0,1) for _ in range(59)]
        x=[v+rng.gauss(0,.6) for v in m]
        d=fixture();d['prices']=monthly_series([2*v for v in m]);d['benchmark']=monthly_series(m);d['factors']['usd']=monthly_series(x)
        r=next(r for r in self.analysis(d) if r['key']=='usd')
        self.assertGreater(r['correlation'],.7)
        self.assertAlmostEqual(r['beta'],0,places=9)
        self.assertEqual(r['status'],'inconclusive')

    def test_interest_is_difference_in_percentage_points_including_zero(self):
        rng=random.Random(11);x=[rng.uniform(-.2,.2) for _ in range(59)];m=[rng.uniform(-2,2) for _ in x]
        d=fixture();d['factors']={'rates':monthly_series(x,10,True)};d['prices']=monthly_series([3*a+.2*b for a,b in zip(x,m)]);d['benchmark']=monthly_series(m)
        r=next(r for r in self.analysis(d) if r['key']=='rates')
        self.assertAlmostEqual(r['effect'],3,places=9)
        self.assertEqual(r['status'],'positive')
        zero=fixture(mk='US',symbol='TEST');zero['factors']={'us_rates':dict(points=[dict(month='2026-09',date='2026-09-30',value=0)],source_url='https://example.org/rates')}
        self.assertEqual(model.validate_snapshot(app,zero)['factors']['us_rates']['points'][0]['value'],0)

    def test_missing_months_are_not_carried_or_multi_month_returns(self):
        rows=monthly_series([1]*5)['points'];missing=rows[:2]+rows[3:]
        c=model.changes(missing)
        self.assertNotIn(rows[3]['month'],c)
        self.assertEqual(len(c),3)

    def test_open_month_partial_first_month_and_suspended_prices_excluded(self):
        points={'2026-06-12':100,'2026-06-30':101,'2026-07-01':102,'2026-07-31':103,'2026-08-03':104,'2026-08-10':105,'2026-09-01':106,'2026-09-30':107,'2026-10-01':108}
        self.assertEqual([r['month'] for r in model.monthly(points,date(2026,10,10))],['2026-07','2026-09'])
        self.assertEqual(len(model.monthly({'2026-09-01':100},date(2026,10,10),'monthly')),1)

    def test_insufficient_constant_and_collinear_series_do_not_receive_badges(self):
        for d in (fixture(n=20),fixture()):
            if len(d['prices']['points'])>30:d['benchmark']=copy.deepcopy(d['factors']['usd'])
            r=next(r for r in self.analysis(d) if r['key']=='usd')
            self.assertNotIn(r['status'],('positive','negative'))
        d=fixture();d['factors']['usd']=monthly_series([0]*59)
        self.assertIsNone(next(r for r in self.analysis(d) if r['key']=='usd')['beta'])

    def test_regime_change_and_old_data_do_not_receive_badges(self):
        d=fixture();rng=random.Random(11);x=[rng.gauss(0,1) for _ in range(59)];m=[rng.gauss(0,1) for _ in x]
        d['factors']['usd']=monthly_series(x);d['benchmark']=monthly_series(m)
        d['prices']=monthly_series([(-1 if i<29 else 4)*a+.2*b for i,(a,b) in enumerate(zip(x,m))])
        r=next(r for r in self.analysis(d) if r['key']=='usd');self.assertNotIn(r['status'],('positive','negative'))
        r=next(r for r in self.analysis(fixture(),date(2027,3,10)) if r['key']=='usd');self.assertEqual(r['status'],'stale')

    def test_hac_covariance_agrees_with_independent_numpy_reference(self):
        # Numerical regression oracle is optional; production is standard-library only.
        try:import numpy as np
        except ImportError:self.skipTest('NumPy opcional para conferir a covariância por outra implementação.')
        rng=random.Random(28);panel=[dict(month=t,x=rng.gauss(0,2),m=rng.gauss(0,1),y=rng.gauss(0,3)) for t in periods(60)]
        fitted=model.fit(panel);x=np.array([[r['x'],r['m']] for r in panel]);y=np.array([r['y'] for r in panel]);x=(x-x.mean(0))/x.std(0);y=(y-y.mean())/y.std()
        design=np.column_stack([np.ones(60),x]);bread=np.linalg.inv(design.T@design);beta=bread@design.T@y;score=design*(y-design@beta)[:,None];meat=score.T@score
        for lag in range(1,4):
            cross=score[lag:].T@score[:-lag];meat+=(1-lag/4)*(cross+cross.T)
        covariance=bread@meat@bread*60/57
        self.assertAlmostEqual(fitted['beta'],beta[1],places=12)
        self.assertAlmostEqual(fitted['standard_error'],math.sqrt(covariance[1,1]),places=12)

    def test_snapshot_strict_currency_nan_duplicates_and_future_validation(self):
        d=fixture();self.assertEqual(model.validate_snapshot(app,d),d)
        variants=[]
        for key,value in [('currency','USD'),('symbol','bad symbol'),('asof','2099-01-01')]:
            bad=copy.deepcopy(d);bad[key]=value;variants.append(bad)
        bad=copy.deepcopy(d);bad['prices']['points'][0]['value']=float('nan');variants.append(bad)
        bad=copy.deepcopy(d);bad['prices']['points'][0]['value']=1e300;variants.append(bad)
        bad=copy.deepcopy(d);bad['prices']['points'].append(bad['prices']['points'][0]);variants.append(bad)
        bad=copy.deepcopy(d);bad['factors']['usd']['points'][-1]['month']='2026-10';bad['factors']['usd']['points'][-1]['date']='2026-10-01';variants.append(bad)
        bad=copy.deepcopy(d);bad['seal']='positive';variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValueError):model.validate_snapshot(app,bad)

    def test_sector_has_fixed_composition_market_separation_and_single_issuer_rule(self):
        one=dict(id=1,ticker='ABCD3',asset_type='stock',sector='Mineração',company_research={},snapshots={model.KINDS[0]:{'data':fixture()}})
        two=dict(id=2,ticker='WXYZ3',asset_type='stock',sector='Mineração',company_research={},snapshots={model.KINDS[0]:{'data':fixture('WXYZ3.SA')}})
        pn=copy.deepcopy(one);pn.update(id=3,ticker='ABCD4');pn['snapshots'][model.KINDS[0]]['data']['symbol']='ABCD4.SA'
        usa=dict(id=4,ticker='TEST',asset_type='foreign',sector='Mineração',company_research={},snapshots={model.KINDS[0]:{'data':fixture('TEST','US')}})
        missing=dict(id=5,ticker='FALT3',asset_type='stock',sector='Mineração',company_research={},snapshots={})
        model.enrich(app,[one,two,pn,usa,missing])
        result=one['company_research']['factor_analysis'];self.assertEqual(result['members'],['ABCD3','WXYZ3']);self.assertEqual(result['excluded'],['FALT3']);self.assertEqual(result['group_size'],3)
        self.assertTrue(any(r['status']=='positive' for r in result['sector']))
        self.assertTrue(all(r['status']=='coverage' for r in usa['company_research']['factor_analysis']['sector']))

    def test_empty_app_state_is_local_and_fii_is_untouched(self):
        aid=self.asset()
        with patch.object(app,'request_json',side_effect=AssertionError('Unexpected network')):
            a=next(a for a in app.state()['assets'] if a['id']==aid)
        f=a['company_research']['factor_analysis'];self.assertTrue(f['supported']);self.assertTrue(all(r['status']=='insufficient' for r in f['company']))

    def test_price_collector_checks_symbol_currency_exchange_and_adjustment(self):
        dates=['2026-08-03','2026-08-31','2026-09-01','2026-09-30','2026-10-01']
        from datetime import datetime,timezone
        stamps=[datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp() for d in dates]
        result=dict(meta=dict(symbol='MSFT',currency='USD',instrumentType='EQUITY',exchangeName='NMS'),timestamp=stamps,
            indicators=dict(adjclose=[dict(adjclose=[100,101,102,103,104])]))
        def request(r):return patch.object(app,'request_json',return_value=dict(chart=dict(result=[r])))
        with request(result):self.assertEqual(len(model.fetch_prices(app,'MSFT','US')['points']),2)
        for key,value in [('symbol','OTHER'),('currency','BRL'),('exchangeName','UNKNOWN'),('instrumentType','ETF')]:
            bad=copy.deepcopy(result);bad['meta'][key]=value
            with request(bad),self.assertRaises(ValueError):model.fetch_prices(app,'MSFT','US')
        bad=copy.deepcopy(result);bad['indicators']=dict(quote=[dict(close=[100,101,102,103,104])])
        with request(bad),self.assertRaises(ValueError):model.fetch_prices(app,'MSFT','US')

    def test_factor_collector_accepts_csv_missing_points_and_bcb_comma_rates(self):
        rows=[dict(data='01/08/2026',valor='0,0'),dict(data='31/08/2026',valor='0,25'),dict(data='01/09/2026',valor='0,25'),dict(data='30/09/2026',valor='0,50')]
        with patch.object(app,'request_json',return_value=rows):
            r=model.fetch_factor(app,'rates',date(2026,8,1),date(2026,10,10));self.assertEqual([p['value'] for p in r['points']],[.25,.5])
        csv='observation_date,PIORECRUSDM\n2026-07-01,100\n2026-08-01,.\n2026-09-01,105\n2026-10-01,110\n'
        with patch.object(model.company_insights,'request_text',return_value=csv):
            r=model.fetch_factor(app,'iron',date(2026,7,1),date(2026,10,10));self.assertEqual(len(r['points']),2);self.assertEqual(model.changes(r['points']),{})

    def test_refresh_persists_and_partial_failure_preserves_old_sources(self):
        aid=self.asset();a=next(a for a in app.state()['assets'] if a['id']==aid);d=fixture(a['ticker']+'.SA')
        with patch.object(model,'fetch_factor',side_effect=lambda app,key,start,day:copy.deepcopy(d['factors']['usd'])),patch.object(model,'fetch_prices',side_effect=lambda app,symbol,mk,index=False:copy.deepcopy(d['benchmark'] if index else d['prices'])):
            result=company_research.action(app,'/api/issuer/factors',{'asset_id':aid});self.assertEqual(result['received'],[a['ticker']])
        with app.connect() as c:saved=app.latest(c,aid)[model.KINDS[0]]['data']
        with patch.object(model,'fetch_factor',side_effect=ValueError('Fonte indisponível')),patch.object(model,'fetch_prices',side_effect=ValueError('Fonte indisponível')):
            result=model.refresh(app,a);self.assertTrue(result['warnings'])
        with app.connect() as c:after=app.latest(c,aid)[model.KINDS[0]]['data']
        self.assertEqual(after['prices'],saved['prices']);self.assertEqual(after['factors'],saved['factors'])
        with self.assertRaises(ValueError):company_research.action(app,'/api/issuer/factors',{'asset_id':aid,'lookahead':True})

    def test_backup_roundtrip_validates_issuer_and_recomputes_badges(self):
        aid=self.asset();a=next(a for a in app.state()['assets'] if a['id']==aid)
        d=model.validate_snapshot(app,fixture(a['ticker']+'.SA'))
        with app.connect() as c:app.add_snapshot(c,aid,model.KINDS[0],d,'Fixture',d['asof'])
        with app.connect() as c:backup=app.export_data(c)
        self.assertTrue(any(s['kind']==model.KINDS[0] for s in backup['tables']['snapshots']))
        app.mutate('/api/import',backup)
        ticker=a['ticker'];a=next(item for item in app.state()['assets'] if item['ticker']==ticker)
        self.assertEqual(next(r for r in a['company_research']['factor_analysis']['company'] if r['key']=='usd')['status'],'positive')
        bad=copy.deepcopy(backup)
        for s in bad['tables']['snapshots']:
            if s['kind']==model.KINDS[0]:
                data=json.loads(s['data']);data['symbol']='OTHER3.SA';s['data']=json.dumps(data)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)
        wrong_market=copy.deepcopy(backup)
        for s in wrong_market['tables']['snapshots']:
            if s['kind']==model.KINDS[0]:
                data=json.loads(s['data']);data.update(market='US',currency='USD',factors={'dollar_index':data['factors']['usd']});s['data']=json.dumps(data)
        with self.assertRaises(ValueError):app.mutate('/api/import',wrong_market)
