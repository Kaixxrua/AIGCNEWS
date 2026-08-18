package postgres

import (
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/config"
)

// conninfo 的引用规则是 libpq 关键字式：单引号包裹，\ 与 ' 反斜杠转义。
// 密码含特殊字符时（生产 .env 即如此）DSN 不得断裂。
func TestConninfoQuoting(t *testing.T) {
	cfg := config.Postgres{
		Host:                  "project-catalog-postgres",
		Port:                  5432,
		User:                  "aigc",
		Password:              `s'ecret\x`,
		Database:              "aigcnews",
		SSLMode:               "disable",
		ConnectTimeoutSeconds: 5,
	}
	dsn := conninfo(cfg)
	for _, want := range []string{
		`host='project-catalog-postgres'`,
		`port=5432`,
		`user='aigc'`,
		`password='s\'ecret\\x'`,
		`dbname='aigcnews'`,
		`sslmode='disable'`,
		`connect_timeout=5`,
		`application_name='aigcnews-mcp-go'`,
	} {
		if !strings.Contains(dsn, want) {
			t.Errorf("conninfo 缺少 %q: %s", want, dsn)
		}
	}
}
