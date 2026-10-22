"""Synthetic portfolios: quality gates, conditional valuation, real cash and risk caps."""
import copy
import json
import random
import unittest
from datetime import date, timedelta
from unittest.mock import patch
import long_term
import portfolio_strategy
import test_app as baseline

app = baseline.app


class LocalApp:
    today = staticmethod(lambda:date(2026, 6, 15))
    now = staticmethod(lambda:'2026-06-15T12:00:00+00:00')
    @staticmethod
    def age(value):
        try:return (LocalApp.today()-date.fromisoformat(value[:10])).days
        except (TypeError, ValueError):return 99999
    number = staticmethod(app.number)
    def state(self): return self.data


def asset(index, sector=None, typ='stock', ticker=None):
    day = LocalApp.today().isoformat()
    check = lambda n:dict(key='quality_'+str(n), label='Critério fictício '+str(n), status='pass')
    return dict(id=index, ticker=ticker or 'T'+f'{index:03d}'+'3', name='Empresa fictícia '+str(index),
                asset_type=typ, sector=sector or 'Setor fictício '+str(index%3),
                value=0, position={'quantity':0}, analysis={'score':75},
                snapshots={'quote':{'data':{'price':10}, 'asof':day, 'source':'Synthetic fixture'}},
                valuation={'suggestion':{'method':'Fluxo fictício', 'value':20, 'ceiling':16},
                           'inputs':{'safety_margin':20}, 'estimates':[],
                           'methods':[{'method':'Fluxo fictício', 'role':'primary', 'requirements':['fcfe_per_share']}]},
                company_research={'study':{'groups':[{'key':'requested', 'checks':[check(n) for n in range(10)]},
                    {'key':'price', 'checks':[{'key':'price', 'label':'Preço relativo', 'status':'fail'}]}]}})


def fixture(count=6):
    local = LocalApp(); rows = [asset(n+1) for n in range(count)]
    cfg = dict(allocation_targets={k:100 if k=='national' else 0 for k in portfolio_strategy.CLASSES},
               allocation_overrides={}, asset_limit=20, sector_limit=40)
    local.data = dict(assets=rows, fixed=[], settings=cfg,
                     valuation_cases={r['ticker']:{'saved_at':local.now()} for r in rows})
    local.data['allocation'] = portfolio_strategy.allocation(rows, [], cfg, local.age)
    return local


