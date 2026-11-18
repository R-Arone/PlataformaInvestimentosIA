'use strict';
// Atualiza saldo e vencimento da renda fixa a partir do extrato de Posição da B3, com prévia e confirmação.
const fixedImports=importsView,fixedBind=bindForms;
const fixedStatus={update:['Atualizar','warn'],new:['Só na B3','warn'],same:['Já igual','good'],older:['Saldo local mais novo','']};
let fixedPlan=null,fixedUpload={},fixedMap={};

function fixedPanel(){return `<section class="panel" id="b3-fixed-panel"><h2>Atualizar saldos da renda fixa pelo extrato de Posição</h2><p>Lê as abas Tesouro Direto e Renda Fixa e atualiza saldo, data do saldo e vencimento (se estiver vazio) dos produtos que você já tem. Nada é salvo antes da sua confirmação.</p><form id="b3-fixed-form"><div class="form-grid"><div class="field wide"><label for="b3-fixed-file">Excel de Posição (.xlsx)</label><input id="b3-fixed-file" type="file" accept=".xlsx,.csv" required></div>${field('fixed_asof','Data da posição (opcional)','','date',`max="${S.today}"`)}</div><p class="form-hint">Na Área do Investidor: Extratos → Posição → Excel. Taxa, indexador e imposto continuam como você cadastrou. O arquivo é lido neste computador.</p><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Ver o que será atualizado</button></form><div id="b3-fixed-result">${fixedPlan?fixedView(fixedPlan):''}</div></section>`;}

function fixedView(p){const s=p.summary,pending=s.update+s.new;
 const rows=p.rows.map((r,i)=>`<tr><td><b>${esc(r.name)}</b><small>${esc(r.institution)}${r.issuer?' · '+esc(r.issuer):''}</small></td><td>${tag(...fixedStatus[r.status])}</td><td>${money(r.b3_value)}<small>${esc(r.value_column)}</small></td><td>${r.local_balance==null?'—':money(r.local_balance)+(r.local_date?`<small>${dt(r.local_date)}</small>`:'')}</td><td>${r.maturity?dt(r.maturity):'—'}</td><td class="wrap-cell">${r.status==='new'?`<label class="check"><input type="checkbox" data-fixed-create="${esc(r.name+'|'+r.institution)}">Criar</label><small>${esc(r.hint)}</small>`:esc(r.hint)}</td></tr>`).join('');
 return `<div class="notice ${pending?'warn':''}"><b>Posição em ${dt(p.asof)} · ${esc(p.filename)}</b><p>${s.update} para atualizar · ${s.new} só na B3 · ${s.same} já igual(is)${s.older?` · ${s.older} com saldo local mais novo`:''}.</p></div>
 ${p.rows.length?`<div class="table-wrap"><table><thead><tr><th>Produto / instituição</th><th>Situação</th><th>Saldo na B3</th><th>Saldo local</th><th>Vencimento</th><th>O que acontece</th></tr></thead><tbody>${rows}</tbody></table></div>`:'<p class="muted">Nenhum produto reconhecido neste arquivo.</p>'}
 ${p.local_only.length?`<details><summary>Só no cadastro local (${p.local_only.length}), não serão alterados</summary><ul>${p.local_only.map(x=>`<li>${esc(x.name)} · ${esc(x.institution)} · ${money(x.balance)}</li>`).join('')}</ul></details>`:''}
 ${p.unmatched_count?`<details><summary>Linhas não lidas (${p.unmatched_count})</summary><ul>${p.unmatched.map(u=>`<li>${esc(u.sheet)} · linha ${u.line} · ${esc(u.product)}: ${esc(u.reason)}</li>`).join('')}</ul></details>`:''}
 ${p.institutions.length?`<details><summary>Nomes de instituição diferentes dos seus registros?</summary><form id="b3-fixed-banks"><p>Escolha a equivalência só quando for a mesma corretora ou banco. Vale apenas para esta atualização.</p><div class="form-grid">${p.institutions.map((b,i)=>`${select('fbank_'+i,b,[['','Manter este nome'],...[...new Set([...S.fixed.map(f=>f.institution)])].sort().map(x=>[x,x])],fixedMap[b]||'',true)}<input type="hidden" name="fbank_name_${i}" value="${esc(b)}">`).join('')}</div><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Refazer prévia</button></form></details>`:''}
 ${pending?`<form id="b3-fixed-commit"><label class="check"><input name="confirm" type="checkbox" required>Conferi os saldos acima com o meu extrato</label><div class="form-error" role="alert"></div><button class="button" type="submit">Salvar atualização</button></form>`:''}
 <ul class="form-hint">${p.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`;}

async function runFixedPreview(){fixedPlan=await api('/api/b3/fixed-preview',{...fixedUpload,asof:fixedUpload.asof||undefined,institution_map:fixedMap});const box=$('#b3-fixed-result');if(box){box.innerHTML=fixedView(fixedPlan);bindFixedResult();}}
function bindFixedResult(){
 wireForm('#b3-fixed-banks',async d=>{const map={};for(const [k,v] of Object.entries(d)){const m=k.match(/^fbank_(\d+)$/);if(m&&v)map[d['fbank_name_'+m[1]]]=v;}fixedMap=map;await runFixedPreview();});
 wireForm('#b3-fixed-commit',async(d,f)=>{const create=[...document.querySelectorAll('[data-fixed-create]:checked')].map(x=>x.dataset.fixedCreate);
  const r=await api('/api/b3/fixed-commit',{token:fixedPlan.token,confirm_records:true,create});fixedPlan=null;await load();toast(`${r.updated} atualizado(s), ${r.created} criado(s).`);});
}

importsView=function(){return fixedImports()+fixedPanel();};
bindForms=function(){fixedBind();
 wireForm('#b3-fixed-form',async d=>{fixedUpload={...await readB3Upload($('#b3-fixed-file').files[0]),asof:d.fixed_asof||undefined};fixedMap={};$('#b3-fixed-result').innerHTML='<p class="muted">Lendo o extrato neste computador…</p>';await runFixedPreview();});
 bindFixedResult();
};
