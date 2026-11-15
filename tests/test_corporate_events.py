import unittest
from datetime import timedelta
import b3_import
import test_app as baseline
app=baseline.app
HEADER='Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n'

def ago(days):return (app.today()-timedelta(days=days)).isoformat()

class CorporateEventTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def preview(self,rows,**options):
        return b3_import.preview(app,{'csv':HEADER+'\n'.join(rows),**options})

    def commit(self,p,**extra):
        return b3_import.commit(app,{'token':p['token'],'confirm_records':True,'confirm_events':True,**extra})

    def holding(self):return app.state()['assets'][0]

    def test_split_dilutes_average_and_later_sale_uses_new_quantity(self):
        self.asset()
        rows=[f'Crédito;{ago(10)};Compra;ABCD3 - EMPRESA;XP;100;20;2000',
              f'Crédito;{ago(5)};Desdobro;ABCD3 - EMPRESA;XP;100;-;-',
              f'Débito;{ago(2)};Venda;ABCD3 - EMPRESA;XP;150;12;1800']
        p=self.preview(rows,include_settlements=True)
        self.assertFalse(p['errors'],p['errors']);self.assertEqual(len(p['corporate_events']),1)
        ev=p['corporate_events'][0]
        self.assertEqual((ev['before'],ev['after'],ev['ratio']),(100,200,'1 para 2'));self.assertFalse(ev['warning'])
        self.assertTrue(all(r['record_type']!='event' for r in p['rows']))
        with self.assertRaisesRegex(ValueError,'eventos corporativos'):b3_import.commit(app,{'token':p['token'],'confirm_records':True})
        self.commit(p)
        a=self.holding();self.assertEqual(a['position']['quantity'],50);self.assertAlmostEqual(a['position']['average'],10)
        self.assertAlmostEqual(a['position']['realized'],150*(12-10));self.assertEqual(len(a['trades']),2)
        self.assertEqual(a['corporate_events'][0]['quantity_delta'],100)
        self.assertEqual(self.preview(rows,include_settlements=True)['skipped'],3)

    def test_grouping_uses_resulting_quantity_and_fraction_leaves_at_average(self):
        self.asset()
        rows=[f'Crédito;{ago(10)};Compra;ABCD3;XP;105;2;210',
              f'Crédito;{ago(5)};Grupamento;ABCD3;XP;10,5;-;-',
              f'Débito;{ago(5)};Fração em Ativos;ABCD3;XP;0,5;-;-',
              f'Crédito;{ago(3)};Leilão de Fração;ABCD3;XP;0,5;19;9,5']
        p=self.preview(rows,include_settlements=True)
        self.assertFalse(p['errors'],p['errors'])
        events={e['event']:e for e in p['corporate_events']}
        self.assertEqual(events['grouping']['ratio'],'10 para 1');self.assertAlmostEqual(events['grouping']['after'],10.5)
        self.assertEqual(events['fraction_out']['after'],10)
        self.assertIn('Leilão de fração',p['ignored'][0]['reason'])
        self.commit(p,ack_ignored=True)
        pos=self.holding()['position'];self.assertAlmostEqual(pos['quantity'],10);self.assertAlmostEqual(pos['average'],20)
        self.assertAlmostEqual(pos['cost'],200)

    def test_bonus_requires_attributed_cost_and_adds_it(self):
        self.asset()
        rows=[f'Crédito;{ago(10)};Compra;ABCD3;XP;100;30;3000',f'Crédito;{ago(4)};Bonificação em Ativos;ABCD3;XP;10;-;-']
        p=self.preview(rows,include_settlements=True)
        self.assertIsNone(p['token']);self.assertIn('custo atribuído',p['errors'][0])
        need=p['event_inputs_needed'][0];self.assertEqual(need['need'],'unit_cost')
        p=self.preview(rows,include_settlements=True,event_inputs={need['key']:{'unit_cost':18.5}})
        self.assertFalse(p['errors'],p['errors']);self.assertEqual(p['corporate_events'][0]['unit_cost'],18.5)
        self.commit(p)
        pos=self.holding()['position'];self.assertEqual(pos['quantity'],110);self.assertAlmostEqual(pos['cost'],3000+185)
        # A corrected cost cannot add the same bonus a second time.
        p=self.preview(rows,include_settlements=True,event_inputs={need['key']:{'unit_cost':20}});self.assertEqual(p['skipped'],2)

    def test_bonus_cost_from_statement_and_skip_options(self):
        self.asset()
        rows=[f'Crédito;{ago(10)};Compra;ABCD3;XP;100;30;3000',f'Crédito;{ago(4)};Bonificação em Ativos;ABCD3;XP;10;12;120']
        p=self.preview(rows,include_settlements=True);self.assertFalse(p['errors']);self.assertEqual(p['corporate_events'][0]['unit_cost'],12)
        p=self.preview(rows,include_settlements=True,skip_events=True)
        self.assertFalse(p['corporate_events']);self.assertIn('excluído por sua escolha',p['ignored'][0]['reason'])
        b3_import.commit(app,{'token':p['token'],'confirm_records':True,'ack_ignored':True})
        self.assertEqual(self.holding()['position']['quantity'],100)

    def test_event_without_position_is_explicit_and_nothing_is_saved(self):
        self.asset()
        p=self.preview([f'Crédito;{ago(4)};Desdobro;ABCD3;XP;100;-;-'])
        self.assertIsNone(p['token']);self.assertIn('sem posição anterior',p['errors'][0])
        self.assertFalse(self.holding()['corporate_events'])

    def test_split_against_saved_history_backup_restore_and_delete(self):
        aid=self.asset();app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':50,'price':40,'date':ago(20),'institution':'XP'})
        p=self.preview([f'Crédito;{ago(5)};Desdobro;ABCD3;XP;150;-;-']);self.commit(p)
        a=self.holding();self.assertEqual(a['position']['quantity'],200);self.assertAlmostEqual(a['position']['average'],10)
        self.assertEqual(p['corporate_events'][0]['ratio'],'1 para 4')
        with app.connect() as c:data=app.export_data(c)
        self.assertEqual(data['format'],'aporte-brasil-v7');self.assertEqual(len(data['tables']['corporate_events']),1)
        app.mutate('/api/import',data);a=self.holding();self.assertEqual(a['position']['quantity'],200)
        self.assertEqual(self.preview([f'Crédito;{ago(5)};Desdobro;ABCD3;XP;150;-;-'])['skipped'],1)
        app.mutate('/api/trades',{'asset_id':aid,'side':'sell','quantity':120,'price':11,'date':ago(1),'institution':'XP'})
        with self.assertRaisesRegex(ValueError,'vendas posteriores'):app.mutate('/api/corporate-events/delete',{'id':a['corporate_events'][0]['id']})
        sale=next(t for t in self.holding()['trades'] if t['side']=='sell');app.mutate('/api/trades/delete',{'id':sale['id']})
        app.mutate('/api/corporate-events/delete',{'id':a['corporate_events'][0]['id']})
        self.assertEqual(self.holding()['position']['quantity'],50)
        p=self.preview([f'Crédito;{ago(5)};Desdobro;ABCD3;XP;150;-;-']);self.assertEqual(p['added'],1)

    def test_grouping_override_and_other_institution_untouched(self):
        aid=self.asset()
        for bank in ('XP','Itaú'):app.mutate('/api/trades',{'asset_id':aid,'side':'buy','quantity':300,'price':1,'date':ago(20),'institution':bank})
        rows=[f'Crédito;{ago(5)};Grupamento;ABCD3;XP;400;-;-']
        p=self.preview(rows);self.assertIn('sem redução',p['errors'][0])
        key=f'ABCD3|{ago(5)}|XP|grouping'
        p=self.preview(rows,event_inputs={key:{'after':30}});self.assertFalse(p['errors'],p['errors'])
        self.assertEqual(p['corporate_events'][0]['ratio'],'10 para 1');self.commit(p)
        pools={x['institution']:x['quantity'] for x in self.holding()['position']['institutions']}
        self.assertEqual(pools,{'XP':30,'Itaú':300})

if __name__=='__main__':unittest.main()
