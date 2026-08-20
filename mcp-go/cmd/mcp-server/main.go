// mcp-server 是 AIGC Radar MCP 的 Go 实现入口（金丝雀阶段与 Python
// mcp-api 并存，compose 服务 mcp-api-go，127.0.0.1:8002）。
//
// PR 1.1 范围：配置装载、Postgres 连接池、探活/版本端点。
// PR 1.2 范围：/api/mcp 协议面——认证（authn）、解析/信封（wire）、
// 无状态分派（mcpapp），以 backend/tests/parity/corpus/protocol.jsonl
// 为逐字节门禁。
// PR 1.3 范围：Redis 限流层（ratelimit）落在解析之后、分派之前。
// PR 1.4 范围：静态清单（tools/resources/prompts 目录）。
// PR 2.1 范围：get_project_categories 工具（静态分类仓储）。
// PR 2.2 范围：search_papers / search_documents 工具（Postgres 文档检索）。
// PR 2.3 范围：get_paper_detail 工具（Postgres 单文档详情）。
// PR 2.4 范围：get_top_items 工具（Postgres 榜单快照）+ resources/read
// 六路由（dashboard/summary、dashboard/top、projects/categories、
// report/latest、papers/{id}；projects/library 待 PR 2.8 语义检索落地后接线，
// 当前按仓储未装配语义投射 -32603）。
// PR 2.5 范围：search_my_project_favorites 工具（身份感知注册缝 +
// Postgres 收藏检索）。
// PR 2.6 范围：submit_project_adoption 工具（采纳回执写路径；
// 匿名可写，无语料用例，门禁为 Go 单测）。
package main

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"aigcnews/mcp-go/internal/authn"
	"aigcnews/mcp-go/internal/config"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/postgres"
	"aigcnews/mcp-go/internal/probes"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/version"

	goredis "github.com/redis/go-redis/v9"
)

// shutdownGrace 进程退出宽限。Python 侧由 uvicorn 默认值兜底；
// Go 侧显式给出，覆盖在途请求排水。
const shutdownGrace = 10 * time.Second

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))
	slog.SetDefault(logger)
	os.Exit(run())
}

