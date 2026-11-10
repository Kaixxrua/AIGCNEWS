# PortShelf 游戏资料富化

`/api/v1/projects/descriptions` 保持原有简介读取和生成行为。客户端可用 GET
query `gameDetails=true` 或 POST JSON 布尔字段 `gameDetails: true` 请求游戏资料；
省略或传 false 时，返回原来的字段，不发起游戏资料富化。

```json
{"repo":"owner/repository","gameDetails":true,"refreshPoster":false}
```

`refreshPoster` 为可选严格布尔值，`true` 必须同时使用 `gameDetails: true`。
它允许已存在图片的项目主动重新联网找海报，仍遵守新版搜索冷却。

游戏模式的 `ready` 项目在 `descriptionZh`、`repo`、`status`、`source` 之外返回：

| 字段 | 含义 |
| --- | --- |
| `gameNameZh` | 有足够证据时给出原作的通行简体中文名，否则空串 |
| `gameNameOriginal` | 仓库简介或 README 中明确出现的原作原名，否则空串 |
| `posterUrl` | 新联网任务返回本站已下载验证的 JPEG 地址；失败可保留旧版有效图片，否则空串 |
| `posterSourceUrl` | 工具实际读取且核实游戏身份的公开 HTTPS 来源页；旧图片仍保留其原来源 |
| `posterKind` | `cover` 表示海报/封面，`screenshot` 表示游戏画面；没有图片为空串 |
| `detailsVersion` | 固定为 `1`，表示此版本的资料已尝试核实 |
| `posterSearchVersion` | `1` 表示已尝试新版联网 Agent；旧资料为 `0` |
| `posterStatus` | 最近一次找图的结果：`ready` 验证成功、`missing` 未找到匹配图片、`unavailable` 来源或搜索暂不可用 |
| `posterRetryAfter` | 再次找图前的剩余秒数；即使保留旧图也需要遵守 |

`detailsVersion=1` 不保证名称和图片都有结果。合集、通用引擎、模拟器、证据不足、
没有适用图片等情况允许留空，客户端应保存版本并明确显示缺失，不能重复自动付费重试。
来源只能是 `aigcnews`。`missing/pending/failed` 的既有中文简介可用于继续展示。仅补海报
任务的 `pending` 会保留已核实的名称、简介及 `detailsVersion=1`；此时图片尚未完成。

已有 `ready`、`detailsVersion=1`、原名非空但没有图片的缓存，可再次 POST 只找海报，
保留已核实简介和名称，不重新生成文字。初次富化即使 README 选出截图，也主动执行联网
Agent 找海报；搜索失败时保留 README 图片。已有图的旧资料只有显式 `refreshPoster: true`
才重新查找。旧 `posterSearchVersion=0` 的缺图项目普通 POST 可首次升级，绕过旧维基百科
冷却；旧版有图的显式刷新也可首次升级。

新版搜索未找到时冷却 1 小时，超时或来源异常时冷却 5 分钟，成功后手动再次搜索冷却
60 秒。`posterSearchVersion=1` 的普通和强制请求均遵守冷却，重复请求不会新建任务。
搜索失败可继续显示旧图，但 `posterStatus` 仍记录此次失败，不能仅因旧图存在改为 `ready`。
没有已确认原名的已完成资料不自动重试模型。任务中断、超时和进程退出保留已核实文字。

已有目录中文简介、旧版独立简介缓存不会阻止游戏资料补全。游戏资料使用
`projects:descriptions:v1:cache:game-v1:<repo>` 与对应 `lock:game-v1:<repo>`，
旧客户端缓存键不变。两种模型生成模式共用每用户请求限流、每天/月程序化额度以及全局
4 个生成槽。新版只找海报也使用既有模型，因此每次实际提交的新任务扣一次既有
`charge_generation` 程序化额度；初次文字加找图任务总共扣一次。缓存、去重和冷却命中
不会重复扣除；取消和来源失败没有自动退还额度。纯维基百科注入仅用于旧契约测试，生产
默认联网 Agent。工作进程仍受 90 秒超时、
120 秒 lease 和 fencing 保护，缓存 TTL 仍为 7 天。没有数据库 schema 变更，
不会写入公开目录或改动其分类。

游戏身份输入从固定 `https://api.github.com/repos/<repo>` 和它的 README API 读取，
不跟随重定向；仓库必须公开且名称精确匹配。游戏模式即使已有简介也读取 README，
最多接收 64 KiB 解码内容，并将前 12,000 字符交给既有富化模型。相对图片按 API
返回的实际 README 路径及仓库实际 `default_branch` 解析，最多保留 12 个候选。

模型只选择候选 ID，不能提供 URL。README 图片仅允许 HTTPS 的本仓库
`raw.githubusercontent.com`、`user-images.githubusercontent.com`，或
`github.com/user-attachments/assets/<UUID>`；拒绝端口、凭据、query、fragment、
路径越界、SVG、徽章、logo、小型跟踪图等。README 图片是否确属当前游戏由有约束
的模型选择，无法可靠判断或候选无效时不使用。

