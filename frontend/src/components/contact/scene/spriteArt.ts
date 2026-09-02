/**
 * 像素原野全部美术数据——本文件内所有像素均为手工逐格编写的原创数据，
 * 不含任何外部素材、AI 生成素材或八方旅人（Octopath Traveler）等既有游戏的
 * 资产/逐像素设计；仅借鉴「3 头身 Q 版 + 有限色板 + 色相偏移」这类公开技法。
 *
 * 结构：
 * - NPC/动物/道具：手写字符串点阵（'.' 透明），字母查色板；
 * - 远景剪影带（山/树线/地面/小径/草）：确定性程序化生成（mulberry32 种子噪声），
 *   白底 alpha 剪影，运行时按视口宽度重生成，保证 1 美术像素 = 1 低分缓冲像素。
 * 纸娃娃组装：NPC = 身体块（18 行）+ 腿带（6 行）；待机 bob = 整体上移 1px；
 * 眨眼 = 眼睛字母 'e' 全局替换为肤色 's'；反应帧 = 手写举手/举杖变体 + 上移跳起。
 */
import type { PixelFrame } from './sprites'
import { mulberry32 } from './events'

/* ── 组装辅助 ─────────────────────────────────────────────── */

/** 点阵块 → PixelFrame：行右补 '.' 到块内最长行（右侧皆为透明像素） */
const mk = (block: string, palette: Record<string, string>): PixelFrame => {
  const rows = block.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')
  const width = Math.max(...rows.map((row) => row.length))
  return { rows: rows.map((row) => row.padEnd(width, '.')), palette }
}

const emptyRow = (width: number): string => '.'.repeat(width)

/** 整体上移 1px（待机呼吸 bob / 反应小跳）；要求首行留空 */
const shiftUp = (rows: string[]): string[] => {
  const width = rows[0]?.length ?? 0
  return [...rows.slice(1), emptyRow(width)]
}

/** 眨眼帧：眼睛字母替换为肤色 */
const withBlink = (rows: string[]): string[] => rows.map((row) => row.replace(/e/g, 's'))

const compose = (body: string[], legs: string[]): string[] => [...body, ...legs]

/* ── NPC 色板（字母语义全体共用，色值按角色区分剪影以外的身份） ── */

const NPC_COMMON = {
  o: '#26231f', // 轮廓
  s: '#f0c8a0', // 皮肤
  S: '#d8a074', // 皮肤阴影
  e: '#26231f', // 眼睛
  m: '#b56a54', // 嘴
  b: '#4a3a2c', // 鞋
  w: '#fff6e8', // 亮部（胡须/眼白）
}

const KID_PALETTE = {
  ...NPC_COMMON,
  t: '#f0e0b8', // 奶油T恤
  T: '#d8c89a',
  p: '#5a7ab8', // 短裤
  P: '#4a669a',
  h: '#d95f4a', // 棒球帽
  H: '#b84a3a',
  a: '#fff0d0', // 帽扣
}

const ELDER_PALETTE = {
  ...NPC_COMMON,
  t: '#6a6f8a', // 灰蓝长外套
  T: '#565a72',
  p: '#4a4a52',
  P: '#3a3a42',
  h: '#d8d8d0', // 白鬓发
  H: '#b8b8b0',
  c: '#6a4a30', // 手杖
  b: '#3a3028',
}

const MERCHANT_PALETTE = {
  ...NPC_COMMON,
  t: '#7a4a3a', // 棕衫
  T: '#623a2e',
  p: '#3f3a45',
  P: '#322e38',
  h: '#3a2e26', // 发
  H: '#c8903a', // 束发带
  a: '#e8dcc0', // 围裙
  A: '#c9bb9a', // 围裙下摆阴影
}

const TRAVELER_PALETTE = {
  ...NPC_COMMON,
  t: '#4a6a58', // 绿斗篷
  T: '#3a5648',
  p: '#5a4a38',
  P: '#463a2c',
  h: '#c8a86a', // 宽檐草帽
  H: '#a88850',
  a: '#6a4a30', // 帽带/挎包带
}

