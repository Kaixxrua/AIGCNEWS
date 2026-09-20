package mcpapp

import (
	"encoding/json"
	"testing"
	"time"
)

type visibleRankingsStub struct{}

func (visibleRankingsStub) GetSnapshotDocuments(date, channel, source string, limit int) ([]DocumentRow, error) {
	id := "existing-item"
	return []DocumentRow{{ID: &id, Source: &source}}, nil
}

func (visibleRankingsStub) GetSnapshotDocIDs(date, channel string) (map[string]bool, error) {
	return map[string]bool{}, nil
}

func TestYesterdayRankingsRemainVisibleThroughSourceFinalization(t *testing.T) {
	for _, source := range rankingSources {
		for _, hour := range []int{0, 1, 10, 15, 16, 17, 23} {
			service := NewGetTopItemsService(visibleRankingsStub{}, "")
			service.SetNow(func() time.Time {
				return time.Date(2026, 8, 11, hour, 0, 0, 0, time.FixedZone("CST", 8*3600))
			})
			value, err := service.Get(map[string]any{"source": source, "date": "2026-08-10"})
			if err != nil {
				t.Fatal(err)
			}
			var body map[string]any
			if err := json.Unmarshal([]byte(pythonDumps(value)), &body); err != nil {
				t.Fatal(err)
			}
			closeHour := 17
			if source == "github" || source == "news" || source == "hackernews" || source == "x" {
				closeHour = 1
			}
			if body["is_embargoed"] != false || body["is_finalized"] != (hour >= closeHour) || len(body["items"].([]any)) == 0 {
				t.Fatalf("source=%s hour=%d: %v", source, hour, body)
			}
		}
	}
}
