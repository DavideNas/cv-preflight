"""
CV Extractor API
Endpoint:
  POST /extract   → upload file, ritorna PreflightResult
  GET  /health    → healthcheck
  GET  /          → info servizio

Versione: 1.1.1
Changelog:
    - 1.1.1: Aggiunto blocco agency_protection nell'output
    - 1.0.0: Prima versione (preflight check base)
"""

import logging
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from preflight_check import preflight_check, PreflightResult


# ============================================================
# Configurazione
# ============================================================
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
VERSION = "1.1.1"

ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}


# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cv-extractor")


# ============================================================
# App
# ============================================================
app = FastAPI(
    title="CV Extractor",
    version=VERSION,
    description=(
        "Pre-flight check + estrazione testo CV + agency detection "
        "(deterministico, no LLM)"
    ),
)


# ============================================================
# Modelli risposta
# ============================================================
class HealthResponse(BaseModel):
    status: str
    version: str


class InfoResponse(BaseModel):
    name: str
    version: str
    max_upload_mb: int
    allowed_mimes: list[str]


# ============================================================
# Endpoints
# ============================================================
@app.get("/", response_model=InfoResponse)
async def root():
    return InfoResponse(
        name="cv-extractor",
        version=VERSION,
        max_upload_mb=MAX_UPLOAD_MB,
        allowed_mimes=sorted(ALLOWED_MIMES),
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version=VERSION)


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    # --------------------------------------------------------
    # Validazione dimensione
    # --------------------------------------------------------
    file.file.seek(0, 2)
    size_mb = file.file.tell() / (1024 * 1024)
    file.file.seek(0)
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File troppo grande: {size_mb:.1f}MB (max {MAX_UPLOAD_MB}MB)",
        )

    # --------------------------------------------------------
    # Salvataggio temporaneo
    # --------------------------------------------------------
    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        logger.info(f"Processing: {file.filename} ({size_mb:.2f}MB)")
        result: PreflightResult = preflight_check(
            tmp_path, file_id=Path(file.filename or "upload").stem
        )

        # Log esteso con info agency
        agency_info = result.agency_protection
        agency_log = (
            f"agency={agency_info.get('agency_name') or agency_info.get('match_type')} "
            f"(detected={agency_info.get('detected')}, "
            f"confidence={agency_info.get('confidence')})"
            if agency_info.get("detected")
            else "agency=none"
        )

        logger.info(
            f"Result: {result.risk_class} score={result.readability_score} "
            f"method={result.extraction_method} {agency_log}"
        )

        return JSONResponse(content=_to_json(result))
    except Exception as e:
        logger.exception("Errore durante l'estrazione")
        raise HTTPException(status_code=500, detail=f"Errore estrazione: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ============================================================
# Serializzazione
# ============================================================
def _to_json(result: PreflightResult) -> dict:
    """
    Converte PreflightResult in dict.
    Il raw_text viene tenuto intero (necessario per Fase 21),
    ma si aggiunge raw_text_length per comodità del consumer.
    """
    data = asdict(result)
    data["raw_text_length"] = len(data.get("raw_text", ""))
    return data