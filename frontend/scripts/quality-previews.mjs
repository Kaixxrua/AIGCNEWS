// Standalone mounting and token demonstration only; imported material stays unchanged.
import {readFile,writeFile} from 'node:fs/promises'
import {resolve} from 'node:path'
import {build} from 'esbuild'
import postcss from 'postcss'
import {compile} from 'tailwindcss4'
const escape = value => value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')
export async function buildQualityPreview(item,data,output,root){
 if(!['tweakcn','shadcn'].includes(item.provider_id))return false
 const report=`let failed=false;const report=state=>{if(state==='ready'&&failed)return;if(state!=='ready')failed=true;parent.postMessage({type:'ui-library-preview',id:${JSON.stringify(item.id)},state},'*')};window.addEventListener('error',()=>report('error'));window.addEventListener('unhandledrejection',()=>report('error'));setTimeout(()=>report('ready'),700);`
 let markup='<div id="root"></div>',css,js
 if(item.provider_id==='tweakcn'){
  css=await readFile(resolve(data,item.files[0].path),'utf8')
  css+=`*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Arial,Helvetica,sans-serif;background:var(--background);color:var(--foreground)}body{padding:32px}.palette{display:flex;gap:8px}.swatch{width:36px;height:36px;border-radius:50%;border:1px solid var(--border)}header{display:flex;align-items:start;justify-content:space-between;gap:24px}small{color:var(--muted-foreground);font:11px Arial,Helvetica,sans-serif}h1{font-size:28px;font-weight:500;letter-spacing:var(--letter-spacing);margin:20px 0 6px}.sample{margin-top:28px;display:grid;grid-template-columns:1.3fr 1fr;gap:18px}.panel{padding:20px;background:var(--card);color:var(--card-foreground);border:1px solid var(--border);border-radius:var(--radius)}.label{font-size:12px;color:var(--muted-foreground)}.amount{font-size:26px;margin:10px 0 22px}.chart{display:flex;align-items:end;gap:8px;height:50px}.chart i{flex:1;border-radius:3px 3px 0 0}.actions{display:flex;flex-wrap:wrap;gap:8px}button{padding:9px 14px;border:1px solid transparent;border-radius:var(--radius);font:12px inherit;background:var(--primary);color:var(--primary-foreground)}button.secondary{background:var(--secondary);color:var(--secondary-foreground);border-color:var(--border)}.badge{display:inline-block;margin-bottom:15px;padding:5px 9px;background:var(--accent);color:var(--accent-foreground);border-radius:var(--radius);font-size:11px}.token{font:10px Arial,Helvetica,sans-serif;color:var(--muted-foreground);margin-top:20px}@media(max-width:430px){body{padding:20px}.sample{grid-template-columns:1fr}.sample .panel:last-child{display:none}.swatch{width:27px;height:27px}h1{font-size:24px}}`
  markup=`<header><div class="palette">${['primary','secondary','accent','muted','border'].map(k=>`<span class="swatch" style="background:var(--${k})" title="${k}"></span>`).join('')}</div><small id="mode">LIGHT / DARK</small></header><h1>${escape(item.name.en)}</h1><small>Original tweakcn theme · Interface token preview</small><div class="sample"><section class="panel"><div class="label">Activity</div><div class="amount">12,480</div><div class="chart">${[45,68,53,90,78].map((h,i)=>`<i style="height:${h}%;background:var(--chart-${i+1})"></i>`).join('')}</div></section><section class="panel"><span class="badge">Accent</span><div class="actions"><button>Primary</button><button class="secondary">Secondary</button></div><div class="token">colors · radius · typography</div></section></div>`
  js=`const dark=new URLSearchParams(location.search).get('mode')==='dark';document.documentElement.classList.toggle('dark',dark);document.getElementById('mode').textContent=dark?'DARK':'LIGHT';`+report
  await writeFile(resolve(output,item.id+'.js'),js)
 }else{
  const source=resolve(data,item.files[0].path)
  const entry=`import React from 'react';import{createRoot}from'react-dom/client';import Page from ${JSON.stringify(source)};createRoot(document.getElementById('root')).render(<Page/>);${report}`
  const files=await Promise.all(item.files.map(f=>readFile(resolve(data,f.path),'utf8')))
  const original=await readFile(resolve(data,'sources/shadcn/app/globals.css'),'utf8')
  const rules=postcss.parse(original).nodes.filter(rule=>(rule.type==='atrule'&&rule.name==='theme')||(rule.type==='rule'&&[':root','.dark'].includes(rule.selector))).map(rule=>rule.toString()).join('\n')
  const compiler=await compile(await readFile(resolve(root,'node_modules/tailwindcss4/index.css'),'utf8')+'\n@custom-variant dark (&:where(.dark, .dark *));\n'+rules)
  const compiled=postcss.parse(compiler.build(files.join('\n').match(/[^\s"'`<>]+/g)??[]))
  // The official legacy registry mixes v3 [--token] utilities with v4 blocks.
  // Resolve that old shorthand in generated CSS only; preserve original TSX.
  compiled.walkDecls(declaration=>{if(/^--[a-z0-9-]+$/i.test(declaration.value))declaration.value=`var(${declaration.value})`})
  css=compiled.toString()
  css+='\nhtml,body,#root{margin:0;min-height:100%;font-family:Arial,Helvetica,sans-serif}body{background:var(--background);color:var(--foreground)}*{border-color:var(--border)}#root{min-height:100vh}'
  await build({stdin:{contents:entry,loader:'tsx',resolveDir:root},outfile:resolve(output,item.id+'.js'),bundle:true,minify:true,format:'iife',platform:'browser',jsx:'automatic',nodePaths:[resolve(root,'node_modules')],define:{'process.env.NODE_ENV':'"production"'},legalComments:'linked',plugins:[{name:'official-registry',setup(builder){
   builder.onResolve({filter:/^@\/(?:registry\/new-york\/|lib\/utils|hooks\/)/},args=>{
    let name=args.path.replace(/^@\/registry\/new-york\//,'').replace(/^@\//,'')
    const file=item.files.find(f=>f.name===name||f.name===name+'.tsx'||f.name===name+'.ts')
    if(!file)throw Error('Missing original registry dependency: '+name)
    return {path:resolve(data,file.path)}
   })
  }}]})
 }
 await writeFile(resolve(output,item.id+'.css'),css)
 const csp="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
 await writeFile(resolve(output,item.id+'.html'),`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${escape(item.name.en)}</title><link rel="stylesheet" href="./${item.id}.css"></head><body>${markup}<script src="./${item.id}.js"></script></body></html>`)
 return true
}
