# PortShelf · 移植游戏目录

Windows 10 / 11 上的 GitHub 开源移植游戏目录。每款游戏显示名称、原作名、Stars、一句简介，以及上游发布的 Windows 下载地址。

## 使用

1. 下载与你的电脑匹配的压缩包：普通 Intel / AMD 电脑选 `windows-x64`，Windows ARM 电脑选 `windows-arm64`。
2. 解压后双击 `PortShelf.exe`，默认浏览器会打开本机的游戏目录。无需安装 Go、Python、Git 或额外运行库。
3. 用 Stars 范围、游戏类型筛选目录，也可选填名称进一步缩小范围；点击「查看下载」查看版本、附件架构和大小，直接打开或复制地址。
4. 点击「刷新资料」从 GitHub 更新 Stars 和正式 Release；网络暂时不可用时仍可浏览上次成功取得的资料。
5. 打开「发现更多」，选择最低 / 最高 Stars，或点选快捷门槛，然后点击「按 Stars 查找」。工具自动查找 GitHub 移植游戏项目，无需输入关键词；可继续加载更多结果，或一键添加当前已加载的游戏。也可使用「添加项目」直接粘贴项目地址。
6. 点击侧栏的「退出工具」结束本地进程。关闭浏览器标签不会结束进程；再次双击会打开已经运行的目录。

界面中的 Stars 与下载链接带有独立的核对时间。程序附带首次打包时实际查询的公开数据快照；缓存不是实时排名。

更新版本时，请先点击旧版侧栏的「退出工具」，再运行新包中的 `PortShelf.exe`。已有目录与缓存会继续保留；只关闭浏览器标签不会退出旧版进程。

## Stars 筛选

- 「我的目录」直接使用最近核对的 Stars 筛选，无需联网；有 Stars 条件时，尚未核对 Stars 的项目不计入结果。
- 「发现更多」默认从 1,000 Stars 起查找，也可选择快捷门槛，或自行填写上下限。留空表示不限，`0` 是有效数值，上下限均包含边界。
- 自动发现按源码移植、重编译、重制等描述与标签查找公开、未归档项目，并排除明显的项目合集、SDK 和模拟器。每批读取 100 个候选，筛选游戏后按 Stars 排序；点击「加载更多」继续追加，跨批重复项目自动合并，不再截断为 24 项。
- [GitHub 搜索 API](https://docs.github.com/en/rest/search/search#about-search) 每次查询最多开放前 1,000 个候选。达到上游限制或返回不完整结果时会提示，可收窄 Stars 范围后继续查找。候选数量不等于实际游戏数量；未匹配描述的项目仍可通过地址添加。
- Stars 反映社区关注数，搜索结果不保证包含 Windows 发布附件。加入目录后可核对实际下载信息。

## 一键添加与中文简介

- 一键添加只保存当前已加载的查找结果，跳过已在目录中的游戏；显示成功、跳过和失败进度，可停止后继续补添。批量添加使用本次 GitHub 查询取得的资料，不会逐个重复查询 GitHub。打开游戏详情时再核对 Release 和下载附件。
- 中文简介由 AIGCNEWS 的项目富化服务提供，已有结果直接读取并缓存；可以展开查看 GitHub 原始简介。未生成中文时保留原文，不把简单规则拼接的文字当作翻译。
- 生成缺失的中文简介需要在设置中填写你自己的 AIGCNEWS MCP Token，可从 [AIGCNEWS MCP 页面](https://aigcnews.cn/mcp) 创建。它与 GitHub Token 分开，只保留在当前进程内存中，退出后清除。
- 可逐项生成，也可补全当前结果的中文简介。生成在服务端排队，使用账户的程序化 API 配额；已有结果和进行中的任务不会重复生成。限流、失败或服务尚未就绪会明确提示，不影响游戏查找和添加。
- 中文结果在本机与服务端缓存；本机有效期为 7 天。游戏列表、原文和已有中文在网络暂不可用时仍可浏览。

## 收录内容

初始目录包含 Ship of Harkinian、Zelda64 Recompiled、OpenRCT2、OpenRA、DevilutionX、CorsixTH、UZDoom、dhewm3 和 OpenMW。项目简介和原作名称由目录整理；Stars、版本及附件来自 GitHub API。

下载链接指向各项目自己的 GitHub Release。部分移植需要自备原版数据或 ROM，详情中的「运行要求」链接到上游说明。没有 Windows 附件时会显示相应状态，并保留项目发布页入口。

## 网络与缓存

- 更新资料需要访问 `api.github.com`；实际下载由浏览器访问 GitHub 的发布文件链接。
- 读取或生成中文简介需要访问 `https://aigcnews.cn/api/v1/projects/descriptions`。请求只提交公开仓库名；AIGCNEWS 在服务端查询公开资料并调用已有富化模型，模型凭据不会进入下载包。
- 程序支持 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量；如需代理，请在启动前设置。浏览器的系统代理设置不会自动传给本地工具。
- GitHub 匿名 API 有请求限额。遇到限流，可稍后重试，或在设置中填写自己的 GitHub Token。只查询公开仓库，无需授予私有仓库写入权限。
- Token 只保存在当前进程内存，退出后清除，不写入缓存或分发文件。
- 缓存默认位于 `%LOCALAPPDATA%\PortShelf\library.json`。可以用 `PortShelf.exe -data-dir D:\PortShelfData` 指定位置。
- 程序仅监听 `127.0.0.1` 的随机端口；本机界面使用每次启动生成的会话凭据。

## 源码构建

需要 Go 1.24 或更新版本；本模块没有外部 Go 依赖。

```sh
cd tools/portshelf
go test -race ./...
go vet ./...
go run . -no-browser
```

中文显示逻辑可另用 `node --test tests/descriptions.test.cjs` 验证；Node 只用于此开发测试，Windows 用户运行工具不需要安装。

在 Linux / macOS 上交叉构建两个 Windows 版本：

```sh
python3 build.py --out /absolute/path/to/portshelf-dist
```

或在 Windows PowerShell 中直接构建本机版本：

```powershell
go test ./...
go build -trimpath -ldflags="-s -w -H=windowsgui" -o PortShelf.exe .
```

打包脚本先运行测试和静态检查，再输出 EXE、ZIP 和 SHA256SUMS。压缩包的 `source/` 目录包含对应版本的完整源码，可以进入该目录直接重新构建。程序通过浏览器提供界面；Linux 上可验证 API 与交互，Windows 原生启动仍需在 Windows 系统上验收。

## 许可

本工具沿用所在仓库的 GNU AGPL v3 许可，完整条款见 `LICENSE`。分发包包含对应源码和第三方许可。

## 第三方来源

布局基于 [Sailboat UI](https://github.com/sailboatui/sailboatui) 的 Sidebar 示例（MIT），图标来自 [Lucide](https://github.com/lucide-icons/lucide)（ISC）。源代码、版本证据和完整许可见 `third_party/`，分发包包含相同声明。项目发现和 UI 素材检索使用 [AIGC Radar · aigcnews.cn](https://aigcnews.cn)。
