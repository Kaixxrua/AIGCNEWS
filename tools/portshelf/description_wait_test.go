package main

import (
	"context"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestTransferDescriptionWaitAccommodatesFourMinuteBackgroundJob(t *testing.T) {
	app, _, _ := prepareTransferApp(t)
	// Inspect the enclosing enrichment deadline independently of the production
	// HTTP client's shorter per-request timeout; no real network is used here.
	app.aigc.client.Timeout = 0
	old := webPosterFixture()
	old.Repo = "OpenRCT2/OpenRCT2"
	old.PosterURL, old.PosterSourceURL, old.PosterKind = "", "", ""
	old.PosterStatus, old.PosterRetryAfter = "missing", 0
	completed := webPosterFixture()
	completed.Repo = old.Repo
	job := TransferJob{ID: randomID(), Repo: old.Repo, Status: "running", Enrich: true, Outputs: map[string]TransferOutput{}}
	app.transfers.mu.Lock()
	app.transfers.jobs = append(app.transfers.jobs, job)
	app.transfers.mu.Unlock()
	app.aigc.setToken("test-description-wait-token")
	gets, posts := 0, 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		deadline, ok := r.Context().Deadline()
		remaining := time.Until(deadline)
		if !ok || remaining < 270*time.Second || remaining > 5*time.Minute {
			t.Errorf("background metadata deadline must include a 240-second job plus margin: %v", remaining)
		}
		item := old
		if r.Method == http.MethodPost {
			posts++
			item.Status = "pending"
		} else {
			gets++
			if gets > 1 {
				item = completed
			}
		}
		return apiResponse(http.StatusOK, jsonString(DescriptionsResponse{Items: []Description{item}, PollAfter: 2})), nil
	})
	if err := app.transfers.enrich(context.Background(), job); err != nil {
		t.Fatal(err)
	}
	after, _ := app.transfers.job(job.ID)
	if posts != 1 || gets != 2 || after.PosterURL != completed.PosterURL || after.Description != completed.DescriptionZh || len(after.Warnings) != 0 {
		t.Fatal("pending background enrichment must complete by GET without a second generation request")
	}
}

func TestPendingPosterRetainsOldImageAcrossRestartAndReadsCompletedImageWithoutPost(t *testing.T) {
	app := descriptionApp(t)
	old := webPosterFixture()
	old.CheckedAt = time.Now().UTC().Format(time.RFC3339)
	if err := app.lib.saveDescriptions([]Description{old}); err != nil {
		t.Fatal(err)
	}
	pending := old
	pending.Status = "pending"
	if err := app.lib.saveDescriptions([]Description{pending}); err != nil {
		t.Fatal(err)
	}
	reloaded, err := newLibrary(app.lib.root)
	if err != nil {
		t.Fatal(err)
	}
	retained := reloaded.snapshot().Descriptions[old.Repo]
	if retained.CheckedAt != "" || retained.PosterURL != old.PosterURL || retained.DescriptionZh != old.DescriptionZh || !readyGameDetails(retained) {
		t.Fatal("restart must retain the old visible image and text plus the stale read marker")
	}
	app.lib = reloaded
	completed := old
	completed.PosterURL = "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("b", 64) + ".jpg"
	read, calls := posterCacheHTTPReader(t, app, http.StatusOK, completed)
	if got := read(); calls.Load() != 1 || got.PosterURL != completed.PosterURL || got.CheckedAt == "" {
		t.Fatal("GET after pending cache restoration must retrieve the new image without generating again")
	}
}

func TestTransferResumesPendingDescriptionWithoutGeneratingAgain(t *testing.T) {
	app, _, _ := prepareTransferApp(t)
	completed := webPosterFixture()
	job := TransferJob{ID: randomID(), Repo: completed.Repo, Status: "running", Enrich: true, Outputs: map[string]TransferOutput{}}
	app.transfers.mu.Lock()
	app.transfers.jobs = append(app.transfers.jobs, job)
	app.transfers.mu.Unlock()
	app.aigc.setToken("test-description-wait-token")
	gets, posts := 0, 0
	app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		item := completed
		if r.Method == http.MethodPost {
			posts++
		} else {
			gets++
		}
		if gets == 1 {
			item.Status = "pending"
		}
		return apiResponse(http.StatusOK, jsonString(DescriptionsResponse{Items: []Description{item}, PollAfter: 2})), nil
	})
	if err := app.transfers.enrich(context.Background(), job); err != nil {
		t.Fatal(err)
	}
	after, _ := app.transfers.job(job.ID)
	if posts != 0 || gets != 2 || after.PosterURL != completed.PosterURL || len(after.Warnings) != 0 {
		t.Fatal("an existing background task must resume by GET only and apply its completed image")
	}
}