/* ── 小孩（棒球帽，个子最矮） ── */

const KID_BODY = `
................
.....oooooo.....
....ohhhhho.....
...ohhhhhhao....
...ohhhhhhhhho..
...oooooooooo...
...osssssso.....
...osssssso.....
...oseseso......
...osssssso.....
...osSsmso......
....ossso.......
....osso........
...otttttto.....
..osttttttso....
..otttttttto....
..otttttttto....
...oTTTTTTo.....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const KID_LEGS_STAND = `
...oppppppo.....
...oppppppo.....
...osso.osso....
...osso.osso....
...obbo.obbo....
...obbo.obbo....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const KID_LEGS_CONTACT_R = `
...oppppppo.....
...oppppppo.....
..osso..osso....
..osso...osso...
.obbo....obbo...
.obbo.....obbo..
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const KID_LEGS_CONTACT_L = `
...oppppppo.....
...oppppppo.....
....osso..osso..
...osso...osso..
...obbo....obbo.
..obbo.....obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const KID_LEGS_PASSING = `
...oppppppo.....
...oppppppo.....
....ossssso.....
....ossssso.....
....obbbbo......
....obbbbo......
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/** 小孩反应：右手举过肩挥手 */
const KID_BODY_REACT = `
................
.....oooooo.....
....ohhhhho.....
...ohhhhhhao....
...ohhhhhhhhho..
...oooooooooo...
...osssssso.....
...osssssso.....
...oseseso......
...osssssso.....
...osSmmso......
....ossso..o....
....osso...so...
...otttttto.so..
..osttttttto....
..otttttttto....
..otttttttto....
...oTTTTTTo.....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/* ── 老人（白鬓发、驼背、拄杖） ── */

