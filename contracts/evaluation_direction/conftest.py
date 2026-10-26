import pytest

from tests.support import Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path).setup()
    try:
        yield r
    finally:
        r.close()
