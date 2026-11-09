package main

import (
	"context"
	"reflect"
	"testing"
	"time"
)

func automaticRetryJob() TransferJob {
	return TransferJob{ID: randomID(), Repo: "OpenRCT2/OpenRCT2", Arch: "amd64", Automatic: true, Attempts: 1,
		Providers: []string{"baidu", "quark"}, Status: "partial", Outputs: map[string]TransferOutput{
			"baidu": {Status: "done", Share: CloudShare{URL: "https://pan.baidu.com/s/complete"}},
			"quark": {Status: "failed", Error: "temporary service error"},
		}}
}

func saveAutomaticRetryJobs(t *testing.T, m *transferManager, jobs ...TransferJob) {
	t.Helper()
	m.mu.Lock()
	defer m.mu.Unlock()
	if err := m.saveLocked(jobs); err != nil {
		t.Fatal(err)
	}
}

func TestAutomaticRetryBackoffPersistsAndDoesNotRunEarly(t *testing.T) {
	m := automationTestManager(t).app.transfers
	job := automaticRetryJob()
	m.app.cloud.accounts["quark"] = cloudAccount{drive: &fakeCloudDrive{id: "quark"}, session: "quark-session"}
	saveAutomaticRetryJobs(t, m, job)
	m.planAutomaticRetry(job.ID)
	first, _ := m.job(job.ID)
	due, err := time.Parse(time.RFC3339, first.NextRetryAt)
	if err != nil || due.Before(time.Now().Add(119*time.Second)) || due.After(time.Now().Add(121*time.Second)) || first.NeedsAttention {
		t.Fatalf("unexpected retry policy: %+v %v", first, err)
	}
	config := defaultAutomationConfig()
	config.Enabled = true
	m.maintainAutomatic(config)
	unchanged, _ := m.job(job.ID)
	if unchanged.Status != "partial" || unchanged.NextRetryAt != first.NextRetryAt {
		t.Fatal("retried before backoff deadline")
	}
	restored, err := newTransferManager(m.app)
	if err != nil {
		t.Fatal(err)
	}
	afterRestart, _ := restored.job(job.ID)
	if afterRestart.NextRetryAt != first.NextRetryAt || afterRestart.Attempts != 1 {
		t.Fatal("restart forgot retry deadline/attempts")
	}
	if err := restored.modify(job.ID, func(j *TransferJob) { j.NextRetryAt = time.Now().Add(-time.Second).UTC().Format(time.RFC3339) }, true); err != nil {
		t.Fatal(err)
	}
	restored.maintainAutomatic(config)
	queued, _ := restored.job(job.ID)
	if queued.Status != "queued" || queued.NextRetryAt != "" || !reflect.DeepEqual(queued.Outputs, first.Outputs) {
		t.Fatalf("retry lost successful provider checkpoint: %+v", queued)
	}
	for _, test := range []struct {
		attempt int
		delay   time.Duration
	}{{0, 2 * time.Minute}, {1, 2 * time.Minute}, {2, 4 * time.Minute}, {8, 256 * time.Minute}, {9, 6 * time.Hour}, {1000000, 6 * time.Hour}} {
		if automaticRetryDelay(test.attempt) != test.delay {
			t.Fatalf("backoff for %d", test.attempt)
		}
	}
}

func TestAutomaticRetryWaitsForHumanAndReauthorization(t *testing.T) {
	m := automationTestManager(t).app.transfers
	job := automaticRetryJob()
	m.app.cloud.accounts["quark"] = cloudAccount{drive: &fakeCloudDrive{id: "quark"}, session: "quark-session"}
	job.Outputs["quark"] = TransferOutput{Status: "failed", Session: "quark-session", Error: "夸克授权已失效，请重新授权", NeedsAttention: true}
	saveAutomaticRetryJobs(t, m, job)
	m.planAutomaticRetry(job.ID)
	blocked, _ := m.job(job.ID)
	if !blocked.NeedsAttention || blocked.NextRetryAt != "" {
		t.Fatalf("authorization must wait: %+v", blocked)
	}
	m.credentialsAvailable("quark")
	woken, _ := m.job(job.ID)
	if woken.NextRetryAt == "" || woken.Outputs["quark"].NeedsAttention || woken.Outputs["baidu"].Status != "done" {
		t.Fatalf("reauthorization did not preserve/resume correct steps: %+v", woken)
	}
	for _, message := range []string{"GitHub Token 无效或已过期", "下载文件未通过上游 SHA-256 校验，已删除临时文件", "百度网盘登录已失效，请更新 Cookie", "需要验证码"} {
		job.Status, job.Error, job.Enrich = "failed", message, true
		job.Outputs = map[string]TransferOutput{}
		saveAutomaticRetryJobs(t, m, job)
		m.planAutomaticRetry(job.ID)
		got, _ := m.job(job.ID)
		if !got.NeedsAttention || got.NextRetryAt != "" {
			t.Fatalf("unattempted cloud work bypassed upstream block %q: %+v", message, got)
		}
	}
}

func TestAutomaticPauseCancelAndManualJobsRemainIndependent(t *testing.T) {
	m := automationTestManager(t).app.transfers
	active := automaticRetryJob()
	active.Status = "running"
	queued := automaticRetryJob()
	queued.Status = "queued"
	manual := automaticRetryJob()
	manual.Automatic, manual.Status = false, "queued"
	cancelled := automaticRetryJob()
	cancelled.Status = "cancelled"
	saveAutomaticRetryJobs(t, m, active, queued, manual, cancelled)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	m.activeID, m.activeStop = active.ID, cancel
	config := defaultAutomationConfig()
	m.maintainAutomatic(config)
	if ctx.Err() == nil {
		t.Fatal("pause did not interrupt active automatic work")
	}
	for _, job := range []TransferJob{active, queued} {
		got, _ := m.job(job.ID)
		if got.Status != "paused" || got.NextRetryAt != "" {
			t.Fatalf("did not pause: %+v", got)
		}
	}
	gotManual, _ := m.job(manual.ID)
	if gotManual.Status != "queued" {
		t.Fatal("automatic switch affected manual queue")
	}
	if err := m.action(queued.ID, "retry"); err == nil {
		t.Fatal("manually continuing an automatic task requires enabled automation")
	}
	m.activeID, m.activeStop = "", nil
	config.Enabled = true
	m.maintainAutomatic(config)
	resumed, _ := m.job(active.ID)
	gotCancelled, _ := m.job(cancelled.ID)
	if resumed.Status != "queued" || gotCancelled.Status != "cancelled" {
		t.Fatal("resume revived cancelled work or lost paused work")
	}
	if err := m.action(active.ID, "cancel"); err != nil {
		t.Fatal(err)
	}
	m.credentialsAvailable("quark")
	m.maintainAutomatic(config)
	stopped, _ := m.job(active.ID)
	if stopped.Status != "cancelled" || stopped.NextRetryAt != "" {
		t.Fatal("credentials event revived a user cancellation")
	}
}
