"""Isolated browser fixture, with synthetic holdings only."""
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import tesouro


if __name__=='__main__':
    with tempfile.TemporaryDirectory(dir=app.ROOT/'tests',prefix='tmp-test-tesouro-ui-') as folder:
        app.DB_PATH=Path(folder)/'carteira.sqlite3'
        app.init_db()
        app.mutate('/api/settings',{'auto_refresh':False})
        for kind,maturity in (('ipca','2035-05-15'),('prefixado_cupom','2035-01-01'),('renda',''),('reserva','')):
            tesouro.save(app,{'kind':kind,'maturity':maturity,'conversion':'2030-01-15' if kind=='renda' else '',
                'institution':'Banco fictício para teste','invested':1000,'balance':1400,'balance_date':app.today().isoformat(),
                'quantity':1 if kind!='reserva' else None,'purchase_rate':6 if kind!='reserva' else None,
                'purchase_date':(app.today()-timedelta(days=800)).isoformat(),'single_lot':True,'balance_basis':'gross'})
        with app.connect() as c:
            for key,value in (('ipca',4.5),('selic',10)):
                c.execute('INSERT OR REPLACE INTO macro VALUES (?,?,?,?,?)',(key,value,app.today().isoformat(),'Valor fictício para teste',app.now()))
            app.write_cache(c,'tesouro_market',{'quotes':[{'kind':'ipca','maturity':'2035-05-15','asof':app.today().isoformat(),
                'buy_price':1450,'sell_price':1400,'base_price':1400,'buy_rate':6,'sell_rate':6.1}],
                'live_quotes':[{'kind':'ipca','maturity':'2035-05-15','asof':app.today().isoformat(),
                    'asof_at':app.today().isoformat()+'T15:26:44-03:00','reference':'current','source':tesouro.CURRENT_SOURCE,
                    'buy_price':1450,'sell_price':1400,'base_price':None,'buy_rate':6,'sell_rate':6.1}],
                'source':tesouro.SOURCE,'retrieved_at':app.now()})
        server=ThreadingHTTPServer(('127.0.0.1',8779),app.Handler)
        print('Synthetic Treasury UI: http://127.0.0.1:8779/#tesouro',flush=True)
        try:server.serve_forever()
        finally:server.server_close()
