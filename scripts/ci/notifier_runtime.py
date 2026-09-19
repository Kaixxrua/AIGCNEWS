"""Fail closed before notification workers start with the wrong Python."""
import os
import subprocess
import sys


def validate(config, *, current=False):
    python = config.get('notifier_python')
    if not isinstance(python, str) or not os.path.isabs(python):
        raise RuntimeError('notify requires an absolute notifier_python')
    # Do not resolve symlinks: a venv and system Python may share the same binary.
    if current and os.path.abspath(sys.executable) != os.path.abspath(python):
        raise RuntimeError('notify interpreter differs from notifier_python; repair systemd ExecStart')
    subprocess.run([python, '-c', 'from websockets.sync.client import unix_connect'],
                   check=True, timeout=10, capture_output=True)
    return python
