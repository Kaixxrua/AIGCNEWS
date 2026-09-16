// Packaging for reviewed upstream examples. Source files remain byte-for-byte original.
import {readFile,writeFile} from 'node:fs/promises'
import {posix,resolve} from 'node:path'
import {build} from 'esbuild'
import postcss from 'postcss'
import {compile} from 'tailwindcss4'

const escape=value=>value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
export async function buildOriginalPreview(item,data,output,root){
 if(item.preview_adapter!=='original-react-v1')return false
 const originals=await Promise.all(item.files.map(async file=>({name:file.name,text:await readFile(resolve(data,file.path),'utf8')})))
 const source=resolve(data,item.files[0].path)
 const cssSource=originals.find(file=>file.name===item.preview_css)
 if(!cssSource)throw Error('Missing original global CSS: '+item.id)
 const parsed=postcss.parse(cssSource.text)
 const rules=[]
 // Retain original tokens, animations and utility definitions; omit docs chrome,
 // remote font imports and build-time plugins from the standalone mount.
 parsed.walkRules(rule=>{if([':root','.dark'].includes(rule.selector))rules.push(rule.toString())})
 for(const rule of parsed.nodes){
  if(rule.type==='atrule'&&['theme','keyframes','utility','custom-variant'].includes(rule.name))rules.push(rule.toString()+(rule.nodes?'':';'))
 }
 // Some upstream docs inherit semantic tokens from their framework preset.
 // Include the pinned original preset rather than inventing replacement colors.
 if(item.preview_preset){rules.unshift(await readFile(resolve(data,item.preview_preset),'utf8'))}
 const base=await readFile(resolve(root,'node_modules/tailwindcss4/index.css'),'utf8')
 const animations=await readFile(resolve(root,'node_modules/tw-animate-css/dist/tw-animate.css'),'utf8')
 const compiler=await compile(base+'\n'+animations+'\n@custom-variant dark (&:where(.dark,.dark *));\n'+rules.join('\n'))
 const compiled=postcss.parse(compiler.build(originals.map(file=>file.text).join('\n').match(/[^\s"'`<>]+/g)??[]))
 compiled.walkDecls(declaration=>{if(/^--[a-z0-9-]+$/i.test(declaration.value))declaration.value=`var(${declaration.value})`})
 const css=compiled.toString()+`\nhtml,body{margin:0;min-height:100%;font-family:Arial,Helvetica,sans-serif;background:var(--background,#fff);color:var(--foreground,#111)}*{box-sizing:border-box;border-color:var(--border,#e5e7eb)}#root{min-height:100vh;${['background','shader'].includes(item.category)?'height:100vh;':''}display:flex;align-items:center;justify-content:center;padding:${item.kind==='block'||['background','shader'].includes(item.category)?'0':'28px'};width:100%}#root>div{max-width:100%;${item.preview_fill?'width:100%;':''}}:root{--font-geist-sans:Arial,Helvetica,sans-serif;--font-geist-mono:monospace}button,a,input,textarea,select{outline-offset:3px}`
 const imported=item.export_name==='default'?'Component':`{${item.export_name} as Component}`
 const report=`let failed=false;const report=state=>{if(state==='ready'&&failed)return;if(state!=='ready')failed=true;parent.postMessage({type:'ui-library-preview',id:${JSON.stringify(item.id)},state},'*')};window.addEventListener('error',()=>report('error'));window.addEventListener('unhandledrejection',()=>report('error'));setTimeout(()=>report('ready'),1200);`
 const action=item.preview_action?`setTimeout(()=>{const target=[...document.querySelectorAll('button')].find(button=>button.textContent?.trim()===${JSON.stringify(item.preview_action)});target?.click()},500);`:''
 const pointer=`window.addEventListener('message',event=>{const d=event.data;if(event.source!==parent||d?.type!=='ui-library-pointer'||!Number.isFinite(d.x)||!Number.isFinite(d.y))return;const target=document.elementFromPoint(d.x,d.y);if(!target)return;for(const kind of d.leave?['mouseout','pointerout']:['mousemove','pointermove'])target.dispatchEvent(kind.startsWith('pointer')?new PointerEvent(kind,{bubbles:true,clientX:d.x,clientY:d.y,pointerType:'mouse'}):new MouseEvent(kind,{bubbles:true,clientX:d.x,clientY:d.y}))});`
 const entry=`import React from 'react';import{createRoot}from'react-dom/client';import{ThemeProvider}from'next-themes';import ${imported} from ${JSON.stringify(source)};${report}${pointer}createRoot(document.getElementById('root')).render(<ThemeProvider forcedTheme="light" attribute="class" enableSystem={false}><Component {...${JSON.stringify(item.props)}}/></ThemeProvider>);${action}`
 const result=await build({stdin:{contents:entry,loader:'tsx',resolveDir:root},outfile:resolve(output,item.id+'.js'),bundle:true,minify:true,metafile:true,format:'iife',platform:'browser',jsx:'automatic',nodePaths:[resolve(root,'node_modules')],define:{'process.env.NODE_ENV':'"production"','process.env':'{}'},legalComments:'linked',logLevel:'silent',plugins:[{name:'original-local-imports',setup(builder){
  builder.onResolve({filter:/^@\//},args=>{
   const name=(item.preview_root?item.preview_root+'/':'')+args.path.slice(2)
   const file=item.files.find(file=>[name,name+'.tsx',name+'.ts',name+'.jsx',name+'.js',name+'/index.tsx',name+'/index.ts'].includes(file.name))
   if(!file)throw Error('Missing original import: '+args.path)
   return {path:resolve(data,file.path)}
  })
  builder.onResolve({filter:/^@repo\//},args=>{
   const name=args.path.slice('@repo/'.length)
   const candidates=name.startsWith('elements/')
    ?[`packages/elements/src/${name.slice('elements/'.length)}.tsx`,`packages/elements/src/${name.slice('elements/'.length)}.ts`]
    :name.startsWith('shadcn-ui/')
      ?[`packages/${name}.tsx`,`packages/${name}.ts`,`packages/${name}/index.tsx`,`packages/${name}/index.ts`]
      :[`packages/${name}/index.tsx`,`packages/${name}/index.ts`]
   const file=item.files.find(file=>candidates.includes(file.name))
   if(!file)throw Error('Missing original workspace import: '+args.path)
   return {path:resolve(data,file.path)}
  })
  builder.onResolve({filter:/^\.\.?\//},args=>{
   const importer=item.files.find(file=>resolve(data,file.path)===args.importer)
   if(!importer)return
   const name=posix.normalize(posix.join(posix.dirname(importer.name),args.path))
   const file=item.files.find(file=>[name,name+'.tsx',name+'.ts',name+'.jsx',name+'.js',name+'/index.tsx',name+'/index.ts'].includes(file.name))
   if(!file)return
   return {path:resolve(data,file.path)}
  })
  builder.onResolve({filter:/^next\/link$/},()=>({path:'next-link',namespace:'standalone'}))
  builder.onLoad({filter:/.*/,namespace:'standalone'},()=>({contents:`import React from 'react';export default React.forwardRef(function Link({href,children,prefetch,replace,scroll,shallow,locale,...props},ref){return <a {...props} ref={ref} href={typeof href==='string'?href:'#'} onClick={event=>event.preventDefault()}>{children}</a>})`,loader:'tsx',resolveDir:root}))
 }}]})
 await writeFile(resolve(output,item.id+'.css'),css)
 if(process.env.UI_PREVIEW_BUILD_METAFILES==='1')await writeFile(resolve(output,item.id+'.build.json'),JSON.stringify(result.metafile))
 const csp="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
 await writeFile(resolve(output,item.id+'.html'),`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${escape(item.name.en)}</title><link rel="stylesheet" href="./${item.id}.css"></head><body><div id="root"></div><script src="./${item.id}.js"></script></body></html>`)
 return true
}
