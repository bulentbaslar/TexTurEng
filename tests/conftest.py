import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep tests away from the real %APPDATA%\\Textureng folder."""
    monkeypatch.setenv("TEXTURENG_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def cfg():
    from textureng.config import Config

    return Config()
