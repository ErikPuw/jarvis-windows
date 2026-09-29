from urllib.error import HTTPError, URLError

from engine.server.telegram_bot import is_transient_polling_timeout


def _http(code: int) -> HTTPError:
    return HTTPError("https://api.telegram.org/x", code, "msg", {}, None)


def test_server_side_http_errors_are_transient():
    for code in (429, 500, 502, 503, 504):
        assert is_transient_polling_timeout(_http(code)), code


def test_client_http_errors_are_not_transient():
    for code in (400, 401, 404, 409):
        assert not is_transient_polling_timeout(_http(code)), code


def test_connection_errors_still_transient():
    assert is_transient_polling_timeout(TimeoutError())
    assert is_transient_polling_timeout(URLError(ConnectionResetError()))
    assert not is_transient_polling_timeout(ValueError())
