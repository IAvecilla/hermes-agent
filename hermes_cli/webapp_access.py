"""Remote access to the gateway-served Webapp: plan, configure and report.

One owner for "make the Webapp reachable from other devices, behind a sign-in", shared by
``hermes webapp --lan|--public-url`` and Desktop's Web Access pane. The gateway serves the Webapp
(``gateway.webapp_listener``) from the ``webapp:`` block of its home's ``config.yaml``, read when it
starts, so everything here writes that home's config and the caller restarts the gateway. Two shapes:

- ``lan``: ``webapp.host: 0.0.0.0``, opened at ``http://<this machine's LAN address>:<port>``. A
  wildcard bind engages the dashboard sign-in gate; ``dashboard.public_url`` is cleared, so the
  server rebuilds its OAuth callback from each request and the portal is told the LAN callback.
- ``public``: the operator already has an HTTPS URL (reverse proxy, Tailscale Serve, a tunnel) that
  forwards to ``127.0.0.1:<port>``. ``dashboard.public_url`` is pinned to it, which engages the
  sign-in gate on the loopback bind and fixes the OAuth callback.

The sign-in itself is the dashboard's: Nous OAuth (a self-hosted portal client) or the bundled
username/password provider. Nothing here can turn the gate off: :func:`prepare` refuses without a
provider, and the gateway keeps the Webapp off rather than serve a gated host without one.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from gateway.webapp_listener import DEFAULT_PORT

MODES = ("lan", "public")
_LAN_BIND = "0.0.0.0"
_LOOPBACK_BIND = "127.0.0.1"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_PUBLIC_URL_ENV = "HERMES_DASHBOARD_PUBLIC_URL"
_CLIENT_ID_ENV = "HERMES_DASHBOARD_OAUTH_CLIENT_ID"


class WebappAccessError(RuntimeError):
    """Remote access cannot be set up as asked; ``str(exc)`` is the user-facing reason."""


@dataclass(frozen=True)
class AccessPlan:
    mode: str
    port: int
    bind_host: str
    url: str  # what the user opens
    callback_url: str  # registered with the portal for Nous sign-in
    public_url: str  # pinned dashboard.public_url ("" for lan)


def lan_address() -> Optional[str]:
    """This machine's primary LAN IPv4 address, or None when it has none.

    Connecting a UDP socket only asks the kernel which interface would route to a
    non-local address; no packet is sent, so this works offline on a LAN too.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def normalize_public_url(raw: str) -> str:
    """``https://host[:port][/prefix]`` without a trailing slash, or WebappAccessError."""
    value = (raw or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise WebappAccessError("The public URL must start with https:// and name a host.")
    if parsed.hostname in _LOOPBACK_HOSTS:
        raise WebappAccessError("The public URL must be the address other devices use, not localhost.")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise WebappAccessError("The public URL cannot carry credentials, a query or a fragment.")
    return value


def plan_access(mode: str, *, port: int = DEFAULT_PORT, public_url: Optional[str] = None) -> AccessPlan:
    """Resolve *mode* into the bind, the URL to open and the OAuth callback."""
    if mode not in MODES:
        raise WebappAccessError(f"Unknown access mode {mode!r}; expected one of {', '.join(MODES)}.")
    if not 1 <= int(port) <= 65535:
        raise WebappAccessError("The port must be between 1 and 65535.")
    if mode == "lan":
        address = lan_address()
        if address is None:
            raise WebappAccessError("This machine has no network address other devices can reach.")
        url = f"http://{address}:{port}"
        return AccessPlan(mode, port, _LAN_BIND, url, f"{url}/auth/callback", "")
    url = normalize_public_url(public_url or "")
    return AccessPlan(mode, port, _LOOPBACK_BIND, url, f"{url}/auth/callback", url)


def gateway_home() -> Path:
    """The home whose gateway serves the current one: its config holds the Webapp's settings and
    sign-in, so every read and write here belongs there."""
    from hermes_cli.webapp_launcher import _gateway_home
    from hermes_constants import get_hermes_home

    return _gateway_home(get_hermes_home())


def _env(key: str) -> str:
    from hermes_cli.config import load_env

    return str(load_env().get(key) or "").strip()


def _dashboard_section() -> dict:
    from hermes_cli.config import load_config

    section = load_config().get("dashboard")
    return section if isinstance(section, dict) else {}


def configured_public_url() -> str:
    from hermes_cli.dashboard_auth.prefix import _normalise_public_url

    return _normalise_public_url(_env(_PUBLIC_URL_ENV) or str(_dashboard_section().get("public_url") or ""))


def sign_in_methods() -> dict:
    """Configured logins for this home: ``{"nous": client_id or "", "password": username or ""}``."""
    section = _dashboard_section()
    oauth = section.get("oauth") if isinstance(section.get("oauth"), dict) else {}
    basic = section.get("basic_auth") if isinstance(section.get("basic_auth"), dict) else {}
    has_password = bool(str(basic.get("password_hash") or basic.get("password") or "").strip())
    return {
        "nous": _env(_CLIENT_ID_ENV) or str(oauth.get("client_id") or "").strip(),
        "password": str(basic.get("username") or "").strip() if has_password else "",
    }


def _write_webapp_config(plan: Optional[AccessPlan]) -> None:
    """Serve *plan* (or turn the Webapp off) from the next gateway start.

    ``dashboard.public_url`` is the plan's; a ``.env`` copy would shadow it (env wins) and outlive a
    switch back to the network, so it goes. Turning the Webapp off leaves the public URL alone.
    """
    from hermes_cli.config import load_config, remove_env_value, save_config

    cfg = load_config()
    webapp = cfg.get("webapp") if isinstance(cfg.get("webapp"), dict) else {}
    if plan is None:
        webapp["enabled"] = False
    else:
        webapp.update(enabled=True, host=plan.bind_host, port=plan.port)
        dashboard = cfg.setdefault("dashboard", {})
        if plan.public_url:
            dashboard["public_url"] = plan.public_url
        else:
            dashboard.pop("public_url", None)
    cfg["webapp"] = webapp
    save_config(cfg)
    if plan is not None and _env(_PUBLIC_URL_ENV):
        remove_env_value(_PUBLIC_URL_ENV)


def register_nous_sign_in(plan: AccessPlan, *, name: Optional[str] = None):
    """Register or update this home's portal client with *plan*'s callback."""
    from hermes_cli.dashboard_register import DashboardRegisterError, register_dashboard_client

    try:
        return register_dashboard_client(name=name, redirect_uri=plan.callback_url, write_public_url=False)
    except DashboardRegisterError as exc:
        raise WebappAccessError(str(exc)) from exc


def remove_nous_sign_in() -> None:
    """Forget the portal client locally; revoke it at the portal's Local Dashboards page."""
    from hermes_cli.config import remove_env_value

    remove_env_value(_CLIENT_ID_ENV)


def prepare(plan: AccessPlan, *, enable_nous: bool = False, name: Optional[str] = None) -> dict:
    """Make this home's gateway serve *plan* from its next start; returns the accepted sign-ins.

    Nous sign-in (already configured, or turned on with *enable_nous*) is registered with this
    plan's callback first — idempotent, so it follows a changed LAN address or URL — and the
    ``webapp:`` block is written last, so a failed registration leaves the config as it was.
    Refuses when no login is configured: the gateway would keep the Webapp off.
    """
    methods = sign_in_methods()
    nous = enable_nous or bool(methods["nous"])
    if not (nous or methods["password"]):
        raise WebappAccessError("Set up a sign-in method (Nous account or password) first.")
    if plan.mode == "public" and not nous:
        raise WebappAccessError(
            "Your own URL needs Nous sign-in. A password alone is for a network you trust.")
    if nous:
        register_nous_sign_in(plan, name=name)
    _write_webapp_config(plan)
    return sign_in_methods()


def turn_off() -> None:
    """Stop serving the Webapp from the gateway's next start."""
    _write_webapp_config(None)


def gateway_state(home: Path) -> dict:
    """What *home*'s gateway serves now: ``state`` is ``serving``, ``off``, ``unavailable`` (with a
    ``reason``) or ``stopped`` when no gateway answers. The Webapp settings apply at its start, so
    this can lag the config until the gateway restarts."""
    from hermes_cli.webapp_launcher import GatewayUnreachable, _control

    try:
        response = _control(home, "webapp-status")
    except GatewayUnreachable:
        return {"state": "stopped", "url": None, "reason": None}
    if not response.get("ok"):
        return {"state": "unavailable", "url": None, "reason": str(response.get("error") or "")}
    return dict(response["result"])


def access_status() -> dict:
    """Everything the Web Access pane shows, read for the gateway home in scope."""
    from gateway.webapp_listener import _is_wildcard, webapp_settings

    home = gateway_home()
    settings = webapp_settings(home)
    public_url = configured_public_url()
    mode = None
    if settings.enabled:
        mode = "lan" if _is_wildcard(settings.host) else "public" if public_url else "local"
    methods = sign_in_methods()
    return {
        "enabled": settings.enabled,
        "mode": mode,
        "port": settings.port,
        "gateway": gateway_state(home),
        "lan_address": lan_address(),
        "public_url": public_url,
        "nous_client_id": methods["nous"],
        "password_username": methods["password"],
        "default_port": DEFAULT_PORT,
    }
