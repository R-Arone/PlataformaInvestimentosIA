from datetime import datetime,timezone,date,timedelta
import unittest
from unittest.mock import patch
import json
import test_app as baseline
from aporte_brasil.portfolio import tax_rules
from aporte_brasil.company import public_fundamentals as public
from aporte_brasil.market import market_brief as news
from aporte_brasil.portfolio import sector_analysis
app=baseline.app

class InsightsTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def test_tax_boundaries_product_exceptions_and_2026(self):
        for days,rate in [(180,22.5),(181,20),(360,20),(361,17.5),(720,17.5),(721,15)]:
            self.assertEqual(tax_rules.reference('CDB',days)['rate'],rate)
        self.assertEqual(tax_rules.reference('LCI')['rate'],0)
        self.assertIsNone(tax_rules.reference('ETF · renda fixa')['rate'])
        self.assertIsNone(tax_rules.reference('Fundo de investimento')['rate'])
        self.assertEqual(tax_rules.reference('JCP')['rate'],17.5)
        self.assertEqual(tax_rules.horizon_days(date(2026,10,5),12),365)

    def test_auto_tax_separate_benchmark_manual_override(self):
        d={'principal':1000,'months':12,'indexer':'CDI','rate':100,'cdi':10,'tax_mode':'auto','product':'LCI'}
        r=app.projection(d)
        self.assertEqual(r['tax'],0);self.assertEqual(r['benchmark_tax'],17.5)
        self.assertGreater(r['net'],r['benchmark'])
        r=app.projection({**d,'tax_mode':'manual','tax':7})
        self.assertEqual(r['tax'],7)
        with self.assertRaises(ValueError): app.projection({**d,'product':'Fundo de investimento'})

    def test_foreign_basic_position_price_brl_ranking_backup(self):
        aid=app.mutate('/api/assets',{'ticker':'A','asset_type':'foreign','name':'Empresa A','sector':'Tecnologia'})['id']
        app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':2,'price':500,'date':self.day,'institution':'Conta exterior'})
        a=app.state()['assets'][0];self.assertEqual(a['value'],1000);self.assertTrue(a['value_at_cost'])
        self.assertIsNone(a['analysis']['score']);self.assertEqual(a['sector_analysis']['profile'],'technology')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'quote','price':600,'source':'Extrato convertido em BRL','asof':self.day})
        self.assertEqual(app.state()['assets'][0]['value'],1200)
        app.mutate('/api/assets',{'ticker':'AAPL34','asset_type':'bdr','name':'Apple BDR','sector':'Tecnologia'})
        with app.connect() as c:
            values,_=app.asset_values_from_catalog(c,{'ticker':'A1MD34','asset_type':'bdr','name':'AMD BDR'})
            self.assertEqual(values[0],'A1MD34')
        with app.connect() as c: data=app.export_data(c)
        app.mutate('/api/import',data)
        self.assertEqual(len(app.state()['assets']),2)
        with self.assertRaises(ValueError): app.mutate('/api/assets',{'ticker':'PETR4','asset_type':'bdr'})

    def test_sector_specific_profiles_and_manual_risk_survives_public(self):
        for sector,expected in [('Tecnologia','technology'),('Construção e incorporação','construction'),('Transportes','transport'),('Saúde','health'),('Educação','education'),('Alimentos','food_agro')]:
            self.assertEqual(sector_analysis.profile({'asset_type':'stock','sector':sector}),expected)
        aid=self.asset('ABCD3','Tecnologia')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','wacc':12,'asof':self.day,'source':'Relatório'})
        with app.connect() as c: app.add_snapshot(c,aid,'public',{'roic':16,'debt_equity':.5},'Fundamentus',self.day)
        a=app.state()['assets'][0]
        self.assertEqual(a['snapshots']['risk']['data']['wacc'],12)
        self.assertEqual(next(c for c in a['sector_analysis']['checks'] if c['metric']=='roic')['status'],'pass')

    def test_public_mapping_missing_not_ev_ebitda_and_identity(self):
        cells=[('Papel','ABCD3'),('Cotação','10,50'),('Data últ cot',date.today().strftime('%d/%m/%Y')),('Últ balanço processado','30/06/2026'),('P/VP','1,20'),('P/L','8,50'),('ROE','15,0%'),('ROIC','14,1%'),('Dív. Bruta','200,00'),('Patrim. Líq','100,00'),('EV / EBITDA','5,00')]
        html='<table>'+''.join('<tr><td>?'+k+'</td><td>'+v+'</td></tr>' for k,v in cells)+'</table>'
        data=public.parse_detail(html,'ABCD3',date.today)
        self.assertEqual(data['financial'][0]['debt_equity'],2)
        self.assertNotIn('net_debt_ebitda',data['financial'][0])
        self.assertEqual(data['statistics'][0]['pvp'],1.2)
        with self.assertRaises(ValueError): public.parse_detail(html,'OTHER3',date.today)

    def test_rss_future_old_unsafe_urls_and_plain_titles(self):
        def item(title,link,day): return '<item><title>'+title+'</title><link>'+link+'</link><pubDate>'+day+'</pubDate></item>'
        now=datetime(2026,10,5,15,tzinfo=timezone.utc)
        raw=('<rss><channel>'+item('&lt;b&gt;Selic&lt;/b&gt;','https://example.com/noticia','Mon, 05 Oct 2026 12:00:00 GMT')+item('Futura','https://example.com/futura','Mon, 06 Oct 2026 12:00:00 GMT')+item('Antiga','https://example.com/old','Mon, 01 Jan 2024 12:00:00 GMT')+item('Insegura','javascript:alert(1)','Mon, 05 Oct 2026 12:00:00 GMT')+'</channel></rss>').encode()
        result=news.parse_rss(raw,now);self.assertEqual(len(result),1);self.assertEqual(result[0]['title'],'Selic')
        with self.assertRaises(ValueError): news.parse_rss(b'<!DOCTYPE rss><rss/>',now)

    def test_news_cached_no_private_data_prompt_and_empty_not_bullish(self):
        aid=self.asset('ABCD3','Bancos',True)
        app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':123,'price':987,'date':self.day,'institution':'Banco secreto'})
        report={'profile':'bank','retrieved_at':app.now(),'headlines':[{'title':'Juros e crédito','url':'https://example.com/noticia','published_at':app.now(),'publisher':'Fonte'}],'sources':[],'errors':[],'method':'Títulos'}
        with app.connect() as c: app.write_cache(c,'news_reports',{'bank':report})
        r=app.news_action('/api/news/prompt',{'profile':'bank'})
        self.assertNotIn('Banco secreto',r['prompt']);self.assertNotIn('quantity',r['prompt']);self.assertNotIn('position',r['prompt'])
        self.assertIn('https://example.com/noticia',r['prompt'])
        b=app.news_action('/api/news/brief',{'profile':'bank'});self.assertIn('Rever concentração',b['recommendation']);self.assertTrue(b['topics'])
        app.init_db();self.assertIn('bank',app.state()['news_reports'])

    def test_brazil_sample_dedupe_invalid_multiples_minimum(self):
        for t in ('ABCD3','ABCD4','EFGH3','IJKL3'): self.asset(t,'Bancos')
        rows=[{'ticker':t,'liquidity':li,'pvp':p,'pe':8,'roe':15,'net_debt_equity':.2,'current_ratio':1,'roic':10,'operating_margin':20} for t,li,p in [('ABCD3',10,1),('ABCD4',20,2),('EFGH3',30,3),('IJKL3',40,4)]]
        with patch.object(public,'fetch_html',return_value='fixture'),patch.object(public,'parse_universe',return_value=rows): r=app.brazil_benchmarks()
        s=r['sectors']['Bancos'];self.assertEqual(s['count'],3);self.assertEqual(s['metrics']['pvp']['median'],3);self.assertNotIn('ABCD3',s['peers'])
        with patch.object(public,'fetch_html',side_effect=AssertionError('cache should avoid fetch')):self.assertEqual(app.brazil_benchmarks(),r)

if __name__=='__main__': unittest.main()
