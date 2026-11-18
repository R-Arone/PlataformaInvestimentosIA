'use strict';
// Conector opcional Meu Pluggy (Open Finance): só leitura, sem guardar credenciais, com prévia antes de salvar.
const pluggyImports=importsView,pluggyBind=bindForms;
let pluggyResult=null;

function pluggyPanel(){return `<details class="panel" id="b3-pluggy-panel"><summary>Conector opcional: Meu Pluggy (Open Finance)</summary><p>Lê investimentos e operações das conexões que você fez no Meu Pluggy. <b>Seus dados passam pela Pluggy</b> (api.pluggy.ai), por isso o conector fica desligado até você usar. Só leitura; as credenciais não são guardadas.</p><form id="b3-pluggy-form"><div class="form-grid">${field('client_id','clientId da sua aplicação Pluggy','','text','required autocomplete="off" maxlength="40"')}${field('client_secret','clientSecret','','password','required autocomplete="off" maxlength="200"')}<div class="field wide"><label for="f-item_ids">itemId de cada conexão (um por linha)</label><textarea id="f-item_ids" name="item_ids" rows="3" required></textarea></div>${field('pluggy_institution','Corretora padrão (quando a Pluggy não informar)','','text','required maxlength="150"')}${field('pluggy_since','Operações a partir de (opcional)','','date',`max="${S.today}"`)}</div><label class="check"><input name="consent" type="checkbox" required>Entendo que meus dados financeiros passam pela Pluggy durante a leitura</label><p class="form-hint">Crie uma aplicação de desenvolvimento no painel da Pluggy, adicione o conector Meu Pluggy e use o itemId de cada conexão. A qualidade dos dados varia por instituição.</p><div class="form-error" role="alert"></div><button class="button secondary" type="submit">Ler da Pluggy</button></form><div id="b3-pluggy-result">${pluggyResult?pluggyView(pluggyResult):''}</div></details>`;}

function pluggyView(r){
 const rows=r.positions.map(p=>`<tr><td><b>${esc(p.ticker||p.name)}</b><small>${esc(p.type||'')}${p.subtype?' · '+esc(p.subtype):''} · ${esc(p.institution||'—')}</small></td><td>${p.quantity==null?'—':qty(p.quantity)}</td><td>${p.local_quantity==null?'—':qty(p.local_quantity)}</td><td>${p.balance==null?'—':money(p.balance)}${p.due_date?`<small>vence ${dt(p.due_date)}</small>`:''}</td><td>${p.status_check?tag(p.status_check==='ok'?'Confere':'Diferente',p.status_check==='ok'?'good':'warn'):''}</td></tr>`).join('');
 return `<div class="notice"><b>${r.positions.length} investimento(s) · ${r.trade_count} operação(ões) de renda variável</b></div>
 <div class="table-wrap"><table><thead><tr><th>Investimento</th><th>Quantidade (Pluggy)</th><th>Quantidade local</th><th>Saldo</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
 <ul class="form-hint">${[...r.warnings,...r.notes].map(n=>`<li>${esc(n)}</li>`).join('')}</ul>
 ${r.csv?`<div class="actions"><button class="button" type="button" data-action="pluggy-continue">Continuar para a prévia de importação (${r.trade_count} operação(ões))</button></div>`:''}`;}

document.addEventListener('click',async e=>{const b=e.target.closest('[data-action=pluggy-continue]');if(!b||!pluggyResult?.csv)return;
 try{b.disabled=true;b3File={csv:pluggyResult.csv,filename:pluggyResult.filename};b3Options={sheet:'__all',mode:'trades',amount_basis:'reported'};b3Preview(await previewB3());$('#b3-preview')?.scrollIntoView();}catch(ex){toast(ex.message);}finally{b.disabled=false;}});

importsView=function(){return pluggyImports()+pluggyPanel();};
bindForms=function(){pluggyBind();
 wireForm('#b3-pluggy-form',async(d,f)=>{const ids=(d.item_ids||'').split(/[\s,;]+/).filter(Boolean);
  $('#b3-pluggy-result').innerHTML='<p class="muted">Consultando a Pluggy…</p>';
  try{pluggyResult=await api('/api/pluggy/read',{client_id:d.client_id,client_secret:d.client_secret,item_ids:ids,institution:d.pluggy_institution,since:d.pluggy_since||'',consent:$('[name=consent]',f).checked});}
  catch(ex){$('#b3-pluggy-result').innerHTML='';throw ex;}
  finally{$('[name=client_secret]',f).value='';}
  $('#b3-pluggy-result').innerHTML=pluggyView(pluggyResult);});
};
