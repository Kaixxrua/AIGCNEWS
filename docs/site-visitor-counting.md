# 站点访客统计

`POST /api/dashboard/visit` 以浏览器 localStorage 中的匿名 ID 按北京时间自然日去重。
只有首次出现且未判为自动化的 ID 才增加 `site_visit_days` 与平台计数；浏览器回访历史
及带来源标记的落地统计也排除自动化访问。机器人仍按日去重，单列在平台 `bot` 桶。
接口的状态码与 `today_visits` / `total_visits` 响应格式保持兼容。

## 2026-11-09 浏览器脚本过滤

当天约 40 分钟样本中，91 次上报有 90 次来自华为云、腾讯云 / Aceville 的 83 个 IP。
两组请求间隔中位数为 60 秒、55 秒，均只访问论文与日报，并使用相同的六种浏览器
标识：Windows 10 / macOS 10.15.7 与 Chrome 148、149、150 的组合。

`automated_visit_sources.py` 同时匹配这六种完整 UA 与已核实的来源网段，
不单凭云厂商或 Chrome 版本判定，也不在线调用 IP 归属服务。增量回放确认同一
指纹还在切换相邻云网段，因此 `automated_visit_networks.json` 包含原样本的 APNIC
分配网段，以及来源 AS132203、AS136907 的 RIPE RIS 路由快照，覆盖地址轮换。
快照标注核查日期、查询地址；按 IPv4 / IPv6 分别合并相邻网段，不扩大边界。
来源登记可核对 [华为云](https://rdap.apnic.net/ip/124.243.189.24)、
[腾讯云](https://rdap.apnic.net/ip/119.28.68.186)、
[Aceville](https://rdap.apnic.net/ip/43.154.137.20)。这是统计过滤，不阻止浏览网站。

路由快照来源：[AS132203](https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS132203)、
[AS136907](https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS136907)。
更新时下载这两个来源，提取 `data.prefixes[].prefix`，与已审核的 APNIC 分配范围
合并；按地址族分别用 `ipaddress.collapse_addresses` 归并，保留来源与核查日期。
通过单元、路由契约和新日志回放验证后随代码发布，不在请求路径自动更新规则。

客户端 IP 只由 `core.client_ip.client_ip_from_request` 解析。不可信直连对端伪造
X-Forwarded-For 不能改变归因。源站 nginx 必须仅信任实际隧道 / Docker 网关，
从边缘 XFF 的尾跳恢复客户端，再覆写发给后端的 XFF；编排网络变动后需核对私有
`nginx-private-server-directives.inc`，不能把旧网关当作访客 IP。

过滤从新请求开始生效。既有日计数没有逐请求来源关联，不能按样本比例扣减或清零。
未知网段、其他浏览器指纹仍沿用原有 UA 识别；发现新的批量行为后须重新核实网段、
请求模式并补充契约测试，不把本规则当作完整的人机验证。
