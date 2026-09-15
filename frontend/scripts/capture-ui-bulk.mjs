// Each poster is a screenshot of the original source inside the production sandbox.
import { chromium } from 'playwright'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
const data=resolve('../mcp-go/internal/uicatalog/data')
const report=resolve(process.env.UI_RENDER_REPORT_FILE||'../test-results/ui-expansion/bulk-render-report.json')
const {items}=JSON.parse(await readFile(resolve(data,'catalog.json'),'utf8'))
const ids=process.env.UI_CAPTURE_IDS_FILE ? JSON.parse(await readFile(process.env.UI_CAPTURE_IDS_FILE,'utf8')) : null
const selected=items.filter(item=>item.provider_id==='galaxy'&&(!ids||ids.includes(item.id)))
const base=process.env.UI_LIBRARY_BASE_URL||'http://127.0.0.1:18784'
await mkdir(resolve(data,'posters'),{recursive:true})
const browser=await chromium.launch({channel:'chrome',headless:true})
let index=0
const results=[]
try {
 await Promise.all(Array.from({length:6},async()=>{
  const page=await browser.newPage({viewport:{width:640,height:400},deviceScaleFactor:1})
  let errors=[]
  page.on('pageerror',error=>errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
  page.on('requestfailed',request=>errors.push(request.url()+': '+request.failure()?.errorText))
  while(index<selected.length){
   const item=selected[index++];errors=[]
   let state='error'
   try{
    await page.setContent('<style>html,body{margin:0;width:100%;height:100%}iframe{width:100%;height:100%;border:0;display:block}</style><script>window.previewState="loading";window.addEventListener("message",e=>{if(e.source===document.querySelector("iframe").contentWindow&&e.data?.type==="ui-library-preview")window.previewState=e.data.state})</script><iframe sandbox="allow-scripts" src="'+base+item.preview_url+'"></iframe>')
    await page.waitForFunction(()=>window.previewState!=='loading',null,{timeout:20000})
    await page.waitForTimeout(150)
    state=await page.evaluate(()=>window.previewState)
    await page.screenshot({path:resolve(data,'posters',item.id+'.png')})
   }catch(error){errors.push(error.message)}
   results.push({id:item.id,state,errors:[...errors]})
   if(results.length%100===0){await writeFile(report,JSON.stringify(results));console.log(JSON.stringify({completed:results.length,total:selected.length,failed:results.filter(row=>row.state!=='ready'||row.errors.length).length}))}
  }
  await page.close()
 }))
}finally{
 await browser.close()
 await writeFile(report,JSON.stringify(results,null,2))
}
console.log(JSON.stringify({completed:results.length,failed:results.filter(row=>row.state!=='ready'||row.errors.length).length}))
