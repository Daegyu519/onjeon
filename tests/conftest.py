import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str):
        path = FIXTURES / name
        if name.endswith(".json"):
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")

    return _load
