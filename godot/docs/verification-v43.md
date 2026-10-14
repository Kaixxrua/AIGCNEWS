# v43 对照与验证记录

2026-09-09。本版是持续修改的检查点，**不是严格 1:1 复刻完成**。原晴天草原图继续作为唯一整体构图参考，不进入游戏背景或导出包。

## 已改动

- 左侧第一台地从 `(-42,-32,27,25)` 调整为 `(-42,-44,35,25)`，向后退并加宽。高度加入随边界角度变化的破碎起伏；中央路径及 Boss 区的高度约束不变。
- 岩面固定横槽改成沿共享边界顶点计算的起伏节理、外露坡脚和较高的局部碎裂块体。左右相邻段共用边界公式，层间顶点保持单调，减少固定的水平台阶带。左侧三个岩纹域按各自可见横向跨度展开一次，不再沿整条半椭圆拉长。
- 水面 UV 沿累计河心弧长推进，UV2 保存当地宽度及切线斜率；水纹和扰动法线按当地流向组织。降低细密等频闪点，使用低频变化区分快慢水纹。这是材质运动，不是流体模拟。
- 第一批内置 imagegen 四并发，选 A，替换独立远景村庄：左右两座不同四叶风车与低矮房屋。村庄落点 `(-64.3,-116)`、宽 44 米，图像根锚点约为画幅 `(0.205,0.292)`。旧村庄不再导出，原文件保留。
- 第二批四并发，选 D，新增四块各用一次的独立植被：左侧边缘橡树、坡顶榛树、深叶山楂、花草岩坡。旧 WildHawthorn 和 LimestoneBrambles 实例退出当前场景，原图集的其他区域继续各用一次。总图像元素从 60 增至 62，不是复制四棵树。
- 四块新植被只在根部范围随地形变形，按真实透明空隙确定 UV 边界。分别检查位置在地面网格以内、水面以上，避开道路及 Boss 空地；另对四个根锚点检查实际碰撞支撑。
- 减轻草地的第二次强压暗与高频噪声；减少与底色无关的细草法线强度，仅在细草混合区域相对加强，并随像素实际覆盖范围衰减。远树曝光/对比单独校正。未加大雾、景深、泛光或全场曝光。

两批提示词均显式包含“八方旅人2”，完整提示词、全部候选、选择理由、透明度与原件路径见 [生成记录](asset-generation-v43.md)。内置 imagegen 模式；没有 CLI/API fallback。两张采用 PNG 均未经像素改写，副本哈希与原件一致，导入开启 mipmaps。

## 抓到并修正的失败

- 植被 A/C 的上排没有贯通的透明列，最优列仍分别穿过 78/55 个可见像素，因此未接入。B/D 的四块分隔通过，最终选 D。
- 初次根锚点检查只有 3/4 通过。花草岩坡在原 `(-17.5,-25.19)` 处被实体岩体覆盖：较短射线从岩块内部起射，只报告 0.2568 米差异；邻域检查从更高处向下检测后，发现完整岩顶实际约比高度函数高 1.78 米。将正式检查起点提高到地表上方 8 米，避免在岩体内部起射造成假通过。
- 花草组合移至附近台地顶缘 `(-17.5,-25.99)`，没有放宽 0.075 米支撑容差。最终四个根锚点全部通过，最大差异 0.0320 米。检查的是四个锚点，不声称检测了 PNG 每个可见像素。
- 新只读邻域诊断脚本初次运行有一个变量类型推断错误，已明确 Node3D 类型并重新运行；失败日志保留，不列为成功测试。

## 最终构建

日志前缀 `artifacts/v43/20260909-084057-`。导入、启用断言的源码运行、Web 导出、独立 PCK 启动均通过。上述最终日志没有 SCRIPT/SHADER/ERROR。

```text
MEADOW_TERRAIN: 92619 vertices / 184000 triangles
MEADOW_RIVER_FLOW_AUDIT: 345 paired bank rows; 288.37 m arc length; local heading -70.75 to 49.77 deg
MEADOW_DETAIL_AUDIT: 2020 unique solid rocks; 87633 individual grass/leaf forms
MEADOW_GEOLOGY_AUDIT: 883 continuous stratified rock-face segments
MEADOW_CLIFF_SURFACE_AUDIT: 4 unique atlas regions on 4 solid escarpments
MEADOW_READY: 62 unique art assets
MEADOW_VALLEY_AUDIT: 8 unique colonies above water and clear of the trail
MEADOW_FRAME_GROWTH_AUDIT: 4 unique designs on terrain, clear of trail and Boss clearing
MEADOW_FRAME_ROOT_AUDIT: 4/4 supported root anchors; max error 0.0320 m
MEADOW_COLLISION_AUDIT: 31/31 grounded probes; max height error 0.0214 m
MEADOW_PLAYSPACE_AUDIT: route max slope 12.66 deg; Boss clearing height deviation 0.0000 m
MEADOW_BRIDGE_AUDIT: 9/9 supported deck probes; max height error 0.0122 m
MEADOW_BRIDGE_ENTRY_AUDIT: 24/24 supported entry probes; max error 0.0000 m; grade 14.98 deg
MEADOW_HORIZON_GROUND_AUDIT: 4/4 supported distant terrain probes; solid ground reaches -327 m
```

