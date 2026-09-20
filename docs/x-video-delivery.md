# X 视频播放与边缘分片缓存

采集保留 `media[].url` 原视频，新增可选 `playback_url`。只从 X 实际返回的
HTTPS `video.twimg.com` MP4 变体选择：优先最长边不超过 1280px、码率不超过
2.5Mbps 的最高码率版本，否则选择最低码率版本。横竖屏同口径，不拼接猜测 URL。
卡片和详情播放器优先使用该字段；没有变体时继续使用原视频。

存量回填入口为 `scripts/backfill_x_video_variants.py`，在后端运行环境执行。
默认只预览最近 48 小时、最多 100 条，`--apply` 才写入；`--hours` 最大 720、
`--limit` 最大 1000。应持有生产部署锁，先将涉及的 `id/media/quote` 备份到仓库外。
脚本只更新媒体 JSON，按原字段值 CAS，遇并发采集修改不覆盖；原视频、封面、
译文不变。授权/限流错误中止，其余网络/服务错误至多重试一次。仪表盘缓存约一分钟过期。

## 国内媒体边缘

`deploy/nginx/x-video-slice.conf` 用于国内节点既有媒体 Nginx server（8488），
依赖已存在的 `aigcmedia` 缓存区及到源站的 18443 SSH 隧道。仅匹配 X MP4 路径，
图片、抽帧、其它媒体保留原配置；源站出站仍使用配置的 Mihomo。

安装到 `/etc/nginx/snippets/aigcnews-x-video-slice.conf`，并在媒体 server 的
通用正则 location 之前 include。先备份既有配置，执行 `nginx -t` 成功后 reload；
失败恢复备份。该主机配置独立于前端静态制品发布，后续重建节点应同步安装本片段。
东京节点已有 CDN 直连路径，不应直接套用此国内回源配置。

每片 1MiB，缓存键为版本、Host、完整 URI/query 和 `$slice_range`，缓存 200/206；
覆盖父级 Range bypass，避免 206 污染整文件缓存。继承缓存区容量预算，合并并发填充，
禁用与 slice 不兼容的后台更新。Range/If-Range 由 Nginx 处理，保留拖动播放和 416；
多段 Range 按 HTTP 允许的方式退为完整 200。

验证：`backend/tests/test_x_video_slice.py` 使用真实 Nginx 和本地模拟源，覆盖
不同分片、跨边界、尾段、完整读取、If-Range、416、query 隔离和重复读取零回源。
线上对同一 MP4 重复请求 Range 应由 MISS 变 HIT，Content-Range 与字节摘要一致。
首次未缓存分片仍依赖源站链路，不能承诺首次播放秒开。
