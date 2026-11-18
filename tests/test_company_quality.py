"""Eleven requested criteria: strict cutoffs, historical windows and sourced vetoes."""
import copy
from datetime import date, timedelta
import unittest
from unittest.mock import patch

from aporte_brasil.company import company_quality as quality
from aporte_brasil.company import company_history
from aporte_brasil.company import company_insights
from aporte_brasil.company import company_research
import test_app as baseline

app = baseline.app


class CriteriaTests(unittest.TestCase):
    def setUp(self):
        self.end = app.today().year-1
        self.years = list(range(self.end-5,self.end+1))
        self.asset = {'ticker':'ABCD3','asset_type':'stock','snapshots':{},'sector_analysis':{'profile':'utility'}}
        rows = [dict(date=f'{y}-12-31',net_income=100*1.10**i,revenue=1000*1.08**i,
                     equity=1000,debt=200,cash=100,ebitda=100) for i,y in enumerate(self.years)]
        self.asset['snapshots']['issuer_statements'] = {'data':dict(annual=rows,currency='BRL',source_url='https://example.org/statements'), 'retrieved_at':app.now()}
        self.payload = {'symbol':'ABCD3.SA','facts':{},'annual_metrics':[]}
        for key in quality.BOOL_FIELDS:
            self.fact(key,key in ('innovation','dividend_payments','blue_chip','good_management'))
        self.fact('founded','1900-01-01')
        self.fact('sector_origin_year',1800)
        self.fact('leadership',{'rank':1,'scope':'national','metric':'Receita no segmento nacional, exercício completo'})

    def fact(self,key,value,asof=None):
        self.payload['facts'][key] = dict(value=value,asof=asof or app.today().isoformat(),
            source_url='https://example.org/evidence',note='Evidência sintética, com escopo definido para teste.')

    def checks(self):
        self.asset['snapshots'][quality.KIND] = {'data':quality.validate_snapshot(app,self.payload)}
        return {c['key']:c for c in quality.assess(app,self.asset)['checks']}

    def status(self,key):return self.checks()['quality_'+key]['status']

    def test_all_eleven_are_present_and_complete_evidence_passes(self):
        checks=self.checks()
        self.assertEqual(len(checks),11)
        self.assertTrue(all(c['status']=='pass' for c in checks.values()),checks)

    def test_current_roe_cannot_replace_five_annual_observations(self):
        self.asset['snapshots'].pop('issuer_statements')
        self.asset['sector_metrics']={'roe':{'value':40,'asof':app.today().isoformat()}}
        self.assertEqual(self.status('roe5'),'unknown')

    def test_roe_requires_each_year_strictly_above_five(self):
        self.asset['snapshots']['issuer_statements']['data']['annual'][-2]['net_income']=50
        self.assertEqual(self.status('roe5'),'fail')

    def test_roe_needs_previous_equity_and_positive_balance(self):
        rows=self.asset['snapshots']['issuer_statements']['data']['annual']
        rows[0]['equity']=None
        self.assertEqual(self.status('roe5'),'unknown')
        rows[0]['equity']=-1000
        self.assertEqual(self.status('roe5'),'unknown')

    def test_growth_is_five_intervals_and_revenue_or_profit(self):
        for row in self.asset['snapshots']['issuer_statements']['data']['annual']:row['net_income']=100
        self.assertEqual(self.status('growth5'),'pass')
        self.asset['snapshots']['issuer_statements']['data']['annual'].pop(0)
        self.assertEqual(self.status('growth5'),'unknown')

    def test_exactly_five_percent_cagr_does_not_pass_due_to_rounding(self):
        for i,row in enumerate(self.asset['snapshots']['issuer_statements']['data']['annual']):
            row.update(net_income=100*1.05**i,revenue=1000*1.05**i)
        self.assertEqual(self.status('growth5'),'fail')

    def test_one_failed_growth_series_and_one_missing_remain_unknown(self):
        for row in self.asset['snapshots']['issuer_statements']['data']['annual']:row.update(net_income=None,revenue=1000)
        self.assertEqual(self.status('growth5'),'unknown')

    def test_growth_never_stitches_incomplete_currency_series(self):
        data=self.asset['snapshots']['issuer_statements']['data']
        older=data['annual'][:3];data['annual']=data['annual'][3:]
        self.asset['snapshots']['issuer_financials']={'data':{'currency':'USD','years':older,'source_url':'https://example.org/other'},'retrieved_at':app.now()}
        self.assertEqual(self.status('growth5'),'unknown')

    def test_negative_growth_base_does_not_create_a_compound_return(self):
        for row in self.asset['snapshots']['issuer_statements']['data']['annual']:row['revenue']=None
        self.asset['snapshots']['issuer_statements']['data']['annual'][0]['net_income']=-100
        self.assertEqual(self.status('growth5'),'unknown')

    def test_new_complete_correction_cannot_fall_back_to_old_positive_growth(self):
        previous=self.asset['snapshots']['issuer_statements']
        previous['retrieved_at']='2000-01-01T00:00:00+00:00'
        newer=copy.deepcopy(previous['data']['annual'])
        newer[0].update(net_income=-100,revenue=-1000)
        self.asset['snapshots']['issuer_financials']={'data':dict(years=newer,currency='BRL',source_url='https://example.org/corrected'), 'retrieved_at':app.now()}
        self.assertEqual(self.status('growth5'),'unknown')

    def test_corruption_and_obsolete_sector_are_vetoes_even_when_old(self):
        old=(app.today()-timedelta(days=800)).isoformat()
        self.fact('obsolete_sector',True,old);self.fact('corruption_history',True,old)
        self.assertEqual(self.status('innovation'),'fail')
        self.assertEqual(self.status('management'),'fail')

    def test_missing_or_stale_qualitative_evidence_is_not_a_positive(self):
        del self.payload['facts']['obsolete_sector']
        self.assertEqual(self.status('innovation'),'unknown')
        self.fact('blue_chip',True,(app.today()-timedelta(days=800)).isoformat())
        self.assertEqual(self.status('blue_chip'),'unknown')

    def test_only_number_one_leadership_qualifies(self):
        self.fact('leadership',{'rank':2,'scope':'global','metric':'Receita mundial no segmento'})
        self.assertEqual(self.status('leader'),'fail')
        self.payload['facts']['leadership']['value']['rank']=1
        self.assertEqual(self.status('leader'),'pass')

    def test_foundation_is_distinct_from_listing_and_strict_thirty_years(self):
        del self.payload['facts']['founded']
        self.asset['snapshots']['issuer_governance']={'data':{'first_listed':'1900-01-01'}}
        self.assertEqual(self.status('age30'),'unknown')
        with patch.object(app,'today',return_value=date(2026,10,21)):
            # Evidence and anniversary must use the same frozen clock.
            for row in self.payload['facts'].values():row['asof']=app.today().isoformat()
            self.fact('founded','1996-10-21')
            self.assertEqual(self.status('age30'),'fail')
            self.fact('founded','1996-10-20')
            self.assertEqual(self.status('age30'),'pass')

    def test_sector_age_does_not_use_company_age_or_guess_anniversary(self):
        self.fact('sector_origin_year',app.today().year-100)
        self.assertEqual(self.status('sector100'),'unknown')
        self.fact('sector_origin_year',app.today().year-101)
        self.assertEqual(self.status('sector100'),'pass')

    def test_state_or_single_customer_each_reject_independence(self):
        self.fact('state_controlled',True)
        self.assertEqual(self.status('independent'),'fail')
        self.fact('state_controlled',False);self.fact('single_client_concentration',True)
        self.assertEqual(self.status('independent'),'fail')
        self.payload['facts'].pop('single_client_concentration')
        self.assertEqual(self.status('independent'),'unknown')

    def test_dividend_payment_history_has_no_five_percent_yield_requirement(self):
        del self.payload['facts']['dividend_payments']
        self.asset['snapshots']['issuer_dividend_history']={'data':{'years':[{'year':self.end,'dy':1}], 'source_url':'https://example.org/dividends'}}
        self.assertEqual(self.status('dividends'),'pass')
        self.asset['snapshots'].pop('issuer_dividend_history')
        self.asset['income']=[{'amount':500,'date':app.today().isoformat()}]
        self.assertEqual(self.status('dividends'),'unknown')

    def test_debt_is_strict_two_each_year_not_average_and_not_sector_cut(self):
        self.asset['snapshots']['issuer_statements']['data']['annual'][-1].update(debt=300,cash=100,ebitda=100)
        self.assertEqual(self.status('debt5'),'fail')
        self.asset['snapshots']['issuer_statements']['data']['annual'][-1]['debt']=299
        self.assertEqual(self.status('debt5'),'pass')

    def test_negative_ebitda_does_not_pass_as_negative_debt_ratio(self):
        self.asset['snapshots']['issuer_statements']['data']['annual'][-1]['ebitda']=-100
        self.assertEqual(self.status('debt5'),'unknown')
        self.asset['sector_analysis']['profile']='bank'
        self.assertEqual(self.status('debt5'),'na')

    def test_manual_historical_values_override_only_their_fields(self):
        self.payload['annual_metrics']=[dict(date=f'{self.end}-12-31',roe=4,net_debt=None,ebitda=None,source_url='https://example.org/correction')]
        self.assertEqual(self.status('roe5'),'fail')
        self.assertEqual(self.status('debt5'),'pass')

    def test_validation_rejects_unsourced_future_mistyped_or_duplicate_data(self):
        for change in ('url','future','bool','duplicate'):
            bad=copy.deepcopy(self.payload)
            if change=='url':bad['facts']['blue_chip']['source_url']=''
            elif change=='future':bad['facts']['blue_chip']['asof']=(app.today()+timedelta(days=1)).isoformat()
            elif change=='bool':bad['facts']['blue_chip']['value']='yes'
            else:
                row=dict(date=f'{self.end}-12-31',roe=10,net_debt=None,ebitda=None,source_url='https://example.org/year')
                bad['annual_metrics']=[row,row]
            with self.subTest(change=change),self.assertRaises(ValueError):quality.validate_snapshot(app,bad)


class PersistenceTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def test_api_backup_restore_and_overall_study_use_the_same_criteria(self):
        aid=self.asset()
        data={'symbol':'ABCD3.SA','annual_metrics':[], 'facts':{'corruption_history':dict(value=True,asof=self.day,source_url='https://example.org/decision',note='Caso sintético comprovado.')}}
        company_research.action(app,'/api/issuer/quality-facts',{'asset_id':aid,'data':data})
        a=app.state()['assets'][0]
        group=next(g for g in a['company_research']['study']['groups'] if g['key']=='requested')
        self.assertEqual(len(group['checks']),11)
        self.assertEqual(next(c for c in group['checks'] if c['key']=='quality_management')['status'],'fail')
        self.assertEqual(a['company_research']['study']['status'],'review')
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        after=app.state()['assets'][0]
        self.assertEqual(after['company_research']['quality_facts']['data'],data)
        self.assertEqual(after['company_research']['requested_quality'],a['company_research']['requested_quality'])
        bad=copy.deepcopy(backup)
        snap=next(s for s in bad['tables']['snapshots'] if s['kind']==quality.KIND)
        import json
        payload=json.loads(snap['data']) if isinstance(snap['data'],str) else snap['data']
        payload['facts']['corruption_history']['value']='false'
        snap['data']=json.dumps(payload)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)


if __name__=='__main__':unittest.main()