const ELDER_BODY = `
................
................
.....ooooo......
....ossssso.....
...ohosssoho....
....ossssso.....
....oseseso.....
....ossssso.....
....oswwwso.....
.....ossso......
.....ottto......
....ottttto.....
...otttttto.....
..otttttttto....
..ottttttttsoc..
..otttttttto.c..
..otttttttt..c..
..otttttttt..c..
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const ELDER_LEGS_STAND = `
...otttttto..c..
...oTTTTTTo..c..
...osso.osso.c..
...osso.osso.c..
...obbo.obbo.c..
...obbo.obbo.cc.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const ELDER_LEGS_CONTACT_R = `
...otttttto..c..
...oTTTTTTo..c..
..osso..osso.c..
..osso...osso.c.
.obbo....obbo.c.
.obbo.....obbo.c
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const ELDER_LEGS_CONTACT_L = `
...otttttto..c..
...oTTTTTTo..c..
....osso..osso.c
...osso...osso.c
...obbo....obbo.
..obbo.....obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const ELDER_LEGS_PASSING = `
...otttttto..c..
...oTTTTTTo..c..
....ossssso..c..
....ossssso..c..
....obbbbo...c..
....obbbbo...c..
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/** 老人反应：举杖致意（杖整体上移 2px） */
const ELDER_BODY_REACT = `
................
................
.....ooooo......
....ossssso.....
...ohosssoho....
....ossssso.....
....oseseso.....
....ossssso.....
....oswwwso.....
.....ossso......
.....ottto..c...
....ottttto..c..
...otttttto..c..
..ottttttttosc..
..otttttttto....
..otttttttt.....
..otttttttt.....
..otttttttt.....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const ELDER_LEGS_REACT = `
...otttttto.....
...oTTTTTTo.....
...osso.osso....
...osso.osso....
...obbo.obbo....
...obbo.obbo....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/* ── 商人（束发带、围裙、体态最宽） ── */

const MERCHANT_BODY = `
................
....oooooo......
...ohhhhhho.....
...oHHHHHHo.....
...ohhhhhho.....
...osssssso.....
...osssssso.....
...oseseso......
...osssssso.....
...osSsmso......
....osssso......
....osso........
...otttttto.....
..otttttttto....
..ostttttttso...
..ottaaaaatto...
..ottaaaAatto...
..otTaaaATto....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const MERCHANT_LEGS_STAND = `
...oaaaaaao.....
...oAAAAAAo.....
...osso..osso...
...osso..osso...
...obbo..obbo...
...obbo..obbo...
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const MERCHANT_LEGS_CONTACT_R = `
...oaaaaaao.....
...oAAAAAAo.....
..osso...osso...
..osso....osso..
.obbo.....obbo..
.obbo......obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const MERCHANT_LEGS_CONTACT_L = `
...oaaaaaao.....
...oAAAAAAo.....
...osso...osso..
..osso....osso..
..obbo.....obbo.
.obbo......obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const MERCHANT_LEGS_PASSING = `
...oaaaaaao.....
...oAAAAAAo.....
....ossssso.....
....ossssso.....
....obbbbo......
....obbbbo......
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/** 商人反应：单手高举招呼 */
const MERCHANT_BODY_REACT = `
................
....oooooo......
...ohhhhhho.....
...oHHHHHHo.....
...ohhhhhho.....
...osssssso.....
...osssssso.....
...oseseso...o..
...osssssso..so.
...osSmmso...so.
....osssso...o..
....osso........
...otttttto.....
..otttttttto....
..otttttttto....
..ottaaaaatto...
..ottaaaaatto...
..otTaaaATto....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/* ── 旅人（宽檐草帽、斗篷、挎包带） ── */

const TRAVELER_BODY = `
................
.....oooooo.....
....ohhhhho.....
...ohhhhhhhho...
..ohhhhhhhhhho..
...oaaaaaao.....
....ossssso.....
....ossssso.....
....oseseso.....
....ossssso.....
....osSsmso.....
.....ossso......
.....osso.......
....otttttto....
...otttttttto...
...ottttttttso..
...otttatttto...
...otttttttto...
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const TRAVELER_LEGS_STAND = `
...otttttttto...
...oTTTTTTTTo...
....osso.sso....
....osso.sso....
....obbo.bbo....
....obbo.bbo....
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const TRAVELER_LEGS_CONTACT_R = `
...otttttttto...
...oTTTTTTTTo...
..osso...osso...
..osso....osso..
.obbo.....obbo..
.obbo......obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const TRAVELER_LEGS_CONTACT_L = `
...otttttttto...
...oTTTTTTTTo...
...osso...osso..
..osso....osso..
..obbo.....obbo.
.obbo......obbo.
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

const TRAVELER_LEGS_PASSING = `
...otttttttto...
...oTTTTTTTTo...
....ossssso.....
....ossssso.....
....obbbbo......
....obbbbo......
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/** 旅人反应：抬手扶帽檐致意 */
const TRAVELER_BODY_REACT = `
................
.....oooooo.....
....ohhhhho.....
...ohhhhhhhho...
..ohhhhhhhhhho..
...oaaaaaao...o.
....ossssso..so.
....ossssso..so.
....oseseso...o.
....ossssso.....
....osSmmso.....
.....ossso......
.....osso.......
....otttttto....
...otttttttto...
...otttttttto...
...otttatttto...
...otttttttto...
`.replace(/^\n+/, '').replace(/\s+$/, '').split('\n')

/* ── NPC 帧集组装 ── */

export interface NpcArt {
  idle: PixelFrame[]
  walk: PixelFrame[]
  react: PixelFrame[]
  width: number
  height: number
}

interface NpcParts {
  palette: Record<string, string>
  body: string[]
  legsStand: string[]
  legsContactR: string[]
  legsContactL: string[]
  legsPassing: string[]
  bodyReact: string[]
  /** 反应帧用不同的腿带（如老人举杖后杖不在腿带里） */
  legsReact?: string[]
}

