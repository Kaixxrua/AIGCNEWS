# X 链路开源剥离方案（2026-08-13 审定）

> 决策背景：主仓计划公开。X 链路按"实现层开源、运营层留私有"拆分；
> 微信链路**永不迁出**（腾讯对公众号采集有胜诉判例，风险不对称）。
> 本文档只放私有仓，不进公共仓。

## 风险重估结论

X 链路的抓取引擎 **twitter-cli 是公开 PyPI 包**
（jackwener/twitter-cli 0.8.5，github.com/jackwener/twitter-cli），
`x_client_transaction` 亦源自公开项目。X 反滥用团队早已能读到这些。
我们的私有代码只是其上 812 行编排/补丁/探测层——公开它的边际暴露
是"用法"，不是反检测核心（凭据池、代理拓扑、部署形态都不在其中）。

## 可公开（实现层）

| 项 | 现状 | 迁出去向 |
| --- | --- | --- |
| `sources/x_transport.py`（812 行） | 私有仓 | 公共仓 `backend/app/services/source_plugins/x_transport.py` |
| X 相关契约测试（存活分类、作者交叉验证、探测中止语义） | 私有仓 `tests/` | 公共仓 `backend/tests/`，适配公共测试矩阵 |
| 依赖声明 `twitter-cli==0.8.5` | pylibs 供给 | 公共仓正常依赖 + constraints 锁定（口径沿用 pylibs README 段） |

`x_transport.py` 内容自查：async 门面、parser 补丁（封面/链接卡）、
translateTweet 增强、janitor 存活探测分类、凭据 fallback 编排、
user_id 缓存、抖动延迟——**无凭据本体、无代理配置、无部署信息**，
符合可公开标准。

## 必须留私有（运营层）

1. **凭据本体**：DB 中的 auth_token/ct0 账号池（是数据，本就不进任何仓）
2. **`deploy/` 全部**：docker-compose.private.yml、nginx inc
   （代理隧道拓扑、sub2api/PriceAI 内部主机名，暴露即泄露内网形态）
3. **pylibs 供给机制**：`pip --target` + PYTHONPATH 注入；迁出后改公共仓
   正常依赖声明，供给机制不再被需要，也不必公开
4. **微信链路全部**：`wechat/`、`wechat_sogou/`、`wechat_facade.py`
   及对应测试——永不开源
5. **`x_client_transaction` vendored 形态**：不单独署名发布；迁出后由
   twitter-cli 公开依赖链自然带入（其本身即公开项目衍生）

## 迁出时公共仓配套改动

1. **README「数据归属与合规」段**：X 实现从"不含在仓内"改为"内置，
   仅供学习研究使用"口径；NOTICE 同步。中英 README 一起改。
2. **`x_source_enabled` 门控语义**：代码在仓内后默认启用；凭据缺失时
   走现有 `XAuthNotConfigured` fail-closed 路径（已满足，无需新代码）。
3. **合规声明**：标注"仅学习使用"——法律效力约等于零，定位为社区
   惯例性态度声明，不作为风险评估依据。

## 发布后若被 X 针对的预案

迁出后 X 若按 repo 收紧（探测/翻译端点失效、queryId 加速轮换）：
应对成本 = 跟随 twitter-cli 上游版本更新即可——生产与公开生态共用
同一客户端，享有"连坐保护"（X 封手法会误伤所有 twitter-cli 用户，
投鼠忌器）。自身独有的探测 features/端点组合被针对时，退回
twitter-cli 默认 fetch_article 路径，探测精度降级但采集主链不断。

## 发布日顺序（与主仓公开联动）

1. 公共仓转 public（宣发文案备妥后，由用户手动执行）
2. MCP registry：`mcp-publisher login github`（用户本人交互 OAuth）
   → `mcp-publisher publish`（server.json 已通过官方 schema 校验，
   CLI v1.8.1 已备妥于 ~/bin）
3. 内容分发：掘金 / 即刻 / V2EX / 知乎 / X / Show HN
4. 观察约 1 周 → 按本方案执行 X 链路迁出，作为第二波话题
   （"我们把 X 采集链也开源了"比一次性全抛多一次传播机会）
5. 微信链路永不迁出，无例外
