"""Dated stock ratios, sector preferences and BRL opening balances."""
import copy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

import stock_fundamentals as sf
import test_app as baseline
from test_us_market import chart
app=baseline.app


def financials(day=None):
    day=day or app.today().isoformat();prior=(app.today()-timedelta(days=365)).isoformat()
    values={'eps':4,'net_income':12,'revenue':80,'ebit':16,'operating_cashflow':20,'free_cashflow':8,
        'ebitda':20,'interest':4,'equity':100,'shares':10,'debt':40,'cash':10,'current_assets':60,'current_liabilities':30}
    rows=[{'field':field,'date':day,'period':'TTM' if field.startswith('trailing') else '3M','currency':'USD','value':values[key]}
          for field,key in sf.FIELDS.items()]
    rows.append({'field':'quarterlyStockholdersEquity','date':prior,'period':'3M','currency':'USD','value':80})
    return {'symbol':'AAPL','market':'US','series':rows,'source_url':'https://finance.yahoo.com/quote/AAPL/financials/'}


def profile(sector='Technology',industry='Software - Infrastructure'):
    return {'symbol':'AAPL','market':'US','name':'Apple Inc.','sector_original':sector,'industry':industry,
        'sector':sf.area(sector,industry),'source_url':'https://finance.yahoo.com/quote/AAPL/profile/'}


def quote(currency='USD',day=None):
    return {'data':{'price':100,'currency':currency},'asof':day or app.today().isoformat()}


class MathTests(unittest.TestCase):
    def test_ratios_have_matching_periods_and_roe_uses_average_equity(self):
        r=sf.derive(financials(),quote(),app.age)
        self.assertEqual(r['pe']['value'],25);self.assertEqual(r['pvp']['value'],10)
        self.assertAlmostEqual(r['roe']['value'],100*12/90)
        self.assertEqual(r['net_debt_ebitda']['value'],1.5)
        self.assertEqual(r['current_ratio']['value'],2)
        self.assertEqual(r['operating_margin']['value'],20)
        self.assertEqual(r['interest_coverage']['value'],4)
        self.assertEqual(r['debt_equity']['value'],.4)

    def test_reporting_currency_differs_from_share_price_no_fake_multiples(self):
        d=financials()
        for row in d['series']:row['currency']='EUR'
        r=sf.derive(d,quote(),app.age)
        self.assertNotIn('pe',r);self.assertNotIn('pvp',r)
        self.assertEqual(r['eps']['currency'],'EUR');self.assertIn('roe',r)

    def test_mixed_periods_and_currencies_never_form_debt_ratio(self):
        d=financials()
        for row in d['series']:
            if row['field']=='trailingEBITDA':row['currency']='EUR'
            if row['field']=='quarterlyCurrentLiabilities':row['date']=(app.today()-timedelta(days=90)).isoformat()
        r=sf.derive(d,quote(),app.age)
        self.assertNotIn('net_debt_ebitda',r);self.assertNotIn('current_ratio',r)

    def test_negative_denominators_and_old_quotes_do_not_look_cheap(self):
        d=financials()
        for row in d['series']:
            if row['field'] in ('trailingEBITDA','trailingDilutedEPS','quarterlyStockholdersEquity'):row['value']=-1
        r=sf.derive(d,quote(),app.age)
        for key in ('pe','pvp','roe','debt_equity','net_debt_ebitda'):self.assertNotIn(key,r)
        r=sf.derive(financials(),quote(day=(app.today()-timedelta(days=8)).isoformat()),app.age)
        self.assertNotIn('pe',r);self.assertNotIn('pvp',r)

    def test_snapshot_rejects_bool_nonfinite_future_duplicate_period_and_currency(self):
        for field,bad in (('value',True),('value',float('nan')),('period','12M'),('currency','XXX'),('date',(app.today()+timedelta(days=1)).isoformat())):
            d=financials();d['series'][0][field]=bad
            with self.assertRaises(ValueError):sf.validate_snapshot(app,'stock_financials',d)
        d=financials();d['series'].append(d['series'][0])
        with self.assertRaises(ValueError):sf.validate_snapshot(app,'stock_financials',d)

    def test_sector_translation_distinguishes_banks_insurance_and_consumption(self):
        for sector,industry,expected in (('Financial Services','Banks - Diversified','Bancos'),
            ('Financial Services','Insurance - Life','Seguros'),('Financial Services','Asset Management','Serviços financeiros e holdings'),
            ('Basic Materials','Steel','Metais, mineração e siderurgia'),('Consumer Defensive','Packaged Foods','Alimentos e agronegócio')):
            self.assertEqual(sf.area(sector,industry),expected)
        self.assertEqual(sf.area('Unknown','Unknown'),'Não classificado')

    def test_lookup_confirms_ticker_equity_exchange_and_does_not_infer_revenue_geography(self):
        raw={'quotes':[{'symbol':'AAPL','quoteType':'EQUITY','exchange':'NMS','longname':'Apple','sector':'Technology','industry':'Consumer Electronics'}]}
        with patch.object(app,'request_json',return_value=raw):self.assertEqual(sf.lookup(app,'AAPL')['sector'],'Tecnologia')
        for key,value in (('symbol','MSFT'),('quoteType','ETF'),('exchange','LSE')):
            wrong=copy.deepcopy(raw);wrong['quotes'][0][key]=value
            with patch.object(app,'request_json',return_value=wrong),self.assertRaises(ValueError):sf.lookup(app,'AAPL')

    def test_timeseries_provider_identity_and_period_are_validated(self):
        d=financials();parts=[]
        for field in sf.FIELDS:
            rows=[r for r in d['series'] if r['field']==field]
            parts.append({'meta':{'symbol':['AAPL'],'type':[field]},field:[{'asOfDate':r['date'],'periodType':r['period'],'currencyCode':r['currency'],'reportedValue':{'raw':r['value']}} for r in rows]})
        raw={'timeseries':{'result':parts}}
        with patch.object(app,'request_json',return_value=raw):self.assertEqual(len(sf.fetch(app,'AAPL','US')['series']),15)
        parts[0]['meta']['symbol']=['MSFT']
        with patch.object(app,'request_json',return_value=raw),self.assertRaises(ValueError):sf.fetch(app,'AAPL','US')


class IntegrationTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown

    def stock(self,automatic=False,sector='Varejo'):
        return app.mutate('/api/assets',{'ticker':'AAPL','name':'AAPL','asset_type':'foreign','sector':sector,'auto_sector':automatic})['id']

    def prepare(self,automatic=False):
        aid=self.stock(automatic)
        with app.connect() as c:
            app.add_snapshot(c,aid,'us_quote',{'price':100,'currency':'USD','market':'US','exchange':'NMS','symbol':'AAPL','issuer':'Apple'},'Teste',self.day)
        a=app.state()['assets'][0]
        with patch.object(sf,'lookup',return_value=profile()),patch.object(sf,'fetch',return_value=financials()):sf.refresh_asset(app,a)
        return aid

    def test_automatic_sector_can_be_disabled_and_manual_override_survives_refresh(self):
        aid=self.prepare(True);a=app.state()['assets'][0]
        self.assertEqual(a['sector'],'Tecnologia');self.assertEqual(a['name'],'Apple Inc.')
        app.mutate('/api/assets',{'id':aid,'ticker':'AAPL','asset_type':'foreign','name':'Nome escolhido','sector':'Saúde','auto_sector':False})
        with patch.object(sf,'lookup',return_value=profile()),patch.object(sf,'fetch',return_value=financials()):sf.refresh_asset(app,app.state()['assets'][0],True)
        a=app.state()['assets'][0];self.assertEqual(a['sector'],'Saúde');self.assertEqual(a['name'],'Nome escolhido')
        self.assertEqual(a['stock_research']['profile']['data']['sector'],'Tecnologia')

    def test_new_stock_quantity_fractional_cost_preserved_by_public_refresh(self):
        opening={'quantity':2.5,'average':500,'date':(app.today()-timedelta(days=30)).isoformat(),'institution':'Corretora teste','confirmed':True}
        aid=app.mutate('/api/assets',{'ticker':'AAPL','asset_type':'foreign','name':'Apple','sector':'Tecnologia','auto_sector':True,'opening':opening})['id']
        before=app.state()['assets'][0]
        with patch.object(sf,'lookup',return_value=profile()),patch.object(sf,'fetch',return_value=financials()):sf.refresh_asset(app,before)
        a=app.state()['assets'][0]
        self.assertEqual(a['position']['quantity'],2.5);self.assertEqual(a['position']['average'],500)
        self.assertEqual(a['trades'],before['trades']);self.assertTrue(a['trades'][0]['opening'])

    def test_indicators_reach_sector_checks_in_native_units_without_selic(self):
        self.prepare(True);a=app.state()['assets'][0]
        self.assertEqual(a['metrics']['pe'],25);self.assertEqual(a['metrics']['operating_cashflow'],20)
        self.assertEqual(a['sector_metrics']['operating_cashflow']['currency'],'USD')
        self.assertNotIn('Selic',json.dumps(a['sector_analysis']['checks']))
        checks={c['metric']:c for c in a['sector_analysis']['checks']}
        self.assertEqual(checks['operating_cashflow']['unit'],'USD');self.assertEqual(checks['operating_cashflow']['status'],'pass')
        self.assertEqual(checks['roic']['status'],'unknown')

    def test_manual_batch_is_atomic_and_preserves_other_metrics(self):
        aid=self.prepare(True)
        body={'asset_id':aid,'values':{'eps':7,'roe':20},'currency':'USD','asof':self.day,'source':'Relatório conferido'}
        app.mutate('/api/stocks/metrics',body)
        a=app.state()['assets'][0];self.assertEqual(a['metrics']['eps'],7);self.assertEqual(a['metrics']['roe'],20)
        self.assertEqual(a['metrics']['operating_cashflow'],20)
        with self.assertRaises(ValueError):app.mutate('/api/stocks/metrics',{**body,'values':{'eps':8,'roe':True}})
        self.assertEqual(app.state()['assets'][0]['metrics']['eps'],7)

    def test_global_listing_joins_fundamentals_in_reporting_currency(self):
        listing={'symbol':'SAP.DE','market':'XETRA','currency':'EUR','domicile':'DE','isin':'',
                 'distribution':'not_applicable','source_url':'https://www.sap.com/investors','asof':self.day}
        aid=app.mutate('/api/assets',{'ticker':'SAP.DE','name':'SAP.DE','asset_type':'global_stock',
            'sector':'Não classificado','auto_sector':True,'listing':listing})['id']
        facts=financials();facts.update(symbol='SAP.DE',market='XETRA',source_url='https://finance.yahoo.com/quote/SAP.DE/financials/')
        for row in facts['series']:row['currency']='EUR'
        identity=profile();identity.update(symbol='SAP.DE',market='XETRA',name='SAP SE',source_url='https://finance.yahoo.com/quote/SAP.DE/profile/')
        with app.connect() as c:
            app.add_snapshot(c,aid,'international_quote',{'price':100,'currency':'EUR','market':'XETRA',
                'exchange':'GER','symbol':'SAP.DE','instrument_type':'EQUITY','issuer':'SAP SE',
                'raw_currency':'EUR','scale':1},'Teste',self.day)
        with patch.object(sf,'lookup',return_value=identity),patch.object(sf,'fetch',return_value=facts):
            sf.refresh_asset(app,app.state()['assets'][0])
        a=app.state()['assets'][0]
        self.assertEqual(a['sector'],'Tecnologia');self.assertEqual(a['metrics']['pe'],25)
        self.assertEqual(a['sector_metrics']['eps']['currency'],'EUR')
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup)
        self.assertEqual(app.state()['assets'][0]['metrics']['pe'],25)

    def test_provider_failure_preserves_old_financials_and_valid_price(self):
        self.prepare();before=app.state()['assets'][0]
        with patch.object(sf,'lookup',side_effect=ValueError('Unavailable')),patch.object(sf,'fetch',side_effect=ValueError('Unavailable')):
            warnings=sf.refresh_asset(app,before,True)
        self.assertEqual(len(warnings),2);after=app.state()['assets'][0]
        self.assertEqual(after['snapshots']['stock_financials'],before['snapshots']['stock_financials'])
        self.assertEqual(after['us']['quote'],before['us']['quote'])

    def test_backup_keeps_sector_preferences_and_rejects_foreign_company_facts(self):
        self.prepare(True)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(backup));a=app.state()['assets'][0]
        self.assertEqual(a['auto_sector'],1);self.assertEqual(a['metrics']['eps'],4)
        bad=copy.deepcopy(backup)
        for s in bad['tables']['snapshots']:
            if s['kind']=='stock_financials':
                d=json.loads(s['data']);d['symbol']='MSFT';d['source_url']='https://finance.yahoo.com/quote/MSFT/financials/';s['data']=json.dumps(d)
        with self.assertRaises(ValueError):app.mutate('/api/import',bad)
        self.assertEqual(app.state()['assets'][0]['metrics']['eps'],4)


if __name__=='__main__':unittest.main()
