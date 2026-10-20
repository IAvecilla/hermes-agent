"""Remote Webapp access (``hermes_cli.webapp_access``, ``/api/webapp-access/*``).

Contracts: a public URL engages the sign-in gate on the gateway's loopback bind, LAN access
registers the LAN callback and unpins a public URL, and nothing is written or restarted while no
login is configured.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from hermes_cli import web_server

    c = TestClient(web_server.app, raise_server_exceptions=False)
    c.headers["Authorization"] = f"Bearer {web_server._SESSION_TOKEN}"
    return c


@pytest.fixture()
def restarts(monkeypatch):
    """Capture the gateway restart that applies the config instead of spawning it."""
    import hermes_cli.web_server_gateway as gw

    calls: list[str] = []

    def _restart(profile, *, what, label):
        calls.append(what)
        return {"restart_started": True}

    monkeypatch.setattr(gw, "_restart_gateway_after", _restart)
    return calls


@pytest.fixture()
def nous_client(monkeypatch):
    """A configured Nous sign-in; portal registration is stubbed (no network)."""
    from hermes_cli import dashboard_register
    from hermes_cli.config import save_env_value

    save_env_value("HERMES_DASHBOARD_OAUTH_CLIENT_ID", "agent:test-client")
    registered: list[dict] = []
    monkeypatch.setattr(
        dashboard_register, "register_dashboard_client", lambda **kw: registered.append(kw))
    return registered


def _config() -> dict:
    from hermes_cli.config import load_config

    return load_config()


def test_public_url_engages_the_sign_in_gate_on_the_loopback_bind(client, restarts, nous_client):
    from hermes_cli.web_server_boundary import _dashboard_public_hosts, listener_auth_required

    response = client.post(
        "/api/webapp-access/start",
        json={"mode": "public", "public_url": "https://hermes.example.test", "port": 9333})

    assert response.status_code == 200, response.text
    assert _config()["webapp"] == {"enabled": True, "host": "127.0.0.1", "port": 9333}
    assert restarts == ["turning on Web Access"]
    # What the restarted gateway decides for its listener (gateway.run_api.start_gateway_api).
    assert listener_auth_required("127.0.0.1", _dashboard_public_hosts())


def test_lan_access_registers_the_lan_callback_and_unpins_a_public_url(nous_client, monkeypatch):
    from hermes_cli import webapp_access
    from hermes_cli.config import load_env, save_config, save_env_value

    # A public URL from an earlier "own URL" setup, and an older .env pin that would shadow it.
    save_config({**_config(), "dashboard": {"public_url": "https://old.example.test"}})
    save_env_value("HERMES_DASHBOARD_PUBLIC_URL", "https://older.example.test")
    monkeypatch.setattr(webapp_access, "lan_address", lambda: "192.168.1.50")

    webapp_access.prepare(webapp_access.plan_access("lan", port=9120))

    assert [(r["redirect_uri"], r["write_public_url"]) for r in nous_client] == [
        ("http://192.168.1.50:9120/auth/callback", False)]
    assert _config()["webapp"]["host"] == "0.0.0.0"
    assert webapp_access.configured_public_url() == ""
    assert "HERMES_DASHBOARD_PUBLIC_URL" not in load_env()


@pytest.mark.parametrize("plan", [
    {"mode": "lan"},  # no login at all
    {"mode": "public", "public_url": "https://hermes.example.test"},  # a password alone: trusted networks only
])
def test_start_without_a_fitting_login_writes_and_restarts_nothing(client, restarts, monkeypatch, plan):
    from hermes_cli import webapp_access
    from hermes_cli.dashboard_auth_setup import save_basic_auth

    monkeypatch.setattr(webapp_access, "lan_address", lambda: "192.168.1.50")
    if plan["mode"] == "public":
        save_basic_auth("admin", "pw-for-test")
    response = client.post("/api/webapp-access/start", json=plan)

    assert response.status_code == 400
    assert restarts == []
    assert "webapp" not in _config() or not _config()["webapp"].get("enabled")


def test_privileged_routes_need_an_explicit_profile_when_serving_several(client, restarts, monkeypatch):
    from agent import secret_scope
    from hermes_cli.dashboard_auth_setup import save_basic_auth

    save_basic_auth("admin", "pw-for-test")
    monkeypatch.setattr(secret_scope, "is_multiplex_active", lambda: True)

    responses = [
        client.post("/api/webapp-access/start", json={"mode": "lan"}),
        client.post("/api/webapp-access/password", json={"username": "x", "password": "y"}),
        client.post("/api/webapp-access/stop"),
    ]

    assert [r.status_code for r in responses] == [400, 400, 400]
    assert restarts == []
