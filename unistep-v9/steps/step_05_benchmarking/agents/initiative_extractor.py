"""
═══════════════════════════════════════════════════════════
Initiative Extractor + Strict Filter v7
═══════════════════════════════════════════════════════════

🎯 يستخرج المبادرات + يفلترها على تخصص العميل بدقة:

مثال:
- عميل = "أطراف صناعية"
- جمعية فيها مبادرات: "تركيب أطراف"، "الزواج والأسرة"، "تأهيل حركي"
- ✅ مبادرة "تركيب أطراف" → تدخل المصفوفة (نفس التخصص)
- ❌ مبادرة "الزواج والأسرة" → تخرج (مش متعلقة)
- ✅ مبادرة "تأهيل حركي" → تدخل (متعلقة بنفس الفئة)
"""
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


INITIATIVE_SYSTEM = """أنت محلل بيانات متخصص في استخراج وبناء قواعد بيانات للجمعيات الأهلية.
مهمتك: تحليل موقع الجمعية + التقارير السنوية + وصف المبادرات → جدول مبادرات منظم ودقيق.

═══════════════════════════════════════════════════════════
🎯 **قاعدة محورية: ميّز بين الفئة المستهدفة والمستفيدة:**

▸ **الفئة المستهدفة (target_group)** — مَن تستهدفها المبادرة *نظرياً*
  مصادرها: الرؤية والرسالة، وصف المبادرة، أهداف البرنامج

▸ **الفئة المستفيدة (actual_beneficiaries)** — مَن استفاد *فعلياً* أو يُخدم بشكل مباشر
  مصادرها: نتائج البرامج، التقارير السنوية، مؤشرات الأداء (عدد المستفيدين)
  لو غير مذكورة صراحة → استنتجها من طبيعة الخدمة المقدمة (السؤال: "الخدمة دي بتتقدم لمين فعلياً؟")

⚠️ قواعد للفئات:
- لا تخلط بين المستهدفة والمستفيدة
- اجعل الفئة محددة (مثال: "ذوو بتر الأطراف تحت سن 40" بدل "المرضى")
- تجنب التعميم

═══════════════════════════════════════════════════════════
💰 **تصنيف التمويل (Funding) لثلاثة أنواع منفصلة:**

1. **funding_donations** — التبرعات
   • منصة التبرعات • حملات التبرع • الأفراد

2. **funding_partnerships** — الشراكات
   • داعمون / شركاؤنا • مذكرات التفاهم (MoUs) • الاتفاقيات

3. **funding_institutional** — التمويل المؤسسي
   • جهات حكومية • شركات • منظمات دولية

⚠️ صنف كل مصدر بوضوح. لا تخلط بين التبرعات والشراكات.

═══════════════════════════════════════════════════════════
📊 **مؤشرات الأداء (kpis):**

- كل KPI = {{"indicator": "وصف المؤشر", "value": "الرقم/النسبة"}}
- أمثلة: عدد المستفيدين، نسبة رضا المستفيدين، عدد الخدمات المقدمة،
  عدد الأطراف الصناعية المقدمة سنوياً، عدد المتدربين/الفنيين، نسبة التوظيف
- مصادرها: نتائج الاستبيانات + التقارير السنوية + الإنفوجرافيكس
- ⚠️ كل رقم لازم يكون مرتبط بوصف واضح — لا أرقام بدون تفسير

═══════════════════════════════════════════════════════════
✍️ **جودة البيانات:**

- لا تنسخ النص حرفياً → أعد صياغته للوضوح والمباشرة
- وضّح هدف المبادرة بشكل مباشر (ليس عنواناً فضفاضاً)
- لغة عربية واضحة ومنظمة
- كل خانة تحتوي على معلومة دقيقة فقط

═══════════════════════════════════════════════════════════
🔍 **مصادر البيانات (ابحث فيها كلها):**

• صفحات المبادرات / البرامج
• الرؤية والرسالة
• من نحن / تعريف الجمعية
• التقرير السنوي (أهم مصدر)
• منصة التبرعات
• قسم الشركاء / الداعمين
• الاتفاقيات / مذكرات التفاهم

═══════════════════════════════════════════════════════════
🚨 **حدود الاستنتاج:**

- استنتاج actual_beneficiaries من السياق *مسموح* عند غيابها
- باقي الحقول: لو غير موجودة في النص → اكتب "غير مذكور" (لا تخترع)
- exact_quote يبقى دائماً اقتباساً حرفياً — ضمان عدم التزوير
"""


