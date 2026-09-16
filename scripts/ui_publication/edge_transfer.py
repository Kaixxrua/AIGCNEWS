"""Reuse verified files on the destination without linking to live release files."""
from contextlib import contextmanager


def transfer_args(args, previous):
    if previous is None or not isinstance(args, (list, tuple)) or not args or args[0] != 'rsync':
        return args
    return [args[0], '--checksum', '--copy-dest=../../releases/' + previous, *args[1:]]


@contextmanager
def reuse_release_files(controller, previous):
    if previous is None:
        yield
        return
    controller.validate_release(previous)
    base = controller.subprocess

    class ProcessProxy:
        def __getattr__(self, name):
            return getattr(base, name)

        def run(self, args, *positional, **kwargs):
            return base.run(transfer_args(args, previous), *positional, **kwargs)

    controller.subprocess = ProcessProxy()
    try:
        yield
    finally:
        controller.subprocess = base
