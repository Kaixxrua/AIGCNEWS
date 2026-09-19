import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]/'scripts/ci'))
import release_progress as p


def test_successful_stages_survive_later_failure(tmp_path):
    config = {'state': str(tmp_path)}
    sha = 'a'*40
    with p.stage(config, sha, 'build'):
        pass
    with pytest.raises(RuntimeError), p.stage(config, sha, 'deploy'):
        raise RuntimeError('health check failed')
    state = p.read(config, sha)
    assert state['completed'] == ['build']
    assert state['stage'] == 'deploy' and state['status'] == 'failed'
    (p.path(config, sha).parent/'release.log').write_text('connection reset')
    assert not p.retryable(config, sha)


@pytest.mark.parametrize('phase', ['build', 'edge'])
def test_only_transport_failures_of_safe_stages_can_retry(tmp_path, phase):
    config = {'state': str(tmp_path)}
    sha = 'a'*40
    with pytest.raises(RuntimeError), p.stage(config, sha, phase):
        raise RuntimeError('failed')
    log = p.path(config, sha).parent/'release.log'
    log.write_text('assertion failed')
    assert not p.retryable(config, sha)
    log.write_text('TLS handshake timeout')
    assert p.retryable(config, sha)
