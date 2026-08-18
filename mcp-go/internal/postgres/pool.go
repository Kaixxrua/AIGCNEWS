// Package postgres 装配 pgx 连接池，参数语义逐项对齐
// backend/app/core/postgres_database.py 的 create_postgres_pool。
package postgres

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"aigcnews/mcp-go/internal/config"
)

// applicationName 与 Python 侧不同名是有意选择：金丝雀期 pg_stat_activity
// 里要能区分两个实现。该属性不进任何响应字节，不影响线格式契约。
const applicationName = "aigcnews-mcp-go"

// quoteKeyword 按 libpq 关键字式连接串规则引用一个值
// （单引号包裹，反斜杠与单引号反斜杠转义）。
func quoteKeyword(v string) string {
	replacer := strings.NewReplacer(`\`, `\\`, `'`, `\'`)
	return "'" + replacer.Replace(v) + "'"
}

// conninfo 生成与 Python make_conninfo 等价的关键字式 DSN。
func conninfo(cfg config.Postgres) string {
	parts := []string{
		"host=" + quoteKeyword(cfg.Host),
		"port=" + strconv.Itoa(cfg.Port),
		"user=" + quoteKeyword(cfg.User),
		"password=" + quoteKeyword(cfg.Password),
		"dbname=" + quoteKeyword(cfg.Database),
		"sslmode=" + quoteKeyword(cfg.SSLMode),
		"connect_timeout=" + strconv.Itoa(cfg.ConnectTimeoutSeconds),
		"application_name=" + quoteKeyword(applicationName),
	}
	return strings.Join(parts, " ")
}

// NewPool 创建连接池（惰性建连，同 psycopg open=False 语义；
// 启动期连通性由 main 里的 Ping 兜底）。
func NewPool(ctx context.Context, cfg config.Postgres) (*pgxpool.Pool, error) {
	pcfg, err := pgxpool.ParseConfig(conninfo(cfg))
	if err != nil {
		return nil, fmt.Errorf("postgres: DSN 解析失败: %w", err)
	}
	pcfg.MinConns = int32(cfg.PoolMinSize)
	pcfg.MaxConns = int32(cfg.PoolMaxSize)
	// 对齐 Python options=-c statement_timeout=...（毫秒，服务端运行时参数）。
	pcfg.ConnConfig.RuntimeParams["statement_timeout"] = strconv.Itoa(cfg.StatementTimeoutMillis)
	pool, err := pgxpool.NewWithConfig(ctx, pcfg)
	if err != nil {
		return nil, fmt.Errorf("postgres: 连接池创建失败: %w", err)
	}
	return pool, nil
}

// Ping 在池取连超时预算内做一次连通性检查；供启动 fail-fast 与
// /api/ready 的就绪探针复用（Python 侧为 pool 内 SELECT 1，深度等价）。
func Ping(ctx context.Context, pool *pgxpool.Pool, poolTimeoutSeconds float64) error {
	budget := time.Duration(poolTimeoutSeconds * float64(time.Second))
	ctx, cancel := context.WithTimeout(ctx, budget)
	defer cancel()
	return pool.Ping(ctx)
}
