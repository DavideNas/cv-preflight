# Roadmap — CV Preflight

Stato attuale: **Fase 21 completa** (estrazione dati CV + routing GREEN/YELLOW/RED).

Questo documento descrive le fasi successive per completare la pipeline end-to-end del progetto di automazione recruiting, in conformità con i vincoli della traccia (GDPR, AI Act, CCNL, determinismo, tracciabilità, budget).

---

## 📊 Stato attuale

| Fase | Descrizione | Stato |
|---|---|---|
| **Fase 21** | Estrazione dati CV + routing GREEN/YELLOW/RED | ✅ **Completa** |
| **Fase 22** | Confronto con JD + scoring qualitativo | 📋 Design |
| **Fase 23** | Audit log + tracciabilità | 📋 Design |
| **Fase 24** | Comunicazione esito al candidato | 📋 Design |
| **Fase 25** | Ingestion email reale (IMAP) | 📋 Design |

---

## 🎯 Fase 22 — Confronto con JD + Scoring qualitativo

### Obiettivo

Coprire gli step 4 e 5 del processo manuale:

> 4. Confronto con Job Description (JD) della posizione ricercata
> 5. Scoring qualitativo della aderenza del candidato al profilo

### Perché è importante

Senza questa fase, il sistema si ferma all'estrazione dei dati. Con questa fase, il sistema produce uno **score di aderenza** e una **decisione** (advance/hold/reject), che è il cuore del processo di pre-screening.

### Architettura

Il pattern è **lo stesso della Fase 21**:

1. **JD Agent** (LLM) → estrae requisiti dalla JD in JSON strutturato
2. **Matching deterministico** (Python) → confronto CV ↔ JD
3. **Scoring LLM** (LLM) → giudizio olistico + reasoning

```
[CV strutturato (Fase 21)]
        ↓
[JD strutturato (Fase 22a)] ← AI Agent con LLM
        ↓
[Matching deterministico (Fase 22b)] ← Python, zero LLM
        ↓
[Scoring qualitativo (Fase 22c)] ← AI Agent con LLM
        ↓
[Decision Router]
   ├── advance → [Telegram HR]
   ├── hold    → [Telegram HR]
   └── reject  → [Telegram HR]
```

**Perché 3 livelli?**

- **Livello 1 (LLM)**: JD in testo libero → JSON strutturato
- **Livello 2 (Python)**: matching oggettivo, deterministico, tracciabile, zero costi LLM
- **Livello 3 (LLM)**: giudizio complessivo, reasoning, motivazione

Solo i livelli 1 e 3 costano (1 chiamata LLM ciascuno). Il livello 2 è gratis e ripetibile.

### Schema JD

Il JD Agent restituisce un JSON conforme a `schemas/fase22_jd_output.json`:

```json
{
  "jd_metadata": {
    "jd_id": "senior_devops_2026",
    "title": "Senior DevOps Engineer",
    "company": "Acme SRL",
    "location": "Milano",
    "work_mode": "hybrid",
    "language": "it",
    "confidence": "high"
  },
  "requirements": {
    "mandatory": [
      { "skill": "Terraform", "level": "advanced", "years_min": 3, "weight": 10, "confidence": "high" }
    ],
    "preferred": [
      { "skill": "GCP", "level": "intermediate", "weight": 5, "confidence": "high" }
    ],
    "excluded": [
      { "condition": "no_cloud_experience", "reason": "Ruolo richiede esperienza cloud", "confidence": "high" }
    ]
  },
  "experience": {
    "years_min": 5,
    "years_max": null,
    "seniority": "senior",
    "industries": ["IT services", "cloud"],
    "confidence": "high"
  },
  "education": {
    "level": "bachelor",
    "fields": ["computer science", "engineering"],
    "certifications": [],
    "confidence": "medium"
  },
  "responsibilities": [
    { "description": "Design cloud-native architectures", "category": "technical" }
  ],
  "soft_skills": ["teamwork", "communication"],
  "languages_required": [
    { "language": "Italian", "level": "C1" },
    { "language": "English", "level": "B2" }
  ],
  "salary_range": {
    "min": 50000,
    "max": 70000,
    "currency": "EUR",
    "period": "yearly"
  },
  "extraction_metadata": {
    "extraction_version": "1.0.0",
    "extraction_timestamp": "2026-10-12T14:00:00Z",
    "language_source": "it",
    "overall_confidence": "high"
  }
}
```

