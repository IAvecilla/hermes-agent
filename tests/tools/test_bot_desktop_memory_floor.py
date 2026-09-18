"""Bot Desktop refuses to start when the instance has no headroom for it.

Measured in the official image: gateway idle 304 MiB, +216 for Xvnc/Xfce, +553 once the bot opens one
browser page (peak 1115 MiB). The OOM killer picks a victim by score, so on a small instance the casualty
is the dashboard or the gateway rather than the desktop that caused the pressure.

The gate lives in ``resources`` and ``start()`` is its only enforcement point, so the pane's reason and the
refusal cannot come from different code.
"""
from __future__ import annotations

import pytest

from tools.bot_desktop import resources, runtime

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """No env override, and never the developer's own ~/.hermes/config.yaml."""
    monkeypatch.delenv(resources.ENV_MIN_FREE_MB, raising=False)
    monkeypatch.setattr(resources, "_meminfo", lambda: {})
    monkeypatch.setattr("hermes_cli.config.load_config_readonly", lambda *a, **k: {})


def _running_linux_host(monkeypatch, tmp_path, *, running: bool = False):
    """A Linux host with the packages present, so only memory can block a start."""
    monkeypatch.setattr(runtime, "is_supported_host", lambda: True)
    monkeypatch.setattr(runtime, "missing_binaries", lambda: [])
    monkeypatch.setattr(runtime, "state_dir", lambda: tmp_path / "bd")
    monkeypatch.setattr(runtime, "_launcher_pid", lambda: 4242 if running else None)
    monkeypatch.setattr(runtime, "published_env", lambda: {"DISPLAY": ":7"} if running else {})
    monkeypatch.setattr(runtime, "_reap_orphaned_server", lambda sd: None)
    spawned: list = []
    monkeypatch.setattr(runtime, "_spawn_and_wait", lambda *a, **k: spawned.append(a) or "SPAWNED")
    return spawned


def _memory(monkeypatch, *, available_mb, limit_mb=4096):
    monkeypatch.setattr(resources, "memory_info",
                        lambda: resources.MemoryInfo(available_mb=available_mb, limit_mb=limit_mb))


def _write_cgroup_v2(root, *, limit: str, current: int, inactive_file: int | None = None) -> None:
    (root / "memory.max").write_text(limit, encoding="utf-8")
    (root / "memory.current").write_text(str(current), encoding="utf-8")
    if inactive_file is not None:
        (root / "memory.stat").write_text(f"anon 123\ninactive_file {inactive_file}\nslab 7\n", encoding="utf-8")


# ---- what "available" means ------------------------------------------------------------------------

def test_page_cache_does_not_count_against_the_limit(tmp_path, monkeypatch):
    """The regression this guards: a 4 GB instance idling at 643 MiB of mostly page cache must not read as
    643 MiB consumed. memory.current includes reclaimable cache, so charging it would make the check tighten
    the longer an instance stays up and refuse starts that would have been fine."""
    _write_cgroup_v2(tmp_path, limit=str(4096 * MB), current=643 * MB, inactive_file=340 * MB)
    monkeypatch.setattr(resources, "_CGROUP_V2", tmp_path)
    assert resources.memory_info().available_mb == 4096 - (643 - 340)


def test_page_cache_is_excluded_on_cgroup_v1_too(tmp_path, monkeypatch):
    (tmp_path / "memory.limit_in_bytes").write_text(str(4096 * MB), encoding="utf-8")
    (tmp_path / "memory.usage_in_bytes").write_text(str(643 * MB), encoding="utf-8")
    (tmp_path / "memory.stat").write_text(f"total_inactive_file {340 * MB}\n", encoding="utf-8")
    monkeypatch.setattr(resources, "_CGROUP_V2", tmp_path / "absent")
    monkeypatch.setattr(resources, "_CGROUP_V1", tmp_path)
    assert resources.memory_info().available_mb == 4096 - (643 - 340)


def test_unlimited_cgroup_falls_back_to_meminfo(tmp_path, monkeypatch):
    """`memory.max` = "max" means no container limit, so the host's own free memory is the real answer."""
    _write_cgroup_v2(tmp_path, limit="max", current=100 * MB)
    monkeypatch.setattr(resources, "_CGROUP_V2", tmp_path)
    monkeypatch.setattr(resources, "_meminfo", lambda: {"MemAvailable": 900 * MB, "MemTotal": 2048 * MB})
    info = resources.memory_info()
    assert info.available_mb == 900 and info.limit_mb == 2048


