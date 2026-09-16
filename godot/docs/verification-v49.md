# v49 独立城镇体量、透明度与基脚验证

2026-09-09。继续严格对照用户原晴天大平原参考，**1:1 目标仍未完成**。本轮替换远景城镇并贴合实际地形，不以技术检查代替美术验收。

## 基线与制作

修改前，v48 最终快照 172 个源码文件与工作区逐个哈希一致，场景基线检查通过。重新查看原参考和实际 v48 网页：旧城镇细尖塔多、下部建筑层次不足。使用 imagegen 技能，内置工具两批各四并发，提示词都含“八方旅人2”。

第一批四张 alpha 全为不透明，棋盘格只是图案，全部拒绝。第二批四张真透明，选 C 的厚重主堡与密集小屋；C 透明像素 52.0217%，alpha>0.22 范围内可见红色杂边 0。仅复制选中源到 `assets/backgrounds/castle-town-v49.png`，源图和项目 PNG 的 SHA256 相同，不做脚本修图；未拼接其它候选。完整提示词、源图路径与选择依据见 `asset-generation-v49.md`。

旧城镇文件保留，当前场景和显式 Web 清单换为 v49；未新增重复城镇，图像元素仍为 66 个。新图使用正常 mipmaps 和 alpha-border 导入处理。没有改其它已有 PNG、shader、天气控制、HTML 控件、地形、路线、Boss 区、河道或景深参数。

## 基脚和构图实现

`meadow_city_builder.gd` 使用相机射线将新源最高塔 UV (0.585849,0.002574) 放在原参考的 (0.70,0.06)。深度 -255 米、宽 172 米，基脚锚点 v=0.955；并未移动相机来补偿新图。

构建时读取导入纹理 alpha，沿 129 个均匀列及一个主塔列找最下方 alpha>0.60 实像素，共 128 个有效基脚。对实际 ContinuousMeadow 三角网格投射，在对应支撑面下沉 0.025 米。只有各列基脚上方 0.20 UV 高的过渡带变形，上部塔身不变；最大下部位移 7.084 米，不能把这个数说成接地误差。没有修改 PNG 像素，也不是将平整地面涂在图底。

首次网格的基脚落在相邻行之间，插值后最大支撑差值 0.0587 米，见 `first-source.log`。最终将每个测得的脚底显式加入一行网格，使用 3,380 顶点 / 6,450 三角形；检查阈值从 0.075 收紧至 0.035 米，最终最大误差 0.0250 米。每列顶点严格单调，防止下部折叠；墙体风摆为 0。

独立复查从实际网格顶点/UV 反算每个脚底，再用物理射线查碰撞支撑，不从预设目标高度直接报告通过。主塔构图查询也读取实际网格。此检查覆盖采样列，并非证明每个源图像素都贴地；城镇仍是独立远景美术网格，不是可环绕、内部可行走的完整三维建筑。

## 最终构建

完整构建日志前缀 `artifacts/v49/20260909-124911-`。导入、启用断言的源码启动、天气、草甸、树冠、Web 导出、独立 PCK 启动七阶段通过，七份日志未发现 SCRIPT/SHADER/ERROR/WARNING。

```text
MEADOW_CITY_ROOT_AUDIT: 128/128; max error 0.0250 m; rigid masonry
MEADOW_COMPOSITION_AUDIT: castle_spire (0.700,0.060), original target (0.70,0.06)
MEADOW_COLLISION_AUDIT: 31/31; max error 0.0214 m
MEADOW_PLAYSPACE_AUDIT: route 12.66 deg; Boss deviation 0.0000 m
MEADOW_BRIDGE_AUDIT: 9/9; max error 0.0122 m
MEADOW_BRIDGE_ENTRY_AUDIT: 24/24; grade 14.98 deg
MEADOW_FENCE_AUDIT: 4/4; max error 0.0160 m; screen error 0.00037
MEADOW_HORIZON_GROUND_AUDIT: 4/4
MEADOW_FOREGROUND_ROOT_AUDIT: 2/2; max error 0.0034 m
MEADOW_FRAME_ROOT_AUDIT: 4/4; max error 0.0140 m
MEADOW_COLONY_ROOT_AUDIT: 4/4; max error 0.0195 m
MEADOW_CANOPY_ROOT_AUDIT: 4/4; max error 0.0288 m
MEADOW_CAP_ROOT_AUDIT: 6788/6788; max error 0.00600 m
MEADOW_CREEPING_ROOT_AUDIT: 49360/49360; max error 0.00600 m
MEADOW_GROWTH_FIELD_AUDIT: PASS; 92619 vertices; zero field error
MEADOW_CANOPY_LAYOUT_AUDIT: PASS
MEADOW_WEATHER_AUDIT: PASS
```

