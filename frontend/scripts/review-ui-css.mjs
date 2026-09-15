import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import postcss from 'postcss'
const data=resolve('../mcp-go/internal/uicatalog/data')
const catalog=JSON.parse(await readFile(resolve(data,'catalog.json'),'utf8'))
const rejected=[]
for(const item of catalog.items.filter(item=>item.provider_id==='galaxy')){
 const raw=await readFile(resolve(data,item.files[0].path),'utf8')
 try { postcss.parse([...raw.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(m=>m[1]).join('\n')) }
 catch(error){rejected.push({id:item.id,path:item.files[0].path,reason:error.reason})}
}
catalog.items=catalog.items.filter(item=>!rejected.some(row=>row.id===item.id))
if(catalog.items.length<3000)throw Error('Insufficient reviewed entries')
await writeFile(resolve('../test-results/ui-expansion/rejected-css.json'),JSON.stringify(rejected,null,2))
await writeFile(resolve(data,'catalog.json'),JSON.stringify(catalog,null,2)+'\n')
console.log(JSON.stringify({remaining:catalog.items.length,rejected:rejected.length}))