def test_a_limit_larger_than_the_machine_does_not_invent_headroom(tmp_path, monkeypatch):
    """"a limit of 8 GB on a 4 GB host is not 8 GB": available is the tighter of the two."""
    _write_cgroup_v2(tmp_path, limit=str(8192 * MB), current=100 * MB)
    monkeypatch.setattr(resources, "_CGROUP_V2", tmp_path)
    monkeypatch.setattr(resources, "_meminfo", lambda: {"MemAvailable": 500 * MB, "MemTotal": 4096 * MB})
    assert resources.memory_info().available_mb == 500


# ---- the gate --------------------------------------------------------------------------------------

def test_start_refuses_when_headroom_is_below_the_floor(tmp_path, monkeypatch):
    spawned = _running_linux_host(monkeypatch, tmp_path)
    _memory(monkeypatch, available_mb=900)
    with pytest.raises(RuntimeError) as excinfo:
        runtime.start()
    message = str(excinfo.value)
    assert "900 MB" in message and "1536 MB" in message
    assert "min_free_memory_mb" in message, "the message must name the knob that relaxes it"
    assert spawned == [], "the launcher must not be spawned on a host that cannot hold it"


def test_start_allows_a_host_with_headroom(tmp_path, monkeypatch):
    spawned = _running_linux_host(monkeypatch, tmp_path)
    _memory(monkeypatch, available_mb=4096)
    runtime.start()
    assert spawned, "a host with headroom starts"


def test_unmeasurable_host_is_never_blocked(tmp_path, monkeypatch):
    """A host where neither the cgroup nor /proc/meminfo is readable keeps today's behaviour."""
    spawned = _running_linux_host(monkeypatch, tmp_path)
    _memory(monkeypatch, available_mb=None, limit_mb=None)
    runtime.start()
    assert spawned


def test_a_running_desktop_is_never_refused_for_the_memory_it_is_using(tmp_path, monkeypatch):
    """start() is idempotent. The gate guards the allocation, not the session: a desktop that is already up
    is itself the thing consuming the memory, so checking before the running-check made Start fail on a
    perfectly healthy screen."""
    _running_linux_host(monkeypatch, tmp_path, running=True)
    _memory(monkeypatch, available_mb=400)
    assert runtime.status().blocker is None, "a running screen is never blocked"
    runtime.start()  # returns status(), does not raise


# ---- the floor -------------------------------------------------------------------------------------

def test_env_override_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv(resources.ENV_MIN_FREE_MB, "512")
    assert resources.min_free_mb() == 512
    spawned = _running_linux_host(monkeypatch, tmp_path)
    _memory(monkeypatch, available_mb=900)
    runtime.start()  # 900 clears a 512 floor
    assert spawned


def test_env_override_zero_disables_the_gate_end_to_end(tmp_path, monkeypatch):
    """config_defaults documents "0 disables the check", so it must disable it in start(), not merely in
    one of two gates that used to run there."""
    monkeypatch.setenv(resources.ENV_MIN_FREE_MB, "0")
    assert resources.min_free_mb() == 0
    spawned = _running_linux_host(monkeypatch, tmp_path)
    _memory(monkeypatch, available_mb=10)
    runtime.start()
    assert spawned, "the documented escape hatch must actually let a start through"


def test_a_non_numeric_override_falls_back_to_config(monkeypatch):
    monkeypatch.setenv(resources.ENV_MIN_FREE_MB, "lots")
    assert resources.min_free_mb() == resources.DEFAULT_MIN_FREE_MB


def test_tight_headroom_tracks_the_floor(monkeypatch):
    """The "starting, but it is tight" warning is derived from the floor, so raising the floor cannot
    silently retire it and lowering the floor cannot make it fire on every start."""
    monkeypatch.setenv(resources.ENV_MIN_FREE_MB, "3072")
    assert resources.tight_headroom_mb() > 3072
    monkeypatch.setenv(resources.ENV_MIN_FREE_MB, "512")
    assert resources.tight_headroom_mb() < 1536


# ---- install path ----------------------------------------------------------------------------------

def test_unprivileged_host_cannot_install(tmp_path, monkeypatch):
    """The published image: unprivileged, no sudo. The packages can only arrive in the image."""
    monkeypatch.setattr(runtime, "package_manager", lambda: "apt")
    monkeypatch.setattr(runtime, "is_root", lambda: False)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None if name == "sudo" else "/usr/bin/" + name)
    assert runtime.installable() is False

    _running_linux_host(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "missing_binaries", lambda: ["Xvnc"])
    with pytest.raises(RuntimeError, match="baked in"):
        runtime.start()
