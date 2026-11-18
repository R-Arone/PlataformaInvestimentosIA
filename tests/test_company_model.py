"""Golden financial scenarios, currency/date gaps and persisted issuer assumptions."""
import copy
import json
import unittest

import test_app as baseline
import test_company_insights as fixtures
from aporte_brasil.company import company_model as model
from aporte_brasil.company import company_research as research
from aporte_brasil.company import company_history as history
from aporte_brasil.company import stock_fundamentals

app = baseline.app


class CompanyModelTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    complete = baseline.AppTests.complete
    row = fixtures.CompanyInsightsTests.row
    statements = fixtures.CompanyInsightsTests.statements
    governance = fixtures.CompanyInsightsTests.governance
    company = fixtures.CompanyInsightsTests.company

    def selected(self, aid):
        return next(a for a in app.state()['assets'] if a['id'] == aid)

    def configure(self, aid, **values):
        p = {**model.DEFAULTS, **values}
        research.action(app, '/api/issuer/model', {'asset_id': aid, 'parameters': p})
        return self.selected(aid)['company_research']['fundamental_model']

    def test_every_registered_issuer_gets_a_model_even_without_history(self):
        aid = self.asset()
        m = self.selected(aid)['company_research']['fundamental_model']
        self.assertEqual(m['quality']['status'], 'incomplete')
        self.assertEqual(m['stress']['status'], 'incomplete')
        self.assertEqual(m['valuation']['scenarios'], [])
        self.assertIsNone(m['parameters']['cost_of_equity'])
        self.assertNotIn('probability', m)

    def test_residual_value_and_price_classification_have_known_answers(self):
        aid = self.company()
        with app.connect() as c:
            app.add_snapshot(c,aid,'statistics',{'pvp':.8,'pe':10,'dy':3},'Fixture',self.day)
        m = self.configure(aid,cost_of_equity=15,sustainable_roe=18)
        chosen = m['valuation']['scenarios'][1]
        self.assertEqual(chosen['pvp'], 1.25)
        self.assertAlmostEqual(chosen['difference'],56.25)
        self.assertEqual(chosen['classification'],'below')
        self.assertEqual(m['valuation']['roe_origin'],'Premissa escolhida')

    def test_value_tolerance_uses_current_price_relative_to_the_hypothesis(self):
        a = {'sector_metrics':{'roe':{'value':15},'pvp':{'value':.9}},'sector_analysis':{'profile':'bank'}}
        r = model.residual_value(a,{**model.DEFAULTS,'cost_of_equity':15})
        self.assertEqual(r['scenarios'][1]['pvp'],1)
        self.assertEqual(r['scenarios'][1]['classification'],'near')

    def test_invalid_growth_reinvestment_is_not_reported_as_fair_value(self):
        aid = self.company()
        m = self.configure(aid,cost_of_equity=15,sustainable_roe=2,long_growth=3)
        self.assertIsNone(m['valuation']['scenarios'][1]['pvp'])
        self.assertEqual(m['valuation']['status'],'incomplete')
        with self.assertRaises(ValueError):self.configure(aid,cost_of_equity=3,long_growth=3)

    def test_operating_stress_preserves_depreciation_and_has_known_answer(self):
        aid = self.company()
        m = self.selected(aid)['company_research']['fundamental_model']
        base, shocked = m['stress']['rows']
        self.assertEqual(base['ebit'],120)
        # Revenue 1000 -> 800. Cash expenses 850 -> 731, depreciation 30.
        self.assertAlmostEqual(shocked['ebit'],39)
        self.assertAlmostEqual(shocked['ebitda'],69)
        self.assertEqual(shocked['interest'],23) # 20 + 200 * .50 * .03
        self.assertAlmostEqual(shocked['interest_coverage'],39/23)
        self.assertAlmostEqual(shocked['net_debt_ebitda'],100/69)
        self.assertEqual(m['stress']['status'],'within_scenario')

    def test_fixed_costs_and_revenue_loss_can_reverse_operating_result(self):
        aid = self.company()
        m = self.configure(aid,variable_cost_share=0)
        self.assertAlmostEqual(m['stress']['rows'][1]['ebit'],-80)
        self.assertEqual(m['stress']['status'],'attention')

    def test_missing_interest_does_not_become_zero_or_safe(self):
        aid = self.company();d=self.statements()
        for r in d['annual']:r['interest_expense']=None
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        s=self.selected(aid)['company_research']['fundamental_model']['stress']
        self.assertIsNone(s['rows'][1]['interest_coverage'])
        self.assertEqual(s['status'],'incomplete')

    def test_explicit_zero_debt_and_zero_interest_are_supported_without_infinity(self):
        aid=self.company();d=self.statements()
        for r in d['annual']:r.update(debt=0,interest_expense=0)
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        s=self.selected(aid)['company_research']['fundamental_model']['stress']
        self.assertEqual(s['status'],'within_scenario')
        self.assertEqual(s['rows'][1]['interest'],0)
        self.assertIsNone(s['rows'][1]['interest_coverage'])
        json.dumps(s,allow_nan=False)

    def test_financial_firms_never_use_industrial_stress_or_cash_cut(self):
        aid=self.company(sector='Bancos')
        for sector in ('Bancos','Seguros','Serviços financeiros e holdings'):
            with app.connect() as c:c.execute('UPDATE assets SET sector=?,financial=1 WHERE id=?',(sector,aid))
            m=self.selected(aid)['company_research']['fundamental_model']
            self.assertEqual(m['stress']['status'],'na')
            self.assertEqual(m['stress']['rows'],[])
            self.assertEqual(next(c for c in m['quality']['checks'] if c['key']=='cash')['status'],'na')

    def test_currency_conflict_cannot_make_a_complete_model(self):
        aid=self.company();a=self.selected(aid)
        other=copy.deepcopy(a['snapshots']['issuer_financials']['data']) if 'issuer_financials' in a['snapshots'] else {
            'symbol':a['ticker']+'.SA','currency':'USD','source_url':'https://example.org/conflict',
            'years':[{k:r.get(k) for k in ('date','net_income','revenue','operating_cashflow','free_cashflow')} for r in self.statements()['annual']]}
        other['currency']='USD'
        with app.connect() as c:app.add_snapshot(c,aid,'issuer_financials',other,'Fixture',self.day)
        m=self.selected(aid)['company_research']['fundamental_model']
        self.assertEqual(m['stress']['status'],'incomplete')
        self.assertEqual(m['stress']['rows'],[])
        self.assertEqual(next(c for c in m['quality']['checks'] if c['key']=='growth')['status'],'unknown')

    def test_old_financial_periods_are_not_treated_as_current_stress(self):
        aid=self.company();d=self.statements();d['annual']=d['annual'][:-2]
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        s=self.selected(aid)['company_research']['fundamental_model']['stress']
        self.assertEqual(s['status'],'incomplete');self.assertEqual(s['rows'],[])

    def test_foreign_ttm_joins_require_same_date_and_currency(self):
        aid=self.asset('AAPL',sector='Tecnologia')
        with app.connect() as c:c.execute("UPDATE assets SET asset_type='foreign' WHERE id=?",(aid,))
        values={'revenue':1000,'ebit':120,'ebitda':150,'debt':200,'cash':100,'interest':20}
        fields={v:k for k,v in stock_fundamentals.FIELDS.items()}
        data={'symbol':'AAPL','market':'US','source_url':'https://finance.yahoo.com/quote/AAPL/financials/',
              'series':[{'field':fields[k],'date':self.day,'period':'TTM' if fields[k].startswith('trailing') else '3M',
                         'currency':'USD','value':v} for k,v in values.items()]}
        with app.connect() as c:app.add_snapshot(c,aid,'stock_financials',data,'Fixture',self.day)
        s=self.selected(aid)['company_research']['fundamental_model']['stress']
        self.assertEqual(s['base']['currency'],'USD');self.assertAlmostEqual(s['rows'][1]['ebit'],39)
        changed=copy.deepcopy(data);next(r for r in changed['series'] if r['field']==fields['interest'])['currency']='EUR'
        with app.connect() as c:app.add_snapshot(c,aid,'stock_financials',changed,'Fixture',self.day)
        s=self.selected(aid)['company_research']['fundamental_model']['stress']
        self.assertIsNone(s['rows'][1]['interest_coverage']);self.assertEqual(s['status'],'incomplete')

    def test_assumptions_are_per_issuer_persisted_and_backup_roundtrip(self):
        aid=self.company();second=self.asset('OTHER3')
        m=self.configure(aid,cost_of_equity=15,revenue_shock=-30)
        app.init_db()
        self.assertEqual(self.selected(aid)['company_research']['fundamental_model']['parameters'],m['parameters'])
        self.assertIsNone(self.selected(second)['company_research']['fundamental_model']['parameters']['cost_of_equity'])
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(self.selected(aid)['company_research']['fundamental_model']['parameters'],m['parameters'])
        bad=copy.deepcopy(backup);snap=next(s for s in bad['tables']['snapshots'] if s['kind']==model.KINDS[0])
        data=json.loads(snap['data']);data['symbol']='OTHER3.SA';snap['data']=json.dumps(data)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)

    def test_settings_validation_rejects_nan_boolean_unknown_and_future(self):
        for changed in ({'rate_shock':float('nan')},{'rate_shock':True},{'variable_cost_share':101},{'extra':1}):
            with self.assertRaises(ValueError):model.parameters({**model.DEFAULTS,**changed})
        with self.assertRaises(ValueError):model.validate_snapshot(app,{'symbol':'ABCD3.SA','asof':'2099-01-01','parameters':model.DEFAULTS})

    def test_new_statements_recompute_scenarios_without_touching_assumptions(self):
        aid=self.company();before=self.configure(aid,cost_of_equity=15)
        d=self.statements();d['annual'][-1]['ebit']=60
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        after=self.selected(aid)['company_research']['fundamental_model']
        self.assertEqual(after['parameters'],before['parameters'])
        self.assertNotEqual(after['stress']['rows'][1]['ebit'],before['stress']['rows'][1]['ebit'])


if __name__=='__main__':unittest.main()
