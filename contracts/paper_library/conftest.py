import pytest

from contracts.paper_library.support import PaperRig


@pytest.fixture
def rig(tmp_path):
    r = PaperRig(tmp_path)
    try:
        yield r
    finally:
        r.close()
