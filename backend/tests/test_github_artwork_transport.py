import ssl
from unittest.mock import Mock

import httpx
import pytest

from backend.app.services.ingestion import github_artwork_transport as artwork


def request(host='github.com', ip='93.184.216.34'):
    return httpx.Request('GET', f'https://{ip}/acme.png', headers={'Host': host},
                         extensions={'sni_hostname': host})


def test_proxy_connect_preserves_pin_and_verified_hostname(monkeypatch):
    contexts = []
    transports = []
    def transport(**kwargs):
        contexts.append(kwargs['verify'])
        assert kwargs['proxy'] == 'http://proxy.example:3128'
        result = Mock()
        result.handle_request.return_value = httpx.Response(200)
        transports.append(result)
        return result
    monkeypatch.setattr(artwork.httpx, 'HTTPTransport', transport)
    wrap = Mock()
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', wrap)
    with artwork.GitHubArtworkTransport(proxy='http://proxy.example:3128') as client:
        first = request()
        client.handle_request(first)
        client.handle_request(request())
        client.handle_request(request('avatars.githubusercontent.com'))
        assert len(transports) == 2
        assert transports[0].handle_request.call_args_list[0].args[0] is first
        assert first.url.host == '93.184.216.34'
        assert contexts[0].verify_mode == ssl.CERT_REQUIRED
        assert contexts[0].check_hostname is True
        assert contexts[0].cert_store_stats()['x509_ca'] > 0
        contexts[0].wrap_socket('socket', server_hostname='93.184.216.34')
        wrap.assert_called_with('socket', server_hostname='github.com')
        contexts[1].wrap_socket('socket', server_hostname='93.184.216.34')
        wrap.assert_called_with('socket', server_hostname='avatars.githubusercontent.com')
    for transport in transports:
        transport.close.assert_called_once()


@pytest.mark.parametrize('host,ip', [('evil.example', '93.184.216.34'),
    ('github.com', '127.0.0.1'), ('github.com', '169.254.169.254'),
    ('github.com', 'github.com')])
def test_transport_rejects_non_pinned_or_untrusted_requests(host, ip):
    with artwork.GitHubArtworkTransport() as client, pytest.raises(ValueError):
        client.handle_request(request(host, ip))


def test_transport_rejects_host_header_mismatch():
    req = request()
    req.headers['Host'] = 'evil.example'
    with artwork.GitHubArtworkTransport() as client, pytest.raises(ValueError):
        client.handle_request(req)


@pytest.mark.parametrize('error', [httpx.ConnectError('TLS EOF'), httpx.ReadTimeout('timeout')])
def test_proxy_failure_retries_the_identical_pin_directly(monkeypatch, error):
    proxy = Mock()
    proxy.handle_request.side_effect = error
    direct = Mock()
    direct.handle_request.return_value = httpx.Response(200)
    factory = Mock(side_effect=[proxy, direct])
    monkeypatch.setattr(artwork.httpx, 'HTTPTransport', factory)
    req = request()
    with artwork.GitHubArtworkTransport('http://proxy.example:3128') as client:
        assert client.handle_request(req).status_code == 200
    assert factory.call_args_list[0].kwargs['proxy'] == 'http://proxy.example:3128'
    assert factory.call_args_list[1].kwargs['proxy'] is None
    assert factory.call_args_list[1].kwargs['verify'].check_hostname is True
    proxy.handle_request.assert_called_once_with(req)
    direct.handle_request.assert_called_once_with(req)


def test_certificate_failures_are_never_bypassed(monkeypatch):
    factory = Mock()
    factory.return_value.handle_request.side_effect = httpx.ConnectError('CERTIFICATE_VERIFY_FAILED')
    monkeypatch.setattr(artwork.httpx, 'HTTPTransport', factory)
    with artwork.GitHubArtworkTransport('http://proxy.example:3128') as client:
        with pytest.raises(httpx.ConnectError):
            client.handle_request(request())
    assert factory.call_count == 1


def test_failed_proxy_cools_down_before_another_probe(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(artwork.time, 'monotonic', lambda: now[0])
    proxy, direct = Mock(), Mock()
    proxy.handle_request.side_effect = [httpx.ConnectError('EOF'), httpx.Response(200)]
    direct.handle_request.return_value = httpx.Response(200)
    monkeypatch.setattr(artwork.httpx, 'HTTPTransport', Mock(side_effect=[proxy, direct]))
    with artwork.GitHubArtworkTransport('http://proxy.example:3128') as client:
        client.handle_request(request())
        client.handle_request(request())
        assert proxy.handle_request.call_count == 1
        assert direct.handle_request.call_count == 2
        now[0] = 161.0
        client.handle_request(request())
        assert proxy.handle_request.call_count == 2
