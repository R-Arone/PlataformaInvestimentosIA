"""Optional browser verification with fictional holdings in a temporary database."""
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from aporte_brasil.company import company_history as history
from aporte_brasil.company import company_research as research
from aporte_brasil.company import company_insights as insights
from aporte_brasil.ai import market_ai


def fixture():
    app.init_db()
    app.mutate('/api/settings', {'auto_refresh': False, 'profile': 'Demonstração · empresas e valores fictícios'})
    with app.connect() as c:
        app.write_cache(c, 'issuer_auto', False)
    for ticker, name in [('ABCD3', 'Horizonte Energia · empresa fictícia'), ('EFGH3', 'Indústria Norte · empresa fictícia')]:
        with app.connect() as c:
            c.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?)', (ticker, name, 'stock', 'Energia elétrica', 0, 'Fixture', app.now()))
        aid = app.mutate('/api/assets', {'ticker': ticker, 'name': name, 'asset_type': 'stock'})['id']
        if ticker == 'EFGH3': continue
        app.mutate('/api/manual', {'asset_id': aid, 'kind': 'risk', 'source': 'Relatório fictício', 'asof': app.today().isoformat(),
            'roe': 18, 'debt_equity': .6, 'pvp': 1.2, 'pe': 12, 'interest_coverage': 8, 'current_ratio': 2,
            'net_debt_ebitda': 1.2, 'operating_cashflow': 180_000_000, 'free_cashflow': 90_000_000,
            'roic': 14, 'wacc': 10, 'contracted_revenue': 92, 'payout': 60, 'operating_margin': 21})
        with app.connect() as c:
            app.add_snapshot(c, aid, 'quote', {'price': 24}, 'Fixture', app.today().isoformat())
            pts = [{'date': (app.today() - timedelta(days=250-i)).isoformat(), 'close': 17+i*.028} for i in range(250)]
            app.add_snapshot(c, aid, 'history', {'prices': pts}, 'Fixture', pts[-1]['date'])
        years = [{'date': f'{app.today().year-11+i}-12-31', 'net_income': 50_000_000*(1.12**i),
            'revenue': 500_000_000*(1.08**i), 'operating_cashflow': 100_000_000*(1.1**i), 'free_cashflow': 40_000_000*(1.1**i)} for i in range(11)]
        research.action(app, '/api/issuer/financials', {'asset_id': aid, 'data': {'symbol': ticker+'.SA', 'currency': 'BRL',
            'years': years, 'source_url': 'https://example.org/relatorio-ficticio'}})
        a = app.state()['assets'][0]
        profile = {'symbol': ticker+'.SA', 'name': name, 'sector': 'Energia elétrica', 'industry': 'Geração e transmissão',
            'description': 'Empresa fictícia para verificar a interface. Atua na geração e transmissão de energia, com contratos de longo prazo. Os números desta demonstração são inventados.',
            'cnpj': '', 'website': 'https://example.org', 'source_url': 'https://example.org/perfil-ficticio'}
        history.save(app, a, 'issuer_profile', history.validate_snapshot(app, 'issuer_profile', profile), 'Fixture')
        statement_rows=[{'date': row['date'], **dict.fromkeys(insights.FIELDS), **{k:v for k,v in row.items() if k!='date'},
                         'debt':200_000_000,'cash':80_000_000,'ebitda':200_000_000*(1.08**i)} for i,row in enumerate(years)]
        history.save(app,a,'issuer_statements',{'symbol':ticker+'.SA','currency':'BRL','annual':statement_rows,'quarterly':[],
            'sources':{'income-statement':'https://example.org/results','balance-sheet':'https://example.org/balance'},'source_url':'https://example.org/results'},'Fixture')
        history.save(app,a,'issuer_governance',{'symbol':ticker+'.SA','segment':'Novo Mercado · fictício','tag_along':100,'asof':app.today().isoformat(),
            'first_listed':'2000-01-03','source_url':'https://example.org/statute','rule_url':insights.B3_RULE,'method':'Direito fictício de 100% desta classe.'},'Fixture')
        ref=(app.today()-timedelta(days=1)).isoformat();prev=(app.today()-timedelta(days=31)).isoformat()
        def observation(current,previous,unit):return {'current':current,'previous':previous,'asof':ref,'previous_asof':prev,'source_url':'https://example.org/serie-ficticia',
            'source':'Exemplo fictício · não é cotação real','unit':unit,'frequency':'daily'}
        history.save(app,a,'issuer_exposure',{'symbol':ticker+'.SA','usd_role':'importer','commodities':['brent'],'asof':ref,
            'source_url':'https://example.org/exposicao-ficticia','note':'Exemplo fictício: expansão depende de equipamentos importados; combustível é um custo de parte da operação. Confira contratos e proteções cambiais.'},'Fixture')
        history.save(app,a,'issuer_drivers',{'symbol':ticker+'.SA','observations':{'rates':observation(12,12.5,'% a.a.'),'usd':observation(5.2,5.05,'R$/US$'),
            'brent':observation(82,78,'US$/barril')},'warnings':[],'source_url':'https://example.org/serie-ficticia'},'Fixture')
        qlast = (app.today().year*4 + (app.today().month-1)//3) - 1
        quarters = []
        for n in range(qlast-19, qlast+1):
            y, q = divmod(n, 4)
            quarters.append({'date': date(y, (q+1)*3, (31,30,30,31)[q]).isoformat(), 'net_income': 28_000_000+(n-qlast+19)*500_000, 'revenue': 250_000_000})
        research.action(app, '/api/issuer/quarters', {'asset_id': aid, 'data': {'symbol': ticker+'.SA', 'currency': 'BRL', 'quarters': quarters, 'source_url': 'https://example.org/trimestres'}})
        research.action(app, '/api/issuer/dividends', {'asset_id': aid, 'data': {'symbol': ticker+'.SA', 'years': [{'year': y, 'dy': 6+(y%3)*.4} for y in range(app.today().year-5, app.today().year)], 'method': 'Exemplo fictício: proventos brutos do ano / preço ao final do ano.', 'source_url': 'https://example.org/dy'}})
        market = {'symbol': ticker+'.SA', 'currency': 'BRL', 'first_trade': '2000-01-03', 'average_daily_value': 12_000_000,
            'sessions': 20, 'asof': (app.today()-timedelta(days=1)).isoformat(), 'source_url': 'https://example.org/precos'}
        history.save(app, a, 'issuer_market_history', history.validate_snapshot(app, 'issuer_market_history', market), 'Fixture')
        research.action(app, '/api/issuer/opinion', {'asset_id': aid, 'data': {'origin': 'manual', 'title': 'Perspectivas para o setor de energia · exemplo', 'text': 'Comentário fictício: os contratos de longo prazo trazem previsibilidade, enquanto expansão e dívida merecem acompanhamento.', 'author': 'Canal fictício de análise', 'date': app.today().isoformat(), 'url': 'https://example.org/opiniao-ficticia'}})
    reports={};sentiments={}
    for profile,titles in {
        'utility':['Tarifas e concessões: contratos merecem revisão · exemplo fictício','Expansão da capacidade de energia e investimento · exemplo fictício',
                   'Juros e financiamento das concessionárias · exemplo fictício','Demanda por energia e receita contratada · exemplo fictício'],
        'general':['Juros e custo de financiamento na economia · exemplo fictício','Dólar e preços dos equipamentos importados · exemplo fictício',
                   'Crédito e consumo das famílias · exemplo fictício','Petróleo e custos de transporte · exemplo fictício']}.items():
        items=[{'title':title,'url':f'https://example.org/news/{profile}/{i}','publisher':'Veículo fictício '+str(i%2+1),
                'published_at':app.now()} for i,title in enumerate(titles)]
        reports[profile]={'profile':profile,'headlines':items,'retrieved_at':app.now(),'sources':[],'errors':[],
                          'method':'Exemplo fictício para revisão visual; não são notícias reais.'}
        sentiments[profile]=market_ai.summarize_sentiment(reports[profile],items,
            [{'positive':0.,'negative':0.,'neutral':1.} for _ in items],app.now(),'Classificação fictícia','llm')
        sentiments[profile]['method']='DEMONSTRAÇÃO FICTÍCIA. '+sentiments[profile]['method']
    with app.connect() as c:
        app.write_cache(c,'news_reports',reports);app.write_cache(c,'ai_sentiment',sentiments)
    from aporte_brasil.company import fii_research
    from test_fii_research import fixture as fund_fixture
    for ticker,name,segment in [('TSTJ11','Imóveis Horizonte · FII fictício','Logística'),('TSTP11','Crédito Horizonte · FII fictício','Papel / recebíveis')]:
        with app.connect() as c:c.execute('INSERT INTO catalog VALUES (?,?,?,?,?,?,?)',(ticker,name,'fii',segment,0,'Fixture',app.now()))
        aid=app.mutate('/api/assets',{'ticker':ticker,'name':name,'asset_type':'fii'})['id']
        a=next(a for a in app.state()['assets'] if a['id']==aid)
        d=fund_fixture(ticker,segment);d['profile']['name']=name
        if ticker=='TSTP11':
            for row in d['monthly']:row.update(cri=90_000_000,property_assets=0)
            for row in d['quarterly']:row['properties']=[]
        fii_research.save(app,a,'fii_reports',d,'DEMONSTRAÇÃO FICTÍCIA · não são dados de fundo real')
        app.mutate('/api/manual',{'asset_id':aid,'kind':'risk','source':'Relatório fictício','asof':app.today().isoformat(),
            'distribution_cover':1.12,'top_tenant':15,'financial_vacancy':3,'credit_delinquency':.7,'top_credit':12,'ltv':55,'dy':10})
        with app.connect() as c:app.add_snapshot(c,aid,'quote',{'price':100},'DEMONSTRAÇÃO FICTÍCIA',app.today().isoformat())
        last=app.today().year*12+app.today().month-2
        items=[{'date':f'{n//12:04d}-{n%12+1:02d}-10','amount':.85,'type':'RENDIMENTO','estimated':False} for n in range(last-12,last+1)]
        fii_research.save(app,a,'fii_dividends',{'symbol':ticker,'items':items,'source_url':'https://example.org/renda-ficticia'},'DEMONSTRAÇÃO FICTÍCIA · rendimentos')
    items=[{'title':'Juros e crédito dos FIIs · notícia fictícia','url':'https://example.org/fii/news','publisher':'Veículo fictício','published_at':app.now()},
           {'title':'Demanda por galpões e renovação de contratos · exemplo fictício','url':'https://example.org/fii/demand','publisher':'Veículo fictício','published_at':app.now()}]
    with app.connect() as c:
        reports=app.read_cache(c,'news_reports',{});reports['fii']={'profile':'fii','headlines':items,'retrieved_at':app.now(),'sources':[],'errors':[],'method':'Demonstração fictícia'}
        app.write_cache(c,'news_reports',reports)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(dir=app.ROOT/'tests', prefix='tmp-test-buy-hold-ui-') as folder:
        app.DB_PATH = Path(folder)/'demo.sqlite3'
        app.VAULT = None
        fixture()
        port = int(sys.argv[1]) if len(sys.argv) > 1 else 18880
        server = ThreadingHTTPServer(('127.0.0.1', port), app.Handler)
        print(f'Demonstração fictícia: http://127.0.0.1:{port}/#sectors', flush=True)
        try: server.serve_forever()
        finally: server.server_close()
