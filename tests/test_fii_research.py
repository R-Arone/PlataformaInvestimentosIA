"""Issuer identity, FII applicability, original periods and incomplete public disclosures."""
import copy
from datetime import date,timedelta
import json
import unittest
from unittest.mock import patch

import test_app as baseline
import fii_research as fii
import public_reports as reports
import company_insights
import company_history
import sector_analysis

app=baseline.app


def fixture(symbol='TEST11',segment='Logística'):
    day=app.today();last=day.year*12+day.month-2
    monthly=[]
    for n in range(last-11,last+1):
        monthly.append({'date':f'{n//12:04d}-{n%12+1:02d}-01',**dict.fromkeys(fii.MONTHLY),
            'nav':100,'equity':100_000_000,'shares':1_000_000,'assets':110_000_000,'yield_nav':.008,
            'amortization':0,'obligations':5_000_000,'securitization':0,'property_assets':90_000_000,
            'cri':0,'funds':0,'source_url':'https://example.org/monthly'})
    qlast=day.year*4+(day.month-1)//3-1;y,q=divmod(qlast,4);ref=date(y,(q+1)*3,(31,30,30,31)[q]).isoformat()
    return {'symbol':symbol,'profile':{'cnpj':'12345678000195','name':'Fundo fictício','segment':segment,'mandate':'Renda',
        'management':'Ativa','administrator':'Administrador fictício','isin':'BR'+symbol[:4]+'CTF001','started':'2000-01-01'},'monthly':monthly,
        'quarterly':[{'date':ref,'cash_result':3_000_000,'cash_accumulated':6_000_000,'declared':5_800_000,
            'ipca_share':.8,'igpm_share':.1,'short_contracts':.1,'source_url':'https://example.org/quarter',
            'properties':[{'name':'Galpão A','area':100,'vacancy':.1,'delinquency':0,'revenue_share':.2,'class':'Imóveis para renda acabados'},
                {'name':'Galpão B','area':300,'vacancy':0,'delinquency':.04,'revenue_share':.8,'class':'Imóveis para renda acabados'}],
            'portfolio':[{'type':'FII','issuer':'Fundo A','issuer_cnpj':'11111111000111','name':'A','value':10},
                {'type':'FII','issuer':'Fundo B','issuer_cnpj':'22222222000122','name':'B','value':30}]}],
        'source_url':'https://example.org/cvm'}


class FiiResearchTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown

    def asset(self,segment='Logística',symbol='TEST11'):
        with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',(symbol,'Fundo fictício','fii',segment,0,'Fixture',app.now()))
        aid=app.mutate('/api/assets',{'ticker':symbol,'name':'Fundo fictício','asset_type':'fii'})['id']
        return next(a for a in app.state()['assets'] if a['id']==aid)

    def saved(self,segment='Logística'):
        a=self.asset(segment);d=fixture(segment=segment)
        if 'Papel' in segment:
            for r in d['monthly']:r.update(cri=90_000_000,property_assets=0)
            for r in d['quarterly']:r['properties']=[]
        fii.save(app,a,'fii_reports',d,'Fixture')
        return app.state()['assets'][0]

    def test_complete_properties_use_area_weights_and_do_not_infer_recurring_income(self):
        a=self.saved();v,s,reason=sector_analysis.metric(a,'vacancy',app.age)
        self.assertAlmostEqual(v,2.5)
        self.assertAlmostEqual(sector_analysis.metric(a,'rental_delinquency',app.age)[0],3.2)
        self.assertAlmostEqual(sector_analysis.metric(a,'fund_leverage',app.age)[0],5)
        self.assertIsNone(sector_analysis.metric(a,'distribution_cover',app.age)[0])
        self.assertAlmostEqual(sector_analysis.metric(a,'cash_distribution_cover',app.age)[0],6/5.8)
        keys={c['key'] for g in a['fii_research']['study']['groups'] for c in g['checks']}
        self.assertNotIn('roe',keys);self.assertNotIn('tag_along',keys);self.assertNotIn('net_debt_ebitda',keys)
        self.assertEqual(a['fii_research']['study']['status'],'review')

    def test_paper_and_fof_do_not_require_property_vacancy_or_tenant(self):
        a=self.saved('Papel / recebíveis')
        keys={c['metric'] for c in a['sector_analysis']['checks']}
        self.assertNotIn('vacancy',keys);self.assertNotIn('top_tenant',keys)
        self.assertTrue({'credit_delinquency','top_credit','ltv'}<=keys)
        self.assertNotIn('financial_vacancy',{r['metric'] for r in a['indicator_coverage']})
        fii.action(app,'/api/fii/classification',{'asset_id':a['id'],'data':{'symbol':'TEST11','type':'fof','asof':self.day,'source_url':'https://example.org/regulation'}})
        a=app.state()['assets'][0];keys={c['metric'] for c in a['sector_analysis']['checks']}
        self.assertIn('top_fund',keys);self.assertNotIn('ltv',keys);self.assertNotIn('vacancy',keys)
        self.assertEqual(sector_analysis.metric(a,'top_fund',app.age)[0],75)

    def test_unknown_type_has_no_unverified_property_or_credit_requirements(self):
        a=self.asset('FII');keys={c['metric'] for c in a['sector_analysis']['checks']}
        self.assertNotIn('vacancy',keys);self.assertNotIn('ltv',keys)
        self.assertEqual(a['fii_research']['type'],'unknown')
        self.assertTrue(any(c['key']=='profile_known' and c['status']=='unknown' for g in a['fii_research']['study']['groups'] for c in g['checks']))

    def test_missing_area_or_fraction_does_not_fabricate_zero(self):
        a=self.asset();d=fixture();d['quarterly'][0]['properties'][0]['area']=None;d['monthly'][-1]['securitization']=None
        fii.save(app,a,'fii_reports',d,'Fixture');a=app.state()['assets'][0]
        self.assertIsNone(sector_analysis.metric(a,'vacancy',app.age)[0])
        self.assertIsNone(sector_analysis.metric(a,'fund_leverage',app.age)[0])

    def test_identity_requires_exact_isin_root_unique_cnpj_and_listed_fund(self):
        d={'Codigo_ISIN':'BRTESTCTF001','CNPJ_Fundo_Classe':'12.345.678/0001-95','Mercado_Negociacao_Bolsa':'S','Data_Referencia':self.day,'Versao':'1'}
        self.assertEqual(reports.fii_identity({'ticker':'TEST11'},[d],app.today())[0],'12345678000195')
        for rows in ([{**d,'Codigo_ISIN':'BRABCDCTF001'}],[d,{**d,'CNPJ_Fundo_Classe':'11111111000111'}],[{**d,'Mercado_Negociacao_Bolsa':'N'}]):
            with self.assertRaises(ValueError):reports.fii_identity({'ticker':'TEST11'},rows,app.today())

    def test_partial_query_preserves_old_fields_periods_and_backup_identity(self):
        a=self.saved();d=fixture();d['monthly']=d['monthly'][-1:];d['monthly'][0]['nav']=None;d['quarterly']=[]
        fii.save(app,a,'fii_reports',d,'CVM · parcial');a=app.state()['assets'][0]
        self.assertEqual(len(a['fii_research']['reports']['data']['monthly']),12)
        self.assertEqual(a['fii_research']['reports']['data']['monthly'][-1]['nav'],100)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(backup))
        bad=copy.deepcopy(backup);s=next(s for s in bad['tables']['snapshots'] if s['kind']=='fii_reports');p=json.loads(s['data']);p['symbol']='ABCD11';s['data']=json.dumps(p)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)

    def test_new_month_keeps_explicit_missing_fields_instead_of_erasing_schema(self):
        a=self.saved();d=fixture();d['monthly']=d['monthly'][-1:];d['monthly'][0]['date']=self.day;d['monthly'][0]['nav']=None
        fii.save(app,a,'fii_reports',d,'CVM · parcial');a=app.state()['assets'][0]
        self.assertIsNone(a['fii_research']['reports']['data']['monthly'][-1]['nav'])
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)

    def test_empty_updated_portfolio_does_not_retain_old_concentration(self):
        a=self.saved();d=fixture();d['quarterly'][0]['properties']=[];d['quarterly'][0]['portfolio']=[]
        fii.save(app,a,'fii_reports',d,'CVM · carteira atualizada');a=app.state()['assets'][0]
        self.assertIsNone(sector_analysis.metric(a,'vacancy',app.age)[0])
        self.assertIsNone(sector_analysis.metric(a,'top_fund',app.age)[0])
        self.assertEqual(a['fii_research']['reports']['data']['quarterly'][0]['properties'],[])

    def test_dates_units_urls_and_negative_values_are_rejected(self):
        a=self.asset()
        for edit in (lambda d:d['monthly'][-1].update(yield_nav=12),lambda d:d['monthly'][-1].update(nav=-1),
            lambda d:d['monthly'][-1].update(date=(app.today()+timedelta(days=1)).isoformat()),lambda d:d.update(source_url='javascript:alert(1)')):
            d=fixture();edit(d)
            with self.assertRaises(ValueError):fii.save(app,a,'fii_reports',d,'Fixture')

    def test_amortization_does_not_count_as_monthly_income(self):
        a=self.saved();items=[{'date':r['date'],'type':'AMORTIZAÇÃO','amount':1,'estimated':False} for r in fixture()['monthly']]
        fii.save(app,a,'fii_dividends',{'symbol':'TEST11','items':items,'source_url':'https://example.org/events'},'Fixture')
        study=app.state()['assets'][0]['fii_research']['study'];check=next(c for g in study['groups'] for c in g['checks'] if c['key']=='payments12')
        self.assertEqual(check['status'],'unknown')

    def test_failed_refresh_preserves_existing_informes(self):
        a=self.saved()
        with patch.object(reports,'fetch_fii',side_effect=ValueError('Fonte fora do ar')),patch.object(app,'request_json',side_effect=ValueError('Indisponível')):
            result=fii.refresh(app,a)
        self.assertTrue(result['warnings']);self.assertTrue(app.state()['assets'][0]['fii_research']['reports'])

    def test_fii_news_uses_credit_metrics_and_leaves_study_unchanged(self):
        a=self.saved('Papel / recebíveis');before=a['fii_research']['study'];feed={'fii':{'retrieved_at':app.now(),'headlines':[{'title':'Juros e crédito nos fundos imobiliários','url':'https://example.org/news','published_at':app.now(),'publisher':'Fixture'}]}}
        r=company_insights.news_context(app,a,feed,{})
        self.assertTrue(r['available']);self.assertTrue(r['themes'])
        self.assertIn('credit_delinquency',{m['key'] for t in r['themes'] for m in t['metrics']})
        self.assertEqual(before,app.state()['assets'][0]['fii_research']['study'])

    def test_latest_cvm_revision_is_used_without_mixing_funds(self):
        row={'CNPJ_Fundo_Classe':'12345678000195','Data_Referencia':self.day,'Versao':'1','value':'10'}
        got=reports.selected([row,{**row,'Versao':'2','value':'12'},{**row,'CNPJ_Fundo_Classe':'11111111000111'}],'12345678000195',app.today())
        self.assertEqual(got[self.day][0]['value'],'12')

    def test_cvm_contract_weights_cannot_mix_different_report_revisions(self):
        row={'CNPJ_Fundo_Classe':'12345678000195','Data_Referencia':self.day,'Versao':'1'}
        general={**row,'Codigo_ISIN':'BRTESTCTF001','Mercado_Negociacao_Bolsa':'S','Nome_Fundo_Classe':'Fixture'}
        monthly={'general':[general],'monthly':[],'balance':[]}
        quarterly={'result':[{**row,'Resultado_Trimestral_Liquido_Financeiro':'3'}],
            'contracts':[{**row,'Versao':'2','Percentual_Indexador_Receita_FII_IPCA':'.8'}],'properties':[],'portfolio':[]}
        with patch.object(reports,'tables',side_effect=lambda url,*args,**kwargs:monthly if '/INF_MENSAL/' in url else quarterly):
            d,warnings=reports.fetch_fii({'ticker':'TEST11','name':'Fixture'},app.today())
        self.assertEqual(d['quarterly'][0]['cash_result'],3)
        self.assertIsNone(d['quarterly'][0]['ipca_share'])

    def test_brick_news_maps_credit_to_rental_risk_and_interest_to_obligations(self):
        a=self.saved();feed={'fii':{'retrieved_at':app.now(),'headlines':[{'title':'Juros e crédito nos fundos imobiliários',
            'url':'https://example.org/news','published_at':app.now(),'publisher':'Fixture'}]}}
        themes={r['key']:r for r in company_insights.news_context(app,a,feed,{})['themes']}
        self.assertIn('rental_delinquency',{m['key'] for m in themes['credit']['metrics']})
        self.assertNotIn('credit_delinquency',{m['key'] for m in themes['credit']['metrics']})
        self.assertIn('locatários',themes['credit']['reading'])
        self.assertIn('fund_leverage',{m['key'] for m in themes['rates']['metrics']})

    def test_company_cvm_currency_scale_and_ytd_are_respected(self):
        def r(code,value,start,end,**extra):return {'CNPJ_CIA':'12345678000195','CD_CONTA':code,'VL_CONTA':str(value),'DT_INI_EXERC':start,'DT_FIM_EXERC':end,
            'ORDEM_EXERC':'ÚLTIMO','MOEDA':'REAL','ESCALA_MOEDA':'MIL','VERSAO':'1',**extra}
        y=app.today().year-1
        data={'DRE':[r('3.11',20,f'{y}-01-01',f'{y}-03-31'),r('3.11',50,f'{y}-01-01',f'{y}-06-30')],
              'DFC_MI':[r('6.01',30,f'{y}-01-01',f'{y}-03-31'),r('6.01',70,f'{y}-01-01',f'{y}-06-30'),
                        r('6.02',-10,f'{y}-01-01',f'{y}-03-31'),r('6.02',-25,f'{y}-01-01',f'{y}-06-30')],
              'BPP':[r('2.03',100,'',f'{y}-06-30')]}
        annual,q=reports.parse_company(data,'12345678000195',app.today())
        june=next(row for row in q if row['date']==f'{y}-06-30')
        self.assertEqual(june['net_income'],30_000);self.assertEqual(june['operating_cashflow'],40_000);self.assertEqual(june['equity'],100_000)
        self.assertEqual(june['free_cashflow'],25_000)
        self.assertIsNone(june['ebitda']);self.assertIsNone(june['interest_expense'])
        annual,q=reports.parse_company(data,'11111111000111',app.today());self.assertEqual(q,[])

    def test_refresh_fetches_current_quote_and_fills_dossier_from_cvm(self):
        a=self.asset();d=fixture()
        with patch.object(reports,'fetch_fii',return_value=(d,[])),patch.object(app,'fetch_stock',return_value=('quote',{'price':90},self.day)),\
             patch.object(app,'fetch_fii',side_effect=ValueError('Plano indisponível')),patch('extra_sources.yahoo',return_value={}),\
             patch.object(app,'request_json',return_value={'dividends':[]}):
            result=fii.refresh(app,a)
        self.assertIn('quote',result['received']);self.assertIn('fii_reports',result['received'])
        a=app.state()['assets'][0];self.assertAlmostEqual(a['metrics']['pvp'],.9)
        self.assertEqual(a['fii_research']['reports']['data']['profile']['cnpj'],'12345678000195')

    def test_empty_primary_dividends_attempt_public_fallback_with_unconfirmed_dates(self):
        a=self.saved()
        with patch.object(reports,'fetch_fii',return_value=(fixture(),[])),patch.object(app,'fetch_stock',side_effect=ValueError('Indisponível')),\
             patch.object(app,'fetch_fii',side_effect=ValueError('Indisponível')),patch('extra_sources.yahoo',return_value={}),\
             patch.object(app,'request_json',return_value={'dividends':[]}),patch.object(reports,'market_dividends',return_value=({self.day:1},{},{})):
            result=fii.refresh(app,a)
        self.assertIn('fii_dividends',result['received'])
        event=app.state()['assets'][0]['fii_research']['dividends']['data']['items'][0]
        self.assertTrue(event['estimated']);self.assertEqual(event['amount'],1)
        self.assertTrue(any('Sem eventos históricos' in w for w in result['warnings']))

    def test_announced_future_dividend_does_not_discard_confirmed_history(self):
        a=self.saved();rows=[{'symbol':'TEST11','label':'RENDIMENTO','rate':1,'paymentDate':self.day},
            {'symbol':'TEST11','label':'RENDIMENTO','rate':2,'paymentDate':(app.today()+timedelta(days=5)).isoformat()}]
        with patch.object(reports,'fetch_fii',return_value=(fixture(),[])),patch.object(app,'fetch_stock',side_effect=ValueError('Indisponível')),\
             patch.object(app,'fetch_fii',side_effect=ValueError('Indisponível')),patch('extra_sources.yahoo',return_value={}),\
             patch.object(app,'request_json',return_value={'dividends':rows}),patch.object(reports,'market_dividends') as fallback:
            fii.refresh(app,a)
        fallback.assert_not_called()
        events=app.state()['assets'][0]['fii_research']['dividends']['data']['items']
        self.assertEqual(events,[{'date':self.day,'type':'RENDIMENTO','amount':1,'estimated':False}])

    def test_composition_overrides_misleading_cadastral_sector(self):
        d=fixture(segment='Logística')
        for row in d['monthly']:row.update(cri=90_000_000,property_assets=0)
        self.assertEqual(fii.subtype({'snapshots':{'fii_reports':{'data':d}}}),'papel')

    def test_securitizer_is_not_inferred_as_largest_credit_debtor(self):
        a=self.asset('Papel');d=fixture();d['quarterly'][0]['portfolio']=[{'type':'CRI','issuer':'Securitizadora X','issuer_cnpj':'11111111000111','name':'Operação A','value':100}]
        fii.save(app,a,'fii_reports',d,'Fixture');a=app.state()['assets'][0]
        self.assertIsNone(sector_analysis.metric(a,'top_credit',app.age)[0])

    def test_company_profile_falls_back_to_verified_b3_identity(self):
        a={'ticker':'ABCD3','asset_type':'stock','name':'Fixture','sector':'Indústria'}
        detail={'issuingCompany':'ABCD','code':'ABCD3','cnpj':'12345678000195','companyName':'Companhia fictícia','activity':'Equipamentos',
                'industryClassification':'Bens industriais','otherCodes':[]}
        search={'results':[{'issuingCompany':'ABCD','status':'A','codeCVM':'1'}]}
        with patch.object(company_history,'brapi',side_effect=ValueError('Fonte indisponível')),patch.object(app,'request_json',side_effect=[search,detail]):
            d=company_history.fetch_profile(app,a)
        self.assertEqual(d['cnpj'],'12345678000195');self.assertEqual(d['description'],'Equipamentos')
        with patch.object(company_history,'brapi',side_effect=ValueError('Fonte indisponível')),patch.object(app,'request_json',side_effect=[search,{**detail,'code':'ABCD4'}]):
            with self.assertRaises(ValueError):company_history.fetch_profile(app,a)

if __name__=='__main__':unittest.main()
