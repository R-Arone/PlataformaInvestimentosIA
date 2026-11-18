"""Linked issuer research never substitutes an underlying price for a BRL receipt."""
import copy
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_app as baseline
from test_stock_fundamentals import financials, profile
from test_us_market import chart
from test_factor_analysis import fixture as factor_fixture
import stock_fundamentals as sf
import company_history
import company_research
import company_batch
import factor_analysis
app=baseline.app


class BdrResearchTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown

    def add(self,linked=True,**extra):
        link=dict(symbol='AAPL',market='US',currency='USD',source_url='https://example.org/programa-bdr',asof=self.day)
        body=dict(ticker='AAPL34',asset_type='bdr',name='AAPL34',sector='Tecnologia',auto_sector=True,
                  **({'bdr_listing':link} if linked else {}))
        return app.mutate('/api/assets',{**body,**extra})['id']

    def asset(self,aid):
        return next(a for a in app.state()['assets'] if a['id']==aid)

    def prepare(self):
        aid=self.add(opening=dict(quantity=12,average=40,date=self.day,institution='Teste',confirmed=True))
        with app.connect() as c:app.add_snapshot(c,aid,'quote',dict(price=60),'Teste B3',self.day)
        before=self.asset(aid)
        with patch.object(app,'request_json',return_value=chart()),patch.object(sf,'lookup',return_value=profile()),patch.object(sf,'fetch',return_value=financials()):
            self.assertEqual(sf.refresh_asset(app,before,True),[])
        return aid,before

    def test_native_metrics_quality_and_factors_preserve_brl_position(self):
        aid,before=self.prepare();a=self.asset(aid)
        self.assertEqual(a['metrics']['price'],60)
        self.assertEqual(a['metrics']['pe'],25)
        self.assertEqual(a['sector_metrics']['eps']['currency'],'USD')
        self.assertEqual(a['bdr']['quote']['data']['price'],100)
        self.assertEqual(a['value'],720)
        self.assertEqual(a['position']['average'],40)
        self.assertEqual(a['trades'],before['trades'])
        self.assertEqual(a['sector_analysis']['profile'],'technology')
        self.assertNotIn('Selic',json.dumps(a['sector_analysis']['checks']))
        self.assertEqual(company_history.symbol(a),'AAPL')
        self.assertTrue(a['company_research']['factor_analysis']['supported'])
        self.assertEqual(a['company_research']['factor_analysis']['currency'],'USD')
        self.assertIn('fundamental_model',a['company_research'])
        self.assertEqual(company_batch.validate(app,dict(asset_ids=[aid],years=5,refresh=False,use_ai=False))['asset_ids'],[aid])

    def test_manual_annuals_assumptions_and_evidence_use_linked_issuer(self):
        aid,_=self.prepare()
        data=dict(symbol='AAPL',currency='USD',years=[dict(date='2025-12-31',net_income=10,revenue=80,operating_cashflow=20,free_cashflow=8)],source_url='https://example.org/annual')
        company_research.action(app,'/api/issuer/financials',dict(asset_id=aid,data=data))
        company_research.action(app,'/api/issuer/model',dict(asset_id=aid,parameters=dict(cost_of_equity=12,long_growth=3,sustainable_roe=15,revenue_shock=-20,variable_cost_share=70,rate_shock=3,floating_debt_share=50)))
        self.assertEqual(self.asset(aid)['company_research']['annual']['symbol'],'AAPL')
        body=dict(symbol='AAPL',facts={},annual_metrics=[])
        company_research.action(app,'/api/issuer/quality-facts',dict(asset_id=aid,data=body))
        app.mutate('/api/stocks/metrics',dict(asset_id=aid,values=dict(roe=22),currency='USD',asof=self.day,source='Relatório'))
        self.assertEqual(self.asset(aid)['metrics']['roe'],22)

    def test_unlinked_legacy_bdr_remains_usable_and_can_be_linked(self):
        aid=self.add(False);a=self.asset(aid)
        self.assertNotIn('company_research',a)
        self.assertEqual(a['sector_analysis']['profile'],'foreign')
        with self.assertRaisesRegex(ValueError,'Vincule'):company_research.asset(app,aid)
        self.add(id=aid)
        self.assertIn('company_research',self.asset(aid))

    def test_link_is_immutable_but_source_can_be_reconfirmed(self):
        aid=self.add();link=self.asset(aid)['bdr']['listing']
        for key,bad in [('symbol','MSFT'),('currency','EUR'),('market','XETRA')]:
            with self.assertRaises(ValueError):self.add(id=aid,bdr_listing={**link,key:bad})
        self.add(id=aid,bdr_listing={**link,'source_url':'https://example.org/updated'})
        self.assertEqual(self.asset(aid)['bdr']['listing']['symbol'],'AAPL')
        with self.assertRaises(ValueError):app.mutate('/api/assets',dict(id=aid,ticker='AAPL34',asset_type='foreign',name='X',sector='Tecnologia'))

    def test_backup_roundtrip_and_wrong_issuer_rejection(self):
        aid,_=self.prepare()
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(backup))
        self.assertEqual(self.asset(aid)['metrics']['pe'],25)
        for kind in ('stock_financials','bdr_underlying_quote'):
            bad=copy.deepcopy(backup)
            row=next(s for s in bad['tables']['snapshots'] if s['kind']==kind)
            data=json.loads(row['data']);data['symbol']='MSFT';row['data']=json.dumps(data)
            with self.assertRaises(ValueError):app.mutate('/api/import',bad)
            self.assertEqual(self.asset(aid)['metrics']['price'],60)

    def test_previous_backup_without_link_column_still_restores(self):
        aid=self.add(False)
        with app.connect() as c:backup=app.export_data(c)
        for row in backup['tables']['assets']:row.pop('bdr_listing')
        app.mutate('/api/import',backup)
        self.assertEqual(self.asset(aid)['bdr']['listing'],{})

    def test_provider_failure_preserves_native_and_brl_data(self):
        aid,_=self.prepare();before=self.asset(aid)
        with patch.object(app,'request_json',side_effect=ValueError('Offline')),patch.object(sf,'lookup',side_effect=ValueError('Offline')),patch.object(sf,'fetch',side_effect=ValueError('Offline')):
            self.assertEqual(len(sf.refresh_asset(app,before,True)),3)
        after=self.asset(aid)
        self.assertEqual(after['bdr'],before['bdr'])
        self.assertEqual(after['metrics'],before['metrics'])

    def test_factor_refresh_fetches_underlying_us_series_and_restores(self):
        aid,_=self.prepare();a=self.asset(aid);d=factor_fixture('AAPL','US')
        with patch.object(factor_analysis,'fetch_factor',return_value=d['factors']['dollar_index']),patch.object(factor_analysis,'fetch_prices',side_effect=lambda app,symbol,mk,index=False:d['benchmark'] if index else d['prices']) as fetch:
            result=company_research.action(app,'/api/issuer/factors',dict(asset_id=aid))
        self.assertEqual(result['received'],['AAPL34'])
        self.assertTrue(any(call.args[1:3]==('AAPL','US') for call in fetch.call_args_list))
        with app.connect() as c:
            saved=app.latest(c,aid)[factor_analysis.KINDS[0]]['data']
            backup=app.export_data(c)
        self.assertEqual(saved['symbol'],'AAPL')
        self.assertEqual(saved['currency'],'USD')
        app.mutate('/api/import',backup)
        self.assertEqual(self.asset(aid)['company_research']['factor_analysis']['currency'],'USD')

    def test_non_us_link_has_fundamentals_and_explicit_factor_limit(self):
        link=dict(symbol='SAP.DE',market='XETRA',currency='EUR',source_url='https://example.org/programa',asof=self.day)
        aid=self.add(bdr_listing=link);a=self.asset(aid)
        self.assertEqual(company_research.annual_symbol(a),'SAP.DE')
        self.assertIsNone(factor_analysis.market(a))
        self.assertFalse(a['company_research']['factor_analysis']['supported'])

    @unittest.skipUnless(shutil.which('node'),'Node is required to check the JavaScript renderers')
    def test_page_forms_filters_and_both_dossiers_render(self):
        aid,_=self.prepare()
        self.add(False,ticker='MSFT34',name='BDR legado',auto_sector=False)
        app.mutate('/api/assets',dict(ticker='MSFT',name='Stock teste',asset_type='foreign',sector='Tecnologia'))
        state=app.state()
        script=r'''
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const S=JSON.parse(fs.readFileSync(0,'utf8'));
const c={S,view:'us',Intl,document:{addEventListener(){}},
 usView(){},globalView(){},assetForm(){},globalForm(){},detail(){},bindForms(){},
 assetById:id=>S.assets.find(a=>a.id===Number(id)),
 esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;'),
 fmt:v=>String(v??''),dt:v=>v||'sem data',money:v=>'BRL '+v,
 valueMetric:v=>String(v),tag:v=>String(v),qualityBadge:()=>'',checkBadges:()=>'',
 button:(action,label,cls,extra)=>`<button data-action="${action}" ${extra||''}>${label}</button>`,
 field:(name,label,value)=>`<label>${label}<input name="${name}" value="${value}"></label>`,
 select:(name,label,options,value)=>`<select name="${name}">${options.map(o=>`<option>${o}</option>`).join('')}</select>`,
 textarea:()=>'',footer:()=>'',card:(...a)=>a.join(' '),page:(...a)=>a.join(' '),
 refreshNotice:()=>'',checklist:()=>'',companyDetail:()=>'',historyChart:()=>'',
 modal:(title,html)=>{c.modalHtml=html;},wireForm(){},$:()=>null};
vm.createContext(c);vm.runInContext(fs.readFileSync('static/stocks.js','utf8'),c);
let html=vm.runInContext('usView()',c);
assert.ok(html.includes('Stocks e BDRs'));assert.ok(html.includes('AAPL34'));assert.ok(html.includes('MSFT34'));
vm.runInContext('stockFilters.us.type="foreign"',c);html=vm.runInContext('usView()',c);
assert.ok(html.includes('Stock teste'));assert.ok(!html.includes('AAPL34'));
for(const a of S.assets.filter(a=>a.asset_type==='bdr')){
 c.a=a;vm.runInContext('detail(a.id)',c);assert.ok(c.modalHtml.includes('BDR na B3'));
 vm.runInContext('bdrForm(a.id)',c);assert.ok(c.modalHtml.includes('name="symbol"'));
 assert.ok(c.modalHtml.includes('name="source_url"'));
}
'''
        result=subprocess.run([shutil.which('node'),'-e',script],input=json.dumps(state),text=True,capture_output=True,cwd=app.ROOT,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
