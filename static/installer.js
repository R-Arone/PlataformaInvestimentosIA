'use strict';
let installerState=null,installerTimer=null,installerFetching=false,installerSending=false;
const installerBaseRender=render;
render=function(){installerBaseRender();if(S&&view==='settings'){
 $('#main').insertAdjacentHTML('afterbegin','<section class="panel" id="installer-panel" aria-labelledby="installer-heading"></section>');
 drawInstaller();pollInstaller();
}};
function drawInstaller(){
 const panel=$('#installer-panel');if(!panel||!S)return;
 const job=installerState,busy=!!job?.running||installerSending;
 const artifacts=job?.artifacts||[];
 const size=n=>(n/1048576).toLocaleString('pt-BR',{maximumFractionDigits:1})+' MB';
 panel.innerHTML=`<div class="panel-head"><h2 id="installer-heading">Gerar instalador</h2>${tag(busy?'Gerando…':'ZIP para Windows',busy?'warn':'')}</div>
 <p>Monte um novo ZIP com os arquivos atuais do aplicativo para instalar em outro computador. Carteira, senha, backups, extratos e modelos pessoais ficam fora do pacote.</p>
 <p class="form-hint">Gerar não instala nem troca a versão aberta. Continue testando pela pasta do projeto e use Reiniciar aplicativo após atualizar o código. No instalador, use IA via Ollama/llama.cpp. FinBERT e Chronos ficam disponíveis na versão por código, com os pacotes opcionais de IA.</p>
 <button id="generate-installer" type="button" class="button" ${!job||busy||!job.available?'disabled':''}>${busy?'Gerando instalador…':'Gerar novo ZIP do instalador'}</button>
 <div role="status" aria-live="polite" class="installer-status"><p>${esc(job?.detail||'Conferindo a geração local…')}</p>${busy?`<p class="form-hint">Etapa ${job?.step||1} de ${job?.steps||6}. A montagem pode levar alguns minutos; aguarde antes de encerrar ou reiniciar.</p>`:''}</div>
 ${job?.error?`<div class="notice warn" role="alert">${esc(job.error)}</div>`:''}
 ${job&&!job.available?`<div class="notice">${esc(job.reason)}</div>`:''}
 ${artifacts.length?`<h3>Pacotes prontos</h3><p class="form-hint">Também ficam na pasta release do projeto. Extraia o ZIP e abra Instalar.cmd para instalar. Cada geração cria um arquivo novo.</p><div class="installer-artifacts">${artifacts.map(a=>`<div class="installer-artifact"><div><b>Versão ${esc(String(a.version))}</b><p class="form-hint">${esc(new Date(a.created_at).toLocaleString('pt-BR'))} · ${size(a.size)}</p><details><summary>Conferir arquivo</summary><p class="form-hint installer-filename">${esc(a.filename)}</p><p class="form-hint installer-filename">SHA-256: ${esc(a.sha256)}</p></details></div><a class="button secondary" href="/api/installer/download?file=${encodeURIComponent(a.filename)}" download>Baixar ZIP</a></div>`).join('')}</div>`:''}`;
 const restart=$('#restart-vault');if(restart)restart.disabled=busy||!!(S.job.running||S.ai?.job.running||S.signals?.job.running);
 const exit=$('#exit-vault');if(exit)exit.disabled=busy;
}
async function pollInstaller(){
 clearTimeout(installerTimer);
 if(!S||installerFetching)return;
 installerFetching=true;
 try{installerState=await api('/api/installer/status');drawInstaller();}
 catch(e){if(S&&$('#installer-panel'))$('#installer-panel').innerHTML='<h2>Gerar instalador</h2><p role="alert">'+esc(e.message)+'</p><button id="retry-installer-status" type="button" class="button secondary">Tentar novamente</button>';}
 finally{installerFetching=false;if(S&&installerState?.running)installerTimer=setTimeout(pollInstaller,2000);}
}
document.addEventListener('click',async e=>{
 if(e.target.closest('#retry-installer-status'))return pollInstaller();
 if(!e.target.closest('#generate-installer')||installerSending||installerState?.running)return;
 installerSending=true;drawInstaller();
 try{installerState=await api('/api/installer/build',{});}
 catch(ex){toast(ex.message);}
 finally{installerSending=false;drawInstaller();pollInstaller();}
});
