"""Contract tests for the Bot Screen desktop packages baked into the Docker image.

Hosted deployments cannot install them at runtime: supervised services drop to the
unprivileged ``hermes`` user, the image ships no ``sudo``, and /opt/hermes is sealed.
The image layer is the only delivery path, so these tests guard it against drift.

Delivery is the ``HERMES_BOT_DESKTOP`` build arg, set to 1 by .github/workflows/docker.yml.
That split matters: hosted sandboxes (Fly Machines, Azure container instances) *pull* a
prebuilt image and never run a build, so the arg can only ever be set by our own pipeline,
never by the deployment — which is why the workflow is under test here too.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.bot_desktop import runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker.yml"


def _desktop_packages_in_dockerfile() -> set[str]:
    """Package names from the Bot Screen apt layer, as the Dockerfile lists them."""
    text = DOCKERFILE.read_text()
    marker = "ARG HERMES_BOT_DESKTOP"
    assert marker in text, "the Bot Screen apt layer is gone from the Dockerfile"
    layer = text.split(marker, 1)[1]
    body = layer.split("--no-install-recommends", 1)[1].split("rm -rf", 1)[0]
    return {tok for tok in re.split(r"[\s\\&]+", body) if tok and not tok.startswith("-")}


def test_desktop_layer_installs_an_x_server_and_a_window_manager() -> None:
    packages = _desktop_packages_in_dockerfile()
    # Xvnc renders to memory and needs no privileged device access, which is what
    # makes the screen runnable as UID 10000 once the binaries are present.
    assert "tigervnc-standalone-server" in packages
    assert "xfwm4" in packages
    # dbus-x11 ships dbus-run-session, which the launcher wraps the session in.
    assert "dbus-x11" in packages
    # The xfce4 metapackage would drag in a screensaver, a power manager and a
    # polkit agent, none of which mean anything on a headless desktop.
    assert "xfce4" not in packages


def test_the_desktop_packages_are_installed_exactly_once() -> None:
    """One install site, and it is the opt-in one.

    A second unconditional layer silently defeats HERMES_BOT_DESKTOP: every build then carries the
    packages whatever the arg says, and the two lists drift apart independently.
    """
    text = DOCKERFILE.read_text()
    sites = text.count("tigervnc-standalone-server")
    assert sites == 1, f"the desktop packages are installed at {sites} sites in the Dockerfile, expected 1"


def test_published_image_has_the_desktop_packages_enabled() -> None:
    """The arg is a switch for whoever runs the build. Fly/Azure sandboxes pull a prebuilt image and never
    build, so if the workflow stops passing it the published image silently loses Bot Screen."""
    text = WORKFLOW.read_text()
    build_sites = text.count("build-args: |")
    assert build_sites, "docker.yml no longer passes build args"
    assert text.count("HERMES_BOT_DESKTOP=1") == build_sites, \
        "every image build must enable the desktop packages, or hosted instances cannot start a screen"


def test_image_ships_a_headed_chromium_not_only_the_headless_shell() -> None:
    text = DOCKERFILE.read_text()
    # chrome-headless-shell can drive pages but cannot open a window, so a human
    # who takes over the screen would have no browser to log in with.
    assert "npx playwright install --with-deps chromium --only-shell" in text
    assert re.search(r"npx playwright install --with-deps chromium\s*&&", text), \
        "the full headed chromium build is no longer installed"


def test_container_gets_an_xdg_runtime_dir_outside_the_data_volume() -> None:
    text = DOCKERFILE.read_text()
    match = re.search(r"^ENV XDG_RUNTIME_DIR=(\S+)$", text, re.MULTILINE)
    assert match, "XDG_RUNTIME_DIR is unset; Xfce and the display-alloc lock fall back to $HOME/.cache"
    # $HERMES_HOME is commonly bind-mounted and sometimes shared with a host-side
    # install: two instances would then contend for one display-allocation lock.
    assert not match.group(1).startswith("/opt/data")


def test_the_runtime_dir_is_created_with_an_owner_and_a_symlink_guard() -> None:
    """It sits in world-writable sticky /tmp under a predictable name and holds the display-allocation
    lock, so stage2 must own it rather than inherit whatever is already there."""
    hook = (REPO_ROOT / "docker" / "stage2-hook.sh").read_text()
    block = hook.split("# --- XDG_RUNTIME_DIR ---", 1)[1].split("# --- Install-method stamp", 1)[0]
    assert "refuse_symlinked_path" in block, "a root chmod through a planted symlink retargets its victim"
    assert "chown hermes:hermes" in block, "a HERMES_UID remap otherwise leaves it owned by the old uid"
    assert "chmod 0700" in block


def test_dockerfile_package_list_matches_the_runtime_install_command() -> None:
    """The baked list must stay identical to what a self-hosted operator would install."""
    baked = _desktop_packages_in_dockerfile()
    required = set(runtime.PACKAGES["apt"])
    assert required <= baked, f"the image would not install: {sorted(required - baked)}"
    # The image adds apt `chromium` on top of the operator's list: the dock's Browser icon needs a headed
    # browser present even before Playwright's copy is discovered.
    assert baked - required <= {"chromium"}, f"unexpected extra packages: {sorted(baked - required)}"


def test_every_required_binary_is_covered_by_a_baked_package() -> None:
    baked = _desktop_packages_in_dockerfile()
    missing = {
        binary: pkg
        for binary, pkg in runtime.BINARY_PACKAGES["apt"].items()
        if pkg not in baked
    }
    assert not missing, f"binaries the image would still be missing at runtime: {missing}"
