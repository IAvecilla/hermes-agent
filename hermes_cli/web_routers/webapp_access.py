"""Web Access routes: Desktop's Web Access pane drives remote Webapp access here.

Thin HTTP over :mod:`hermes_cli.webapp_access` (``hermes webapp --lan|--public-url`` uses the same
functions). The gateway serves the Webapp, so every handler acts on the home of the gateway that
serves the requested profile. Start and stop write its ``webapp:`` config and restart that gateway,
which reads the config only when it starts.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes_cli import webapp_access
from hermes_cli.web_deps import late
from hermes_cli.web_routers._common import _profile_scope, config_write_scope, destructive_profile

_restart_gateway_after = late("_restart_gateway_after", "hermes_cli.web_server_gateway")

router = APIRouter()


class AccessPlanBody(BaseModel):
    mode: str
    port: int = webapp_access.DEFAULT_PORT
    public_url: Optional[str] = None


class PasswordBody(BaseModel):
    username: str
    password: str


@contextmanager
def _gateway_scope(profile: Optional[str], *, config_write: bool):
    """Scope to the home of the gateway serving *profile*; yields that gateway's profile name."""
    from hermes_constants import profile_name_for_home

    with _profile_scope(profile):
        name = profile_name_for_home(webapp_access.gateway_home()) or profile
    with config_write_scope(name) if config_write else _profile_scope(name):
        yield name


async def _scoped(profile: Optional[str], fn: Callable[[Optional[str]], Any], *, config_write: bool = False) -> Any:
    """Run ``fn(gateway profile)`` in the gateway's scope off the loop; access errors become 400s.

    Only a ``config.yaml`` read-modify-write takes the config mutation lock. Nous registration
    alone touches ``.env`` and may wait on the portal for seconds, which must not stall every
    other settings write.
    """

    def _run():
        with _gateway_scope(profile, config_write=config_write) as gateway_profile:
            return fn(gateway_profile)

    try:
        return await asyncio.to_thread(_run)
    except (webapp_access.WebappAccessError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _plan(body: AccessPlanBody) -> webapp_access.AccessPlan:
    return webapp_access.plan_access(body.mode, port=body.port, public_url=body.public_url)


def _restart(gateway_profile: Optional[str], what: str) -> dict:
    """The status after a gateway restart that applies the new ``webapp:`` config. A refused
    restart (live sessions) keeps the saved config and reports ``restart_error``."""
    restart = _restart_gateway_after(gateway_profile, what=what, label="Web Access")
    return {**webapp_access.access_status(), **restart}


@router.get("/api/webapp-access/status")
async def webapp_access_status(profile: Optional[str] = None):
    return await _scoped(profile, lambda _gateway: webapp_access.access_status())


@router.post("/api/webapp-access/password")
async def set_webapp_password(body: PasswordBody, profile: Optional[str] = None):
    from hermes_cli.dashboard_auth_setup import save_basic_auth

    profile = destructive_profile(profile, "POST /api/webapp-access/password")

    def _save(_gateway):
        save_basic_auth(body.username, body.password)
        return webapp_access.access_status()

    return await _scoped(profile, _save, config_write=True)


@router.delete("/api/webapp-access/password")
async def remove_webapp_password(profile: Optional[str] = None):
    from hermes_cli.dashboard_auth_setup import clear_basic_auth

    profile = destructive_profile(profile, "DELETE /api/webapp-access/password")

    def _clear(_gateway):
        clear_basic_auth()
        return webapp_access.access_status()

    return await _scoped(profile, _clear, config_write=True)


@router.post("/api/webapp-access/nous")
async def set_webapp_nous_sign_in(body: AccessPlanBody, profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/nous")

    def _register(_gateway):
        webapp_access.register_nous_sign_in(_plan(body))
        return webapp_access.access_status()

    return await _scoped(profile, _register)


@router.delete("/api/webapp-access/nous")
async def remove_webapp_nous_sign_in(profile: Optional[str] = None):
    profile = destructive_profile(profile, "DELETE /api/webapp-access/nous")

    def _remove(_gateway):
        webapp_access.remove_nous_sign_in()
        return webapp_access.access_status()

    return await _scoped(profile, _remove)


@router.post("/api/webapp-access/start")
async def start_webapp_access(body: AccessPlanBody, profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/start")

    def _start(gateway):
        webapp_access.prepare(_plan(body))
        return _restart(gateway, "turning on Web Access")

    return await _scoped(profile, _start, config_write=True)


@router.post("/api/webapp-access/stop")
async def stop_webapp_access(profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/webapp-access/stop")

    def _stop(gateway):
        webapp_access.turn_off()
        return _restart(gateway, "turning off Web Access")

    return await _scoped(profile, _stop, config_write=True)
