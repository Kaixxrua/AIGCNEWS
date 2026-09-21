import io
import json
from unittest.mock import Mock

from scripts.backfill_github_project_logos import RepairQueue


def test_repair_snapshot_attempts_failures_once_and_records_no_binary_content():
    repository = Mock()
    report = io.StringIO()
    queue = RepairQueue(repository, [{'repo_id': 'a/hot'}, {'repo_id': 'b/cold'}], report)
    assert queue.pending(1) == [{'repo_id': 'a/hot'}]
    queue.save('a/hot', {'status': 'failed', 'errors': [{'error': 'ReadTimeout'}]})
    assert queue.pending(1) == [{'repo_id': 'b/cold'}]
    queue.save('b/cold', {'status': 'found', 'content': b'artwork'})
    assert queue.pending(10) == []
    records = [json.loads(line) for line in report.getvalue().splitlines()]
    assert records == [{'repo_id': 'a/hot', 'status': 'failed', 'errors': [{'error': 'ReadTimeout'}]},
                       {'repo_id': 'b/cold', 'status': 'found'}]
    assert repository.save.call_count == 2
