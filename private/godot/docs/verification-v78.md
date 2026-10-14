# v78 — 有方向的日光/月光与建筑补光

状态：第一轮实现的有界CPU、实际WebGL和2K日夜检查已完成；侧光层次有小幅进展，但整体干草与远景仍偏灰，尚不是画风通过结论。

植物基线 v77 已冻结：PCK `B67C63D16B5F1DD40344F7A391830234E28937E524180F3ED1A1342F55C0EB14`；`artifacts/v77/source-final-20260910/` 共547文件逐个SHA核对。最终 `day-final-2k.png` / `night-final-2k.png` 已按 original 查看完整画幅，实际PNG及canvas均2560×1440，DPR约1，暂停clock0，昼夜端点0/1，无控制台错误/警告；普通加载16.4秒，仅是本机已有缓存/上下文的记录。天空飞龙初始路线随机，跨加载不把它当成同姿态静态对照。

## 范围

- 只调天气控制器既有灯组：白天方向(-34,72,0)、能量1.90、RGB(1,.92,.80)，ambient .22、日间天空补光 .18；夜间主光1.20、RGB(.65,.79,1)，月间天空补光 .32，ambient仍 .32。
- 四个建筑材质按同一可反向昼夜blend绝对赋值painted_fill .18/.26；窗灯/光晕保持，城镇独立夜补光仍 .70。两个风车转子旧值为 .60，需看它们是否过暗或与建筑脱节。
- 不改AgX、曝光2.0/2.2、对比、饱和度、雾、SSAO、阴影预算、景深、相机、几何、PNG或动画路线。
- 水材质/透明度/流速/共享动画与反射设置不改；实际光源改变自然会影响河床与反射，视觉上仍须保留透明和克制水色。

静态缓存继续用 v77、签名 `a697804e3160757ebf23f638fa2b7bfb7dd2b7c5d08145b0ec8d6d17089efc7e`。天气和GPU探针不在几何签名内；导出v78前仍须逐包缓存预检，不以版本号变化强制重烘焙。v77包不覆盖。

## 已取得的运行证据（2026-09-10）

- 原构建命令40558实际exit 0。`20260910-131654-*` 材料流程10阶段完成，另有weather / atmosphere / architecture三项直接CPU检查通过；lighting包含在10阶段内，不重复计数。独立检查14份日志无error/warning。不是完整35阶段或长时生物路径复验。
- PCK SHA-256 `6ef91563c419a1ba56ecb4ac10fb8a146e8ccd6f3829d152d05435429346ecb1`，118,842,164字节，gzip 114,063,895字节；比v77分别增加208/306字节。现有Node控制单测7/7通过，服务测试本轮未重跑。
- 普通Web页 `http://127.0.0.1:4231/v78/index.html` 的 `day-first-2k.png` / `night-first-2k.png` 均实际PNG2560×1440，canvas2560×1440、DPR约1、完整16:10画幅及两侧留黑、clock0暂停、blend0/1。主代理以original查看并对照v77最终双图与原参考。控制台无warn/error。本机此次就绪18,250ms、下载1,743ms、场景构建2,598ms；不是冷缓存或公网速度承诺。
- 另一个独立诊断页开启 `render_audit=1&canopy_audit=1&architecture_audit=1`，于05:35:33–44 UTC实际记录：`MEADOW_CANOPY_RESPONSE_AUDIT: PASS`、`MEADOW_ARCHITECTURE_RESPONSE_AUDIT: PASS`、`MEADOW_RENDER_RESPONSE_AUDIT: PASS`、`MEADOW_LEAF_TRANSFER_RESPONSE_AUDIT: PASS`、`MEADOW_FOLIAGE_NO_INCIDENT_LIGHT_AUDIT: PASS`；无warn/error。原灰阶容差仍2/255、主动错误补偿canary保留；叶/木/高光/黑场门槛不降低。旧大幅toe改善假设仍是DIAGNOSTIC_ONLY，不冒充有效性通过。诊断页已关闭，普通截图不取自被探针改动的页面。
- 水/景深相关12文件与v77冻结源逐SHA相同，详见 `artifacts/v78/regression-review.md`。这是源保护，不单独证明观感；实际两幅水面仍能辨河床石与克制的蓝灰透明层。
- 普通页恢复动画后时钟由0推进至73.616，再暂停保持73.616；`night-motion-check-2k.png` 与clock0夜图相比可见云群移动、飞龙在高空换位、月鹿换位/姿态、水纹变化。主代理original查看。暂停时点击破晓，DOM先记录blend .997 / transitioning true，再到0 / false，运动时钟仍73.616。此为有界动态和过渡检查，不代替长时所有随机路径验证。

## 视觉结论与后续

主代理的当前结论：v78侧向阴影比v77明确，日夜道路/灯光仍可读；但干草大面积灰蒙、远景预绘明暗与现场受光的衔接仍不足，不把小幅亮度变化称作去灰完成。固定四区独立对照另见 `artifacts/v78/visual-colour-targets.md`。下一步单独隔离干草密度染色的贡献，不靠全屏加饱和、黑位或模糊；实验另导出v79，不覆盖本v78包。

## 持续保护项

- 四项lighting/weather/atmosphere/architecture直接回归覆盖新端点、四材质过渡/反向/返回白天，原预算/空间/水/窗灯/动画契约保留。
- 材料流程中的GPU `check-only` 仅是解析；本轮上述单独WebGL执行才是实际像素证据。
- 同倍率原生PNG昼夜对照，重点看草/岩/路的材质与受光分离、右树暗部、夜间道路与灯池，以及水下石可读性。不以全图平均更亮或饱和度更高替代美术判断。

此文随实际结果补充。总体目标仍未完成，不将植物局部通过或参数断言通过等同于整场景达到参考质感。
