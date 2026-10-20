"""Hourly, opt-in monitoring. Public Brazil news continues while the vault is locked."""
from datetime import datetime,timezone,timedelta
import json
import threading
import time

import desktop_notifications
import extra_sources
import market_ai
import market_brief
import market_news
import market_signals

DEFAULTS={'enabled':False,'brazil_news':True,'prices':True,'windows_notifications':True}
LOCK=threading.RLock()
CYCLE_LOCK=threading.Lock()
STATE={'running':False,'progress':'Monitor desativado.','error':'','last_attempt':None,
       'last_finished':None,'next_check':None,'public_only':False,'alerts':[],'market':None}
CONFIG=dict(DEFAULTS)
BASELINE={}
ENABLED_AT=None
URL='http://127.0.0.1:8765/#news'
INTERVAL=3600


def unlocked(app):
    return app.VAULT is None or app.VAULT.key is not None


def status():
    with LOCK:return json.loads(json.dumps({**STATE,'settings':CONFIG,'interval_minutes':60}))


def public_state(app,c):
    saved={**DEFAULTS,**app.read_cache(c,'monitor_settings',{})}
    current=status();current['settings']=saved
    if current['market'] is None:current['market']=app.read_cache(c,'monitor_market',None)
    if not current['alerts']:current['alerts']=app.read_cache(c,'monitor_alerts',[])
    return current


def configure(app,d):
    if not isinstance(d,dict) or set(d)!=set(DEFAULTS) or any(type(v) is not bool for v in d.values()):
        raise ValueError('Confira as opções do monitor.')
    if d['enabled'] and not (d['brazil_news'] or d['prices']):raise ValueError('Escolha notícias ou preços para acompanhar.')
    with app.WRITE_LOCK,app.connect() as c:app.write_cache(c,'monitor_settings',dict(d))
    with LOCK:
        if d['enabled'] and not CONFIG['enabled']:
            global ENABLED_AT
            ENABLED_AT=datetime.now(timezone.utc).isoformat()
            BASELINE.clear()
            STATE.update(last_attempt=None,next_check=None)
        CONFIG.update(d)
        if not d['enabled']:STATE['next_check']=None
        STATE['progress']='Consultas a cada hora enquanto o aplicativo estiver rodando.' if d['enabled'] else 'Monitor desativado.'
    return status()


def news_changes(previous,current,enabled_at):
    old={e['id'] for e in (previous or {}).get('events',[])}
    messages=[]
    for e in current['events']:
        if e['id'] in old or e['certainty']!='reported':continue
        if not enabled_at or datetime.fromisoformat(e['headline']['published_at'])<datetime.fromisoformat(enabled_at):continue
        messages.append({'kind':'news','key':e['id'],'title':'Aporte Brasil · notícia para conferir',
            'body':e['headline']['title'][:220]+'. Veja fontes e possíveis efeitos; direção ainda depende do contexto.'})
    if previous and previous.get('tone') not in (None,'unknown') and current['tone']!='unknown':
        if current['tone']!=previous['tone'] and abs(current['score']-previous['score'])>=.25:
            messages.append({'kind':'sentiment','key':current['asof'],'title':'Aporte Brasil · mudou o tom das notícias',
                'body':'O sentimento das últimas 24 horas mudou para '+{'positive':'positivo','negative':'negativo','neutral':'equilibrado'}[current['tone']]+'. Isso não determina o retorno da bolsa.'})
    return messages


def remember(app,messages):
    with LOCK:
        seen={a['key'] for a in STATE['alerts']}
        new=[m for m in messages if m['key'] not in seen
             and CONFIG['prices' if m['kind']=='price' else 'brazil_news']]
        deliver=CONFIG['enabled'] and CONFIG['windows_notifications']
        for m in new:m.update(created_at=app.now(),notification='pending' if deliver else 'disabled')
        STATE['alerts']=(new+STATE['alerts'])[:100]
    # At most one native toast per cycle, grouping material changes.
    if new and CONFIG['enabled'] and CONFIG['windows_notifications']:
        try:
            desktop_notifications.notify(new[0]['title'],new[0]['body']+(f" Mais {len(new)-1} mudança(s) no aplicativo." if len(new)>1 else ''),URL)
            for m in new:m['notification']='submitted'
        except Exception:
            for m in new:m['notification']='failed'
            with LOCK:STATE['error']='Alerta guardado, mas o Windows não aceitou a notificação. Confira as configurações de notificações.'


def update_prices(app):
    if not unlocked(app):return []
    state=app.state()
    candidates=[a for a in state['assets'] if a['asset_type']=='stock' and a['verified']
        and sum(m['value'] is not None for m in a['valuation']['methods'])>=2
        and (a['position']['quantity']>0 or a['valuation'].get('has_saved'))][:40]
    for a in candidates:
        if not unlocked(app):return []
        with LOCK:STATE['progress']='Conferindo cotação de '+a['ticker']+'…'
        try:
            result=extra_sources.yahoo(a['ticker'],app.request_json,app.today,False)
            if 'quote' not in result:continue
            data,ref,source=result['quote']
            with app.WRITE_LOCK,app.connect() as c:
                current=c.execute('SELECT ticker,archived FROM assets WHERE id=?',(a['id'],)).fetchone()
                if current and not current['archived'] and current['ticker']==a['ticker']:
                    app.add_snapshot(c,a['id'],'quote',data,source,ref)
        except Exception:
            with LOCK:STATE['error']='Algumas cotações não foram obtidas; as referências anteriores foram preservadas.'
    if not unlocked(app):return []
    updated=app.state();ids={a['id'] for a in candidates};messages=[]
    labels={'below':'abaixo dos cenários','within':'dentro da faixa dos cenários','above':'acima dos cenários',
            'expensive':'muito acima dos cenários','mixed':'modelos divergentes','insufficient':'sem base suficiente'}
    for a in updated['assets']:
        if a['id'] not in ids:continue
        current=a['valuation']['comparison']['classification'];old=BASELINE.get(a['ticker'])
        if old and old!=current and current not in ('mixed','insufficient'):
            messages.append({'kind':'price','key':a['ticker']+':'+current+':'+app.now(),
                'title':'Aporte Brasil · revisar preço de '+a['ticker'],
                'body':'Mudou de '+labels[old]+' para '+labels[current]+'. Resultado pelas premissas salvas; confira os modelos antes de decidir.'})
        BASELINE[a['ticker']]=current
    return messages


