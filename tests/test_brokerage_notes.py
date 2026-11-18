import base64
import io
import unittest
from aporte_brasil.importers import b3_import
from aporte_brasil.importers import brokerage_notes as notes
import test_app as baseline
app=baseline.app

def note(number='1234567',date='03/05/2018',trades=None,costs=None,net=None,irrf='0,00'):
    trades=trades if trades is not None else ['1-BOVESPA C VISTA PETROBRAS PN N2 # 100 28,50 2.850,00 D','1-BOVESPA V VISTA ITAUUNIBANCO PN N1 50 40,00 2.000,00 C']
    costs=costs if costs is not None else ['Taxa de liquidação 1,34 D     Taxa de registro 0,00','Emolumentos 0,24 D','Corretagem 9,90 D','ISS ( SÃO PAULO ) 0,50 D','Outras 0,00']
    return '\n'.join(['NOTA DE NEGOCIAÇÃO','Nr. nota   Folha   Data pregão',f'{number}      1       {date}','XP INVESTIMENTOS CCTVM S/A','Negócios realizados',
        'Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C',*trades,
        'Resumo dos Negócios','Resumo Financeiro','Valor líquido das operações 850,00 C',*costs,f'I.R.R.F. s/ operações, base R$ 2.000,00 {irrf}',
        f'Líquido para {date} '+(net or '')])

