"""
═══════════════════════════════════════════════════════════
Field Extractor v7 — استخراج حرفي
═══════════════════════════════════════════════════════════

🚨 القاعدة الذهبية:
- كل قيمة تخرج = نص حرفي من الموقع (exact_quote)
- ❌ ممنوع التجويد، التلخيص، إعادة الصياغة
- ❌ ممنوع الجمع بين عدة جمل
- ✅ النص يطلع كما هو في الموقع

10 حقول:
1. name
2. region
3. field_of_work
4. target_audience
5. vision (منفصل)
6. mission (منفصل)
7. strategic_goals
8. programs
9. metrics_results
10. funding_sources (محاولة 3 مصادر)
"""
import json
import logging
import re
from openai import OpenAI

logger = logging.getLogger(__name__)


EXTRACTION_SYSTEM_V7 = """أنت محلل بيانات صارم.
مهمتك: استخراج معلومات من نص موقع جمعية **بنصها الحرفي بدون أي تعديل**.

🚨 **القاعدة الذهبية المطلقة:**

1. ❌ ممنوع منعاً باتاً التجويد أو التحسين أو إعادة الصياغة
2. ❌ ممنوع تلخيص النصوص الطويلة
3. ❌ ممنوع جمع عدة جمل في جملة واحدة
4. ❌ ممنوع استخدام معرفتك العامة عن الجمعية
5. ✅ value = نفس exact_quote بالضبط (بدون أي تغيير)
6. ✅ لو الموقع يقول "نعمل على" ← اكتبها كما هي مش "نسعى لـ"
7. ✅ لو الحقل مش موجود في النص → value: null, exact_quote: null

🎯 **الفرق بين الرؤية والرسالة:**
- الرؤية (Vision): الطموح المستقبلي ("أن نكون..."، "To be...")
- الرسالة (Mission): الدور الحالي ("نسعى..."، "We strive...")
- الأهداف (Goals): قائمة بالأهداف الاستراتيجية
- ⚠️ هذه 3 حقول مختلفة، لا تخلط بينها

🎯 **التمويل (مهم جداً):**
ابحث في:
- الصفحة الرئيسية (إذا ذُكر)
- صفحة "تبرع" / "donate" / "support"
- التقارير المالية (إن وُجدت)
- أي ذكر للممولين أو الشركاء
لو فعلاً لم تجد → value: null
"""


