"""Exercise the shipped nginx slice config against real Range responses."""
import http.server
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

BODY = bytes(range(251)) * 13000
REQUESTS = []


class Origin(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = self.headers.get('Range', '')
        REQUESTS.append((self.path, raw))
        match = re.fullmatch(r'bytes=(\d+)-(\d*)', raw)
        start, end = (int(match[1]), int(match[2] or len(BODY)-1)) if match else (0, len(BODY)-1)
        if start >= len(BODY):
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{len(BODY)}')
            self.end_headers()
            return
        end = min(end, len(BODY)-1)
        self.send_response(206 if match else 200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Length', str(end-start+1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('ETag', '"immutable-video"')
        self.send_header('Cache-Control', 'public, max-age=604800')
        if match:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(BODY)}')
        self.end_headers()
        self.wfile.write(BODY[start:end+1])


@pytest.fixture
def edge(tmp_path):
    nginx = shutil.which('nginx')
    if not nginx:
        pytest.skip('nginx with http_slice_module required for integration test')
    REQUESTS.clear()
    origin = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    snippet = (Path(__file__).resolve().parents[2] / 'deploy/nginx/x-video-slice.conf').read_text()
    snippet = snippet.replace('https://127.0.0.1:18443', f'http://127.0.0.1:{origin.server_port}')
    config = tmp_path / 'nginx.conf'
    config.write_text(f'''daemon off; master_process off; pid {tmp_path}/nginx.pid;
error_log {tmp_path}/error.log; events {{ worker_connections 64; }}
http {{ access_log off; proxy_temp_path {tmp_path}/temp;
proxy_cache_path {tmp_path}/cache keys_zone=aigcmedia:1m;
server {{ listen 127.0.0.1:{port};
proxy_no_cache $http_range; proxy_cache_bypass $http_range;
{snippet}
}} }}''')
    process = subprocess.Popen([nginx, '-p', str(tmp_path), '-c', str(config)])
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail((tmp_path / 'error.log').read_text())
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except OSError:
                time.sleep(.02)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
            yield client
    finally:
        process.terminate()
        process.wait(timeout=5)
        origin.shutdown()
        origin.server_close()


def test_slices_hit_and_seek_without_cross_contamination(edge):
    path = '/api/media/x/img/video.twimg.com/test.mp4?tag=29'
    for start, end in [(0, 999), (1500000, 1500999), (1048500, 1048600),
                       (len(BODY)-100, len(BODY)-1)]:
        response = edge.get(path, headers={'Range': f'bytes={start}-{end}'})
        assert response.status_code == 206
        assert response.content == BODY[start:end+1]
        assert response.headers['content-range'] == f'bytes {start}-{end}/{len(BODY)}'
        before = len(REQUESTS)
        repeated = edge.get(path, headers={'Range': f'bytes={start}-{end}'})
        assert repeated.content == response.content
        assert repeated.headers['x-edge-cache'] == 'HIT'
        assert len(REQUESTS) == before
    assert all(re.fullmatch(r'bytes=\d+-\d+', raw) for _, raw in REQUESTS)
    assert edge.get(path).content == BODY
    assert edge.get(path, headers={'Range': 'bytes=-100'}).content == BODY[-100:]
    assert edge.get(path, headers={'Range': f'bytes={len(BODY)+10}-'}).status_code == 416
    other = edge.get(path + '&different=1', headers={'Range': 'bytes=0-999'})
    assert other.headers['x-edge-cache'] == 'MISS'
    assert other.content == BODY[:1000]


def test_if_range_and_multi_range_keep_http_semantics(edge):
    path = '/api/media/x/img/video.twimg.com/conditional.mp4'
    response = edge.get(path, headers={'Range': 'bytes=0-99', 'If-Range': '"old"'})
    assert response.status_code == 200
    assert response.content == BODY
    response = edge.get(path, headers={'Range': 'bytes=10-99', 'If-Range': '"immutable-video"'})
    assert response.status_code == 206
    assert response.content == BODY[10:100]
    response = edge.get(path, headers={'Range': 'bytes=0-9,20-29'})
    assert response.status_code == 200  # max_ranges=1 safely ignores multipart Range
    assert response.content == BODY
