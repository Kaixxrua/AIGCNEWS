"""Durable final-peak and bounded recovery decisions; never reruns GitHub jobs."""
from __future__ import annotations

import json
import os
from pathlib import Path

from runner_workloads import category


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(data, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Receipts:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, runner_id):
        return self.root / f'{int(runner_id)}.json'

    def register(self, runner_id, instance):
        path = self.path(runner_id)
        if path.exists():
            raise ValueError('runner already has durable ownership')
        atomic_json(path, {'runner_id': int(runner_id), 'instance': instance,
                           'job': None, 'state': 'registered'})

    def bind(self, runner_id, job):
        path = self.path(runner_id)
        data = json.loads(path.read_text()) if path.exists() else {}
        identity = {key: job[key] for key in ('id', 'run_id', 'head_sha')}
        if data.get('job') is not None and data['job'] != identity:
            raise ValueError('runner job ownership changed')
        if data.get('job') is None:
            data.update(job=identity, category=category(job), state='running')
            atomic_json(path, data)

    def finalize(self, runner_id, job, peak, oom, history):
        path = self.path(runner_id)
        data = json.loads(path.read_text())
        identity = {key: job[key] for key in ('id', 'run_id', 'head_sha')}
        if identity != data['job'] or job['status'] != 'completed':
            raise ValueError('final job evidence is obsolete or incomplete')
        if data['state'] == 'final':
            return data
        if peak < 0 or oom < 0:
            raise ValueError('invalid final counters')
        history.observe(str(job['id']), data['category'], peak)
        history.oom(str(job['id']), oom)
        history.save()
        data.update(state='final', peak=peak, oom_kill=oom, conclusion=job['conclusion'],
                    classification='memory_oom' if oom else ('success' if job['conclusion'] == 'success'
                                                            else 'needs_failure_logs'),
                    recovery='coordinator_review' if oom else 'none', retry_budget=1)
        atomic_json(path, data)
        return data

    def authorize_recovery(self, runner_id, current_head, job_id, evidence):
        """Persist one reviewed retry receipt; no API mutation or automatic replay."""
        path = self.path(runner_id)
        data = json.loads(path.read_text())
        if (data.get('classification') != 'memory_oom' or data.get('retry_budget') != 1
                or data['job']['head_sha'] != current_head or data['job']['id'] != job_id
                or not evidence.strip()):
            raise ValueError('recovery requires exact job/head, evidence and unused budget')
        data.update(retry_budget=0, recovery='authorized_once', recovery_evidence=evidence)
        atomic_json(path, data)
        return data