const buildNpc = (parts: NpcParts): NpcArt => {
  const frame = (rows: string[]): PixelFrame => ({ rows, palette: parts.palette })
  const stand = compose(parts.body, parts.legsStand)
  const reactLegs = parts.legsReact ?? parts.legsStand
  const reactBase = compose(parts.bodyReact, reactLegs)
  return {
    idle: [
      frame(stand),
      frame(shiftUp(stand)),
      frame(withBlink(stand)),
      frame(shiftUp(stand)),
    ],
    walk: [
      frame(compose(parts.body, parts.legsContactR)),
      frame(compose(parts.body, parts.legsPassing)),
      frame(compose(parts.body, parts.legsContactL)),
      frame(compose(parts.body, parts.legsPassing)),
    ],
    react: [frame(reactBase), frame(shiftUp(reactBase))],
    width: 16,
    height: 24,
  }
}

export const KID = buildNpc({
  palette: KID_PALETTE,
  body: KID_BODY,
  legsStand: KID_LEGS_STAND,
  legsContactR: KID_LEGS_CONTACT_R,
  legsContactL: KID_LEGS_CONTACT_L,
  legsPassing: KID_LEGS_PASSING,
  bodyReact: KID_BODY_REACT,
})

export const ELDER = buildNpc({
  palette: ELDER_PALETTE,
  body: ELDER_BODY,
  legsStand: ELDER_LEGS_STAND,
  legsContactR: ELDER_LEGS_CONTACT_R,
  legsContactL: ELDER_LEGS_CONTACT_L,
  legsPassing: ELDER_LEGS_PASSING,
  bodyReact: ELDER_BODY_REACT,
  legsReact: ELDER_LEGS_REACT,
})

export const MERCHANT = buildNpc({
  palette: MERCHANT_PALETTE,
  body: MERCHANT_BODY,
  legsStand: MERCHANT_LEGS_STAND,
  legsContactR: MERCHANT_LEGS_CONTACT_R,
  legsContactL: MERCHANT_LEGS_CONTACT_L,
  legsPassing: MERCHANT_LEGS_PASSING,
  bodyReact: MERCHANT_BODY_REACT,
})

export const TRAVELER = buildNpc({
  palette: TRAVELER_PALETTE,
  body: TRAVELER_BODY,
  legsStand: TRAVELER_LEGS_STAND,
  legsContactR: TRAVELER_LEGS_CONTACT_R,
  legsContactL: TRAVELER_LEGS_CONTACT_L,
  legsPassing: TRAVELER_LEGS_PASSING,
  bodyReact: TRAVELER_BODY_REACT,
})

/* ── 猫（14×10：舔毛×2 / 走×2 / 逃窜×2） ── */

const CAT_PALETTE = {
  o: '#26231f',
  f: '#e8a860', // 橘猫
  F: '#c88848',
  w: '#fff0e0',
  e: '#26231f',
  p: '#e89090', // 鼻/耳廓
}

const CAT_GROOM_A = mk(`
....o.o.......
...offfo......
...ofefo......
...offoff.....
...offof......
..oofffo......
.offfffo......
.offfffoo.....
.offfow.oooo..
.ooooowwo...o.
`, CAT_PALETTE)

const CAT_GROOM_B = mk(`
............
....o.o.....
...offfo....
...ofefo....
...offoff...
..ooffof....
.offfffo....
.offfffoo...
.offfow.oooo..
.ooooowwo...o.
`, CAT_PALETTE)

const CAT_WALK_A = mk(`
o........o.o..
oo......offfo.
ooooooooofefo.
.ooooooooooooo
.offfffffffwo.
.offfffffffFo.
..of..of..ofof
..of..of..ofof
..ow..ow..owow
............
`, CAT_PALETTE)

const CAT_WALK_B = mk(`
o........o.o..
oo......offfo.
ooooooooofefo.
.ooooooooooooo
.offfffffffwo.
.offfffffffFo.
...of..of..of.
...of..of..of.
...ow..ow..ow.
............
`, CAT_PALETTE)

/** 逃窜：身体拉长压低、腿全展开 */
const CAT_SCURRY_A = mk(`
...........o.o
.o.......offfo
oooooooooofefo
offffffffffffo
.ffffffffffFo.
..of.....of...
.of.......of..
.o.........o..
............
............
`, CAT_PALETTE)

