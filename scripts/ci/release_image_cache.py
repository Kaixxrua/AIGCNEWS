"""Reuse immutable production images only when their prepared inputs match."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path

CONTEXTS = {'backend': 'backend', 'mcp': 'mcp-go', 'frontend': 'frontend'}
MAX_AGE = 7 * 24 * 3600


def digest_tree(root):
    """Hash staged bytes and modes, including private assets, without following links."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('unsupported build input: ' + str(path.relative_to(root)))
        digest.update(json.dumps([path.relative_to(root).as_posix(), stat.S_IMODE(mode),
                                  'file' if stat.S_ISREG(mode) else 'directory']).encode() + b'\0')
        if stat.S_ISREG(mode):
            with path.open('rb') as stream:
                file_digest = hashlib.file_digest(stream, 'sha256').digest()
            digest.update(file_digest)
    return digest.hexdigest()


def toolchain_identity():
    commands = (['docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}/{{.Server.Version}}'],
                ['docker', 'buildx', 'version'])
    return [subprocess.check_output(args, text=True, timeout=30).strip() for args in commands]


def image_key(checkout, service, config, toolchain):
    # The actual Docker contexts contain private files absent from Git. Shared
    # repository files (including every deploy/build helper) invalidate all
    # components; only the other two component directories are excluded.
    context = CONTEXTS[service]
    if service == 'mcp':
        ignore = checkout / 'mcp-go/Dockerfile.dockerignore'
        if not ignore.exists():
            ignore = checkout / '.dockerignore'
        patterns = [line.strip() for line in ignore.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith('#')] if ignore.exists() else []
        # The Go build uses the repository root. A broader context needs a new
        # dependency review; continue building it normally in the meantime.
        if patterns != ['*', '!mcp-go']:
            return None
    entries = subprocess.check_output(['git', '-C', str(checkout), 'ls-tree', '-r', '-z', 'HEAD'],
                                      timeout=30).split(b'\0')
    shared = [entry.decode() for entry in entries if entry and
              entry.split(b'\t', 1)[1].split(b'/', 1)[0].decode() not in CONTEXTS.values()]
    payload = [service, digest_tree(checkout / context), shared, config, toolchain,
               hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               hashlib.sha256(Path(__file__).with_name('local_release.py').read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def image_available(reference):
    result = subprocess.run(['docker', 'image', 'inspect', reference],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    return result.returncode == 0


def cached_image(path, key, service):
    if key is None:
        return None
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = json.loads(path.read_text())
        image = value['image']
        if (value['key'] != key or not 0 <= time.time() - value['at'] <= MAX_AGE
                or not re.fullmatch('ghcr.io/kaixxrua/aigcnews/' + service + r'@sha256:[0-9a-f]{64}', image)
                or not re.fullmatch(r'[0-9a-f]{40}', value['source_sha'])
                or not image_available(image)):
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


def record_image(path, key, image, sha):
    from local_ci import atomic_json

    if key is not None:
        atomic_json(path, {'key': key, 'image': image, 'source_sha': sha, 'at': time.time()})
