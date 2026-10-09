# ============================================================
# CV Extractor - FastAPI + OCRmyPDF + Tesseract
# Pre-flight check + estrazione testo CV (deterministico, no LLM)
# + Agency protection detection (v1.1.1)
#
# Base: Debian slim (compatibilità Tesseract + OCRmyPDF)
# ============================================================
FROM python:3.11-slim

# ------------------------------------------------------------
# Metadata
# ------------------------------------------------------------
LABEL org.opencontainers.image.title="cv-extractor"
LABEL org.opencontainers.image.description="Pre-flight check + estrazione testo CV + agency detection"
LABEL org.opencontainers.image.version="1.1.1"
LABEL org.opencontainers.image.authors="DavideNas"

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TESSERACT_LANGS=ita+eng

# ------------------------------------------------------------
# Dipendenze di sistema
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR
    tesseract-ocr \
    tesseract-ocr-ita \
    tesseract-ocr-eng \
    ocrmypdf \
    ghostscript \
    qpdf \
    # Image processing
    libmagic1 \
    poppler-utils \
    # Utilities
    curl \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Dipendenze Python
# ------------------------------------------------------------
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------
# Codice applicativo
# ------------------------------------------------------------
COPY app.py .
COPY preflight_check.py .
COPY agency_patterns.yaml .

# ------------------------------------------------------------
# Utente non-root
# ------------------------------------------------------------
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/logs /tmp/cv-work && \
    chown -R appuser:appuser /app /tmp/cv-work
USER appuser

EXPOSE 8080

# ------------------------------------------------------------
# Healthcheck + avvio
# ------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]