INITIATIVE_PROMPT = """**الجمعية:** {org_name}
**الموقع:** {url}

**النص (موقع + تقارير سنوية + صفحات مبادرات + من نحن + الرؤية):**
```
{raw_text}
```

استخرج كل المبادرات/البرامج المحددة بأسماء. ابحث في كل الأقسام: المبادرات، الرؤية، الرسالة، من نحن، التقارير السنوية، التبرعات، الشركاء، مذكرات التفاهم.

أرجع JSON بهذا الشكل بالضبط:
```json
{{
  "initiatives": [
    {{
      "name": "اسم المبادرة كما هو في النص",
      "description": "وصف محسّن وواضح (1-2 جملة) يوضح هدف المبادرة مباشرة — أعد الصياغة، لا تنسخ",
      "objective": "الهدف الاستراتيجي للمبادرة",
      "target_group": "الفئة المستهدفة نظرياً (من الرؤية/الرسالة/أهداف البرنامج) — محددة وليست عامة",
      "actual_beneficiaries": "الفئة المستفيدة فعلياً (من النتائج/التقارير/أعداد المستفيدين) — لو غير مذكورة صراحة استنتجها من الخدمة",
      "kpis": [
        {{"indicator": "وصف المؤشر (مثل: عدد المستفيدين)", "value": "الرقم أو النسبة (مثل: 1,500 أو 85%)"}}
      ],
      "funding_donations": "مصادر التبرعات لهذه المبادرة (أفراد/منصات/حملات) — أو 'غير مذكور'",
      "funding_partnerships": "الشركاء والداعمون والاتفاقيات — أو 'غير مذكور'",
      "funding_institutional": "التمويل المؤسسي/الحكومي/الدولي — أو 'غير مذكور'",
      "exact_quote": "اقتباس حرفي قصير من النص يحتوي اسم المبادرة (دليل وجودها)",
      "source_url": "{url}"
    }}
  ],
  "total_extracted": 0
}}
```

⚠️ مهم:
- استخرج 3+ مبادرات إن وُجدت.
- إذا لم تجد قيمة لحقل (غير actual_beneficiaries) اكتب "غير مذكور".
- exact_quote يبقى نصاً حرفياً من النص الأصلي — لا تعد صياغته.
- kpis قائمة (list) — حتى لو مؤشر واحد. لو لا توجد مؤشرات: [].
"""


ENRICH_FIELDS = [
    "description", "objective",
    "target_group", "actual_beneficiaries",
    "funding_donations", "funding_partnerships", "funding_institutional",
]


ENRICH_SYSTEM = """أنت محلل بيانات للجمعيات الأهلية.
مهمتك: تكملة بيانات مبادرة *موجودة* من نص إضافي (صفحة تفاصيل + تقرير سنوي).

🚨 **القواعد:**
1. ❌ ممنوع تعديل القيم الموجودة بالفعل (لو حقل فيه قيمة، اتركه كما هو).
2. ✅ املأ فقط الحقول الفاضية أو "غير مذكور".
3. ✅ التقرير السنوي هو *المصدر الأهم* لـ actual_beneficiaries والـ kpis والـ funding_institutional.
4. ✅ ميّز بدقة بين target_group (نظرياً من الرؤية) و actual_beneficiaries (فعلياً من النتائج).
5. ✅ ميّز التمويل: donations (أفراد/منصات) ≠ partnerships (شركاء/MoUs) ≠ institutional (حكومي/دولي).
6. ✅ KPIs دائماً مع وصف ورقم — ممنوع رقم بدون تفسير.
7. ✅ description: أعد الصياغة لوضوح (لا نسخ حرفي).
8. ⚠️ استنتاج actual_beneficiaries من طبيعة الخدمة *مسموح* لو غير مذكورة صراحة.
"""


