# UNISTEP Platform v9

منصة استشارية متكاملة لتشخيص الوضع الراهن للجمعيات غير الربحية في المملكة العربية السعودية.

**v9** = مشروع مستقل بالكامل، فيه كل حاجة من Wizard إلى Output. **3 خطوات جاهزة:**

| الخطوة | الإطار | الحالة |
|---|---|---|
| **Step 1 — PESTLE** | مسح البيئة الكلية (6 عوامل) | ✅ جاهز |
| **Step 2 — Porter** | تحليل القوى التنافسية الـ 5 | ✅ جاهز |
| **Step 5 — Benchmarking** | المقارنة مع 4 محلية + 3 دولية | ✅ جاهز |

## 🎯 المميزات

### Multi-Step Orchestration الذكي
- **Wave 1 (متوازي):** PESTLE + Benchmarking يشتغلوا في نفس الوقت
- **Wave 2 (متسلسل):** Porter يشتغل بعدهم لأنه بياخد منهم data
  - من Benchmarking: قائمة المنافسين الـ 7 (للقوة 1)
  - من PESTLE: العامل القانوني وحواجز الدخول (للقوة 3)

### Wizard 4 صفحات
1. الهوية الأساسية (إلزامي)
2. التموضع (اختياري لكن يحسّن النتائج)
3. البرامج والتمويل (اختياري)
4. اختيار الخطوات اللي تشتغل

### Confidence System 🟢🟡🔴
كل بيان مستخرج له:
- مستوى ثقة (HIGH/MEDIUM/LOW/UNAVAILABLE)
- مصدر URL
- اقتباس حرفي

### OCR للعربي + Fallback Search
- 3 طبقات OCR: pypdf → Tesseract `ara+eng` → GPT-4o Vision
- 4 طبقات Fallback: Annual Reports → LinkedIn → Social → News

## 🚀 التشغيل

### المتطلبات System
```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-ara poppler-utils

# Mac
brew install tesseract tesseract-lang poppler

# Windows: حمّل من https://github.com/UB-Mannheim/tesseract/wiki
```

### الإعداد
```bash
# 1. ثبّت deps
pip install -r requirements.txt

# 2. حط الـ API key
export OPENAI_API_KEY=sk-...

# 3. شغّل
./run.sh           # Linux/Mac
run.bat            # Windows
```

افتح http://localhost:8000

## 📁 البنية

```
unistep-v9/
├── core/                            ← المشترك بين كل الخطوات
│   ├── client_input.py              ← 12 حقل Wizard
│   ├── confidence.py                ← نظام 🟢🟡🔴
│   ├── pipeline_state.py            ← State + cross-step accessors
│   ├── orchestrator_base.py         ← Base class
│   └── llm_client.py                ← LLM wrapper مع cost tracking
│
├── steps/
│   ├── step_01_pestle/              ← Step 1 — PESTLE (NEW)
│   │   ├── orchestrator.py          ← parallel 6 factors + synthesis
│   │   ├── agents/
│   │   │   ├── prompts.py           ← 6 system prompts
│   │   │   ├── factor_agent.py      ← FactorAgent (per factor)
│   │   │   └── synthesizer.py       ← Strategic synthesis
│   │   └── generators/word_generator.py
│   │
│   ├── step_02_porter/              ← Step 2 — Porter (NEW)
│   │   ├── orchestrator.py          ← parallel 5 forces + cross-step
│   │   ├── agents/
│   │   │   ├── prompts.py           ← 5 force prompts
│   │   │   ├── force_agent.py       ← ForceAgent
│   │   │   └── synthesizer.py       ← Competitive position
│   │   └── generators/word_generator.py
│   │
│   └── step_05_benchmarking/        ← Step 5 — من v8
│       ├── orchestrator.py          ← Wrapper
│       ├── _legacy_orchestrator.py  ← v7 + 4+3 + enrichment
│       ├── agents/                  ← 9 وكلاء
│       └── generators/              ← Word + 4 Excel
│
├── api/main.py                      ← FastAPI v9 unified
├── ui/static/                       ← UI كاملة
│   ├── css/shared.css
│   ├── dashboard.html               ← الـ 12 خطوة
│   ├── wizard.html                  ← 4 صفحات
│   └── results.html                 ← SSE + downloads
├── runs/                            ← runtime data
├── tests/test_smoke.py              ← Smoke test
└── requirements.txt
```

## 🔑 API Endpoints

| Method | Path | الوصف |
|---|---|---|
| `GET`  | `/`                              | Dashboard |
| `GET`  | `/wizard`                        | Wizard 4 صفحات |
| `GET`  | `/run/{run_id}`                  | صفحة النتائج |
| `POST` | `/api/start`                     | بدء run |
| `GET`  | `/api/stream/{run_id}`           | SSE progress |
| `GET`  | `/api/state/{run_id}`            | حالة الـ run |
| `GET`  | `/api/result/{run_id}`           | النتيجة كاملة |
| `GET`  | `/api/result/{run_id}/{step_id}` | نتيجة خطوة واحدة |
| `GET`  | `/api/download/{run_id}/{file}`  | تحميل ملف |
| `GET`  | `/api/info`                      | معلومات المنصة |

## 🧪 Testing

```bash
PYTHONPATH=. python3 tests/test_smoke.py
```

## 💰 التكلفة المتوقعة (تقريبية)

| الخطوة | API Calls | التكلفة |
|---|---|---|
| PESTLE | 7 (6 عوامل + 1 synthesis) | ~$0.50 |
| Porter | 6 (5 قوى + 1 synthesis) | ~$0.45 |
| Benchmarking | متغيّرة | ~$2.50 |
| **الكل** | | **~$3.50** |

## 🛣️ خارطة الطريق

| Version | الخطوات الجديدة | الحالة |
|---|---|---|
| v8 | Refactor + OCR + Fallback + Confidence | ✅ |
| **v9** | **+ PESTLE + Porter + Wizard موحد** | **✅ هذا الإصدار** |
| v10 | + Steps 3, 4, 6 | 📅 |
| v11 | + Steps 7-11 (المرحلة الداخلية) | 📅 |
| v12 | + Step 12 (التوليف النهائي) | 📅 |