const CAT_SCURRY_B = mk(`
...........o.o
.o.......offfo
oooooooooofefo
offffffffffffo
.ffffffffffFo.
....of.of.....
...of...of....
...o.....o....
............
............
`, CAT_PALETTE)

export const CAT = {
  groom: [CAT_GROOM_A, CAT_GROOM_B],
  walk: [CAT_WALK_A, CAT_WALK_B],
  scurry: [CAT_SCURRY_A, CAT_SCURRY_B],
  width: 14,
  height: 10,
}

/* ── 狗（16×12：走×4 / 坐×2 摇尾） ── */

const DOG_PALETTE = {
  o: '#26231f',
  f: '#c89868',
  F: '#a87848',
  w: '#f0e8d8',
  e: '#26231f',
  n: '#3a2e26', // 鼻
  t: '#e89090', // 舌
}

const DOG_WALK_A = mk(`
..........oo....
.........offfo..
.o.......ofefono
oooooooooofffo..
.ooooooooooo....
.offffffffffo...
.offfffFffffo...
..of..of..of.of.
..of..of..of.of.
..of..of..of.of.
..of..of..of.of.
..ow..ow..ow.ow.
`, DOG_PALETTE)

const DOG_WALK_B = mk(`
..........oo....
.........offfo..
.o.......ofefono
oooooooooofffo..
.ooooooooooo....
.offffffffffo...
.offfffFffffo...
...of..of..of.of
...of..of..of.of
...of..of..of.of
...of..of..of.of
...ow..ow..ow.ow
`, DOG_PALETTE)

const DOG_WALK_C = mk(`
..........oo....
.........offfo..
.o.......ofefono
oooooooooofffo..
.ooooooooooo....
.offffffffffo...
.offfffFffffo...
..of.of..of..of.
..of.of..of..of.
..of.of..of..of.
..of.of..of..of.
..ow.ow..ow..ow.
`, DOG_PALETTE)

const DOG_WALK_D = mk(`
..........oo....
.........offfo..
.o.......ofefono
ooooooooooffto..
.ooooooooooo....
.offffffffffo...
.offfffFffffo...
.of..of..of..of.
.of..of..of..of.
.of..of..of..of.
.of..of..of..of.
.ow..ow..ow..ow.
`, DOG_PALETTE)

const DOG_SIT_A = mk(`
......oo......
.....offfo....
.....ofefono..
.....offfto...
.....offo.....
....offffo....
...offfffo....
..offfffffo...
..offfFfffo...
..offffffof...
..oo...o..of..
..oooooow.ow..
`, DOG_PALETTE)

/** 摇尾帧：尾巴从臀后探出（左侧两格） */
const DOG_SIT_B = mk(`
......oo......
.....offfo....
.....ofefono..
.....offfto...
.....offo.....
....offffo....
...offfffo....
.oofffff.o....
.o.fffFfffo...
..offffffof...
..oo...o..of..
..oooooow.ow..
`, DOG_PALETTE)

export const DOG = {
  walk: [DOG_WALK_A, DOG_WALK_B, DOG_WALK_C, DOG_WALK_D],
  sit: [DOG_SIT_A, DOG_SIT_B],
  width: 16,
  height: 12,
}

/* ── 飞鸟（10×6，两帧振翅） ── */

const BIRD_PALETTE = {
  o: '#26231f',
  f: '#7a9ab8',
  F: '#5a7a98',
  w: '#e8ecf0',
  e: '#26231f',
  a: '#e8a83a', // 喙
}

const BIRD_FLY_A = mk(`
...o......
..ooo.....
..offfoeao
.fffffwwo.
..fffo....
..........
`, BIRD_PALETTE)

const BIRD_FLY_B = mk(`
..........
..........
..offfoeao
.fffffwwo.
..offfo...
...ffo....
`, BIRD_PALETTE)

export const BIRD = { fly: [BIRD_FLY_A, BIRD_FLY_B], width: 10, height: 6 }

/* ── 蝴蝶（5×4，两帧扇翅） ── */

const BUTTERFLY_PALETTE = {
  w: '#f0a8c8',
  W: '#d888a8',
  o: '#3a3030',
}

