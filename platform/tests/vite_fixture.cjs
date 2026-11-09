const path = require('node:path');

async function openFixture(browser, source, options = {}) {
  const project = options.project || path.resolve(__dirname, '../../local-only');
  const frontend = path.join(project, 'frontend');
  const virtualFile = path.join(frontend, '__framework_fixture__.tsx');
  const {createServer} = await import(`file://${path.join(frontend, 'node_modules/vite/dist/node/index.js')}`);
  const server = await createServer({root:frontend, logLevel:'silent', server:{host:'127.0.0.1',port:0,strictPort:true,
    ...(options.apiTarget ? {proxy:{'/api':{target:options.apiTarget,changeOrigin:true}}} : {})}, plugins:[{
    name:'framework-browser-fixture',
    resolveId(id){if(id==='/__framework_fixture__.tsx'||id===virtualFile)return virtualFile;},
    load(id){if(id===virtualFile)return source;},
    configureServer(vite){vite.middlewares.use(async(req,res,next)=>{
      if(req.url!=='/fixture.html')return next();
      try {
        const html=await vite.transformIndexHtml('/fixture.html','<!doctype html><html><body><div id="root"></div><script type="module" src="/__framework_fixture__.tsx"></script></body></html>');
        res.setHeader('Content-Type','text/html');res.end(html);
      } catch(error){res.statusCode=500;res.end(String(error));}
    });},
  }]});
  let page;
  try {
    await server.listen();
    await server.transformRequest('/__framework_fixture__.tsx');
    const base=`http://127.0.0.1:${server.httpServer.address().port}`;
    page=await browser.newPage({viewport:options.viewport||{width:1440,height:1000}});
    page.setDefaultTimeout(6000);
    const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/fixture.html');
    return {page,base,errors,close:async()=>{await page.close();await server.close();}};
  } catch(error){if(page)await page.close();await server.close();throw error;}
}
module.exports={openFixture};
