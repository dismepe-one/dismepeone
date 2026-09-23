/* DISMEPE ONE Web Push. Nenhuma página comercial é armazenada em cache. */
self.addEventListener('install',event=>{self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(self.clients.claim());});
self.addEventListener('push',event=>{
  let data={};try{data=event.data?.json()||{};}catch(_){}
  const id=/^ONE-PUSH-[a-f0-9]{32}$/.test(String(data.id||''))?String(data.id):'';
  if(!id)return;
  const title=String(data.title||'DISMEPE ONE').slice(0,120);
  const body=String(data.body||'Você recebeu uma nova notificação.').slice(0,250);
  event.waitUntil(self.registration.showNotification(title,{
    body,
    tag:'dismepe-'+id,renotify:false,
    icon:'/push/icon.svg',badge:'/push/icon.svg',
    data:{id,url:'/?dismepe_notice='+encodeURIComponent(id)}
  }));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  const id=String(event.notification?.data?.id||'');
  if(!/^ONE-PUSH-[a-f0-9]{32}$/.test(id))return;
  const target=new URL('/?dismepe_notice='+encodeURIComponent(id),self.location.origin);
  event.waitUntil((async()=>{
    const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const sameOrigin=windows.find(w=>new URL(w.url).origin===self.location.origin);
    if(sameOrigin){
      await sameOrigin.navigate(target.href);
      return sameOrigin.focus();
    }
    return self.clients.openWindow(target.href);
  })());
});
