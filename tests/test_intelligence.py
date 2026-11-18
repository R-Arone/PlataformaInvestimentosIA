"""Independent valuation identities, 24h event handling and private-monitor isolation."""
import base64
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from aporte_brasil.core import desktop_notifications as desktop
from aporte_brasil.market import market_monitor as monitor
from aporte_brasil.market import market_news as news
from aporte_brasil.company import valuation
import test_signals as existing
from test_app import app


def headline(title,clock,publisher='Fonte A'):
    return {'title':title,'published_at':clock.isoformat(),'publisher':publisher,'url':'https://example.org/noticia'}


class ValuationTests(unittest.TestCase):
    def values(self,inputs):return {m['method']:m for m in valuation.calculate(inputs,app.number)['methods']}

    def test_flat_growth_dcf_equals_gordon_for_any_explicit_period(self):
        for years in (1,5,10):
            rows=self.values({'fcfe_per_share':3,'fcfe_growth':2,'terminal_growth':2,'forecast_years':years,
                              'required_return':10,'dividends_per_share':3,'growth':2})
            self.assertAlmostEqual(rows['Fluxo de caixa descontado (FCFE)']['value'],3*1.02/.08)
            self.assertAlmostEqual(rows['Gordon']['value'],rows['Fluxo de caixa descontado (FCFE)']['value'])

    def test_two_stage_dcf_independent_cash_flow_arithmetic(self):
        row=self.values({'fcfe_per_share':3,'fcfe_growth':10,'terminal_growth':2,'forecast_years':2,'required_return':12})
        expected=3.3/1.12+3.63/1.12**2+(3.63*1.02/.10)/1.12**2
        self.assertAlmostEqual(row['Fluxo de caixa descontado (FCFE)']['value'],expected)

    def test_residual_income_at_cost_of_equity_equals_book_value(self):
        rows=self.values({'bvps':20,'normalized_roe':12,'growth':3,'required_return':12})
        self.assertEqual(rows['Lucro residual (estável)']['value'],20)
        rows=self.values({'bvps':20,'normalized_roe':18,'growth':3,'required_return':12})
        self.assertAlmostEqual(rows['Lucro residual (estável)']['value'],20*15/9)

    def test_no_fabricated_growth_multiple_cashflow_or_negative_valuation(self):
        rows=self.values({'eps':-3,'target_pe':10,'fcfe_per_share':3,'fcfe_growth':5,'terminal_growth':10,'required_return':10,
                          'bvps':20,'normalized_roe':2,'growth':3})
        self.assertIsNone(rows['Múltiplo de lucro']['value'])
        self.assertIsNone(rows['Fluxo de caixa descontado (FCFE)']['value'])
        self.assertIsNone(rows['Lucro residual (estável)']['value'])
        self.assertTrue(all(m['value'] is None for m in self.values({}).values()))
        for bad in ({'forecast_years':1.5},{'fcfe_growth':True}):
            with self.assertRaises(ValueError):valuation.calculate(bad,app.number)

    def test_classification_uses_raw_model_value_and_handles_boundaries(self):
        inputs={'eps':10,'target_pe':10,'fcfe_per_share':10,'fcfe_growth':0,'terminal_growth':0,'required_return':10,'safety_margin':50}
        for price,label in ((90,'within'),(110,'within'),(89,'below'),(130,'expensive'),(120,'above')):
            r=valuation.calculate({**inputs,'price':price},app.number)
            self.assertEqual(r['comparison']['classification'],label)
            self.assertEqual(r['comparison']['count'],2)
        r=valuation.calculate({'eps':4,'target_pe':10,'bvps':20,'normalized_roe':10,'required_return':10,'growth':0,'price':30},app.number)
        self.assertEqual(r['comparison']['classification'],'mixed')