新增城镇门槛同时用于源码与 PCK 启动。天气独立检查包含统一时钟、暂停恢复、平滑端点、反向切换、减少动态效果、固定根部和仅在端点刷新反射。网页控件单元测试 6/6 通过。只读 alpha 负样本检查对已知假棋盘格返回失败，不把脚本执行成功当作资产通过。

PCK 65,020,148 字节，比 v48 增加 13,524；WASM 保持 39,514,754。HTML/PCK/WASM/CSS/JS 均 HTTP 200，类型分别正确。完成后默认预览改为 v49，并用 `-NoBuild` 验证，不重新导出覆盖旧版。

## 实际网页检查

仅使用原有同一浏览器标签，未并行运行多个版本。页面 1280×720，canvas 1920×1080，保留完整 16:10 画幅。所有截图直接保存工具输出，不改像素。

- `moving-day-a.jpg`：白天，时钟 39.733；主堡与底部建筑已替换，未见棋盘格和明显白边。轮廓更厚重，但小建筑密度、外围林石/山脚与参考仍不同。
- `night-web.jpg`：点击入夜后 blend=1、时钟 64.320，未重载场景。新城镇转为月夜冷色，灯笼有局部暖光，地面/河流仍可读。
- 暂停后时钟固定 80.433；夜晚两组采样和暂停中切回白天再入夜，时钟均不变。两组 JPEG 比较仍有微小差异：地面平均每通道 0.006785/255，224/691200 像素超过 RGB 和差 6.1；天空与控件没有超阈值像素。原图/日志保留于 `paused-night-*`、`paused-settled-*`。原因未确认，**不声称逐像素完全冻结**。检查确认实际使用的环境 shader 不读引擎 TIME，而共享暂停时钟；本轮没有为截图一致性改渲染参数。
- `scale-no-focus-web.jpg`：暂停中白天，C 开人物占位体/8.4 米 Boss 标线，D 关闭景深查看原始资产轮廓。中央路线与战斗空地保留；C 是比例测试，不是正式人物、寻路或战斗。
- 另取白天暂停 `paused-day-a.jpg` / `paused-day-b.jpg`，天空、地面、控件区逐像素差全部为 0，仅代表这次白天采样，不覆盖上述夜晚微小差异。交付恢复播放环境、白天、景深开启、C/G 辅助关闭；`day-web.jpg` 时钟继续走到 128.609，没有重置。
- 本轮浏览器 error/warn 查询为空。三次短采样 **58/64/45 FPS**，132 visible draw calls，2,460,194 reported visible primitives，比 v48 多 6,448，与城镇网格替换差量相符。这不是稳定 60 FPS 或长期性能结论。

## 保留范围与后续

using-git-worktrees 技能检查仍发现 Git 根在 E:/，不是工程专用仓库；未在该根目录执行分支、worktree、提交或推送。只在明确本地工程开发，不连接 SSH，不写恢复源，不运行历史 dev_session/钩子。v48 导出和源码快照未改，v49 的最终源码快照在 `artifacts/v49/source-final-20260909/`，179 个文件逐个核验哈希；快照排除 PNG 二进制和 .godot 缓存，版本化 PNG 留在项目资产目录。

原参考的建筑群尺度层次、左侧村庄、山脚、碎坡、土草过渡、河谷纵深、整体光色仍有差异，需要继续独立资产和真实地形打磨。新城镇不是 1:1 完成的证明，构图点对齐也不是美术相似度评分。动态风车、正式角色、自动寻路、怪物与 Boss 系统尚未制作。目标保持 active。
