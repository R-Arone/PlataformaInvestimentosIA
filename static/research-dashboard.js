'use strict';
const researchRenderBefore=render,researchRowsBefore=simpleAssetRows,researchTableBefore=stockTable,
 researchDriversBefore=companyDriversPane,researchMarketBefore=longTermMarketPanel,researchResultBefore=longTermResult,researchPollBefore=aiPoll;
let researchSeen='';

function researchScore(a){
 if(!['stock','foreign','global_stock','fii'].includes(a.asset_type))return null;
 const study=a.fii_research?.study||a.company_research?.study;
 const checks=(study?.groups||[]).filter(g=>g.key!=='price').flatMap(g=>g.checks||[]).filter(c=>c.status!=='na'&&c.scope!=='price');
 const measured=checks.filter(c=>['pass','fail'].includes(c.status));
 return measured.length?100*measured.filter(c=>c.status==='pass').length/measured.length:null;
}
function researchCoverage(a){if(!['stock','foreign','global_stock','fii'].includes(a.asset_type))return 'Nota de empresa não aplicável';const s=a.fii_research?.study||a.company_research?.study,c=s?.counts;if(!c)return 'Sem critérios medidos';const total=c.pass+c.fail+c.unknown;return `${c.pass+c.fail}/${total} conhecidos · ${c.fail} negativos · ${c.unknown} sem dados`;}
function researchReference(a){const p=a.value_reading,r=p?.reading;
 if(!r)return '<span class="muted">Sem referência aplicável / premissas a conferir</span>';
 return `${tag(esc(r.label),r.status==='cheap'?'good':r.status==='expensive'?'bad':'warn')}${p.reference>0?`<b>${money(p.reference)}</b><small>Teto: ${money(p.ceiling)} · ${esc(p.method)} · ${dt(p.asof)}</small>`:''}${r.disagreement?'<small>Métodos divergem; conferir premissas</small>':''}`;
}
function decisionSectorScore(a){const r=a.sector_rating;return r?.score!=null?button('sector-rating-open','Setor '+fmt(r.score,0)+'/100','text-button',`data-id="${a.id}"`)+`<small>${esc(r.label)} · premissa estrutural</small>`:'<small>Sem nota estrutural de setor aplicável</small>';}
function researchFactors(a){
 const f=a.company_research?.factor_analysis;if(!f?.supported)return '<span class="muted">Critérios do produto</span>';
 const rows=(f.company||[]).filter(r=>['positive','negative'].includes(r.status)).map(r=>({key:r.key,status:r.status,text:r.label+' '+(r.status==='positive'?'↑':'↓')+' · mesmo mês'}));
 for(const factor of f.delayed?.factors||[]){if(rows.some(r=>r.key===factor.key))continue;const valid=factor.models.filter(m=>['positive','negative'].includes(m.status));if(!valid.length)continue;
  const signs=new Set(valid.map(m=>m.status));rows.push({key:factor.key,status:signs.size>1?'mixed':valid[0].status,lag:true,text:factor.label+(signs.size>1?' · sinais distintos':' '+(valid[0].status==='positive'?'↑':'↓')+' · '+valid.map(m=>m.lag_months).join('/')+' m')});}
 const unknown=(f.company||[]).every(r=>r.status==='insufficient')?'? Histórico insuficiente':(f.company||[]).some(r=>r.status==='stale')?'? Atualizar histórico':'? Sem associação demonstrada';
 return rows.length?`<div class="research-factors">${rows.slice(0,3).map(r=>button('factor-open',esc(r.text),'research-factor association-'+r.status,`data-id="${a.id}" data-research-factor="true" data-research-lag="${!!r.lag}" title="${r.status==='positive'?'Associação positiva: movimentos na mesma direção':r.status==='negative'?'Associação negativa: movimentos em direções opostas':'Sinais diferentes conforme o atraso'}. Não é nota de compra."`)).join('')}</div>`:button('factor-open',unknown,'research-factor association-unknown',`data-id="${a.id}"`);
}
function researchColumns(html){
 const t=document.createElement('template');t.innerHTML=html;
 for(const table of $$('table',t.content)){
  if(table.dataset.researchColumns)continue;
  const rows=$$('tbody > tr',table).filter(r=>$('[data-action=detail][data-id]',r));if(!rows.length)continue;
  table.dataset.researchColumns='true';
  const head=$('thead tr',table);if(head)head.firstElementChild.insertAdjacentHTML('afterend','<th>Nota de qualidade</th><th>Preço de referência</th><th>Fatores associados</th>');
  for(const row of rows){const a=assetById($('[data-action=detail]',row).dataset.id);if(!a)continue;const score=researchScore(a);
   row.firstElementChild.insertAdjacentHTML('afterend',`<td data-label="Nota de qualidade">${score===null?'—':fmt(score,0)+'/100'}<small>Critérios conhecidos · ${researchCoverage(a)}</small>${decisionSectorScore(a)}</td><td data-label="Preço de referência">${researchReference(a)}</td><td data-label="Fatores associados">${researchFactors(a)}</td>`);}
 }
 return t.innerHTML;
}
simpleAssetRows=function(){return researchColumns(researchRowsBefore());};
stockTable=function(assets,mode='watchlist'){const html=researchTableBefore(assets,mode);return mode==='portfolio'?researchColumns(html):html;};

