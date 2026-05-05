"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — Confidence System
═══════════════════════════════════════════════════════════════════

نظام درجات الثقة 🟢🟡🔴 لكل بيان مستخرج.

كل ConfidenceRecord بتحتفظ بـ:
- value (القيمة الفعلية)
- source_url (المصدر)
- exact_quote (الاقتباس الحرفي)
- level (HIGH/MEDIUM/LOW/UNAVAILABLE)
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    HIGH = "high"           # 🟢 من مصدر رسمي مباشر
    MEDIUM = "medium"       # 🟡 من مصدر ثانوي موثوق
    LOW = "low"             # 🔴 من مصدر واحد غير موثق
    UNAVAILABLE = "unavailable"  # ⚪ مش موجود — لا نخمّن
    
    @property
    def emoji(self) -> str:
        return {"high": "🟢", "medium": "🟡", "low": "🔴", "unavailable": "⚪"}[self.value]
    
    @property
    def label_ar(self) -> str:
        return {"high": "عالي", "medium": "متوسط", "low": "منخفض", "unavailable": "غير متاح"}[self.value]


class SourceTier(str, Enum):
    OFFICIAL_WEBSITE = "official_website"
    ANNUAL_REPORT = "annual_report"
    GOVERNMENT_DATA = "government_data"      # بيانات رسمية حكومية (لـ PESTLE)
    INTERNATIONAL_DATA = "international_data"  # World Bank, UN (لـ PESTLE)
    LINKEDIN = "linkedin"
    NEWS = "news"
    SOCIAL_MEDIA = "social_media"
    GOOGLE_SEARCH = "google_search"
    AI_INFERENCE = "ai_inference"
    USER_INPUT = "user_input"
    
    @property
    def default_confidence(self) -> ConfidenceLevel:
        return {
            "official_website": ConfidenceLevel.HIGH,
            "annual_report": ConfidenceLevel.HIGH,
            "government_data": ConfidenceLevel.HIGH,
            "international_data": ConfidenceLevel.HIGH,
            "user_input": ConfidenceLevel.HIGH,
            "linkedin": ConfidenceLevel.MEDIUM,
            "news": ConfidenceLevel.MEDIUM,
            "social_media": ConfidenceLevel.LOW,
            "google_search": ConfidenceLevel.LOW,
            "ai_inference": ConfidenceLevel.LOW,
        }[self.value]


class ConfidenceRecord(BaseModel):
    """سجل ثقة لقيمة واحدة"""
    value: Optional[Any] = None
    level: ConfidenceLevel = ConfidenceLevel.UNAVAILABLE
    source_url: Optional[str] = None
    source_tier: Optional[SourceTier] = None
    exact_quote: Optional[str] = None
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = None
    
    @property
    def is_available(self) -> bool:
        return self.level != ConfidenceLevel.UNAVAILABLE and self.value is not None
    
    @property
    def display_value(self) -> str:
        if not self.is_available:
            return "غير متاح"
        return f"{self.level.emoji} {self.value}"
    
    @classmethod
    def unavailable(cls, notes: Optional[str] = None) -> "ConfidenceRecord":
        return cls(level=ConfidenceLevel.UNAVAILABLE, notes=notes)
    
    @classmethod
    def from_official_source(cls, value: Any, source_url: str, exact_quote: str) -> "ConfidenceRecord":
        return cls(
            value=value, level=ConfidenceLevel.HIGH,
            source_url=source_url, source_tier=SourceTier.OFFICIAL_WEBSITE,
            exact_quote=exact_quote,
        )
    
    @classmethod
    def from_secondary_source(
        cls, value: Any, source_url: str,
        source_tier: SourceTier = SourceTier.LINKEDIN,
        exact_quote: Optional[str] = None,
    ) -> "ConfidenceRecord":
        return cls(
            value=value, level=ConfidenceLevel.MEDIUM,
            source_url=source_url, source_tier=source_tier, exact_quote=exact_quote,
        )


class ConfidenceSummary(BaseModel):
    """ملخص الثقة لمجموعة بيانات"""
    total_fields: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    unavailable_count: int = 0
    
    @property
    def availability_rate(self) -> float:
        if self.total_fields == 0:
            return 0.0
        available = self.high_count + self.medium_count + self.low_count
        return round(available / self.total_fields * 100, 1)
    
    @property
    def quality_score(self) -> float:
        if self.total_fields == 0:
            return 0.0
        weighted = self.high_count * 100 + self.medium_count * 60 + self.low_count * 30
        return round(weighted / self.total_fields, 1)
    
    @classmethod
    def from_records(cls, records: list[ConfidenceRecord]) -> "ConfidenceSummary":
        s = cls(total_fields=len(records))
        for r in records:
            if r.level == ConfidenceLevel.HIGH:
                s.high_count += 1
            elif r.level == ConfidenceLevel.MEDIUM:
                s.medium_count += 1
            elif r.level == ConfidenceLevel.LOW:
                s.low_count += 1
            else:
                s.unavailable_count += 1
        return s
