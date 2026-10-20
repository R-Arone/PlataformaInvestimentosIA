"""Listing integrity, monetary units and explainable cross-border screening."""
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import test_app as baseline
import company_research as cr
import international_market as im
import investment_exposure as x
import portfolio_strategy
app=baseline.app


class InternationalTests(unittest.TestCase):
    def setUp(self):
        baseline.AppTests.setUp(self)
        with app.connect() as c: app.write_cache(c,'issuer_auto',False)
    tearDown=baseline.AppTests.tearDown

    def add(self,ticker='VWRP.L',typ='global_etf',**kwargs):
        preset=im.PRESETS.get(ticker,{})
        listing={'symbol':ticker,'market':preset.get('market','XETRA'),'currency':preset.get('currency','EUR'),
            'domicile':preset.get('domicile','DE'),'isin':preset.get('isin',''),'distribution':preset.get('distribution','not_applicable'),
            'source_url':preset.get('source_url','https://example.org/issuer'),'asof':self.day}
        listing.update(kwargs)
        return app.mutate('/api/assets',{'ticker':ticker,'name':'Instrumento de teste','asset_type':typ,
            'sector':'Tecnologia' if typ=='global_stock' else 'ETF · Ações exterior','listing':listing})['id']

    def chart(self,ticker='VWRP.L',currency='GBp',price=14000,exchange='LSE',typ='ETF',day=None):
        stamp=int(datetime.fromisoformat(day or self.day).replace(tzinfo=timezone.utc).timestamp())
        return {'chart':{'result':[{'meta':{'symbol':ticker,'currency':currency,'regularMarketPrice':price,
            'regularMarketTime':stamp,'exchangeName':exchange,'instrumentType':typ,'longName':'Instrumento de teste'}}]}}

    def request(self,url):
        if 'BRL=X' in url:
            ticker='GBPBRL=X' if 'GBP' in url else 'EURBRL=X'
            return self.chart(ticker,'BRL',7,'CCY','CURRENCY')
        return self.chart()

    def asset(self,aid): return next(a for a in app.state()['assets'] if a['id']==aid)

    def test_listing_and_native_quote_do_not_rewrite_ledger(self):
        aid=self.add()
        app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':2,'price':500,'date':self.day,'institution':'Conta exterior'})
        before=self.asset(aid)['position']
        with patch.object(app,'request_json',side_effect=self.request): im.refresh_asset(app,self.asset(aid))
        a=self.asset(aid)
        self.assertEqual(a['international']['quote']['data']['price'],140)
        self.assertEqual(a['international']['quote']['data']['currency'],'GBP')
        self.assertEqual(a['metrics']['price'],980)
        self.assertEqual(a['value'],1960)
        self.assertEqual({k:a['position'][k] for k in ('quantity','cost','average','realized')},{k:before[k] for k in ('quantity','cost','average','realized')})
        self.assertIsNone(a['analysis']['score'])
        self.assertEqual(portfolio_strategy.classify(a),'international')
        instrument=x.instrument(a,{})
        self.assertEqual(instrument['native_price'],140)
        self.assertEqual(instrument['currency'],'GBP')
        self.assertEqual(instrument['exposure']['scope'],'GLOBAL')
        x.validate_instrument(app,instrument)

    def test_bad_identity_type_exchange_currency_price_rejected(self):
        aid=self.add();a=self.asset(aid);l=a['international']['listing']
        for kwargs in ({'ticker':'VWRA.L'},{'currency':'USD'},{'exchange':'NMS'},{'typ':'EQUITY'},{'price':True},{'price':-1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError): im.parse_quote(app,a,l,self.chart(**kwargs))
        for symbol,market in (('VWRP','LSE'),('VWRP.L','XETRA'),('PETR4.SA','US')):
            with self.assertRaises(ValueError): im.symbol(symbol,market)

    def test_fx_failure_and_old_dates_preserve_previous_brl(self):
        aid=self.add();a=self.asset(aid)
        app.mutate('/api/manual',{'asset_id':aid,'kind':'quote','price':800,'source':'Referência BRL','asof':self.day})
        def nofx(url):
            if 'BRL=X' in url: raise ValueError('Fonte indisponível')
            return self.chart()
        with patch.object(app,'request_json',side_effect=nofx): self.assertTrue(im.refresh_asset(app,a))
        self.assertEqual(self.asset(aid)['metrics']['price'],800)
        def oldfx(url):
            return self.chart('GBPBRL=X','BRL',7,'CCY','CURRENCY','2020-01-01') if 'BRL=X' in url else self.chart()
        with patch.object(app,'request_json',side_effect=oldfx): self.assertTrue(im.refresh_asset(app,a))
        self.assertEqual(self.asset(aid)['metrics']['price'],800)
        self.assertEqual(self.asset(aid)['international']['quote']['data']['price'],140)

    def test_listing_validation_and_edit_are_atomic(self):
        for kwargs in ({'isin':'IE00BK5BQT81'},{'currency':'USD'},{'market':'US'},{'domicile':'US'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError): self.add(**kwargs)
        self.assertFalse(app.state()['assets'])
        aid=self.add();a=self.asset(aid)
        for typ in ('global_stock','foreign'):
            with self.assertRaises(ValueError): app.mutate('/api/assets',{**a,'asset_type':typ,'listing':a['international']['listing']})
        self.assertEqual(self.asset(aid)['asset_type'],'global_etf')

    def test_sector_screening_stocks_and_etfs_use_different_rules(self):
        aid=self.add('SAP.DE','global_stock');a=self.asset(aid)
        self.assertEqual(a['sector_analysis']['profile'],'technology')
        self.assertNotIn('Selic',' '.join(c['label'] for c in a['sector_analysis']['checks']))
        app.mutate('/api/research-profile',{'id':aid,'profile':'utility'})
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','currency':'EUR','asof':self.day,'source':'Relatório teste',
            'roe':20,'net_debt_ebitda':3,'debt_equity':.5,'interest_coverage':8,'operating_cashflow':100,'roic':15,'wacc':10})
        years=[{'date':str(app.today().year-3+i)+'-12-31','net_income':100,'revenue':1000,'operating_cashflow':100,'free_cashflow':50} for i in range(3)]
        cr.action(app,'/api/issuer/financials',{'asset_id':aid,'data':{'symbol':'SAP.DE','currency':'EUR','years':years,'source_url':'https://example.org/annual'}})
        a=self.asset(aid)
        self.assertEqual(a['company_research']['status'],'within')
        self.assertEqual(next(c for c in a['sector_analysis']['checks'] if c['metric']=='operating_cashflow')['unit'],'EUR')
        app.mutate('/api/settings',{'sector_rules':{'utility':{'net_debt_ebitda':2}}})
        self.assertEqual(self.asset(aid)['company_research']['status'],'review')
        etf=self.asset(self.add('CSPX.L'))
        self.assertNotIn('company_research',etf)
        self.assertEqual(etf['sector_analysis']['profile'],'etf')
        self.assertEqual(set(c['metric'] for c in etf['sector_analysis']['checks']),{'expense_ratio','tracking_error'})
        with self.assertRaises(ValueError): app.mutate('/api/research-profile',{'id':etf['id'],'profile':'technology'})
        self.assertEqual(x.instrument(etf,{})['exposure']['scope'],'US')
        self.assertEqual(x.instrument(a,{})['exposure']['scope'],'UNKNOWN')

    def test_sector_peers_do_not_deduplicate_four_letter_foreign_prefixes(self):
        for ticker,value in (('TECH.DE',10),('TECH1.DE',20),('TECH2.DE',30)):
            aid=self.add(ticker,'global_stock')
            app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','currency':'EUR','asof':self.day,'source':'Teste','pe':value})
        a=next(a for a in app.state()['assets'] if a['ticker']=='TECH.DE')
        check=next(c for c in a['sector_analysis']['checks'] if c['metric']=='pe')
        self.assertEqual(check['median'],25)
        self.assertEqual(len(check['peers']),2)

    def test_etf_exposure_scenario_and_accounting_currency_are_independent(self):
        broad=self.asset(self.add('VWRA.L'))
        us=self.asset(self.add('CSPX.L'))
        world={'sectors':[{'profile':'general','scope':'GLOBAL','market_wide':True,'direction':'favorable'}]}
        local={'sectors':[{'profile':'technology','scope':'BR','market_wide':False,'direction':'favorable'}]}
        self.assertEqual(x.effect(x.instrument(broad,{})['exposure'],world)[0],'favorable')
        self.assertEqual(x.effect(x.instrument(broad,{})['exposure'],local)[0],'unknown')
        self.assertEqual(x.instrument(us,{})['exposure']['scope'],'US')
        aid=self.add('TEST.DE','global_stock')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','asof':self.day,'source':'Relatório EUR','currency':'EUR','roic':15})
        app.mutate('/api/manual',{'asset_id':aid,'kind':'metric:wacc','asof':self.day,'source':'Premissa USD','currency':'USD','wacc':10})
        check=next(c for c in self.asset(aid)['sector_analysis']['checks'] if c['metric']=='roic')
        self.assertEqual(check['status'],'unknown')
        self.assertIn('moeda',check['reason'])

    def test_backup_roundtrip_and_currency_association_fail_closed(self):
        aid=self.add()
        with patch.object(app,'request_json',side_effect=self.request): im.refresh_asset(app,self.asset(aid))
        with app.connect() as c: backup=app.export_data(c)
        app.mutate('/api/import',copy.deepcopy(backup))
        self.assertEqual(self.asset(aid)['international']['listing']['isin'],'IE00BK5BQT80')
        self.assertEqual(self.asset(aid)['snapshots']['quote']['data']['fx_rate'],7)
        bad=copy.deepcopy(backup)
        q=next(r for r in bad['tables']['snapshots'] if r['kind']=='quote')
        data=json.loads(q['data']);data['fx_rate']=8;q['data']=json.dumps(data)
        with self.assertRaises(ValueError): app.mutate('/api/import',bad)
        for kind,key,value in (('international_quote','currency','USD'),('international_quote','price',True),('international_fx','currency','EUR')):
            bad=copy.deepcopy(backup)
            r=next(r for r in bad['tables']['snapshots'] if r['kind']==kind)
            d=json.loads(r['data']);d[key]=value;r['data']=json.dumps(d)
            with self.assertRaises(ValueError):app.mutate('/api/import',bad)
            self.assertEqual(self.asset(aid)['international']['quote']['data']['currency'],'GBP')
        bad=copy.deepcopy(backup);bad['tables']['snapshots']=[r for r in bad['tables']['snapshots'] if r['kind']!='international_listing']
        with self.assertRaises(ValueError): app.mutate('/api/import',bad)


if __name__=='__main__': unittest.main()