联网 Agent 复用既有富化模型，不依赖 Kimi 或新增搜索凭据。`search_web` 使用已安装的
DDGS（Yahoo 优先、DuckDuckGo 备用；`search_public_web(..., engines=...)` 可注入最多两个
预定义引擎），查询最多 2 次、每次 6 条结果；查询必须含已确认
原名，只给已确认中文名时工具改写为原名加 `cover` 并保留 `site:` 筛选。优先官网、游戏
商店和游戏资料/封面站（例如 Steam、GOG、MobyGames、IGDB、TheCoverProject、Nintendo、
LaunchBox 和 itch.io），没有匹配再扩大来源；任何网站都必须真实读取并验证。
`read_page(resultId)` 最多 4 页，仅接受本任务搜索工具返回的 ID；
`verify_image(candidateId, kind)` 最多 3 图，仅接受已读取页面中的真实候选 ID。
Agent 最多 6 轮模型调用，所有页面及工具内容作为不可信资料，不能执行其中的指令。
模型最终只能选择已下载验证成功的候选 ID，不能生成 URL。

HTML 最多 1 MiB，页面须出现已确认原名或中文名；从主图元数据、游戏结构化数据、
`img` 和有界 lazy/srcset 属性提取候选，过滤装饰图片及 GitHub 通用社交卡。身份
词命中只是必要条件，模型还须核实图片属于相同游戏及版本，拒绝续作、合集、同名电影、
小说和无关图片。图片真正 GET 后检查类型及 Pillow 解码，只接受 JPEG/PNG/WebP，
最多 4 MiB、1600 万像素，最短边至少 160 像素。去除元数据、最长边缩到 1200 后转
JPEG，SHA-256 命名并原子写入 `storage/site/game-posters/`。公开地址固定为
`https://aigcnews.cn/api/media/site/game-posters/<64位小写SHA256>.jpg`，复用现有匿名
site media 挂载。

外部请求仅 HTTPS，无 URL 凭据、端口或 IP 字面量；每跳重新解析并拒绝内网与公私混合
DNS，按现有代理路径使用 `CONNECT_TO` 固定公开 IP 并保留 TLS/Host/SNI 校验。页面与
图片总计单次最多 15 秒、最多 3 次重定向，传输回调限制解压后大小。DDGS 在独立可杀死
子进程中执行，任务取消会结束搜索进程；其它请求和模型调用遵守异步取消，不继续后续工具。
工具实际 query、结果、来源页 hash、图片原地址、图片 hash 和执行状态只存内部
`posterTrace`（Redis），不会经公开响应暴露，也不记录凭据或提供商原始异常。

海报目录每次写入执行 TTL 和容量清理，上限取现有媒体配置与 7 天/128 MiB 的较小值；
只清理此专用子目录，拒绝 symlink/path traversal。海报是可修复缓存，并非永久地址。
GET 只读 Redis/目录资料并检查本站 hash 图片是否仍存在，不联网、不扣额度；文件已淘汰
时返回三个图片字段的显式空串，保留中文文字，普通 POST 可在当前冷却结束后重新找图。
旧客户端应将 `ready` 响应图片字段视为完整记录，不把已清空的失效图片重新合并回来。

契约测试：

```bash
PORTSHELF_TEST_REDIS_URL=redis://127.0.0.1:<isolated-test-port>/0 \
  backend/.venv/bin/python -m pytest -q \
  backend/tests/test_project_descriptions.py backend/tests/test_project_game_details.py \
  backend/tests/test_project_game_posters.py backend/tests/test_project_web_posters.py
```

Redis 必须是单独创建的测试实例，测试使用随机缓存前缀和随机用户 ID，不能指向生产实例。

独立联网验收入口为 `research_game_poster(item, model=..., search=..., fetch=..., cache=...)`，
不依赖 Redis。测试可注入模拟模型/工具；真实验收必须使用临时 `site_assets_storage_dir`，
不写服务缓存。模型未注入时使用现有 `get_chat_model` 与 enrichment reasoning 配置，
需先只读初始化 runtime provider setting reader（无需启动应用 lifespan、迁移或采集）：

```python
from backend.app.core.model_factory import configure_runtime_provider_settings
from backend.app.core.postgres_database import postgres_database
from backend.app.repositories.postgres_runtime_provider_repository import PostgresRuntimeProviderSettingRepository
from backend.app.services.project_catalog.game_poster_agent import research_game_poster

configure_runtime_provider_settings(PostgresRuntimeProviderSettingRepository(postgres_database))
# 在异步验收函数中，使用临时目录覆盖 settings.site_assets_storage_dir 后：
result = await research_game_poster({
    "repo": "owner/repository", "gameNameOriginal": "已经核实的原名",
    "gameNameZh": "已核实中文名", "descriptionZh": "已核实中文简介",
})
# 仅检查 status/trace/临时JPEG，不输出提供商设置或令牌。
```
