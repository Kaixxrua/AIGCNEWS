# contact 场景私有化 overlay（AI 卡司版）

**不随开源仓库发布。** 联系页 HD-2D 场景的 AI 卡司版本：开源线上版维持
手写卡司（kid/elder/merchant/traveler + 猫狗），本 overlay 把角色/宠物
整体换成 AI 抽卡底稿 + 机器清洗管线产出的 5 角色 + 2 宠物。

## 内容

`files/` 下为整文件覆盖（相对公共仓 `frontend/src/`）：

| 文件 | 变化 |
|---|---|
| `components/contact/scene/spriteArt.ts` | 重写：整帧动画 DSL（idle 基础帧 + shiftUp 呼吸帧，walk×4，react×1–2），导出 SWORDSMAN/SCHOLAR_F/SCHOLAR_M/KNIGHT/CLOAK + NpcArt 化的 CAT/DOG；鸟/蝶/气泡/路灯/树手写段原样保留 |
| `components/contact/scene/ContactFieldScene.ts` | 卡司接线：事件 kind 字符串不变，变量重接 knight/scholarM/swordsman/cloak + 新增第五人 scholarF；CAT/DOG 调用点简化为直接传 NpcArt |
| `components/contact/scene/spriteArt.test.ts` | 契约测试改写（24×41 角色、18×15 猫、22×15 狗、帧数与剪影互异不变量） |

## 来源与合规（诚实声明）

- 角色/宠物像素数据：原创角色设计提示词的 AI 抽卡底稿（八方旅人2 HD-2D
  风格提示词；带官方 LOGO 的卡已剔除），经确定性清洗管线（手动行框裁帧 →
  软 alpha 修剪 → 网格化 → 联合中位切分量化 → 去噪）转写为 DSL 点阵。
  不含八方旅人（Octopath Traveler）等既有游戏资产或逐像素设计。
- 管线脚本与中间产物在宿主机 `/tmp/spritecrafter/` 与 `/tmp/ai-sprites/`
  （临时目录，重启即失；需要重建时以本 overlay 文件为准）。
- 飞鸟/蝴蝶/气泡/路灯/树仍为手写原创；环境大纹理仍为公共仓程序化烘焙
  （AI 环境纹理批次未启用，随 V2/V3 再议）。

## 部署耦合（关键）

**任何前端 publish 若不先套用本 overlay，线上会回退为手写卡司。**
发布配方（沿用 deploy.py 既有流程）：

```bash
# 1. 干净 detached 发布检出（钉公共仓目标 SHA），symlink node_modules
# 2. 套用 overlay：
python3 /home/kaixxrua/aigcnews_private/frontend-overlay/contact-scene/apply.py <发布检出/frontend>
# 3. 在发布检出内 npm run test:unit（contact 相关）+ npm run typecheck + npm run build
# 4. /tmp inventory 钉双边缘 project_root 到该检出 → deploy.py validate
#    → publish aigcnews --skip-build → publish aigcnews-cn --skip-smoke 绝不可省
# 5. curl --resolve 双边缘校验场景懒块与 /contact 200
```

`apply.py --check <树>` 可核对某棵树当前是否与 overlay 一致（CI/排障用）。

## V1 范围备忘（用户拍板）

只做「角色动 + 场景自洽」：5 角色 + 2 宠物在港湾场景昼夜自洽。
战斗循环（1 BOSS+3 小怪+全自动）、抽卡/经济（券、0.5% VIP-7 天、隐藏保底、
稀有度 UR/SSR/SR/R 首日入模）、雪原/森林/绿洲主题包均为 V2/V3，未启动。
