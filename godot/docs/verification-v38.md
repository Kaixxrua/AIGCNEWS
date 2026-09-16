# v38 实体验证记录

日期：2026-09-09（本机 Asia/Shanghai）。工作区：`E:/Projects/Godot-Octopath2`。

## 改动与迭代

- 对照用户的晴天原野参考，而不是另生成一张整景背景。
- v37 近景贴片原先 unshaded 且不投影；v38 改为接收统一日光和透明轮廓投影，辅以少量绘制补光。主相机 billboard 方向在阴影遍历中保持一致。
- 三个有限岩坡和两侧河岸补实体地质、不同大小的风化碎岩，形体各自生成，不把同一块道具模型重复盖章。实体岩石具备碰撞。
- 第一轮岩层太像规则砌墙，第二轮打散大小、层高、旋转和坡脚碎片；随后重选四并发风化材质，修正世界纹理尺寸、凹凸强度和 mipmaps，清除白色坡底和高频闪点。
- 约 6.2 万个草/叶形体构成连续低矮地被；8 个新图集区域各放一次。Boss 范围只有极低、无碰撞的地被，没有石块或高灌木。路线碰撞高度不变。
- 修正水面过密白纹，保留稀疏水光、流动法线、暗湿岸线，以及一次更新的局部环境反射探针。探针不捕获自身水面、屏幕效果和微小草叶，只影响水面。它不是 SSR，也不是准确的全河平面反射。
- 保留真实深度景深；中景清晰，近景适度柔化。天空、远山和村庄仍是独立层级。前景两棵树重新落位，不再几乎全在画外。
- 增加 SSAO、很轻的泛光、统一对比度与冷暖调整。固定视角使用两个 4096 阴影级联，替代初版四级联，以减少重复提交的大型网格。
- 微小草叶不再单独投影，以消除远处的亚像素条纹；仍接收树岩阴影，保留顶点根部遮蔽与 SSAO。树木、灌木和实体岩块继续投影。
- 窄视口保持 16:10 全构图；不让浏览器面板宽度改变场景裁切。

## 工程与导出检查

本机 Godot 4.7.2 `--headless` 导入、Web Release 导出、独立 PCK 启动检查通过。最终构建日志前缀：`artifacts/v38/20260909-004931-`；另有 `final-source-check.log` 检查源码启动和断言。脚本不仅检查退出码，还检查日志中的 SCRIPT/SHADER/ERROR 与场景审计输出。

实际独立 PCK 输出：

```text
MEADOW_TERRAIN: 86595 vertices / 172000 triangles
MEADOW_DETAIL_AUDIT: 4407 unique solid rocks; 61903 individual grass/leaf forms; build 4054 ms
MEADOW_READY: continuous terrain; 52 unique art assets; D focus, G depth, C scale guide
MEADOW_COLLISION_AUDIT: 31/31 grounded probes; max height error 0.0033 m
MEADOW_PLAYSPACE_AUDIT: route max slope 9.58 deg; Boss clearing height deviation 0.0000 m
```

导出资源仍使用显式清单，新增脚本、着色器和三个选中 PNG 均被打包；旧整景背景和未选候选不进入包。所有历史源码/候选原图仍保留。

## 浏览器检查

使用真实 in-app WebGL 浏览器预览 `http://127.0.0.1:4231/v38/index.html`，多轮截图检查，不以 headless 成功替代 GPU 渲染检查。

- `C`：显示/关闭 1.8 米走路占位体与直径 8.4 米 Boss 标线；占位体经过主路时贴地、与环境透视一致，树与新灌木不挡主路。
- `G`：深度视图近暗远亮；树叶透明区域写入正确的轮廓深度，没有整张矩形卡片挡在背景前。
- `D`：开关景深均实际检查；关闭后能看到草叶和树冠原始细节，不靠模糊掩盖不透明底。
- 1280×800 页面检查：1.8 米占位体在脚本定义的近/远测量点约 43.4/21.6 像素（逻辑视口投影值）；无窗口读数不能作为真实浏览器像素值。
- 最终真实 WebGL 日志没有 error/warn。绘制计数从初版四级联的 191 次 / 4,036,578 primitives，下降到 126 次 / 1,660,726 primitives；这是含阴影遍历的提交计数，不是移除了场景资产。
- 最后一次三点帧率样本为 45 / 29 / 57 fps，当时同时开着另一预览与临时比例测试页；随后关闭代理自己的两个临时比较/测试页，保留用户原 v37 标签和 v38 成果。不能据此宣称稳定 60 fps，需在目标设备和加入角色后重新分析性能。
- 另一个实际 1280×720 页面（canvas backing 1920×1080）已验证左右自动留边、保留 16:10 全构图。760×760 覆盖请求没有作用到隐藏测试页，因此不将其列为已通过的窄屏实测。临时 viewport override 已 reset；窄屏行为由已接入的 keep-aspect 配置控制，仍可在用户真实窄面板复核。
- 最終 PCK 为 55,628,660 字节，WASM 为 39,514,754 字节；几何在启动时生成，源码检查生成用时约 3.7 秒。未压缩 HTTP 的下载大小和首次着色器编译仍影响初次加载，不把本机缓存刷新速度当作公网加载速度。

## 新 PNG 校验

| 文件 | SHA-256 |
| --- | --- |
| `limestone-albedo-v38.png` | `DB1CACFBD45B819DB60A0C989192FC6A295DF56C76395F66F3632584ED51331F` |
| `limestone-weathered-v38.png` | `7081DBDD741B6E7CBDFDF3EABECDBE6B35386890568FF88CC2C32669387F3F06` |
| `living-meadow-v38.png` | `2583C77C076D661BAFDCC4BB8504C1A5A1979994C1D61DFE1EBA02EC68789C2F` |

透明 PNG 只读采样：46.966% 完全透明，8 个图集区域均有透明间隔；alpha>0.22 的纯红杂边计数均为 0。没有对生成 PNG 做像素重写。

## 边界

当前仍是固定相机的模块化 2.5D 环境，并非可任意绕行观察的全 3D 美术；正式角色、自动寻路、怪物、Boss 和战斗系统不在本次实现内。不能将当前画面宣称为参考图的 1:1 完成品，远景细节与自然群落的组织仍可继续迭代。

本次没有 SSH、旧 dev_session 流程、Git 提交/推送或公共部署。v37 导出未覆盖，修改前脚本/配置保存在 `artifacts/v37/source-baseline/`。检测到的 Git 元数据属于 `E:/` 父目录而非恢复项目，没有对该盘符根仓库做状态遍历或修改。

核对的引擎官方依据：[spatial shader](https://docs.godotengine.org/en/4.7/tutorials/shaders/shader_reference/spatial_shader.html)、[Environment](https://docs.godotengine.org/en/4.7/classes/class_environment.html)、[ReflectionProbe](https://docs.godotengine.org/en/4.7/classes/class_reflectionprobe.html)、[多分辨率](https://docs.godotengine.org/en/4.7/tutorials/rendering/multiple_resolutions.html)。
