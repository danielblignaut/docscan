// Bundle a pure TypeScript module with the build's own esbuild; no browser seams or production files are changed.
import {createRequire} from 'node:module';
import {dirname} from 'node:path';
const require=createRequire(import.meta.url);
const {build}=require(require.resolve('esbuild',{paths:[dirname(require.resolve('vite'))]}));
export async function pureModuleUrl(path){
 const result=await build({entryPoints:[path instanceof URL?path.pathname:path],bundle:true,platform:'node',format:'esm',write:false,logLevel:'silent'});
 return `data:text/javascript,${encodeURIComponent(result.outputFiles[0].text)}`;
}
export async function loadPureModule(path){return import(await pureModuleUrl(path));}
