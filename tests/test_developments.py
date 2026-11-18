import copy,json,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from aporte_brasil.importers import b3_import
from aporte_brasil.market import extra_sources
from aporte_brasil.importers import research_exchange
from aporte_brasil.portfolio import sector_analysis
from aporte_brasil.company import valuation
import test_app as baseline
app=baseline.app

class DevelopmentsTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset
    trade=baseline.AppTests.trade
    complete=baseline.AppTests.complete

    def csv(self,rows):
        return 'Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação;Custos\n'+'\n'.join(rows)

    def test_remaining_average_cost_sale_and_new_purchase(self):
        aid=self.asset('PETR4'); dates=[(app.today()-timedelta(days=i)).isoformat() for i in (4,3,2,1)]
        raw=self.csv([f'Crédito;{dates[0]};COMPRA / VENDA;PETR4;XP;10;20;—;—',
            f'Crédito;{dates[1]};Compra;PETR4;XP;10;30;300;2',
            f'Débito;{dates[2]};COMPRA / VENDA;PETR4;XP;5;40;200;1',
            f'Crédito;{dates[3]};Compra;PETR4;XP;5;10;50;0'])
        p=b3_import.preview(app,{'csv':raw});self.assertFalse(p['errors'])
        q=p['position_changes'][0]['after'];self.assertEqual(q['quantity'],20)
        self.assertAlmostEqual(q['average'],21.325);self.assertAlmostEqual(q['cost'],426.5)
        self.assertAlmostEqual(q['realized'],73.5);self.assertEqual(app.state()['assets'][0]['position']['quantity'],0)
        r=b3_import.commit(app,{'confirm_records':True,'token':p['token']});self.assertAlmostEqual(r['position_changes'][0]['after']['average'],21.325)
        p=b3_import.preview(app,{'csv':raw});self.assertEqual(p['skipped'],4);self.assertEqual(p['position_changes'],[])

    def test_historical_identity_review_and_explicit_skip(self):
        raw=self.csv([f'Crédito;{self.day};Compra;VELH3 - EMPRESA ANTIGA;XP;2;10;20;—',
                      f'Crédito;{self.day};Dividendos;PETR4;XP;—;—;3;—'])
        p=b3_import.preview(app,{'csv':raw});self.assertTrue(p['errors']);self.assertEqual(p['unknown_assets'][0]['ticker'],'VELH3')
        identified={'VELH3':{'asset_type':'stock','name':'Empresa antiga','sector':'Outros'}}
        p=b3_import.preview(app,{'csv':raw,'historical_assets':identified});self.assertFalse(p['errors'])
        b3_import.commit(app,{'confirm_records':True,'token':p['token']});a=next(a for a in app.state()['assets'] if a['ticker']=='VELH3')
        self.assertEqual(a['verified'],0);self.assertEqual(a['position']['quantity'],2)
        with self.assertRaises(ValueError):b3_import.preview(app,{'csv':raw,'historical_assets':{'VELH3':{**identified['VELH3'],'ticker':'PETR4'}}})

    def test_unknown_skip_requires_ack_and_does_not_guess(self):
        raw=self.csv([f'Crédito;{self.day};Compra;ANTG3;XP;2;10;20;0',f'Crédito;{self.day};Dividendos;PETR4;XP;1;1;1;0'])
        p=b3_import.preview(app,{'csv':raw,'skip_unknown':True});self.assertFalse(p['errors']);self.assertEqual(p['ignored_count'],1)
        with self.assertRaises(ValueError):b3_import.commit(app,{'confirm_records':True,'token':p['token']})
        b3_import.commit(app,{'confirm_records':True,'token':p['token'],'ack_ignored':True});self.assertFalse(app.state()['assets'])

    def test_invalid_numbers_have_field_and_raw_value(self):
        raw=self.csv([f'Crédito;{self.day};Compra;PETR4;XP;XYZ;30;90;0'])
        p=b3_import.preview(app,{'csv':raw});self.assertIn('Quantidade',p['errors'][0]);self.assertIn('XYZ',p['errors'][0]);self.assertIsNone(p['token'])
        self.assertEqual(b3_import.numeric(app,'R$\u00a01.234,56','Valor'),1234.56)
        self.assertIsNone(b3_import.numeric(app,'R$ -','Valor',True))
        with self.assertRaises(ValueError):b3_import.numeric(app,'(1,5)','Quantidade')

    def test_treasury_audit_remaining_position(self):
        raw=self.csv([f'Crédito;{self.day};Compra;TESOURO SELIC 2031;XP;2;1000;2000;0',f'Débito;{self.day};Resgate antecipado;TESOURO SELIC 2031;XP;0,5;1100;550;0'])
        p=b3_import.preview(app,{'csv':raw});self.assertFalse(p['errors']);q=p['position_changes'][0]
        self.assertEqual(q['institution'],'XP');self.assertEqual(q['after']['quantity'],1.5);self.assertEqual(q['after']['average'],1000)

    def record(self,ticker='PETR4'):
        r=research_exchange.template(self.day,'commodity');r['summary']='Resumo de teste';r['sources']=[]
        r['indicators']=[{'ticker':ticker,'metric':'net_debt_ebitda','value':1.5,'asof':self.day,'source_url':'https://www.bcb.gov.br/','definition':'Mesma janela anual; conferido no relatório.'}]
        return r

    def test_treasury_merges_backdated_batch_before_validation(self):
        raw=self.csv(['Crédito;2026-09-01;Compra;TESOURO SELIC 2031;XP;10;1000;10000;0','Débito;2026-09-05;Venda;TESOURO SELIC 2031;XP;10;1200;12000;0'])
        p=b3_import.preview(app,{'csv':raw});self.assertFalse(p['errors']);b3_import.commit(app,{'confirm_records':True,'token':p['token']})
        raw=self.csv(['Débito;2026-09-02;Venda;TESOURO SELIC 2031;XP;5;1100;5500;0','Crédito;2026-09-03;Compra;TESOURO SELIC 2031;XP;5;1100;5500;0'])
        p=b3_import.preview(app,{'csv':raw});self.assertFalse(p['errors']);self.assertEqual(p['position_changes'][0]['after']['quantity'],0)
        b3_import.commit(app,{'confirm_records':True,'token':p['token']});self.assertEqual(app.state()['fixed'][0]['balance'],0)

    def test_research_optional_metric_preserves_other_data_and_dedupes(self):
        aid=self.asset('PETR4')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','wacc':12,'asof':self.day,'source':'Relatório teste'})
        p=research_exchange.action(app,'/api/research/preview',{'text':json.dumps(self.record())})
        with self.assertRaises(ValueError):research_exchange.action(app,'/api/research/commit',{'token':p['token'],'apply_indicators':True})
        research_exchange.action(app,'/api/research/commit',{'token':p['token']})
        self.assertNotIn('metric:net_debt_ebitda',app.state()['assets'][0]['snapshots'])
        p=research_exchange.action(app,'/api/research/preview',{'text':json.dumps(self.record())})
        research_exchange.action(app,'/api/research/commit',{'token':p['token'],'apply_indicators':True,'verified_sources':True})
        s=app.state();self.assertEqual(len(s['research_reports']),1);a=s['assets'][0]
        self.assertEqual(a['snapshots']['risk']['data']['wacc'],12);self.assertEqual(a['metrics']['net_debt_ebitda'],1.5)
        self.assertIn('https://',a['sector_metrics']['net_debt_ebitda']['source']);self.assertFalse(a['trades'])
        with app.connect() as c:data=app.export_data(c)
        data['valuation_cases']={'PETR4':{'inputs':valuation.calculate({'price':30,'dividends_per_share':3,'target_yield':6},app.number)['inputs'],'saved_at':app.now()}}
        app.mutate('/api/import',data);self.assertEqual(len(app.state()['research_reports']),1)
        self.assertEqual(app.state()['valuation_cases']['PETR4']['inputs']['target_yield'],6)

    def test_research_rejects_orders_future_unsafe_and_invalid_values(self):
        self.asset('PETR4');r=self.record()
        for mutate in [lambda v:v.update(quantity=5),lambda v:v['actions'].append({'ticker':'PETR4','action':'comprar','reason':'ordem'}),
            lambda v:v['indicators'][0].update(value=True),lambda v:v['indicators'][0].update(value=float('nan')),
            lambda v:v['indicators'][0].update(ticker='ZZZZ3'),lambda v:v['indicators'][0].update(source_url='javascript:alert(1)'),
            lambda v:v['indicators'][0].update(asof=(app.today()+timedelta(days=1)).isoformat())]:
            v=copy.deepcopy(r);mutate(v)
            with self.assertRaises(ValueError):research_exchange.validate(app,v)
        self.assertEqual(research_exchange.validate(app,'```json\n'+json.dumps(r)+'\n```')['summary'],'Resumo de teste')

    def test_health_signals_exclude_peer_price_and_opportunity(self):
        aid=self.asset('PETR4','Petróleo');self.complete(aid,pvp=10)
        a=app.state()['assets'][0];r=a['sector_analysis']
        self.assertTrue(any(c['metric']=='pvp' and c['group']=='valuation' for c in r['checks']))
        self.assertEqual(sum(r['counts'].values()),len([c for c in r['checks'] if c['group']=='health']))
        self.assertTrue(all(c['metric'] not in ('pvp','pe') for c in r['checks'] if c['group']=='health'))

    def test_valuation_math_and_invalid_denominators(self):
        r=valuation.calculate({'price':40,'dividends_per_share':3,'eps':4,'bvps':20,'target_yield':6,'safety_margin':20,'required_return':10,'growth':2},app.number)
        self.assertEqual(r['methods'][0]['value'],50);self.assertEqual(r['methods'][0]['ceiling'],40)
        self.assertEqual(r['methods'][0]['price_gap'],0);self.assertAlmostEqual(r['methods'][1]['value'],1800**.5)
        self.assertAlmostEqual(r['methods'][2]['value'],38.25);self.assertEqual(r['payout'],75);self.assertEqual(r['dividend_yield'],7.5)
        r=valuation.calculate({'eps':-1,'bvps':10,'dividends_per_share':3,'target_yield':6,'required_return':5,'growth':5},app.number)
        self.assertIsNone(r['methods'][1]['value']);self.assertIsNone(r['methods'][2]['value'])
        self.assertTrue(all(m['value'] is None for m in valuation.calculate({},app.number)['methods']))

    def test_status_reference_not_given_invented_balance_date(self):
        records=json.dumps([{'Key':'p_vp','Value':1.2},{'Key':'dividaliquida_ebitda','Value':2},{'Key':'roe','Value':None}]).replace('"','&quot;')
        raw='<link rel="canonical" href="https://statusinvest.com.br/acoes/petr4"><input id="indicator-current" value="'+records+'">'
        r=extra_sources.page_reference('status',raw,'PETR4',app.today)
        self.assertEqual(r['groups'],{});self.assertIsNone(r['reference']['balance_asof']);self.assertEqual(r['reference']['values']['net_debt_ebitda'],2)
        self.assertNotIn('roe',r['reference']['values'])
        with self.assertRaises(ValueError):extra_sources.page_reference('status',raw,'VALE3',app.today)

    def test_yahoo_adjusted_prices_and_currency_identity(self):
        ts=int(datetime.combine(app.today(),datetime.min.time(),timezone.utc).timestamp())
        r={'chart':{'result':[{'meta':{'symbol':'PETR4.SA','currency':'BRL','regularMarketTime':ts,'regularMarketPrice':30},'timestamp':[ts-86400,ts,ts+86400],
            'indicators':{'quote':[{'close':[100,100,100]}],'adjclose':[{'adjclose':[25,26,27]}]}}]}}
        result=extra_sources.yahoo('PETR4',lambda _:r,app.today)
        self.assertEqual([p['close'] for p in result['history'][0]['prices']],[25,26]);self.assertEqual(result['quote'][0]['price'],30)
        del r['chart']['result'][0]['indicators']['adjclose']
        self.assertNotIn('history',extra_sources.yahoo('PETR4',lambda _:r,app.today))
        r['chart']['result'][0]['meta']['currency']='USD'
        with self.assertRaises(ValueError):extra_sources.yahoo('PETR4',lambda _:r,app.today)

if __name__=='__main__':unittest.main()