def cycle(app):
    if not CYCLE_LOCK.acquire(blocking=False):raise ValueError('Uma consulta do monitor já está em andamento.')
    try:
        with LOCK:STATE.update(running=True,error='',last_attempt=app.now(),progress='Consultando notícias recentes…',public_only=not unlocked(app))
        if unlocked(app):
            with app.connect() as c:
                saved_market=app.read_cache(c,'monitor_market',None)
                saved_alerts=app.read_cache(c,'monitor_alerts',[])
            with LOCK:
                if STATE['market'] is None:STATE['market']=saved_market
                if not STATE['alerts']:STATE['alerts']=saved_alerts
        messages=[]
        if CONFIG['brazil_news']:
            clock=datetime.now(timezone.utc);feed=market_brief.fetch('general',clock)
            items=market_news.recent(feed['headlines'],clock)
            prepared=app.ROOT/'data'/'ai_models'
            cache=prepared if (prepared/('models--'+market_ai.HF_MODEL.replace('/','--'))/'snapshots'/market_ai.HF_REVISION/'pytorch_model.bin').is_file() else app.DB_PATH.parent/'ai_models'
            sentiment=None
            try:
                rows=market_ai.hf_classify([n['title'] for n in items],cache) if items else []
                sentiment=market_ai.summarize_sentiment(feed,items,rows,app.now(),market_ai.HF_MODEL,'huggingface')
            except Exception:
                with LOCK:STATE['error']='Notícias consultadas; sentimento não calculado. Confira o modelo local e suas dependências.'
            current=market_news.overview(feed,sentiment,clock)
            with LOCK:previous=STATE['market'];STATE['market']=current
            messages+=news_changes(previous,current,ENABLED_AT)
            if unlocked(app):
                with app.WRITE_LOCK,app.connect() as c:
                    app.write_cache(c,'monitor_market',current)
        if CONFIG['prices'] and unlocked(app):messages+=update_prices(app)
        if not unlocked(app):
            BASELINE.clear()
        remember(app,messages)
        if unlocked(app):
            with app.WRITE_LOCK,app.connect() as c:app.write_cache(c,'monitor_alerts',STATE['alerts'])
        with LOCK:
            STATE.update(last_finished=app.now(),next_check=(datetime.now(timezone.utc)+timedelta(seconds=INTERVAL)).isoformat() if CONFIG['enabled'] else None,
                progress=('Consulta concluída. Próxima verificação em uma hora.' if CONFIG['enabled'] else 'Consulta concluída. Acompanhamento por hora desativado.')+(' Carteira bloqueada: somente notícias públicas.' if not unlocked(app) else ''))
    except Exception as exc:
        with LOCK:
            STATE['error']=str(exc) if isinstance(exc,ValueError) else 'Consulta interrompida; os dados anteriores foram preservados.'
            STATE['next_check']=(datetime.now(timezone.utc)+timedelta(seconds=INTERVAL)).isoformat() if CONFIG['enabled'] else None
    finally:
        with LOCK:STATE['running']=False
        CYCLE_LOCK.release()
    return status()


def start_cycle(app):
    with LOCK:
        if STATE['running']:raise ValueError('O monitor já está consultando as fontes.')
        STATE.update(running=True,error='',progress='Iniciando consulta…')
    threading.Thread(target=cycle,args=(app,),daemon=True).start()
    return status()


def start_worker(app,stop,port):
    global URL
    URL=f'http://127.0.0.1:{port}/#news'
    def run():
        global ENABLED_AT
        while not stop.wait(15):
            try:
                if unlocked(app):
                    with app.connect() as c:saved={**DEFAULTS,**app.read_cache(c,'monitor_settings',{})}
                    with LOCK:
                        if saved['enabled'] and not CONFIG['enabled']:ENABLED_AT=app.now()
                        CONFIG.update(saved)
                current=status()
                due=not current['next_check'] or datetime.now(timezone.utc)>=datetime.fromisoformat(current['next_check'])
                if current['settings']['enabled'] and due and not current['running'] and not app.JOB['running'] and not market_ai.job_state()['running'] and not market_signals.job_state()['running']:
                    cycle(app)
            except Exception:
                # A lock can occur between checking key and acquiring the DB.
                # Never authenticate, extend idle sessions or unlock automatically.
                continue
    threading.Thread(target=run,daemon=True).start()


def action(app,path,d):
    if path=='/api/monitor/settings':return configure(app,d)
    if path=='/api/monitor/check':
        if d:raise ValueError('A consulta usa apenas as opções salvas.')
        return start_cycle(app)
    if path=='/api/monitor/test':
        if d:raise ValueError('O teste não aceita texto nem comandos externos.')
        return desktop_notifications.notify('Aporte Brasil · teste de notificação',
            'Notificações de pesquisa disponíveis. Nenhuma operação financeira foi realizada.',URL)
    raise ValueError('Ação do monitor inválida.')
