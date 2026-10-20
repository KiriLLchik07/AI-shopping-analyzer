import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

TESTS_ROOT = Path(__file__).resolve().parent
load_dotenv(TESTS_ROOT / ".env.test", override=True)


def pytest_collection_modifyitems(items):
    for item in items:
        for marker, flag in (("ocr", "RUN_OCR_TESTS"), ("llm", "RUN_LLM_TESTS")):
            if item.get_closest_marker(marker) is not None and os.getenv(flag) != "1":
                item.add_marker(
                    pytest.mark.skip(
                        reason=f"Set {flag}=1 to run real local {marker.upper()}"
                    )
                )
