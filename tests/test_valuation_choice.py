"""Saved reference choice, comparable historical samples and objective registry facts."""
import copy
from datetime import date
import unittest
from unittest.mock import patch
import company_history
import company_registry
import company_research
import history_cache
import investment_value
import market_ai
import valuation
import valuation_history
import test_app as baseline

app=baseline.app
DAY=date(2026,11,6)
def age(ref):
    try:return (DAY-date.fromisoformat(str(ref)[:10])).days
    except (ValueError,TypeError):return 99999


class ReferenceChoiceTests(unittest.TestCase):
    def asset(self):return dict(ticker='ABCD3',name='Empresa fictícia',asset_type='stock',sector='Saúde',position={'quantity':1},metrics={'price':20},snapshots={'quote':{'asof':DAY.isoformat(),'data':{'price':20}}},sector_metrics={})

    def calculate(self,**inputs):
        a=self.asset();v=valuation.calculate(inputs,app.number);valuation_history.attach(v,a,age);return valuation.apply_policy(v,valuation.policy(a,v['inputs']))

    def test_bazin_is_explicit_choice_and_auto_still_uses_business_policy(self):
        self.assertIsNone(self.calculate(dividends_per_share=2,target_yield=6)['suggestion']['value'])
        r=self.calculate(reference_method='Bazin',dividends_per_share=2,target_yield=6,safety_margin=20)
        self.assertAlmostEqual(r['suggestion']['value'],2/.06);self.assertAlmostEqual(r['suggestion']['ceiling'],2/.06*.8)
        self.assertEqual(r['suggestion']['mode'],'manual');self.assertEqual(r['inputs']['reference_method'],'Bazin')
        missing=self.calculate(reference_method='Bazin',eps=2,target_pe=15)
        self.assertEqual(missing['suggestion']['method'],'Bazin');self.assertIsNone(missing['suggestion']['value'])

    def test_manual_method_is_used_by_value_gate_and_estimates_remain_blocked(self):
        a=self.asset();a['valuation']=self.calculate(reference_method='Bazin',dividends_per_share=2,target_yield=6)
        cases={a['ticker']:{'saved_at':DAY.isoformat()}}
        fake=type('Local',(),{'age':staticmethod(age),'today':staticmethod(lambda:DAY)})()
        self.assertEqual(investment_value.reference(fake,a,cases)['reading']['status'],'cheap')
        a['valuation']['estimates']=['dividends_per_share']
        self.assertEqual(investment_value.reference(fake,a,cases)['reading']['status'],'unknown')
        a['sector']='Bancos';v=valuation.calculate({'reference_method':valuation.FCFF,'fcff_forecast':[10],'wacc':10,'fcff_terminal_value':0,'net_debt_per_share':0,'other_claims_per_share':0},app.number)
        valuation.apply_policy(v,valuation.policy(a,v['inputs']));self.assertIsNone(v['suggestion']['value'])

    def test_reference_validation_and_roundtrip(self):
        for data in ({'reference_method':'invented'},{'reference_method':[]},{'historical_stat':'last'},{'historical_stat':False}):
            with self.assertRaises(ValueError):valuation.calculate(data,app.number)
        r=self.calculate(reference_method='Graham',historical_stat='median',eps=2,bvps=10)
        self.assertEqual(r['inputs'],valuation.calculate(r['inputs'],app.number)['inputs'])

    def test_history_uses_monthly_multiples_with_coverage_and_no_current_price_backfill(self):
        a=self.asset();a['fundamental_history']={'pe':[dict(date=f'{year}-{month:02d}-15',value=10,source='Fonte sintética') for year in (2022,2023,2024) for month in range(1,13)]}
        a['fundamental_history']['pe'].append(dict(date='2024-12-20',value=46,source='Correção sintética'))
        before=copy.deepcopy(a);v=valuation.calculate({'eps':2,'reference_method':'P/L histórico'},app.number)
        valuation_history.attach(v,a,age);valuation.apply_policy(v,valuation.policy(a,v['inputs']))
        h=v['historical_multiples']['pe'];self.assertTrue(h['available']);self.assertEqual(h['count'],36);self.assertEqual(h['mean'],11);self.assertEqual(h['median'],10)
        self.assertEqual(v['suggestion']['value'],22);self.assertEqual(a,before)
        v=valuation.calculate({'eps':2,'reference_method':'P/L histórico','historical_stat':'median'},app.number);valuation_history.attach(v,a,age);valuation.apply_policy(v,valuation.policy(a,v['inputs']))
        self.assertEqual(v['suggestion']['value'],20)
        a['fundamental_history']['pe']=a['fundamental_history']['pe'][-12:]
        h=valuation_history.series(a,'pe',age);self.assertFalse(h['available']);self.assertIsNone(h['mean'])

    def test_invalid_old_future_and_nonpositive_history_is_excluded(self):
        a=self.asset();a['fundamental_history']={'pvp':[dict(date=d,value=v) for d,v in [('2020-01-01',2),('2027-01-01',2),('2026-11-01',2),('2023-01-01',0),('2023-02-01',-1),('2023-03-01',True),('2023-04-01',float('inf'))]]}
        h=valuation_history.series(a,'pvp',age);self.assertEqual(h['count'],0);self.assertIsNone(h['mean'])


class RegistryAndConnectionTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def registry_asset(self):
        aid=self.asset();a=company_research.asset(app,aid)
        payload=dict(symbol=company_history.symbol(a),name='Empresa fictícia',sector='Saúde',industry='',description='',cnpj='12.345.678/0001-90',website='https://example.org',source_url='https://example.org')
        company_history.save(app,a,'issuer_profile',payload,'Identificação pública sintética')
        return company_research.asset(app,aid)

    def test_registry_fills_only_objective_missing_fields_with_confirmed_identity(self):
        a=self.registry_asset();rows=[dict(CNPJ_CIA='12.345.678/0001-90',CD_CVM='1',DT_CONST='1900-02-03',CONTROLE_ACIONARIO='PRIVADO',SIT='ATIVO')]
        with patch.object(company_registry.public_reports,'company_identity',return_value='12345678000190'),patch.object(company_registry,'catalog',return_value=rows):
            self.assertEqual(company_registry.fill(app,a),['founded','state_controlled'])
            b=company_research.asset(app,a['id']);facts=b['snapshots']['issuer_quality_facts']['data']['facts']
            self.assertEqual(facts['founded']['value'],'1900-02-03');self.assertFalse(facts['state_controlled']['value'])
            self.assertNotIn('single_client_concentration',facts);self.assertNotIn('good_management',facts)
            self.assertEqual(company_registry.fill(app,b),[])
        with patch.object(company_registry.public_reports,'company_identity',return_value='99999999000199'),patch.object(company_registry,'catalog') as download:
            with self.assertRaises(ValueError):company_registry.fill(app,a)
            download.assert_not_called()

    def test_registry_does_not_overwrite_year_or_interpret_unknown_control(self):
        a=self.registry_asset();company_history.save(app,a,'issuer_quality_facts',dict(symbol=company_history.symbol(a),facts={'founded_year':dict(value=1890,asof=app.today().isoformat(),source_url='https://example.org',note='Ano conferido')},annual_metrics=[]),'Manual · ano conferido')
        rows=[dict(CNPJ_CIA='12345678000190',DT_CONST='1900-01-01',CONTROLE_ACIONARIO='',SIT='ATIVO')]
        for control in ('','ESTRANGEIRO','ESTRANGEIRO HOLDING'):
            rows[0]['CONTROLE_ACIONARIO']=control
            with patch.object(company_registry.public_reports,'company_identity',return_value='12345678000190'),patch.object(company_registry,'catalog',return_value=rows):
                self.assertEqual(company_registry.fill(app,company_research.asset(app,a['id'])),[])
        facts=company_research.asset(app,a['id'])['snapshots']['issuer_quality_facts']['data']['facts'];self.assertEqual(set(facts),{'founded_year'})

    def test_monthly_multiple_history_retains_years_despite_daily_queries(self):
        a=self.registry_asset()
        with app.connect() as c:
            for year in (2022,2023,2024):
                for month in range(1,13):
                    for day in range(1,6):app.add_snapshot(c,a['id'],'metric:pe',{'pe':day},'Fonte sintética',f'{year}-{month:02d}-{day:02d}')
            rows=history_cache.observations(app,c,a['id'])['pe']
        self.assertEqual(len(rows),36);self.assertTrue(all(r['value']==5 for r in rows));self.assertTrue(valuation_history.series({'fundamental_history':{'pe':rows}},'pe',age)['available'])

    def test_ollama_connection_uses_only_local_endpoint_and_does_not_change_preferences(self):
        before=market_ai.config(app)
        with patch.object(market_ai,'request',return_value={'models':[{'name':'qwen2.5:3b'},{'name':'qwen2.5:7b'}]}) as call:
            r=market_ai.connection(app,dict(provider='ollama',base_url='http://127.0.0.1:11434',model='qwen2.5:7b'))
        self.assertEqual(r['selected_model'],'qwen2.5:7b');self.assertTrue(r['model_available']);self.assertNotIn('search_key',r)
        self.assertEqual(call.call_args.args[0],'http://127.0.0.1:11434/api/tags');self.assertEqual(market_ai.config(app),before)
        for data in ({'base_url':'https://example.org'},{'command':'anything'},{'search_key':'secret'}):
            with self.assertRaises(ValueError):market_ai.connection(app,data)


if __name__=='__main__':unittest.main()