**Campi chiave**:

- **`weight`**: peso del requisito (1-10) → scoring ponderato
- **`level`**: livello richiesto (basic/intermediate/advanced/expert) → matching più preciso
- **`excluded`**: condizioni escludenti → reject automatico se matchano
- **`confidence`**: affidabilità dell'estrazione → il matching pesa meno i campi a bassa confidence

### Matching deterministico

Nuovo endpoint `POST /match` in `cv-extractor`:

**Input**: `cv.json` + `jd.json`
**Output**: `match.json`

**Logica**:

1. **Match requisiti obbligatori**
   - Per ogni `jd.requirements.mandatory`, verifica se `skill` è in `cv.skills.technical` (esatto o fuzzy)
   - Output: `matched[]`, `missing[]`, `score`

2. **Match requisiti preferenziali**
   - Idem, ma con peso minore

3. **Verifica condizioni escludenti**
   - Per ogni `jd.requirements.excluded`, verifica se la condizione matcha il CV
   - Output: `triggered[]`

4. **Calcolo anni esperienza**
   - Somma durate da `cv.experience`
   - Confronta con `jd.experience.years_min`
   - Output: `actual_years`, `required_years`, `score`

5. **Score ponderato**

   ```
   mandatory_score  × 0.60
   preferred_score  × 0.20
   experience_score × 0.15
   education_score  × 0.05
   ```

   Se `excluded_triggered` non è vuoto → **score = 0** (reject automatico).

**Output esempio**:

```json
{
  "mandatory_match": {
    "matched": ["Terraform", "Kubernetes", "AWS"],
    "missing": [],
    "score": 100
  },
  "preferred_match": {
    "matched": ["GCP", "CI/CD"],
    "missing": ["Azure"],
    "score": 66
  },
  "excluded_match": {
    "triggered": [],
    "score": 100
  },
  "experience_match": {
    "required_years": 5,
    "actual_years": 15,
    "score": 100
  },
  "education_match": {
    "required_level": "bachelor",
    "actual_level": "diploma",
    "score": 60
  },
  "overall_score": 94,
  "excluded_triggered": false,
  "matching_metadata": {
    "algorithm_version": "1.0.0",
    "timestamp": "2026-10-12T14:00:00Z"
  }
}
```

### Scoring LLM

Nuovo AI Agent in n8n:

**Input**: `cv.json` + `jd.json` + `match.json`
**Output**: `score.json`

**Contenuto**:

- `overall_score` (0-100)
- `reasoning` (motivazione testuale)
- `strengths[]` (punti di forza del candidato)
- `weaknesses[]` (gap rispetto alla JD)
- `decision` (`advance` / `hold` / `reject`)
- `feedback_candidate` (testo pronto per il candidato)
- `confidence` (high/medium/low)

**Prompt**: stesso pattern della Fase 21 (system + user, temperatura 0, max token 4096).

---

## 🎯 Fase 23 — Audit Log + Tracciabilità

### Obiettivo

Coprire lo step 7 del processo manuale:

> 7. Archiviazione della candidatura e relativa valutazione per audit interno

E il vincolo della traccia:

> Tracciabilità: il team HR e i revisori devono poter ricostruire ogni decisione: quale LLM era in uso, quale versione del prompt, quali erano i dati di input, quale la valutazione, con timestamp e autenticazione

### Perché è importante

L'AI Act art. 6 classifica i sistemi di decisione sull'impiego come **ad alto rischio**. Questo richiede:

- **Log immutabile** di ogni decisione
- **Ricostruibilità** end-to-end
- **Timestamp** e **autenticazione**

### Architettura

Aggiungere **PostgreSQL** allo stack `cv-preflight`:

```yaml
postgres:
  image: postgres:16
  container_name: cv-preflight-postgres
  restart: unless-stopped
  environment:
    - POSTGRES_DB=cv_audit
    - POSTGRES_USER=cv_user
    - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
  volumes:
    - postgres-data:/var/lib/postgresql/data
  networks:
    - cv-preflight-net
```

### Schema DB