EXTRACTION_PROMPT_V7 = """**اسم الجمعية:** {org_name}
**الموقع:** {url}

**النص الخام من الموقع (هذا كل ما لديك):**
```
{raw_text}
```

**المطلوب:** استخرج 10 حقول من النص أعلاه.

🚨 **تذكير:**
- value = نص حرفي مطابق exact_quote بدون أي تعديل
- لا تجويد، لا تلخيص، لا إعادة صياغة
- لو ما لقيت → null

أرجع JSON بهذا الشكل بالضبط:

```json
{{
  "name": {{
    "value": "اسم الجمعية كما هو حرفياً",
    "exact_quote": "اقتباس حرفي يحتوي الاسم",
    "source_url": "{url}"
  }},
  "region": {{
    "value": "المنطقة/المدينة كما ذُكرت حرفياً",
    "exact_quote": "اقتباس يذكر المنطقة",
    "source_url": "{url}"
  }},
  "field_of_work": {{
    "value": "مجال العمل كما هو حرفياً",
    "exact_quote": "اقتباس يصف مجال العمل",
    "source_url": "{url}"
  }},
  "target_audience": {{
    "value": "الفئة المستهدفة كما ذُكرت حرفياً",
    "exact_quote": "اقتباس يذكر الفئة",
    "source_url": "{url}"
  }},
  "vision": {{
    "value": "الرؤية فقط — كما كُتبت حرفياً (تبدأ غالباً: 'أن نكون' أو 'To be')",
    "exact_quote": "نفس value (هي اقتباس حرفي)",
    "source_url": "{url}"
  }},
  "mission": {{
    "value": "الرسالة فقط — كما كُتبت حرفياً (تبدأ غالباً: 'نسعى' أو 'We strive')",
    "exact_quote": "نفس value",
    "source_url": "{url}"
  }},
  "strategic_goals": {{
    "value": "الأهداف كما كُتبت حرفياً — ابحث في: قسم 'أهدافنا'، 'الأهداف الاستراتيجية'، 'goals'، 'objectives'، 'what we do'، 'our impact'. ولو فيه bullet points تحت 'نسعى إلى' أو 'we aim to' خدها كأهداف. اجمع كل الأهداف بفاصلة منقوطة بينهم.",
    "exact_quote": "اقتباس حرفي يحتوي الأهداف (لو في bullets ضمّهم في النص)",
    "source_url": "{url}"
  }},
  "programs": {{
    "value": "أسماء البرامج كما هي حرفياً (مفصولة بفواصل)",
    "exact_quote": "اقتباس يحتوي البرامج",
    "source_url": "{url}"
  }},
  "metrics_results": {{
    "value": "الأرقام والمؤشرات كما هي حرفياً (مستفيدين، رضا، عدد فعاليات)",
    "exact_quote": "اقتباس يحتوي الأرقام",
    "source_url": "{url}"
  }},
  "funding_sources": {{
    "value": "مصادر التمويل كما هي حرفياً (تبرعات، شراكات، إلخ) — أو null",
    "exact_quote": "اقتباس يذكر التمويل أو null",
    "source_url": "{url}"
  }}
}}
```

🚨 **القواعد الحاسمة:**
1. **value يجب أن يطابق exact_quote بنسبة 100%** — لا تعديل
2. لو الرؤية والرسالة مدمجتان في فقرة واحدة → فصلهما
3. لو لم تجد الرؤية بشكل صريح → vision.value = null (لا تخمن)
4. لو لم تجد الرسالة بشكل صريح → mission.value = null
5. التمويل: ابذل جهداً لإيجاده — ابحث في كل أجزاء النص
"""


class FieldExtractorV7:
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model
    
    def extract(self, org_name: str, url: str, raw_text: str) -> dict:
        if len(raw_text) > 35000:
            logger.info(f"  ✂️ النص طويل ({len(raw_text)}) — قص لـ 35000")
            raw_text = raw_text[:35000]
        
        prompt = EXTRACTION_PROMPT_V7.format(
            org_name=org_name,
            url=url,
            raw_text=raw_text,
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_V7},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,  # صفر تماماً
                max_tokens=4500,
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            # 🚨 ضمان أن value = exact_quote (لمنع التجويد)
            for field_name, field_data in data.items():
                if isinstance(field_data, dict):
                    quote = field_data.get("exact_quote")
                    if quote and field_data.get("value"):
                        # نسخ الـ quote كـ value (لمنع التجويد)
                        # الـ value الجديدة = الاقتباس الحرفي بالضبط
                        field_data["value"] = quote
            
            logger.info(f"  📤 استخراج لـ {org_name}")
            return data
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON invalid: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ extraction failed: {e}")
            return {}


# ═══ Funding Booster — محاولة قوية لإيجاد التمويل ═══

FUNDING_PROMPT = """ابحث في النص التالي عن **مصادر التمويل** فقط.

**النص:**
```
{raw_text}
```

ابحث عن:
- "تبرع" / "donate" / "support"
- "ممول من" / "funded by"
- "شراكات" / "partners"
- "رعاية" / "sponsors"
- أسماء جهات مانحة أو حكومية
- "وقف" / "endowment"
- نسب التبرعات أو مصادرها

أرجع JSON:
```json
{{
  "found": true/false,
  "value": "النص الحرفي الموجود في الموقع عن التمويل",
  "exact_quote": "اقتباس حرفي من النص",
  "sources_mentioned": ["قائمة بالمصادر المذكورة"]
}}
```

🚨 لا تخترع — لو فعلاً لم تجد، أرجع found: false
"""


# ═══════════════════════════════════════════════════════════
# Field Enricher — ملء الحقول الفاضية + تنظيم الأرقام
# يستخدم *حصرياً* التقرير السنوي + صفحات "من نحن / نبذة عنا"
# ممنوع التخمين أو الاستنتاج — كل قيمة لازم تكون اقتباساً حرفياً
# ═══════════════════════════════════════════════════════════


