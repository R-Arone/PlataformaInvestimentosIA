import copy,json,unittest
from datetime import date,timedelta
from unittest.mock import patch
import test_app as baseline
import market_brief,market_outlook as outlook,research_exchange as exchange
app=baseline.app

class OutlookTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def report(self,profile='retail',**kw):
        return {'profile':profile,'retrieved_at':app.now(),'headlines':[],'sources':[],'errors':[],'method':'Teste sintético',**kw}

    def scenario(self,**kw):
        return {**outlook.DEFAULT,'usd':'unknown','geopolitics':'unknown','energy':'unknown',
                'asof':self.day,'source':'Hipótese sintética',**kw}

    def rows(self,start=15,end=14,age=0):
        return [{'data':(app.today()-timedelta(days=age+n)).strftime('%d/%m/%Y'),'valor':str(v)} for n,v in [(31,start),(0,end)]]

    def test_observations_filter_bad_future_and_compare_actual_dates(self):
        rows=self.rows()+[{'data':(app.today()+timedelta(days=1)).strftime('%d/%m/%Y'),'valor':'100'},
                          {'data':self.day,'valor':'nan'},{'data':'01/01/2020','valor':'1'},{'valor':'x'}]
        r=outlook.observation(rows,app.today(),'rates','https://example.org/serie')
        self.assertEqual(r['current'],14);self.assertEqual(r['direction'],'down');self.assertEqual(r['difference'],-1)
        self.assertEqual(r['asof'],self.day);self.assertFalse(r['stale'])
        r=outlook.observation(self.rows(5,5.02),app.today(),'usd','https://example.org/serie')
        self.assertEqual(r['direction'],'flat')
        r=outlook.observation(self.rows(5,5.2),app.today(),'usd','https://example.org/serie')
        self.assertEqual(r['direction'],'up');self.assertAlmostEqual(r['change'],4)
        with self.assertRaises(ValueError):outlook.observation(self.rows()[1:],app.today(),'rates','url')

    def test_fetch_context_partial_failure_is_dated_and_public_only(self):
        urls=[]
        def fake(url):
            urls.append(url)
            if '.1/' in url:raise ValueError('Falha sintética')
            return self.rows()
        r=outlook.fetch_context(fake,app.today(),app.now())
        self.assertEqual(set(r['observations']),{'rates'});self.assertEqual(len(r['errors']),1)
        self.assertEqual(len(urls),2);self.assertTrue(all(u.startswith('https://api.bcb.gov.br/') for u in urls))
        self.assertTrue(all('dataInicial=' in u and 'dataFinal=' in u for u in urls))

    def test_conditional_direction_conflicts_and_sector_exposure(self):
        r=outlook.outlook(self.report(scenario=self.scenario(rates='down')),app.today())
        self.assertEqual(r['direction'],'favorable');self.assertEqual(r['confidence'],'baixa')
        self.assertEqual(r['drivers'][0]['origin'],'user_hypothesis')
        r=outlook.outlook(self.report(scenario=self.scenario(rates='down',geopolitics='up')),app.today())
        self.assertEqual(r['direction'],'mixed')
        self.assertEqual(outlook.channel('bank','rates','down')[0],'mixed')
        self.assertEqual(outlook.channel('fii','rates','down')[0],'mixed')
        self.assertEqual(outlook.channel('foreign','usd','up')[0],'favorable')
        self.assertEqual(outlook.channel('commodity','energy','up')[0],'mixed')

    def test_old_future_and_missing_data_do_not_infer_direction(self):
        for day in ((app.today()-timedelta(days=8)).isoformat(),(app.today()+timedelta(days=1)).isoformat(),'bad'):
            obs=outlook.observation(self.rows(),app.today(),'rates','https://example.org/serie');obs['asof']=day
            r=outlook.outlook(self.report(scenario=self.scenario(),macro_context={'observations':{'rates':obs}}),app.today())
            self.assertEqual(r['direction'],'unknown')
        r=outlook.outlook(self.report(scenario=self.scenario(rates='down',asof=(app.today()-timedelta(days=8)).isoformat())),app.today())
        self.assertEqual(r['direction'],'unknown')
        self.assertEqual(outlook.outlook(self.report(),app.today())['direction'],'unknown')

    def test_headlines_are_recent_unambiguous_hypotheses(self):
        def headline(title,age=0):return {'title':title,'published_at':(app.today()-timedelta(days=age)).isoformat()+'T12:00:00+00:00','publisher':'Fonte de teste','url':'https://example.org/noticia'}
        for title in ('Brent pode subir com guerra','Brent não sobe após tensão','Alta do Brent e queda do petróleo'):
            self.assertEqual(outlook.headline_hints(self.report(headlines=[headline(title)]),app.today(),'energy'),[])
        self.assertEqual(outlook.headline_hints(self.report(headlines=[headline('Brent sobe após ataque',8)]),app.today(),'energy'),[])
        r=self.report(headlines=[headline('Brent sobe após ataque'),headline('Petróleo cai com acordo')])
        self.assertEqual(outlook.outlook(r,app.today())['drivers'][3]['direction'],'unknown')
        r=outlook.outlook(self.report(headlines=[headline('Ataque militar intensifica conflito')]),app.today())
        self.assertEqual(r['drivers'][2]['origin'],'headline_hint');self.assertIn('sem leitura do artigo',r['drivers'][2]['basis'])
        late=headline('Petróleo cai com acordo');late['published_at']=(app.today()+timedelta(days=1)).isoformat()+'T01:00:00+00:00'
        self.assertEqual(outlook.headline_hints(self.report(headlines=[late]),app.today(),'energy')[0]['direction'],'down')

    def test_manual_scenario_validated_persisted_without_network(self):
        for edit in ({'rates':[]},{'horizon':'tomorrow'},{'asof':(app.today()+timedelta(days=1)).isoformat()},{'source':''},{'quantity':10}):
            with self.assertRaises(ValueError):outlook.validate_scenario(app,self.scenario(**edit))
        with patch.object(app,'request_json',side_effect=AssertionError('Não deve consultar')):
            r=app.news_action('/api/news/scenario',{'profile':'retail',**self.scenario(rates='down')})
            self.assertEqual(r['outlook']['direction'],'favorable');self.assertEqual(r['headlines'],[])
            app.init_db();s=app.state();self.assertEqual(s['news_scenarios']['retail']['rates'],'down')
            self.assertEqual(s['news_reports']['retail']['outlook']['direction'],'favorable')
            self.assertIsNone(s['news_reports']['retail']['retrieved_at'])

    def test_backup_restores_personal_scenarios_and_rejects_bad_profiles(self):
        app.news_action('/api/news/scenario',{'profile':'retail',**self.scenario(rates='down')})
        with app.connect() as c:
            data=app.export_data(c)
            app.write_cache(c,'news_scenarios',{})
            app.write_cache(c,'news_reports',{'bank':self.report('bank')})
        app.mutate('/api/import',copy.deepcopy(data))
        state=app.state()
        self.assertEqual(state['news_scenarios']['retail']['rates'],'down')
        self.assertEqual(state['news_reports']['retail']['outlook']['direction'],'favorable')
        self.assertNotIn('bank',state['news_reports'])
        for bad in ({'unknown':self.scenario()},{'retail':self.scenario(source='')}):
            with self.assertRaises(ValueError):app.mutate('/api/import',{**copy.deepcopy(data),'news_scenarios':bad})
        self.assertEqual(app.state()['news_scenarios']['retail']['rates'],'down')
        legacy=copy.deepcopy(data);legacy.pop('news_scenarios')
        app.mutate('/api/import',legacy)
        self.assertEqual(app.state()['news_scenarios'],{})

    def test_context_cache_shared_daily_forced_and_failure_preserves_dates(self):
        calls=[]
        def fake(url):calls.append(url);return self.rows()
        with patch.object(app,'request_json',side_effect=fake):
            app.update_news_context();app.update_news_context();self.assertEqual(len(calls),2)
            app.news_action('/api/news/context',{'profile':'retail'});self.assertEqual(len(calls),4)
        with app.connect() as c:
            old=app.read_cache(c,'news_macro_context',{});old['observations']['rates']['asof']=(app.today()-timedelta(days=8)).isoformat()
            app.write_cache(c,'news_macro_context',old)
        with patch.object(app,'request_json',side_effect=ValueError('Falha sintética')):app.update_news_context(force=True)
        r=app.state()['news_reports']['retail'];self.assertEqual(r['macro_context']['observations']['rates']['asof'],old['observations']['rates']['asof'])
        self.assertEqual(r['outlook']['drivers'][0]['direction'],'unknown');self.assertEqual(len(r['macro_context']['errors']),2)

    def opinion_record(self):
        r=exchange.template(self.day,'retail');r['sources']=[{'title':'Fonte sintética','url':'https://example.org/juros','asof':self.day}]
        r['outlooks']=[{'ticker':'ABCD3','direction':'favorable','horizon':'medium','confidence':'baixa','conclusion':'Juros menores podem favorecer demanda, se não houver piora de crédito.',
          'drivers':[{'factor':'rates','impact':'favorable','fact':'Dado sintético, sem recomendação real.','interpretation':'Hipótese de redução do custo de crédito.','source_urls':['https://example.org/juros']}],
          'invalidation':['Recessão ou alta inesperada de juros.']}]
        return r

    def test_structured_return_old_v1_compatible_and_dated_source_binding(self):
        self.asset();r=self.opinion_record();v=exchange.validate(app,r)
        self.assertEqual(v['outlooks'][0]['direction'],'favorable')
        del r['outlooks'];self.assertNotIn('outlooks',exchange.validate(app,r))

    def test_return_rejects_orders_probability_bad_sources_tickers_and_dates(self):
        self.asset();r=self.opinion_record()
        mutations=[lambda v:v['outlooks'][0].update(probability=80),lambda v:v['outlooks'][0].update(quantity=10),
          lambda v:v['outlooks'][0].update(ticker='ZZZZ3'),lambda v:v['outlooks'].append(copy.deepcopy(v['outlooks'][0])),
          lambda v:v['outlooks'][0].update(direction=[]),lambda v:v['outlooks'][0].update(invalidation=[]),
          lambda v:v['outlooks'][0]['drivers'][0].update(source_urls=['https://example.org/unlisted']),
          lambda v:v['outlooks'][0]['drivers'][0].update(source_urls=['javascript:alert(1)']),
          lambda v:v['outlooks'][0]['drivers'][0].update(source_urls=[]),
          lambda v:v.update(asof=(app.today()-timedelta(days=1)).isoformat())]
        for mutate in mutations:
            v=copy.deepcopy(r);mutate(v)
            with self.assertRaises(ValueError):exchange.validate(app,v)

    def test_review_save_dedup_backup_and_no_portfolio_or_metric_mutations(self):
        self.asset();before=app.state()['assets']
        for _ in range(2):
            p=exchange.action(app,'/api/research/preview',{'text':json.dumps(self.opinion_record())})
            self.assertEqual(app.state()['research_reports'],[] if _==0 else saved)
            exchange.action(app,'/api/research/commit',{'token':p['token']});saved=app.state()['research_reports']
        self.assertEqual(len(saved),1);self.assertEqual(app.state()['assets'],before)
        with app.connect() as c:backup=app.export_data(c)
        app.mutate('/api/import',backup);self.assertEqual(app.state()['research_reports'][0]['record']['outlooks'][0]['ticker'],'ABCD3')

    def test_prompt_requests_researched_direction_without_private_position(self):
        aid=self.asset();app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':123,'price':987,'date':self.day,'institution':'Banco privado de teste'})
        app.news_action('/api/news/scenario',{'profile':'industrial',**self.scenario(rates='down')})
        prompt=app.news_action('/api/news/prompt',{'profile':'industrial'})['prompt']
        self.assertIn('outlooks',prompt);self.assertIn('geopolítica',prompt);self.assertIn('invalidariam',prompt)
        self.assertNotIn('Banco privado de teste',prompt);self.assertNotIn('quantity',prompt);self.assertNotIn('position',prompt)

if __name__=='__main__':unittest.main()
