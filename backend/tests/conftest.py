import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

TESTS_ROOT = Path(__file__).resolve().parent
load_dotenv(TESTS_ROOT / ".env.test", override=True)


def pytest_collection_modifyitems(items):
    if os.getenv("RUN_OCR_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="Set RUN_OCR_TESTS=1 to run real local OCR")
    for item in items:
        if item.get_closest_marker("ocr") is not None:
            item.add_marker(skip)
