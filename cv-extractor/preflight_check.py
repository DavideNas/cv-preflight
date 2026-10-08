"""
Pre-flight check di leggibilità per CV.
Deterministico, zero LLM. Output: JSON con score e risk class.

Dipendenze di sistema:
    - Tesseract OCR (con lingua ita + eng)
    - OCRmyPDF
    - libmagic (per python-magic)

Dipendenze Python:
    pip install pdfplumber pymupdf pytesseract pillow langdetect python-magic python-docx
"""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import magic
import pdfplumber
import pytesseract
from langdetect import detect_langs, LangDetectException
from PIL import Image


# ============================================================
# CONFIGURAZIONE SOGLIE (calibrabili sul dataset aziendale)
# ============================================================

@dataclass
class Thresholds:
    # Testo nativo PDF
    min_chars_per_page_native: int = 100

    # OCR
    min_ocr_confidence: float = 0.70
    min_chars_per_page_ocr: int = 150

    # Qualità testo
    max_noise_ratio: float = 0.30
    min_language_confidence: float = 0.80

    # Immagine
    min_image_dpi: int = 150
    max_rotation_degrees: float = 5.0

    # Score finale
    green_threshold: int = 80
    yellow_threshold: int = 50


# ============================================================
# MODELLO OUTPUT
# ============================================================

@dataclass
class PreflightResult:
    file_id: str
    file_path: str
    mime_type: str
    file_size_bytes: int
    pages: int
    extraction_method: str
    readability_score: int
    risk_class: str            # GREEN | YELLOW | RED
    metrics: dict
    raw_text: str
    warnings: list = field(default_factory=list)
    action: str = "proceed"    # proceed | proceed_with_flag | human_review


# ============================================================
# UTILITY
# ============================================================

def detect_mime(file_path: str) -> str:
    return magic.from_file(file_path, mime=True)


def safe_lang_detect(text: str) -> tuple[Optional[str], float]:
    """Ritorna (lang, confidence). Confidence 0 se fallisce."""
    if not text or len(text.strip()) < 30:
        return None, 0.0
    try:
        results = detect_langs(text)
        if not results:
            return None, 0.0
        top = results[0]
        return top.lang, top.prob
    except LangDetectException:
        return None, 0.0


def compute_noise_ratio(text: str) -> float:
    """% caratteri non alfanumerici (esclusi spazi/newline)."""
    if not text:
        return 1.0
    stripped = re.sub(r"\s", "", text)
    if not stripped:
        return 1.0
    noise = sum(1 for c in stripped if not c.isalnum())
    return noise / len(stripped)


def get_pdf_native_text(file_path: str) -> tuple[str, int]:
    """Estrae testo da PDF nativo. Ritorna (testo, n_pagine)."""
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n".join(text_parts), pages


def is_pdf_scanned(native_text: str, pages: int, thresholds: Thresholds) -> bool:
    """Decide se un PDF è scansionato (poco testo nativo)."""
    if pages == 0:
        return True
    return (len(native_text) / pages) < thresholds.min_chars_per_page_native


