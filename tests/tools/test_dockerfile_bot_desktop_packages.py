"""Parity between the packages the image bakes and the ones the runtime would install by hand.

Hosted deployments cannot install at runtime: supervised services drop to the unprivileged ``hermes``
user, the image ships no ``sudo``, and /opt/hermes is sealed. The image layer is the only delivery path,
so the baked list drifting from ``PACKAGES``/``BINARY_PACKAGES`` would strand the feature with no error
until someone pressed Start.

These read the Dockerfile only to recover that list; the assertions themselves are data-to-data. Whether
the layers are wired up correctly is the image build's job (``tests/docker/``), not a regex here — a
source-text assertion passes on a mis-wired build and fails on a correct refactor.
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


def test_dockerfile_package_list_matches_the_runtime_install_command() -> None:
    """The baked list must stay identical to what a self-hosted operator would install."""
    baked = _desktop_packages_in_dockerfile()
    required = set(runtime.PACKAGES["apt"])
    assert required <= baked, f"the image would not install: {sorted(required - baked)}"
    # The image adds apt `chromium` on top of the operator's list: a headed browser for the dock's
    # Browser icon that does not depend on Playwright's copy being unpacked yet.
    assert baked - required <= {"chromium"}, f"unexpected extra packages: {sorted(baked - required)}"


def test_every_required_binary_is_covered_by_a_baked_package() -> None:
    baked = _desktop_packages_in_dockerfile()
    missing = {
        binary: pkg
        for binary, pkg in runtime.BINARY_PACKAGES["apt"].items()
        if pkg not in baked
    }
    assert not missing, f"binaries the image would still be missing at runtime: {missing}"


def test_published_image_enables_the_desktop_build_argument() -> None:
    """The one wiring fact no image build can check for us.

    Fly Machines and Azure container instances pull a prebuilt image and never run a build, so the
    argument can only ever be set by this workflow. If it stops being passed, every published image
    silently loses Bot Screen, and the only symptom is "Install on host" on a host that cannot install.
    """
    text = WORKFLOW.read_text()
    build_sites = text.count("build-args: |")
    assert build_sites, "docker.yml no longer passes build args"
    assert text.count("HERMES_BOT_DESKTOP=1") == build_sites, \
        "every image build must enable the desktop packages, or hosted instances cannot start a screen"
