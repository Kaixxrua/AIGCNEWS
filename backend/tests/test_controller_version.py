import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]/'scripts/ci'))
from install_controller_version import stage


def test_modified_staged_bundle_is_never_activated(tmp_path):
    source = tmp_path/'source'
    (source/'scripts/ci').mkdir(parents=True)
    (source/'scripts/release').mkdir()
    (source/'scripts/ci/local_delivery.py').write_text('version = 1\n')
    config = {'runtime': str(tmp_path/'installed/runtime')}
    target = stage(source, config)
    assert stage(source, config) == target
    (target/'local_delivery.py').write_text('version = 2\n')
    with pytest.raises(RuntimeError, match='modified'):
        stage(source, config)
