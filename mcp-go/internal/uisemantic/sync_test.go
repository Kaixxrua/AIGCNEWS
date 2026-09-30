package uisemantic

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strings"
	"testing"
	"time"
)

type fakeStore struct {
	rows        map[string]Row
	lookups     [][]string
	upserts     [][]Row
	flushes     int
	existingErr error
}

func newFakeStore() *fakeStore { return &fakeStore{rows: map[string]Row{}} }

func (s *fakeStore) Existing(_ context.Context, ids []string) (map[string]bool, error) {
	s.lookups = append(s.lookups, append([]string(nil), ids...))
	if s.existingErr != nil {
		return nil, s.existingErr
	}
	found := map[string]bool{}
	for _, id := range ids {
		if _, ok := s.rows[id]; ok {
			found[id] = true
		}
	}
	return found, nil
}

func (s *fakeStore) Upsert(_ context.Context, rows []Row) error {
	s.upserts = append(s.upserts, rows)
	for _, row := range rows {
		s.rows[row.VectorID] = row
	}
	return nil
}

func (s *fakeStore) Flush(context.Context) error { s.flushes++; return nil }

type fakeBatchEmbedder struct {
	calls    [][]string
	failures int // 前 failures 次调用返回错误
	vector   func(text string) []float64
}

func (e *fakeBatchEmbedder) EmbedTexts(_ context.Context, texts []string) ([][]float64, error) {
	e.calls = append(e.calls, append([]string(nil), texts...))
	if e.failures > 0 {
		e.failures--
		return nil, errors.New("HTTP 429")
	}
	vectors := make([][]float64, len(texts))
	for i, text := range texts {
		if e.vector != nil {
			vectors[i] = e.vector(text)
		} else {
			vectors[i] = []float64{float64(len(text)), 1}
		}
	}
	return vectors, nil
}

func testDocuments(n int) []Document {
	documents := make([]Document, n)
	for i := range documents {
		documents[i] = newDocument(fmt.Sprintf("item-%02d", i), KindIcon, fmt.Sprintf("text %d", i))
	}
	return documents
}

func noWait(int) time.Duration { return 0 }

func TestSyncEmbedsOnlyMissingDocumentsInBatches(t *testing.T) {
	documents := testDocuments(7)
	store := newFakeStore()
	for _, document := range documents[:3] {
		store.rows[document.VectorID()] = Row{VectorID: document.VectorID()}
	}
	embedder := &fakeBatchEmbedder{}
	report, err := Sync(context.Background(), documents, embedder, store, SyncConfig{Dimension: 2, LookupBatch: 5, EmbedBatch: 2, Backoff: noWait})
	if err != nil {
		t.Fatal(err)
	}
	if report != (SyncReport{Total: 7, Existing: 3, Embedded: 4}) {
		t.Fatalf("report %#v", report)
	}
	if len(store.lookups) != 2 || len(store.lookups[0]) != 5 || len(store.lookups[1]) != 2 {
		t.Fatalf("lookups %#v", store.lookups)
	}
	// 第一段 5 条里缺 2 条（一批），第二段 2 条都缺（一批）。
	if len(embedder.calls) != 2 || strings.Join(embedder.calls[0], "|") != "text 3|text 4" || strings.Join(embedder.calls[1], "|") != "text 5|text 6" {
		t.Fatalf("embed calls %#v", embedder.calls)
	}
	row := store.rows[documents[4].VectorID()]
	if row.ItemID != "item-04" || row.Kind != KindIcon || row.Fingerprint != documents[4].Fingerprint || len(row.Embedding) != 2 || row.Embedding[0] != float32(len("text 4")) {
		t.Fatalf("row %#v", row)
	}
	if store.flushes != 1 {
		t.Fatalf("flushes %d", store.flushes)
	}

	again, err := Sync(context.Background(), documents, embedder, store, SyncConfig{Dimension: 2, Backoff: noWait})
	if err != nil || again != (SyncReport{Total: 7, Existing: 7}) || len(embedder.calls) != 2 || store.flushes != 1 {
		t.Fatalf("second sync must be a no-op: %#v err=%v calls=%d flushes=%d", again, err, len(embedder.calls), store.flushes)
	}
}

func TestSyncRetriesTransientEmbeddingFailures(t *testing.T) {
	store := newFakeStore()
	embedder := &fakeBatchEmbedder{failures: 2}
	var waits []int
	report, err := Sync(context.Background(), testDocuments(1), embedder, store, SyncConfig{Dimension: 2, MaxAttempts: 3, Backoff: func(attempt int) time.Duration {
		waits = append(waits, attempt)
		return 0
	}})
	if err != nil || report.Embedded != 1 || len(embedder.calls) != 3 || fmt.Sprint(waits) != "[1 2]" {
		t.Fatalf("report %#v err=%v calls=%d waits=%v", report, err, len(embedder.calls), waits)
	}
}

func TestSyncStopsAfterMaxAttemptsWithoutFlushing(t *testing.T) {
	store := newFakeStore()
	embedder := &fakeBatchEmbedder{failures: 5}
	report, err := Sync(context.Background(), testDocuments(3), embedder, store, SyncConfig{Dimension: 2, MaxAttempts: 2, Backoff: noWait})
	if err == nil || !strings.Contains(err.Error(), "item-00") || report.Embedded != 0 || len(store.upserts) != 0 || store.flushes != 0 {
		t.Fatalf("report %#v err=%v upserts=%d flushes=%d", report, err, len(store.upserts), store.flushes)
	}
}

func TestSyncRejectsBadVectorsAndLookupErrors(t *testing.T) {
	cases := map[string]*fakeBatchEmbedder{
		"dimension":  {vector: func(string) []float64 { return []float64{1, 2, 3} }},
		"non-finite": {vector: func(string) []float64 { return []float64{math.NaN(), 1} }},
	}
	for name, embedder := range cases {
		t.Run(name, func(t *testing.T) {
			store := newFakeStore()
			if _, err := Sync(context.Background(), testDocuments(1), embedder, store, SyncConfig{Dimension: 2, Backoff: noWait}); err == nil || len(store.upserts) != 0 {
				t.Fatalf("expected rejection, err=%v upserts=%d", err, len(store.upserts))
			}
		})
	}
	store := newFakeStore()
	store.existingErr = errors.New("milvus down")
	embedder := &fakeBatchEmbedder{}
	if _, err := Sync(context.Background(), testDocuments(1), embedder, store, SyncConfig{Dimension: 2}); err == nil || len(embedder.calls) != 0 {
		t.Fatalf("lookup failure must abort before embedding: err=%v calls=%d", err, len(embedder.calls))
	}
}

func TestSyncHonoursCancellationDuringBackoff(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	embedder := &fakeBatchEmbedder{failures: 5}
	done := make(chan error, 1)
	go func() {
		_, err := Sync(ctx, testDocuments(1), embedder, newFakeStore(), SyncConfig{Dimension: 2, Backoff: func(int) time.Duration { return time.Hour }})
		done <- err
	}()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("err %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("sync did not stop on cancellation")
	}
}

func TestDefaultBackoffIsExponentialAndCapped(t *testing.T) {
	for attempt, want := range map[int]time.Duration{0: 2 * time.Second, 1: 2 * time.Second, 2: 4 * time.Second, 5: 32 * time.Second, 6: 60 * time.Second, 64: 60 * time.Second} {
		if got := defaultBackoff(attempt); got != want {
			t.Fatalf("attempt %d: got %s want %s", attempt, got, want)
		}
	}
}