function researchBatchPanel(){const r=S.ai.company_batch;if(!r)return '';
 return `<details class="panel"><summary>Última análise de ativos · ${r.rows.length} resultado(s)</summary><p class="date-source">${localTime(r.created_at)} · ${r.running?'Em andamento':'Etapas encerradas'}</p><div class="table-wrap"><table><thead><tr><th>Ativo</th><th>Etapas</th><th>Nota / preço de referência</th><th>Pendências</th></tr></thead><tbody>${r.rows.map(row=>{const a=assetById(row.asset_id),score=a?researchScore(a):null;return `<tr><td>${esc(row.ticker)}${a?button('detail','Ver análise','secondary',`data-id="${a.id}"`):''}</td><td>${esc(row.status==='done'?'Etapas concluídas':row.status==='skipped'?'Não analisado':'Com pendências')}<small>IA: ${esc({done:'leitura salva',failed:'indisponível',not_requested:'não solicitada',na:'método próprio do produto'}[row.review]||'pendente')}</small></td><td>${score===null?'Sem nota de empresa':fmt(score,0)+'/100'}${a?'<small>'+researchReference(a)+'</small>':''}</td><td><details><summary>${row.warnings.length} observação(ões)</summary>${row.received.map(s=>`<p>Recebido: ${esc(s)}</p>`).join('')}${row.warnings.map(s=>`<p>${esc(s)}</p>`).join('')}</details></td></tr>`;}).join('')}</tbody></table></div></details>`;
}

function researchJob(){const j=S.ai.job;return `<p class="notice research-job" role="status" ${j.running||j.error?'':'hidden'}>${esc(j.error||j.progress)}</p>`;}
function researchStatus(){for(const e of $$('.research-job')){const j=S.ai.job;e.hidden=!j.running&&!j.error;e.textContent=j.error||j.progress;}}
aiPoll=async function(){await researchPollBefore();if(!S)return;researchStatus();const j=S.ai.job;if(!j.running&&j.kind==='market_batch'&&j.id!==researchSeen){researchSeen=j.id;toast(j.error||'Análise de todos os setores concluída; confira a cobertura e as fontes.');}};

function researchMacro(context){const rows=(context?.indicators||[]).filter(i=>i.available);
 if(!rows.length)return '<p class="notice">Atualize os indicadores para ver Selic, juros dos EUA, inflação, petróleo, minério, cobre e soja.</p>';
 return `<h3>Juros e commodities</h3><div class="research-indicators">${rows.map(i=>{const o=i.observation;return `<article><b>${esc(i.label)}</b><strong>${fmt(o.value,2)} <small>${esc(i.unit)}</small></strong><span>${o.direction==='up'?'↑':o.direction==='down'?'↓':'→'} ${fmt(o.difference,2)} ${esc(o.difference_unit)} desde ${dt(o.previous_date)}</span><small>${dt(o.date)} · ${i.frequency==='monthly'?'série mensal':'série diária'}${o.fresh?'':' · atualizar'} · <a href="${esc(i.source_url)}" target="_blank" rel="noreferrer">Fonte ↗</a></small></article>`;}).join('')}</div>`;
}
longTermMarketPanel=function(context){return researchMarketBefore(context).replace('</h2>','</h2><div class="actions">'+button('research-market-open','Analisar cenário atual','secondary',`data-scope="tracked" ${S.ai.job.running?'disabled':''}`)+'</div>').replace('<button type="button" class="button secondary" data-action="long-term-market-refresh"',researchMacro(context)+'<button type="button" class="button secondary" data-action="long-term-market-refresh"').replaceAll('Atualizar bolsa e dólar','Atualizar indicadores').replaceAll('Consultando bolsa e dólar','Consultando indicadores');};

