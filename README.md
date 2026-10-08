# CV Preflight

Microservizio per il **pre-flight check di leggibilità** e l'**estrazione testo** di CV in formati eterogenei (PDF nativo, PDF scansionato, DOCX, immagini). Deterministico, zero chiamate LLM.

Progetto pilota per l'automazione del processo di recruiting di una PMI italiana, in conformità con **GDPR**, **AI Act Europeo (art. 6)** e **CCNL italiano**.

---

## 🎯 Obiettivo

Prima di inviare un CV a un LLM per scoring e valutazione, il sistema:

1. **Classifica il rischio di leggibilità** del documento (GREEN / YELLOW / RED)
2. **Estrae il testo** con il metodo più appropriato (nativo o OCR)
3. **Calcola metriche oggettive** (densità testo, confidence OCR, rumore, lingua, rotazione)
4. **Decide l'azione**: procedi, procedi con flag, oppure human review

Questo permette di:
- **Risparmiare chiamate LLM** su documenti illeggibili
- **Ridurre allucinazioni** (LLM lavora solo su testo pulito)
- **Rispettare l'AI Act** (human-in-the-loop sui casi dubbi)
- **Garantire tracciabilità** (ogni decisione è motivata da metriche)

---

## 🏗️ Architettura

