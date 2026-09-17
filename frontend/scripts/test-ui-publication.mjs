import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
const run=process.env.UI_PUBLICATION_RUN
if(!run) throw Error('UI_PUBLICATION_RUN is required')
const reviews=JSON.parse(await readFile(resolve(run,'reviews.json'),'utf8'))
const ids=reviews.filter(row=>row.status==='published'&&row.item_id).map(row=>row.item_id)
const catalog=JSON.parse(await readFile(resolve(run,'dist/ui-library/catalog.json'),'utf8'))
const recent=catalog.items.filter(item=>Date.parse(item.added_at)>Date.now()-86400000).sort((a,b)=>Date.parse(b.added_at)-Date.parse(a.added_at))
const args=process.env.UI_PUBLICATION_EDGE_IP ? [`--host-resolver-rules=MAP aigcnews.cn ${process.env.UI_PUBLICATION_EDGE_IP}`] : []
const browser=await chromium.launch({channel:'chrome',headless:true,args})
const page=await browser.newPage({viewport:{width:1920,height:1080},locale:'zh-CN'})
const errors=[]
page.on('pageerror',error=>errors.push(error.message))
try{
 await page.goto('https://aigcnews.cn/ui-library?rank=new',{waitUntil:'domcontentloaded'})
 await page.waitForFunction(()=>document.querySelectorAll('.ui-library__card').length===96)
 const shown=await page.locator('.ui-library__card').evaluateAll(nodes=>nodes.map(node=>node.dataset.templateId))
 assert.deepEqual(shown,recent.slice(0,96).map(item=>item.id))
 assert.ok(ids.every(id=>shown.includes(id)))
 await page.waitForFunction(()=>document.querySelectorAll('video.ui-library__card-preview.is-ready').length>=4)
 await page.screenshot({path:resolve(run,'production-new-today.png')})
 const item=catalog.items.find(item=>item.id===ids[0])
 assert.ok(item.poster_url.endsWith('.webp')&&item.clip_url.endsWith('.mp4'))
 await page.goto('https://aigcnews.cn/ui-library/'+item.id+'?rank=new')
 const dialog=page.locator('dialog.ui-detail')
 await dialog.waitFor()
 await dialog.locator('pre code .hljs-tag').first().waitFor()
 await dialog.locator('.ui-detail__preview-status').waitFor({state:'hidden'})
 assert.equal(await dialog.locator('.ui-detail__preview-error').count(),0)
 assert.equal(await dialog.getByRole('link',{name:'查看授权与版本存档'}).getAttribute('href'),item.rights_evidence_url)
 await page.screenshot({path:resolve(run,'production-detail.png')})
 await dialog.locator('.ui-detail__copy-prompt').click()
 await page.getByRole('dialog').locator('input[autocomplete="current-password"]').waitFor()
 const results=[]
 for(const q of ['HyperUI 徽章','HyperUI badges']){
  await page.goto('https://aigcnews.cn/ui-library?framework=html&q='+encodeURIComponent(q))
  await page.locator('.ui-library__card').first().waitFor()
  results.push(await page.locator('.ui-library__card').evaluateAll(nodes=>nodes.map(node=>node.dataset.templateId).sort()))
 }
 assert.deepEqual(results[0],results[1])
 assert.ok(results[0].length>2)
 assert.deepEqual(errors,[])
 await writeFile(resolve(run,'browser-verification.json'),JSON.stringify({total:catalog.items.length,newlyPublished:ids.length,newTodayOrder:true,sourceHighlight:true,preview:true,licenseEvidenceLink:true,loginRequired:true,bilingualSearch:true,errors},null,2))
 console.log('Public daily publication verified: '+ids.length+' new / '+catalog.items.length+' total')
}finally{await browser.close()}
