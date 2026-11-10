# PortShelf 游戏资料富化

`/api/v1/projects/descriptions` 保持原有简介读取和生成行为。客户端可用 GET
query `gameDetails=true` 或 POST JSON 布尔字段 `gameDetails: true` 请求游戏资料；
省略或传 false 时，返回原来的字段，不发起游戏资料富化。

```json
{"repo":"owner/repository","gameDetails":true}
```

游戏模式的 `ready` 项目在 `descriptionZh`、`repo`、`status`、`source` 之外返回：

| 字段 | 含义 |
| --- | --- |
| `gameNameZh` | 有足够证据时给出原作的通行简体中文名，否则空串 |
| `gameNameOriginal` | 仓库简介或 README 中明确出现的原作原名，否则空串 |
| `posterUrl` | 从 README 实际图片候选中选择的图片地址，否则空串 |
| `posterSourceUrl` | 图片证据所在的当前仓库 README 页面，否则空串 |
| `posterKind` | `cover` 表示海报/封面，`screenshot` 表示游戏画面；没有图片为空串 |
| `detailsVersion` | 固定为 `1`，表示此版本的资料已尝试核实 |

`detailsVersion=1` 不保证名称和图片都有结果。合集、通用引擎、模拟器、证据不足、
没有适用图片等情况允许留空，客户端应保存版本并明确显示缺失，不能重复自动付费重试。
来源只能是 `aigcnews`。`missing/pending/failed` 的既有中文简介可用于继续展示，但不表示
游戏身份已补全；只有 `ready` 且 `detailsVersion=1` 才算本次富化完成。

已有目录中文简介、旧版独立简介缓存不会阻止游戏资料补全。游戏资料使用
`projects:descriptions:v1:cache:game-v1:<repo>` 与对应 `lock:game-v1:<repo>`，
旧客户端缓存键不变。两种模式共用每用户请求限流、每天/月程序化额度以及全局 4 个
生成槽；同仓库同模式重复请求和命中缓存不会重复计费。工作进程仍受 90 秒超时、
120 秒 lease 和 fencing 保护，缓存 TTL 仍为 7 天。没有数据库 schema 变更，
不会写入公开目录或改动其分类。

输入仅从固定 `https://api.github.com/repos/<repo>` 和它的 README API 读取，
不跟随重定向；仓库必须公开且名称精确匹配。游戏模式即使已有简介也读取 README，
最多接收 64 KiB 解码内容，并将前 12,000 字符交给既有富化模型。相对图片按 API
返回的实际 README 路径及仓库实际 `default_branch` 解析，最多保留 12 个候选。

模型只选择候选 ID，不能提供 URL。图片仅允许 HTTPS 的本仓库
`raw.githubusercontent.com`、`user-images.githubusercontent.com`，或
`github.com/user-attachments/assets/<UUID>`；拒绝端口、凭据、query、fragment、
路径越界、SVG、徽章、logo、小型跟踪图等。不会由服务端请求图片、任意官网或新增
图片搜索服务。候选均来自 README，图片是否确属当前游戏由有约束的模型选择，
无法可靠判断时留空；浏览器应处理上游图片失效的情况。已有图片版权和仓库说明不变。

契约测试：

```bash
PORTSHELF_TEST_REDIS_URL=redis://127.0.0.1:<isolated-test-port>/0 \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_project_descriptions.py backend/tests/test_project_game_details.py
```

Redis 必须是单独创建的测试实例，测试使用随机缓存前缀和随机用户 ID，不能指向生产实例。
