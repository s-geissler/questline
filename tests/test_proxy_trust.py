import importlib
import sys

from starlette.requests import Request


def request_with_forwarded_for(client_host, forwarded_for):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", forwarded_for.encode("utf-8"))],
            "client": (client_host, 12345),
        }
    )


def load_main_with_trusted_proxies(tmp_path, monkeypatch, trusted_proxies):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUESTLINE_ENV", "development")
    monkeypatch.setenv("QUESTLINE_ALLOW_INSECURE_COOKIES", "true")
    monkeypatch.setenv("QUESTLINE_TRUSTED_PROXIES", trusted_proxies)

    for module_name in (
        "main",
        "models",
        "database",
        "authz",
        "filters_logic",
        "routes",
        "routes.auth",
        "routes.boards",
        "routes.stages",
        "routes._deps",
        "routes._helpers",
        "services",
        "services.audit",
        "services.settings",
        "services.tasks",
        "services.notifications",
        "services.automation",
        "services.recurrence",
    ):
        sys.modules.pop(module_name, None)

    return importlib.import_module("main")


def test_spoofed_forwarded_for_is_ignored_for_untrusted_peer(tmp_path, monkeypatch):
    main = load_main_with_trusted_proxies(tmp_path, monkeypatch, "127.0.0.1/32")

    request = request_with_forwarded_for("203.0.113.10", "198.51.100.42")

    assert main._request_client_ip(request) == "203.0.113.10"


def test_forwarded_for_is_used_for_trusted_peer(tmp_path, monkeypatch):
    main = load_main_with_trusted_proxies(tmp_path, monkeypatch, "127.0.0.1/32,10.0.0.0/8")

    request = request_with_forwarded_for("10.1.2.3", "198.51.100.42, 10.1.2.3")

    assert main._request_client_ip(request) == "198.51.100.42"


def test_invalid_forwarded_for_falls_back_to_proxy_peer(tmp_path, monkeypatch):
    main = load_main_with_trusted_proxies(tmp_path, monkeypatch, "10.0.0.0/8")

    request = request_with_forwarded_for("10.1.2.3", "not-an-ip")

    assert main._request_client_ip(request) == "10.1.2.3"


def test_invalid_trusted_proxy_config_fails_fast(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("QUESTLINE_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("QUESTLINE_ENV", "development")
    monkeypatch.setenv("QUESTLINE_ALLOW_INSECURE_COOKIES", "true")
    monkeypatch.setenv("QUESTLINE_TRUSTED_PROXIES", "not-a-network")

    for module_name in (
        "main",
        "models",
        "database",
        "authz",
        "filters_logic",
        "routes",
        "routes.auth",
        "routes.boards",
        "routes.stages",
        "routes._deps",
        "routes._helpers",
        "services",
        "services.audit",
        "services.settings",
        "services.tasks",
        "services.notifications",
        "services.automation",
        "services.recurrence",
    ):
        sys.modules.pop(module_name, None)

    try:
        importlib.import_module("main")
        assert False, "Expected invalid trusted proxy config to fail"
    except RuntimeError as exc:
        assert "QUESTLINE_TRUSTED_PROXIES" in str(exc)
