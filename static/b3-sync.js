'use strict';
// B3 por arquivo: eventos corporativos na prévia e conferência com o extrato de Posição (somente leitura).
const syncImports=importsView,syncPreview=b3Preview,syncBind=bindForms,syncDetail=detail;
const corporateLabel={split:'Desdobramento',grouping:'Grupamento',bonus:'Bonificação em ativos',fraction_out:'Fração retirada para leilão'};
const positionStatus={ok:['Confere','good'],different:['Quantidade diferente','warn'],only_b3:['Só na B3','warn'],only_local:['Só na carteira local','warn']};
const qty=v=>v==null?'—':Number(v).toLocaleString('pt-BR',{maximumFractionDigits:8});
let positionResult=null,positionUpload={},positionOptions={};

async function readB3Upload(file){
 if(!file)throw Error('Selecione o arquivo.');const lower=file.name.toLowerCase();
 if(lower.endsWith('.xlsx')){if(file.size>8_000_000)throw Error('Use Excel de até 8 MB.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));return {xlsx:btoa(binary),filename:file.name};}
 if(lower.endsWith('.csv')){if(file.size>4_000_000)throw Error('Use CSV de até 4 MB.');const buffer=await file.arrayBuffer();let text;try{text=new TextDecoder('utf-8',{fatal:true}).decode(buffer);}catch{text=new TextDecoder('windows-1252').decode(buffer);}return {csv:text,filename:file.name};}
 throw Error('Exporte como .xlsx ou CSV. Arquivos .xls antigos precisam ser salvos como .xlsx.');
}
function corporateKey(r){return [r.ticker,r.date,r.institution,r.event].join('|');}

function eventSummary(rows){if(!rows?.length)return '';return `<div class="notice warn corporate-events"><h3>Eventos corporativos (${rows.length})</h3><div class="table-wrap"><table><thead><tr><th>Ativo / instituição</th><th>Data</th><th>Evento</th><th>Quantidade antes → depois</th><th>Proporção / custo</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${esc(r.ticker)}</b><small>${esc(r.institution)}</small></td><td>${dt(r.date)}</td><td>${esc(r.label||corporateLabel[r.event])}<small>Extrato B3: ${qty(r.b3_quantity)}${r.sheet?' · '+esc(r.sheet)+' · linha '+r.line:''}</small></td><td>${qty(r.before)} → <b>${qty(r.after)}</b></td><td class="wrap-cell narrow">${esc(r.ratio||'—')}${r.event==='bonus'?`<small>Custo atribuído ${money(r.unit_cost)} por ação</small>`:''}${r.warning?`<small>${esc(r.warning)}</small>`:''}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">Confira a proporção no fato relevante da empresa. Nenhuma compra ou venda é criada: desdobramento e grupamento mantêm o custo total, a bonificação soma o custo atribuído e a fração retirada sai pelo preço médio.</p></div>`;}

function eventAdjustments(p){
 const needs=p.event_inputs_needed||[],ratios=(p.event_rows||[]).filter(r=>['split','grouping'].includes(r.event));
 const saved=b3Options.event_inputs||{};let html='';
 if(needs.length||ratios.length){html+=`<details class="panel" id="b3-events-panel" ${needs.length?'open':''}><summary>Eventos corporativos · informações complementares${needs.length?` (${needs.length} pendente(s))`:''}</summary><form id="b3-events-form">${needs.map((r,i)=>`<fieldset class="historical-row"><legend>${esc(r.ticker)} · ${dt(r.date)} · ${esc(r.institution)}</legend><p>Bonificação de ${qty(r.b3_in)} ação(ões). Informe o <b>custo atribuído por ação</b> divulgado no fato relevante ou aviso aos acionistas. Ele entra no preço médio e no IR; não use a cotação.</p><div class="form-grid">${numField('cost_'+i,'Custo atribuído por ação (R$)',saved[r.key]?.unit_cost??'','min="0" required')}</div><input type="hidden" name="cost_key_${i}" value="${esc(r.key)}"></fieldset>`).join('')}${ratios.length?`<p>Desdobramento e grupamento usam a quantidade do extrato. Se a proporção mostrada não bater com o fato relevante, informe a quantidade nessa instituição <b>depois</b> do evento.</p><div class="form-grid">${ratios.map((r,i)=>`${numField('after_'+i,`${esc(r.ticker)} · ${dt(r.date)} · ${esc(r.institution)} · ${esc(corporateLabel[r.event])} · quantidade depois (opcional)`,saved[r.key]?.after??'','min="0"')}<input type="hidden" name="after_key_${i}" value="${esc(r.key)}">`).join('')}</div>`:''}<div class="form-error" role="alert"></div><button class="button secondary" type="submit">Refazer prévia com estas informações</button></form></details>`;}
 if((p.event_rows||[]).length||b3Options.skip_events)html+=`<details class="panel"><summary>Não aplicar eventos corporativos nesta importação</summary><form id="b3-skip-events-form"><p>Use se você já ajustou esses eventos manualmente. As linhas ficam na lista de exclusões, e a posição pode ficar diferente da B3.</p><label class="check"><input name="skip_events" type="checkbox" ${b3Options.skip_events?'checked':''}>Excluir desdobramentos, grupamentos, bonificações e frações desta prévia</label><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Refazer prévia</button></form></details>`;
 return html;
}

b3Preview=function(p){syncPreview(p);const root=$('#b3-preview');if(!root)return;
 const extra=(p.corporate_events?.length?`<section class="panel">${eventSummary(p.corporate_events)}</section>`:'')+eventAdjustments(p);
 if(extra){const final=$('.import-final',root);final?final.insertAdjacentHTML('beforebegin',extra):root.insertAdjacentHTML('beforeend',extra);}
 wireForm('#b3-events-form',async(d)=>{const inputs={...(b3Options.event_inputs||{})};
  for(const [name,value] of Object.entries(d)){const m=name.match(/^(cost|after)_(\d+)$/);if(!m)continue;const k=d[m[1]+'_key_'+m[2]];if(!k)continue;const field=m[1]==='cost'?'unit_cost':'after';const entry={...(inputs[k]||{})};if(value===''||value===undefined)delete entry[field];else entry[field]=Number(value);if(Object.keys(entry).length)inputs[k]=entry;else delete inputs[k];}
  b3Options={...b3Options,event_inputs:inputs};b3Preview(await previewB3());});
 wireForm('#b3-skip-events-form',async(d,f)=>{b3Options={...b3Options,skip_events:$('[name=skip_events]',f).checked};b3Preview(await previewB3());});
};

function positionPanel(){return `<section class="panel" id="b3-position-panel"><h2>Conferir com o extrato de Posição da B3</h2><p>Compare a quantidade de cada ativo por instituição com a sua carteira local. Somente leitura: nada é salvo ou ajustado.</p><form id="b3-position-form"><div class="form-grid"><div class="field wide"><label for="b3-position-file">Excel de Posição (.xlsx)</label><input id="b3-position-file" type="file" accept=".xlsx,.csv" required></div>${field('asof','Data da posição (opcional)',positionOptions.asof||'','date',`max="${S.today}"`)}</div><p class="form-hint">Na Área do Investidor, abra Extratos → Posição e baixe em Excel. Sem data, uso a data do nome do arquivo ou hoje. O arquivo é lido neste computador.</p><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Conferir posição</button></form><div id="b3-position-result">${positionResult?positionView(positionResult):''}</div></section>`;}

function positionView(r){const s=r.summary;const pending=s.different+s.only_b3+s.only_local;
 const local=[...new Set([...S.assets.flatMap(a=>(a.position.institutions||[]).map(p=>p.institution)),...S.fixed.map(f=>f.institution),...(S.institutions||[])])].sort();
 return `<div class="notice ${pending?'warn':''}"><b>Posição em ${dt(r.asof)} · ${esc(r.filename)}</b><p>${s.ok} confere(m) · ${s.different} com quantidade diferente · ${s.only_b3} só na B3 · ${s.only_local} só na carteira local. Classes comparadas: ${r.categories.map(esc).join(', ')||'—'}.</p></div>
 ${r.rows.length?`<div class="table-wrap"><table><thead><tr><th>Ativo / instituição</th><th>Situação</th><th>B3</th><th>Carteira local</th><th>Diferença</th><th>O que conferir</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td><b>${esc(x.ticker)}</b><small>${esc(x.institution)} · ${esc(x.category_label)}</small></td><td>${tag(...positionStatus[x.status])}</td><td>${qty(x.b3_quantity)}${x.b3_value!=null?`<small>${money(x.b3_value)}</small>`:''}</td><td>${qty(x.local_quantity)}</td><td>${x.status==='ok'?'—':(x.difference>0?'+':'')+qty(x.difference)}</td><td class="wrap-cell">${esc(x.hint)||'—'}</td></tr>`).join('')}</tbody></table></div>`:'<p>Nenhum ativo reconhecido no arquivo.</p>'}
 ${r.unmatched_count?`<details><summary>Linhas não comparadas (${r.unmatched_count})</summary><ul>${r.unmatched.map(u=>`<li>${esc(u.sheet)} · linha ${u.line} · ${esc(u.product)}: ${esc(u.reason)}</li>`).join('')}</ul></details>`:''}
 ${r.institutions.length?`<details><summary>Nomes de instituição diferentes dos seus registros?</summary><form id="b3-position-banks"><p>Escolha a equivalência só quando for a mesma corretora/banco. Isso vale apenas para esta conferência.</p><div class="form-grid">${r.institutions.map((b,i)=>`${select('pbank_'+i,b,[['','Manter este nome'],...local.map(x=>[x,x])],(positionOptions.institution_map||{})[b]||'',true)}<input type="hidden" name="pbank_name_${i}" value="${esc(b)}">`).join('')}</div><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Conferir novamente</button></form></details>`:''}
 <ul class="form-hint">${r.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`;}

async function runPositionCheck(){positionResult=await api('/api/b3/position-check',{...positionUpload,...positionOptions});const box=$('#b3-position-result');if(box){box.innerHTML=positionView(positionResult);bindPositionBanks();}}
function bindPositionBanks(){wireForm('#b3-position-banks',async d=>{const map={};for(const [k,v] of Object.entries(d)){const m=k.match(/^pbank_(\d+)$/);if(m&&v)map[d['pbank_name_'+m[1]]]=v;}positionOptions={...positionOptions,institution_map:map};await runPositionCheck();});}

importsView=function(){return syncImports()+positionPanel();};
bindForms=function(){syncBind();
 wireForm('#b3-position-form',async d=>{positionUpload=await readB3Upload($('#b3-position-file').files[0]);positionOptions={asof:d.asof||undefined};$('#b3-position-result').innerHTML='<p class="muted">Lendo a posição neste computador…</p>';await runPositionCheck();});
 bindPositionBanks();
};

detail=function(id){syncDetail(id);const a=assetById(id);const body=$('#modal-body');if(!a||!body||!a.corporate_events?.length)return;
 body.insertAdjacentHTML('beforeend',`<section class="details-section"><h3>Eventos corporativos registrados</h3><div class="table-wrap"><table><thead><tr><th>Data</th><th>Evento</th><th>Instituição</th><th>Variação de quantidade</th><th></th></tr></thead><tbody>${a.corporate_events.map(e=>`<tr><td>${dt(e.date)}</td><td>${esc(corporateLabel[e.kind])}<small>${esc(e.notes)}</small></td><td>${esc(e.institution)}</td><td>${e.quantity_delta>0?'+':''}${qty(e.quantity_delta)}</td><td>${button('corporate-event-delete','Excluir','subtle',`data-id="${e.id}"`)}</td></tr>`).join('')}</tbody></table></div><p class="form-hint">Excluir um evento recalcula quantidade e preço médio. Uma nova importação do mesmo extrato poderá trazê-lo de volta.</p></section>`);};

document.addEventListener('click',async e=>{const b=e.target.closest('[data-action=corporate-event-delete]');if(!b)return;e.stopImmediatePropagation();
 if(!confirm('Excluir este evento corporativo e recalcular a posição?'))return;
 try{b.disabled=true;await api('/api/corporate-events/delete',{id:Number(b.dataset.id)});$('#modal').close();await load();toast('Evento excluído; posição recalculada.');}catch(ex){toast(ex.message);}finally{if(b.isConnected)b.disabled=false;}},true);
