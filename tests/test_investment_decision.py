"""Decision evidence, review checkpoints and supported valuation warnings."""
import copy
import unittest
from unittest.mock import patch
from aporte_brasil.company import company_history
from aporte_brasil.portfolio import investment_decision
from aporte_brasil.portfolio import investment_value
from aporte_brasil.portfolio import portfolio_review as review
from aporte_brasil.portfolio import sector_analysis
from aporte_brasil.portfolio import long_term
import test_app as baseline
import test_contrarian as contra
import test_long_term as examples


class DecisionTests(unittest.TestCase):
    def test_software_alias_selects_technology_without_ticker_rule(self):
        for sector in ('Programas e Serviços','Software','Serviços de TI','Processamento de Dados'):
            a=examples.asset(1,sector=sector,ticker='FICT3');self.assertEqual(sector_analysis.profile(a),'technology')
        a['research_profile']='retail';self.assertEqual(sector_analysis.profile(a),'retail')

    def test_decline_does_not_turn_missing_valuation_into_cheap(self):
        local=contra.portfolio();a=local.data['assets'][0];a.pop('valuation');before=copy.deepcopy(local.data)
        p=contra.recommend(local);r=next(r for r in p['candidates'] if r['id']==a['id'])
        self.assertEqual(r['price']['reading']['status'],'unknown');self.assertFalse(r['eligible']);self.assertIn('falta demonstrar',r['decision_evidence']['summary'])
        self.assertTrue(r['decision_evidence']['decline']['available']);self.assertTrue(r['decision_evidence']['quality_groups']);self.assertEqual(local.data,before)
        self.assertTrue(r['decision_evidence']['investor10'].endswith('/acoes/'+a['ticker'].lower()+'/'))

    def test_value_explanation_lists_missing_inputs_for_selected_method(self):
        local=contra.portfolio();a=local.data['assets'][0]
        a['valuation']['suggestion'].update(method=None,value=None,ceiling=None);a['valuation']['selection']={'primary':['Fluxo fictício'],'reason':'Caixa e reinvestimento'}
        a['valuation']['data_plan']=[dict(field='fcfe_per_share',label='FCFE por ação',status='missing',guidance='Confira o caixa recorrente'),dict(field='eps',label='LPA',status='missing')]
        p=contra.recommend(local);r=next(r for r in p['candidates'] if r['id']==a['id'])
        self.assertEqual([x['key'] for x in r['decision_evidence']['needed_inputs']],['fcfe_per_share']);self.assertEqual(r['decision_evidence']['preferred_method'],'Fluxo fictício')
        item=r['decision_evidence']['method_details']['inputs'][0]
        self.assertEqual(item['key'],'fcfe_per_share');self.assertIsNone(item['value']);self.assertFalse(item['estimated'])


class ReviewValueTests(unittest.TestCase):
    def fixture(self):
        local=examples.fixture();a=local.data['assets'][0];a.update(value=500,position={'quantity':10});a['snapshots']['quote']['data']['price']=50
        a['valuation']['methods']=[dict(method='Fluxo fictício',role='primary',value=20,family='cash',requirements=['fcfe_per_share']),dict(method='Lucro comparável',role='complementary',value=25,family='earnings',requirements=['eps'])]
        return local,a

    def test_two_independent_applicable_models_required_for_strong_price_alert(self):
        local,a=self.fixture();self.assertEqual(review.price_alert(local,a,local.data['valuation_cases'],30)['status'],'expensive')
        a['valuation']['methods'][1]['family']='cash';self.assertEqual(review.price_alert(local,a,local.data['valuation_cases'],30)['status'],'limited')
        a['valuation']['methods'][1]['family']='earnings';a['valuation']['methods'][1]['value']=100
        self.assertEqual(review.price_alert(local,a,local.data['valuation_cases'],30)['status'],'limited')

    def test_estimated_or_stale_data_cannot_support_strong_exit_warning(self):
        local,a=self.fixture();a['valuation']['estimates']=['eps'];self.assertEqual(review.price_alert(local,a,local.data['valuation_cases'],30)['status'],'limited')
        a['valuation']['estimates']=[];local.data['valuation_cases'][a['ticker']]['saved_at']='2020-01-01'
        self.assertEqual(review.price_alert(local,a,local.data['valuation_cases'],30)['status'],'unknown')
        self.assertEqual(review.evaluate(local,[a],local.data['settings'],local.data['valuation_cases'],{})['rows'],[])

    def test_fii_uses_user_pvp_rule_without_company_valuation(self):
        local,a=self.fixture();a['asset_type']='fii'
        with patch.object(investment_value.fii_quality,'market_pvp',return_value=(1.7,{'asof':local.today().isoformat()},'Fonte sintética')):
            self.assertEqual(review.price_alert(local,a,{},30)['status'],'product_rule')

    def test_existing_failure_is_not_invented_as_loss_and_rules_are_distinguished(self):
        local,a=self.fixture();a.pop('valuation');check=a['company_research']['study']['groups'][0]['checks'][0];check['status']='fail'
        current=review.evaluate(local,[a],local.data['settings'],{},{});self.assertTrue(current['rows'][0]['failed']);self.assertFalse(current['rows'][0]['lost'])
        cache={'baselines':{str(a['id']):dict(ticker=a['ticker'],rules=review.rules(a,local.data['settings']),checks={check['key']:'pass'})},'events':[]}
        changed=review.evaluate(local,[a],local.data['settings'],{},cache);self.assertEqual(changed['rows'][0]['lost'][0]['kind'],'lost')
        local.data['settings']['sector_rules']={'general':{'net_debt_ebitda':1}}
        changed=review.evaluate(local,[a],local.data['settings'],{},cache);self.assertEqual(changed['rows'][0]['lost'][0]['kind'],'rule_changed')
        check['status']='unknown';self.assertFalse(review.evaluate(local,[a],local.data['settings'],{},cache)['rows'])


class CheckpointTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    trade=baseline.AppTests.trade
    complete=baseline.AppTests.complete

    def test_loss_is_recorded_locally_and_recovery_removes_active_warning(self):
        app=baseline.app;aid=self.asset();self.complete(aid);self.trade(aid)
        def foundation(year):
            a=next(a for a in app.state()['assets'] if a['id']==aid)
            company_history.save(app,a,'issuer_quality_facts',dict(symbol=company_history.symbol(a),facts={'founded_year':dict(value=year,asof=app.today().isoformat(),note='História sintética documentada',source_url='https://example.org/history')},annual_metrics=[]),'Manual · fonte sintética')
        foundation(1900)
        with patch.object(app,'request_json') as external:review.record(app,{});external.assert_not_called()
        foundation(2020);result=review.record(app,{})
        self.assertTrue(any(x['key']=='quality_age30' for r in result['rows'] for x in r['lost']))
        persisted=app.state()['position_review'];self.assertTrue(any(x['key']=='quality_age30' for r in persisted['rows'] for x in r['lost']))
        foundation(1900);recovered=review.record(app,{})
        self.assertFalse(any(x['key']=='quality_age30' for r in recovered['rows'] for x in r['failed']))
        with self.assertRaises(ValueError):review.record(app,{'asset_id':aid})


if __name__=='__main__':unittest.main()
