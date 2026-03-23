import pytest
from pathlib import Path

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path

@pytest.fixture
def base_dir():
    return Path(__file__).resolve().parent.parent