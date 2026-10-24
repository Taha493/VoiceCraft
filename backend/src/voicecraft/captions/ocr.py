"""OCR backends. RapidOCR (PP-OCR on ONNX Runtime) is the default: its models ship inside the
pip package and it copes with stylized text over gradients. Tesseract is optional and needs the
system `tesseract` binary.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

import cv2
import numpy as np

from .. import config


@dataclass(frozen=True)
class TextLine:
    text: str
    score: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels of the given image

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


class OcrEngine:
    name = "base"

    def read(self, image: np.ndarray) -> list[TextLine]:
        raise NotImplementedError


class RapidOcrEngine(OcrEngine):
    name = "rapidocr"

    def __init__(self, threads: int | None = None, min_score: float = 0.5, det_side: int = 960):
        from rapidocr import RapidOCR

        self._ocr = RapidOCR(
            params={
                "Global.use_cls": False,  # captions are horizontal; skipping the angle classifier saves time
                "Global.log_level": "error",
                "Global.text_score": min_score,
                # Default is limit_type=min/736, which upscales a short caption strip to ~6000px wide.
                # Capping the longest side keeps detection ~10x cheaper with no loss on caption-size text.
                "Det.limit_type": "max",
                "Det.limit_side_len": det_side,
                "EngineConfig.onnxruntime.intra_op_num_threads": threads or config.cpu_threads(),
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )

    def read(self, image: np.ndarray) -> list[TextLine]:
        res = self._ocr(image)
        if res.boxes is None or not res.txts:
            return []
        out = []
        for box, txt, score in zip(res.boxes, res.txts, res.scores):
            pts = np.asarray(box)
            out.append(
                TextLine(
                    text=txt.strip(),
                    score=float(score),
                    box=(float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())),
                )
            )
        return [line for line in out if line.text]


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(self, lang: str = "eng", min_score: float = 0.5):
        if shutil.which("tesseract") is None:
            raise RuntimeError("Tesseract is not installed (Arch: `sudo pacman -S tesseract tesseract-data-eng`).")
        import pytesseract

        self._tess = pytesseract
        self._lang = lang
        self._min = min_score * 100

    @staticmethod
    def preprocess(image: np.ndarray) -> np.ndarray:
        """Upscale, grayscale, Otsu-binarize, and make text dark-on-light (what Tesseract expects)."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        if gray.shape[0] < 400:
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(bw) < 127:
            bw = 255 - bw
        return bw

    def read(self, image: np.ndarray) -> list[TextLine]:
        prepped = self.preprocess(image)
        scale = image.shape[0] / prepped.shape[0]
        data = self._tess.image_to_data(prepped, lang=self._lang, config="--psm 6", output_type=self._tess.Output.DICT)
        lines: dict[tuple, list[int]] = {}
        for i, word in enumerate(data["text"]):
            if word.strip() and float(data["conf"][i]) >= self._min:
                lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
        out = []
        for idx in lines.values():
            x0 = min(data["left"][i] for i in idx) * scale
            y0 = min(data["top"][i] for i in idx) * scale
            x1 = max(data["left"][i] + data["width"][i] for i in idx) * scale
            y1 = max(data["top"][i] + data["height"][i] for i in idx) * scale
            text = " ".join(data["text"][i] for i in idx)
            score = float(np.mean([float(data["conf"][i]) for i in idx])) / 100
            out.append(TextLine(text, score, (x0, y0, x1, y1)))
        return out


def load_ocr(name: str = "rapidocr") -> OcrEngine:
    if name == "rapidocr":
        return RapidOcrEngine()
    if name == "tesseract":
        return TesseractEngine()
    raise ValueError(f"Unknown OCR engine: {name}")


def available_ocr() -> list[str]:
    names = ["rapidocr"]
    if shutil.which("tesseract"):
        try:
            import pytesseract  # noqa: F401

            names.append("tesseract")
        except ImportError:
            pass
    return names
