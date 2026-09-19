# 原野资源下载

私有 Godot release 仍先由 `stage_private_frontend.py` 校验完整 manifest 和源码摘要。
前端 build 随后运行 `prepare-scene-delivery.mjs`，只在临时构建目录派生下载适配器、
资源摘要清单和启动计时补丁；不改私有发布目录、场景 PCK、画质、桥接协议或真实 ready 门禁。
未知 bootstrap 摘要拒绝构建，升级私有 release 时须重新审查适配器。

公开 `.wasm`/`.pck` 优先从 `https://scene.aigcnews.cn/camp-scene/` 下载，
URL 携带文件 SHA-256。响应按解压后长度与摘要验证，通过后写入同源 Cache Storage。
再次进入按相同摘要复用；缓存损坏重新下载，禁用存储或配额不足不阻断启动。
CDN 失败、30 秒无数据或摘要不符回退同源，调用方取消不会重试。
API、带 Range 的请求、非 GET 请求和清单外资源不受影响。

联系页打开时只预热共享引擎（省流量模式除外），选择画质后才下载对应包。
素材持续有进展时不再受总计 90 秒误杀，下载停滞和场景初始化分别计时。
CDN 解决传输与回源等待，浏览器缓存解决重复下载；新设备首次资源传输、
WebAssembly 初始化和 GPU 着色器编译仍存在，不承诺首次访问零等待。

CDN 须允许主站来源 CORS，场景文档 CSP 须允许 `connect-src https://scene.aigcnews.cn`。
当前公网边缘已配置这些头。缓存键应保留版本参数，并区分压缩编码。
发布后应对实际版本 URL 预热原画、均衡、极速、引擎和启动包，
而不是只请求不带版本号的旧路径。可用以下命令对已发布且验证通过的构建制品预热：

```sh
node frontend/scripts/warm-scene-cdn.mjs /absolute/path/to/camp-scene/meadow-delivery-manifest.js
```

预热命令验证 CDN 返回的实际字节摘要；任何文件失败均非零退出。
它不修改源站或刷新其他资源。首次 CDN 命中与再次浏览器缓存命中应分别验收。

2026-09-19 本地验证：发布清单中的两种 camp bootstrap、三档核心包与 WASM
均经 CDN 完整读取并通过 SHA-256 校验。浏览器原画传输测试中，首次下载约
204 秒，刷新后 Cache Storage 读取及校验约 0.91 秒，原画包网络请求为零。
这些是下载层数据，不是首帧指标；当前软件 WebGL 环境的原画场景初始化仍出现
长时间阻塞，不能据此宣称原画秒开或所有节点 CDN 传输已达性能目标。
