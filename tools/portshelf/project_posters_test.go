package main

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestProjectPosterAutomaticDownloadWithoutSingleOriginalGame(t *testing.T) {
	for _, scenario := range []struct {
		name       string
		status     int
		cooldown   int
		hasImage   bool
		wantSearch bool
	}{
		{name: "official_project_screenshot", status: http.StatusOK, wantSearch: true},
		{name: "poster_service_failure", status: http.StatusServiceUnavailable, wantSearch: true},
		{name: "cooling_project", cooldown: 300},
		{name: "healthy_project", hasImage: true},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			app, downloads, content := prepareTransferApp(t)
			item := Description{
				Repo: "OpenRA/OpenRA", Status: "ready", Source: "aigcnews", DetailsVersion: 1,
				DescriptionZh: "OpenRA 是一个支持多款经典即时战略游戏的开源引擎。",
				PosterStatus:  "missing", PosterSearchVersion: 1, PosterRetryAfter: scenario.cooldown,
				CheckedAt: time.Now().UTC().Format(time.RFC3339),
			}
			complete := item
			complete.PosterURL = "https://aigcnews.cn/api/media/site/game-posters/" + strings.Repeat("d", 64) + ".jpg"
			complete.PosterSourceURL, complete.PosterKind = "https://www.openra.net/media/", "screenshot"
			complete.PosterStatus, complete.PosterRetryAfter = "ready", 60
			if scenario.hasImage {
				item = complete
			}
			if err := app.lib.saveDescriptions([]Description{item}); err != nil {
				t.Fatal(err)
			}
			app.aigc.setToken("project-poster-test-token")
			var posts atomic.Int32
			app.aigc.client.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				if r.Method == http.MethodGet {
					return apiResponse(200, jsonString(DescriptionsResponse{Items: []Description{item}})), nil
				}
				posts.Add(1)
				var body map[string]any
				if json.NewDecoder(r.Body).Decode(&body) != nil || len(body) != 2 || body["repo"] != item.Repo || body["gameDetails"] != true {
					t.Error("automatic project artwork must use ordinary enrichment without an invented game name or forced refresh")
				}
				return apiResponse(scenario.status, jsonString(DescriptionsResponse{Items: []Description{complete}})), nil
			})
			release := Release{Tag: "test-release", URL: "https://github.com/OpenRA/OpenRA/releases/tag/test-release", Assets: []Asset{
				{ID: 123, Name: "OpenRA-windows-x64.zip", Size: int64(len(content)), URL: "https://github.com/OpenRA/OpenRA/releases/download/test-release/OpenRA-windows-x64.zip"},
			}}
			// Automation is disabled in this fixture, so the background worker cannot race this deterministic automatic attempt.
			ids, _, err := app.transfers.enqueueAutomatic(item.Repo, AutomationConfig{Arch: "amd64", Enrich: true}, release)
			if err != nil || len(ids) != 1 {
				t.Fatal("enqueue automatic project", err)
			}
			before, _ := app.transfers.job(ids[0])
			if !readyTransferDetails(before) || before.GameNameZh != "" || before.GameNameOriginal != "" {
				t.Fatal("fixture must start from already enriched multi-game project metadata")
			}
			if err := app.transfers.beginAutomaticAttempt(ids[0]); err != nil {
				t.Fatal(err)
			}
			if err := app.transfers.run(context.Background(), ids[0]); err != nil {
				t.Fatal(err)
			}
			app.transfers.planAutomaticRetry(ids[0])
			job, _ := app.transfers.job(ids[0])
			if (posts.Load() == 1) != scenario.wantSearch || posts.Load() > 1 || downloads.Load() != 1 {
				t.Fatalf("poster search/download count: searches=%d downloads=%d", posts.Load(), downloads.Load())
			}
			if !job.Automatic || job.Status != "done" || job.NextRetryAt != "" || job.Description != item.DescriptionZh || job.GameNameZh != "" || job.GameNameOriginal != "" || !readyTransferDetails(job) {
				t.Fatal("project poster flow changed the verified identity, lost text, or retried completed file transfers")
			}
			wantImage := scenario.hasImage || scenario.status == http.StatusOK
			if (job.PosterURL == complete.PosterURL) != wantImage {
				t.Fatal("official project screenshot was not applied as expected")
			}
			if wantImage {
				if job.PosterKind != "screenshot" || job.PosterSourceURL != complete.PosterSourceURL || len(job.Warnings) != 0 {
					t.Fatal("project screenshot attribution or completion status was lost")
				}
			} else if len(job.Warnings) != 1 || !strings.Contains(job.Warnings[0], "海报") {
				t.Fatal("an incomplete project poster should be explicit while the download stays complete")
			}
		})
	}
}
