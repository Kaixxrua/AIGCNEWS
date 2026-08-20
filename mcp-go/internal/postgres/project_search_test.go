package postgres

import (
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestNewProjectSearchRepositoryStatementTimeoutCompatibility(t *testing.T) {
	pool := (*pgxpool.Pool)(nil)

	legacy := NewProjectSearchRepository(pool, "")
	if legacy.timezone != "Asia/Shanghai" {
		t.Fatalf("legacy constructor timezone = %q, want Asia/Shanghai", legacy.timezone)
	}
	if legacy.statementTimeoutMillis != 0 {
		t.Fatalf("legacy constructor timeout = %d, want 0", legacy.statementTimeoutMillis)
	}

	configured := NewProjectSearchRepository(pool, "UTC", 9000)
	if configured.timezone != "UTC" {
		t.Fatalf("configured constructor timezone = %q, want UTC", configured.timezone)
	}
	if configured.statementTimeoutMillis != 9000 {
		t.Fatalf("configured constructor timeout = %d, want 9000", configured.statementTimeoutMillis)
	}

	clamped := NewProjectSearchRepository(pool, "UTC", 0)
	if clamped.statementTimeoutMillis != 1 {
		t.Fatalf("non-positive configured timeout = %d, want 1", clamped.statementTimeoutMillis)
	}
}
