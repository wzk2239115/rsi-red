import pytest

from contracts.benchmark_runner.support import prepare
from tests.support import Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        yield prepare(r)
    finally:
        r.close()