class BrokerageNoteTests(unittest.TestCase):
    setUp=baseline.AppTests.setUp
    tearDown=baseline.AppTests.tearDown
    asset=baseline.AppTests.asset

    def build(self,*texts,**extra):
        return notes.build(app,{'files':[{'name':f'nota{i}.txt','text':t} for i,t in enumerate(texts)],'institution':'XP','ticker_map':{'PETROBRAS PN N2':'PETR4','ITAUUNIBANCO PN N1':'ITUB4'},**extra})

    def test_parses_trades_costs_and_checks_the_net_amount(self):
        # 850,00 credit = 2.000 - 2.850 - 11,98 costs → expected -861,98 (D)
        r=self.build(note(net='861,98 D'))
        n=r['notes'][0]
        self.assertEqual((n['number'],n['date'],n['trade_count']),('1234567','03/05/2018',2))
        self.assertEqual(n['costs'],{'taxa de liquidacao':1.34,'taxa de registro':0.0,'emolumentos':.24,'corretagem':9.9,'iss':.5,'outras':0.0})
        self.assertEqual(n['total_costs'],11.98);self.assertEqual(r['errors'],[]);self.assertEqual(r['warnings'],[])
        self.assertEqual(r['unresolved'],[]);self.assertEqual(r['rows'],2)
        lines=r['csv'].splitlines()
        self.assertEqual(lines[0],'Data;Movimentação;Produto;Instituição;Mercado;Quantidade;Preço unitário;Valor da Operação;Custos')
        fees=[float(l.split(';')[-1].replace(',','.')) for l in lines[1:]]
        self.assertAlmostEqual(sum(fees),11.98,places=2)
        self.assertEqual(lines[1].split(';')[:5],['03/05/2018','Compra','PETR4','XP','Mercado à Vista'])

    def test_mismatched_net_and_unsupported_markets_warn(self):
        r=self.build(note(net='100,00 C'))
        self.assertTrue(any('líquido' in w for w in r['warnings']))
        r=self.build(note(trades=['1-BOVESPA C VISTA PETROBRAS PN N2 # 100 28,50 2.850,00 D','1-BOVESPA C OPCAO DE COMPRA 05/18 PETRE250 ON 100 0,50 50,00 D']))
        self.assertTrue(any('não suportados' in w for w in r['warnings']))
        self.assertEqual(r['rows'],1)

    def test_unresolved_names_need_a_mapping_and_tickers_are_used_directly(self):
        with app.connect() as c:
            c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)',('PETR4','PETROBRAS','stock','Energia',0,'Test fixture',app.now()))
        r=notes.build(app,{'files':[{'name':'n','text':note(trades=['1-BOVESPA C VISTA PETROBRAS PN N2 100 28,50 2.850,00 D','1-BOVESPA C VISTA HGLG11 CI 10 150,00 1.500,00 D'])}],'institution':'XP'})
        self.assertEqual([u['spec'] for u in r['unresolved']],['PETROBRAS PN N2'])
        self.assertEqual(r['csv'],'')
        self.assertTrue(any(s['ticker']=='PETR4' for s in r['unresolved'][0]['suggestions']))

    def test_flows_into_the_b3_preview_without_duplicating(self):
        self.asset('PETR4');self.asset('ITUB4')
        r=self.build(note(number='1',date='02/05/2018',trades=['1-BOVESPA C VISTA ITAUUNIBANCO PN N1 50 39,00 1.950,00 D']),note())
        p=b3_import.preview(app,{'csv':r['csv'],'filename':r['filename'],'mode':'trades','sheet':'__all','amount_basis':'reported'})
        self.assertEqual(p['errors'],[])
        self.assertEqual(len(p['rows']),3)
        sale=notes.build(app,{'files':[{'name':'x','text':note(trades=['1-BOVESPA V VISTA ITAUUNIBANCO PN N1 80 40,00 3.200,00 C'])}],'institution':'XP','ticker_map':{'ITAUUNIBANCO PN N1':'ITUB4'}})
        self.assertIn('excede',b3_import.preview(app,{'csv':sale['csv'],'filename':'x','mode':'trades','sheet':'__all','amount_basis':'reported'})['errors'][0])
        buy=next(x for x in p['rows'] if x['side']=='buy' and x['ticker']=='PETR4')
        self.assertEqual((buy['ticker'],buy['quantity'],buy['price'],buy['date']),('PETR4',100,28.5,'2018-05-03'))
        self.assertGreater(buy['fees'],0)

    def test_multi_page_note_repeated_note_limit_date_and_b3_period_warning(self):
        page1=note(costs=[]);page2='\n'.join(['NOTA DE NEGOCIAÇÃO','Nr. nota Folha Data pregão','1234567 2 03/05/2018','Corretagem 10,00 D'])
        r=self.build(page1,page2)
        self.assertEqual((len(r['notes']),r['notes'][0]['pages'],r['notes'][0]['total_costs']),(1,[1,2],10.0))
        r=self.build(note(),note(number='99',date='20/12/2019'))
        self.assertTrue(any('01/11/2019' in w for w in r['warnings']))
        r=self.build(note(),note(number='99',date='20/12/2019'),until='2019-10-31')
        self.assertEqual(r['rows'],2);self.assertTrue(any('data limite' in w for w in r['warnings']))
        with self.assertRaisesRegex(ValueError,'Não encontrei notas'):notes.build(app,{'files':[{'name':'x','text':'texto qualquer'}],'institution':'XP'})

    def test_header_layouts_short_numbers_and_unnumbered_pages(self):
        wide=note(number='7',date='03/05/2018').replace('Nr. nota   Folha   Data pregão','Nr. nota                 Folha                 Data pregão').replace('7      1       03/05/2018','7                  1                  03/05/2018')
        r=self.build(wide)
        self.assertEqual((r['notes'][0]['number'],r['notes'][0]['date']),('7','03/05/2018'))
        blank=note().replace('1234567      1       03/05/2018','')
        r=self.build(blank,blank)
        self.assertEqual(len(r['notes']),2)  # never merged without a number
        self.assertTrue(any('número da nota' in w for w in r['warnings']))

    def test_pdf_reading_with_and_without_password(self):
        try:
            from pypdf import PdfReader,PdfWriter
            from reportlab.pdfgen import canvas
        except ImportError:self.skipTest('pypdf/reportlab não instalados')
        buffer=io.BytesIO();c=canvas.Canvas(buffer)
        y=800
        for line in note().splitlines():
            c.setFont('Helvetica',8);c.drawString(20,y,line);y-=12
        c.save()
        plain=buffer.getvalue()
        writer=PdfWriter(clone_from=PdfReader(io.BytesIO(plain)));writer.encrypt('123456');locked=io.BytesIO();writer.write(locked)
        b64=lambda b:base64.b64encode(b).decode()
        ok=notes.build(app,{'files':[{'name':'n.pdf','pdf':b64(plain)}],'institution':'XP','ticker_map':{'PETROBRAS PN N2':'PETR4','ITAUUNIBANCO PN N1':'ITUB4'}})
        self.assertEqual(ok['rows'],2)
        with self.assertRaisesRegex(ValueError,'senha'):notes.build(app,{'files':[{'name':'n.pdf','pdf':b64(locked.getvalue())}],'institution':'XP'})
        again=notes.build(app,{'files':[{'name':'n.pdf','pdf':b64(locked.getvalue())}],'institution':'XP','password':'123456','ticker_map':{'PETROBRAS PN N2':'PETR4','ITAUUNIBANCO PN N1':'ITUB4'}})
        self.assertEqual(again['rows'],2)

if __name__=='__main__':unittest.main()
