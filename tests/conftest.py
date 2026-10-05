import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


@pytest.fixture
def v2_data(tmp_path):
    """一份 v2 格式資料夾的複本。"""
    target = tmp_path / "timemanager_data"
    shutil.copytree(os.path.join(FIXTURES, "v2"), target)
    return str(target)
