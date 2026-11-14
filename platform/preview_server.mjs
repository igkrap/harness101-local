// Platform-owned Vite launcher. Project code and configuration stay untouched.
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root=path.resolve(process.argv[2]);
const {createServer}=await import(pathToFileURL(path.join(root,'node_modules/vite/dist/node/index.js')).href);
// A project made on the platform has its own port and its own server behind /api (given by the platform); others keep what their own configuration says.
const port0=Number(process.env.PLATFORM_PREVIEW_PORT||0),api=process.env.PLATFORM_PREVIEW_API||'';
const server=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:port0,strictPort:true,open:false,...(api?{proxy:{'/api':{target:api,changeOrigin:true}}}:{})}});
await server.listen();
const port=server.httpServer.address().port;
const base=server.config.base.startsWith('/')?server.config.base:'/';
console.log('PLATFORM_PREVIEW_READY '+JSON.stringify({url:`http://127.0.0.1:${port}${base}`}));
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,async()=>{await server.close();process.exit(0);});
