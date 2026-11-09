# PortShelf · 移植游戏目录

Windows 10 / 11 上的 GitHub 开源移植游戏目录。每款游戏显示名称、原作名、Stars、一句简介，以及上游发布的 Windows 下载地址。

## 使用

1. 下载与你的电脑匹配的压缩包：普通 Intel / AMD 电脑选 `windows-x64`，Windows ARM 电脑选 `windows-arm64`。
2. 解压后双击 `PortShelf.exe`，默认浏览器会打开本机的游戏目录。无需安装 Go、Python、Git 或额外运行库。
3. 搜索游戏名称，点击「查看下载」查看版本、附件架构和大小。可直接打开下载链接，或复制地址。
4. 点击「刷新资料」从 GitHub 更新 Stars 和正式 Release；网络暂时不可用时仍可浏览上次成功取得的资料。
5. 使用「添加项目」输入 `owner/repo` 或 GitHub 项目地址，也可通过 GitHub 搜索发现更多项目。
6. 点击侧栏的「退出工具」结束本地进程。关闭浏览器标签不会结束进程；再次双击会打开已经运行的目录。

界面中的 Stars 与下载链接带有独立的核对时间。程序附带首次打包时实际查询的公开数据快照；缓存不是实时排名。

## 收录内容

初始目录包含 Ship of Harkinian、Zelda64 Recompiled、OpenRCT2、OpenRA、DevilutionX、CorsixTH、UZDoom、dhewm3 和 OpenMW。项目简介和原作名称由目录整理；Stars、版本及附件来自 GitHub API。

下载链接指向各项目自己的 GitHub Release。部分移植需要自备原版数据或 ROM，详情中的「运行要求」链接到上游说明。没有 Windows 附件时会显示相应状态，并保留项目发布页入口。

## 网络与缓存

- 更新资料需要访问 `api.github.com`；实际下载由浏览器访问 GitHub 的发布文件链接。
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
