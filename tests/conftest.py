import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import app


@pytest.fixture(autouse=True)
def _seed_collections():
    app.MAIN_COLLECTION = "systems"
    app.PARTITIONING_PROPERTY = "system"
    app.COLLECTIONS.update({"systems", "schedules", "contacts"})
    yield
    app.MAIN_COLLECTION = None
    app.PARTITIONING_PROPERTY = None
    app.COLLECTIONS.difference_update({"systems", "schedules", "contacts"})