function researchMarketReport(){const r=S.ai.market_batch;if(!r)return '';
 const claim=(c,sources)=>`<p>${esc(c.text)} ${c.source_ids.map(id=>sources.find(s=>s.id===id)).filter(Boolean).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noreferrer">[${s.id}]</a>`).join(' ')}</p>`;
 return `<section class="panel research-market-report"><h2>Análise dos setores · ${r.rows.length}/${r.requested.length}</h2><p class="date-source">${localTime(r.created_at)} · ${r.use_ai?'Interpretação com IA solicitada':'Notícias e canais econômicos'} · ${r.research?'Pesquisa ampliada solicitada':'Fontes públicas'}</p>${r.warnings.length?`<details><summary>Pendências gerais (${r.warnings.length})</summary>${r.warnings.map(s=>`<p>${esc(s)}</p>`).join('')}</details>`:''}<div class="research-sector-grid">${r.rows.map(row=>`<details><summary>${esc(row.label)} · ${row.status==='done'?'consultado':'com pendências'}</summary>${row.reading?claim(row.reading.summary,row.sources)+['opportunities','risks','watch'].map(k=>`<h4>${{opportunities:'Oportunidades para estudar',risks:'Riscos',watch:'Acompanhar'}[k]}</h4>${row.reading[k].map(c=>claim(c,row.sources)).join('')}`).join(''):'<p>Sem interpretação generativa nesta consulta.</p>'}${(row.channels||[]).map(c=>`<p><b>${esc(c.label)} · ${dt(c.asof)}:</b> se o movimento continuar, ${esc(c.text)} · <a href="${esc(c.source_url)}" target="_blank" rel="noreferrer">Fonte ↗</a></p>`).join('')}${row.headlines.map(n=>`<p><a href="${esc(n.url)}" target="_blank" rel="noreferrer">${esc(n.title)}</a></p>`).join('')}${row.warnings.map(s=>`<p class="notice warn">${esc(s)}</p>`).join('')}<p class="form-hint">Leitura condicional; não é previsão de retorno ou ordem de compra.</p></details>`).join('')}</div></section>`;
}

function researchSectorPlan(p){const rows=p.sector_context||[];if(!rows.length)return '';
 return `<section class="panel"><h2>Setores e cenário na decisão do aporte</h2><p>Contexto para conferir a tese. Notícias e correlações não substituem qualidade, preço e limites nem alteram o aporte por conta própria.</p><div class="research-sector-grid">${rows.map(r=>`<article><h3>${esc(r.label)}</h3><p>${r.tickers.map(esc).join(' · ')} · ${money(r.amount)} sugeridos</p>${r.research?.reading?`<p>${esc(r.research.reading.summary.text)}</p><small>Leitura: ${dt(r.research.asof)}</small>`:'<p class="muted">Sem leitura recente deste setor. Use Analisar cenário atual para consultar todos os setores acompanhados.</p>'}${r.factors.slice(0,6).map(f=>`<p>${esc(f.ticker)} · ${esc(f.label)}: ${esc({support:'movimento associado historicamente a apoio',pressure:'movimento associado historicamente a pressão',flat:'movimento estável'}[f.pressure])} · ${dt(f.asof)}.</p>`).join('')}</article>`).join('')}</div>${simpleViewLink('news','Ver fontes e análise de mercado')}</section>`;
}
longTermResult=function(p){return researchResultBefore(p)+researchSectorPlan(p);};

function researchLagPane(a){const d=a.company_research?.factor_analysis?.delayed;if(!d)return '';
 return `<section class="factor-analysis research-lags"><h3>Relações com atraso e períodos de subida/queda</h3><p>${esc(d.method)}</p><p class="form-hint">${esc(d.note)}</p>${d.factors.map(f=>`<details><summary>${esc(f.label)} · ver atrasos fixos</summary><div class="table-wrap"><table><thead><tr><th>Atraso</th><th>Amostra / período</th><th>Associação controlada</th><th>Quando o fator subiu</th><th>Quando o fator caiu</th></tr></thead><tbody>${f.models.map(m=>`<tr><td>${m.lag_months===0?'Mesmo mês':m.lag_months+' meses'}</td><td>${m.n} meses<small>${m.start||'—'} a ${m.end||'—'}</small></td><td>${esc(sensitivityFactorLabels[m.status]||m.status)}<small>Beta padronizado: ${m.beta==null?'—':fmt(m.beta,2)}${m.interval?' · intervalo: '+m.interval.map(v=>fmt(v,2)).join(' a '):''}</small></td>${[1,-1].map(sign=>{const g=m.groups.find(g=>g.direction===sign);return `<td>${g?.sufficient?pct(g.median_return):'Dados insuficientes'}<small>${g?.n||0} observações · retorno mensal mediano${g?.sufficient?'<br>Diferença vs. índice: '+fmt(g.median_excess,2)+' p.p.':''}</small></td>`;}).join('')}</tr>`).join('')}</tbody></table></div><p><a href="${esc(f.source_url||'#')}" target="_blank" rel="noreferrer">Fonte do fator ↗</a></p></details>`).join('')}${d.references.map(r=>`<p><a href="${esc(r.url)}" target="_blank" rel="noreferrer">${esc(r.title)} ↗</a></p>`).join('')}</section>`;
}
companyDriversPane=function(a){return researchDriversBefore(a)+researchLagPane(a);};

render=function(){researchRenderBefore();if(!S||document.body.classList.contains('vault-locked'))return;
 if(['watchlist','portfolio'].includes(view)){
  $('.page-heading .actions')?.insertAdjacentHTML('beforeend',button('research-batch-open','Analisar todos os ativos','secondary',S.ai.job.running?'disabled':''));
  $('#task-navigation')?.insertAdjacentHTML('afterend',researchJob()+researchBatchPanel());
 }
 if(view==='news'){
  $('.page-heading .actions')?.insertAdjacentHTML('beforeend',button('research-market-open','Analisar todos os setores','',`data-scope="all" ${S.ai.job.running?'disabled':''}`));
  $('#task-navigation')?.insertAdjacentHTML('afterend',researchJob()+researchMarketReport());
 }
 if(view==='long-term'){
  $('#task-navigation')?.insertAdjacentHTML('afterend',researchJob());
 }
};

document.addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;
 if(b.dataset.action==='sector-rating-open'){
  const a=assetById(b.dataset.id),r=a.sector_rating,g=a.risk_group,held=S.assets.filter(x=>x.risk_group?.key===g.key&&x.value>0),total=S.assets.reduce((s,x)=>s+x.value,0),value=held.reduce((s,x)=>s+x.value,0);
  modal('Nota estrutural do setor · '+r.label,`<p><b>${fmt(r.score,0)}/100 · ${esc(r.assessment)}</b></p><p>${esc(r.note)}</p><div class="mini-stat"><b>Grupo de concentração: ${esc(g.label)}</b><p>${held.map(x=>esc(x.ticker)).join(' · ')||'Sem posição neste grupo'} · ${money(value)} · ${pct(total?value/total*100:0)} da carteira negociada. Limite: ${pct(S.settings.sector_limit)}.</p></div>${r.dimensions.map(d=>`<div class="mini-stat"><span>${esc(d.label)}</span><b>${d.value}/${d.maximum}</b></div>`).join('')}<ul>${r.risks.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p>A nota participa com 10% do contrafluxo de ações/FIIs. Sem nota aplicável, o componente é neutro (50); não substitui a avaliação da empresa.</p>${r.references.map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.title)} ↗</a></p>`).join('')}`);
 }
 if(b.dataset.action==='factor-open'){const target=b.dataset.researchLag==='true'?'.research-lags':'.factor-analysis';$('#modal '+target)?.scrollIntoView({block:'start'});}
 if(b.dataset.action==='research-batch-open'){
  const choices=[['all','Toda a lista ('+S.assets.length+')'],['held','Só a carteira ('+S.assets.filter(a=>a.position.quantity>0).length+')'],['visible','Ativos do filtro atual ('+simpleAssets().length+')']];
  modal('Analisar ativos de uma vez',`<form id="research-batch-form"><p>Atualiza dados e executa a avaliação adequada a cada produto. Empresas: fundamentos, fatores e parecer opcional. FIIs: informes e rendimentos. ETFs/Bitcoin: preços e critérios do produto. Saldos de renda fixa continuam informados pelo extrato.</p><div class="form-grid">${select('scope','Ativos',choices,view==='portfolio'?'held':'all')}${select('years','Histórico de fatores para empresas',[[5,'5 anos'],[10,'10 anos'],[20,'20 anos']],10)}</div><label class="check"><input name="refresh" type="checkbox" checked>Atualizar fontes públicas</label><label class="check"><input name="use_ai" type="checkbox">Parecer das empresas com a IA configurada</label>${footer('Analisar seleção')}</form>`);
  wireForm('#research-batch-form',async(d,f)=>{const assets=d.scope==='visible'?simpleAssets():S.assets.filter(a=>d.scope!=='held'||a.position.quantity>0);if(!assets.length)throw Error('Nenhum ativo nesta seleção.');S.ai.job=await api('/api/issuer/batch',{asset_ids:assets.map(a=>a.id),years:Number(d.years),refresh:f.elements.refresh.checked,use_ai:f.elements.use_ai.checked,all_types:true});$('#modal').close();render();aiPoll();});
 }
 if(b.dataset.action==='research-market-open'){
  modal('Analisar mercado e setores',`<form id="research-market-form"><p>Consulta indicadores, notícias e canais econômicos em uma rodada. A pesquisa ampliada usa a conexão de busca já configurada e não envia posições nem valores da carteira.</p><div class="form-grid">${select('scope','Alcance',[['selected','Setor selecionado'],['tracked','Todos os setores acompanhados'],['all','Todos os setores do catálogo']],b.dataset.scope||'tracked')}</div><label class="check"><input name="use_ai" type="checkbox">Interpretar cada setor com IA local</label><label class="check"><input name="research" type="checkbox" ${S.ai.settings.has_search_key?'':'disabled'}>Incluir pesquisa geral ampliada na internet</label>${S.ai.settings.has_search_key?'':'<p class="form-hint">A pesquisa ampliada exige a chave de busca nas configurações de IA. Notícias públicas e indicadores funcionam sem ela.</p>'}${footer('Analisar mercado')}</form>`);
  wireForm('#research-market-form',async(d,f)=>{S.ai.job=await api('/api/ai/market-batch',{scope:d.scope,profile:newsProfile||'general',use_ai:f.elements.use_ai.checked,research:f.elements.research.checked});$('#modal').close();render();aiPoll();});
 }
});

