"""Import pinned Galaxy files that passed the recorded source review."""
import argparse,hashlib,json,re,subprocess,tarfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'mcp-go/internal/uicatalog/data'
REVISION='adbd2adde0a299a3956ea288fb444ec01891ca41'
CATEGORIES={'Buttons':('按钮','button'),'Cards':('卡片','card'),'Checkboxes':('复选框','checkbox'),'Forms':('表单','form'),'Inputs':('输入框','input'),'loaders':('加载动画','loader'),'Notifications':('通知提示','notification'),'Patterns':('背景图案','pattern'),'Radio-buttons':('单选按钮','radio'),'Toggle-switches':('切换开关','toggle'),'Tooltips':('悬浮提示','tooltip')}

def uses_tailwind(raw,tags):
 classes=' '.join(re.findall(r'class\s*=\s*["\']([^"\']+)["\']',raw.decode('utf-8'))).split()
 utilities=sum(bool(re.match(r'^(?:bg|text|w|h|p|m|px|py|mx|my|rounded|border|shadow|inset|top|left|right|bottom|z|gap|space|translate|scale|rotate|duration|opacity)-',token)) for token in classes)
 return utilities>=3 or any('tailwind' in tag.lower() for tag in tags)
TAGS={'animated':'动态','animation':'动效','hover':'悬停','rounded':'圆角','gradient':'渐变','neon':'霓虹','glow':'发光','3d':'立体','dark':'深色','light':'浅色','minimal':'极简','minimalist':'极简','simple':'简约','colorful':'彩色','modern':'现代','glass':'玻璃','glassmorphism':'毛玻璃','loading':'加载','spinner':'旋转','pulse':'脉冲','blue':'蓝色','green':'绿色','red':'红色','purple':'紫色','pink':'粉色','orange':'橙色','black':'黑色','white':'白色','skeuomorphism':'拟物','retro':'复古','toggle':'开关','switch':'开关','checkbox':'复选框','button':'按钮','card':'卡片','input':'输入框','form':'表单','pattern':'图案','tooltip':'提示','radio':'单选','submit':'提交','search':'搜索','login':'登录','sign up':'注册','border':'边框','shadow':'阴影','loader':'加载','loading animation':'加载动画','hover button':'悬停按钮','tailwind':'Tailwind','tailwindcss':'Tailwind','css':'CSS'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--repository',type=Path,required=True);p.add_argument('--review',type=Path,required=True);args=p.parse_args()
 assert subprocess.check_output(['git','-C',str(args.repository),'rev-parse','HEAD'],text=True).strip()==REVISION
 review=json.loads(args.review.read_text(encoding='utf-8'))
 assert len(review)>=3000
 archive=args.review.parent/'galaxy-source-raw.tar'
 if not archive.exists():subprocess.run(['git','-c','core.autocrlf=false','-C',str(args.repository),'archive','--format=tar','--output='+str(archive.resolve()),REVISION],check=True)
 old=json.loads((DATA/'catalog.json').read_text(encoding='utf-8'));existing={item['id']:item for item in old['items']}
 now=datetime.now(timezone.utc).isoformat();new=[]
 with tarfile.open(archive) as tar:
  licence=tar.extractfile('LICENSE').read();readme=tar.extractfile('README.md').read()
  assert b'MIT License' in licence and b'All UI elements in this repository' in readme and b'**MIT License**' in readme
  notices=[]
  for filename,raw in [('LICENSE',licence),('README.md',readme)]:
   path=DATA/'licenses/galaxy'/filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
   notices.append({'name':f'licenses/galaxy/{filename}','path':f'licenses/galaxy/{filename}','sha256':hashlib.sha256(raw).hexdigest()})
  for record in review:
   path=record['path'];raw=tar.extractfile(path).read();author=record['author'];kind=record['category'];zh,en=CATEGORIES[kind]
   assert record['sha256']==hashlib.sha256(raw).hexdigest(),'Reviewed bytes differ from pinned source: '+path
   item_id='galaxy-'+en+'-'+hashlib.sha256(path.encode()).hexdigest()[:16]
   target=DATA/'sources/galaxy'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
   tags=record['tags'];styles=list(dict.fromkeys(TAGS[tag.lower()] for tag in tags if tag.lower() in TAGS and TAGS[tag.lower()]!=zh))
   slug=Path(path).stem.split('_',1)[-1]
   title=' '.join(styles[:2]+[zh])+' · '+author
   evidence=f'/ui-library/assets/galaxy/evidence/{REVISION}/manifest.json'
   new.append({'id':item_id,'name':{'zh':title,'en':slug.replace('-',' ').title()+' '+en.title()},'description':{'zh':f'Uiverse 作者 {author} 的原版{zh}；标签：'+', '.join(tags),'en':f'Original {en} by {author} on Uiverse. Tags: '+', '.join(tags)},'notes':{'zh':'保留作者署名、MIT 许可证和原始 HTML/CSS。预览不下载外部资源；系统未安装的字体使用浏览器回退字体。授权声明与固定版本证据已归档。','en':'Preserve creator attribution, MIT notices and original HTML/CSS. Previews do not download external resources; unavailable fonts use browser fallbacks. Publisher licensing statements and pinned revision evidence are archived.'},'provider':'Uiverse','provider_id':'galaxy','author':author,'license':'MIT','license_url':'/ui-library/licenses/galaxy/LICENSE','revision':REVISION,'source_url':'https://github.com/uiverse-io/galaxy/blob/'+REVISION+'/'+quote(path),'demo_url':'https://uiverse.io/'+quote(author)+'/'+quote(slug),'category':'background' if kind=='Patterns' else 'component','frameworks':['html'],'aliases':list(dict.fromkeys(tags+styles+[zh,en,'html','css','uiverse','ui','component','template','组件','素材','模板'])),'files':[{'name':path,'path':'sources/galaxy/'+path,'sha256':hashlib.sha256(raw).hexdigest()}],'notices':notices,'assets':[],'dependencies':{'tailwindcss':'3.4.19'} if uses_tailwind(raw,tags) else {},'export_name':'','props':{},'preview_kind':'html','preview_url':f'/ui-library/previews/{item_id}.html','poster_url':f'/ui-library/posters/{item_id}.png','clip_url':'','added_at':existing.get(item_id,{}).get('added_at',now),'rights_evidence_url':evidence})
 groups={kind:[item for item in new if Path(item['files'][0]['path']).parent.name==kind] for kind in CATEGORIES}
 new=[group[index] for index in range(max(map(len,groups.values()))) for group in groups.values() if index<len(group)]
 ids={item['id'] for item in new}
 old['items']=[item for item in old['items'] if item['id'] not in ids]+new
 (DATA/'catalog.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 locks=json.loads((DATA/'upstreams.json').read_text());locks['galaxy']={'repository':'uiverse-io/galaxy','revision':REVISION,'license_source':'LICENSE'}
 (DATA/'upstreams.json').write_text(json.dumps(locks,indent=2)+'\n')
 print(json.dumps({'imported':len(new),'total':len(old['items']),'revision':REVISION}))

if __name__=='__main__':main()