- 12 个原构图锚点继续通过原容差；这不是美术相似度测试，不替代逐处目测。
- 预览脚本默认 v43，新增河向、四个植被区域及根支撑检查为源码/独立包必需日志。旧版只能以 `-NoBuild -Version v42` 等读取，不把当前源码重新导出覆盖旧版。
- 最终源码细节构建 5.373 秒，独立包 5.344 秒；不包含下载和完整浏览器首访。
- PCK 62,555,396 字节，WASM 39,514,754 字节。相较 v42 PCK 增加 2,684,112 字节，未声称新增美术没有加载成本。
- `git -c core.autocrlf=false diff --no-index --check` 对比 v42 快照 scripts/shaders，没有空白错误输出；退出 1 表示存在内容差异。只读命令未修改 Git 配置。

## Web 实际复核

- 先在 1280×720 宽页比较，再显示到当前任务实际面板。最终面板为 682×710、DPR 1.5、canvas backing 1023×1065；完整 16:10 场景约 682×426，顶部约 y=142。没有为截图换相机或裁掉左右场景。
- D 关闭后检查新村庄和四个新植被的边缘，没有见到棋盘底、白矩形或明显连续白圈。原 PNG 查看器能显示低 alpha 像素中的彩色 RGB，实际游戏 alpha-scissor 后未见同样的彩边；仍需不同尺寸持续复核，不能由透明比例推断所有边缘永远正确。
- C 测试分别看到占位体在中央岔路和右中景路线，远处体量更小，脚底沿路。1.8 米占位体及 8.4 米 Boss 区是比例/地面示意，不是正式人物、寻路或战斗测试。
- G 深度显示中植物和栏杆是不规则轮廓，不是完整矩形卡片；大于 160 米的远端饱和为白，不代表远景建筑具有完整三维内部层次。
- 最后恢复 D 开、C/G 关，v43 显示到当前任务，未关闭旧版本标签。浏览器 error/warn 为空，Web 输出新根支撑 4/4 日志。
- 当前面板启动采样 76/88/26 fps，124 draw calls，2,024,947 submitted primitives。多标签、启动和前后台调度会影响结果，这不是固定硬件基准，不能宣称稳定帧率。

## 与参考仍有明显差距

1. 城堡仍是较稀疏的小塔和规则山体，不符合参考密集城镇、主堡、附塔层层堆叠的体量；山脚和远山轮廓也不一致。应直接针对参考中的独立城堡对象生成候选，而不是继续泛泛生成另一座城堡。
2. 中远景仍有缺少树影、细小岩草和疏密过渡的空白区域；现有独立林丛之间连接偏生硬，左边缘树形和落点也没有完全对上。
3. 左侧岩层的方向改善，但部分岩面仍过于平直、块体重复节奏明显，参考的局部崩落和贴壁植被还没有充分重建。
4. 草地不再叠加那么强的无关凹凸，但高频叶片、花丛与大片草面之间的密度关系仍不像参考；近景颜色与暗影仍需进一步统一。
5. 河流仍缺少参考中更自然的河岸突起、浅水及局部涡流，沿河流向材质不等于真实水流或完成的水面质感。

因此保留“严格 1:1 复刻”为未完成目标，不因构建、碰撞或构图锚点检查通过而宣布完成。

## 保全

本轮开始时 v42 快照对应的 73 个文件与当前源码哈希一致，没有覆盖其他未明改动。修改前快照为 `artifacts/v42/source-final-20260909/`；本版代码、配置、文档及相关导入设置保存到 `artifacts/v43/source-final-20260909/`。新增 PNG 使用新版本名留在工程，生成原件不动。

Git 只读识别仍指向 E:/ 盘符仓库，不是该项目独立仓库；没有在那里建工作树、分支、提交或推送，继续采用版本快照保全。没有访问 SSH、旧 dev_session、推送钩子或修改恢复源。
