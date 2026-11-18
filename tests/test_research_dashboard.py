"""Synthetic lag alignment, bulk isolation and source-grounded sector research."""
import copy
import random
import unittest
from datetime import date
from unittest.mock import patch

from aporte_brasil.company import company_batch
from aporte_brasil.company import company_research
from aporte_brasil.portfolio import contrarian
from aporte_brasil.company import factor_analysis as factors
from aporte_brasil.ai import market_ai
from aporte_brasil.market import market_brief
from aporte_brasil.market import market_research as research
import test_app as baseline
from test_factor_analysis import monthly_series

app=baseline.app


class LagTests(unittest.TestCase):
    def fixture(self):
        rng=random.Random(280);x=[rng.uniform(-.4,.4) for _ in range(120)];m=[rng.gauss(0,1) for _ in x];y=[]
        for i in range(len(x)):y.append(8*x[i-3]+.3*m[i]+(.2*y[-1] if y else 0)+rng.gauss(0,.03) if i>=3 else rng.gauss(0,1))
        return factors.changes(monthly_series(y)['points']),factors.changes(monthly_series(m)['points']),{'rates':monthly_series(x,10,True)}

    def test_known_three_month_delay_and_fixed_family(self):
        p,m,f=self.fixture();day=date(2031,11,2)
        result=factors.lagged_analysis(p,m,f,'BR',day,['rates'])
        rows=result['factors'][0]['models'];self.assertEqual([r['lag_months'] for r in rows],[0,1,3,6,12])
        lag=next(r for r in rows if r['lag_months']==3)
        self.assertEqual(lag['status'],'positive');self.assertGreater(lag['interval'][0],0)
        self.assertEqual(result['family_size'],len(factors.MARKETS['BR']['factors'])*5)
        other=factors.lagged_analysis(p,m,f,'BR',day,['rates','usd'])
        self.assertEqual(other['factors'][0],result['factors'][0])
        self.assertNotIn('best_lag',result)
        self.assertTrue(all(g['n']>=6 and g['median_return'] is not None for g in lag['groups'] if g['sufficient']))

    def test_missing_month_current_month_and_cache_mutation(self):
        p,m,f=self.fixture();day=date(2026,10,5)
        before=factors.lagged_analysis(p,m,f,'BR',day,['rates'])
        self.assertTrue(all(r['end']<'2026-10' for r in before['factors'][0]['models']))
        future=copy.deepcopy(p);future['2035-01']=900
        self.assertEqual(factors.lagged_analysis(future,m,f,'BR',day,['rates']),before)
        before['factors'][0]['models'][0]['status']='tampered'
        self.assertNotEqual(factors.lagged_analysis(p,m,f,'BR',day,['rates'])['factors'][0]['models'][0]['status'],'tampered')
        f['rates']['points']=[r for r in f['rates']['points'] if r['month']!='2024-04']
        after=factors.lagged_analysis(p,m,f,'BR',day,['rates'])
        original=factors.lagged_analysis(p,m,self.fixture()[2],'BR',day,['rates'])
        self.assertEqual(after['factors'][0]['models'][2]['n'],original['factors'][0]['models'][2]['n']-2)

    def test_short_and_stale_data_do_not_get_badges(self):
        p,m,f=self.fixture();p=dict(list(p.items())[:20])
        self.assertTrue(all(r['status']=='insufficient' for r in factors.lagged_analysis(p,m,f,'BR',date(2031,11,2),['rates'])['factors'][0]['models']))
        p,m,f=self.fixture()
        self.assertTrue(all(r['status']=='stale' for r in factors.lagged_analysis(p,m,f,'BR',date(2033,11,2),['rates'])['factors'][0]['models']))


class ResearchTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def test_sector_scope_and_strict_input(self):
        state={'assets':[{'sector_analysis':{'profile':'utility'},'exposure':{'profiles':['technology']}}]}
        self.assertIn('utility',research.profiles(state,'tracked'))
        self.assertEqual(research.profiles(state,'all'),list(research.sector_analysis.PROFILES))
        d=dict(scope='all',profile='general',use_ai=False,research=False)
        self.assertEqual(research.validate(app,d),d)
        for bad in (dict(scope=[]),dict(research=True),dict(extra=1),dict(use_ai=1)):
            with self.assertRaises(ValueError):research.validate(app,{**d,**bad})

    def test_reading_requires_received_sources(self):
        claim=dict(text='Hipótese condicionada aos dados.',source_ids=[1])
        reading=dict(summary=claim,opportunities=[claim],risks=[],watch=[])
        self.assertEqual(research.validate_reading(app,reading,[{'id':1}]),reading)
        bad=copy.deepcopy(reading);bad['summary']['source_ids']=[999]
        with self.assertRaises(ValueError):research.validate_reading(app,bad,[{'id':1}])

    def test_all_sectors_no_truncation_failure_isolation_and_private_query(self):
        self.asset('PRIV3');keys=list(research.sector_analysis.PROFILES)
        def fetch(profile,now):
            if profile==keys[1]:raise ValueError('Offline')
            return dict(profile=profile,retrieved_at=app.now(),headlines=[dict(title='Notícia sintética',url='https://example.org/news',published_at=app.now())],errors=[],sources=[])
        previous=dict(profile=keys[1],retrieved_at=app.now(),headlines=[],sources=[],errors=[],sentinel='preserve')
        with app.connect() as c:app.write_cache(c,'news_reports',{keys[1]:previous})
        with patch.object(contrarian,'refresh',return_value={'errors':[],'indicators':[]}),patch.object(market_brief,'fetch',side_effect=fetch),patch.object(market_ai,'research',return_value=([],[])) as web,patch.object(research,'ai_reading',side_effect=ValueError('Modelo indisponível')):
            research.run(app,dict(scope='all',profile='general',use_ai=True,research=True))
        self.assertEqual(web.call_args.args[1],research.QUESTION);self.assertNotIn('PRIV3',web.call_args.args[1])
        with app.connect() as c:r=app.read_cache(c,research.CACHE,{});feeds=app.read_cache(c,'news_reports',{})
        self.assertEqual(len(r['rows']),len(keys));self.assertFalse(r['running'])
        self.assertTrue(all(row['warnings'] for row in r['rows']));self.assertEqual(feeds[keys[1]],previous)

    def test_criteria_and_models_are_not_shared_with_etfs_or_fiis(self):
        one=app.mutate('/api/assets',{'ticker':'IVVB11'})['id']
        with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',('TEST11','FII sintético','fii','Logística',0,'Fixture',app.now()))
        two=app.mutate('/api/assets',{'ticker':'TEST11'})['id']
        args=dict(asset_ids=[one,two],years=10,refresh=True,use_ai=True,all_types=True)
        self.assertEqual(company_batch.validate(app,args),args)
        with self.assertRaises(ValueError):company_batch.validate(app,{k:v for k,v in args.items() if k!='all_types'})
        before=copy.deepcopy([a['position'] for a in app.state()['assets']])
        with patch.object(company_batch,'refresh_product',side_effect=[ValueError('Fonte indisponível'),{'received':['Informes do FII']}]) as refresh,patch.object(company_research,'analyze') as ai,patch.object(company_research,'action') as companies:
            company_batch.run(app,args)
        self.assertEqual(refresh.call_count,2);ai.assert_not_called();companies.assert_not_called()
        self.assertEqual([a['position'] for a in app.state()['assets']],before)
        with app.connect() as c:r=app.read_cache(c,'issuer_batch',{})
        self.assertEqual(len(r['rows']),2);self.assertTrue(all(row['review']=='na' for row in r['rows']))

    def test_macro_optional_refresh_preserves_previous_timestamp_on_failure(self):
        d=date(2026,10,10);series=dict(points=[dict(month='2026-08',date='2026-08-31',value=10),dict(month='2026-09',date='2026-09-30',value=11)],latest=dict(date='2026-09-30',value=11,previous_date='2026-08-31',previous_value=10),source_url='https://example.org/indicator')
        with patch.object(app,'today',return_value=d),patch.object(contrarian,'index_snapshot',side_effect=ValueError('Offline')),patch.object(contrarian,'fx_snapshot',side_effect=ValueError('Offline')),patch.object(factors,'fetch_factor',return_value=series) as macro:
            result=contrarian.refresh(app,{'indicators':True})
        self.assertEqual(macro.call_count,len(contrarian.INDICATORS));self.assertEqual(len(result['indicators']),8)
        with patch.object(app,'today',return_value=d),patch.object(contrarian,'index_snapshot',side_effect=ValueError('Offline')),patch.object(contrarian,'fx_snapshot',side_effect=ValueError('Offline')),patch.object(factors,'fetch_factor',side_effect=ValueError('Offline')):
            result=contrarian.refresh(app,{'indicators':True})
        self.assertTrue(all(i['observation']['date']=='2026-09-30' for i in result['indicators']));self.assertEqual(len(result['errors']),10)

    def test_global_etf_success_and_fx_warning_are_preserved(self):
        from aporte_brasil.market import international_market
        for warnings in ([],['Câmbio indisponível; preço nativo preservado.']):
            with patch.object(international_market,'refresh_asset',return_value=warnings):
                result=company_batch.refresh_product(app,{'asset_type':'global_etf'})
            self.assertTrue(result['received']);self.assertEqual(result['warnings'],warnings)


if __name__=='__main__':unittest.main()
