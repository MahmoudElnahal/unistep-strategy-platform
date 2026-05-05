"""
═══════════════════════════════════════════════════════════
Validator v7.1 — حسب الـ 9 صفوف اللي طلبهم المستخدم
═══════════════════════════════════════════════════════════

🎯 الـ 6 إلزاميين (بس نقبل لو 5/6 — التمويل اختياري):
- name (اسم الجهة)
- field_of_work (مجال العمل)
- target_audience (الفئة المستهدفة)
- programs (أسماء البرامج والمبادرات)
- metrics_results (المؤشرات وعدد المستفيدين)
- funding_sources (مصادر التمويل) — نحاول نجيبها من PDFs

🟢 مرنة (نحاول، لو ما لقيناش مش مشكلة)::
- region, vision, mission, strategic_goals

⚠️ منطق القبول:
- لازم 5 من الـ 6 إلزاميين على الأقل
- التمويل لو فاضي → نقبل (لأن كثير مواقع ما بتنشرش تمويلها)
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FieldValidation:
    field_name: str
    value: Optional[str]
    exact_quote: Optional[str]
    source_url: Optional[str]
    passed: bool
    reason: str = ""


@dataclass
class OrganizationValidation:
    organization_name: str
    fields: list[FieldValidation] = field(default_factory=list)
    accepted: bool = False
    completeness: float = 0.0
    passed_count: int = 0
    failed_count: int = 0
    rejection_reason: str = ""
    
    vision_2030_compliant: bool = False
    vision_2030_keywords: list[str] = field(default_factory=list)
    
    def get_field(self, name: str) -> Optional[FieldValidation]:
        for f in self.fields:
            if f.field_name == name:
                return f
        return None


# ═══ تصنيف الحقول v7.1 (الـ 9 صفوف اللي طلبهم المستخدم) ═══
FIELD_CATEGORIES = {
    # 🔴 إلزامية (6 حقول — نقبل لو 5/6 على الأقل)
    "mandatory": [
        "name",              # الصف 1 — اسم الجهة
        "field_of_work",     # الصف 3 — مجال العمل
        "target_audience",   # الصف 4 — الفئة المستهدفة
        "programs",          # الصف 7 — أسماء البرامج والمبادرات
        "metrics_results",   # الصف 8 — المؤشرات وعدد المستفيدين
        "funding_sources",   # الصف 9 — مصادر التمويل (نحاول نجيبها من PDFs)
    ],

    # 🟢 مرنة — نحاول نجيبها بس مش حاسمة للقبول
    "flexible": [
        "region",            # الصف 2 — المنطقة الجغرافية
        "vision",            # الصف 5 (جزء)
        "mission",           # الصف 5 (جزء)
        "strategic_goals",   # الصف 6 — الأهداف الاستراتيجية
    ],
}

ALL_FIELDS = FIELD_CATEGORIES["mandatory"] + FIELD_CATEGORIES["flexible"]

# نقبل لو 5 من الـ 6 إلزاميين نجحوا (التمويل اختياري لأن صعب يطلع من المواقع)
MIN_MANDATORY = 5


VISION_2030_KEYWORDS = [
    "جودة الحياة", "تمكين", "استدامة", "تحول رقمي", "شفافية",
    "حوكمة", "تنمية القطاع غير الربحي", "ريادة الأعمال", "اقتصاد المعرفة",
    "التنوع", "الابتكار", "العمل التطوعي", "المشاركة المجتمعية",
    "رؤية 2030", "vision 2030",
    "empowerment", "sustainability", "transparency",
    "governance", "innovation", "digital transformation",
]


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',
        'ى': 'ي', 'ة': 'ه', 'ـ': '',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.lower()


def quote_exists_in_text(quote: str, raw_text: str, min_match_ratio: float = 0.6) -> bool:
    """تحقق إن quote موجود في raw_text (أكثر مرونة من v6)"""
    if not quote or not raw_text:
        return False
    
    quote_norm = normalize_arabic(quote)
    raw_norm = normalize_arabic(raw_text)
    
    if len(quote_norm) < 8:
        return False
    
    if quote_norm in raw_norm:
        return True
    
    quote_words = [w for w in quote_norm.split() if len(w) > 2]
    if len(quote_words) < 3:
        return False
    
    found_words = sum(1 for w in quote_words if w in raw_norm)
    match_ratio = found_words / len(quote_words)
    
    return match_ratio >= min_match_ratio


def validate_field(field_name: str, field_data: dict, raw_text: str) -> FieldValidation:
    if not isinstance(field_data, dict):
        field_data = {"value": str(field_data) if field_data else None}
    
    value = field_data.get("value")
    exact_quote = field_data.get("exact_quote")
    source_url = field_data.get("source_url")
    
    # حالة 1: null
    if not value or value in ["null", "None", "غير متاح", "غير مفصح عنه", "N/A", "غير محدد"]:
        return FieldValidation(
            field_name=field_name,
            value=None, exact_quote=None, source_url=None,
            passed=False, reason="غير متاح في المصادر"
        )
    
    # حالة 2: قيمة بدون quote
    if not exact_quote:
        return FieldValidation(
            field_name=field_name,
            value=value, exact_quote=None, source_url=source_url,
            passed=False, reason="❌ لا يوجد exact_quote"
        )
    
    # حالة 3: التحقق
    if quote_exists_in_text(exact_quote, raw_text):
        return FieldValidation(
            field_name=field_name,
            value=value, exact_quote=exact_quote, source_url=source_url,
            passed=True, reason="✅ تم التحقق"
        )
    else:
        return FieldValidation(
            field_name=field_name,
            value=value, exact_quote=exact_quote, source_url=source_url,
            passed=False, reason="⚠️ الاقتباس غير موجود حرفياً"
        )


def check_vision_2030(extracted_data: dict) -> tuple[bool, list[str]]:
    text_to_check = ""
    
    for fname in ["vision", "mission", "strategic_goals", "field_of_work"]:
        fdata = extracted_data.get(fname, {})
        if isinstance(fdata, dict):
            v = fdata.get("value", "")
            if v:
                text_to_check += " " + str(v)
    
    if not text_to_check.strip():
        return False, []
    
    text_lower = text_to_check.lower()
    matched = []
    for kw in VISION_2030_KEYWORDS:
        if kw.lower() in text_lower:
            matched.append(kw)
    
    return len(matched) >= 1, matched


def validate_organization(
    org_name: str,
    extracted_data: dict,
    raw_text: str,
) -> OrganizationValidation:
    """
    منطق القبول v7:
    - الـ 3 الإلزاميات (target_audience, strategic_goals, programs) لازم تنجح
    - باقي الحقول: نحاول، لو ما نجحتش مش مشكلة
    """
    result = OrganizationValidation(organization_name=org_name)

    # Validate كل الحقول
    for fname in ALL_FIELDS:
        fdata = extracted_data.get(fname, {})
        validation = validate_field(fname, fdata, raw_text)

        # ⭐ استثناء: حقل الاسم — نعرفه من الـ discovery، ما يحتاجش exact_quote
        # لو الاسم اتعرف من الـ URL/Discovery، يبقى auto-pass
        if fname == "name" and not validation.passed and org_name:
            # هل اسم الجمعية موجود في الـ raw_text؟ (تحقق سريع)
            org_norm = normalize_arabic(org_name)
            raw_norm = normalize_arabic(raw_text)
            org_words = [w for w in org_norm.split() if len(w) > 2]
            if org_words:
                found = sum(1 for w in org_words if w in raw_norm)
                if found / len(org_words) >= 0.4:
                    validation = FieldValidation(
                        field_name="name",
                        value=org_name,
                        exact_quote=org_name,
                        source_url=fdata.get("source_url") if isinstance(fdata, dict) else None,
                        passed=True,
                        reason="✅ معروف من Discovery",
                    )

        result.fields.append(validation)

        if validation.passed:
            result.passed_count += 1
        else:
            result.failed_count += 1
    
    # Vision 2030 (informational فقط)
    v2030, kws = check_vision_2030(extracted_data)
    result.vision_2030_compliant = v2030
    result.vision_2030_keywords = kws
    
    # Completeness
    result.completeness = result.passed_count / len(ALL_FIELDS)
    
    # ⭐ القرار: 5 من الـ 6 إلزاميين على الأقل (التمويل اختياري)
    mandatory_passed = sum(
        1 for f in result.fields
        if f.field_name in FIELD_CATEGORIES["mandatory"] and f.passed
    )

    missing = [
        f.field_name for f in result.fields
        if f.field_name in FIELD_CATEGORIES["mandatory"] and not f.passed
    ]

    if mandatory_passed >= MIN_MANDATORY:
        result.accepted = True
        if missing:
            logger.info(f"  ⚠️ {org_name} مقبولة لكن ناقصها: {', '.join(missing)}")
    else:
        # استثناء: لو الناقص هو التمويل بس + حقل تاني واحد، نقبلها برضه
        non_funding_missing = [m for m in missing if m != "funding_sources"]
        if len(non_funding_missing) <= 1 and mandatory_passed >= 4:
            result.accepted = True
            logger.info(f"  ⚠️ {org_name} مقبولة استثناءً (ناقصها: {', '.join(missing)})")
        else:
            result.accepted = False
            result.rejection_reason = f"حقول إلزامية ناقصة: {', '.join(missing)}"

    return result


def get_validation_summary(validation: OrganizationValidation) -> str:
    icon = "✅" if validation.accepted else "❌"
    lines = [
        f"{icon} {validation.organization_name}",
        f"   الاكتمال: {validation.completeness * 100:.0f}% ({validation.passed_count}/{len(ALL_FIELDS)})",
        f"   رؤية 2030: {'✓' if validation.vision_2030_compliant else '✗'}",
    ]
    if not validation.accepted:
        lines.append(f"   ❌ {validation.rejection_reason}")
    return "\n".join(lines)