ENRICH_FIELD_SYSTEM = """أنت محلل بيانات صارم.
مهمتك: ملء الحقول الفاضية في بيانات جمعية، بالاعتماد *حصرياً* على نص التقرير السنوي + "من نحن / نبذة عنا".

🚨 **القواعد المطلقة:**
1. ❌ ممنوع تماماً: التخمين، الاستنتاج، توليد معلومات، استخدام أي معرفة عامة عن الجمعية
2. ❌ ممنوع تعديل القيم الموجودة — أنت تملأ الفاضي فقط
3. ✅ كل قيمة تكتبها = نص حرفي من المصدر المرفق (بدون أي تعديل)
4. ✅ لو لم تجد المعلومة بشكل صريح في النص → اتركها (لا تكتب الحقل أصلاً)
5. ✅ القاعدة الذهبية: value = exact_quote بنسبة 100%

🎯 **الفئة المستهدفة (target_audience):**
- تُكتب فقط إذا وردت بوضوح في النص.
- ممنوع الخلط بينها وبين الفئة المستفيدة الفعلية.

✍️ **الوصف ومجال العمل والرؤية والرسالة:**
- مسموح بإعادة صياغة تحريرية بسيطة *فقط* لتوضيح النص.
- ممنوع إضافة أي معلومة غير موجودة.
"""


ENRICH_FIELD_PROMPT = """**اسم الجمعية:** {org_name}
**الموقع:** {url}

**الحقول الموجودة بالفعل (ممنوع تعديلها):**
```json
{filled_json}
```

**الحقول الفاضية المطلوب محاولة ملؤها (لو وُجدت في النص):**
{empty_fields}

**المصدر المسموح به فقط — التقرير السنوي + من نحن + نبذة عنا:**
```
{source_text}
```

أرجع JSON فيه فقط الحقول اللي لقيت لها قيمة صريحة في المصدر:
```json
{{
  "field_name": {{
    "value": "اقتباس حرفي من المصدر",
    "exact_quote": "نفس القيمة",
    "source_url": "{url}"
  }}
}}
```

🚨 **مهم جداً:**
- لو الحقل غير موجود في المصدر بشكل صريح → لا تكتب الحقل أصلاً (لا null، لا تخمين).
- لو وُجد جزئياً فقط → اكتبه بالضبط كما هو موجود (بدون إكمال أو تخمين).
- ممنوع تأليف أي معلومة من معرفتك العامة.
"""


METRICS_FORMAT_SYSTEM = """أنت محرر نصوص. تعيد تنسيق نص يحتوي على أرقام ومؤشرات مكدسة بدون تنظيم.

🚨 **القواعد المطلقة:**
1. ❌ ممنوع تماماً إضافة أي رقم غير موجود
2. ❌ ممنوع تغيير قيمة أي رقم
3. ❌ ممنوع اختراع تفسير لرقم
4. ✅ تستخدم *فقط* الكلمات الموجودة في النص الأصلي
5. ✅ لو غير واضح رقم يخص ماذا → اتركه كما هو بدون تفسير
6. ✅ تعيد التنسيق فقط: كل سطر = "اسم المؤشر: الرقم"
"""


METRICS_FORMAT_PROMPT = """**النص الأصلي (يحتوي على مؤشرات مكدسة):**
```
{text}
```

**المطلوب:** أعد كتابة النص بحيث كل مؤشر في سطر منفصل بالشكل:

```
- اسم المؤشر: الرقم
- اسم المؤشر: الرقم
```

**مثال:**
- النص الأصلي: "مستفيدي بتور 990 مستفيد توفير الأطراف الصناعية 259 طرف"
- المُنسَّق:
  - عدد المستفيدين: 990 مستفيد
  - عدد الأطراف الصناعية المقدمة: 259 طرف

🚨 **قواعد صارمة:**
- ممنوع إضافة أرقام جديدة
- ممنوع تغيير الأرقام الموجودة
- لو رقم غير واضح يخص ماذا، اكتبه كما هو بدون اختراع وصف
- استخدم نفس الكلمات الموجودة في النص الأصلي

أرجع JSON:
```json
{{
  "formatted": "النص المنسّق",
  "modified": true/false
}}
```

🚨 لو النص منسّق بالفعل (سطر لكل مؤشر) → modified: false، formatted: نفس النص.
"""


