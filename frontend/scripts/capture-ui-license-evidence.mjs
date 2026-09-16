import { chromium } from 'playwright'
import { readFile, writeFile, access } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
const data=resolve('../mcp-go/internal/uicatalog/data')
const locks=JSON.parse(await readFile(resolve(data,'upstreams.json'),'utf8'))
const channel=process.env.PLAYWRIGHT_CHANNEL
const executablePath=process.env.PLAYWRIGHT_EXECUTABLE_PATH
const browser=await chromium.launch({...channel?{channel}:{},...executablePath?{executablePath}:{},headless:true})
try {
 const page=await browser.newPage({viewport:{width:1440,height:1080}})
 for(const [provider,lock] of Object.entries(locks)){
  const dir=resolve(data,'assets',provider,'evidence',lock.revision)
  const path=resolve(dir,'manifest.json'), manifest=JSON.parse(await readFile(path,'utf8'))
  if(manifest.screenshot_sha256){await access(resolve(dir,manifest.screenshot));continue}
  const response=await page.goto(manifest.license_page_url,{waitUntil:'domcontentloaded',timeout:60000})
  if(!response?.ok())throw Error(provider+' license page HTTP '+response?.status())
  await page.getByText(manifest.license==='Apache-2.0'?'Apache License':'MIT License',{exact:false}).first().waitFor({timeout:20000})
  await page.screenshot({path:resolve(dir,'license-page.png'),fullPage:true})
  manifest.screenshot_sha256=createHash('sha256').update(await readFile(resolve(dir,'license-page.png'))).digest('hex')
  manifest.screenshot_captured_at=new Date().toISOString()
  await writeFile(path,JSON.stringify(manifest,null,2)+'\n')
  console.log(provider+' evidence screenshot saved')
 }
} finally {await browser.close()}