document.addEventListener('change',e=>{if(e.target.form?.id==='research-market-form'&&e.target.name==='research'&&e.target.checked)e.target.form.elements.use_ai.checked=true;});

const decisionResultBefore=longTermResult;
function decisionCorrelation(p){return `<span class="${p.correlation>=0?'positive':'negative'}">${p.correlation>=0?'+':''}${fmt(p.correlation,2)}</span>`;}
longTermResult=function(p){const rows=p.sector_allocation||[];return decisionResultBefore(p)+(rows.length?`<section class="panel decision-sector-allocation"><h2>Como este aporte muda os setores</h2><p>Posições já existentes e compras sugeridas, sobre o valor efetivamente investido. O saldo a decidir não dilui concentração. Exposições equivalentes compartilham o limite; composição desconhecida de ETF fica sem rateio entre setores.</p><div class="table-wrap"><table><thead><tr><th>Grupo de risco</th><th>Já tenho</th><th>Peso antes</th><th>Aporte</th><th>Peso depois / limite</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.label)}</td><td>${r.tickers.map(esc).join(' · ')||'Sem posição'}</td><td>${pct(r.before_weight)}</td><td>${money(r.contribution)}</td><td>${pct(r.after_weight)} / ${pct(r.limit)}${r.after_weight>r.limit+.001?' · posição existente acima do limite':''}</td></tr>`).join('')}</tbody></table></div></section>`:'');};
