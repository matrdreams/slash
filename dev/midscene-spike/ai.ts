import { AndroidDevice, AndroidAgent } from '@midscene/android';
(async()=>{const d=new AndroidDevice('127.0.0.1:15555');await d.connect();const a=new AndroidAgent(d);
const t=Date.now();try{await a.aiAct('open Settings and search Display')}catch(e:any){console.log('ERR',Date.now()-t,e.message.slice(0,300))}process.exit(0)})();