class LongTermTests(unittest.TestCase):
    def run_plan(self, local=None, **values):
        return long_term.recommend(local or fixture(), {'amount':1000, **values})

    def test_budget_whole_units_exact_money_and_final_risk(self):
        local=fixture(); before=copy.deepcopy(local.data)
        p=self.run_plan(local, amount=1000.07)
        self.assertEqual(local.data,before)
        self.assertEqual(round(p['invested']+p['unassigned'],2),1000.07)
        self.assertEqual(p['invested'],1000)
        self.assertEqual(round(sum(r['suggested']+r['pending'] for r in p['classes']),2),1000.07)
        buys=[r for r in p['candidates'] if r['amount']]
        self.assertEqual(len(buys),5)
        for r in buys:
            self.assertEqual(r['amount'],r['quantity']*r['price']['price'])
            self.assertLessEqual(r['after_issuer_weight'],20)
        for s in {r['sector'] for r in buys}:
            self.assertLessEqual(sum(r['amount'] for r in buys if r['sector']==s)/p['invested']*100,40)

    def test_uninvested_cash_cannot_dilute_concentration(self):
        p=self.run_plan(fixture(3))
        self.assertEqual(p['invested'],0); self.assertEqual(p['unassigned'],1000)
        self.assertTrue(p['warnings'])
        p=self.run_plan(fixture(8),max_assets=2)
        self.assertEqual(p['invested'],0)

    def test_many_candidates_same_sector_still_respect_sector_cap(self):
        local=fixture(8)
        for r in local.data['assets']:r['sector']='Um único setor'
        p=self.run_plan(local)
        self.assertEqual(p['invested'],0)

    def test_existing_positions_and_varied_units_respect_final_caps(self):
        rng=random.Random(43)
        for trial in range(30):
            local=fixture(12)
            for row in local.data['assets']:
                price=rng.randint(101,5000)/100
                quantity=rng.randint(0,5)
                row['snapshots']['quote']['data']['price']=price
                row['value']=price*quantity;row['position']['quantity']=quantity
                row['valuation']['suggestion'].update(value=price*2,ceiling=price*1.6)
            cfg=local.data['settings']
            local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],[],cfg,local.age)
            p=self.run_plan(local,amount=rng.randint(100,20000)/100)
            self.assertGreaterEqual(p['unassigned'],0)
            total=sum(r['value'] for r in local.data['assets'])+p['invested']
            for row in p['candidates']:
                if not row['amount']:continue
                self.assertLessEqual(row['after_issuer_weight'],20+1e-8)
                sector_value=sum(a['value'] for a in local.data['assets'] if a['sector']==row['sector'])
                sector_value+=sum(r['amount'] for r in p['candidates'] if r['sector']==row['sector'])
                self.assertLessEqual(sector_value/total*100,40+1e-8)

    def test_share_classes_count_as_one_issuer(self):
        local=fixture(8)
        local.data['assets'][1]['ticker']='T0014'
        local.data['valuation_cases']['T0014']={'saved_at':local.now()}
        p=self.run_plan(local)
        same=[r for r in p['candidates'] if r['issuer']=='stock:T001' and r['amount']]
        self.assertLessEqual(len(same),1)
        self.assertLessEqual(sum(r['amount'] for r in same),p['invested']*.2)

    def test_quality_failure_and_missing_data_never_rewarded(self):
        local=fixture()
        checks=local.data['assets'][0]['company_research']['study']['groups'][0]['checks']
        checks[0]['status']='fail'
        row=self.run_plan(local)['candidates'][-1]
        self.assertFalse(row['eligible']); self.assertEqual(row['quality'],90)
        self.assertIn('Critérios de qualidade', ' '.join(row['reasons']))
        for check in checks:check['status']='unknown'
        row=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
        self.assertEqual(row['quality'],0);self.assertEqual(row['coverage'],0)
        self.assertFalse(row['eligible'])

    def test_partial_coverage_explicit_and_price_checks_separate(self):
        local=fixture(); checks=local.data['assets'][0]['company_research']['study']['groups'][0]['checks']
        for c in checks[:3]:c['status']='unknown'
        row=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
        self.assertTrue(row['eligible']);self.assertEqual(row['coverage'],70)
        self.assertEqual(row['quality'],70)
        row=next(r for r in self.run_plan(local,min_coverage=80)['candidates'] if r['id']==1)
        self.assertFalse(row['eligible'])

    def test_bad_tape_and_legacy_score_do_not_veto_or_promote(self):
        local=fixture(); first=copy.deepcopy(self.run_plan(local))
        for row in local.data['assets']:
            row['analysis']['score']=0;row['trend']={'score':0}
        second=self.run_plan(local)
        self.assertEqual([(r['ticker'],r['priority'],r['amount']) for r in first['candidates']],
                         [(r['ticker'],r['priority'],r['amount']) for r in second['candidates']])

    def test_deeper_discount_wins_without_unbounded_bonus(self):
        local=fixture(); local.data['assets'][0]['valuation']['suggestion'].update(value=12,ceiling=11)
        local.data['assets'][1]['valuation']['suggestion'].update(value=10000,ceiling=8000)
        p=self.run_plan(local)
        self.assertNotEqual(p['candidates'][0]['id'],1)
        self.assertEqual(next(r for r in p['candidates'] if r['id']==2)['components']['discount'],100)

    def test_stale_future_quote_and_reviewed_valuation_dates(self):
        for field,stamp in [('quote','2026-06-07'),('quote','2026-06-16'),('case','2025-01-01'),('case','2026-06-16')]:
            with self.subTest(field=field,stamp=stamp):
                local=fixture(); row=local.data['assets'][0]
                if field=='quote':row['snapshots']['quote']['asof']=stamp
                else:local.data['valuation_cases'][row['ticker']]['saved_at']=stamp
                self.assertFalse(next(r for r in self.run_plan(local)['candidates'] if r['id']==1)['eligible'])

    def test_estimates_screening_methods_above_ceiling_and_negative_value(self):
        for change in ('estimate','role','expensive','negative'):
            with self.subTest(change=change):
                local=fixture(); v=local.data['assets'][0]['valuation']
                if change=='estimate':v['estimates']=['fcfe_per_share']
                if change=='role':v['methods'][0]['role']='screening'
                if change=='expensive':v['suggestion']['ceiling']=9.99
                if change=='negative':v['suggestion']['value']=-1
                self.assertFalse(next(r for r in self.run_plan(local)['candidates'] if r['id']==1)['eligible'])

    def test_no_budget_shift_into_other_classes_for_missing_opportunity(self):
        local=fixture(); cfg=local.data['settings'];cfg['allocation_targets'].update(national=50,rf=50)
        local.data['allocation']=portfolio_strategy.allocation(local.data['assets'],[],cfg,local.age)
        p=self.run_plan(local)
        rf=next(r for r in p['classes'] if r['key']=='rf')
        self.assertEqual(rf['budget'],500);self.assertEqual(rf['suggested'],0)
        self.assertGreaterEqual(p['unassigned'],500)
        self.assertLessEqual(p['invested'],500)

    def test_non_stock_no_fabricated_company_score(self):
        local=fixture(); local.data['assets'][0]['asset_type']='etf'
        local.data['assets'][0].pop('company_research')
        r=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
        self.assertIsNone(r['quality']); self.assertIsNone(r['priority']);self.assertFalse(r['eligible'])

    def test_fii_strict_pvp_discount_and_hard_discard(self):
        local=fixture(); row=local.data['assets'][0];row['asset_type']='fii'
        row['fii_research']=row.pop('company_research')
        for pvp,eligible in ((.8,True),(1,False),(1.5,False),(1.5001,False)):
            with self.subTest(pvp=pvp):
                row['snapshots']['statistics']={'asof':local.today().isoformat(),'data':{'pvp':pvp}}
                # This helper uses the app's real date; patch it to the fixture date.
                with patch.object(local,'age',lambda v:(local.today()-date.fromisoformat(v[:10])).days if v else 99999):
                    r=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
                self.assertEqual(r['eligible'],eligible)
                self.assertEqual(any('Descarte obrigatório' in x for x in r['reasons']),pvp>1.5)

    def test_fii_yield_failure_and_misaligned_pvp_date(self):
        local=fixture();row=local.data['assets'][0];row['asset_type']='fii'
        row['fii_research']=row.pop('company_research')
        row['snapshots']['statistics']={'asof':local.today().isoformat(),'data':{'pvp':.8}}
        row['fii_research']['study']['groups'][0]['checks'].append(
            dict(key='fii_quality_yield',label='Yield dos pares',scope='price',status='fail'))
        with patch.object(local,'age',lambda v:(local.today()-date.fromisoformat(v[:10])).days if v else 99999):
            r=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
            self.assertIn('Yield abaixo',' '.join(r['reasons']))
            row['fii_research']['study']['groups'][0]['checks'][-1]['status']='unknown'
            r=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
            self.assertTrue(r['eligible']);self.assertIn('Yield dos pares',r['pending'])
            row['snapshots']['statistics']['asof']='2026-06-14'
            r=next(r for r in self.run_plan(local)['candidates'] if r['id']==1)
            self.assertFalse(r['eligible']);self.assertIn('mesma data',' '.join(r['reasons']))

    def test_held_filter_and_unconfirmed_estimates(self):
        local=fixture()
        self.assertTrue(all(not r['eligible'] for r in self.run_plan(local,universe='held')['candidates']))
        local.data['allocation']['issues']=['Saldo sintético ao custo']
        with self.assertRaisesRegex(ValueError,'estimativas'):self.run_plan(local)
        self.assertTrue(self.run_plan(local,accept_estimates=True)['warnings'])

    def test_context_is_separate_dated_and_does_not_change_money(self):
        local=fixture(); row=local.data['assets'][0]; day=local.today()
        row['snapshots']['history']={'data':{'prices':[{'date':(day-timedelta(days=125-i)).isoformat(), 'close':100-i*.25} for i in range(126)]}}
        base=self.run_plan(local); enriched=self.run_plan(local,mode='context')
        self.assertEqual([(r['id'],r['amount'],r['priority']) for r in base['candidates']],
                         [(r['id'],r['amount'],r['priority']) for r in enriched['candidates']])
        c=enriched['candidates'][0]['context']
        self.assertLess(c['drawdown']['value'],-15);self.assertIn('Candidato',c['hypothesis'])
        self.assertFalse(base['candidates'][0].get('context'))
        self.assertFalse(enriched['candidates'][1]['context']['available'])

    def test_stale_ai_does_not_supply_pessimism(self):
        local=fixture(); row=local.data['assets'][0]
        row['company_research']['news_context']={'sections':[dict(label='Setor',stale=False,retrieved_at=local.now(),
            items=[dict(url='https://example.org/test',title='Fictício')],
            sentiment=dict(tone='negative',stale=False,analyzed_at='2025-01-01'))]}
        c=long_term.context(local,row,True)
        self.assertFalse(c['sentiments']);self.assertIn('Sem evidência',c['hypothesis'])
        row['company_research']['news_context']['sections'][0]['stale']=True
        self.assertFalse(long_term.context(local,row,True)['available'])

    def test_validation_and_no_goals(self):
        for extra in ({'amount':True},{'amount':float('nan')},{'max_assets':True},{'max_assets':1.5},
                      {'max_assets':21},{'min_coverage':49},{'min_coverage':True},{'accept_estimates':'true'},
                      {'mode':'forecast'},{'universe':'internet'},{'unknown':1}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.run_plan(**extra)
        local=fixture();local.data['allocation']['has_targets']=False
        with self.assertRaisesRegex(ValueError,'metas'):self.run_plan(local)


class LongTermIntegrationTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    trade=baseline.AppTests.trade
    complete=baseline.AppTests.complete

    def test_real_state_pending_data_and_no_mutations_or_network(self):
        aid=self.asset();self.complete(aid)
        app.mutate('/api/settings',{'allocation_targets':{k:100 if k=='national' else 0 for k in portfolio_strategy.CLASSES}})
        with app.connect() as c:before=c.serialize()
        with patch.object(app,'request_json',side_effect=AssertionError('No network from recommender')):
            p=long_term.recommend(app,{'amount':123.45,'mode':'context'})
        self.assertEqual(p['unassigned'],123.45)
        self.assertFalse(p['candidates'][0]['eligible'])
        self.assertTrue(p['candidates'][0]['pending'])
        with app.connect() as c:self.assertEqual(c.serialize(),before)
        self.assertEqual(json.loads(json.dumps(p))['amount'],123.45)


if __name__=='__main__':unittest.main()
