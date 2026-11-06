"""Value conclusions, sector aliases, held overlap and correlated purchases."""
import copy
import math
import random
import unittest
from datetime import timedelta
from unittest.mock import patch

import investment_risk as risk
import investment_value as value
import long_term
import portfolio_strategy
import valuation
import test_app as baseline
import test_long_term as examples
import test_contrarian as contra


class ValueTests(unittest.TestCase):
    def test_explicit_value_labels_and_no_discount_from_missing_evidence(self):
        local=examples.fixture();a=local.data['assets'][0]
        for price,status in ((10,'cheap'),(18,'no_margin'),(20,'fair'),(23,'expensive')):
            a['snapshots']['quote']['data']['price']=price
            r=value.reference(local,a,local.data['valuation_cases'])
            self.assertEqual(r['reading']['status'],status)
        a['snapshots']['quote']['data']['price']=10
        for alter in ('date','estimates','quote'):
            b=copy.deepcopy(a);cases=copy.deepcopy(local.data['valuation_cases'])
            if alter=='date':cases={}
            if alter=='estimates':b['valuation']['estimates']=['fcfe_per_share']
            if alter=='quote':b['snapshots']['quote']['asof']='2020-01-01'
            r=value.reference(local,b,cases)['reading'];self.assertEqual(r['status'],'unknown');self.assertIsNone(r['score'])

    def test_fii_discount_is_patrimonial_and_etf_does_not_get_fair_value(self):
        local=examples.fixture();a=local.data['assets'][0];a['asset_type']='fii'
        with patch.object(value.fii_quality,'market_pvp',return_value=(.8,{'asof':local.today().isoformat()},'Documento sintético')):
            p=value.reference(local,a,{})
        self.assertEqual(p['reading']['label'],'Desconto patrimonial');self.assertIn('não comprova valor justo',p['reading']['explanation'])
        a['asset_type']='etf';self.assertEqual(value.reference(local,a,{})['reading']['status'],'unknown')

    def test_sector_policy_selects_bank_equity_and_normalized_commodity_method(self):
        bank=examples.asset(1,sector='Bancos');metal=examples.asset(2,sector='Mineração')
        self.assertEqual(valuation.policy(bank)['primary'][0],valuation.RI)
        self.assertEqual(valuation.policy(metal)['primary'][0],valuation.FCFF)

    def test_audited_complementary_method_precedes_quote_derived_primary(self):
        rows=[dict(method=name,value=20,ceiling=16,classification='cheap',requirements=[field]) for name,field in ((valuation.RI,'bvps'),(valuation.PE,'eps'))]
        result=dict(methods=rows,estimates=['bvps']);valuation.apply_policy(result,valuation.policy(examples.asset(1,sector='Bancos')))
        self.assertEqual(result['suggestion']['method'],valuation.PE);self.assertTrue(result['suggestion']['fallback'])


def histories(local,rows):
    rng=random.Random(981);common=[rng.gauss(0,.013) for _ in range(130)];other=[rng.gauss(0,.013) for _ in common]
    for index,a in enumerate(rows):
        path=common if index<2 else other;price=100;points=[]
        for n,r in enumerate(path):
            price*=math.exp(r);points.append(dict(date=(local.today()-timedelta(days=130-n)).isoformat(),close=price))
        a['snapshots']['history']=dict(data=dict(prices=points,currency='BRL'),retrieved_at=local.now())


