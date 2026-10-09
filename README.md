# CV Preflight

Microservizio per il **pre-flight check di leggibilità**, l'**estrazione testo** di CV in formati eterogenei (PDF nativo, PDF scansionato, DOCX, immagini) e il **rilevamento di agenzie HR intermediarie**. Deterministico, zero chiamate LLM.

Progetto pilota per l'automazione del processo di recruiting di una PMI italiana, in conformità con **GDPR**, **AI Act Europeo (art. 6)** e **CCNL italiano**.

**Versione attuale**: `1.1.0`

---

## 🎯 Obiettivo

Prima di inviare un CV a un LLM per scoring e valutazione, il sistema:

1. **Classifica il rischio di leggibilità** del documento (GREEN / YELLOW / RED)
2. **Estrae il testo** con il metodo più appropriato (nativo o OCR)
3. **Calcola metriche oggettive** (densità testo, confidence OCR, rumore, lingua, rotazione)
4. **Rileva se il CV è passato da un'agenzia HR** (header agenzia + dati sensibili)
5. **Decide l'azione**: procedi, procedi con flag, oppure human review

Questo permette di:
- **Risparmiare chiamate LLM** su documenti illeggibili
- **Ridurre allucinazioni** (LLM lavora solo su testo pulito)
- **Evitare retry inutili** su CV anonimizzati da agenzie
- **Rispettare l'AI Act** (human-in-the-loop sui casi dubbi)
- **Garantire tracciabilità** (ogni decisione è motivata da metriche)

---

## 🏗️ Architettura

```
[File CV] → [Preflight Check] → GREEN/YELLOW/RED
                    ↓
              [Agency Detection]
                    ↓
       ┌────────────┴────────────┐
       │                         │
   GREEN/YELLOW              RED
       │                         │
       ↓                         ↓
[LLM Extraction]          [Human Review]
```

Il pre-flight check è **completamente deterministico**: nessuna chiamata LLM, nessuna variabilità, nessuna allucinazione possibile.

---

## 📦 Stack

| Componente | Tecnologia |
|---|---|
| API | FastAPI + Uvicorn |
| PDF nativo | pdfplumber + PyMuPDF |
| PDF scansionato | OCRmyPDF + Tesseract |
| DOCX | python-docx |
| Immagini | Tesseract + Pillow |
| Rilevamento lingua | langdetect |
| Rilevamento MIME | python-magic |
| Agency detection | pyyaml + regex |
| Container | Docker |
| Orchestrazione | Portainer |
| CI/CD | GitHub Actions → GHCR |
| Email di test | Mailpit |

---

## 🚀 Deploy

### Prerequisiti

- Docker + Docker Compose
- Portainer (o Docker Compose CLI)
- Accesso a GHCR (il package è pubblico, quindi pull anonimo)

### Con Portainer

1. **Stacks** → **Add stack**
2. Nome: `cv-preflight`
3. **Build method**: **Repository**
4. **Repository URL**: `https://github.com/DavideNas/cv-preflight`
5. **Repository reference**: `refs/heads/main`
6. **Compose path**: `docker-compose.yml`
7. **Authentication**: ON (se repo privato) → username GitHub + PAT con scope `repo`
8. **Deploy the stack**

### Con Docker Compose (CLI)

```bash
git clone https://github.com/DavideNas/cv-preflight.git
cd cv-preflight
docker compose up -d
```

### Verifica

```bash
curl http://localhost:8080/health
# → {"status":"ok","version":"1.1.0"}
```

---

## 📡 API

### `GET /`

Info sul servizio.

### `GET /health`

Healthcheck.

### `POST /extract`

Upload di un CV, ritorna il risultato del pre-flight check + agency detection.

**Esempio:**

```bash
curl -X POST http://localhost:8080/extract \
  -F "file=@/path/to/cv.pdf" | jq
```

**Output:**

```json
{
  "file_id": "cv",
  "mime_type": "application/pdf",
  "extraction_method": "pdfplumber",
  "readability_score": 95,
  "risk_class": "GREEN",
  "action": "proceed",
  "metrics": {
    "chars_per_page": 2495,
    "ocr_confidence": 1.0,
    "noise_ratio": 0.055,
    "language_detected": "en",
    "language_confidence": 0.99999,
    "rotation_detected": 0.0,
    "text_length": 7485
  },
  "agency_protection": {
    "detected": false,
    "confidence": "low",
    "agency_name": null,
    "agency_header_line": null,
    "match_type": "none",
    "sensitive_data_present": null,
    "expected_missing_fields": []
  },
  "raw_text": "...",
  "raw_text_length": 7485,
  "warnings": []
}
```

---

## 🎨 Classificazione rischio

| Classe | Score | Azione | Significato |
|---|---|---|---|
| 🟢 GREEN | ≥ 80 | `proceed` | Documento leggibile, procedi |
| 🟡 YELLOW | 50–79 | `proceed_with_flag` | Leggibile con riserve, procedi con flag |
| 🔴 RED | < 50 | `human_review` | Illeggibile, richiede revisione umana |

**Override RED automatico** se:
- `ocr_confidence < 0.40`
- `chars_per_page < 50`

---

## 🕵️ Agency Protection Detection

Il sistema rileva se un CV è passato da un'agenzia HR intermediaria, analizzando **header e footer** del testo (prime 20 righe, ultime 10 righe).

### Come funziona

