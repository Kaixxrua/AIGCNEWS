// mcp-server 是 AIGC Radar MCP 的 Go 实现入口（金丝雀阶段与 Python
// mcp-api 并存，compose 服务 mcp-api-go，127.0.0.1:8002）。
//
// PR 1.1 范围：配置装载、Postgres 连接池、探活/版本端点。
// /api/mcp 协议面自 PR 1.2 起逐层落地（见 backend/tests/parity 语料门禁）。
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
	"syscall"
	"time"

	"aigcnews/mcp-go/internal/config"
	"aigcnews/mcp-go/internal/postgres"
	"aigcnews/mcp-go/internal/probes"
	"aigcnews/mcp-go/internal/version"
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

	mux := probes.NewMux(version.Resolve(), func(ctx context.Context) bool {
		return postgres.Ping(ctx, pool, cfg.Postgres.PoolTimeoutSeconds) == nil
	})

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