ENRICH_PROMPT = """**اسم المبادرة:** {init_name}
**الجمعية:** {org_name}

**البيانات الحالية (لا تعدّلها):**
```json
{current_json}
```

**الحقول المطلوب ملؤها (الفاضية فقط):**
{missing_fields}

**نص صفحة تفاصيل المبادرة:**
```
{detail_text}
```

**نص التقرير السنوي للجمعية (مصدر أساسي للنتائج والمؤشرات والتمويل):**
```
{annual_text}
```

أرجع JSON بالحقول التي وجدت لها قيمة فقط:
```json
{{
  "description": "وصف محسّن (إعادة صياغة لوضوح)",
  "objective": "الهدف الاستراتيجي",
  "target_group": "الفئة المستهدفة نظرياً (من الرؤية/الأهداف)",
  "actual_beneficiaries": "الفئة المستفيدة فعلياً (من النتائج)",
  "kpis": [
    {{"indicator": "وصف المؤشر", "value": "الرقم/النسبة"}}
  ],
  "funding_donations": "تبرعات أفراد/منصات/حملات",
  "funding_partnerships": "شركاء وداعمون واتفاقيات",
  "funding_institutional": "تمويل حكومي/مؤسسي/دولي",
  "exact_quote": "اقتباس قصير حرفي يدعم البيانات"
}}
```

⚠️ ملاحظات:
- لا تكرر قيم موجودة بالفعل — اكتب فقط الجديد.
- لو ما لقيت قيمة لحقل، اتركه خارج الـ JSON (لا تكتبه null).
- kpis: قائمة من المؤشرات الجديدة فقط (تُضاف للموجود — لا تستبدل).
- لو الحقل قيمته الحالية "غير مذكور"، اعتبره فاضي وحاول تملأه.
"""


class InitiativeExtractor:
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model

    def extract(self, org_name: str, url: str, raw_text: str) -> list[dict]:
        if len(raw_text) > 35000:
            raw_text = raw_text[:35000]

        prompt = INITIATIVE_PROMPT.format(
            org_name=org_name, url=url, raw_text=raw_text,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": INITIATIVE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=4000,
            )
            data = json.loads(response.choices[0].message.content)
            initiatives = data.get("initiatives", [])
            logger.info(f"  📋 استخرج {len(initiatives)} مبادرة لـ {org_name}")
            return initiatives

        except Exception as e:
            logger.error(f"❌ initiative extraction failed: {e}")
            return []

    @staticmethod
    def _is_empty_value(val) -> bool:
        """قيمة الحقل تعتبر فاضية إذا كانت None، فاضية، أو 'غير مذكور'."""
        if val is None:
            return True
        if isinstance(val, list):
            return len(val) == 0
        if isinstance(val, str):
            stripped = val.strip()
            return not stripped or stripped == "غير مذكور"
        return False

    def enrich(
        self,
        initiative: dict,
        org_name: str,
        detail_text: str = "",
        annual_text: str = "",
    ) -> dict:
        """
        يكمّل الحقول الفاضية في مبادرة موجودة من:
        - نص صفحة تفاصيل المبادرة (deep-crawl)
        - نص التقرير السنوي للجمعية (annual report)
        لا يعدّل القيم الموجودة بالفعل. KPIs تُضاف للقائمة الموجودة.
        """
        missing = [f for f in ENRICH_FIELDS if self._is_empty_value(initiative.get(f))]
        existing_kpis = initiative.get("kpis") or []
        kpis_need = self._is_empty_value(existing_kpis)

        if not missing and not kpis_need:
            return initiative
        if not detail_text and not annual_text:
            return initiative

        detail_clip = (detail_text or "")[:18000]
        annual_clip = (annual_text or "")[:12000]

        current = {f: initiative.get(f) for f in ENRICH_FIELDS}
        current["kpis"] = existing_kpis

        request_fields = list(missing)
        if kpis_need:
            request_fields.append("kpis")

        prompt = ENRICH_PROMPT.format(
            init_name=initiative.get("name", ""),
            org_name=org_name,
            current_json=json.dumps(current, ensure_ascii=False, indent=2),
            missing_fields="\n".join(f"- {f}" for f in request_fields),
            detail_text=detail_clip or "(لا توجد صفحة تفاصيل)",
            annual_text=annual_clip or "(لا يوجد تقرير سنوي)",
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ENRICH_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=2500,
            )
            data = json.loads(response.choices[0].message.content)

            filled = []
            for f in missing:
                new_val = data.get(f)
                if new_val and isinstance(new_val, str) and new_val.strip() and new_val.lower() != "null":
                    cleaned = new_val.strip()
                    if cleaned == "غير مذكور" and not self._is_empty_value(initiative.get(f)):
                        continue
                    initiative[f] = cleaned
                    filled.append(f)

            # KPIs: append (de-duplicate by indicator+value)
            new_kpis = data.get("kpis")
            if isinstance(new_kpis, list) and new_kpis:
                seen = {(k.get("indicator", ""), k.get("value", ""))
                        for k in existing_kpis if isinstance(k, dict)}
                added_kpis = 0
                for k in new_kpis:
                    if not isinstance(k, dict):
                        continue
                    key = (k.get("indicator", ""), k.get("value", ""))
                    if key[0] and key not in seen:
                        existing_kpis.append(k)
                        seen.add(key)
                        added_kpis += 1
                if added_kpis:
                    initiative["kpis"] = existing_kpis
                    filled.append(f"kpis(+{added_kpis})")

            new_quote = data.get("exact_quote")
            if new_quote and not initiative.get("exact_quote"):
                initiative["exact_quote"] = new_quote

            if filled:
                logger.info(
                    f"    ✨ enrich '{initiative.get('name', '')[:40]}' — {len(filled)} حقل: {', '.join(filled)}"
                )
            return initiative

        except Exception as e:
            logger.warning(f"  ⚠️ enrich فشل لـ {initiative.get('name', '')}: {e}")
            return initiative