func run() int {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("[Startup] 配置解析失败", "err", err)
		return 2
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pool, err := postgres.NewPool(ctx, cfg.Postgres)
	if err != nil {
		slog.Error("[Startup] Postgres 连接池创建失败", "err", err)
		return 1
	}
	defer pool.Close()
	// 对齐 Python lifespan 的 pool.open()：启动即建连，DB 不可达直接拒启动，
	// 不做"先起来再说"的半就绪服务。
	if err := postgres.Ping(ctx, pool, cfg.Postgres.PoolTimeoutSeconds); err != nil {
		slog.Error("[Startup] Postgres 连通性检查失败", "err", err)
		return 1
	}
	slog.Info("[Startup] Postgres connection pool opened.")

	serverVersion := version.Resolve()
	// 工具注册表（Phase 2 逐只接入）：get_project_categories 走静态仓储
	// （PR 2.1）；search_papers/search_documents 走 Postgres 文档检索
	// （PR 2.2）；get_paper_detail 走 Postgres 单文档（PR 2.3）；
	// get_top_items 走榜单快照（PR 2.4）。publicBaseURL 仅取自
	// PUBLIC_BASE_URL 配置并 rstrip("/")，与 Python
	// presentation.public_base_url 同语义。
	registry := mcpapp.Handlers{}
	categories := mcpapp.NewProjectCategoriesService(mcpapp.StaticProjectCategoriesRepository{})
	registry["get_project_categories"] = categories.Get
	publicBaseURL := strings.TrimRight(cfg.PublicBaseURL, "/")
	for name, handler := range mcpapp.NewDocumentsHandlers(postgres.NewDocumentRepository(pool), publicBaseURL) {
		registry[name] = handler
	}
	papers := mcpapp.NewPaperDetailService(postgres.NewPaperDetailRepository(pool), publicBaseURL)
	registry["get_paper_detail"] = papers.Get
	rankSnapshots := postgres.NewRankSnapshotRepository(pool)
	registry["get_top_items"] = mcpapp.NewGetTopItemsService(rankSnapshots, publicBaseURL).Get
	// 采纳回执写路径（PR 2.6）：匿名可写的普通工具（Python 匿名短路
	// 仅覆盖 favorites），McpToolContext.adoptions 的 Go 对应物。
	registry["submit_project_adoption"] = mcpapp.NewAdoptionsService(
		postgres.NewProjectAdoptionsRepository(pool), publicBaseURL).Submit
	app := mcpapp.New(version.ServerName, serverVersion, registry)
	// 身份感知工具（PR 2.5）：收藏检索需要 UserID + scope 判定，
	// 认证/scope 文案在处理器内产生（对齐 Python dispatcher 短路 +
	// handler 内分支的同文案双检查）。日期锚复用调度时区。
	app.RegisterIdentityTool("search_my_project_favorites",
		mcpapp.NewFavoritesService(
			postgres.NewProjectCollectionsRepository(pool, cfg.SchedulerTimezone),
			publicBaseURL,
		).Get)
	// resources/read 装配（PR 2.4）：榜单快照 + 看板统计 + 简报三个 Postgres
	// 适配器，分类/论文详情复用上方同名服务。projects/library 的语义检索
	// 仓储属 PR 2.8，届时经 SetProjectLibrary 补接。
	app.SetResources(mcpapp.NewResourceService(
		rankSnapshots,
		postgres.NewDocumentStatistics(pool, cfg.SchedulerTimezone),
		postgres.NewBriefingRepository(pool),
		categories,
		papers,
		publicBaseURL,
	))

	// 限流层接线（PR 1.3）。对齐 Python 语义：redis-py 构造不预连，故障
	// 发生在请求期并由 enforce 的 except 吞掉（fail-open）；go-redis 同样
	// 惰性建连，ratelimit 对每个命令错误放行，故这里不做启动 Ping——
	// Redis 晚于本进程拉起时两实现都会自动恢复限流。
	redisClient := goredis.NewClient(&goredis.Options{
		Addr:     net.JoinHostPort(cfg.Redis.Host, strconv.Itoa(cfg.Redis.Port)),
		Password: cfg.Redis.Password, // 空串 = 免认证（对齐 Python password or None）
		DB:       cfg.Redis.DB,
	})
	defer func() { _ = redisClient.Close() }()
	limiter := ratelimit.NewLimiter(ratelimit.GoRedis{Client: redisClient}, cfg.TrustedProxyIPs)
	slog.Info("[Startup] 限流层已接线（Redis 故障时请求级 fail-open）",
		"addr", redisClient.Options().Addr, "db", cfg.Redis.DB)

	mcpHandler := mcpapp.NewHandler(app, authn.Authenticator{DB: authn.PgxQuerier{Pool: pool}}, limiter)
	mux := probes.NewMux(serverVersion, func(ctx context.Context) bool {
		return postgres.Ping(ctx, pool, cfg.Postgres.PoolTimeoutSeconds) == nil
	}, mcpHandler)

	server := &http.Server{
		Addr:              net.JoinHostPort("", strconv.Itoa(cfg.Port)),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	serveErr := make(chan error, 1)
	go func() {
		slog.Info("[Startup] mcp-server listening.", "addr", server.Addr)
		serveErr <- server.ListenAndServe()
	}()

	select {
	case <-ctx.Done():
		slog.Info("[Shutdown] 收到退出信号，开始排水。")
	case err := <-serveErr:
		if !errors.Is(err, http.ErrServerClosed) {
			slog.Error("[Shutdown] HTTP 服务异常退出", "err", err)
			return 1
		}
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownGrace)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		slog.Error("[Shutdown] HTTP 排水失败（强退）", "err", err)
		return 1
	}
	slog.Info("[Shutdown] Postgres connection pool closing.")
	return 0
}