const BUTTERFLY_A = mk(`
ww.ww
wWoWw
.wow.
..o..
`, BUTTERFLY_PALETTE)

const BUTTERFLY_B = mk(`
.wWw.
.wWw.
..o..
..o..
`, BUTTERFLY_PALETTE)

export const BUTTERFLY = { fly: [BUTTERFLY_A, BUTTERFLY_B], width: 5, height: 4 }

/* ── 对话气泡（14×12：'!' / '…' / '♪'） ── */

const BUBBLE_PALETTE = {
  o: '#23211d',
  f: '#fffdf6',
  i: '#23211d',
}

const bubbleRows = (glyph: string[]): PixelFrame => mk(`
....oooooo....
..ooffffffoo..
.offffffffffo.
${glyph[0]}
${glyph[1]}
${glyph[2]}
${glyph[3]}
${glyph[4]}
..ooffffffoo..
...oo.........
...o..........
..............`, BUBBLE_PALETTE)

export const BUBBLE_EXCLAIM = bubbleRows([
  '.offffifffffo.',
  '.offffifffffo.',
  '.offffifffffo.',
  '.offffffffffo.',
  '.offffifffffo.',
])

export const BUBBLE_DOTS = bubbleRows([
  '.offffffffffo.',
  '.offffffffffo.',
  '.offiffiffifo.',
  '.offffffffffo.',
  '.offffffffffo.',
])

export const BUBBLE_NOTE = bubbleRows([
  '.offffffiiifo.',
  '.offfffffiffo.',
  '.offfffffiffo.',
  '.offffiiiiffo.',
  '.offffiiifffo.',
])

export const BUBBLES = { exclaim: BUBBLE_EXCLAIM, dots: BUBBLE_DOTS, note: BUBBLE_NOTE }

/* ── 路灯柱（12×30 白底 alpha 剪影，材质色 = lampPost；灯芯另由 HDR 面片叠加） ── */

const SILHOUETTE_PALETTE = { x: '#ffffff', d: '#ffffff80' }

export const LAMP_POST: PixelFrame = mk(`
....xxxx....
...xxxxxx...
..xxxxxxxx..
...xxxxxx...
...xx..xx...
...xx..xx...
...xx..xx...
...xxxxxx...
....xxxx....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
.....xx.....
....xxxx....
...xxxxxx...
`, SILHOUETTE_PALETTE)

/* ── 树（叶 28×32 + 干 8×18，白底 alpha 剪影；边缘 50% 抖动） ── */

export const TREE_TRUNK: PixelFrame = mk(`
...xx...
...xx...
...xxx..
...xx.x.
...xx..x
...xx...
...xx...
..xxx...
...xx...
...xx...
...xx...
...xx...
...xx...
...xx...
...xx...
...xx...
..xxxx..
.xxxxxx.
`, SILHOUETTE_PALETTE)

/** 树冠：实心团块 + 底部/右缘有序抖动（50% alpha），内部稀疏抖点模拟叶簇 */
const canopy = (seed: number): PixelFrame => {
  const rng = mulberry32(seed)
  const width = 28
  const height = 32
  const rows: string[] = []
  // 每行半宽（相对中心 13.5）：顶部窄、中部宽、底部略收
  for (let y = 0; y < height; y++) {
    const t = y / (height - 1)
    const bulge = Math.sin(Math.min(t * 1.35, 1) * Math.PI) // 0→1→(底收)
    let half = Math.round(4 + bulge * 9.5)
    if (y > height - 6) half = Math.max(2, half - (y - (height - 6)) * 2)
    const left = Math.max(0, Math.round(13.5 - half))
    const right = Math.min(width - 1, Math.round(13.5 + half))
    let row = ''
    for (let x = 0; x < width; x++) {
      if (x < left || x > right) {
        row += '.'
        continue
      }
      const edge = x === left || x === right || y >= height - 4
      const clump = rng() < 0.08
      row += edge ? ((x + y) % 2 === 0 ? 'd' : 'x') : clump ? 'd' : 'x'
    }
    rows.push(row)
  }
  return { rows, palette: SILHOUETTE_PALETTE }
}

