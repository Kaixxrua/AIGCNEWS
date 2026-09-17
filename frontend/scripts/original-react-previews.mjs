// Packaging for reviewed upstream examples. Source files remain byte-for-byte original.
import {readFile,writeFile} from 'node:fs/promises'
import {realpathSync} from 'node:fs'
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
 if(item.preview_preset){const preset=originals.find(file=>file.name===item.preview_preset);if(!preset)throw Error('Missing original preset CSS: '+item.id);const presetParsed=postcss.parse(preset.text);const presetRules=[];presetParsed.walkRules(rule=>{if([':root','.dark'].includes(rule.selector))presetRules.push(rule.toString())});for(const rule of presetParsed.nodes){if(rule.type==='atrule'&&['theme','keyframes','utility','custom-variant'].includes(rule.name)){presetRules.push(rule.toString()+(rule.nodes?'':';'));if(rule.name==='theme'&&/\binline\b/.test(rule.params)){const decls=(rule.nodes??[]).filter(node=>node.type==='decl').map(node=>node.toString());if(decls.length)presetRules.push(':root{'+decls.join(';')+'}')}}}rules.unshift(...presetRules)}
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
   const body=args.path.slice(2)
   const rule=(item.preview_alias_rules||[]).find(([prefix])=>body.startsWith(prefix))
   const name=rule?rule[1]+body.slice(rule[0].length):(item.preview_root?item.preview_root+'/':'')+body
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
  builder.onResolve({filter:/^@[^/]+\//},args=>{
   const dirs=item.preview_package_dirs||{}
   const base=Object.keys(dirs).find(name=>args.path===name||args.path.startsWith(name+'/'))
   if(!base)return
   const rest=args.path.slice(base.length).replace(/^\//,'')
   const stem=dirs[base]+(rest?'/'+rest:'/index')
   const file=item.files.find(file=>[stem,stem+'.tsx',stem+'.ts',stem+'.jsx',stem+'.js',stem+'/index.tsx',stem+'/index.ts'].includes(file.name))
   if(!file)throw Error('Missing original workspace package import: '+args.path)
   return {path:resolve(data,file.path)}
  })
  builder.onResolve({filter:/^\.\.?\//},args=>{
   let importer
   try{importer=item.files.find(file=>realpathSync(resolve(data,file.path))===realpathSync(args.importer))}catch{return}
   if(!importer)return
   const name=posix.normalize(posix.join(posix.dirname(importer.name),args.path))
   const file=item.files.find(file=>[name,name+'.tsx',name+'.ts',name+'.jsx',name+'.js',name+'/index.tsx',name+'/index.ts'].includes(file.name))
   if(!file)return
   return {path:resolve(data,file.path)}
  })
  builder.onResolve({filter:/^next\//},args=>({path:args.path,namespace:'standalone'}))
  builder.onLoad({filter:/.*/,namespace:'standalone'},({path})=>{
   if(path==='next/link')return {contents:`import React from 'react';export default React.forwardRef(function Link({href,children,prefetch,replace,scroll,shallow,locale,...props},ref){return <a {...props} ref={ref} href={typeof href==='string'?href:'#'} onClick={event=>event.preventDefault()}>{children}</a>})`,loader:'tsx',resolveDir:root}
   if(path==='next/image')return {contents:`import React from 'react';export default function Image({src,alt,fill,width,height,style,...props}){const resolved=typeof src==='string'?src:(src&&src.src)||'';const finalStyle=fill?{position:'absolute',inset:0,width:'100%',height:'100%',objectFit:'cover',...style}:style;if(!resolved)return <span aria-label={alt||''} style={{display:'inline-block',width:width||'100%',height:height||64,background:'var(--muted,#eee)',...finalStyle}}/>;return <img {...props} src={resolved} alt={alt||''} width={fill?undefined:width} height={fill?undefined:height} style={finalStyle}/>}`,loader:'tsx',resolveDir:root}
   if(path.startsWith('next/font'))return {contents:`const font=()=>({className:'',style:{fontFamily:'inherit'},variable:''});export const Inter=font,Roboto=font,Montserrat=font,Poppins=font,Geist=font,Geist_Mono=font,Instrument_Serif=font,Playfair_Display=font,Space_Grotesk=font,DM_Sans=font,Manrope=font,Plus_Jakarta_Sans=font,Outfit=font,Work_Sans=font,Lora=font,Merriweather=font,Open_Sans=font,Be_Vietnam_Pro=font,IBM_Plex_Mono=font,JetBrains_Mono=font,Fira_Code=font,Source_Serif_4=font,Libre_Baskerville=font,Archivo=font,Rubik=font,Nunito=font,Oswald=font,Raleway=font,Urbanist=font,Sora=font,Public_Sans=font,Figtree=font,Bricolage_Grotesque=font,Press_Start_2P=font,Silkscreen=font,VT323=font,Pixelify_Sans=font,DotGothic16=font,Bungee=font,Monoton=font,Cinzel=font,Cormorant_Garamond=font,EB_Garamond=font,Bodoni_Moda=font,Fraunces=font,Kanit=font,Teko=font,Chakra_Petch=font,Orbitron=font,Audiowide=font,Tourney=font;export default font`,loader:'ts',resolveDir:root}
   if(path==='next/navigation')return {contents:`export const useRouter=()=>({push:()=>{},replace:()=>{},back:()=>{},forward:()=>{},refresh:()=>{},prefetch:()=>{}});export const usePathname=()=>'/';export const useSearchParams=()=>new URLSearchParams();export const useParams=()=>({});export const redirect=()=>{};export const notFound=()=>{};export const useSelectedLayoutSegment=()=>null;export const useSelectedLayoutSegments=()=>[]`,loader:'ts',resolveDir:root}
   if(path==='next/script')return {contents:`import React from 'react';export default function Script(){return null}`,loader:'tsx',resolveDir:root}
   if(path==='next/dynamic')return {contents:`import React from 'react';export default function dynamic(loader){return function DynamicComponent(props){const [Loaded,setLoaded]=React.useState(null);React.useEffect(()=>{loader().then(m=>setLoaded(()=>m.default||m))},[]);return Loaded?<Loaded {...props}/>:null}}`,loader:'tsx',resolveDir:root}
   return {contents:'export default {}',loader:'ts',resolveDir:root}
  })
 }}]})
 const closureCss=originals.filter(file=>file.name.endsWith('.css')&&file.name!==item.preview_css&&file.name!==item.preview_preset).map(file=>`/* ${file.name} */\n`+file.text.replace(/@import[^;]+;/g,'')).join('\n')
 await writeFile(resolve(output,item.id+'.css'),css+'\n'+closureCss)
 if(process.env.UI_PREVIEW_BUILD_METAFILES==='1')await writeFile(resolve(output,item.id+'.build.json'),JSON.stringify(result.metafile))
 const csp="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
 await writeFile(resolve(output,item.id+'.html'),`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${escape(item.name.en)}</title><link rel="stylesheet" href="./${item.id}.css"></head><body><div id="root"></div><script src="./${item.id}.js"></script></body></html>`)
 return true
}
