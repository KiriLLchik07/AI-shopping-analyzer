from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.image_processing.orientation import (
    ImageOrientationError,
    OrientationDetector,
    OrientationPrediction,
)


class PaddleOrientationDetector(OrientationDetector):
    def __init__(
        self, *, model_dir: Path, device: str = "cpu", cpu_threads: int = 4
    ) -> None:
        self.model_dir = model_dir
        self.device = device
        self.cpu_threads = cpu_threads
        self._model: Any | None = None

    def load(self) -> None:
        """Загружает локальные веса в вызывающем процессе без загрузки модели."""
        if self._model is not None:
            return
        if not all(
            (self.model_dir / name).is_file()
            for name in ("inference.json", "inference.pdiparams", "inference.yml")
        ):
            raise ImageOrientationError("Local orientation model files are missing")
        try:
            from paddleocr import DocImgOrientationClassification

            self._model = DocImgOrientationClassification(
                model_name="PP-LCNet_x1_0_doc_ori",
                model_dir=str(self.model_dir),
                device=self.device,
                cpu_threads=self.cpu_threads,
            )
        except Exception as error:
            raise ImageOrientationError(
                "Could not initialize orientation model"
            ) from error

    def predict(self, image: Image.Image) -> OrientationPrediction:
        self.load()
        try:
            import numpy as np

            rgb = np.asarray(image, dtype=np.uint8)
            bgr = np.ascontiguousarray(rgb[:, :, ::-1])
            results = list(self._model.predict(input=bgr, batch_size=1))
            if len(results) != 1:
                raise ImageOrientationError("Unexpected orientation result count")
            labels, scores = results[0]["label_names"], results[0]["scores"]
            if len(labels) != 1 or len(scores) != 1:
                raise ImageOrientationError("Invalid orientation prediction")
            return OrientationPrediction(
                correction_angle=int(labels[0]), confidence=float(scores[0])
            )
        except ImageOrientationError:
            raise
        except Exception as error:
            raise ImageOrientationError(
                "Could not predict image orientation"
            ) from error
