const token=location.pathname.split('/').filter(Boolean)[1];
const base=`/phone/${encodeURIComponent(token)}`;
const screen=document.querySelector('#screen'),video=document.querySelector('#video');
const status=document.querySelector('#status'),stage=document.querySelector('#stage'),offline=document.querySelector('#offline');
let width=1080,height=2340,pointer=null,controller=null,objectUrl='',fallbackTimer=null,retryTimer=null,generation=0;

async function heartbeat(){
  if(document.hidden)return;
  const response=await fetch(`${base}/heartbeat`,{method:'POST'});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Phone unavailable');
  width=data.width;height=data.height;
}
async function input(body){
  try{
    const response=await fetch(`${base}/input`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'Input failed')}
  }catch(error){status.textContent=error.message}
}
function stop(){
  generation++;controller?.abort();controller=null;
  clearTimeout(fallbackTimer);clearTimeout(retryTimer);
  video.pause();video.removeAttribute('src');video.load();
  if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=''}
}
async function fallback(id){
  if(id!==generation||document.hidden)return;
  video.hidden=true;screen.hidden=false;
  try{
    const response=await fetch(`${base}/screen.png?t=${Date.now()}`,{cache:'no-store'});
    if(!response.ok)throw new Error('Phone unavailable');
    const url=URL.createObjectURL(await response.blob()),image=new Image();
    image.src=url;await image.decode();
    if(id!==generation){URL.revokeObjectURL(url);return}
    const previous=screen.src;screen.src=url;
    if(previous.startsWith('blob:'))URL.revokeObjectURL(previous);
    offline.hidden=true;status.textContent='Connected · compatibility view';
  }catch(error){status.textContent=error.message}
  fallbackTimer=setTimeout(()=>fallback(id),1000);
}
async function start(){
  stop();const id=generation;
  if(document.hidden)return;
  status.textContent='Connecting…';offline.hidden=false;
  try{
    await heartbeat();
    const Source=window.ManagedMediaSource||window.MediaSource;
    if(!Source){fallback(id);return}
    video.hidden=false;screen.hidden=true;
    const source=new Source();objectUrl=URL.createObjectURL(source);
    video.disableRemotePlayback=true;video.src=objectUrl;
    await new Promise((resolve,reject)=>{
      source.addEventListener('sourceopen',resolve,{once:true});
      source.addEventListener('error',()=>reject(new Error('Video decoder failed')),{once:true});
    });
    if(id!==generation)return;
    controller=new AbortController();
    const response=await fetch(`${base}/video.mp4`,{cache:'no-store',signal:controller.signal});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'Video unavailable')}
    const reader=response.body.getReader();let pending=new Uint8Array(),init=[],buffer=null;
    const fragments=[];
    const pump=()=>{
      if(!buffer||buffer.updating||source.readyState!=='open')return;
      try{
        if(video.currentTime>15&&buffer.buffered.length&&buffer.buffered.start(0)<video.currentTime-10){
          buffer.remove(0,video.currentTime-5);return;
        }
        if(fragments.length)buffer.appendBuffer(fragments.shift());
      }catch(error){controller?.abort();status.textContent=error.message}
    };
    const live=()=>{
      if(!video.buffered.length)return;
      const end=video.buffered.end(video.buffered.length-1),lag=end-video.currentTime;
      if(lag>.4)video.currentTime=Math.max(video.buffered.start(video.buffered.length-1),end-.1);
      video.play().catch(()=>{status.textContent='Tap video to play'});
    };
    const queueBox=box=>{
      const tag=String.fromCharCode(...box.slice(4,8));
      if(!buffer){
        init.push(box);if(tag!=='moov')return;
        let codec='avc1.42E01E';
        for(let n=4;n<box.length-7;n++){
          if(box[n]===97&&box[n+1]===118&&box[n+2]===99&&box[n+3]===67){
            codec='avc1.'+Array.from(box.slice(n+5,n+8),v=>v.toString(16).padStart(2,'0')).join('');break;
          }
        }
        const mime=`video/mp4; codecs="${codec}"`;
        if(!Source.isTypeSupported(mime))throw new Error('Browser cannot decode this video');
        buffer=source.addSourceBuffer(mime);
        buffer.addEventListener('updateend',()=>{live();pump()});
        buffer.addEventListener('error',()=>controller?.abort());
        fragments.push(...init);init=[];
      }else fragments.push(box);
      if(fragments.length>100)throw new Error('Connection too slow; reconnecting at live frame');
      pump();
    };
    while(id===generation){
      const {done,value}=await reader.read();if(done)throw new Error('Video disconnected');
      const combined=new Uint8Array(pending.length+value.length);
      combined.set(pending);combined.set(value,pending.length);pending=combined;
      while(pending.length>=8){
        const size=new DataView(pending.buffer,pending.byteOffset,pending.byteLength).getUint32(0);
        if(size<8||size>32*1024*1024)throw new Error('Invalid video fragment');
        if(pending.length<size)break;
        queueBox(pending.slice(0,size));pending=pending.slice(size);
      }
    }
  }catch(error){
    if(id!==generation||document.hidden)return;
    controller?.abort();
    status.textContent=error.message;
    if(error.message.includes('decode')||error.message.includes('scrcpy')||error.message.includes('av'))fallback(id);
    else retryTimer=setTimeout(start,1500);
  }
}
video.addEventListener('playing',()=>{offline.hidden=true;status.textContent='Live video · tap or swipe to control'});
video.addEventListener('click',()=>{if(video.paused)video.play().catch(()=>{})});
function point(event){
  const target=video.hidden?screen:video,rect=target.getBoundingClientRect();
  return{x:Math.max(0,Math.min(width-1,Math.round((event.clientX-rect.left)*width/rect.width))),
         y:Math.max(0,Math.min(height-1,Math.round((event.clientY-rect.top)*height/rect.height)))};
}
for(const target of [video,screen]){
  target.addEventListener('pointerdown',event=>{
    event.preventDefault();target.setPointerCapture(event.pointerId);pointer={...point(event),time:Date.now()};
  });
  target.addEventListener('pointerup',event=>{
    if(!pointer)return;const end=point(event),start=pointer;pointer=null;
    if(Math.hypot(end.x-start.x,end.y-start.y)<24)input({action:'tap',x:end.x,y:end.y});
    else input({action:'swipe',x1:start.x,y1:start.y,x2:end.x,y2:end.y,duration:Math.max(100,Math.min(1200,Date.now()-start.time))});
  });
  target.addEventListener('pointercancel',()=>{pointer=null});
}
document.querySelectorAll('[data-key]').forEach(button=>button.onclick=()=>input({action:button.dataset.key}));
document.querySelector('#wake').onclick=async()=>{
  await input({action:'wake'});
  await heartbeat().catch(error=>{status.textContent=error.message});
  if(video.paused)start();
};
document.querySelector('#fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else stage.requestFullscreen?.()};
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else start()});
window.addEventListener('pagehide',stop);
setInterval(()=>heartbeat().catch(error=>{status.textContent=error.message}),15000);
start();