class NewsTests(unittest.TestCase):
    clock=datetime(2026,10,6,18,tzinfo=timezone.utc)
    def test_minister_exit_has_two_conditional_paths_and_no_causal_forecast(self):
        e=news.event(headline('Ministro anuncia renúncia ao cargo',self.clock))
        self.assertEqual(e['certainty'],'reported')
        self.assertEqual(e['direction'],'mixed')
        self.assertEqual(len(e['paths']),2)
        for title,status in (('Ministro nega renúncia','denial'),('Ministro pode renunciar','hypothesis')):
            self.assertEqual(news.event(headline(title,self.clock))['certainty'],status)
        for title in ('Selic vai cair?', 'Mercado prevê queda da Selic', 'Eleições podem mudar a Selic'):
            self.assertEqual(news.event(headline(title,self.clock))['certainty'],'hypothesis')

    def test_twenty_four_hour_window_deduplicates_reprints_and_rejects_future(self):
        rows=[headline('Título recente',self.clock),headline('Título recente - Fonte B',self.clock,'Fonte B'),
              headline('Antigo',self.clock-timedelta(hours=24,seconds=1)),headline('Futuro',self.clock+timedelta(seconds=1)),
              headline('Limite',self.clock-timedelta(hours=24)),headline('Sem fuso',self.clock.replace(tzinfo=None))]
        self.assertEqual([r['title'] for r in news.recent(rows,self.clock)],['Título recente','Limite'])

    def test_tone_requires_independent_publishers_and_current_titles(self):
        rows=[headline('Título '+str(i),self.clock,'Fonte A' if i%2 else 'Fonte B') for i in range(4)]
        sentiment={'items':[{**r,'score':.8} for r in rows],'model':'Teste','analyzed_at':self.clock.isoformat()}
        feed={'headlines':rows}
        self.assertEqual(news.overview(feed,sentiment,self.clock)['tone'],'positive')
        self.assertEqual(news.overview({'headlines':rows[:3]},sentiment,self.clock)['tone'],'unknown')
        self.assertEqual(news.overview({'headlines':[]},sentiment,self.clock)['classified_count'],0)

    def test_only_new_reported_events_after_activation_generate_alerts(self):
        items=[headline('Ministro anuncia renúncia',self.clock),headline('Ministra pode renunciar',self.clock),
               headline('Ministro nega demissão',self.clock),headline('Ministro deixa o cargo',self.clock-timedelta(hours=2))]
        current=news.overview({'headlines':items},None,self.clock)
        alerts=monitor.news_changes(None,current,(self.clock-timedelta(hours=1)).isoformat())
        self.assertEqual(len(alerts),1)
        self.assertEqual(monitor.news_changes(current,current,(self.clock-timedelta(hours=1)).isoformat()),[])
        old={**current,'tone':'positive','score':.5};new={**current,'tone':'negative','score':-.4}
        self.assertEqual(monitor.news_changes(old,new,self.clock.isoformat())[0]['kind'],'sentiment')