```sql
CREATE TABLE audit_log (
  id              SERIAL PRIMARY KEY,
  timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  cv_id           VARCHAR(255) NOT NULL,
  jd_id           VARCHAR(255),
  llm_model       VARCHAR(100),
  prompt_version  VARCHAR(50),
  input_hash      VARCHAR(64),
  cv_json         JSONB,
  jd_json         JSONB,
  match_json      JSONB,
  score_json      JSONB,
  decision        VARCHAR(50),
  reviewer_id     VARCHAR(100),
  user_auth       VARCHAR(100)
);

CREATE INDEX idx_audit_cv_id ON audit_log(cv_id);
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX idx_audit_decision ON audit_log(decision);

CREATE TABLE prompt_versions (
  version     VARCHAR(50) PRIMARY KEY,
  content     TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by  VARCHAR(100)
);
```

### Cosa loggare

Per ogni decisione:

| Campo | Fonte |
|---|---|
| `timestamp` | automatico |
| `cv_id` | dal preflight |
| `jd_id` | dalla JD |
| `llm_model` | config n8n |
| `prompt_version` | hardcoded nel prompt |
| `input_hash` | SHA-256 del CV |
| `cv_json` | output Fase 21 |
| `jd_json` | output Fase 22a |
| `match_json` | output Fase 22b |
| `score_json` | output Fase 22c |
| `decision` | output scoring |
| `reviewer_id` | se human-in-the-loop |
| `user_auth` | chi ha eseguito |

### GDPR

- **Redazione PII** prima del log (o hash dei campi sensibili)
- **Retention policy**: 12 mesi (configurabile)
- **Diritto all'oblio**: cancellazione su richiesta
- **Pseudonimizzazione**: `cv_id` invece di nome candidato

### Nodo n8n

Dopo `Decision Router`, aggiungere un nodo **Postgres → Insert**:

```
[Decision Router]
    ↓
[Postgres: Insert audit_log]
```

### Costi

- **Zero LLM**
- Storage: ~1 KB/decisione × 500/mese = ~500 KB/mese
- **Trascurabile**

---

## 🎯 Fase 24 — Comunicazione esito al candidato

### Obiettivo

Coprire lo step 6 del processo manuale:

> 6. Comunicazione al candidato dell'esito della pre-screening (respinto, sospeso, avanzato)

E il vincolo della traccia:

> Affidabilità: il candidato DEVE ricevere feedback leale e non allucinato (es. nessuna competenza inventata estratta dal CV, nessuna giustificazione fittizia di un rejection)

### Architettura

```
[Decision Router]
    ├── advance → [Email: avanzato]
    ├── hold    → [Email: sospeso]
    └── reject  → [Email: respinto]
```

### Generazione feedback

**Nuovo AI Agent** dedicato:

**Input**: `score.json` (con reasoning, strengths, weaknesses, decision)
**Output**: testo email personalizzato

**Vincoli**:

- **No allucinazioni**: basato solo su `score.json` (non sul CV grezzo)
- **No discriminazioni**: nessun riferimento a età, genere, etnia, religione
- **Tono professionale e rispettoso**
- **Traduzione condizionale**: se `cv.language_source != "it"`, traduci

### Template email

**Per `advance`**:

```
Gentile [Nome],

grazie per aver inviato la tua candidatura per la posizione di [Ruolo].

Siamo lieti di comunicarti che il tuo profilo ha superato la fase di pre-screening.
[1-2 frasi sui punti di forza]

Ti contatteremo a breve per i prossimi step.

Cordiali saluti,
Il Team HR
```

**Per `hold`**:

```
Gentile [Nome],

grazie per aver inviato la tua candidatura per la posizione di [Ruolo].

Il tuo profilo è in valutazione. [Motivazione trasparente]

Ti aggiorneremo non appena avremo novità.

Cordiali saluti,
Il Team HR
```

**Per `reject`**:

```
Gentile [Nome],

grazie per aver inviato la tua candidatura per la posizione di [Ruolo].

Dopo attenta valutazione, abbiamo deciso di non procedere con il tuo profilo.
[Motivazione oggettiva basata su score.json]

Ti auguriamo il meglio per la tua ricerca.

Cordiali saluti,
Il Team HR
```

### Invio email

- **Test**: Mailpit (`mailpit:1026`)
- **Produzione**: SMTP aziendale o servizio transazionale (SendGrid, Mailgun)

---

## 🎯 Fase 25 — Ingestion email reale (IMAP)

### Obiettivo

Coprire lo step 1 del processo manuale:

> 1. Ricezione CV via email o piattaforma ATS

