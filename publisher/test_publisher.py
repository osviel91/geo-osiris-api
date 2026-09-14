"""Publisher unit tests: no network beyond a local stdlib HTTP stub."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import publisher

UUID = "00000000-0000-0000-0000-0000000000ab"
TOKEN = "publish-token-value"


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        server = self.server
        length = int(self.headers.get("Content-Length") or 0)
        server.requests.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": self.rfile.read(length),
            }
        )
        if server.delay:
            time.sleep(server.delay)
        self.send_response(server.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(server.body).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def stub():
    servers = []

    def start(status=200, body=None, delay=0.0):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        httpd.status = status
        httpd.body = (
            body
            if body is not None
            else {"id": UUID, "committed_at": "2026-01-01T00:00:00Z"}
        )
        httpd.delay = delay
        httpd.requests = []
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}", httpd

    yield start
    for httpd in servers:
        httpd.shutdown()


def test_execute_success(stub):
    url, server = stub()
    result = publisher.execute(UUID, api_url=url, token=TOKEN)
    assert result == {
        "import_id": UUID,
        "status": "executed",
        "committed_at": "2026-01-01T00:00:00Z",
        "approval_state": "executed",
    }
    assert server.requests[0]["path"] == f"/api/v1/admin/imports/{UUID}/commit"
    assert server.requests[0]["body"] == b"{}"
    assert server.requests[0]["auth"] == f"Bearer {TOKEN}"


def test_execute_rejects_non_uuid(stub):
    url, server = stub()
    with pytest.raises(publisher.PublisherError):
        publisher.execute("not-a-uuid", api_url=url, token=TOKEN)
    assert server.requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "publisher authentication failure"),
        (403, "publisher lacks required scope"),
        (404, "import not found"),
        (422, "invalid request"),
    ],
)
def test_http_status_mapping(stub, status, message):
    url, _ = stub(status=status, body={"detail": "backend"})
    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(UUID, api_url=url, token=TOKEN)
    assert error.value.http_status == status
    assert error.value.message == message


@pytest.mark.parametrize(
    "detail",
    [
        "No active approval request",
        "Approval is stale",
        "Approval has expired",
        "Import is no longer pending",
        "Approval has already been decided",
    ],
)
def test_conflict_detail_preserved(stub, detail):
    url, _ = stub(status=409, body={"detail": detail})
    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(UUID, api_url=url, token=TOKEN)
    assert error.value.http_status == 409
    assert error.value.message == "approval or import is not executable"
    assert error.value.detail == detail


def test_timeout_is_reported(stub):
    url, _ = stub(delay=0.5)
    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(UUID, api_url=url, token=TOKEN, timeout=0.05)
    assert error.value.message == "Geo Hub is unreachable"


def test_unreachable_api():
    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(UUID, api_url="http://127.0.0.1:1", token=TOKEN, timeout=0.2)
    assert error.value.message == "Geo Hub is unreachable"


def test_no_automatic_retries(stub):
    url, server = stub(status=409, body={"detail": "Approval is stale"})
    with pytest.raises(publisher.PublisherError):
        publisher.execute(UUID, api_url=url, token=TOKEN)
    assert len(server.requests) == 1


def test_main_requires_configuration(monkeypatch, capsys):
    monkeypatch.delenv("GEO_API_URL", raising=False)
    monkeypatch.delenv("GEO_PUBLISH_TOKEN", raising=False)
    assert publisher.main([UUID]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert "GEO_API_URL" in output["error"]


def test_main_success(monkeypatch, capsys, stub):
    url, _ = stub()
    monkeypatch.setenv("GEO_API_URL", url)
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", TOKEN)
    assert publisher.main([UUID]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "executed"


def test_main_rejects_bad_uuid(monkeypatch, capsys):
    monkeypatch.setenv("GEO_API_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", TOKEN)
    assert publisher.main(["nope"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_secret_never_appears_in_output(monkeypatch, capsys, stub):
    url, _ = stub(status=403, body={"detail": "Insufficient scope"})
    secret = "SUPER-SECRET-PUBLISH-TOKEN"
    monkeypatch.setenv("GEO_API_URL", url)
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", secret)
    assert publisher.main([UUID]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
