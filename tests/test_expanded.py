import json
import sqlite3
import csv_import
import market
import unittest
import test_app as baseline
from unittest.mock import patch
app = baseline.app

class ExpandedTests(unittest.TestCase):
    setUp = baseline.AppTests.setUp
    tearDown = baseline.AppTests.tearDown
    asset = baseline.AppTests.asset
    def test_catalog_strict_types_and_digit_tickers(self):
        rows=market.normalize_catalog({'results':[
            {'symbol':'B3SA3','subType':'stock','exchange':'B3','isActive':True,'subsector':'Bancos Diversificados'},
            {'symbol':'03BK11','subType':'etf','exchange':'B3','isActive':True},
            {'symbol':'HGLG11','subType':'fii','exchange':'B3','isActive':True},
            {'symbol':'AAPL34','subType':'bdr','exchange':'B3','isActive':True},
            {'symbol':'OLDI3','subType':'stock','exchange':'B3','isActive':False}]},app.now())
        self.assertEqual([r['ticker'] for r in rows],['B3SA3','03BK11','HGLG11','AAPL34'])
        with app.connect() as c: app.store_catalog(c,rows)
        etf=app.mutate('/api/assets',{'ticker':'03BK11'})['id']
        self.assertEqual(app.state()['assets'][0]['asset_type'],'etf')
        self.assertIsNone(app.state()['assets'][0]['analysis']['score'])
        with self.assertRaises(ValueError):app.mutate('/api/assets',{'ticker':'UNKNOWN34'})
        with self.assertRaises(ValueError):app.mutate('/api/assets',{'ticker':'HGLG11','asset_type':'stock'})
        app.mutate('/api/assets',{'ticker':'BTC'})
        self.assertEqual(app.state()['assets'][1]['asset_type'],'crypto')

    def test_separate_banks_and_sell_rollback(self):
        aid=self.asset()
        for bank,qty,price in [('Itaú',10,20),('XP',5,30)]:
            app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':qty,'price':price,'fees':0,'date':self.day,'institution':bank})
        with self.assertRaises(ValueError):
            app.mutate('/api/trades',{'asset_id':aid,'side':'sell','quantity':6,'price':40,'fees':0,'date':self.day,'institution':'XP'})
        p=app.state()['assets'][0]['position']
        self.assertEqual(p['quantity'],15)
        self.assertEqual(p['institutions'][1]['average'],30)
        btc=app.mutate('/api/assets',{'ticker':'BTC'})['id']
        app.mutate('/api/trades',{'asset_id':btc,'side':'buy','quantity':1e-8,'price':400000,'fees':0,'date':self.day,'institution':'Carteira própria'})
        with self.assertRaises(ValueError):
            app.mutate('/api/trades',{'asset_id':btc,'side':'sell','quantity':2e-8,'price':400000,'fees':0,'date':self.day,'institution':'Carteira própria'})

    def test_fractional_csv_alias_and_migration_backup(self):
        p=csv_import.preview(app,{'kind':'positions','csv':'ticker;quantidade;preco_medio;instituicao\nPETR4F;10;30;XP'})
        self.assertFalse(p['errors']);self.assertEqual(p['rows'][0]['ticker'],'PETR4')
        csv_import.commit(app,{'token':p['token']})
        p=csv_import.preview(app,{'kind':'positions','csv':'ticker;quantidade;preco_medio;instituicao\nPETR4;10;30;XP'})
        self.assertEqual(p['skipped'],1)
        with app.connect() as c:
            c.execute('DELETE FROM imported_rows');c.execute('DELETE FROM trades');c.execute('DELETE FROM assets')
            c.execute('ALTER TABLE assets DROP COLUMN asset_type');c.execute('ALTER TABLE assets DROP COLUMN verified')
            c.execute('INSERT INTO assets(ticker,name,sector,financial,notes) VALUES (?,?,?,?,?)',('PETR4','Petrobras','Petróleo e gás',0,'anotação antiga'))
        app.init_db()
        self.assertTrue(list(app.DB_PATH.parent.glob('antes-atualizacao-v2-*.sqlite3')))
        self.assertEqual(app.state()['assets'][0]['notes'],'anotação antiga')

    def test_fx_budget_and_dollars_reconcile(self):
        d={'budget':1000,'exchange':5,'spread':2,'percent_fee':1,'fixed_fee':10,'iof':3,'mode':'budget'}
        r=market.fx_projection(d,app.number)
        self.assertAlmostEqual(r['total_cost'],r['spread_cost']+r['fee_cost']+r['tax_cost'])
        self.assertAlmostEqual(r['base_cost']+r['total_cost'],1000)
        inverse=market.fx_projection({**d,'mode':'dollars','budget':r['usd']},app.number)
        self.assertAlmostEqual(inverse['total'],1000)
        with self.assertRaises(ValueError):market.fx_projection({**d,'iof':''},app.number)

    def test_csv_positions_preview_dedupe_and_rollback(self):
        raw='ticker;quantidade;preco_medio;instituicao;data\nPETR4;10;25,50;XP;'+self.day+'\nBTC;0,01;400.000,00;Carteira própria;'+self.day
        p=csv_import.preview(app,{'kind':'positions','csv':raw})
        self.assertFalse(p['errors']); self.assertEqual(p['added'],2)
        self.assertFalse(app.state()['assets'])
        csv_import.commit(app,{'token':p['token']})
        again=csv_import.preview(app,{'kind':'positions','csv':raw})
        self.assertEqual(again['skipped'],2)
        csv_import.commit(app,{'token':again['token']})
        self.assertEqual(len(app.state()['assets']),2)
        wrong=csv_import.preview(app,{'kind':'positions','csv':raw.replace('10;25,50','11;25,50')})
        self.assertTrue(wrong['errors']);self.assertIsNone(wrong['token'])
        self.assertEqual(app.state()['assets'][1]['position']['quantity'],10)
        bad=csv_import.preview(app,{'kind':'trades','csv':'ticker;operacao;quantidade;preco;data;instituicao\nVALE3;compra;10;20;'+self.day+';XP\nPETR4;venda;100;30;'+self.day+';XP'})
        self.assertTrue(bad['errors']);self.assertEqual(len(app.state()['assets']),2)

    def test_csv_custom_mapping_fixed_updates_and_stale_preview(self):
        raw='Produto;Categoria;Banco;Aportes;SaldoAtual;DataExtrato\nMeu LCI;LCI;Itaú;1000;1.020,00;'+self.day
        mapping={'name':'Produto','type':'Categoria','institution':'Banco','invested':'Aportes','balance':'SaldoAtual','balance_date':'DataExtrato'}
        p=csv_import.preview(app,{'kind':'fixed','csv':raw,'mapping':mapping})
        self.assertFalse(p['errors']);csv_import.commit(app,{'token':p['token']})
        p=csv_import.preview(app,{'kind':'fixed','csv':raw.replace('1.020,00','1.050,00'),'mapping':mapping})
        self.assertEqual(p['updated'],1);csv_import.commit(app,{'token':p['token']})
        self.assertEqual(len(app.state()['fixed']),1);self.assertEqual(app.state()['fixed'][0]['balance'],1050)
        p=csv_import.preview(app,{'kind':'watchlist','csv':'ticker\nVALE3'})
        self.asset()
        with self.assertRaises(ValueError):csv_import.commit(app,{'token':p['token']})

    def test_backup_new_fields_and_v1_compatibility(self):
        p=csv_import.preview(app,{'kind':'trades','csv':'ticker;operacao;quantidade;preco;data;instituicao\nIVVB11;compra;2;300;'+self.day+';XP'})
        self.assertFalse(p['errors']);csv_import.commit(app,{'token':p['token']})
        with app.connect() as c:
            c.execute('INSERT INTO macro VALUES (?,?,?,?,?)',('btc',400000,self.day,'Fixture',app.now()))
            export=app.export_data(c)
        app.mutate('/api/import',export)
        self.assertEqual(app.state()['assets'][0]['asset_type'],'etf')
        self.assertEqual(app.state()['assets'][0]['trades'][0]['institution'],'XP')
        again=csv_import.preview(app,{'kind':'trades','csv':'ticker;operacao;quantidade;preco;data;instituicao\nIVVB11;compra;2;300;'+self.day+';XP'})
        self.assertEqual(again['skipped'],1)
        old=json.loads(json.dumps(export));old['format']='aporte-brasil-v1';old['tables'].pop('imported_rows');old['tables']['macro']=[]
        for a in old['tables']['assets']: a.pop('asset_type');a.pop('verified')
        for t in old['tables']['trades']:t.pop('institution')
        app.mutate('/api/import',old)
        self.assertEqual(app.state()['assets'][0]['asset_type'],'etf')
        self.assertEqual(app.state()['assets'][0]['trades'][0]['institution'],'Não informada')

    def test_sentiment_and_fii_fraction_normalization(self):
        ts=int(__import__('datetime').datetime.fromisoformat(self.day).timestamp())
        pts=market.fetch_sentiment(lambda _: {'data':[{'timestamp':ts,'value':'25','value_classification':'Fear'},{'timestamp':ts+172800,'value':'99'}]},app.number,app.today)
        self.assertEqual(len(pts),1)
        data={'fiis':[{'symbol':'MXRF11','asOfDate':self.day+' 00:00:00','priceToNav':.9,'dividendYield12m':.12}]}
        kind,d,ref=market.fetch_fii({'ticker':'MXRF11','asset_type':'fii'},lambda *args:data,'',app.valid_date,app.clean,app.today)
        self.assertEqual(d['dy'],12)

    def test_failed_source_status_survives_restart(self):
        self.asset()
        saved_job=dict(app.JOB)
        try:
            app.REFRESH_LOCK.acquire()
            app.JOB['running']=True
            with patch.object(app,'request_json',side_effect=ValueError('Fonte indisponível no teste')):
                app.refresh_worker()
            errors=list(app.JOB['errors'])
            self.assertTrue(errors)
            source=next(s for s in app.state()['sources'] if s['key']=='quotes')
            self.assertEqual(source['status'],'error')
            app.JOB.update(finished_at=None,errors=[])
            app.init_db()
            self.assertEqual(app.JOB['errors'],errors)
        finally:
            app.JOB.clear();app.JOB.update(saved_job)
