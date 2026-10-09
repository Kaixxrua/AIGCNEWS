package postgres

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type UIVisibilityRepository struct{ pool *pgxpool.Pool }

func NewUIVisibilityRepository(pool *pgxpool.Pool) UIVisibilityRepository {
	return UIVisibilityRepository{pool: pool}
}

// Read on every call: moderation must take effect without rebuilding the catalog
// or waiting for the semantic index to catch up. Database failures fail closed.
func (r UIVisibilityRepository) DeprecatedIDs() (map[string]bool, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	rows, err := r.pool.Query(ctx, "SELECT material_id FROM ui_material_visibility WHERE deprecated")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	ids := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids[id] = true
	}
	return ids, rows.Err()
}
