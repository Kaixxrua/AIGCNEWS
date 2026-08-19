package postgres

import (
	"context"
	"errors"

	"aigcnews/mcp-go/internal/mcpapp"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type PaperDetailRepository struct{ pool *pgxpool.Pool }

func NewPaperDetailRepository(pool *pgxpool.Pool) PaperDetailRepository {
	return PaperDetailRepository{pool: pool}
}

func (r PaperDetailRepository) GetPaperDetail(paperID string) (*mcpapp.DocumentRow, error) {
	const query = `SELECT id, source, source_channel, title, url, summary, published_date, tags, score, raw_score, rank_in_period, local_pdf_path, authors, arxiv_id, created_at FROM documents WHERE id = $1 LIMIT 1`
	values := make([]any, 15)
	pointers := make([]any, len(values))
	for i := range values {
		pointers[i] = &values[i]
	}
	if err := r.pool.QueryRow(context.Background(), query, paperID).Scan(pointers...); errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	} else if err != nil {
		return nil, err
	}

	asString := func(value any) *string {
		if value == nil {
			return nil
		}
		text, ok := value.(string)
		if !ok {
			return nil
		}
		return &text
	}
	asFloat := func(value any) *float64 {
		if value == nil {
			return nil
		}
		f, ok := value.(float64)
		if !ok {
			return nil
		}
		return &f
	}
	asInt32 := func(value any) *int32 {
		if value == nil {
			return nil
		}
		switch n := value.(type) {
		case int32:
			return &n
		case int:
			converted := int32(n)
			return &converted
		case int64:
			converted := int32(n)
			return &converted
		default:
			return nil
		}
	}

	return &mcpapp.DocumentRow{
		ID:            asString(values[0]),
		Source:        asString(values[1]),
		SourceChannel: asString(values[2]),
		Title:         asString(values[3]),
		URL:           asString(values[4]),
		Summary:       asString(values[5]),
		PublishedDate: asString(values[6]),
		Tags:          asString(values[7]),
		Score:         asFloat(values[8]),
		RawScore:      asFloat(values[9]),
		RankInPeriod:  asInt32(values[10]),
		LocalPDFPath:  asString(values[11]),
		Authors:       asString(values[12]),
		ArxivID:       asString(values[13]),
		CreatedAt:     asString(values[14]),
	}, nil
}