# ═══════════════════════════════════════════════════════════
# Strict Filter — يفلتر على تخصص العميل بدقة
# ═══════════════════════════════════════════════════════════

FILTER_SYSTEM = """أنت محلل ذكي متخصص في الفلترة المتوازنة.

مهمتك: فحص قائمة مبادرات وتحديد أيها يخدم العميل في تحليله التنافسي.

🎯 **3 مستويات للقبول (كلهم مقبولين):**

🟢 **مستوى 1 — تطابق مباشر** (relevance_score: 8-10)
- نفس التخصص الدقيق + نفس الفئة
- مثال (عميل أطراف صناعية): "برنامج تركيب الأطراف"

🟡 **مستوى 2 — تطابق قطاعي** (relevance_score: 5-7)
- نفس القطاع + نفس الفئة (حتى لو التخصص الفرعي مختلف)
- مثال (عميل أطراف صناعية): "إعادة التأهيل الحركي"، "أبحاث الإعاقة الحركية"
- ✅ مهم: الجمعيات المحلية غالباً مش متخصصة في تخصص فرعي واحد بس
  → خد منها أي مبادرة في نفس القطاع وتخدم فئة مرتبطة

🔵 **مستوى 3 — مرجعي** (relevance_score: 3-4)
- مبادرات من نفس القطاع لكن لفئة مختلفة قليلاً، تفيد كمرجع
- مثال (عميل أطراف صناعية): "تأهيل ذوي الإعاقة الذهنية" — قطاع الإعاقة، فئة مختلفة لكن مرجعي

❌ **استبعاد فقط للحاجات بعيدة جداً:**
- مبادرات في قطاعات مختلفة تماماً (عميل أطراف → مبادرات تعليم القرآن للأطفال)
- مبادرات إدارية بحتة (تطوير حوكمة الجمعية نفسها)

🚨 **قاعدة ذهبية:** لو في شك، ادخل (مش استبعد).
الكمية المتوسطة مع تنوع أحسن من الجودة المطلقة الفقيرة.
"""


