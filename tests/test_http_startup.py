"""Loopback services must not wait on system reverse DNS just to expose a port."""
from rsi_red.kanban import make_server


def test_dashboard_startup_does_not_query_reverse_dns(monkeypatch):
    def no_dns(*args):
        raise AssertionError('Reverse DNS must not be used for loopback readiness')
    monkeypatch.setattr('socket.getfqdn', no_dns)
    server = make_server(port=0, demo=True, endpoint='http://127.0.0.1:1', token='fixture')
    try:
        assert server.server_address[0] == '127.0.0.1'
        assert server.server_port > 0
    finally:
        server.server_close()
