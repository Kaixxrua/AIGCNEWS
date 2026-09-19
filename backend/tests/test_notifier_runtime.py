import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts/ci'))
from notifier_runtime import validate


def test_wrong_interpreter_rejected_before_import():
    with patch('notifier_runtime.subprocess.run') as run:
        with pytest.raises(RuntimeError, match='ExecStart'):
            validate({'notifier_python': '/private/venv/bin/python'}, current=True)
        run.assert_not_called()


def test_missing_dependency_rejected():
    with patch('notifier_runtime.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'python')):
        with pytest.raises(subprocess.CalledProcessError):
            validate({'notifier_python': sys.executable}, current=True)


def test_exact_interpreter_and_sync_dependency_checked():
    with patch('notifier_runtime.subprocess.run') as run:
        assert validate({'notifier_python': sys.executable}, current=True) == sys.executable
        assert 'websockets.sync.client' in run.call_args.args[0][-1]
        assert run.call_args.kwargs['timeout'] == 10


def test_no_silent_system_python_fallback():
    with pytest.raises(RuntimeError, match='notifier_python'):
        validate({})