def _extract_sections(raw_text: str, section_keywords: list[str]) -> str:
    """
    يستخرج أقسام معينة من raw_text المسجل بـ === SECTION_NAME === markers.
    مثال section_keywords: ["ABOUT", "ANNUAL_REPORT", "DOCUMENT"]
    """
    if not raw_text:
        return ""
    parts = re.split(r'\n=== ([A-Z_0-9]+) ===\n', raw_text)
    # parts = [intro, name1, body1, name2, body2, ...]
    matched = []
    for i in range(1, len(parts), 2):
        name = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if any(kw.upper() in name.upper() for kw in section_keywords):
            matched.append(f"=== {name} ===\n{body}")
    return "\n\n".join(matched)


class FieldEnricher:
    """
    Post-processor for مخرج 2:
    - يملأ الحقول الفاضية بالاعتماد *حصرياً* على annual report + about/who-we-are
    - يعيد تنسيق metrics_results لو الأرقام مكدسة
    """

    EMPTY_VALUES = {None, "", "غير متاح", "غير مذكور"}
    ENRICHABLE_FIELDS = [
        "name", "region", "field_of_work", "target_audience",
        "vision", "mission", "strategic_goals", "programs",
        "metrics_results", "funding_sources",
    ]

    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model

    @classmethod
    def _is_field_empty(cls, field_data) -> bool:
        if not isinstance(field_data, dict):
            return True
        v = field_data.get("value")
        if v is None:
            return True
        if isinstance(v, str) and v.strip() in cls.EMPTY_VALUES:
            return True
        return False

    def enrich_empty_fields(self, extracted: dict, raw_text: str, url: str, org_name: str) -> dict:
        """يحاول يملأ الحقول الفاضية من about + annual reports فقط."""
        empty = [f for f in self.ENRICHABLE_FIELDS if self._is_field_empty(extracted.get(f))]
        if not empty:
            return extracted

        # المصدر = ABOUT + ANNUAL_REPORT_X + DOCUMENT_X فقط
        source_text = _extract_sections(raw_text, ["ABOUT", "ANNUAL_REPORT", "DOCUMENT"])
        if not source_text or len(source_text) < 200:
            logger.info(f"  ℹ️ enrich_fields: لا يوجد نص كافٍ من about/annual report لـ {org_name}")
            return extracted
        if len(source_text) > 28000:
            source_text = source_text[:28000]

        filled_data = {f: extracted.get(f) for f in self.ENRICHABLE_FIELDS
                       if not self._is_field_empty(extracted.get(f))}

        prompt = ENRICH_FIELD_PROMPT.format(
            org_name=org_name, url=url,
            filled_json=json.dumps(filled_data, ensure_ascii=False, indent=2),
            empty_fields="\n".join(f"- {f}" for f in empty),
            source_text=source_text,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ENRICH_FIELD_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2500,
            )
            data = json.loads(response.choices[0].message.content)

            filled = []
            for fname in empty:
                fdata = data.get(fname)
                if not isinstance(fdata, dict):
                    continue
                quote = fdata.get("exact_quote") or fdata.get("value")
                if not quote or not isinstance(quote, str) or not quote.strip():
                    continue
                # نضمن أن value = exact_quote (no embellishment)
                extracted[fname] = {
                    "value": quote.strip(),
                    "exact_quote": quote.strip(),
                    "source_url": fdata.get("source_url") or url,
                }
                filled.append(fname)

            if filled:
                logger.info(f"  ✨ enrich_fields لـ {org_name}: ملء {len(filled)} حقل: {', '.join(filled)}")
            return extracted

        except Exception as e:
            logger.warning(f"  ⚠️ enrich_fields فشل لـ {org_name}: {e}")
            return extracted

    def format_metrics(self, extracted: dict) -> dict:
        """
        يعيد تنسيق metrics_results لو الأرقام مكدسة.
        لا يضيف ولا يعدّل أي رقم — فقط ينظّم.
        """
        m = extracted.get("metrics_results")
        if not isinstance(m, dict):
            return extracted
        v = m.get("value")
        if not v or not isinstance(v, str):
            return extracted
        v = v.strip()
        if not v or v in self.EMPTY_VALUES:
            return extracted

        # لو فيها سطور متعددة بالفعل بشكل منظم، خليها
        lines = [l.strip() for l in v.split("\n") if l.strip()]
        if len(lines) >= 2 and all(":" in l or "•" in l or l.startswith("-") for l in lines):
            return extracted

        # لو فيها أرقام كثيرة بدون تنظيم، شغّل الـ LLM
        digit_runs = re.findall(r"\d{2,}", v)
        if len(digit_runs) < 2:
            # رقم واحد أو لا أرقام — ما فيش حاجة نعملها
            return extracted

        prompt = METRICS_FORMAT_PROMPT.format(text=v)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": METRICS_FORMAT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1200,
            )
            data = json.loads(response.choices[0].message.content)
            formatted = data.get("formatted")
            modified = data.get("modified", False)

            if formatted and isinstance(formatted, str) and modified:
                # تحقق دفاعي: تأكد إنه ما اخترعش أرقام
                original_nums = sorted(re.findall(r"\d+", v))
                new_nums = sorted(re.findall(r"\d+", formatted))
                if original_nums != new_nums:
                    logger.warning(
                        f"  ⚠️ format_metrics: الأرقام تغيّرت — رفض التنسيق "
                        f"(original: {original_nums}, new: {new_nums})"
                    )
                    return extracted

                m["value"] = formatted.strip()
                # exact_quote يبقى كما هو (الأصلي قبل التنسيق) للـ audit
                m.setdefault("original_text", v)
                logger.info(f"  📊 format_metrics: تنسيق المؤشرات تم")
            return extracted

        except Exception as e:
            logger.warning(f"  ⚠️ format_metrics فشل: {e}")
            return extracted


