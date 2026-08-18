package config

import (
	"testing"
)

// envMap 把键对表装成 lookupFunc。
func envMap(pairs map[string]string) lookupFunc {
	return func(name string) (string, bool) {
		v, ok := pairs[name]
		return v, ok
	}
}

// 默认值必须与 backend/app/core/config.py 逐字一致；漂移即违约。
func TestDefaults(t *testing.T) {
	var c Config
	if err := c.load(envMap(nil)); err != nil {
		t.Fatalf("load: %v", err)
	}
	if c.Port != 8000 {
		t.Errorf("Port = %d, want 8000", c.Port)
	}
	pg := c.Postgres
	want := Postgres{
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
	if pg != want {
		t.Errorf("Postgres = %+v, want %+v", pg, want)
	}
}

func TestEnvOverrides(t *testing.T) {
	var c Config
	err := c.load(envMap(map[string]string{
		"MCP_SERVER_PORT":                  "8002",
		"POSTGRES_HOST":                    "project-catalog-postgres",
		"POSTGRES_PORT":                    "5433",
		"POSTGRES_USER":                    "aigc",
		"POSTGRES_PASSWORD":                "s'ecret\\x",
		"POSTGRES_DATABASE":                "aigcnews",
		"POSTGRES_SSLMODE":                 "disable",
		"POSTGRES_POOL_MIN_SIZE":           "1",
		"POSTGRES_POOL_MAX_SIZE":           "4",
		"POSTGRES_POOL_TIMEOUT_SECONDS":    "2.5",
		"POSTGRES_CONNECT_TIMEOUT_SECONDS": "3",
		"POSTGRES_STATEMENT_TIMEOUT_MS":    "9000",
	}))
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if c.Port != 8002 {
		t.Errorf("Port = %d, want 8002", c.Port)
	}
	pg := c.Postgres
	if pg.Host != "project-catalog-postgres" || pg.Port != 5433 ||
		pg.User != "aigc" || pg.Password != `s'ecret\x` ||
		pg.Database != "aigcnews" || pg.SSLMode != "disable" ||
		pg.PoolMinSize != 1 || pg.PoolMaxSize != 4 ||
		pg.PoolTimeoutSeconds != 2.5 || pg.ConnectTimeoutSeconds != 3 ||
		pg.StatementTimeoutMillis != 9000 {
		t.Errorf("Postgres = %+v", pg)
	}
}

func TestInvalidValuesFailFast(t *testing.T) {
	for name, pairs := range map[string]map[string]string{
		"bad port":        {"MCP_SERVER_PORT": "eight thousand"},
		"bad pg port":     {"POSTGRES_PORT": "5432x"},
		"bad pool min":    {"POSTGRES_POOL_MIN_SIZE": "two"},
		"bad pool max":    {"POSTGRES_POOL_MAX_SIZE": "many"},
		"bad pool timout": {"POSTGRES_POOL_TIMEOUT_SECONDS": "soon"},
		"bad connect":     {"POSTGRES_CONNECT_TIMEOUT_SECONDS": "3.5"},
		"bad statement":   {"POSTGRES_STATEMENT_TIMEOUT_MS": "15s"},
		"port range":      {"MCP_SERVER_PORT": "70000"},
		"pg port range":   {"POSTGRES_PORT": "0"},
		"negative min":    {"POSTGRES_POOL_MIN_SIZE": "-1"},
		"zero max":        {"POSTGRES_POOL_MAX_SIZE": "0"},
		"min exceeds max": {"POSTGRES_POOL_MIN_SIZE": "5", "POSTGRES_POOL_MAX_SIZE": "4"},
		"zero timeout":    {"POSTGRES_POOL_TIMEOUT_SECONDS": "0"},
	} {
		var c Config
		if err := c.load(envMap(pairs)); err == nil {
			t.Errorf("%s: 期望报错，实际成功", name)
		}
	}
}