1. Cerca match con **10 agenzie italiane note** (Randstad, Adecco, Manpower, Gi Group, Michael Page, Hays, Robert Half, Page Personnel, Kelly Services, Synergie)
2. Cerca **pattern generici** ("agenzia per il lavoro", "somministrazione di lavoro", "ricerca e selezione", ecc.)
3. Verifica se sono presenti **dati sensibili** (email, telefono, CF, P.IVA, data di nascita, indirizzo)

### Output

```json
{
  "agency_protection": {
    "detected": true,
    "confidence": "high",
    "agency_name": "Randstad",
    "agency_header_line": "Randstad Italia S.p.A. - Divisione IT",
    "match_type": "known_agency",
    "sensitive_data_present": false,
    "expected_missing_fields": [
      "candidate.email",
      "candidate.phone",
      "candidate.location",
      "candidate.date_of_birth",
      "candidate.nationality"
    ]
  }
}
```

### Perché è importante

Molte agenzie inviano CV **anonimizzati** (nome sostituito, contatti rimossi, data di nascita rimossa). Senza questo controllo, il sistema:

- ❌ Farebbe retry inutili su campi attesi mancanti
- ❌ Notificherebbe il recruiter per falsi positivi
- ❌ Sprecherebbe chiamate LLM

Con questo controllo, il sistema:

- ✅ Esclude i campi attesi mancanti dal retry
- ✅ Traccia la provenienza del CV
- ✅ Sa che il candidato va contattato tramite agenzia

### Configurazione

I pattern sono in `cv-extractor/agency_patterns.yaml`:

```yaml
agencies:
  - name: "Randstad"
    patterns: ["randstad", "randstad italia"]

generic_header_patterns:
  - "agenzia per il lavoro"
  - "somministrazione di lavoro"

search_zones:
  header_lines: 20
  footer_lines: 10

sensitive_data_patterns:
  email: '[\w\.-]+@[\w\.-]+\.\w+'
  phone_it: '\+39[\s\.]?\d{2,3}[\s\.]?\d{6,7}'
  # ...
```

Per aggiungere un'agenzia, basta modificare il YAML e riavviare il container.

---

## 📊 Metriche

| Metrica | Peso | Descrizione |
|---|---|---|
| Densità testo | 30 | Caratteri per pagina |
| Confidence OCR | 25 | Confidenza media Tesseract |
| Rumore | 20 | % caratteri non alfanumerici |
| Confidence lingua | 15 | Confidenza langdetect |
| Rotazione | 10 | Gradi di rotazione rilevati |

**Score finale**: 0–100.

---

## ✅ Validazione

### Test 1 — CV nativo PDF (inglese)

**Input**: `Davide_Naselli_Resume.pdf` (3 pagine, 127 KB, PDF nativo)

**Risultato**:

| Campo | Valore |
|---|---|
| `mime_type` | `application/pdf` |
| `extraction_method` | `pdfplumber` |
| `pages` | 3 |
| `readability_score` | **95** |
| `risk_class` | **GREEN** |
| `action` | `proceed` |
| `chars_per_page` | 2495 |
| `ocr_confidence` | 1.0 (nessun OCR) |
| `noise_ratio` | 0.055 |
| `language_detected` | `en` (confidence 0.99999) |
| `agency_protection.detected` | `false` |
| `warnings` | `[]` |

**Esito**: ✅ Il sistema ha correttamente:
- Rilevato il MIME
- Identificato il PDF come nativo (no OCR)
- Estratto testo pulito e ordinato
- Classificato il documento come GREEN (procedi senza intervento umano)
- Rilevato la lingua inglese con altissima confidenza
- Escluso la presenza di agenzia (CV diretto)

**Costo LLM**: **0€** (nessuna chiamata)

---

## ⚖️ Compliance

### GDPR

- **Nessun dato personale** viene inviato a servizi esterni in questa fase
- I file sono processati in `/tmp` e cancellati dopo l'elaborazione
- **Non committare CV reali** nel repository (vedi `.gitignore`)
- Il sistema **riconosce** i CV anonimizzati da agenzie e non forza la ricerca dei dati rimossi

### AI Act (art. 6)

- Il pre-flight check è **deterministico**, non è un sistema AI
- I casi RED sono **automaticamente** indirizzati a **human review**
- Ogni decisione è **tracciata** con metriche oggettive

### CCNL

- Nessun criterio discriminatorio è applicato in questa fase
- L'estrazione è **neutra** rispetto a genere, età, etnia, religione

---

## 🧪 Sviluppo locale

```bash
cd cv-extractor
pip install -r requirements.txt

# Test CLI
python preflight_check.py /path/to/cv.pdf

# Test API
uvicorn app:app --reload --port 8080
```

---

## 📁 Struttura

```
cv-preflight/
├── README.md
├── docker-compose.yml
├── .gitignore
├── .github/
│   └── workflows/
│       └── build-push.yml
└── cv-extractor/
    ├── Dockerfile
    ├── requirements.txt
    ├── app.py
    ├── preflight_check.py
    └── agency_patterns.yaml
```

---

## 📝 Changelog

### v1.1.0
- ✨ Aggiunto rilevamento agency protection (header agenzia HR)
- ✨ Aggiunto file `agency_patterns.yaml` con 10 agenzie italiane
- ✨ Aggiunto campo `agency_protection` in `PreflightResult`
- 🔧 Aggiornato `Dockerfile` per copiare `agency_patterns.yaml`
- 🔧 Aggiunta dipendenza `pyyaml==6.0.2`

### v1.0.0
- 🎉 Prima versione
- Preflight check base (MIME, estrazione, metriche, scoring, risk class)

---

## 📝 Licenza

Progetto privato. Tutti i diritti riservati.