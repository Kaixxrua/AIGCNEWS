package mcpapp

import (
	"errors"
	"strings"
	"testing"

	"aigcnews/mcp-go/internal/jsonx"
)

type paperDetailStub struct {
	wantID string
	row    *DocumentRow
	err    error
}

func (s paperDetailStub) GetPaperDetail(paperID string) (*DocumentRow, error) {
	if paperID != s.wantID {
		return nil, errors.New("unexpected paper id: " + paperID)
	}
	return s.row, s.err
}

func TestValidatePaperDetailArgs(t *testing.T) {
	cases := []struct {
		name string
		args map[string]any
		want string
	}{
		{"missing", map[string]any{}, "paper_id: Field required"},
		{"number", map[string]any{"paper_id": float64(1)}, "paper_id: Input should be a valid string"},
		{"empty", map[string]any{"paper_id": " \t "}, "paper_id: String should have at least 1 character"},
		{"too-long", map[string]any{"paper_id": strings.Repeat("x", 129)}, "paper_id: String should have at most 128 characters"},
		{"extra", map[string]any{"paper_id": "2608.01234", "extra": true}, "extra: Extra inputs are not permitted"},
		{"field-before-extra", map[string]any{"extra": true}, "paper_id: Field required; extra: Extra inputs are not permitted"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := validatePaperDetailArgs(tc.args)
			inputErr, ok := err.(ToolInputError)
			if !ok || inputErr.Message != tc.want {
				t.Fatalf("validatePaperDetailArgs(%v) = %v, want %q", tc.args, err, tc.want)
			}
		})
	}

	got, err := validatePaperDetailArgs(map[string]any{"paper_id": "  2608.01234  "})
	if err != nil || got != "2608.01234" {
		t.Fatalf("裁剪后的 paper_id = %q, %v", got, err)
	}
}

func TestPaperDetailPublicProjection(t *testing.T) {
	id, source, local, authors, created := "2608.01234", "arxiv", "/srv/papers/2608.01234.pdf", `["Alice", "张三"]`, "2026-08-09 17:03:05"
	score, rawScore := 1.0, 42.5
	rank := int32(1)
	row := &DocumentRow{
		ID: &id, Source: &source, LocalPDFPath: &local, Authors: &authors,
		Score: &score, RawScore: rawScore, RankInPeriod: &rank, CreatedAt: &created,
	}
	service := NewPaperDetailService(paperDetailStub{wantID: id, row: row}, "")
	data, err := service.Get(map[string]any{"paper_id": id})
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	result, ok := data.(jsonx.Object)
	if !ok {
		t.Fatalf("result type = %T, want jsonx.Object", data)
	}
	if got := pythonDumps(result); got != `{"item": {"id": "2608.01234", "source": "arxiv", "source_channel": null, "title": null, "url": null, "summary": null, "published_date": null, "tags": null, "score": 1.0, "raw_score": 42.5, "rank_in_period": 1, "authors": ["Alice", "张三"], "arxiv_id": null, "created_at": "2026-08-09 17:03:05", "pdf_media_url": "/api/media/papers/2608.01234.pdf", "detail_url": "https://aigcnews.cn/papers/2608.01234/read?utm_source=mcp&utm_medium=tool"}, "attribution": "Data provided by AIGC Radar · https://aigcnews.cn"}` {
		t.Errorf("public projection = %s", got)
	}
}

func TestPaperDetailNotFoundMessage(t *testing.T) {
	service := NewPaperDetailService(paperDetailStub{wantID: "2608.99999"}, "")
	_, err := service.Get(map[string]any{"paper_id": "2608.99999"})
	inputErr, ok := err.(ToolInputError)
	if !ok || inputErr.Message != "Document '2608.99999' not found." {
		t.Fatalf("not-found error = %v", err)
	}
}

func TestPythonStringRepr(t *testing.T) {
	cases := map[string]string{
		"plain":  "'plain'",
		"a'b":    `"a'b"`,
		`a"b`:    `'a"b'`,
		`a'"b`:   `'a\'"b'`,
		"a\\b\n": `'a\\b\n'`,
	}
	for in, want := range cases {
		if got := pythonStringRepr(in); got != want {
			t.Errorf("pythonStringRepr(%q) = %q, want %q", in, got, want)
		}
	}
}
