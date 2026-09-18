#!/usr/bin/env python3
"""Coordinator-only exact-job recovery receipt and latch reconciliation.

Never reruns a job. Requires a fresh verified empty pool and a current PR head
containing current main. Receipt consumes the one-review budget before clearing
that job's history latch; ambiguous interruption requires manual reconciliation.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path

from ephemeral_runner_autoscaler import ApiClient
from runner_pool_receipts import Receipts
from runner_workloads import History
from shared_runner_pool import active, counters, inventory, limits, owner


def reconcile(receipts, history, runner_id, job_id, head, evidence, pr, comparison):
    if (pr['state'] != 'open' or pr['draft'] or pr['base']['ref'] != 'main'
            or pr['head']['sha'] != head or comparison['status'] not in {'ahead', 'identical'}):
        raise ValueError('PR head/base changed; recovery refused')
    receipt = receipts.authorize_recovery(runner_id, head, job_id, evidence)
    history.data['oom'].pop(str(job_id), None)
    history.save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runner-id', required=True, type=int)
    parser.add_argument('--job-id', required=True, type=int)
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--current-head', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    root = Path.home() / '.local/state/aigcnews-ci-runners'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (root / 'controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    parent = Path(os.environ['AIGCNEWS_RUNNER_SHARED_CGROUP'])
    owner(parent, os.environ['AIGCNEWS_RUNNER_SHARED_UNIT'])
    limits(parent)
    if active(inventory()) or int(counters(parent / 'memory.events').get('oom_kill', 0)):
        raise ValueError('drain all CI/control and recreate the parent before recovery')
    client = ApiClient(os.environ.get('GITHUB_REPOSITORY', 'Kaixxrua/AIGCNEWS'), os.environ['GH_TOKEN'])
    pr = client.request('GET', f'/pulls/{args.pr}')
    main_sha = client.request('GET', '/git/ref/heads/main')['object']['sha']
    comparison = client.request('GET', f'/compare/{main_sha}...{args.current_head}')
    if client.request('GET', '/git/ref/heads/main')['object']['sha'] != main_sha:
        raise ValueError('main advanced during recovery review')
    pr = client.request('GET', f'/pulls/{args.pr}')
    root = Path.home() / '.local/state/aigcnews-ci-runners'
    print(json.dumps(reconcile(Receipts(root / 'job-receipts'), History(root / 'workload-history.json'),
                              args.runner_id, args.job_id, args.current_head, args.evidence, pr, comparison)))


if __name__ == '__main__':
    main()
