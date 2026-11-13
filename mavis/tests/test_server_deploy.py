"""The server install: no desktop-only packages, and the API runs on
exactly what requirements-server.txt installs -- nothing else from the
dev venv."""
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

MAVIS = Path(__file__).resolve().parents[1]
DESKTOP = ("panda3d", "openwakeword", "sounddevice", "opencv", "mcp")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _server_reqs() -> list[str]:
    lines = [l.split("#")[0].strip() for l in
             (MAVIS / "requirements-server.txt").read_text().splitlines()]
    return [l for l in lines if l and not l.startswith("-")]


def _closure() -> set[str]:
    """Every distribution requirements-server.txt pulls in (markers ignored,
    so this errs on the side of allowing)."""
    stack = []
    for req in _server_reqs():
        m = re.match(r"([A-Za-z0-9_.-]+)(?:\[([^\]]*)\])?", req)
        stack.append((_norm(m.group(1)), {e.strip() for e in (m.group(2) or "").split(",") if e}))
    seen: set[str] = set()
    while stack:
        name, extras = stack.pop()
        if name in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen.add(name)
        for r in dist.requires or []:
            extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", r)
            if extra and extra.group(1) not in extras:
                continue
            dep = re.match(r"([A-Za-z0-9_.-]+)(?:\[([^\]]*)\])?", r)
            stack.append((_norm(dep.group(1)),
                          {e.strip() for e in (dep.group(2) or "").split(",") if e}))
    return seen


def _blocked_modules() -> list[str]:
    """Top-level modules installed in this venv by packages the server won't have."""
    allowed = _closure()
    blocked = set()
    for module, dists in metadata.packages_distributions().items():
        if not any(_norm(d) in allowed for d in dists):
            blocked.add(module)
    return sorted(blocked)


def test_requirements_server_has_no_desktop_deps():
    pkgs = [p.lower() for p in _server_reqs()]
    assert not [p for p in pkgs if p.startswith(DESKTOP)]
    for need in ("fastapi", "uvicorn", "httpx", "numpy", "kokoro-onnx", "scipy"):
        assert any(p.startswith(need) for p in pkgs), need
    assert all("==" in p for p in pkgs)    # pinned


def test_server_imports_with_only_server_requirements():
    blocked = _blocked_modules()
    assert "panda3d" in blocked and "cv2" in blocked    # the blocker is live
    code = f"""
import sys, importlib.abc
BLOCK = set({blocked!r})
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in BLOCK:
            raise ModuleNotFoundError("not in requirements-server.txt: " + name, name=name)
sys.meta_path.insert(0, Blocker())
import app, call_route, alerts, graywind_grounding, jobs
import avatar.tts
print("ok")
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=MAVIS, capture_output=True,
                         text=True, timeout=120, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok")