### Perché è importante

In produzione, il sistema deve ricevere i CV **automaticamente**, senza intervento manuale.

### Architettura

```
[Email a cv@azienda.it]
        ↓
[n8n: Email Trigger (IMAP)]
        ↓
[Estrazione allegati]
        ↓
[Fase 21: CV Analysis]
        ↓
[...]
```

### Setup

1. **Casella email dedicata**: `cv@azienda.it`
2. **Configurazione OAuth2** (Gmail) o credenziali IMAP
3. **n8n `Email Trigger (IMAP)` node**
4. **Estrazione allegati**: PDF, DOCX, immagini → binary
5. **Filtro**: solo email da candidati, no spam

### Alternative

- **Webhook da ATS**: se il cliente usa un ATS, integrazione via webhook
- **Form upload web**: form pubblico con webhook

### Costi

- **Zero LLM** (solo trigger + estrazione)
- **Zero costi aggiuntivi**

---

## 💰 Stima costi

### Costo per chiamata LLM

Modello: **Claude Sonnet 4.6** (Anthropic)

| Componente | Token input | Token output | Costo/chiamata |
|---|---|---|---|
| CV extraction | ~2600 | ~2500 | **~0.06€** |
| JD extraction | ~2000 | ~1500 | **~0.04€** |
| Scoring | ~3000 | ~1500 | **~0.05€** |
| Feedback | ~1000 | ~800 | **~0.02€** |

**Nota**: il costo include retry (~15%) e varia in base alla complessità del CV/JD.

### Costo per fase (senza cache)

| Fase | Chiamate LLM/CV | Costo/CV |
|---|---|---|
| Fase 21 — Estrazione CV | 1 | ~0.06€ |
| Fase 22a — JD Agent | 1 | ~0.04€ |
| Fase 22b — Matching | 0 | 0€ |
| Fase 22c — Scoring | 1 | ~0.05€ |
| Fase 23 — Audit log | 0 | 0€ |
| Fase 24 — Feedback | 1 | ~0.02€ |
| Fase 25 — IMAP | 0 | 0€ |
| **Totale** | **4** | **~0.17€** |

**A 500 CV/mese (senza cache)**: **~85€/mese**

### Costo con cache intelligente

La cache riutilizza:

- **Stesso CV** per più JD → CV extraction cached
- **Stessa JD** per più CV → JD extraction cached
- **Stessa coppia (CV, JD)** per rivalutazioni → matching + scoring cached

**Costo effettivo con cache** (500 CV, 20 JD):

| Voce | Chiamate/mese | Costo/mese |
|---|---|---|
| CV extraction (500 CV, cached) | 500 | ~30€ |
| JD extraction (20 JD, cached) | 20 | ~0.80€ |
| Scoring (500 coppie CV-JD) | 500 | ~25€ |
| Feedback (solo avanzati, ~10%) | 50 | ~1€ |
| **Totale** | **1070** | **~57€/mese** |

**Risparmio rispetto a senza cache**: ~33%

**Nota**: il costo cresce **linearmente con i CV** (dominante), ma **non con le JD** (grazie alla cache).

### Budget disponibile

**500€/mese**

### Margine

| Scenario | Costo | Margine |
|---|---|---|
| 500 CV, 20 JD, con cache | ~57€ | **~443€** |
| 1000 CV, 20 JD, con cache | ~114€ | **~386€** |
| 2000 CV, 20 JD, con cache | ~228€ | **~272€** |

**Il margine è ampio**, anche con crescita significativa.

### Ottimizzazioni future

Se il costo dovesse crescere:

1. **Modello più economico** per l'estrazione CV
   - Claude Haiku 4.5: ~10x più economico
   - Costo: ~0.006€/CV invece di 0.06€
   - **Risparmio**: 90%

2. **Modello locale** (open source)
   - Llama, Mistral su GPU locale
   - Costo: 0€/chiamata (ma serve hardware)
   - **Risparmio**: 100% (dopo ammortamento)

3. **Cache distribuita** (Redis)
   - Riduce latenza e chiamate duplicate
   - **Risparmio**: variabile (dipende dal carico)

---

## 📋 Decisioni di design

### Perché 3 livelli di scoring (LLM + deterministico + LLM)?

