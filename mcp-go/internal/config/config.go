// Package config 从环境变量装载 mcp-server 的全部配置。
//
// 变量名与默认值逐一对齐 backend/app/core/config.py（pydantic-settings），
// 使 Go 进程与 Python 进程共用同一份 .env/compose 环境，金丝雀期切换零配置漂移。
// 解析失败（非法数字等）与 pydantic 同策略：启动即报错退出，不带病运行。
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Postgres 镜像 backend.app.core.config.Settings 的 postgres_* 字段，
// 默认值与 Python 侧逐字一致（见 config.py 179-189 行）。
type Postgres struct {
	Host                   string
	Port                   int
	User                   string
	Password               string
	Database               string
	SSLMode                string
	PoolMinSize            int
	PoolMaxSize            int
	PoolTimeoutSeconds     float64
	ConnectTimeoutSeconds  int
	StatementTimeoutMillis int
}

// Config 是 mcp-server 的根配置。
type Config struct {
	// Port 为 HTTP 监听端口（容器内恒 8000，compose 映射 127.0.0.1:8002:8000）。
	// Python 侧由 uvicorn --port 旗标给出，Go 侧改由环境变量注入。
	Port     int
	Postgres Postgres
}

// lookup 从环境取值；与 os.LookupEnv 同形，便于测试注入。
type lookupFunc func(string) (string, bool)

func (c *Config) load(lookup lookupFunc) error {
	c.Port = 8000
	c.Postgres = Postgres{
		Host:                   "",
		Port:                   5432,
		User:                   "",
		Password:               "",
		Database:               "",
		SSLMode:                "require",
		PoolMinSize:            2,
		PoolMaxSize:            20,
		PoolTimeoutSeconds:     10.0,
		ConnectTimeoutSeconds:  5,
		StatementTimeoutMillis: 15_000,
	}
	if err := loadInt(lookup, "MCP_SERVER_PORT", &c.Port); err != nil {
		return err
	}
	loadString(lookup, "POSTGRES_HOST", &c.Postgres.Host)
	if err := loadInt(lookup, "POSTGRES_PORT", &c.Postgres.Port); err != nil {
		return err
	}
	loadString(lookup, "POSTGRES_USER", &c.Postgres.User)
	loadString(lookup, "POSTGRES_PASSWORD", &c.Postgres.Password)
	loadString(lookup, "POSTGRES_DATABASE", &c.Postgres.Database)
	loadString(lookup, "POSTGRES_SSLMODE", &c.Postgres.SSLMode)
	if err := loadInt(lookup, "POSTGRES_POOL_MIN_SIZE", &c.Postgres.PoolMinSize); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_POOL_MAX_SIZE", &c.Postgres.PoolMaxSize); err != nil {
		return err
	}
	if err := loadFloat(lookup, "POSTGRES_POOL_TIMEOUT_SECONDS", &c.Postgres.PoolTimeoutSeconds); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_CONNECT_TIMEOUT_SECONDS", &c.Postgres.ConnectTimeoutSeconds); err != nil {
		return err
	}
	if err := loadInt(lookup, "POSTGRES_STATEMENT_TIMEOUT_MS", &c.Postgres.StatementTimeoutMillis); err != nil {
		return err
	}
	if c.Port < 1 || c.Port > 65_535 {
		return fmt.Errorf("config: MCP_SERVER_PORT=%d 超出 1..65535", c.Port)
	}
	if c.Postgres.Port < 1 || c.Postgres.Port > 65_535 {
		return fmt.Errorf("config: POSTGRES_PORT=%d 超出 1..65535", c.Postgres.Port)
	}
	if c.Postgres.PoolMinSize < 0 {
		return fmt.Errorf("config: POSTGRES_POOL_MIN_SIZE=%d 不得为负", c.Postgres.PoolMinSize)
	}
	if c.Postgres.PoolMaxSize < 1 || c.Postgres.PoolMinSize > c.Postgres.PoolMaxSize {
		return fmt.Errorf(
			"config: Postgres 池大小非法 min=%d max=%d",
			c.Postgres.PoolMinSize,
			c.Postgres.PoolMaxSize,
		)
	}
	if c.Postgres.PoolTimeoutSeconds <= 0 || c.Postgres.ConnectTimeoutSeconds <= 0 ||
		c.Postgres.StatementTimeoutMillis <= 0 {
		return fmt.Errorf("config: Postgres 超时配置必须为正值")
	}
	return nil
}

// Load 读取进程环境，返回完整配置；任何变量非法即返回具名错误。
func Load() (Config, error) {
	var c Config
	if err := c.load(os.LookupEnv); err != nil {
		return Config{}, err
	}
	return c, nil
}

func loadString(lookup lookupFunc, name string, dst *string) {
	if v, ok := lookup(name); ok {
		*dst = v
	}
}

func loadInt(lookup lookupFunc, name string, dst *int) error {
	v, ok := lookup(name)
	if !ok || strings.TrimSpace(v) == "" {
		return nil
	}
	n, err := strconv.Atoi(strings.TrimSpace(v))
	if err != nil {
		return fmt.Errorf("config: %s=%q 不是合法整数: %w", name, v, err)
	}
	*dst = n
	return nil
}

func loadFloat(lookup lookupFunc, name string, dst *float64) error {
	v, ok := lookup(name)
	if !ok || strings.TrimSpace(v) == "" {
		return nil
	}
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil {
		return fmt.Errorf("config: %s=%q 不是合法浮点数: %w", name, v, err)
	}
	*dst = f
	return nil
}
