"""OCR with word-level confidence.

Preprocessing targets the two degradations prior-auth inboxes actually see: scan
noise (salt speckle, slight skew) and fax binarization. Tesseract returns per-word
confidence, which flows into field confidence and the abstain decision downstream.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps


@dataclass
class OCRWord:
    text: str
    conf: float
    line_key: tuple


@dataclass
class OCRPage:
    text: str
    words: list[OCRWord]
    mean_conf: float


@dataclass
class OCRDoc:
    pages: list[OCRPage]
    latency_ms: float
    word_conf: dict[str, float] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def mean_conf(self) -> float:
        confs = [w.conf for p in self.pages for w in p.words]
        return sum(confs) / len(confs) if confs else 0.0

    def conf_for(self, value: str) -> float:
        """Mean OCR confidence of the tokens that make up an extracted value."""
        toks = [t for t in str(value).replace(",", " ").split() if t]
        if not toks:
            return 0.0
        vals = [self.word_conf.get(t.strip(".:;").upper(), 60.0) for t in toks]
        return sum(vals) / len(vals) / 100.0


def preprocess(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = g.filter(ImageFilter.MedianFilter(3))  # removes salt-and-pepper speckle
    return g.point(lambda v: 0 if v < 170 else 255)


def ocr_image(img: Image.Image) -> OCRPage:
    data = pytesseract.image_to_data(preprocess(img), config="--psm 4",
                                     output_type=pytesseract.Output.DICT)
    words, lines = [], {}
    for i, tok in enumerate(data["text"]):
        tok = tok.strip()
        conf = float(data["conf"][i])
        if not tok or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        words.append(OCRWord(tok, conf, key))
        lines.setdefault(key, []).append(tok)
    text = "\n".join(" ".join(v) for v in lines.values())
    mean = sum(w.conf for w in words) / len(words) if words else 0.0
    return OCRPage(text=text, words=words, mean_conf=mean)


def ocr_pages(paths: list[str | Path]) -> OCRDoc:
    t0 = time.perf_counter()
    pages = [ocr_image(Image.open(p)) for p in paths]
    doc = OCRDoc(pages=pages, latency_ms=(time.perf_counter() - t0) * 1000)
    for p in pages:
        for w in p.words:
            k = w.text.strip(".:;,").upper()
            doc.word_conf[k] = max(doc.word_conf.get(k, 0.0), w.conf)
    return doc
