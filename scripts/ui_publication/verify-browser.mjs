import { chromium } from 'playwright'
const id=process.env.UI_VERIFY_ID
if(!/^hyperui-[a-z0-9-]+$/.test(id??'')) throw Error('Invalid verification ID')
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--host-resolver-rules=MAP aigcnews.cn 118.89.101.11']})
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}})
 await page.goto('https://aigcnews.cn/ui-library?rank=new&q=HyperUI',{waitUntil:'domcontentloaded'})
 const card=page.locator(`[data-template-id="${id}"]`)
 await card.waitFor({timeout:120000})
 await card.scrollIntoViewIfNeeded()
 await card.locator('.ui-card-frame.is-ready iframe').waitFor({timeout:45000})
 console.log('Published card uses a ready HTML iframe: '+id)
}finally{await browser.close()}