export const TREE_LEAF_A = canopy(0x7a11)
export const TREE_LEAF_B = canopy(0x5e3d)

/* ── 共享 blob 阴影（8×3 白底 alpha） ── */

export const BLOB_SHADOW: PixelFrame = mk(`
..xxxx..
.xxxxxxx
..xxxx..
`, SILHOUETTE_PALETTE)

/* ── 程序化剪影带（山脊/树线/地面/小径/草条），按视口宽度重生成 ── */

/** 两段值噪声：格点随机 + smoothstep 插值 */
const valueNoise1d = (seed: number, freq: number): ((x: number) => number) => {
  const rng = mulberry32(seed)
  const lattice: number[] = []
  const at = (i: number): number => {
    while (lattice.length <= i) lattice.push(rng())
    return lattice[i]!
  }
  return (x: number): number => {
    const gx = x * freq
    const i = Math.floor(gx)
    const f = gx - i
    const u = f * f * (3 - 2 * f)
    return at(i) + (at(i + 1) - at(i)) * u
  }
}

/**
 * 山脊/树线条带： skyline = base + 噪声起伏，线下填实，线顶 1px 50% 抖动。
 * base/amp 为条带内比例（0 顶 1 底）。
 */
export const ridgeStrip = (
  width: number,
  height: number,
  seed: number,
  base: number,
  amp: number,
  freq: number,
): PixelFrame => {
  const noiseA = valueNoise1d(seed, freq)
  const noiseB = valueNoise1d(seed ^ 0x9e37, freq * 2.7)
  const rows: string[][] = Array.from({ length: height }, () => Array<string>(width).fill('.'))
  for (let x = 0; x < width; x++) {
    const n = noiseA(x / width) * 0.7 + noiseB(x / width) * 0.3
    const ridgeY = Math.round((base + (n - 0.5) * 2 * amp) * (height - 1))
    for (let y = Math.max(0, ridgeY); y < height; y++) {
      rows[y]![x] = y === ridgeY ? 'd' : 'x'
    }
  }
  return { rows: rows.map((row) => row.join('')), palette: SILHOUETTE_PALETTE }
}

/** 地面/小径色带：主体填实，顶缘 1px 抖动，内部稀疏亮点（草茎/石子的alpha刻痕） */
export const groundStrip = (
  width: number,
  height: number,
  seed: number,
  speckle: number,
): PixelFrame => {
  const rng = mulberry32(seed)
  const rows: string[][] = Array.from({ length: height }, () => Array<string>(width).fill('.'))
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (y === 0) {
        rows[y]![x] = x % 2 === 0 ? 'd' : 'x'
      } else {
        rows[y]![x] = rng() < speckle ? 'd' : 'x'
      }
    }
  }
  return { rows: rows.map((row) => row.join('')), palette: SILHOUETTE_PALETTE }
}

/** 草条：底部填实，向上长出三角叶片（簇距 ~3px，叶尖 50% alpha） */
export const grassStrip = (width: number, height: number, seed: number): PixelFrame => {
  const rng = mulberry32(seed)
  const rows: string[][] = Array.from({ length: height }, () => Array<string>(width).fill('.'))
  const baseRows = Math.max(1, Math.round(height * 0.25))
  for (let y = height - baseRows; y < height; y++) {
    for (let x = 0; x < width; x++) rows[y]![x] = 'x'
  }
  for (let x = 0; x < width; x++) {
    if (rng() < 0.62) {
      const blade = Math.round(1 + rng() * (height - baseRows - 1))
      const lean = rng() < 0.5 ? 0 : 1
      for (let i = 0; i < blade; i++) {
        const y = height - baseRows - 1 - i
        if (y < 0) break
        const bx = Math.min(width - 1, x + (i > blade / 2 ? lean : 0))
        rows[y]![bx] = i === blade - 1 ? 'd' : 'x'
      }
    }
  }
  return { rows: rows.map((row) => row.join('')), palette: SILHOUETTE_PALETTE }
}
