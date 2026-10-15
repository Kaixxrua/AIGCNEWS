"""Exercise the shared media connection pool against a real HTTP peer."""

import asyncio

import pytest

from backend.app.services import x_poster_frames


@pytest.mark.asyncio
async def test_reuses_active_connections_but_reconnects_after_idle(monkeypatch):
    # The production egress can leave an idle socket open but stop answering it.
    # Unlike MockTransport, this peer exercises HTTPX's actual connection pool.
    connections = []
    handlers = []
    release_stalled = asyncio.Event()
    loop = asyncio.get_running_loop()

    async def peer(reader, writer):
        connections.append(writer)
        handlers.append(asyncio.current_task())
        last_response = None
        try:
            while True:
                await reader.readuntil(b"\r\n\r\n")
                if last_response is not None and loop.time() - last_response >= 2.0:
                    await release_stalled.wait()
                    return
                writer.write(
                    b"HTTP/1.1 206 Partial Content\r\n"
                    b"Content-Type: video/mp4\r\n"
                    b"Content-Length: 4\r\n"
                    b"Content-Range: bytes 0-3/8\r\n\r\nclip"
                )
                await writer.drain()
                last_response = loop.time()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(x_poster_frames, "outbound_proxy", lambda: f"http://127.0.0.1:{port}")
        monkeypatch.setattr(x_poster_frames, "_shared_client", None)
        client = x_poster_frames.get_upstream_client()
        # Explicit loopback HTTP proxy: the hostname never reaches public DNS.
        url = "http://video.twimg.com/test.mp4"
        try:
            for _ in range(2):
                response = await client.get(url, headers={"Range": "bytes=0-3"}, timeout=0.5)
                assert response.status_code == 206
                assert response.content == b"clip"
            assert len(connections) == 1  # Active bursts retain connection reuse.

            await asyncio.sleep(2.2)
            response = await client.get(url, headers={"Range": "bytes=0-3"}, timeout=0.5)
            assert response.status_code == 206
            assert response.content == b"clip"
            assert response.headers["content-range"] == "bytes 0-3/8"
            assert len(connections) == 2
        finally:
            await client.aclose()
            release_stalled.set()
            for writer in connections:
                writer.close()
            await asyncio.gather(*handlers)
