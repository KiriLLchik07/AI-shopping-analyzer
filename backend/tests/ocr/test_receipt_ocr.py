"""Постоянные OCR-фикстуры и проверки реальной модели, без БД и внешних API.

Из backend: RUN_OCR_TESTS=1 python -m pytest tests/ocr -m ocr -s
В PowerShell переменная задаётся отдельно: $env:RUN_OCR_TESTS='1'.
Нужны extra ocr-cpu и локальные веса из manifest; загрузка весов не выполняется.
Пороги фиксируют исходный уровень, включая ошибки порядка фрагментов SDK.
Это не независимая оценка качества на новых чеках.
"""

import hashlib
import json
import math
import os
import socket
import time
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from backend.tests.ocr.metrics import character_error_rate, normalize_text

DATASET_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "ocr" / "v1"
MANIFEST = json.loads((DATASET_ROOT / "manifest.json").read_text(encoding="utf-8"))
SAMPLES = MANIFEST["samples"]


def read_reference(sample):
    return (DATASET_ROOT / sample["expected_text"]).read_text(encoding="utf-8-sig")


def test_manifest_covers_all_fixture_pairs():
    assert MANIFEST["version"] == 1
    assert len(SAMPLES) >= 5
    assert len({sample["id"] for sample in SAMPLES}) == len(SAMPLES)
    assert {sample["image"] for sample in SAMPLES} == {
        p.relative_to(DATASET_ROOT).as_posix()
        for p in (DATASET_ROOT / "images").iterdir()
    }
    assert {sample["expected_text"] for sample in SAMPLES} == {
        p.relative_to(DATASET_ROOT).as_posix()
        for p in (DATASET_ROOT / "texts").iterdir()
    }
    evaluation = json.loads(
        (DATASET_ROOT / MANIFEST["preprocessing_evaluation"]).read_text(
            encoding="utf-8"
        )
    )
    assert evaluation["runtime"]["models"] == MANIFEST["runtime"]["models"]
    assert evaluation["fixture_fingerprints"] == [
        {key: sample[key] for key in ("id", "image_sha256", "expected_text_sha256")}
        for sample in SAMPLES
    ]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample["id"])
def test_reviewed_fixture_integrity(sample):
    image_path = DATASET_ROOT / sample["image"]
    text_path = DATASET_ROOT / sample["expected_text"]
    assert image_path.resolve().is_relative_to(DATASET_ROOT.resolve())
    assert text_path.resolve().is_relative_to(DATASET_ROOT.resolve())
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == sample["image_sha256"]
    reference = read_reference(sample)
    # Text hashes use decoded UTF-8 and LF, so Windows/Linux checkouts agree.
    assert (
        hashlib.sha256(reference.encode("utf-8")).hexdigest()
        == sample["expected_text_sha256"]
    )
    assert normalize_text(reference) and "\ufffd" not in reference
    with Image.open(image_path) as image:
        image.load()
        assert image.format == "JPEG" and image.mode == "RGB"
        assert image.size == tuple(sample["size"])
        assert not image.getexif()
        assert all(
            marker == "APP0"
            and data.startswith(b"JFIF\x00")
            and data[12:14] == b"\x00\x00"
            for marker, data in image.applist
        )
        assert not any(
            key in image.info for key in ("exif", "xmp", "photoshop", "comment")
        )
    assert 0 <= sample["baseline_cer"] < 1
    assert sample["expected_total"] in reference


@pytest.fixture(scope="session")
def real_ocr_provider():
    from backend.app.core.config import BACKEND_ROOT, OcrSettings
    from backend.app.ocr.paddle_provider import PaddleOcrProvider

    runtime = MANIFEST["runtime"]
    for package, expected in runtime["versions"].items():
        try:
            installed = version(package)
        except PackageNotFoundError:
            pytest.fail(f"Install the ocr-cpu extra: missing {package}")
        assert installed == expected, (
            f"{package}={installed}; baseline uses {expected}. Review before recalibrating."
        )
    model_dir = Path(
        os.getenv("OCR_TEST_MODEL_DIR", str(BACKEND_ROOT / "models" / "ocr"))
    )
    for model in runtime["models"]:
        for filename, expected in model["files_sha256"].items():
            path = model_dir / model["name"] / filename
            assert path.is_file(), (
                f"Missing local weight {path}; tests never download models"
            )
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, (
                f"Model differs from baseline: {path}"
            )
    return PaddleOcrProvider(
        config=OcrSettings(
            model_dir=model_dir,
            detection_model_name=runtime["models"][0]["name"],
            recognition_model_name=runtime["models"][1]["name"],
            model_files=tuple(runtime["models"][0]["files_sha256"]),
            device="cpu",
            cpu_threads=runtime["cpu_threads"],
            _env_file=None,
        )
    )


@pytest.fixture
def offline_ocr(monkeypatch):
    attempts = []

    def reject_network(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("Network connections are forbidden in OCR regression tests")

    monkeypatch.setenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    yield
    assert not attempts, (
        "OCR attempted a network connection, even if the SDK suppressed its error"
    )


@pytest.mark.ocr
@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample["id"])
def test_real_ocr_does_not_regress(
    sample, real_ocr_provider, offline_ocr, record_property
):
    started = time.perf_counter()
    # These fixtures are upright. Isolate OCR from orientation-model decisions.
    with (
        Image.open(DATASET_ROOT / sample["image"]) as original,
        ImageOps.exif_transpose(original) as oriented,
        oriented.convert("RGB") as rgb,
        BytesIO() as buffer,
    ):
        rgb.save(buffer, format="PNG")
        result = real_ocr_provider.recognize(buffer.getvalue())
    elapsed = time.perf_counter() - started
    assert result.raw_text.strip(), "OCR returned no readable text"
    assert result.confidence is not None and math.isfinite(result.confidence)
    assert 0 <= result.confidence <= 1
    cer = character_error_rate(read_reference(sample), result.raw_text)
    maximum = sample["baseline_cer"] + MANIFEST["allowed_cer_increase"]
    record_property("cer", cer)
    record_property("ocr_seconds", elapsed)
    record_property("confidence", result.confidence)
    print(f"{sample['id']}: CER={cer:.4f}, limit={maximum:.4f}, seconds={elapsed:.2f}")
    assert cer <= maximum, (
        f"{sample['id']}: CER={cer:.4f}, baseline={sample['baseline_cer']:.4f}, limit={maximum:.4f}"
    )
    assert sample["expected_total"] in result.raw_text.replace(",", "."), (
        "Receipt total was not recognized"
    )
