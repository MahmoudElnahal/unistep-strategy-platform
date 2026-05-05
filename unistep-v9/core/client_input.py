"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — Client Input Schema (Unified)
═══════════════════════════════════════════════════════════════════

12 حقل موزّعة على 4 صفحات Wizard:

📄 صفحة 1 (الهوية):     name, sector, specialization, target_audience,
                        num_employees, year_founded
📄 صفحة 2 (التموضع):    region, vision, mission, strategic_goals
📄 صفحة 3 (البرامج):    sample_program, current_kpis, funding_sources
📄 صفحة 4 (الخطوات):    selected_steps (مش schema field — في API request)

كل الـ 12 خطوة بتاخد ClientInput دي. كل خطوة تستخدم اللي يلزمها.
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field, model_validator


class ClientInput(BaseModel):
    """مدخلات الجمعية العميل — 12 حقل لكل الخطوات"""
    
    # ═══════════════════════════════════════════════════
    # 🔴 الصفحة 1 — الهوية الأساسية (إلزامية)
    # ═══════════════════════════════════════════════════
    name: str = Field(..., min_length=2, description="اسم الجمعية")
    sector: str = Field(..., description="القطاع العام (رعاية اجتماعية، صحة، تعليم...)")
    specialization: str = Field(..., description="التخصص الدقيق والفرعي")
    target_audience: str = Field(..., description="الفئة المستهدفة بالتفصيل")
    num_employees: Optional[int] = Field(None, ge=0, description="عدد الموظفين (لتحديد الحجم)")
    year_founded: Optional[int] = Field(None, ge=1900, le=2030, description="سنة التأسيس")
    
    organization_size: Optional[Literal["صغيرة", "متوسطة", "كبيرة"]] = Field(
        None, description="صغيرة (<20) | متوسطة (20-50) | كبيرة (>50)"
    )
    
    # ═══════════════════════════════════════════════════
    # 🟡 الصفحة 2 — التموضع
    # ═══════════════════════════════════════════════════
    region: Optional[str] = Field(None, description="المنطقة الجغرافية")
    vision: Optional[str] = Field(None, description="الرؤية")
    mission: Optional[str] = Field(None, description="الرسالة")
    strategic_goals: Optional[list[str]] = Field(None, description="الأهداف الاستراتيجية (3-5)")
    
    # ═══════════════════════════════════════════════════
    # ⚪ الصفحة 3 — البرامج والتمويل
    # ═══════════════════════════════════════════════════
    sample_program: Optional[str] = Field(None, description="مثال على برنامج قائم")
    current_kpis: Optional[str] = Field(None, description="مؤشرات الأداء الحالية")
    funding_sources: Optional[list[str]] = Field(None, description="مصادر التمويل")
    
    # ═══════════════════════════════════════════════════
    # Auto-calculation
    # ═══════════════════════════════════════════════════
    @model_validator(mode="after")
    def auto_calculate_size(self):
        """لو مفيش organization_size، احسبها من num_employees"""
        if self.organization_size is None and self.num_employees is not None:
            if self.num_employees < 20:
                self.organization_size = "صغيرة"
            elif self.num_employees <= 50:
                self.organization_size = "متوسطة"
            else:
                self.organization_size = "كبيرة"
        return self
    
    def to_v7_dict(self) -> dict:
        """تحويل لصيغة v7 dict (لـ Step 5 Benchmarking)"""
        return {
            "name": self.name,
            "sector": self.sector,
            "specialization": self.specialization,
            "target_audience": self.target_audience,
            "organization_size": self.organization_size or "متوسطة",
            "region": self.region,
            "sample_program": self.sample_program,
            "current_kpis": self.current_kpis,
            "funding_sources": self.funding_sources,
            "strategic_goals": self.strategic_goals,
            "vision": self.vision,
            "mission": self.mission,
        }


def get_size_from_employees(num: int) -> Literal["صغيرة", "متوسطة", "كبيرة"]:
    """تحديد الحجم حسب عدد الموظفين"""
    if num < 20:
        return "صغيرة"
    elif num <= 50:
        return "متوسطة"
    else:
        return "كبيرة"


# ═══════════════════════════════════════════════════════════════════
# كلمات رؤية المملكة 2030
# ═══════════════════════════════════════════════════════════════════
VISION_2030_KEYWORDS = [
    "جودة الحياة", "تمكين", "استدامة", "تحول رقمي", "شفافية",
    "حوكمة", "تنمية القطاع غير الربحي", "ريادة الأعمال", "اقتصاد المعرفة",
    "التنوع", "الابتكار", "الاستثمار في الإنسان", "العمل التطوعي",
    "المشاركة المجتمعية", "التطوير المؤسسي", "رؤية 2030",
    "vision 2030", "empowerment", "sustainability", "transparency",
    "governance", "innovation", "digital transformation", "quality of life",
]


def check_vision_2030_compliance(text: str) -> dict:
    """فحص توافق نص مع رؤية 2030"""
    if not text:
        return {"compliant": False, "matched_keywords": [], "score": 0}
    text_lower = text.lower()
    matched = [kw for kw in VISION_2030_KEYWORDS if kw.lower() in text_lower]
    return {
        "compliant": len(matched) >= 1,
        "matched_keywords": matched,
        "score": min(100, len(matched) * 25),
    }


# ═══════════════════════════════════════════════════════════════════
# معايير اختيار المنافسين (لـ Step 5)
# ═══════════════════════════════════════════════════════════════════
SELECTION_CRITERIA = {
    "mandatory": [
        {"id": "target_match", "label": "تطابق الفئة المستهدفة"},
        {"id": "specialization_match", "label": "نفس التخصص الدقيق"},
        {"id": "diverse_programs", "label": "تنوع البرامج"},
        {"id": "institutional_maturity", "label": "النضج المؤسسي"},
        {"id": "vision_2030_alignment", "label": "التوافق مع رؤية 2030"},
    ],
    "important": [
        {"id": "geographic_coverage", "label": "التغطية الجغرافية"},
        {"id": "data_availability", "label": "توفر البيانات"},
        {"id": "diverse_beneficiaries", "label": "تنوع الفئات"},
    ],
}
