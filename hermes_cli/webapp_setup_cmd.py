"""``hermes webapp --lan | --public-url URL``: make the Webapp reachable from other devices, behind a sign-in.

Configures the gateway's home (its ``webapp:`` block, the public URL, Nous sign-in or a password)
through :mod:`hermes_cli.webapp_access`, the same functions Desktop's Web Access pane calls. The
gateway reads that config when it starts: a stopped one picks it up when ``hermes webapp`` starts
it, and a running one needs a restart.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path


class SetupFailed(Exception):
    """Setup stopped; ``str(exc)`` is the user-facing reason."""


def _prompt_password() -> tuple[str, str]:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SetupFailed("Setting a password needs an interactive terminal.")
    from hermes_cli.cli_output import line_input

    try:
        username = line_input("  Username [admin]: ").strip() or "admin"
        password = getpass.getpass("  Password: ")
        confirm = getpass.getpass("  Confirm password: ")
    except (EOFError, KeyboardInterrupt):
        raise SetupFailed("Cancelled.") from None
    if not password:
        raise SetupFailed("Empty password — aborting.")
    if password != confirm:
        raise SetupFailed("Passwords don't match — aborting.")
    return username, password


def set_up_access(args, home: Path, target: Path) -> None:
    """Write the remote-access config for the gateway at *target*; raises SetupFailed."""
    from hermes_cli.dashboard_auth_setup import save_basic_auth
    from hermes_cli.webapp_access import WebappAccessError, plan_access, prepare, sign_in_methods
    from hermes_constants import profile_name_for_home

    if home.resolve() != target.resolve():
        # Another profile's gateway serves this one, and the Webapp's settings are that gateway's.
        name = profile_name_for_home(target)
        selector = f"-p {name} " if name and name != "default" else ""
        raise SetupFailed(f"The gateway of another profile serves this one. Set up its Webapp: hermes {selector}webapp "
                          + ("--lan" if args.lan else f"--public-url {args.public_url}"))

    mode = "public" if args.public_url else "lan"
    try:
        plan = plan_access(mode, port=args.port, public_url=args.public_url)
    except WebappAccessError as exc:
        raise SetupFailed(str(exc)) from exc

    auth = args.auth or ("" if any(sign_in_methods().values()) else "nous")
    if auth == "password":
        if mode == "public":
            raise SetupFailed("Use Nous sign-in (--auth nous) for a public URL; a shared password is for a "
                              "trusted network only.")
        username, password = _prompt_password()
        if save_basic_auth(username, password):
            print("  ✓ Re-enabled the bundled 'basic' auth plugin (was in plugins.disabled)")
    try:
        methods = prepare(plan, enable_nous=auth == "nous", name=args.name)
    except WebappAccessError as exc:
        raise SetupFailed(str(exc)) from exc

    print(f"✓ The Webapp will serve {'your network' if mode == 'lan' else plan.public_url}.")
    if methods["nous"]:
        print("  Sign-in: your Nous account")
    if methods["password"]:
        print(f"  Sign-in: password (user {methods['password']})")
        if mode == "public":
            print("  ⚠ Password sign-in is also on for this public URL. Remove it with "
                  "`hermes config set dashboard.basic_auth.password_hash ''` if you only want Nous.")
    if mode == "public":
        print(f"  Point your HTTPS proxy or tunnel for {plan.public_url} at http://127.0.0.1:{plan.port}")
    print(f"  Open: {plan.url}")