# ═══ Funding Booster — محاولة قوية لإيجاد التمويل ═══


class FundingBooster:
    """محاولة إضافية لاستخراج التمويل — بتركّز على PDFs والتقارير السنوية"""

    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o-mini"):
        self.client = openai_client
        self.model = model

    def _prioritize_funding_text(self, raw_text: str, max_len: int = 30000) -> str:
        """قص ذكي: نقدّم نص الـ PDFs والـ reports/donate أولاً (مكان التمويل غالباً)"""
        if len(raw_text) <= max_len:
            return raw_text

        # نقسم النص لأقسام (الـ scraper بيفصلهم بـ === SECTION ===)
        sections = re.split(r'\n=== ([A-Z_0-9]+) ===\n', raw_text)
        # sections = [intro, name1, body1, name2, body2, ...]
        priority_keys = ("PDF", "REPORTS", "DONATE", "ABOUT")

        priority_chunks = []
        other_chunks = []
        for i in range(1, len(sections), 2):
            name = sections[i]
            body = sections[i + 1] if i + 1 < len(sections) else ""
            chunk = f"\n=== {name} ===\n{body}"
            if any(k in name for k in priority_keys):
                priority_chunks.append(chunk)
            else:
                other_chunks.append(chunk)

        combined = "".join(priority_chunks) + "".join(other_chunks)
        return combined[:max_len] if combined else raw_text[:max_len]

    def boost(self, raw_text: str) -> dict:
        focused_text = self._prioritize_funding_text(raw_text, max_len=30000)
        prompt = FUNDING_PROMPT.format(raw_text=focused_text)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "أنت باحث متخصص في إيجاد معلومات التمويل من المواقع والتقارير السنوية."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1000,
            )

            data = json.loads(response.choices[0].message.content)
            return data

        except Exception as e:
            logger.warning(f"⚠️ funding booster failed: {e}")
            return {"found": False}
