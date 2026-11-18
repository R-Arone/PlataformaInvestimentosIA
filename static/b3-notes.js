'use strict';
// Notas de corretagem (PDF ou texto) para o histórico anterior à B3: lê aqui, confere e segue para a prévia de importação.
const notesImports=importsView,notesBind=bindForms;
let notesResult=null,notesInput={},notesMap={};

async function readNoteFiles(files){
 if(!files.length)throw Error('Selecione os PDFs das notas ou cole o texto.');
 const out=[];if(files.reduce((n,f)=>n+f.size,0)>14_000_000)throw Error('Envie até 14 MB por vez; divida as notas em lotes.');
 for(const file of files){const lower=file.name.toLowerCase();
  if(lower.endsWith('.pdf')){if(file.size>12_000_000)throw Error(file.name+': use PDFs de até 12 MB.');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));out.push({name:file.name,pdf:btoa(binary)});}
  else if(lower.endsWith('.txt')){if(file.size>2_000_000)throw Error(file.name+': arquivo de texto muito grande.');out.push({name:file.name,text:await file.text()});}
  else throw Error(file.name+': envie PDF ou .txt.');}
 return out;
}

function notesPanel(){const banks=[...new Set([...S.institutions||[],...S.fixed.map(f=>f.institution),...S.assets.flatMap(a=>(a.position.institutions||[]).map(p=>p.institution))])].filter(Boolean).sort();
 return `<section class="panel" id="b3-notes-panel"><h2>Notas de corretagem (histórico anterior à B3)</h2><p>A Área do Investidor só tem dados a partir de 01/11/2019. Para antes disso, leia as notas de corretagem em PDF (formato SINACOR). Tudo é lido neste computador e nada é salvo antes da prévia de importação.</p><form id="b3-notes-form"><div class="form-grid"><div class="field wide"><label for="b3-notes-files">PDFs das notas (ou .txt com o texto)</label><input id="b3-notes-files" type="file" accept=".pdf,.txt" multiple></div>${field('notes_institution','Corretora (como aparece na sua carteira)',notesInput.institution||'','text',`required maxlength="150" list="b3-notes-banks"`)}<datalist id="b3-notes-banks">${banks.map(b=>`<option value="${esc(b)}">`).join('')}</datalist>${field('notes_password','Senha do PDF (se houver)','','password','autocomplete="off" maxlength="100"')}${field('notes_until','Importar só até (recomendado 2019-10-31)',notesInput.until??'2019-10-31','date',`max="${S.today}"`)}<div class="field wide"><label for="f-pasted">Ou cole o texto copiado da nota</label><textarea id="f-pasted" name="pasted" rows="4" maxlength="200000"></textarea></div></div><p class="form-hint">A senha costuma ser os primeiros dígitos do CPF. Ela abre o arquivo e não é guardada. Para PDFs é preciso o pacote pypdf (pip install pypdf).</p><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Ler notas</button></form><div id="b3-notes-result">${notesResult?notesView(notesResult):''}</div></section>`;}

function notesView(r){
 const rows=r.notes.map(n=>`<tr><td><b>${esc(n.number)}</b><small>págs. ${n.pages.join(', ')}</small></td><td>${esc(n.date||'—')}</td><td>${n.trade_count}</td><td>${money(n.total_costs)}</td><td class="wrap-cell">${[...n.problems,...n.ignored,...n.warnings].map(esc).join('<br>')||'—'}</td></tr>`).join('');
 const unresolved=r.unresolved.length?`<form id="b3-notes-map"><h3>Informe o ticker de cada ativo</h3><p>As notas trazem o nome do ativo, não o ticker. Confira o código da época do pregão; trocas de código e incorporações ficam para você revisar.</p><div class="form-grid">${r.unresolved.map((u,i)=>`<div class="field"><label for="f-tk${i}">${esc(u.spec)} (${u.count} negócio(s))</label><input id="f-tk${i}" name="tk${i}" value="${esc(notesMap[u.spec]||u.suggestions[0]?.ticker||'')}" maxlength="10" required pattern="[A-Za-z0-9]{3,8}[0-9]{1,2}" ${u.suggestions.length?`list="tk-list-${i}"`:''}>${u.suggestions.length?`<datalist id="tk-list-${i}">${u.suggestions.map(s=>`<option value="${esc(s.ticker)}">${esc(s.name)}</option>`).join('')}</datalist>`:''}<input type="hidden" name="spec${i}" value="${esc(u.spec)}"></div>`).join('')}</div><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Aplicar tickers</button></form>`:'';
 const next=r.csv?`<div class="actions"><button class="button" type="button" data-action="notes-continue">Continuar para a prévia de importação (${r.rows} operação(ões))</button></div>`:'';
 return `<div class="notice ${r.errors.length||r.unresolved.length?'warn':''}"><b>${r.notes.length} nota(s) lidas · ${r.rows} operação(ões) prontas</b>${r.skipped_after_limit?`<p>${r.skipped_after_limit} negócio(s) depois da data limite não entram.</p>`:''}</div>
 <div class="table-wrap"><table><thead><tr><th>Nota</th><th>Pregão</th><th>Negócios</th><th>Custos</th><th>Avisos</th></tr></thead><tbody>${rows}</tbody></table></div>
 ${r.errors.length?`<div class="notice warn"><b>Corrija antes de continuar</b><ul>${r.errors.map(e=>`<li>${esc(e)}</li>`).join('')}</ul></div>`:''}
 ${r.warnings.length?`<ul class="form-hint">${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}
 ${unresolved}${next}<ul class="form-hint">${r.notes_info.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`;}

async function runNotes(){notesResult=await api('/api/notes/parse',{...notesInput,ticker_map:notesMap});const box=$('#b3-notes-result');if(box){box.innerHTML=notesView(notesResult);bindNotesResult();}}
function bindNotesResult(){
 wireForm('#b3-notes-map',async d=>{const map={...notesMap};for(const [k,v] of Object.entries(d)){const m=k.match(/^tk(\d+)$/);if(m&&v)map[d['spec'+m[1]]]=v.toUpperCase();}notesMap=map;await runNotes();});
}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action=notes-continue]');if(!b||!notesResult?.csv)return;
 try{b.disabled=true;b3File={csv:notesResult.csv,filename:notesResult.filename};b3Options={sheet:'__all',mode:'trades',amount_basis:'reported'};b3Preview(await previewB3());$('#b3-preview')?.scrollIntoView();}catch(ex){toast(ex.message);}finally{b.disabled=false;}});

importsView=function(){return notesImports()+notesPanel();};
bindForms=function(){notesBind();
 wireForm('#b3-notes-form',async d=>{const files=await readNoteFiles([...$('#b3-notes-files').files]);if(d.pasted?.trim())files.push({name:'texto colado',text:d.pasted});
  if(!files.length)throw Error('Selecione os PDFs das notas ou cole o texto.');
  notesInput={files,institution:d.notes_institution,password:d.notes_password||'',until:d.notes_until||''};notesMap={};$('#b3-notes-result').innerHTML='<p class="muted">Lendo as notas neste computador…</p>';await runNotes();});
 bindNotesResult();
};
