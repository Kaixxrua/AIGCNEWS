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
	"aigcnews/mcp-go/internal/docsemantic"
	"aigcnews/mcp-go/internal/mcpapp"
	"aigcnews/mcp-go/internal/metrics"
	"aigcnews/mcp-go/internal/postgres"
	"aigcnews/mcp-go/internal/probes"
	"aigcnews/mcp-go/internal/projectsearch"
	"aigcnews/mcp-go/internal/ratelimit"
	"aigcnews/mcp-go/internal/uisemantic"
	"aigcnews/mcp-go/internal/version"

	goredis "github.com/redis/go-redis/v9"
)

// shutdownGrace 进程退出宽限。Python 侧由 uvicorn 默认值兜底；
// Go 侧显式给出，覆盖在途请求排水。
const shutdownGrace = 10 * time.Second

// uiSemanticSyncTimeoutSeconds 是后台批量 embedding 单次请求的 HTTP 超时；
// 查询路径仍用 UI_SEMANTIC_TIMEOUT_SECONDS 的短预算。
const uiSemanticSyncTimeoutSeconds = 30.0

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
	uiCatalog, uiIcons, err := mcpapp.LoadUICatalogs()
	if err != nil {
		slog.Error("[Startup] UI catalog validation failed", "err", err)
		return 1
	}
	var uiSemantic mcpapp.UISemanticSearcher
	if cfg.UISemantic.Enabled {
		// UI 语义通道：mcp-go 是该集合的唯一属主。启动后台只为缺少的
		// （条目, 文本指纹）行计算向量，同步完成前或任何失败时单次请求回落
		// 纯关键词，不阻塞启动。
		uiVectors, uiErr := uisemantic.NewMilvusStore(uisemantic.MilvusConfig{
			Host:           cfg.ProjectSearch.MilvusHost,
			Port:           cfg.ProjectSearch.MilvusPort,
			User:           cfg.ProjectSearch.MilvusUser,
			Password:       cfg.ProjectSearch.MilvusPassword,
			DBName:         cfg.ProjectSearch.MilvusDBName,
			CollectionName: cfg.UISemantic.CollectionName,
			Dimension:      cfg.ProjectSearch.MilvusDimension,
			MetricType:     cfg.ProjectSearch.MilvusMetricType,
		})
		if uiErr != nil {
			slog.Error("[Startup] UI 语义通道装配失败", "err", uiErr)
			return 1
		}
		defer func() { _ = uiVectors.Close() }()
		uiDocuments := append(uisemantic.TemplateDocuments(uiCatalog.Items()), uisemantic.IconDocuments(uiIcons.Icons())...)
		uiSemantic = uisemantic.NewRetriever(newEmbeddingClient(cfg.ProjectSearch, cfg.UISemantic.TimeoutSeconds), uiVectors, uisemantic.Config{
			TopK:           cfg.UISemantic.TopK,
			MinScore:       cfg.UISemantic.MinScore,
			TimeoutSeconds: cfg.UISemantic.TimeoutSeconds,
		}, uiDocuments)
		go func() {
			started := time.Now()
			report, syncErr := uisemantic.Sync(ctx, uiDocuments, newEmbeddingClient(cfg.ProjectSearch, uiSemanticSyncTimeoutSeconds), uiVectors, uisemantic.SyncConfig{
				Dimension: cfg.ProjectSearch.MilvusDimension,
			})
			switch {
			case syncErr == nil:
				slog.Info("[Startup] UI 语义向量同步完成", "total", report.Total, "existing", report.Existing, "embedded", report.Embedded, "elapsed", time.Since(started).Round(time.Second))
			case ctx.Err() != nil:
				slog.Info("[Shutdown] UI 语义向量同步随退出中止", "embedded", report.Embedded)
			default:
				slog.Error("[Startup] UI 语义向量同步失败（检索回落关键词，下次启动续传）", "err", syncErr, "embedded", report.Embedded)
			}
		}()
		slog.Info("[Startup] UI 检索已启用关键词 + 语义混合通道", "collection", cfg.UISemantic.CollectionName, "documents", len(uiDocuments))
	}
	for name, handler := range mcpapp.NewUICatalogHandlers(uiCatalog, uiIcons, publicBaseURL, uiSemantic) {
		registry[name] = handler
	}
	documents := postgres.NewDocumentRepository(pool, cfg.SchedulerTimezone)
	if cfg.DocumentSemantic.Enabled {
		// 文档语义通道：复用 ProjectSearch 的 embedding 与 MILVUS_* 连接，只读
		// backend document_semantic_indexer 写入的一文一向量集合；集合缺失或
		// 检索失败时单次请求回落纯关键词，不影响启动。
		docVectors, docErr := docsemantic.NewMilvusDocumentVectors(docsemantic.MilvusConfig{
			Host:           cfg.ProjectSearch.MilvusHost,
			Port:           cfg.ProjectSearch.MilvusPort,
			User:           cfg.ProjectSearch.MilvusUser,
			Password:       cfg.ProjectSearch.MilvusPassword,
			DBName:         cfg.ProjectSearch.MilvusDBName,
			CollectionName: cfg.DocumentSemantic.CollectionName,
			Dimension:      cfg.ProjectSearch.MilvusDimension,
			MetricType:     cfg.ProjectSearch.MilvusMetricType,
		})
		if docErr != nil {
			slog.Error("[Startup] 文档语义通道装配失败", "err", docErr)
			return 1
		}
		defer func() { _ = docVectors.Close() }()
		docEmbedding := newEmbeddingClient(cfg.ProjectSearch, cfg.DocumentSemantic.TimeoutSeconds)
		documents = documents.WithSemantic(docsemantic.NewRetriever(docEmbedding, docVectors, docsemantic.Config{
			TopK:           cfg.DocumentSemantic.TopK,
			MinScore:       cfg.DocumentSemantic.MinScore,
			TimeoutSeconds: cfg.DocumentSemantic.TimeoutSeconds,
		}))
		slog.Info("[Startup] 文档检索已启用关键词 + 语义混合通道", "collection", cfg.DocumentSemantic.CollectionName)
	}
	for name, handler := range mcpapp.NewDocumentsHandlers(documents, publicBaseURL) {
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
	projectCatalog := postgres.NewProjectSearchRepository(pool, cfg.SchedulerTimezone, cfg.Postgres.StatementTimeoutMillis)
	projectFallback := projectsearch.NewGitHubFallback(projectsearch.GitHubFallbackConfig{
		Enabled:        cfg.ProjectSearch.FallbackEnabled,
		UseToken:       cfg.ProjectSearch.FallbackUseToken,
		Token:          cfg.ProjectSearch.GitHubToken,
		TimeoutSeconds: cfg.ProjectSearch.FallbackTimeoutSeconds,
	})
	// 项目向量集合由项目语义检索与收藏语义通道共用（懒连接、带锁）。
	var projectVectors *projectsearch.MilvusVectorRepository
	if cfg.ProjectSearch.SemanticEnabled || cfg.FavoritesSemantic.Enabled {
		milvusRepo, milvusErr := projectsearch.NewMilvusVectorRepository(projectsearch.MilvusConfig{
			Host:                cfg.ProjectSearch.MilvusHost,
			Port:                cfg.ProjectSearch.MilvusPort,
			User:                cfg.ProjectSearch.MilvusUser,
			Password:            cfg.ProjectSearch.MilvusPassword,
			DBName:              cfg.ProjectSearch.MilvusDBName,
			CollectionName:      cfg.ProjectSearch.SemanticCollectionName,
			Dimension:           cfg.ProjectSearch.MilvusDimension,
			IndexType:           cfg.ProjectSearch.MilvusIndexType,
			MetricType:          cfg.ProjectSearch.MilvusMetricType,
			QueryTimeoutSeconds: cfg.ProjectSearch.SemanticQueryTimeoutSeconds,
		})
		if milvusErr != nil {
			slog.Error("[Startup] Milvus 语义检索装配失败", "err", milvusErr)
			return 1
		}
		projectVectors = milvusRepo
		defer func() { _ = projectVectors.Close() }()
	}
	var semanticSearch projectsearch.SemanticSearcher
	if cfg.ProjectSearch.SemanticEnabled {
		embedding := newEmbeddingClient(cfg.ProjectSearch, cfg.ProjectSearch.SemanticQueryTimeoutSeconds)
		semanticSearch = projectsearch.NewProjectSemanticSearch(embedding, projectVectors, projectsearch.SemanticConfig{
			Enabled:             true,
			RepoLimit:           cfg.ProjectSearch.SemanticRepoLimit,
			ChunkLimit:          cfg.ProjectSearch.SemanticChunkLimit,
			MinScore:            cfg.ProjectSearch.SemanticMinScore,
			QueryTimeoutSeconds: cfg.ProjectSearch.SemanticQueryTimeoutSeconds,
		})
	}
	var reranker projectsearch.Reranker
	if cfg.ProjectSearch.RerankerEnabled {
		reranker = projectsearch.NewProjectReranker(projectsearch.RerankerConfig{
			Enabled:           true,
			URL:               cfg.ProjectSearch.RerankerURL,
			ModelName:         cfg.ProjectSearch.RerankerModelName,
			TimeoutSeconds:    cfg.ProjectSearch.RerankerTimeoutSeconds,
			CandidateLimit:    cfg.ProjectSearch.RerankerCandidateLimit,
			MinCandidates:     cfg.ProjectSearch.RerankerMinCandidates,
			SiliconFlowAPIKey: cfg.ProjectSearch.SiliconFlowAPIKey,
		})
	}
	projectEngine, err := projectsearch.NewEngine(projectCatalog, projectFallback, semanticSearch, reranker, projectsearch.EngineConfig{
		Strategy:                    cfg.ProjectSearch.AIStrategy,
		SemanticEnabled:             cfg.ProjectSearch.SemanticEnabled,
		SemanticHeatFirst:           cfg.ProjectSearch.SemanticHeatFirst,
		SemanticQueryTimeoutSeconds: cfg.ProjectSearch.SemanticQueryTimeoutSeconds,
		AdoptionWeight:              cfg.ProjectSearch.AdoptionWeight,
		RerankerEnabled:             cfg.ProjectSearch.RerankerEnabled,
		RerankerCandidateLimit:      cfg.ProjectSearch.RerankerCandidateLimit,
	})
	if err != nil {
		slog.Error("[Startup] 项目检索引擎装配失败", "err", err)
		return 1
	}
	projectSearch := mcpapp.NewProjectSearchService(projectEngine, publicBaseURL)
	registry["search_github_projects"] = projectSearch.Get
	registry["search_github_ai_projects"] = projectSearch.Search
	app := mcpapp.New(version.ServerName, serverVersion, registry)
	// 身份感知工具（PR 2.5）：收藏检索需要 UserID + scope 判定，
	// 认证/scope 文案在处理器内产生（对齐 Python dispatcher 短路 +
	// handler 内分支的同文案双检查）。日期锚复用调度时区。
	collections := postgres.NewProjectCollectionsRepository(pool, cfg.SchedulerTimezone)
	favorites := mcpapp.NewFavoritesService(collections, publicBaseURL)
	if cfg.FavoritesSemantic.Enabled {
		favorites = favorites.WithSemantic(projectsearch.NewFavoritesSemantic(
			collections,
			newEmbeddingClient(cfg.ProjectSearch, cfg.FavoritesSemantic.TimeoutSeconds),
			projectVectors,
			projectsearch.FavoritesSemanticConfig{
				MinScore:       cfg.FavoritesSemantic.MinScore,
				TimeoutSeconds: cfg.FavoritesSemantic.TimeoutSeconds,
				ChunkLimit:     cfg.ProjectSearch.SemanticChunkLimit,
			},
		))
	}
	app.RegisterIdentityTool("search_my_project_favorites", favorites.Get)
	// resources/read 装配（PR 2.4/2.8）：榜单快照 + 看板统计 + 简报
	// 复用 Postgres 适配器，projects/library 与 AI 搜索共用同一服务。
	resources := mcpapp.NewResourceService(
		rankSnapshots,
		postgres.NewDocumentStatistics(pool, cfg.SchedulerTimezone),
		postgres.NewBriefingRepository(pool),
		categories,
		papers,
		publicBaseURL,
	)
	resources.SetProjectLibrary(projectSearch.Search)
	app.SetResources(resources)

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

	// dashboard 工具调用计数写者（PR 0.2 过渡策略：Go 只写 Redis
	// mcpmetrics:*，与 Python 双写收敛）。已知工具名集合对齐 Python
	// MCP_TOOL_REGISTRY：注册表内按原名统计，其余归 __unknown__。
	// bench UA（mcp-latency-bench/）在分派层免计数。
	knownToolNames := make(map[string]struct{}, len(registry)+1)
	for name := range registry {
		knownToolNames[name] = struct{}{}
	}
	knownToolNames["search_my_project_favorites"] = struct{}{}
	app.SetMetrics(metrics.NewRecorder(redisClient), knownToolNames)

	mcpHandler := mcpapp.NewHandler(app, authn.Authenticator{DB: authn.PgxQuerier{Pool: pool}}, limiter)
	mux := probes.NewMuxWithCORS(serverVersion, func(ctx context.Context) bool {
		return postgres.Ping(ctx, pool, cfg.Postgres.PoolTimeoutSeconds) == nil
	}, probes.CORSConfig{
		AllowedOrigins: config.ParseCORSAllowedOrigins(cfg.CORSAllowedOrigins),
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

// newEmbeddingClient 按 EMBEDDING_* 配置构造向量客户端；项目、文档与 UI
// 语义通道共用同一套 provider/模型，仅 HTTP 超时各按自身预算。
func newEmbeddingClient(search config.ProjectSearch, timeoutSeconds float64) *projectsearch.OpenAIEmbeddingClient {
	return projectsearch.NewOpenAIEmbeddingClient(projectsearch.EmbeddingConfig{
		Provider:          search.EmbeddingProvider,
		APIKey:            search.EmbeddingAPIKey,
		BaseURL:           search.EmbeddingBaseURL,
		ModelName:         search.EmbeddingModelName,
		SiliconFlowAPIKey: search.SiliconFlowAPIKey,
		OpenAIAPIKey:      search.OpenAIAPIKey,
		OpenAIBaseURL:     search.OpenAIBaseURL,
		TimeoutSeconds:    timeoutSeconds,
	})
}
