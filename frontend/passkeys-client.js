/* DISMEPE ONE Passkeys — somente origem oficial, ações explícitas do usuário. */
(function(){
'use strict';
if(window.__DISMEPE_PASSKEYS_CLIENT__)return;
window.__DISMEPE_PASSKEYS_CLIENT__=true;
const $=id=>document.getElementById(id);
const official=location.origin==='https://dismepeone.com.br';
const supported=official&&window.isSecureContext&&!!navigator.credentials?.create&&!!navigator.credentials?.get&&!!window.PublicKeyCredential;
const industry=location.pathname.startsWith('/industrias');
const loginScreen=location.pathname==='/passkeys/login';
function decode(value){
 const s=String(value||'').replace(/-/g,'+').replace(/_/g,'/');
 const bytes=atob(s+'='.repeat((4-s.length%4)%4));
 return Uint8Array.from(bytes,c=>c.charCodeAt(0));
}
function encode(buffer){
 const arr=new Uint8Array(buffer);
 let s='';for(const n of arr)s+=String.fromCharCode(n);
 return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}
function convertOptions(options,register){
 const o={...options,challenge:decode(options.challenge)};
 const descriptors=register?'excludeCredentials':'allowCredentials';
 if(Array.isArray(o[descriptors]))o[descriptors]=o[descriptors].map(x=>({...x,id:decode(x.id)}));
 if(register)o.user={...options.user,id:decode(options.user.id)};
 return o;
}
function serialize(credential,register){
 const r=credential.response;
 const obj={id:credential.id,rawId:encode(credential.rawId),type:credential.type,
  response:{clientDataJSON:encode(r.clientDataJSON)},clientExtensionResults:credential.getClientExtensionResults?.()||{}};
 if(register){
  obj.response.attestationObject=encode(r.attestationObject);
  obj.response.transports=r.getTransports?.()||[];
 }else{
  obj.response.authenticatorData=encode(r.authenticatorData);
  obj.response.signature=encode(r.signature);
  obj.response.userHandle=r.userHandle?encode(r.userHandle):null;
 }
 if(credential.authenticatorAttachment)obj.authenticatorAttachment=credential.authenticatorAttachment;
 return obj;
}
async function request(path,body){
 const result=await fetch('/passkeys/'+path,{method:body?'POST':'GET',credentials:'include',cache:'no-store',
  headers:{Accept:'application/json',...(body?{'Content-Type':'application/json'}:{})},
  ...(body?{body:JSON.stringify(body)}:{})});
 let data={};try{data=await result.json();}catch(_){}
 if(!result.ok||data.sucesso===false){
  const err=typeof data.detail==='string'?data.detail:(data.erro||'Não foi possível concluir a operação.');
  throw new Error(err);
 }
 return data;
}
function el(parent,tag,content,css){
 const n=document.createElement(tag);
 if(content!==undefined)n.textContent=content;
 if(css)n.style.cssText=css;
 parent.append(n);return n;
}
function issue(elm,message,error=false){
 if(!elm)return;
 elm.textContent=message;
 elm.style.color=error?'#ad302e':'#16663e';
}
function browserError(err){
 if(err?.name==='NotAllowedError')return 'Operação cancelada ou não autorizada no dispositivo.';
 if(err?.name==='InvalidStateError')return 'Esta chave já está cadastrada neste dispositivo.';
 if(err?.name==='NotSupportedError')return 'Este aparelho ou navegador não suporta esta opção de chave de acesso.';
 return err?.message||'Não foi possível confirmar a chave de acesso.';
}
let running=false;
async function register(){
 const msg=$('passkeyIndustryStatus'),pwd=$('passkeyIndustryPassword');
 if(running)return;
 if(!supported){issue(msg,'Utilize dismepeone.com.br em um navegador compatível com Face ID, impressão digital ou passkeys.',true);return;}
 if(!pwd?.value){issue(msg,'Confirme sua senha atual para cadastrar uma chave.',true);return;}
 running=true;const password=pwd.value;pwd.value='';
 try{
  issue(msg,'Confirmando a senha e preparando a chave...');
  const start=await request('register/options',{senha:password});
  issue(msg,'Confirme a chave de acesso na janela do seu dispositivo...');
  const credential=await navigator.credentials.create({publicKey:convertOptions(start.options,true)});
  if(!credential)throw Error('Cadastro não autorizado.');
  const finish=await request('register/verify',{id:start.id,credencial:serialize(credential,true)});
  issue(msg,finish.mensagem||'Chave cadastrada.');
  await listKeys();
 }catch(e){issue(msg,browserError(e),true);}
 finally{running=false;}
}
async function listKeys(){
 const holder=$('passkeyIndustryKeys');if(!holder)return;
 holder.replaceChildren();
 try{
  const data=await request('credentials');
  const active=(data.credenciais||[]).filter(x=>x.ativo);
  if(!active.length){el(holder,'p','Nenhuma chave de acesso cadastrada.','font-size:12px;color:#546c5e;');return;}
  for(const key of active){
   const row=el(holder,'div',undefined,'display:flex;gap:9px;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid #e3eae4;');
   const label=el(row,'span',(key.nome||'Chave')+' · '+new Date(key.criado_em).toLocaleDateString('pt-BR'),'font-size:12px;color:#223c30;');
   const del=el(row,'button','Remover','border:1px solid #d8c0c0;background:white;border-radius:8px;padding:6px 9px;color:#962c2c;');
   del.type='button';
   del.addEventListener('click',async()=>{
    if(!confirm('Remover esta chave de acesso da sua conta?'))return;
    const pwd=window.prompt('Confirme sua senha atual para remover a chave:');
    if(!pwd)return;
    del.disabled=true;
    try{await request('credentials/revoke',{credencial_id:key.credential_id,senha:pwd});await listKeys();issue($('passkeyIndustryStatus'),'Chave desativada.');}
    catch(e){issue($('passkeyIndustryStatus'),browserError(e),true);}
    finally{del.disabled=false;}
   });
  }
 }catch(e){issue($('passkeyIndustryStatus'),browserError(e),true);}
}
function industryControls(){
 const container=document.querySelector('.topbar .session');
 if(!container||$('passkeyIndustryButton'))return;
 const btn=document.createElement('button');
 btn.id='passkeyIndustryButton';btn.type='button';btn.className='icon-btn';
 btn.title='Chaves de acesso';btn.setAttribute('aria-label','Configurar acesso por biometria');
 const glyph=el(btn,'i',undefined);glyph.className='fa-solid fa-fingerprint';glyph.setAttribute('aria-hidden','true');
 const before=container.querySelector('button[onclick="openPasswordChange()"]');
 container.insertBefore(btn,before||null);
 const panel=el(document.body,'section',undefined,'display:none;position:fixed;z-index:2147482001;inset:0;background:rgba(0,0,0,.48);padding:22px;overflow:auto;align-items:center;justify-content:center;');
 panel.id='passkeyIndustryModal';
 const content=el(panel,'div',undefined,'background:white;border-radius:16px;padding:20px;max-width:420px;width:100%;margin:auto;box-shadow:0 18px 50px #0003;color:#183a29;font:14px system-ui,sans-serif;');
 const head=el(content,'div',undefined,'display:flex;justify-content:space-between;align-items:center;gap:10px;');
 el(head,'h2','Acesso por biometria','font-size:18px;font-weight:800;margin:0;');
 const close=el(head,'button','×','background:#eff5ef;border:0;border-radius:9px;font-size:22px;padding:4px 12px;');
 close.type='button';close.setAttribute('aria-label','Fechar configurações');
 const exit=()=>{panel.style.display='none';};
 close.addEventListener('click',exit);
 panel.addEventListener('click',event=>{if(event.target===panel)exit();});
 el(content,'p','Cadastre uma chave de acesso para entrar no portal Indústrias usando Face ID, impressão digital ou desbloqueio do dispositivo. Sua biometria não é enviada ao DISMEPE ONE.','line-height:1.5;font-size:12px;color:#526b5a;');
 const pwd=el(content,'input',undefined,'width:100%;box-sizing:border-box;padding:11px;border:1px solid #ceded0;border-radius:9px;margin:9px 0;');
 pwd.type='password';pwd.id='passkeyIndustryPassword';pwd.placeholder='Confirme sua senha atual';pwd.autocomplete='current-password';
 const create=el(content,'button','Cadastrar chave de acesso','border:0;background:#087b51;color:white;border-radius:9px;padding:11px 13px;font-weight:700;width:100%;');
 create.type='button';create.addEventListener('click',register);
 const status=el(content,'p','','font-size:12px;line-height:1.5;');status.id='passkeyIndustryStatus';status.setAttribute('role','status');
 el(content,'h3','Minhas chaves de acesso','font-size:14px;margin:16px 0 4px;');
 const keys=el(content,'div',undefined,'max-height:190px;overflow:auto;');keys.id='passkeyIndustryKeys';
 const link=el(content,'a','Abrir login por biometria →','display:block;font-size:12px;color:#087b51;margin-top:14px;text-decoration:underline;');
 link.href='/passkeys/login';
 btn.addEventListener('click',()=>{panel.style.display='flex';listKeys();});
}
function loginControls(){
 const form=$('passkeyLoginForm');if(!form)return;
 const input=$('passkeyLoginUser'),button=$('passkeyLoginButton'),status=$('passkeyLoginStatus');
 if(!supported){button.disabled=true;issue(status,'Abra este login pelo endereço oficial e utilize um navegador compatível com passkeys.',true);}
 form.addEventListener('submit',async(event)=>{
  event.preventDefault();if(running)return;
  const username=input.value.trim();
  if(!username){issue(status,'Informe seu usuário.',true);return;}
  running=true;button.disabled=true;
  try{
   issue(status,'Localizando sua chave de acesso...');
   const start=await request('login/options',{usuario:username});
   issue(status,'Confirme Face ID, impressão digital ou desbloqueio do dispositivo...');
   const credential=await navigator.credentials.get({publicKey:convertOptions(start.options,false)});
   if(!credential)throw Error('Autenticação não autorizada.');
   const verified=await request('login/verify',{
     id:start.id,usuario:start.usuario,credencial:serialize(credential,false)
   });
   if(!verified.sucesso)throw Error('Não foi possível concluir a autenticação.');
   issue(status,'Acesso autorizado. Abrindo o portal...');
   location.replace(verified.destino||'/industrias');
  }catch(e){issue(status,browserError(e),true);button.disabled=false;}
  finally{running=false;}
 });
}
function mainLoginLink(){
 const form=document.getElementById('loginButton');
 if(!form||$('passkeysMainLoginLink'))return;
 const a=document.createElement('a');a.id='passkeysMainLoginLink';a.href='/passkeys/login';
 a.textContent='Entrar com Face ID ou impressão digital (Indústrias)';
 a.style.cssText='display:block;margin:12px auto;padding:10px;text-align:center;color:#087b51;text-decoration:underline;font-size:12px;font-weight:700;';
 form.insertAdjacentElement('afterend',a);
}
async function boot(){
 if(industry){
  try{
   const r=await fetch('/auth/me',{credentials:'include',cache:'no-store'});
   const data=r.ok?await r.json():null;
   const user=data?.usuario;
   if(String(user?.tipo||'').trim().toUpperCase()==='INDUSTRIA'&&user?.permissoes?.INDUSTRIA_TROCAR_SENHA!==true){
    industryControls();
   }
  }catch(_){}
 }else if(loginScreen)loginControls();
 else mainLoginLink();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();