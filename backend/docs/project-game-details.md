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
| `posterUrl` | README 实际图片候选，或精确同名游戏百科页面的封面地址，否则空串 |
| `posterSourceUrl` | 图片证据所在的当前仓库 README 或已核实的英文维基百科游戏页面，否则空串 |
| `posterKind` | `cover` 表示海报/封面，`screenshot` 表示游戏画面；没有图片为空串 |
| `detailsVersion` | 固定为 `1`，表示此版本的资料已尝试核实 |
| `posterStatus` | `ready` 已有图片、`missing` 未找到匹配图片、`unavailable` 图片来源暂时不可用 |
| `posterRetryAfter` | 再次补海报前的剩余秒数；已有图片或旧版尚未尝试补海报时为 `0` |

`detailsVersion=1` 不保证名称和图片都有结果。合集、通用引擎、模拟器、证据不足、
没有适用图片等情况允许留空，客户端应保存版本并明确显示缺失，不能重复自动付费重试。
来源只能是 `aigcnews`。`missing/pending/failed` 的既有中文简介可用于继续展示。仅补海报
任务的 `pending` 会保留已核实的名称、简介及 `detailsVersion=1`；此时图片尚未完成。

已有 `ready`、`detailsVersion=1`、原名非空但没有图片的缓存，可再次 POST 只补海报，
不再调用模型或扣除生成额度。读取 GET 始终只读缓存，不同步请求外部图片来源。补图
未找到精确匹配时冷却 24 小时；超时或来源异常时冷却 5 分钟。GET/POST 在冷却期返回
原有资料与递减的 `posterRetryAfter`，不会新建任务。没有原名的已完成资料不自动重试
模型。任务中断、超时和进程退出同样保留已核实文字，冷却结束后可仅重试海报。

已有目录中文简介、旧版独立简介缓存不会阻止游戏资料补全。游戏资料使用
`projects:descriptions:v1:cache:game-v1:<repo>` 与对应 `lock:game-v1:<repo>`，
旧客户端缓存键不变。两种模型生成模式共用每用户请求限流、每天/月程序化额度以及全局
4 个生成槽；仅补海报不扣额度，但仍共用 POST 限流、全局槽、同仓库去重和 lease。
同仓库同模式重复请求和命中缓存不会重复计费。工作进程仍受 90 秒超时、
120 秒 lease 和 fencing 保护，缓存 TTL 仍为 7 天。没有数据库 schema 变更，
不会写入公开目录或改动其分类。

输入仅从固定 `https://api.github.com/repos/<repo>` 和它的 README API 读取，
不跟随重定向；仓库必须公开且名称精确匹配。游戏模式即使已有简介也读取 README，
最多接收 64 KiB 解码内容，并将前 12,000 字符交给既有富化模型。相对图片按 API
返回的实际 README 路径及仓库实际 `default_branch` 解析，最多保留 12 个候选。

模型只选择候选 ID，不能提供 URL。README 图片仅允许 HTTPS 的本仓库
`raw.githubusercontent.com`、`user-images.githubusercontent.com`，或
`github.com/user-attachments/assets/<UUID>`；拒绝端口、凭据、query、fragment、
路径越界、SVG、徽章、logo、小型跟踪图等。README 图片是否确属当前游戏由有约束
的模型选择，无法可靠判断或候选无效时不使用。

README 没有选出有效图片且原名已确认时，以原名及可选的精确 ` (video game)` 后缀
查询固定匿名 `https://en.wikipedia.org/w/api.php` PageImages。单次请求不翻页，
超时 8 秒，响应最多 128 KiB；不跟随 HTTP 重定向，不模糊搜索系列、续作或其它年份。
标题只归一化大小写、空白、下划线和弯引号，必须精确匹配；页面必须是非消歧义的主
命名空间文章，并有游戏标题后缀或最多 50 个分类中的 video games 分类证据。
图片 URL 只来自 PageImages 响应，不交给模型生成。仅接受
`https://upload.wikimedia.org/wikipedia/(en|commons)/` 的标准原图或缩略图路径，
限 JPEG/PNG/WebP，拒绝 SVG 及其衍生图、logo、徽章、任意图片主机与越界路径。
API 附加的 `utm_source/utm_campaign/utm_content` 参数经校验后移除，除此之外
不接受 query。来源 URL 必须指向同一条已核实的 `en.wikipedia.org/wiki/` 文章。

不需要新的第三方凭据，不抓取任意官网，也不由服务端下载图片字节。浏览器应处理上游
图片失效的情况。已有图片版权和仓库说明不变。

契约测试：

```bash
PORTSHELF_TEST_REDIS_URL=redis://127.0.0.1:<isolated-test-port>/0 \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_project_descriptions.py backend/tests/test_project_game_details.py \
  backend/tests/test_project_game_posters.py
```

Redis 必须是单独创建的测试实例，测试使用随机缓存前缀和随机用户 ID，不能指向生产实例。