def run_ocr_pdf(file_path: str, thresholds: Thresholds) -> tuple[str, float]:
    """OCR su PDF via ocrmypdf --sidecar. Ritorna (testo, confidence stimata)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sidecar = Path(tmpdir) / "out.txt"
        dummy_pdf = Path(tmpdir) / "dummy.pdf"

        cmd = [
            "ocrmypdf",
            "--image-dpi", "300",
            "--deskew",
            "--rotate-pages",
            "--sidecar", str(sidecar),
            "--output-type", "none",
            "-l", "ita+eng",
            file_path,
            str(dummy_pdf),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return "", 0.0

        text = sidecar.read_text(encoding="utf-8", errors="ignore") if sidecar.exists() else ""
        confidence = estimate_ocr_confidence_pdf(file_path)
        return text, confidence


def estimate_ocr_confidence_pdf(file_path: str) -> float:
    """
    Stima confidence OCR mediando il confidence Tesseract
    sulle prime 2 pagine renderizzate.
    """
    confidences = []
    doc = fitz.open(file_path)
    for i, page in enumerate(doc):
        if i >= 2:
            break
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        try:
            data = pytesseract.image_to_data(
                img, lang="ita+eng", output_type=pytesseract.Output.DICT
            )
            vals = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
            if vals:
                confidences.append(sum(vals) / len(vals) / 100.0)
        except Exception:
            continue
    doc.close()
    return sum(confidences) / len(confidences) if confidences else 0.0


def run_ocr_image(file_path: str) -> tuple[str, float, int]:
    """OCR su immagine singola. Ritorna (testo, confidence, dpi_stimato)."""
    try:
        img = Image.open(file_path)
    except Exception:
        return "", 0.0, 0

    dpi_info = img.info.get("dpi", (72, 72))
    dpi = int(dpi_info[0]) if isinstance(dpi_info, tuple) else int(dpi_info)

    try:
        data = pytesseract.image_to_data(
            img, lang="ita+eng", output_type=pytesseract.Output.DICT
        )
        text = pytesseract.image_to_string(img, lang="ita+eng")
        vals = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
        conf = (sum(vals) / len(vals) / 100.0) if vals else 0.0
    except Exception:
        return "", 0.0, dpi

    return text, conf, dpi


# ============================================================
# SCORING
# ============================================================

def compute_readability_score(metrics: dict, thresholds: Thresholds) -> int:
    """
    Score 0-100 basato su:
      - densità testo (30 pt)
      - confidence OCR (25 pt)
      - rumore (20 pt)
      - confidence lingua (15 pt)
      - rotazione (10 pt)
    """
    score = 0.0

    # Densità testo (30 pt)
    chars_per_page = metrics.get("chars_per_page", 0)
    if chars_per_page >= 1500:
        score += 30
    elif chars_per_page >= 800:
        score += 22
    elif chars_per_page >= 300:
        score += 15
    elif chars_per_page >= 100:
        score += 8
    else:
        score += 0

    # Confidence OCR (25 pt) — se non applicabile, assegna pieno
    if metrics.get("extraction_method") in ("ocrmypdf", "tesseract"):
        ocr_conf = metrics.get("ocr_confidence", 0.0)
        score += max(0.0, min(1.0, ocr_conf)) * 25
    else:
        score += 25

    # Rumore (20 pt)
    noise = metrics.get("noise_ratio", 1.0)
    if noise <= 0.05:
        score += 20
    elif noise <= 0.10:
        score += 15
    elif noise <= 0.20:
        score += 10
    elif noise <= 0.30:
        score += 5
    else:
        score += 0

    # Lingua (15 pt)
    lang_conf = metrics.get("language_confidence", 0.0)
    if lang_conf >= 0.95:
        score += 15
    elif lang_conf >= 0.80:
        score += 10
    elif lang_conf >= 0.60:
        score += 5
    else:
        score += 0

    # Rotazione (10 pt)
    rot = abs(metrics.get("rotation_detected", 0.0))
    if rot <= 2:
        score += 10
    elif rot <= 5:
        score += 6
    elif rot <= 10:
        score += 3
    else:
        score += 0

    return int(round(min(100.0, max(0.0, score))))


def classify_risk(score: int, metrics: dict, thresholds: Thresholds) -> tuple[str, str]:
    """Ritorna (risk_class, action)."""
    # Override: RED forzato se metriche critiche
    if metrics.get("ocr_confidence", 1.0) < 0.40:
        return "RED", "human_review"
    if metrics.get("chars_per_page", 9999) < 50:
        return "RED", "human_review"

    if score >= thresholds.green_threshold:
        return "GREEN", "proceed"
    if score >= thresholds.yellow_threshold:
        return "YELLOW", "proceed_with_flag"
    return "RED", "human_review"


def _estimate_rotation_pdf(file_path: str) -> float:
    """
    Stima grezza rotazione media: Tesseract OSD se disponibile,
    altrimenti 0. Deterministico ma opzionale.
    """
    try:
        doc = fitz.open(file_path)
        page = doc[0]
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        osd = pytesseract.image_to_osd(img)
        doc.close()
        m = re.search(r"Rotate: (\d+)", osd)
        if m:
            deg = int(m.group(1))
            return float(deg if deg <= 180 else deg - 360)
    except Exception:
        return 0.0
    return 0.0


# ============================================================
# ORCHESTRAZIONE
# ============================================================

def preflight_check(file_path: str, file_id: str = "unknown",
                    thresholds: Optional[Thresholds] = None) -> PreflightResult:
    thresholds = thresholds or Thresholds()
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {file_path}")

    mime = detect_mime(file_path)
    file_size = path.stat().st_size
    warnings: list[str] = []

    raw_text = ""
    pages = 1
    extraction_method = "none"
    metrics: dict = {}

    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------
    if mime == "application/pdf":
        native_text, pages = get_pdf_native_text(file_path)
        if not is_pdf_scanned(native_text, pages, thresholds):
            raw_text = native_text
            extraction_method = "pdfplumber"
            metrics["chars_per_page"] = len(native_text) / max(pages, 1)
            metrics["ocr_confidence"] = 1.0
            metrics["rotation_detected"] = 0.0
        else:
            warnings.append("pdf_scanned_detected")
            ocr_text, ocr_conf = run_ocr_pdf(file_path, thresholds)
            raw_text = ocr_text
            extraction_method = "ocrmypdf"
            metrics["chars_per_page"] = len(ocr_text) / max(pages, 1)
            metrics["ocr_confidence"] = ocr_conf
            metrics["rotation_detected"] = _estimate_rotation_pdf(file_path)

    # --------------------------------------------------------
    # Immagini
    # --------------------------------------------------------
    elif mime.startswith("image/"):
        ocr_text, ocr_conf, dpi = run_ocr_image(file_path)
        raw_text = ocr_text
        pages = 1
        extraction_method = "tesseract"
        metrics["chars_per_page"] = len(ocr_text)
        metrics["ocr_confidence"] = ocr_conf
        metrics["image_dpi"] = dpi
        metrics["rotation_detected"] = 0.0
        if dpi < thresholds.min_image_dpi:
            warnings.append("low_image_dpi")

    # --------------------------------------------------------
    # DOCX
    # --------------------------------------------------------
    elif mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        try:
            from docx import Document
            doc = Document(file_path)
            raw_text = "\n".join(p.text for p in doc.paragraphs)
            extraction_method = "python-docx"
            metrics["chars_per_page"] = len(raw_text)
            metrics["ocr_confidence"] = 1.0
            metrics["rotation_detected"] = 0.0
        except Exception as e:
            warnings.append(f"docx_parse_error:{e}")

    else:
        warnings.append(f"unsupported_mime:{mime}")
        return PreflightResult(
            file_id=file_id,
            file_path=str(path),
            mime_type=mime,
            file_size_bytes=file_size,
            pages=0,
            extraction_method="unsupported",
            readability_score=0,
            risk_class="RED",
            metrics={},
            raw_text="",
            warnings=warnings,
            action="human_review",
        )

    # --------------------------------------------------------
    # Metriche comuni
    # --------------------------------------------------------
    lang, lang_conf = safe_lang_detect(raw_text)
    metrics["language_detected"] = lang
    metrics["language_confidence"] = lang_conf
    metrics["noise_ratio"] = compute_noise_ratio(raw_text)
    metrics["extraction_method"] = extraction_method
    metrics["text_length"] = len(raw_text)

    # Warning automatici
    if metrics["noise_ratio"] > thresholds.max_noise_ratio:
        warnings.append("high_noise_ratio")
    if lang_conf < thresholds.min_language_confidence:
        warnings.append("low_language_confidence")
    if metrics.get("ocr_confidence", 1.0) < thresholds.min_ocr_confidence:
        warnings.append("low_ocr_confidence")

    # --------------------------------------------------------
    # Score + classificazione
    # --------------------------------------------------------
    score = compute_readability_score(metrics, thresholds)
    risk_class, action = classify_risk(score, metrics, thresholds)

    return PreflightResult(
        file_id=file_id,
        file_path=str(path),
        mime_type=mime,
        file_size_bytes=file_size,
        pages=pages,
        extraction_method=extraction_method,
        readability_score=score,
        risk_class=risk_class,
        metrics=metrics,
        raw_text=raw_text,
        warnings=warnings,
        action=action,
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python preflight_check.py <file_cv>")
        sys.exit(1)

    result = preflight_check(sys.argv[1], file_id=Path(sys.argv[1]).stem)
    out = asdict(result)
    if len(out["raw_text"]) > 5000:
        out["raw_text_preview"] = out["raw_text"][:5000]
        out["raw_text_truncated"] = True
        del out["raw_text"]

    print(json.dumps(out, ensure_ascii=False, indent=2))