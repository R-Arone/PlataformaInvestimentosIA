"""Viability coverage, period-consistent ratios, governance identity and market drivers."""
import base64
import copy
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

import test_app as baseline
from aporte_brasil.company import company_history as history
from aporte_brasil.company import company_insights as insights
from aporte_brasil.company import company_research as research
from aporte_brasil.portfolio import sector_analysis
from aporte_brasil.ai import market_ai

app = baseline.app


class CompanyInsightsTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    complete = baseline.AppTests.complete

    def row(self, ref, **values):
        return {'date': ref, **dict.fromkeys(insights.FIELDS), **values}

    def statements(self):
        annual = [self.row(f'{y}-12-31', net_income=100, revenue=1000, equity=500,
            debt=200, cash=100, ebitda=150, ebit=120, interest_expense=-20,
            gross_profit=300, cost_of_revenue=-700, operating_cashflow=120, free_cashflow=40,
            current_assets=400, current_liabilities=200, inventory=70) for y in range(app.today().year-10, app.today().year)]
        last = app.today().year*4+(app.today().month-1)//3-1
        q = []
        for n in range(last-4, last+1):
            y, quarter = divmod(n, 4)
            ref = date(y, (quarter+1)*3, (31,30,30,31)[quarter]).isoformat()
            q.append(self.row(ref, net_income=25, revenue=250, gross_profit=75, cost_of_revenue=-175,
                equity=500, debt=200, cash=100, ebitda=40, ebit=30, interest_expense=-5,
                current_assets=400, current_liabilities=200, inventory=70))
        return {'symbol':'ABCD3.SA', 'currency':'BRL', 'annual':annual, 'quarterly':q,
            'source_url':'https://example.org/income', 'sources':{'income-statement':'https://example.org/income','balance-sheet':'https://example.org/balance','cash-flow':'https://example.org/cash'}}

    def governance(self, **values):
        return {'symbol':'ABCD3.SA','segment':'Novo Mercado','tag_along':100,'asof':self.day,'first_listed':'2000-01-01',
            'source_url':'https://example.org/statute','rule_url':insights.B3_RULE,'method':'Direito fictício desta classe confirmado no estatuto.',**values}

    def company(self, sector='Energia elétrica'):
        aid = self.asset(sector=sector); self.complete(aid)
        with app.connect() as c: app.write_cache(c,'issuer_auto',False)
        a = app.state()['assets'][0]
        history.save(app,a,'issuer_statements',insights.validate_snapshot(app,'issuer_statements',self.statements()),'Fixture')
        history.save(app,a,'issuer_governance',insights.validate_snapshot(app,'issuer_governance',self.governance()),'Fixture')
        return aid

    def test_statement_ratios_use_four_isolated_quarters_and_matching_balance(self):
        d=self.statements(); metrics=insights.derived_metrics({'data':d})
        last=d['quarterly'][-1]['date']
        self.assertEqual(metrics['roe']['asof'],last)
        self.assertEqual(metrics['roe']['value'],20)
        self.assertEqual(metrics['net_debt_ebitda']['value'],.625)
        self.assertEqual(metrics['current_ratio']['value'],2)
        self.assertEqual(metrics['gross_margin']['value'],30)
        self.assertEqual(metrics['interest_coverage']['value'],6)
        self.assertAlmostEqual(metrics['inventory_days']['value'],36.5)
        # Annual cash is not silently converted into a quarterly TTM.
        self.assertEqual(metrics['operating_cashflow']['asof'],d['annual'][-1]['date'])
        d['quarterly'].pop(2)
        metrics=insights.derived_metrics({'data':d})
        self.assertNotEqual(metrics['roe']['asof'],last)
        self.assertEqual(metrics['debt_equity']['asof'],last)

    def test_missing_interest_is_not_replaced_by_financial_expense_or_zero(self):
        d=self.statements()
        for r in d['annual']+d['quarterly']: r['interest_expense']=None
        self.assertNotIn('interest_coverage',insights.derived_metrics({'data':d}))
        balance=insights._balance({'loansAndFinancing':100,'longTermLoansAndFinancing':200,'leaseFinancing':50,'longTermLeaseFinancing':80,'cash':10,'shortTermInvestments':5})
        self.assertEqual(balance['debt'],300)
        self.assertEqual(balance['cash'],15)

    def test_viability_never_awards_positive_seal_with_missing_sector_data(self):
        self.company(); a=app.state()['assets'][0]; v=a['company_research']['viability']
        self.assertEqual(next(c for c in v['checks'] if c['key']=='profit10')['status'],'pass')
        self.assertEqual(next(c for c in v['checks'] if c['key']=='leverage5')['status'],'pass')
        self.assertEqual(v['status'],'incomplete') # WACC / current cash still need evidence.
        self.assertGreater(v['counts']['unknown'],0)
        self.assertNotIn('_statement_metrics',a)
        before=copy.deepcopy(v)
        research.action(app,'/api/issuer/opinion',{'asset_id':a['id'],'data':{'origin':'manual','title':'Opinião fictícia','text':'Ótima empresa','author':'Autor fictício','date':self.day,'url':'https://example.org/opinion'}})
        self.assertEqual(app.state()['assets'][0]['company_research']['viability'],before)

    def test_a_failed_year_overrides_missing_years_and_banks_use_prudential_checks(self):
        aid=self.company(); d=self.statements(); d['annual']=d['annual'][-5:]; d['annual'][0]['net_income']=0
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        v=app.state()['assets'][0]['company_research']['viability']
        self.assertEqual(v['status'],'review')
        with app.connect() as c: c.execute("UPDATE assets SET sector='Bancos',financial=1 WHERE id=?",(aid,))
        v=app.state()['assets'][0]['company_research']['viability']
        self.assertNotIn('leverage5',[c['key'] for c in v['checks']])
        self.assertIn('Qualidade do crédito',[r['title'] for r in app.state()['assets'][0]['company_research']['sector_focus']])

    def test_five_year_leverage_uses_configured_sector_limit_and_positive_ebitda(self):
        aid=self.company(); app.mutate('/api/settings',{'sector_rules':{'utility':{'net_debt_ebitda':.5}}})
        c=next(c for c in app.state()['assets'][0]['company_research']['viability']['checks'] if c['key']=='leverage5')
        self.assertEqual(c['status'],'fail'); self.assertIn('0,5',c['label'])
        d=self.statements(); d['annual'][-1]['ebitda']=0
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        self.assertIn('4 de 5',next(c for c in app.state()['assets'][0]['company_research']['viability']['checks'] if c['key']=='leverage5')['detail'])

    def test_governance_checks_exact_ticker_and_cnpj_without_guessing_preferred_rights(self):
        aid=self.asset(); a=app.state()['assets'][0]
        listed={'issuingCompany':'ABCD','status':'A','codeCVM':'123','cnpj':'12345678000199','dateListing':'01/01/2000'}
        detail={'issuingCompany':'ABCD','cnpj':listed['cnpj'],'market':'NOVO MERCADO','code':'ABCD3','otherCodes':[]}
        with patch.object(app,'request_json',side_effect=[{'results':[listed]},detail]):
            d=insights.fetch_governance(app,a,{'cnpj':listed['cnpj']})
        self.assertEqual(d['tag_along'],100)
        with patch.object(app,'request_json',side_effect=[{'results':[listed]},json.dumps(detail)]):
            self.assertEqual(insights.fetch_governance(app,a,{'cnpj':listed['cnpj']})['tag_along'],100)
        a={**a,'ticker':'ABCD4'}; detail={**detail,'code':'ABCD4','market':'NIVEL 1'}
        with patch.object(app,'request_json',side_effect=[{'results':[listed]},detail]):
            self.assertIsNone(insights.fetch_governance(app,a,{'cnpj':listed['cnpj']})['tag_along'])
        with patch.object(app,'request_json',side_effect=[{'results':[listed]},detail]),self.assertRaises(ValueError):
            insights.fetch_governance(app,a,{'cnpj':'99999999000199'})

    def test_public_partial_statements_preserve_old_periods_but_manual_blanks_can_clear(self):
        aid=self.company(); a=app.state()['assets'][0]; d=self.statements(); d['annual']=d['annual'][-1:];d['annual'][0]['cash']=None
        history.save(app,a,'issuer_statements',d,'Consulta pública · Fixture')
        saved=app.state()['assets'][0]['company_research']['statements']['data']
        self.assertEqual(len(saved['annual']),10);self.assertEqual(saved['annual'][-1]['cash'],100)
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        saved=app.state()['assets'][0]['company_research']['statements']['data']
        self.assertEqual(len(saved['annual']),1);self.assertIsNone(saved['annual'][0]['cash'])

    def test_invalid_snapshot_dates_units_and_symbols_fail_backup_restore(self):
        self.company()
        with app.connect() as c: backup=app.export_data(c)
        for kind,field,v in [('issuer_statements','symbol','OTHER3.SA'),('issuer_governance','tag_along',101),('issuer_governance','asof',(app.today()+timedelta(days=1)).isoformat())]:
            bad=copy.deepcopy(backup);row=next(s for s in bad['tables']['snapshots'] if s['kind']==kind)
            d=json.loads(row['data']);d[field]=v;row['data']=json.dumps(d)
            with self.assertRaises(ValueError):app.mutate('/api/import',bad)
        self.assertEqual(app.state()['assets'][0]['ticker'],'ABCD3')

    def test_fred_series_identity_dates_and_monthly_average_are_explicit(self):
        day=date(2026,10,8)
        with patch.object(insights,'request_text',return_value='observation_date,PIORECRUSDM\n2026-06-01,110\n2026-07-01,100\n2026-10-01,999\n2027-01-01,1000\n'):
            d=insights.fred_observation('iron',day)
        self.assertEqual(d['current'],100);self.assertEqual(d['asof'],'2026-07-01');self.assertEqual(d['frequency'],'monthly')
        with patch.object(insights,'request_text',return_value='observation_date,WRONG\n2026-07-01,100\n'),self.assertRaises(ValueError):insights.fred_observation('iron',day)

    def test_failed_macro_lookup_preserves_old_observations_and_flags_stale_values(self):
        self.company(sector='Mineração');a=app.state()['assets'][0]
        prev=(app.today()-timedelta(days=160)).isoformat(); ref=(app.today()-timedelta(days=130)).isoformat()
        payload={'symbol':'ABCD3.SA','observations':{'iron':{'current':100,'previous':110,'asof':ref,'previous_asof':prev,'frequency':'monthly','unit':'US$/tonelada','source':'FMI via FRED','source_url':'https://fred.stlouisfed.org/series/PIORECRUSDM'}},'warnings':[],'source_url':'https://example.org/context'}
        history.save(app,a,'issuer_drivers',insights.validate_snapshot(app,'issuer_drivers',payload),'Fixture')
        a=app.state()['assets'][0]
        with patch.object(insights.market_outlook,'fetch_context',return_value={'observations':{},'errors':['BCB indisponível']}),patch.object(insights,'fred_observation',side_effect=ValueError('FRED indisponível')):
            refreshed=insights.fetch_drivers(app,a)
        self.assertEqual(refreshed['observations'],payload['observations']);self.assertTrue(refreshed['warnings'])
        row=next(r for r in a['company_research']['drivers']['rows'] if r['key']=='iron')
        self.assertFalse(row['fresh']);self.assertEqual(row['direction'],'unknown')
        self.assertIn('produtores',row['explanation'])

    def test_dossier_refresh_also_fetches_current_metrics_and_uses_fresh_statistics_date(self):
        aid=self.asset();a=app.state()['assets'][0]
        def fetch(a,ep,token):
            return ('financial',{'roe':15},'') if ep=='financial-data' else ('statistics',{'pvp':1.5},self.day) if ep=='statistics' else ('quote',{'price':20},self.day)
        with patch.object(app,'fetch_stock',side_effect=fetch),patch('aporte_brasil.company.public_fundamentals.fetch_detail',side_effect=ValueError('Sem cobertura')):
            result=history.refresh_current(app,a)
        a=app.state()['assets'][0]
        self.assertIn('financial',result['received']);self.assertEqual(a['sector_metrics']['roe']['value'],15)
        self.assertEqual(a['sector_metrics']['roe']['asof'],self.day)

    def test_sector_selection_and_operational_metrics_have_sources_and_do_not_change_score(self):
        aid=self.company(sector='Comércio');a=app.state()['assets'][0]
        self.assertIn('same_store_sales',[r['metric'] for r in a['company_research']['sector_focus']])
        self.assertIn('same_store_sales',[r['metric'] for r in a['indicator_coverage']])
        before=a['company_research']['viability']
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','source':'Relatório fictício','asof':self.day,'same_store_sales':8})
        a=app.state()['assets'][0]
        self.assertEqual(next(r for r in a['company_research']['sector_focus'] if r['metric']=='same_store_sales')['value'],8)
        self.assertEqual(a['company_research']['viability'],before)

    def test_explicit_refresh_reuses_statements_for_annual_and_quarterly_history(self):
        aid=self.asset();a=app.state()['assets'][0]
        with patch.object(history,'refresh_current',return_value={'received':[],'warnings':[]}),patch.object(insights,'fetch_statements',return_value=(self.statements(),[])),patch.object(history,'fetch_profile',side_effect=ValueError('Sem perfil')),patch.object(history,'fetch_market',side_effect=ValueError('Sem negociação')),patch.object(insights,'fetch_governance',side_effect=ValueError('Sem B3')),patch.object(history,'fetch_quarters',side_effect=AssertionError('Não consultar novamente')),patch.object(research,'fetch_annual',side_effect=AssertionError('Não consultar novamente')):
            result=research.action(app,'/api/issuer/history',{'asset_id':aid})
        self.assertIn('issuer_financials',result['received']);self.assertIn('issuer_quarters',result['received'])
        a=app.state()['assets'][0]
        self.assertEqual(len(a['company_research']['annual']['years']),10)
        self.assertEqual(len(a['company_research']['quarterly']['data']['quarters']),5)

    def test_exact_year_end_quarter_balance_can_fill_failed_annual_balance(self):
        aid=self.asset();a=app.state()['assets'][0];ref=f'{app.today().year-1}-12-31'
        def read(app,a,ep,**params):
            period=params['period']; kind='yearly' if period=='annual' else 'quarterly'
            if ep=='balance-sheet' and period=='annual':raise ValueError('Limite da fonte')
            r={'endDate':ref,'type':kind}
            if ep=='income-statement':r.update(netIncome=100,totalRevenue=1000,cleanEbitda=150)
            elif ep=='balance-sheet':r.update(loansAndFinancing=100,longTermLoansAndFinancing=200,cash=50,shortTermInvestments=10,shareholdersEquity=500)
            else:r.update(operatingCashFlow=120,freeCashFlow=80)
            return [r],f'https://example.org/{ep}?period={period}'
        d,warnings=insights.fetch_statements(app,a,read)
        self.assertEqual(d['annual'][0]['debt'],300);self.assertEqual(d['annual'][0]['cash'],60)
        self.assertIn('period=annual',d['source_url']);self.assertTrue(warnings)

    def test_manual_annual_correction_takes_precedence_over_older_statement_income(self):
        aid=self.company();annual={'symbol':'ABCD3.SA','currency':'BRL','source_url':'https://example.org/correction',
            'years':[{'date':self.statements()['annual'][-1]['date'],'net_income':-100,'revenue':1000,'operating_cashflow':120,'free_cashflow':80}]}
        research.action(app,'/api/issuer/financials',{'asset_id':aid,'data':annual})
        check=next(c for c in app.state()['assets'][0]['company_research']['viability']['checks'] if c['key']=='profit10')
        self.assertEqual(check['status'],'fail');self.assertEqual(check['source_url'],annual['source_url'])
        self.assertIn('Lucro não positivo',check['detail'])

    def test_observed_falls_explain_lower_rates_and_import_costs(self):
        aid=self.company();a=app.state()['assets'][0];ref=(app.today()-timedelta(days=1)).isoformat();prev=(app.today()-timedelta(days=31)).isoformat()
        def obs(current,previous,unit):return {'current':current,'previous':previous,'asof':ref,'previous_asof':prev,'unit':unit,'frequency':'daily','source':'Fixture','source_url':'https://example.org/series'}
        history.save(app,a,'issuer_exposure',{'symbol':'ABCD3.SA','usd_role':'importer','commodities':[],'asof':ref,'source_url':'https://example.org/exposure','note':'Exemplo fictício.'},'Fixture')
        history.save(app,a,'issuer_drivers',{'symbol':'ABCD3.SA','observations':{'rates':obs(10,12,'% a.a.'),'usd':obs(4,5,'R$/US$')},'warnings':[],'source_url':'https://example.org/context'},'Fixture')
        rows=app.state()['assets'][0]['company_research']['drivers']['rows']
        self.assertIn('Juros menores',rows[0]['explanation']);self.assertIn('baratear',rows[1]['explanation'])
        bad={'symbol':'ABCD3.SA','usd_role':{},'commodities':[{}],'asof':ref,'source_url':'https://example.org/exposure','note':'Exemplo.'}
        with self.assertRaises(ValueError):insights.validate_snapshot(app,'issuer_exposure',bad)

    def study_checks(self):
        return {c['key']:c for g in app.state()['assets'][0]['company_research']['study']['groups'] for c in g['checks']}

    def test_unified_study_includes_original_history_cash_sector_and_separate_price(self):
        self.company(); study=app.state()['assets'][0]['company_research']['study']; checks=self.study_checks()
        self.assertGreaterEqual(study['total'],20)
        self.assertEqual(len(checks),sum(len(g['checks']) for g in study['groups']))
        for key in ('quarterly_profit','growth_revenue','growth_net_income','profit10','leverage5','tag_along','cash5','free_cash_last','cash_profit','payout_covered','sector_interest_coverage_health','sector_roic_health','sector_pe_valuation'):
            self.assertIn(key,checks)
        self.assertEqual(checks['cash5']['status'],'pass');self.assertEqual(checks['cash_profit']['status'],'pass')
        self.assertEqual(checks['cash_profit']['source_url'],'https://example.org/cash')
        quality=[c for g in study['groups'] if g['key']!='price' for c in g['checks'] if c['status']!='na']
        self.assertEqual(study['total'],len(quality))
        self.assertEqual(study['counts']['unknown'],sum(c['status']=='unknown' for c in quality))
        self.assertGreater(study['price_counts']['unknown'],0)

    def test_cash_checks_require_all_annual_periods_and_matching_profit(self):
        aid=self.company();d=self.statements()
        # Missing annual cash may not be filled with a quarterly balance or current ratio.
        d['annual'][-2]['operating_cashflow']=None
        d['annual'][-1]['free_cashflow']=-40;d['annual'][-1]['net_income']=0
        research.action(app,'/api/issuer/statements',{'asset_id':aid,'data':d})
        checks=self.study_checks()
        self.assertEqual(checks['cash5']['status'],'unknown')
        self.assertEqual(checks['free_cash_last']['status'],'fail')
        self.assertEqual(checks['cash_profit']['status'],'unknown')
        self.assertIn('expansão',checks['free_cash_last']['detail'])
        self.assertEqual(app.state()['assets'][0]['company_research']['study']['status'],'review')

    def test_bank_study_uses_capital_and_credit_without_generic_cash_or_debt_filters(self):
        self.company('Bancos'); checks=self.study_checks()
        self.assertEqual(checks['debt_equity']['status'],'na')
        for key in ('cash5','cash_profit','free_cash_last','leverage5'):self.assertNotIn(key,checks)
        for key in ('sector_basel_health','sector_npl90_health','sector_coverage_health'):self.assertIn(key,checks)
        self.assertGreaterEqual(len(app.state()['assets'][0]['company_research']['sector_focus']),5)

    def test_configured_sector_cut_and_price_failure_keep_distinct_meanings(self):
        aid=self.company();app.mutate('/api/settings',{'sector_rules':{'utility':{'debt_equity':.1}}})
        checks=self.study_checks()
        self.assertEqual(checks['debt_equity']['status'],'pass')
        self.assertEqual(checks['sector_debt_equity_health']['status'],'fail')
        a=app.state()['assets'][0]
        synthetic=copy.deepcopy(a)
        for c in synthetic['company_research']['buy_hold']['checks']:c['status']='pass'
        for c in synthetic['company_research']['viability']['checks']:c['status']='pass'
        for c in synthetic['company_research']['requested_quality']['checks']:c['status']='pass'
        for c in synthetic['sector_analysis']['checks']:c['status']='fail' if c['group']!='health' else 'pass'
        with patch.object(sector_analysis,'metric',return_value=(20,{'asof':self.day},'')):
            study=insights.complete_study(app,synthetic)
        self.assertEqual(study['status'],'within');self.assertGreater(study['price_counts']['fail'],0)

    def test_payout_requires_recent_data_and_does_not_turn_missing_values_into_zero(self):
        aid=self.company();self.assertEqual(self.study_checks()['payout_covered']['status'],'unknown')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','source':'Fixture','asof':self.day,'payout':120})
        self.assertEqual(self.study_checks()['payout_covered']['status'],'fail')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','source':'Fixture','asof':(app.today()-timedelta(days=181)).isoformat(),'payout':80})
        # A dated old observation cannot make a current criterion pass.
        with app.connect() as c:c.execute("DELETE FROM snapshots WHERE asset_id=? AND kind='risk' AND asof=?",(aid,self.day))
        self.assertEqual(self.study_checks()['payout_covered']['status'],'unknown')

    def news_fixture(self):
        stamp=app.now()
        return {'profile':'utility','retrieved_at':stamp,'sources':[],'errors':[],'method':'Fixture',
            'headlines':[{'title':'Juros e tarifa de energia · notícia fictícia','url':'https://example.org/energy-news','publisher':'Veículo fictício','published_at':stamp}]}

    def test_news_themes_connect_to_metrics_without_changing_the_accounting_checklist(self):
        self.company();before=copy.deepcopy(app.state()['assets'][0]['company_research']['study'])
        report=self.news_fixture()
        with app.connect() as c:
            app.write_cache(c,'news_reports',{'utility':report})
            app.write_cache(c,'ai_sentiment',{'utility':{'input_hash':market_ai.fingerprint(report),'analyzed_at':app.now(),'tone':'positive','items':report['headlines'],'score':.8}})
        a=app.state()['assets'][0]; context=a['company_research']['news_context']
        self.assertEqual(a['company_research']['study'],before)
        self.assertEqual([s['profile'] for s in context['sections']],['utility','general'])
        self.assertEqual({t['key'] for t in context['themes']},{'rates','regulation'})
        rate=next(t for t in context['themes'] if t['key']=='rates')
        self.assertIn('interest_coverage',[m['key'] for m in rate['metrics']])
        self.assertFalse(context['sections'][0]['sentiment']['stale'])
        report['headlines'][0]['title']='Outra notícia fictícia de juros'
        with app.connect() as c:app.write_cache(c,'news_reports',{'utility':report})
        self.assertTrue(app.state()['assets'][0]['company_research']['news_context']['sections'][0]['sentiment']['stale'])

    def test_news_excludes_future_naive_old_headlines_and_foreign_brazilian_tones(self):
        self.company();a=app.state()['assets'][0];report=self.news_fixture()
        for ref in ((app.today()-timedelta(days=8)).isoformat()+'T12:00:00+00:00',
                    (app.today()+timedelta(days=1)).isoformat()+'T12:00:00+00:00',self.day+'T12:00:00'):
            report['headlines'].append({**report['headlines'][0],'url':'https://example.org/'+ref,'published_at':ref})
        report['headlines'].append(dict(report['headlines'][0]))
        report['retrieved_at']=(app.today()-timedelta(days=3)).isoformat()+'T12:00:00+00:00'
        context=insights.news_context(app,a,{'utility':report},{'utility':{'tone':'positive','stale':False}})
        self.assertEqual(len(context['sections'][0]['items']),1)
        self.assertTrue(context['sections'][0]['sentiment']['stale'])
        for typ in ('foreign','global_stock'):
            foreign=insights.news_context(app,{**a,'asset_type':typ},{'utility':report},{'utility':{'tone':'positive'}})
            self.assertFalse(foreign['available']);self.assertEqual(foreign['sections'],[])

    def test_shared_market_headline_does_not_invalidate_sector_or_market_sentiment(self):
        self.company();a=app.state()['assets'][0];report=self.news_fixture()
        context=insights.news_context(app,a,{'utility':report,'general':{**report,'profile':'general'}},
            {p:{'tone':'neutral','stale':False} for p in ('utility','general')})
        self.assertTrue(all(len(s['items'])==1 for s in context['sections']))
        self.assertTrue(all(not s['sentiment']['stale'] for s in context['sections']))
        self.assertEqual(len(context['themes'][0]['items']),1)

    def test_news_monitoring_uses_the_company_business_model(self):
        self.company('Bancos');a=app.state()['assets'][0];report=self.news_fixture()
        report['headlines'][0]['title']='Petróleo, dólar e risco de crédito · exemplo fictício'
        context=insights.news_context(app,a,{'bank':report},{})
        keys={m['key'] for t in context['themes'] for m in t['metrics']}
        self.assertIn('npl90',keys)
        self.assertTrue(keys.isdisjoint({'production_growth','gross_margin','net_debt_ebitda','free_cashflow'}))
        self.assertIn('carteira',next(t for t in context['themes'] if t['key']=='commodities')['reading'])

    def test_news_themes_use_word_boundaries_instead_of_matching_inside_unrelated_words(self):
        self.company();a=app.state()['assets'][0];report=self.news_fixture()
        report['headlines'][0]['title']='Sobra de energia abre espaço para processamento de dados'
        context=insights.news_context(app,a,{'utility':report},{})
        self.assertFalse(context['themes'])
        report['headlines'][0]['title']='Preços de aço e minério mudam no mercado'
        context=insights.news_context(app,a,{'utility':report},{})
        self.assertEqual([t['key'] for t in context['themes']],['commodities'])


if __name__=='__main__':unittest.main()
