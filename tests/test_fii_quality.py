"""Six FII criteria: applicability, strict price veto, payout window and peers."""
import copy
from datetime import date,timedelta
import unittest

import fii_quality as quality
import fii_research as fii
import test_app as baseline
from test_fii_research import fixture

app=baseline.app


class CriteriaTests(unittest.TestCase):
    def setUp(self):
        self.asset={'ticker':'TEST11','asset_type':'fii','sector':'FII · Logística','snapshots':{
            'fii_reports':{'data':fixture(),'source':'Fixture','asof':app.today().isoformat(),'retrieved_at':app.now()},
            'quote':{'data':{'price':90},'asof':app.today().isoformat(),'retrieved_at':app.now(),'source':'Fixture'}}}
        self.payload={'symbol':'TEST11','facts':{}}
        for key in quality.BOOL_FIELDS:self.fact(key,key not in ('single_tenant_dependence','single_property_dependence'))
        self.fact('peer_yield',{'fund_yield':10,'mean_yield':9,'peer_count':6,'type':'tijolo','segment':'Logística','window_months':12,'basis':'paid_12m'})
        self.events(49)

    def fact(self,key,value,asof=None):
        self.payload['facts'][key]={'value':value,'asof':asof or app.today().isoformat(),
            'source_url':'https://example.org/manager','note':'Conferência sintética da carteira e das referências.'}

    def events(self,count,kind='RENDIMENTO',estimated=False):
        end=app.today().year*12+app.today().month-1
        rows=[{'date':f'{n//12:04d}-{n%12+1:02d}-15','amount':1,'type':kind,'estimated':estimated} for n in range(end-count,end)]
        self.asset['snapshots']['fii_dividends']={'data':{'items':rows,'source_url':'https://example.org/events'}}

    def result(self,profile='tijolo'):
        self.asset['snapshots'][quality.KIND]={'data':quality.validate_snapshot(app,self.payload)}
        return quality.assess(app,self.asset,profile)

    def status(self,key,profile='tijolo'):
        return next(c for c in self.result(profile)['checks'] if c['key']=='fii_quality_'+key)['status']

    def test_six_checks_have_edit_actions_and_complete_data_passes(self):
        checks=self.result()['checks']
        self.assertEqual(len(checks),6)
        self.assertTrue(all(c['status']=='pass' for c in checks),checks)
        self.assertTrue(all(c['edit_action']=='fii-quality' for c in checks))

    def test_location_cannot_be_inferred_from_vacancy_or_class(self):
        del self.payload['facts']['prime_locations']
        self.assertEqual(self.status('location'),'unknown')

    def test_new_buildings_and_low_maintenance_are_both_required(self):
        self.fact('low_maintenance',False)
        self.assertEqual(self.status('properties'),'fail')
        self.payload['facts'].pop('low_maintenance')
        self.assertEqual(self.status('properties'),'unknown')

    def test_paper_and_fof_do_not_receive_property_or_tenant_requirements(self):
        for profile in ('papel','fof'):
            for key in ('location','properties','dependence'):
                self.assertEqual(self.status(key,profile),'na')
        self.assertEqual(self.status('location','unknown'),'unknown')

    def test_price_cutoffs_are_strict_and_discard_is_distinct(self):
        for pvp,status,discard in ((.999,'pass',False),(1,'fail',False),(1.5,'fail',False),(1.5001,'fail',True)):
            with self.subTest(pvp=pvp):
                self.asset['snapshots']['quote']['data']['price']=pvp*100
                self.assertEqual(self.status('pvp'),status)
                self.assertEqual(self.result()['screening']['discard'],discard)

    def test_stale_price_cannot_discard_or_approve(self):
        self.asset['snapshots']['quote'].update(asof=(app.today()-timedelta(days=8)).isoformat())
        self.asset['snapshots']['quote']['data']['price']=200
        self.assertEqual(self.status('pvp'),'unknown')
        self.assertFalse(self.result()['screening']['discard'])

    def test_negative_nav_is_not_a_discount_and_old_stats_cannot_override(self):
        self.asset['snapshots']['fii_reports']['data']['monthly'][-1]['nav']=-100
        self.asset['snapshots']['statistics']={'data':{'pvp':.5},'asof':app.today().isoformat(),'retrieved_at':app.now()}
        self.assertEqual(self.status('pvp'),'unknown')

    def test_manual_current_pvp_correction_can_be_removed_to_use_market_again(self):
        self.fact('pvp',1.6)
        self.assertTrue(self.result()['screening']['discard'])
        del self.payload['facts']['pvp']
        self.assertFalse(self.result()['screening']['discard'])

    def test_consistency_requires_more_than_forty_eight_confirmed_months(self):
        self.events(48)
        self.assertEqual(self.status('dividends'),'unknown')
        self.events(49)
        self.assertEqual(self.status('dividends'),'pass')

    def test_amortizations_estimates_or_missing_month_do_not_prove_consistency(self):
        self.events(49,'AMORTIZAÇÃO');self.assertEqual(self.status('dividends'),'unknown')
        self.events(49,estimated=True);self.assertEqual(self.status('dividends'),'unknown')
        self.events(49);self.asset['snapshots']['fii_dividends']['data']['items'].pop(25)
        self.assertEqual(self.status('dividends'),'unknown')

    def test_sourced_document_review_can_confirm_history_but_not_exactly_four_years(self):
        self.events(0);today=app.today();cutoff=date(today.year-4,today.month,min(today.day,28))
        last=(today.replace(day=1)-timedelta(days=1)).isoformat()
        self.fact('dividend_record',{'since':(cutoff-timedelta(days=10)).isoformat(),'through':last,'frequency':'monthly','consistent':True})
        self.assertEqual(self.status('dividends'),'pass')
        self.payload['facts']['dividend_record']['value']['since']=date(today.year-4,today.month,today.day).isoformat()
        self.assertEqual(self.status('dividends'),'unknown')
        self.payload['facts']['dividend_record']['value']['consistent']=False
        self.assertEqual(self.status('dividends'),'fail')

    def test_many_properties_do_not_prove_many_tenants(self):
        self.payload['facts'].pop('single_tenant_dependence')
        self.assertEqual(self.status('dependence'),'unknown')
        self.fact('single_tenant_dependence',True)
        self.assertEqual(self.status('dependence'),'fail')

    def test_one_property_with_all_revenue_overrides_a_positive_manual_claim(self):
        self.payload['facts']['single_property_dependence']['asof']=self.asset['snapshots']['fii_reports']['data']['quarterly'][-1]['date']
        self.asset['snapshots']['fii_reports']['data']['quarterly'][-1]['properties'][0]['revenue_share']=1
        self.assertEqual(self.status('dependence'),'fail')

    def test_documented_newer_portfolio_change_supersedes_an_old_mono_property(self):
        self.asset['snapshots']['fii_reports']['data']['quarterly'][-1]['properties'][0]['revenue_share']=1
        self.assertEqual(self.status('dependence'),'pass')

    def test_equal_yield_passes_lower_yield_fails(self):
        self.payload['facts']['peer_yield']['value']['fund_yield']=9
        self.assertEqual(self.status('yield'),'pass')
        self.payload['facts']['peer_yield']['value']['fund_yield']=8.9
        self.assertEqual(self.status('yield'),'fail')

    def test_yield_requires_same_type_segment_current_date_and_two_other_funds(self):
        for field,value in (('type','papel'),('segment','Shoppings'),('peer_count',1)):
            original=self.payload['facts']['peer_yield']['value'][field]
            self.payload['facts']['peer_yield']['value'][field]=value
            self.assertEqual(self.status('yield'),'unknown')
            self.payload['facts']['peer_yield']['value'][field]=original
        self.payload['facts']['peer_yield']['asof']=(app.today()-timedelta(days=32)).isoformat()
        self.assertEqual(self.status('yield'),'unknown')

    def test_monthly_nav_yield_cannot_replace_annual_market_comparison(self):
        del self.payload['facts']['peer_yield']
        self.asset['metrics']={'dy':20}
        self.assertEqual(self.status('yield'),'unknown')

    def test_expired_qualitative_records_become_pending(self):
        self.payload['facts']['prime_locations']['asof']=(app.today()-timedelta(days=181)).isoformat()
        self.assertEqual(self.status('location'),'unknown')

    def test_validation_rejects_wrong_windows_unsourced_future_and_invalid_values(self):
        for edit in ('window','basis','url','future','boolean','pvp','credential'):
            bad=copy.deepcopy(self.payload)
            if edit=='window':bad['facts']['peer_yield']['value']['window_months']=1
            elif edit=='basis':bad['facts']['peer_yield']['value']['basis']='monthly_nav'
            elif edit=='url':bad['facts']['prime_locations']['source_url']=''
            elif edit=='future':bad['facts']['prime_locations']['asof']=(app.today()+timedelta(days=1)).isoformat()
            elif edit=='boolean':bad['facts']['prime_locations']['value']='yes'
            elif edit=='pvp':bad['facts']['pvp']={**bad['facts']['prime_locations'],'value':0}
            else:bad['facts']['prime_locations']['source_url']='https://user:pass@example.org/'
            with self.subTest(edit=edit),self.assertRaises(ValueError):quality.validate_snapshot(app,bad)


class PersistenceTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown

    def test_api_backup_and_discard_label_preserve_the_user_rule(self):
        with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',('TEST11','FII sintético','fii','Logística',0,'Fixture',app.now()))
        aid=app.mutate('/api/assets',{'ticker':'TEST11','asset_type':'fii'})['id']
        data={'symbol':'TEST11','facts':{'pvp':dict(value=1.6,asof=self.day,source_url='https://example.org/price',note='Valor sintético conferido.')}}
        fii.action(app,'/api/fii/quality-facts',{'asset_id':aid,'data':data})
        a=app.state()['assets'][0];study=a['fii_research']['study']
        self.assertTrue(study['screening']['discard'])
        self.assertEqual(study['status'],'review');self.assertIn('Descartado',study['label'])
        group=next(g for g in study['groups'] if g['key']=='requested_fii')
        self.assertEqual(len(group['checks']),6)
        self.assertEqual(sum(c.get('scope')=='price' for c in group['checks']),2)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(app.state()['assets'][0]['fii_research']['quality_facts']['data'],data)
        bad=copy.deepcopy(backup)
        import json
        snap=next(s for s in bad['tables']['snapshots'] if s['kind']==quality.KIND)
        payload=json.loads(snap['data']);payload['facts']['pvp']['value']=-1;snap['data']=json.dumps(payload)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)


if __name__=='__main__':unittest.main()
