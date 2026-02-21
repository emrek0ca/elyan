"""Local pytest helpers for async tests when pytest-asyncio is unavailable."""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

# Ensure workspace source tree wins over stale site-packages copies.
ROOT = Path(__file__).resolve().parents[1]
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async coroutine")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
        if name in pyfuncitem.funcargs
    }
    asyncio.run(test_func(**kwargs))
    return True
