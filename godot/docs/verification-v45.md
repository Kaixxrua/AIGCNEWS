# v45 草甸疏密与接地验证

2026-09-09。本版是持续制作检查点，**不是严格 1:1 复刻完成**。沿用用户最初的晴天大平原参考，仅用于对照，不进入场景或导出包。

## 美术与场景变化

- 使用 imagegen 技能的内置生成流程，四并发选 B，新增不透明短草地表 `assets/materials/short-turf-v45.png`；四张都目视检查。提示词显式包含“八方旅人2”，完整文本和来源见 [生成记录](asset-generation-v45.md)。原 PNG 不改像素，保留生成源，启用引擎 mipmaps。
- 短草底层与旧 clover 浓密叶面按世界疏密场混合。地形 UV2 保存同一个 `growth_density` 的采样值，细草、较大草叶、低矮群落也从该函数取密度。浓绿地表不再与实际长草各自随机；片元间仍是网格插值，不宣称连续函数逐像素精确等同。
- 第一轮网页检查发现短草缩得太细、浓密层削减过多，形成过平空地，保存于 `day-first-too-flat.jpg`，未将其作为最终效果。第二轮放大短草采样尺度、加强浓密区的旧叶面混合，恢复成团的低叶厚度，而不是把全地表重新铺满。最终 68,007 个低草/阔叶形体，v44 为87,633；数量变化本身不是相似度或性能合格的证明。
- 岩沿植被取真实崖顶三角面作为初始位置，再查询实体地形和岩体的最高可见三角面。包含左侧台地和前景崖缘，根部与动画顶点权重为零；草叶末端仍轻摆。没有复制新的树或道具，66个独立图像美术元素不变。
- 首轮物理测试拦截 68 个错位根部（3,072/3,140）。问题来自解析高度与岩沿三角网格插值不同，也有突出的碎岩表面。改为构建时的真实三角网格查询后，再用独立物理射线复核；未放宽 0.055m 的检测阈值，也没有从岩体内部启动建造落点射线。
- 相机、道路中心线、地形高度、Boss 空地、岩体本身和城镇构图未在本轮改变。岩石仍2,020块、883段连续岩面，地形92,619顶点/184,000三角形。动画、昼夜、河水、灯光、焦距默认设置保留。

## 最终构建与回归

完整构建日志前缀 `artifacts/v45/20260909-103958-`。导入、启用断言的源码启动、天气回归、草甸回归、Web导出、独立PCK启动均通过；六份最终日志中无SCRIPT/SHADER/ERROR/WARNING。

```text
MEADOW_READY: 66 unique art assets
MEADOW_GROWTH_AUDIT: 1826 sparse / 21016 dense blades; 168 cap sprays
MEADOW_CAP_ROOT_AUDIT: 3412/3412; max detected surface error 0.00600 m
MEADOW_GROWTH_FIELD_AUDIT: PASS; 92619 vertex samples; error 0.0000000
MEADOW_COLLISION_AUDIT: 31/31; max error 0.0214 m
MEADOW_PLAYSPACE_AUDIT: route slope 12.66 deg; Boss deviation 0.0000 m
MEADOW_BRIDGE_AUDIT: 9/9; max error 0.0122 m
MEADOW_BRIDGE_ENTRY_AUDIT: 24/24; grade 14.98 deg
MEADOW_FRAME_ROOT_AUDIT: 4/4; max error 0.0320 m
MEADOW_COLONY_ROOT_AUDIT: 4/4; max error 0.0172 m
MEADOW_HORIZON_GROUND_AUDIT: 4/4
MEADOW_WEATHER_AUDIT: PASS
```

新增 `tools/audit_meadow_growth.gd` 检查所有地形顶点携带疏密值、可见区域同时存在5094个稀疏及4839个浓密采样、1254px不透明材质、新岩沿草叶根锚点的真实物理支撑。根数必须超过1000，不能凭零根通过。材质采样一致和根部接地并不代表画风一致。日夜测试继续检查时钟、暂停/恢复、中途反向、减少动态效果和灯光端点。

网页控件单元测试 `node --test godot/web/meadow-controls.test.cjs`：6/6通过。本轮未修改HTML/CSS/JS控件，不另声称完成全站可访问性认证。

PCK 67,079,932字节（v44 64,361,824，增加2,718,108）；WASM保持39,514,754字节。增长主要是替换地表材质；没有增加引擎或夜晚第二份场景包。HTML/PCK/WASM/CSS/JS HTTP HEAD均为200，MIME正确。

## 实际浏览器检查

1280×720网页内以完整16:10画幅显示场景，不裁左右参考构图。未使用修改后的截图冒充渲染结果。

- 第二轮白天：`day-web.jpg`；月夜：`night-web.jpg`。点击入夜到达blend=1，点击破晓到达0，时钟连续，无重载归零。夜晚草甸仍可辨路与高差，灯笼有暖色局部亮点；不是网页蒙黑。
- 连续月夜截图 `moving-night-a.jpg` → `moving-night-b.jpg`，时钟114.758→178.250，天空平均每通道差3.148780、地表2.716709（0–255尺度）。这是对实际帧的只读差异，支持“环境确有运动”，不构成风格评分或稳定帧率证明。
- 暂停后时钟198.480保持不变，稳定的两张 `paused-night-*.jpg` 逐像素差为0；暂停时点击破晓仍能完成昼夜转场。恢复时钟到198.671并继续推进。零差仅指本次两张采样，不承诺所有GPU绝对像素一致。
- C开启比例示意、D关闭景深时检查路径、8.4m Boss圈和前景细节，保存 `scale-no-focus-web.jpg`。没有把比例占位体当成正式角色。交付恢复C/G关闭、D开启、白天和环境动画播放。
- 最终网页error/warn为空。短时启动采样59/64/60fps、132个可见draw calls、1,867,467个提交图元，仅是当前机器当前页面采样，不是低端设备保证。

## 尚未完成的参考差异

目标仍为严格1:1复刻，范围不缩小。草甸虽有更清晰的疏密关系，参考中的自然短草、灌丛体量、密度过渡仍非逐处一致；一些中景空隙过宽，岩层仍有平整和排布节奏。村庄、城镇的建筑身份和山脚轮廓、近景围栏与树冠形态也尚非原图一致。下一轮优先处理中景植被体量和岩坡形态，不能仅靠加模糊或更换整景背景遮盖。

日夜切换与动画可用不等于所有物件已有独立骨骼：风车叶片仍烘焙在村庄独立图中；树冠是网格风摆而非逐枝骨骼。自动寻路、挂机战斗、正式人物和Boss逻辑未在本轮实现，保留其空间与尺度条件。

## 保全与实现依据

开始时v44快照148个文件哈希与源码一致。现有Git仍指向E:/盘符级仓库；按using-git-worktrees的隔离检查原则未在那里创建工作树/分支/提交，以版本源码快照保全。没有SSH、恢复源写入或历史钩子执行。v44导出和源快照不覆盖，v45源快照位于 `artifacts/v45/source-final-20260909/`。选中PNG保留版本化源文件，未选候选未进入导出。

三角面落点查询使用Godot [TriangleMesh](https://docs.godotengine.org/en/stable/classes/class_trianglemesh.html) 和 [Mesh.generate_triangle_mesh](https://docs.godotengine.org/en/stable/classes/class_mesh.html)，仅在构建时执行；独立接地复核用 [PhysicsDirectSpaceState3D](https://docs.godotengine.org/en/4.7/classes/class_physicsdirectspacestate3d.html)。这些文档支持实现方式，不作为与参考画风一致的证据。
