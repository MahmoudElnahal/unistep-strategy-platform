"""
═══════════════════════════════════════════════════════════
Comparative Analyst v7
═══════════════════════════════════════════════════════════

ياخد المبادرات المفلترة (المتطابقة مع تخصص العميل) ويعمل:
1. تصنيف الفرص (إطلاق جديد / تطوير / توسع / شراكة)
2. Gap Analysis
3. Strategic Insights
4. توصيات

🚨 منع التكرار: كل مبادرة تظهر مرة واحدة في selected_initiatives
"""
import json
import logging
import re
from openai import OpenAI

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """أنت مستشار استراتيجي خبير في القطاع غير الربحي السعودي.
تعمل لشركة Unistep الاستشارية. خبرة 15 سنة في تحليل البرامج الخيرية.

🎯 معاييرك:
- المبادرة تتوافق مع الفئة المستهدفة للعميل
- المبادرة تتوافق مع الأهداف الاستراتيجية للعميل
- المبادرة قابلة للتطبيق في السعودية

🔴 أنواع الفرص (اختر واحدة فقط):
1. "إطلاق جديد": البرنامج غير موجود لدى العميل
2. "تطوير وتحسين": البرنامج موجود لكن يحتاج رفع كفاءة
3. "توسع جغرافي": البرنامج ناجح في منطقة ويحتاج تعميماً
4. "شراكة استراتيجية": يتطلب شريكاً خارجياً

🚨 قواعد صارمة:
1. ❌ لا تكرر مبادرة في selected_initiatives
2. ❌ لا تختر نفس المبادرة من جمعيتين — اختر النسخة الأقوى
3. ✅ Gap Analysis: 3-5 عناصر لكل قسم
4. ✅ Strategic Insights: 3 رؤى متمايزة
5. ✅ Top recommendations: 3 توصيات بأولويات مختلفة
6. ❌ ممنوع اختراع
"""


USER_PROMPT_TEMPLATE = """**بيانات العميل:**
- الاسم: {client_name}
- التخصص الدقيق: {specialization}
- الفئة المستهدفة: {target_audience}
- البرامج الحالية: {current_programs}
- الأهداف:
{goals_formatted}

**المبادرات المتطابقة (مفلترة بالفعل على تخصصك):**
```json
{initiatives_json}
```

أرجع JSON:
```json
{{
  "selected_initiatives": [
    {{
      "name": "اسم المبادرة (فريد)",
      "source_org": "اسم الجمعية المصدر",
      "what_it_does": "ماذا تفعل (جملة)",
      "target_beneficiaries": "من تخدم",
      "achievements": "أرقام إن وجدت",
      "funding_source": "من يموّلها",
      "opportunity_type": "إطلاق جديد | تطوير وتحسين | توسع جغرافي | شراكة استراتيجية",
      "rationale": "لماذا لهذا العميل بالذات",
      "applicability_score": 1-10,
      "implementation_difficulty": "سهلة | متوسطة | صعبة"
    }}
  ],
  "gap_analysis": {{
    "missing_programs": [
      "🚨 3-5 برامج موجودة عند المنافسين وغير موجودة عند العميل",
      "كل عنصر بـ 1-2 جملة محددة مع ذكر الجمعية المرجعية"
    ],
    "weak_areas": [
      "🚨 3-5 مجالات يحتاج العميل تطويرها"
    ],
    "competitive_advantages": [
      "🚨 3-5 نقاط قوة للعميل الحالية"
    ]
  }},
  "strategic_insights": [
    "🚨 3 رؤى متمايزة جوهرياً"
  ],
  "top_3_recommendations": [
    {{
      "priority": 1,
      "action": "إجراء عملي محدد",
      "expected_impact": "أثر كمي متوقع",
      "timeframe": "قصير | متوسط | طويل"
    }}
  ]
}}
```

🚨 لا تكرر مبادرات. 5-8 مبادرات مختارة كافية.
"""


class ComparativeAnalyst:
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model
    
    def analyze(self, client_data: dict, all_initiatives: list[dict]) -> dict:
        if not all_initiatives:
            return self._empty_result("لا توجد مبادرات للتحليل")
        
        goals = client_data.get("strategic_goals") or []
        if isinstance(goals, list):
            goals_formatted = "\n".join(f"  {i+1}. {g}" for i, g in enumerate(goals))
        else:
            goals_formatted = f"  {goals}"
        
        # Compact
        compact = []
        for init in all_initiatives:
            compact.append({
                "name": init.get("name"),
                "source_org": init.get("source_org"),
                "country": init.get("source_country", ""),
                "desc": init.get("description"),
                "target": init.get("target_beneficiaries"),
                "objective": init.get("objective"),
                "metric": init.get("metric"),
                "results": init.get("results"),
                "funding_type": init.get("funding_type"),
            })
        
        prompt = USER_PROMPT_TEMPLATE.format(
            client_name=client_data.get("name", ""),
            specialization=client_data.get("specialization", ""),
            target_audience=client_data.get("target_audience", ""),
            current_programs=client_data.get("sample_program") or "غير محدد",
            goals_formatted=goals_formatted,
            initiatives_json=json.dumps(compact, ensure_ascii=False, indent=2),
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=5000,
            )
            
            data = json.loads(response.choices[0].message.content)
            data = self._deduplicate(data)
            
            logger.info(
                f"  🎯 Analysis: "
                f"{len(data.get('selected_initiatives', []))} مبادرة, "
                f"{len(data.get('strategic_insights', []))} رؤى"
            )
            return data
        
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")
            return self._empty_result(str(e))
    
    def _deduplicate(self, data: dict) -> dict:
        """يزيل المبادرات المكررة"""
        seen = set()
        unique = []
        
        for init in data.get("selected_initiatives", []):
            name = init.get("name", "").strip().lower()
            name = re.sub(r'\s+', ' ', name)
            
            if name and name not in seen:
                seen.add(name)
                unique.append(init)
            else:
                logger.warning(f"⚠️ تم حذف مبادرة مكررة: {init.get('name')}")
        
        data["selected_initiatives"] = unique
        return data
    
    def _empty_result(self, reason: str) -> dict:
        return {
            "selected_initiatives": [],
            "gap_analysis": {"missing_programs": [], "weak_areas": [], "competitive_advantages": []},
            "strategic_insights": [],
            "top_3_recommendations": [],
            "error": reason,
        }