class RiskTests(unittest.TestCase):
    def test_sector_rating_and_economic_aliases(self):
        bank=examples.asset(1,sector='Bancos');alias=examples.asset(2,sector='Financeiro');insurance=examples.asset(3,sector='Seguradoras');retail=examples.asset(4,sector='Varejo')
        self.assertEqual(risk.group(bank)['key'],risk.group(alias)['key']);self.assertEqual(risk.group(bank)['key'],risk.group(insurance)['key'])
        self.assertGreater(risk.rating(bank)['score'],risk.rating(retail)['score'])
        self.assertIn('qualitativa',risk.rating(bank)['note']);self.assertIsNone(risk.rating(examples.asset(5,typ='etf'))['score'])

    def test_held_value_weights_and_unknown_correlation_are_explicit(self):
        local=examples.fixture(4);a,b,c,d=local.data['assets'];a.update(value=1000,position={'quantity':10});histories(local,[a,b,c]);before=copy.deepcopy(local.data)
        plan=risk.Plan(local,local.data);same=plan.assess(b['id']);other=plan.assess(c['id']);unknown=plan.assess(d['id'])
        self.assertAlmostEqual(same['pairs'][0]['correlation'],1,places=8);self.assertGreater(other['correlation_score'],same['correlation_score'])
        self.assertEqual(unknown['correlation_coverage'],0);self.assertEqual(unknown['correlation_score'],50)
        self.assertEqual(local.data,before)
        a['snapshots']['history']['data']['currency']='USD';self.assertEqual(risk.Plan(local,local.data).assess(b['id'])['correlation_coverage'],0)

    def test_concentration_counts_equivalent_names_and_actual_invested_cash(self):
        local=contra.portfolio();assets=local.data['assets'];assets[0]['sector']='Bancos';assets[1]['sector']='Financeiro';assets[2]['sector']='Seguradoras'
        local.data['allocation']=portfolio_strategy.allocation(assets,local.data['fixed'],local.data['settings'],local.age)
        p=contra.recommend(local);total=sum(a['value'] for a in assets)+p['invested'];key=risk.group(assets[0])['key']
        used=sum(a['value'] for a in assets if risk.group(a)['key']==key)+sum(r['amount'] for r in p['candidates'] if r['sector_key']==key)
        if any(r['amount'] for r in p['candidates'] if r['sector_key']==key):self.assertLessEqual(used/total*100,local.data['settings']['sector_limit']+1e-8)
        summary=next(r for r in p['sector_allocation'] if r['key']==key);self.assertAlmostEqual(summary['after_weight'],used/total*100)

    def test_value_and_sector_scores_affect_contraflow_without_lifting_gates(self):
        local=contra.portfolio();assets=local.data['assets'];assets[0]['sector']='Bancos';assets[1]['sector']='Varejo'
        p=contra.recommend(local);rows={r['id']:r for r in p['candidates']};bank,retail=(rows[a['id']] for a in assets[:2])
        self.assertGreater(bank['sector_rating']['score'],retail['sector_rating']['score']);self.assertIn('diversification',bank['components'])
        old=bank['priority'];assets[0]['valuation']['suggestion'].update(value=12,ceiling=11)
        lower=next(r for r in contra.recommend(local)['candidates'] if r['id']==assets[0]['id']);self.assertLess(lower['priority'],old)
        assets[0]['company_research']['study']['groups'][0]['checks'][0]['status']='fail'
        blocked=next(r for r in contra.recommend(local)['candidates'] if r['id']==assets[0]['id']);self.assertFalse(blocked['eligible']);self.assertEqual(blocked['amount'],0)

    def test_proposed_purchase_reduces_next_correlated_priority(self):
        local=examples.fixture(3);a,b,c=local.data['assets'];histories(local,[a,b,c]);plan=risk.Plan(local,local.data)
        self.assertEqual(plan.assess(b['id'])['correlation_score'],50)
        values={a['id']:1000,b['id']:0,c['id']:0}
        self.assertLess(plan.assess(b['id'],values)['score'],plan.assess(c['id'],values)['score'])

    def test_allocator_chooses_less_correlated_second_destination(self):
        local=examples.fixture(3);histories(local,local.data['assets']);local.data['settings'].update(asset_limit=50,sector_limit=100)
        plan=risk.Plan(local,local.data)
        rows=[dict(id=a['id'],ticker=a['ticker'],issuer=long_term.issuer(a),sector_key=long_term.sector(a),class_key='national',eligible=True,priority=50,
            strategy='contrarian',asset_type='stock',diversification=plan.assess(a['id']),ai={'applied':False},price={'price':10}) for a in local.data['assets']]
        self.assertTrue(long_term.allocate(local.data,rows,{'national':100000},2,0,100000,plan))
        self.assertEqual([r['id'] for r in rows if r['amount']],[1,3]);self.assertEqual(sum(r['amount'] for r in rows),1000)

    def test_mixed_etf_related_value_is_not_split_into_invented_weights(self):
        local=examples.fixture(3);a,b,c=local.data['assets'];a.update(asset_type='etf',value=1000,position={'quantity':10},sector='ETF misto',exposure=dict(source_url='https://example.org/fund',asof=local.today().isoformat(),focus='mixed',profiles=['technology','bank'],themes=[],asset_class='mixed'))
        b['sector']='Tecnologia';plan=risk.Plan(local,local.data);r=plan.assess(b['id'])
        self.assertEqual(r['sector_weight'],0);self.assertEqual(r['related_product_weight'],100)
        self.assertNotEqual(risk.group(a)['key'],risk.group(b)['key']);self.assertIn('sem estimar pesos internos',r['note'])


class AccessibilityTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    def test_setting_validation_persistence_and_backup(self):
        app=baseline.app;app.mutate('/api/settings',{'color_mode':'accessible'})
        self.assertEqual(app.state()['settings']['color_mode'],'accessible')
        for bad in (True,'unknown',{}):
            with self.assertRaises(ValueError):app.validate_settings({'color_mode':bad})
        with app.connect() as c:backup=app.export_data(c)
        self.assertIn('accessible',str(backup['tables']['settings']))


if __name__=='__main__':unittest.main()
