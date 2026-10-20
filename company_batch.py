"""Background research for an explicit set of registered companies."""
import company_evidence
import company_history
import company_research
import factor_analysis
import market_ai


def validate(app,d):
    if not isinstance(d,dict) or set(d)!={'asset_ids','years','refresh','use_ai'} or not isinstance(d['asset_ids'],list) or not 1<=len(d['asset_ids'])<=150 or any(type(i) is not int or i<1 for i in d['asset_ids']) or len(set(d['asset_ids']))!=len(d['asset_ids']):raise ValueError('Selecione entre 1 e 150 empresas cadastradas, sem repetições.')
    if type(d['years']) is not int or d['years'] not in factor_analysis.WINDOWS or any(type(d[k]) is not bool for k in ('refresh','use_ai')):raise ValueError('Opções da análise em lote inválidas.')
    assets={a['id']:a for a in app.state()['assets']}
    if any(i not in assets or assets[i]['asset_type'] not in ('stock','foreign','global_stock') for i in d['asset_ids']):raise ValueError('O lote aceita apenas empresas acompanhadas, brasileiras ou stocks.')
    return dict(d)


def run(app,d):
    db_scope=str(app.DB_PATH)
    def ensure_scope():
        if str(app.DB_PATH)!=db_scope:raise ValueError('O armazenamento mudou; lote interrompido para preservar os dados.')
    report=dict(created_at=app.now(),years=d['years'],use_ai=d['use_ai'],refresh=d['refresh'],running=True,rows=[])
    def save():
        ensure_scope()
        with app.WRITE_LOCK,app.connect() as c:app.write_cache(c,'issuer_batch',report)
    save();total=len(d['asset_ids']);group_results={};shared={}
    for index,aid in enumerate(d['asset_ids'],1):
        ensure_scope()
        a=next((a for a in app.state()['assets'] if a['id']==aid),None)
        if not a:
            report['rows'].append(dict(asset_id=aid,ticker='Removida',status='skipped',warnings=['Empresa removida durante o lote.'],received=[],quality='incomplete',valuation='unknown',stress='incomplete',review='skipped'));save();continue
        row=dict(asset_id=aid,ticker=a['ticker'],status='done',warnings=[],received=[],review='not_requested')
        def step(label,fn):
            ensure_scope()
            market_ai.progress(f'{index}/{total} · {a["ticker"]} · {label}')
            try:
                result=fn() or {};row['received'].extend(result.get('received',[]));row['warnings'].extend(result.get('warnings',[]));return result
            except Exception as exc:
                row['warnings'].append(str(exc) if isinstance(exc,ValueError) else label+': fonte indisponível; dados anteriores preservados.');return None
        if d['refresh']:
            step('Indicadores, balanços e ficha',lambda:company_research.action(app,'/api/issuer/history',dict(asset_id=aid)))
            step('Publicações recentes',lambda:company_history.fetch_opinions(app,company_research.asset(app,aid)))
            a=company_research.asset(app,aid)
            if factor_analysis.market(a):
                group=factor_analysis.group(a)
                if group not in group_results:
                    group_results[group]=step('Fatores, ciclos e recuperação',lambda:factor_analysis.refresh(app,a,d['years'],asset_ids=d['asset_ids'],shared=shared))
                else:
                    result=group_results[group]
                    if result:row['received'].extend(result.get('received',[]));row['warnings'].extend(result.get('warnings',[]))
                    else:row['warnings'].append('Histórico do grupo indisponível nesta consulta; dados anteriores preservados.')
            else:row['warnings'].append('Fatores e crises quantitativos disponíveis para B3 e stocks dos EUA; demais fundamentos são analisados.')
        if d['use_ai']:
            got=step('Leitura com IA local',lambda:company_research.analyze(app,dict(asset_id=aid,fetch=False)) or {'received':['Leitura com IA local']})
            row['review']='done' if got else 'failed'
        current=company_research.asset(app,aid);c=company_evidence.context(current,app.today())
        if c['quality']=='incomplete':row['warnings'].append('Avaliação de qualidade ainda incompleta; alguns indicadores não estão disponíveis.')
        if c['valuation']=='unknown':row['warnings'].append('Comparação de valor pendente; confira dados e premissas do modelo fundamental.')
        row.update(quality=c['quality'],valuation=c['valuation'],stress=c['stress'],status='partial' if row['warnings'] else 'done')
        row['warnings']=[str(w)[:500] for w in row['warnings'][:20]];row['received']=list(dict.fromkeys(row['received']))[:40]
        report['rows'].append(row);save()
    report['running']=False;report['finished_at']=app.now();save()
    partial=sum(r['status']!='done' for r in report['rows'])
    market_ai.progress(f'Lote concluído: {total} empresas; {partial} com pendências. Veja a cobertura e as fontes por empresa.')
