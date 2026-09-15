"""Build small image contexts while keeping complete edge artifacts separate."""
import hashlib
import json
import shutil
import tarfile
from pathlib import PurePosixPath


def safe_name(name):
    if not name or name == '.' or name != PurePosixPath(name).as_posix() or name.startswith('/') or any(c in name for c in ('\\', ':', '\0', '\n', '\r')) or '..' in PurePosixPath(name).parts:
        raise ValueError('Unsafe image artifact path')
    return name


def prepare_image_contexts(run, old_images, files):
    previous = {}
    with tarfile.open(run / 'before-artifact.tar') as archive:
        for member in archive:
            if member.isfile():
                name = safe_name(member.name.removeprefix('./'))
                previous[name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    for name in files:
        safe_name(name)
    changed = sorted(name for name, digest in files.items() if previous.get(name) != digest)
    removed = sorted(set(previous) - set(files))
    frontend = run / 'image-context/frontend'
    mcp = run / 'image-context/mcp'
    frontend.mkdir(parents=True, exist_ok=True)
    mcp.mkdir(parents=True, exist_ok=True)
    with tarfile.open(frontend / 'frontend-delta.tar.gz', 'w:gz', compresslevel=1) as archive:
        for name in changed:
            path = run / 'dist' / name
            if path.is_symlink() or not path.resolve().is_relative_to((run/'dist').resolve()):
                raise ValueError('Image artifact escapes its root')
            archive.add(path, arcname=name, recursive=False)
    lines = ['FROM ' + old_images['frontend-web']]
    for offset in range(0, len(removed), 100):
        lines.append('RUN ' + json.dumps(['rm', '-f', '--', *['/usr/share/nginx/html/' + name for name in removed[offset:offset + 100]]]))
    lines.append('ADD frontend-delta.tar.gz /usr/share/nginx/html/')
    (frontend / 'Dockerfile').write_text('\n'.join(lines) + '\n')
    shutil.copyfile(run / 'mcp-server', mcp / 'mcp-server')
    (mcp / 'Dockerfile').write_text('FROM ' + old_images['mcp-api-go'] + '\nCOPY --chmod=755 mcp-server /usr/local/bin/mcp-server\n')
    (run / 'image-delta.json').write_text(json.dumps({'changed':changed,'removed':removed,'bytes':sum((run/'dist'/name).stat().st_size for name in changed)}, indent=2))
    return {'frontend-web': frontend, 'mcp-api-go': mcp}
