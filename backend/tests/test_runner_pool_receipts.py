import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
from runner_pool_receipts import Receipts
from runner_workloads import History


def job(**extra):
    return {'id': 1, 'run_id': 2, 'head_sha': 'a' * 40, 'name': 'Backend tests',
            'status': 'completed', 'conclusion': 'failure', **extra}


def test_final_peak_saved_before_receipt_and_recovery_is_exact_and_once(tmp_path):
    receipts = Receipts(tmp_path / 'receipts')
    history = History(tmp_path / 'history.json')
    receipts.bind(7, job(status='in_progress'))
    final = receipts.finalize(7, job(), 4 * 1024**3, 1, history)
    assert final['classification'] == 'memory_oom'
    assert History(history.path).predict('backend') == 5 * 1024**3
    assert json.loads(receipts.path(7).read_text())['peak'] == 4 * 1024**3
    with pytest.raises(ValueError): receipts.authorize_recovery(7, 'b' * 40, 1, 'review')
    with pytest.raises(ValueError): receipts.authorize_recovery(7, 'a' * 40, 2, 'review')
    with pytest.raises(ValueError): receipts.authorize_recovery(7, 'a' * 40, 1, '')
    receipts.authorize_recovery(7, 'a' * 40, 1, 'profile corrected, exact head and base revalidated')
    with pytest.raises(ValueError): receipts.authorize_recovery(7, 'a' * 40, 1, 'replay')
    assert History(history.path).data['oom']  # authorization does not erase evidence


def test_finalization_is_idempotent_and_other_failures_not_called_oom(tmp_path):
    receipts = Receipts(tmp_path / 'receipts'); history = History(tmp_path / 'history.json')
    receipts.bind(7, job())
    final = receipts.finalize(7, job(), 100, 0, history)
    assert final['classification'] == 'needs_failure_logs'
    assert receipts.finalize(7, job(), 200, 0, history) == final
    with pytest.raises(ValueError): receipts.bind(7, job(id=99))
    with pytest.raises(ValueError): receipts.finalize(7, job(head_sha='b' * 40), 100, 0, history)


def test_active_job_or_missing_identity_never_finalizes(tmp_path):
    receipts = Receipts(tmp_path / 'receipts'); history = History(tmp_path / 'history.json')
    receipts.bind(7, job())
    with pytest.raises(ValueError): receipts.finalize(7, job(status='in_progress'), 100, 0, history)
    with pytest.raises(FileNotFoundError): receipts.finalize(8, job(), 100, 0, history)


def test_reaper_requires_final_receipt_before_unregister_and_destroy(tmp_path):
    import ephemeral_runner_autoscaler as scaler
    runtime = scaler.LxdRuntime('template', 'job-', tmp_path)
    runtime.shared_parent = '/not-live'
    runtime.instances = lambda: [scaler.Instance('job-one', 'STOPPED', runner_id=7)]
    events = []
    class GitHub:
        def delete_runner(self, runner_id): events.append('unregister')
    runtime.destroy = lambda name: events.append('destroy')
    with pytest.raises(scaler.AutoscalerError, match='final peak unavailable'):
        runtime.reap(idle_timeout=scaler.timedelta(minutes=5), github=GitHub())
    assert events == []
    runtime.capture_final = lambda *args: events.append('final-receipt')
    runtime.reap(idle_timeout=scaler.timedelta(minutes=5), github=GitHub())
    assert events == ['final-receipt', 'unregister', 'destroy']


def test_recovery_latch_requires_current_pr_base_and_consumes_one_receipt(tmp_path):
    from review_pool_recovery import reconcile
    receipts = Receipts(tmp_path / 'receipts'); history = History(tmp_path / 'history.json')
    receipts.bind(7, job())
    receipts.finalize(7, job(), 100, 1, history)
    pr = {'state': 'open', 'draft': False, 'base': {'ref': 'main'}, 'head': {'sha': 'a' * 40}}
    with pytest.raises(ValueError):
        reconcile(receipts, history, 7, 1, 'a' * 40, 'reviewed', pr, {'status': 'behind'})
    assert history.data['oom']
    reconcile(receipts, history, 7, 1, 'a' * 40, 'reviewed profile and logs', pr, {'status': 'ahead'})
    assert not History(history.path).data['oom']
    with pytest.raises(ValueError):
        reconcile(receipts, history, 7, 1, 'a' * 40, 'repeat', pr, {'status': 'ahead'})


def test_drain_collects_but_never_admits_even_with_queue(tmp_path, monkeypatch):
    import ephemeral_runner_autoscaler as scaler
    monkeypatch.setattr(scaler.Path, 'home', lambda: tmp_path)
    class GitHub:
        def queued_jobs(self, *args): return [1, 2, 3]
        def generate_jit(self, *args): pytest.fail('drain must never create')
    class Runtime:
        reaped = False
        def instances(self): return []
        def reap(self, **kwargs): self.reaped = True
    runtime = Runtime()
    controller = scaler.Autoscaler(GitHub(), runtime, label='ci', prefix='job-', maximum=2,
                                  cpu='1', memory='1GiB', idle_timeout=scaler.timedelta(minutes=5))
    plan = controller.reconcile(apply=True, drain=True)
    assert plan.spawn == 0 and runtime.reaped


@pytest.mark.parametrize('service,final,expected', [(b'active', True, []),
                                                    (b'inactive', False, ['final']),
                                                    (b'inactive', True, ['final', 'unregister', 'destroy'])])
def test_shared_reaper_finishes_young_jobs_and_waits_without_restart(tmp_path, service, final, expected):
    import ephemeral_runner_autoscaler as scaler
    runtime = scaler.LxdRuntime('template', 'job-', tmp_path)
    runtime.shared_parent = '/not-live'
    runtime.instances = lambda: [scaler.Instance('job-one', 'RUNNING', scaler.datetime.now(scaler.UTC), 7)]
    runtime.has_worker = lambda name: False
    runtime.command = lambda *args, **kwargs: scaler.subprocess.CompletedProcess([], 0, service, b'')
    events = []
    def capture(*args):
        events.append('final')
        return final
    runtime.capture_final = capture
    runtime.destroy = lambda name: events.append('destroy')
    class GitHub:
        def delete_runner(self, runner_id): events.append('unregister')
    runtime.reap(idle_timeout=scaler.timedelta(minutes=5), github=GitHub())
    assert events == expected


def test_launch_ownership_survives_restart_and_cannot_be_reused(tmp_path):
    receipts = Receipts(tmp_path / 'receipts')
    receipts.register(7, 'job-one')
    restored = Receipts(receipts.root)
    with pytest.raises(ValueError): restored.register(7, 'job-two')
    restored.bind(7, job())
    data = json.loads(restored.path(7).read_text())
    assert data['instance'] == 'job-one' and data['runner_id'] == 7
    assert data['job']['id'] == 1
    with pytest.raises(ValueError): restored.bind(7, job(id=2))
