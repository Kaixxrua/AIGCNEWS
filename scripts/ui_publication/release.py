"""Publish a catalog release using the current app artifact and embedded Go catalog."""
from __future__ import annotations

import json
import io
import os
import re
import shutil
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

from adapter import sha, write_json
from image_artifacts import prepare_image_contexts


class Release:
    def __init__(self, root: Path, run: Path):
        self.root, self.run = root, run
        self.compose_path = root / 'local/compose.yml'
        self.compose_before = self.compose_path.read_bytes()
        self.catalog_path = root / 'mcp-go/internal/uicatalog/data/catalog.json'
        self.catalog_before = self.catalog_path.read_bytes()
        self.old_images = {service: self.command(['docker', 'inspect', '--format', '{{.Config.Image}}', 'aigcnews-local-' + service + '-1']).strip() for service in ('frontend-web','mcp-api-go')}
        self.switched = False
        (run / 'before-catalog.json').write_bytes(self.catalog_before)
        (run / 'before-compose.yml').write_bytes(self.compose_before)
        write_json(run / 'before-images.json', self.old_images)

    def command(self, args, *, cwd=None, env=None, timeout=1800, input=None):
        print('Running: ' + ' '.join(str(arg).splitlines()[0][:120] for arg in args[:6]), flush=True)
        result = subprocess.run(args, cwd=cwd or self.root, env=env, input=input, capture_output=True, timeout=timeout)
        with (self.run / 'commands.log').open('ab') as log:
            log.write(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'command_failed:{Path(str(args[0])).name}:{result.returncode}; see commands.log')
        return result.stdout.decode('utf-8', errors='replace')

    def export(self):
        # Snapshot the running image, so unrelated application code is not rebuilt or replaced.
        with (self.run / 'before-artifact.tar').open('wb') as target:
            subprocess.run(['docker','exec','aigcnews-local-frontend-web-1','tar','cf','-','-C','/usr/share/nginx/html','.'], stdout=target, check=True, timeout=180)
        dist = self.run / 'dist'
        dist.mkdir()
        with tarfile.open(self.run / 'before-artifact.tar') as archive:
            archive.extractall(dist, filter='data')
        if sha((dist / 'ui-library/catalog.json').read_bytes()) != sha(self.catalog_before):
            raise RuntimeError('origin_and_backend_catalog_drift')

    def edge(self, phase):
        # Complete template packages exceed the old 512 MB tmpfs. Native Docker
        # storage also avoids slow per-file I/O through Windows bind mounts.
        scratch='aigcnews-ui-edge-'+uuid.uuid4().hex
        worker=scratch+'-worker'
        self.command(['docker','volume','create','--label','aigcnews.role=ui-publication-scratch',scratch])
        try:
            self.command(['docker','run','--rm','--name',worker,'--read-only','--network','aigcnews-local_default','--tmpfs','/root/.ssh:rw,noexec,nosuid,size=1m','-v',scratch+':/tmp','-e','PYTHONDONTWRITEBYTECODE=1',
                          '-v',f'{self.root / "local/edge-credentials"}:/credentials:ro', '-v',f'{self.root / "local/edge/ssh_config"}:/opt/edge/ssh_config:ro',
                          '-v',f'{self.root / "local/edge"}:/work:ro', '-v',f'{self.run}:/release:rw', '-v',f'{Path(__file__).parent}:/publisher:ro',
                          'aigcnews-local-edge:recovered','python3','/publisher/edge.py',phase], timeout=7200)
        except subprocess.TimeoutExpired:
            # A disconnected Docker client does not stop its container. Ensure
            # this worker cannot activate an edge after the caller rolls back.
            self.command(['docker','stop','--timeout','10',worker],timeout=45)
            raise
        finally:
            try:
                self.command(['docker','volume','rm',scratch])
            except (RuntimeError,subprocess.TimeoutExpired):
                # Docker refuses removal if a timed-out worker still uses it.
                print('Publication scratch retained for recovery: '+scratch,flush=True)

    def prepare(self, ids):
        inventory = json.loads((self.root / 'local/edge/inventory.json').read_text())
        for site in inventory['sites'].values():
            site.update(project_root='/tmp/ui-artifact', artifact_dir='dist')
            site['smoke_checks'] += [{'path':'/ui-library/catalog.json','expected_status':200,'contains':ids[0]},
                                     {'path':f'/ui-library/previews/{ids[0]}.html','expected_status':200},
                                     {'path':f'/ui-library/posters/{ids[0]}.png','expected_status':200}]
        write_json(self.run / 'edge-inventory.json', inventory)
        self.edge('snapshot')
        # Pack only the Go program and audited embedded data, excluding previews and posters.
        with tarfile.open(self.run / 'go-source.tar', 'w') as archive:
            for directory, children, filenames in os.walk(self.root / 'mcp-go'):
                children[:] = [name for name in children if name not in ('data','.git')]
                for filename in filenames:
                    path = Path(directory) / filename
                    archive.add(path, arcname=path.relative_to(self.root / 'mcp-go').as_posix(), recursive=False)
            data = self.run / 'dist/ui-library'
            for path in data.rglob('*'):
                rel = path.relative_to(data)
                if path.is_file() and rel.parts[0] not in ('previews','posters','clips'):
                    archive.add(path, arcname='internal/uicatalog/data/' + rel.as_posix(), recursive=False)
        self.command(['docker','run','--rm','--tmpfs','/work:rw,size=768m','-e','GOMAXPROCS=4','-e','CGO_ENABLED=0','-v',f'{self.run}:/release','-v','aigc-ui-go-mod:/go/pkg/mod','-v','aigc-ui-go-build:/root/.cache/go-build','-w','/work','golang:1.26.6-alpine','sh','-c','tar xf /release/go-source.tar && go test -p 2 ./internal/uicatalog ./internal/mcpapp && go build -trimpath -ldflags="-s -w" -o /release/mcp-server ./cmd/mcp-server'])
        files = {}
        with tarfile.open(self.run / 'frontend-dist.tar.gz','w:gz',compresslevel=1) as archive:
            for path in (self.run / 'dist').rglob('*'):
                if path.is_file():
                    name = path.relative_to(self.run / 'dist').as_posix()
                    raw = path.read_bytes()
                    files[name] = sha(raw)
                    archive.addfile(archive.gettarinfo(str(path),arcname=name),io.BytesIO(raw))
        write_json(self.run / 'artifact-manifest.json', files)
        contexts = prepare_image_contexts(self.run, self.old_images, files)
        self.images = {}
        for service, kind in [('frontend-web','frontend'),('mcp-api-go','mcp')]:
            tag = f'aigcnews-local-{kind}:ui-auto-{self.run.name.lower()}'
            self.command(['docker','build','-t',tag,'.'],cwd=contexts[service])
            self.images[service] = tag
        write_json(self.run / 'images.json', self.images)

    def compose(self, images):
        write_json(self.run / 'override.json', {'services':{name:{'image': image} for name,image in images.items()}})
        self.command(['docker','compose','--project-name','aigcnews-local','--env-file','.env','--env-file','local/safety.env','-f','local/compose.yml','-f',str(self.run / 'override.json'),'up','-d','--no-deps','frontend-web','mcp-api-go'])
        for _ in range(36):
            states = [self.command(['docker','inspect','--format','{{.State.Health.Status}}','aigcnews-local-' + service + '-1']).strip() for service in images]
            if states == ['healthy','healthy']:
                return
            time.sleep(5)
        raise RuntimeError('new_containers_unhealthy')

    def publish(self, *, reuse_uploaded=False):
        if self.compose_path.read_bytes() != self.compose_before or self.catalog_path.read_bytes() != self.catalog_before:
            raise RuntimeError('concurrent_origin_change')
        for service, image in self.old_images.items():
            if self.command(['docker','inspect','--format','{{.Config.Image}}','aigcnews-local-' + service + '-1']).strip() != image:
                raise RuntimeError('concurrent_image_change')
        # Source files first, catalog last; existing entries are never overwritten by this adapter.
        self.switched = True
        self.compose(self.images)
        # Admit the new IDs before the first public edge exposes them. Old IDs
        # remain present, so copying an existing template stays compatible.
        target = self.catalog_path.with_suffix('.next.json')
        target.write_bytes((self.run / 'dist/ui-library/catalog.json').read_bytes())
        target.replace(self.catalog_path)
        self.edge('republish' if reuse_uploaded else 'publish')
        compose = self.compose_before.decode()
        for service, image in self.images.items():
            compose, n = re.subn(r'(?m)(^  ' + re.escape(service) + r':\r?\n(?:.*\r?\n)*?    image: )[^\r\n]+',lambda m:m[1]+image,compose,count=1)
            if n != 1:
                raise RuntimeError('compose_image_slot_missing')
        temporary = self.compose_path.with_suffix('.next.yml')
        temporary.write_text(compose, newline='')
        temporary.replace(self.compose_path)

    def rollback(self):
        if not self.switched:
            return
        for service in self.old_images:
            current = self.command(['docker','inspect','--format','{{.Config.Image}}','aigcnews-local-' + service + '-1']).strip()
            if current not in (self.old_images[service], self.images[service]):
                raise RuntimeError('concurrent_release_blocks_rollback')
        if self.catalog_path.read_bytes() not in (self.catalog_before, (self.run / 'dist/ui-library/catalog.json').read_bytes()):
            raise RuntimeError('concurrent_catalog_blocks_rollback')
        self.edge('rollback')
        self.compose(self.old_images)
        temporary = self.catalog_path.with_suffix('.rollback.json')
        temporary.write_bytes(self.catalog_before)
        temporary.replace(self.catalog_path)
        # Preserve unrelated Compose edits; revert only this release's image tags.
        compose = self.compose_path.read_bytes().decode()
        for service, image in self.images.items():
            compose = compose.replace('image: ' + image, 'image: ' + self.old_images[service])
        temporary = self.compose_path.with_suffix('.rollback.yml')
        temporary.write_text(compose, newline='')
        temporary.replace(self.compose_path)

    def sync(self):
        # Compare with the immutable origin snapshot in one sequential read,
        # avoiding tens of thousands of repeated Windows filesystem reads daily.
        previous = {}
        with tarfile.open(self.run / 'before-artifact.tar') as archive:
            for member in archive:
                if member.isfile():
                    previous[member.name.removeprefix('./')] = sha(archive.extractfile(member).read())
        manifest = json.loads((self.run / 'artifact-manifest.json').read_text())
        changed = {name for name, digest in manifest.items() if previous.get(name) != digest}
        for destination, source in [(self.root / 'mcp-go/internal/uicatalog/data', self.run / 'dist/ui-library'),
                                    (self.root / 'frontend/dist', self.run / 'dist'),
                                    (self.root / 'local/edge/artifact', self.run / 'dist')]:
            for name in sorted(changed, key=lambda name: (name == 'ui-library/catalog.json', name)):
                path = self.run / 'dist' / name
                if not path.is_relative_to(source):
                    continue
                target = destination / path.relative_to(source)
                if target.exists() and sha(target.read_bytes()) == manifest[name]:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.publication-next')
                shutil.copyfile(path, temporary)
                temporary.replace(target)