1. **Livello 1 (LLM)**: gestisce l'eterogeneità del linguaggio naturale nella JD
2. **Livello 2 (Python)**: matching oggettivo, ripetibile, tracciabile, zero costi
3. **Livello 3 (LLM)**: giudizio olistico, reasoning, motivazione

Questo garantisce:
- **Ripetibilità**: il matching è deterministico
- **Tracciabilità**: ogni step produce un JSON
- **Economicità**: solo 2 chiamate LLM per la Fase 22
- **Qualità**: il giudizio finale è olistico

### Perché human-in-the-loop sui casi RED?

- **AI Act art. 6**: sistema ad alto rischio per decisioni su impiego
- **Casi ambigui**: meglio il recruiter che l'LLM
- **Trasparenza**: il candidato riceve feedback da umano se il caso è critico

### Perché temperatura 0?

- **Ripetibilità**: stesso input → stesso output
- **Vincolo traccia**: "determinismo dove possibile"
- **Audit**: ogni decisione ricostruibile

### Perché Data Pinning?

- **Test senza costi**: evita chiamate LLM ripetute
- **Debug**: isola i nodi a valle
- **Non in produzione**: funziona solo per esecuzioni manuali

---

## 🔗 Riferimenti alla traccia

| Step traccia | Fase | Stato |
|---|---|---|
| 1. Ricezione CV | Fase 25 | 📋 Design |
| 2. Analisi CV | Fase 21 | ✅ Completa |
| 3. Estrazione dati | Fase 21 | ✅ Completa |
| 4. Confronto con JD | Fase 22 | 📋 Design |
| 5. Scoring qualitativo | Fase 22 | 📋 Design |
| 6. Comunicazione esito | Fase 24 | 📋 Design |
| 7. Archiviazione audit | Fase 23 | 📋 Design |

### Vincoli della traccia

| Vincolo | Fase che lo copre | Stato |
|---|---|---|
| GDPR | Fase 21 (CV mai committati) + Fase 23 (redazione PII) | ✅ / 📋 |
| AI Act art. 6 | Fase 21 (human-in-the-loop RED) + Fase 23 (audit) | ✅ / 📋 |
| CCNL | Fase 22 (no discriminazioni nel prompt) + Fase 24 (feedback) | 📋 |
| Affidabilità | Fase 21 (anti-allucinazione) + Fase 24 (feedback leale) | ✅ / 📋 |
| Ripetibilità | Fase 21 (temperatura 0) + Fase 22 (matching deterministico) | ✅ / 📋 |
| Tracciabilità | Fase 23 (audit log) | 📋 |
| Budget | Tutte (4 chiamate LLM/CV, ~57€/mese con cache) | ✅ |

---

## 📅 Priorità di implementazione

| Priorità | Fase | Motivo |
|---|---|---|
| **P0** | Fase 23 — Audit Log | Vincolo normativo (AI Act art. 6) |
| **P1** | Fase 22 — Confronto JD + Scoring | Cuore del processo |
| **P2** | Fase 24 — Comunicazione esito | Obiettivo del progetto |
| **P3** | Fase 25 — Ingestion email | In produzione |

**Nota**: la priorità P0 (audit log) può sembrare controintuitiva, ma è **obbligatoria per legge**. Senza di essa, il sistema non può essere messo in produzione su decisioni di impiego (AI Act art. 6).

---

## 📝 Note finali

### Cosa è già stato validato

- ✅ Fase 21 completa e funzionante
- ✅ Preflight check deterministico
- ✅ Agency detection
- ✅ Workflow n8n con routing GREEN/YELLOW/RED
- ✅ Gestione errori (AI Agent, parser, validazione)
- ✅ Data Pinning per test senza costi

### Cosa manca per chiudere il cerchio

- 📋 Fase 22: matching CV ↔ JD + scoring
- 📋 Fase 23: audit log PostgreSQL
- 📋 Fase 24: feedback candidato via email
- 📋 Fase 25: ingestion email reale

### Prossimi step operativi

1. Definire schema JD (`schemas/fase22_jd_output.json`)
2. Scrivere prompt JD Agent (`prompts/fase22_jd_system.txt`, `fase22_jd_user.txt`)
3. Implementare endpoint `/match` in `cv-extractor`
4. Scrivere prompt Scoring LLM
5. Aggiungere nodi in n8n
6. Aggiungere PostgreSQL allo stack
7. Testare end-to-end con CV + JD reali