class NotificationTests(unittest.TestCase):
    def test_untrusted_title_is_only_json_stdin_not_executable_code(self):
        text="$(Remove-Item anything); <script> & '"
        with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='submitted')) as run:
            result=desktop.notify(text,text,'http://127.0.0.1:8877/#news')
        args=run.call_args.args[0];kwargs=run.call_args.kwargs
        self.assertNotIn(text,' '.join(args))
        self.assertEqual(base64.b64decode(args[-1]).decode('utf-16-le'),desktop.SCRIPT)
        self.assertEqual(json.loads(kwargs['input'])['body'],text)
        self.assertTrue(result['submitted'])
        with self.assertRaises(ValueError):desktop.notify('x','y','https://example.org/')

    def test_locked_vault_only_queries_public_news_without_authentication(self):
        clock=datetime.now(timezone.utc)
        rows=[headline('Notícia '+str(i),clock,'Fonte A' if i%2 else 'Fonte B') for i in range(4)]
        fake=SimpleNamespace(VAULT=SimpleNamespace(key=None),ROOT=Path('.'),DB_PATH=Path('tests/demo.sqlite3'),
                             now=lambda:clock.isoformat(),connect=Mock(side_effect=AssertionError('Private DB accessed')),
                             state=Mock(side_effect=AssertionError('Portfolio accessed')))
        state={**monitor.STATE,'alerts':[],'market':None}
        with patch.object(monitor,'STATE',state),patch.object(monitor,'BASELINE',{'PRIVATE3':'expensive'}), \
             patch.object(monitor,'CONFIG',{**monitor.DEFAULTS,'enabled':True,'windows_notifications':False}), \
             patch.object(monitor.market_brief,'fetch',return_value={'profile':'general','headlines':rows}), \
             patch.object(monitor.market_ai,'hf_classify',return_value=[{'positive':.8,'negative':.1,'neutral':.1}]*4), \
             patch.object(monitor.desktop_notifications,'notify') as notify:
            result=monitor.cycle(fake)
            self.assertTrue(result['public_only'])
            self.assertEqual(result['market']['tone'],'positive')
            self.assertEqual(monitor.BASELINE,{})
            fake.connect.assert_not_called();fake.state.assert_not_called();notify.assert_not_called()

    def test_notifications_are_grouped_and_failed_delivery_is_visible(self):
        fake=SimpleNamespace(now=lambda:'2026-10-06T18:00:00+00:00')
        messages=[{'key':str(i),'title':'Teste','body':'Teste','kind':'news'} for i in range(3)]
        with patch.object(monitor,'STATE',{**monitor.STATE,'alerts':[]}), \
             patch.object(monitor,'CONFIG',{**monitor.DEFAULTS,'enabled':True,'windows_notifications':True}), \
             patch.object(monitor.desktop_notifications,'notify',side_effect=ValueError('No delivery')) as notify:
            monitor.remember(fake,messages);monitor.remember(fake,messages)
            self.assertEqual(notify.call_count,1)
            self.assertEqual(len(monitor.STATE['alerts']),3)
            self.assertTrue(all(a['notification']=='failed' for a in monitor.STATE['alerts']))
            self.assertIn('Windows',monitor.STATE['error'])

    def test_disabling_during_a_consultation_suppresses_late_popup(self):
        fake=SimpleNamespace(now=lambda:'2026-10-06T18:00:00+00:00')
        with patch.object(monitor,'STATE',{**monitor.STATE,'alerts':[]}), \
             patch.object(monitor,'CONFIG',{**monitor.DEFAULTS,'enabled':False}), \
             patch.object(monitor.desktop_notifications,'notify') as notify:
            monitor.remember(fake,[{'key':'late','title':'Teste','body':'Teste','kind':'news'}])
            notify.assert_not_called()
            self.assertEqual(monitor.STATE['alerts'][0]['notification'],'disabled')
            monitor.CONFIG.update(enabled=True,brazil_news=False)
            monitor.remember(fake,[{'key':'news-off','title':'Teste','body':'Teste','kind':'news'}])
            notify.assert_not_called()
            self.assertEqual(len(monitor.STATE['alerts']),1)


class PriceMonitorIntegrationTests(unittest.TestCase):
    setUp=existing.IntegrationTests.setUp
    tearDown=existing.IntegrationTests.tearDown
    asset=existing.IntegrationTests.asset
    trade=existing.IntegrationTests.trade
    prepare=existing.IntegrationTests.prepare

    def test_monitor_and_popups_can_be_disabled_separately(self):
        with patch.object(monitor,'CONFIG',dict(monitor.DEFAULTS)),patch.object(monitor,'STATE',{**monitor.STATE,'alerts':[]}),patch.object(monitor,'BASELINE',{}):
            cfg={**monitor.DEFAULTS,'enabled':True,'windows_notifications':False}
            self.assertFalse(monitor.configure(app,cfg)['settings']['windows_notifications'])
            self.assertTrue(monitor.status()['settings']['enabled'])
            cfg={k:False for k in monitor.DEFAULTS}
            self.assertFalse(monitor.configure(app,cfg)['settings']['enabled'])
            with app.connect() as c:self.assertEqual(app.read_cache(c,'monitor_settings',{}),cfg)

    def test_hourly_price_change_does_not_change_position_or_repeat_alert(self):
        aid=self.prepare();self.trade(aid)
        inputs={'eps':10,'target_pe':10,'fcfe_per_share':10,'fcfe_growth':0,'terminal_growth':0,'required_return':10}
        with app.connect() as c:
            app.write_cache(c,'valuation_cases',{'AAAA3':{'inputs':inputs,'saved_at':app.now()}})
        original=app.state()['assets'][0]
        before={k:original['position'][k] for k in ('quantity','cost','average','realized')}
        with patch.object(monitor,'BASELINE',{'AAAA3':'within'}), \
             patch.object(monitor.extra_sources,'yahoo',return_value={'quote':({'price':130},self.day,'Yahoo Finance · chart/AAAA3.SA')}):
            changes=monitor.update_prices(app)
            self.assertEqual(len(changes),1)
            self.assertIn('muito acima',changes[0]['body'])
            self.assertEqual(monitor.update_prices(app),[])
        after=app.state()['assets'][0]
        self.assertEqual(before,{k:after['position'][k] for k in before})
        self.assertEqual(original['trades'],after['trades'])


if __name__=='__main__':unittest.main()