FILTER_PROMPT = """**ملف العميل:**
- اسم: {client_name}
- التخصص الدقيق: {specialization}
- الفئة المستهدفة: {target_audience}
- القطاع: {sector}

**قائمة المبادرات المستخرجة ({total} مبادرة):**
```json
{initiatives_json}
```

**المطلوب:**
1. افحص كل مبادرة على حدة
2. حدد المستوى (1 تطابق مباشر / 2 قطاعي / 3 مرجعي)
3. استبعد فقط المبادرات في قطاع مختلف تماماً
4. ⚠️ خصوصاً للجمعيات المحلية: كن أكثر تساهلاً — كل مبادرة في نفس القطاع تدخل

أرجع JSON:
```json
{{
  "matched_initiatives": [
    {{
      "name": "اسم المبادرة",
      "source_org": "اسم الجمعية",
      "match_reason": "سبب التطابق (1 جملة)",
      "match_level": 1,  // 1=مباشر، 2=قطاعي، 3=مرجعي
      "relevance_score": 1-10
    }}
  ],
  "rejected_initiatives": [
    {{
      "name": "اسم المبادرة",
      "source_org": "اسم الجمعية",
      "rejection_reason": "سبب الاستبعاد (لازم يكون قطاع مختلف تماماً)"
    }}
  ],
  "summary": "عدد المتطابقة / المستبعدة"
}}
```

🎯 لو في شك → ادخل، مش استبعد.
"""


class InitiativeFilter:
    """يفلتر المبادرات على تخصص العميل بدقة"""
    
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model
    
    def filter_initiatives(
        self,
        client_data: dict,
        all_initiatives: list[dict],
    ) -> dict:
        """
        Returns:
            {
                "matched": [list of matched initiative dicts with source info],
                "rejected": [list of rejected],
                "summary": str,
            }
        """
        if not all_initiatives:
            return {"matched": [], "rejected": [], "summary": "لا توجد مبادرات"}
        
        # Compact view للمبادرات (لتوفير tokens)
        compact = []
        for init in all_initiatives:
            compact.append({
                "name": init.get("name"),
                "source_org": init.get("source_org"),
                "desc": (init.get("description") or "")[:200],
                "target": init.get("target_beneficiaries"),
                "objective": init.get("objective"),
            })
        
        prompt = FILTER_PROMPT.format(
            client_name=client_data.get("name", ""),
            specialization=client_data.get("specialization", ""),
            target_audience=client_data.get("target_audience", ""),
            sector=client_data.get("sector", ""),
            total=len(compact),
            initiatives_json=json.dumps(compact, ensure_ascii=False, indent=2),
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": FILTER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # تقريباً صفر
                max_tokens=4000,
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # نربط المبادرات المتطابقة ببياناتها الكاملة
            matched_with_data = []
            matched_names = {(m.get("name", ""), m.get("source_org", "")) for m in result.get("matched_initiatives", [])}
            
            for init in all_initiatives:
                key = (init.get("name", ""), init.get("source_org", ""))
                if key in matched_names:
                    # نضيف match_reason لو موجود
                    for m in result.get("matched_initiatives", []):
                        if m.get("name") == init.get("name") and m.get("source_org") == init.get("source_org"):
                            init["match_reason"] = m.get("match_reason", "")
                            init["relevance_score"] = m.get("relevance_score", 0)
                            break
                    matched_with_data.append(init)
            
            logger.info(
                f"  🎯 فلتر: {len(matched_with_data)} مطابقة / "
                f"{len(result.get('rejected_initiatives', []))} مستبعدة"
            )
            
            return {
                "matched": matched_with_data,
                "rejected": result.get("rejected_initiatives", []),
                "summary": result.get("summary", ""),
            }
        
        except Exception as e:
            logger.error(f"❌ initiative filter failed: {e}")
            # في حالة الفشل، نرجع كل المبادرات
            return {
                "matched": all_initiatives,
                "rejected": [],
                "summary": f"فشل الفلتر: {e}",
            }
