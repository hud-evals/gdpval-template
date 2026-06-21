"""Shared fixtures. The ``runtime`` fixture picks a placement provider:
--url (attach) > --image (fresh container) > LocalRuntime (serve from source)."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_addoption(parser):
    parser.addoption("--image", default=None, help="Docker image to serve the env from")
    parser.addoption("--url", default=None, help="tcp:// url of an already-served env")


@pytest.fixture(scope="session")
def runtime(request):
    """A v6 placement provider: --url (attach) > --image (container) > LocalRuntime."""
    from hud import DockerRuntime, LocalRuntime, Runtime

    url = request.config.getoption("--url")
    if url:
        return Runtime(url)
    image = request.config.getoption("--image")
    if image:
        return DockerRuntime(image)
    return LocalRuntime(str(PROJECT_ROOT / "tasks.py"))
