from __future__ import annotations

import pytest
from helpers import eml, run_sync

from rfq.pipeline import RunResult


@pytest.fixture
def offline_run(tmp_path):
    def _run(name: str, **kwargs) -> RunResult:
        return run_sync(tmp_path / name, eml(name), **kwargs)
    return _run
