"""
═══════════════════════════════════════════════════════════════════
Porter Force Agent — وكيل لتحليل قوة واحدة من الخمسة
═══════════════════════════════════════════════════════════════════
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from core.client_input import ClientInput
from core.llm_client import LLMClient
from steps.step_02_porter.agents import prompts as porter_prompts

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Force mapping
# ═══════════════════════════════════════════════════════════════════
FORCE_PROMPTS = {
    "direct_competitors": porter_prompts.DIRECT_COMPETITORS_PROMPT,
    "substitutes":        porter_prompts.SUBSTITUTES_PROMPT,
    "new_entrants":       porter_prompts.NEW_ENTRANTS_PROMPT,
    "donor_power":        porter_prompts.DONOR_POWER_PROMPT,
    "supplier_power":     porter_prompts.SUPPLIER_POWER_PROMPT,
}

FORCE_LABELS_AR = {
    "direct_competitors": "حدّة المنافسة الحالية",
    "substitutes":        "تهديد البدائل",
    "new_entrants":       "تهديد الوافدين الجدد",
    "donor_power":        "القوة التفاوضية للممولين",
    "supplier_power":     "القوة التفاوضية للكوادر والموردين",
}

FORCE_DESCRIPTIONS = {
    "direct_competitors": "كم منافس وما مدى التشابه بينهم وبين جمعيتك",
    "substitutes":        "بدائل المستفيدين والممولين عن خدمات الجمعية",
    "new_entrants":       "صعوبة دخول جمعيات جديدة لنفس المجال",
    "donor_power":        "مدى تأثير الممولين على شروط التمويل",
    "supplier_power":     "مدى ندرة الكفاءات والكوادر",
}


@dataclass
class ForceFactor:
    factor: str
    description: str
    impact: str  # high | medium | low


@dataclass
class ForceResult:
    """نتيجة تحليل قوة واحدة"""
    force: str
    force_label_ar: str
    threat_level: str  # high | medium | low
    summary: str
    factors: list[ForceFactor] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    strategic_implications: str = ""
    
    def to_dict(self) -> dict:
        return {
            "force": self.force,
            "force_label_ar": self.force_label_ar,
            "threat_level": self.threat_level,
            "summary": self.summary,
            "factors": [
                {"factor": f.factor, "description": f.description, "impact": f.impact}
                for f in self.factors
            ],
            "key_insights": self.key_insights,
            "strategic_implications": self.strategic_implications,
        }


# ═══════════════════════════════════════════════════════════════════
# Force Agent
# ═══════════════════════════════════════════════════════════════════
class ForceAgent:
    """وكيل لتحليل قوة واحدة من Porter's 5 Forces"""
    
    def __init__(
        self,
        llm: LLMClient,
        force: str,
        model: str = "gpt-4o",
    ):
        if force not in FORCE_PROMPTS:
            raise ValueError(f"Unknown force: {force}")
        self.llm = llm
        self.force = force
        self.model = model
        self.system_prompt = FORCE_PROMPTS[force]
    
    def _build_user_prompt(
        self,
        client: ClientInput,
        context: Optional[dict] = None,
    ) -> str:
        """
        بناء user prompt من معلومات الجمعية + context إضافي.
        
        context قد يحتوي على:
        - competitors (للـ direct_competitors): قائمة الجمعيات من Benchmarking
        - legal_factor (للـ new_entrants): تحليل العامل القانوني من PESTLE
        """
        parts = [
            f"# الجمعية: {client.name}",
            f"## القطاع: {client.sector}",
            f"## التخصص: {client.specialization}",
            f"## الفئة المستهدفة: {client.target_audience}",
        ]
        
        if client.organization_size:
            parts.append(f"## الحجم: {client.organization_size}")
        if client.region:
            parts.append(f"## المنطقة: {client.region}")
        if client.year_founded:
            parts.append(f"## سنة التأسيس: {client.year_founded}")
        if client.funding_sources:
            parts.append(f"## مصادر التمويل: {'، '.join(client.funding_sources)}")
        if client.sample_program:
            parts.append(f"## برنامج قائم: {client.sample_program}")
        
        # Cross-step context
        if context:
            # للـ direct_competitors — قائمة الجمعيات من Benchmarking
            if self.force == "direct_competitors" and context.get("competitors"):
                parts.append("\n# الجمعيات المنافسة (من تحليل Benchmarking سابق):\n")
                for i, comp in enumerate(context["competitors"][:7], 1):
                    name = comp.get("name", "—")
                    country = comp.get("country", "—")
                    org_type = comp.get("type", "—")
                    parts.append(f"{i}. {name} ({org_type} — {country})")
                    
                    # برامجهم (لو متاحة)
                    val = comp.get("validation")
                    if val:
                        passed = val.get("passed_count", 0)
                        total = val.get("total_count", 0)
                        parts.append(f"   - نضج البيانات: {passed}/{total} حقول مكتملة")
                parts.append("")
            
            # للـ new_entrants — العامل القانوني من PESTLE
            if self.force == "new_entrants" and context.get("legal_factor"):
                legal = context["legal_factor"]
                parts.append("\n# تحليل العامل القانوني (من PESTLE):\n")
                parts.append(f"**الملخص:** {legal.get('summary', '—')}")
                
                # حواجز الدخول لو متاحة
                extra = legal.get("extra", {})
                bte = extra.get("barriers_to_entry")
                if bte:
                    parts.append(f"\n**حواجز الدخول:** مستوى {bte.get('level', '—')}")
                    parts.append(f"{bte.get('description', '')}")
                    reqs = bte.get("key_requirements", [])
                    if reqs:
                        parts.append("**المتطلبات الرئيسية:**")
                        for r in reqs:
                            parts.append(f"- {r}")
                parts.append("")
        
        parts.append(f"\n---\n\nحلّل **{FORCE_LABELS_AR[self.force]}** للجمعية.")
        return "\n".join(parts)
    
    def _parse_response(self, data: dict) -> ForceResult:
        result = ForceResult(
            force=self.force,
            force_label_ar=FORCE_LABELS_AR[self.force],
            threat_level=data.get("threat_level", "medium"),
            summary=data.get("summary", ""),
            strategic_implications=data.get("strategic_implications", ""),
            key_insights=data.get("key_insights", []),
        )
        
        for f in data.get("factors", []):
            result.factors.append(ForceFactor(
                factor=f.get("factor", ""),
                description=f.get("description", ""),
                impact=f.get("impact", "medium"),
            ))
        
        return result
    
    def analyze(
        self,
        client: ClientInput,
        context: Optional[dict] = None,
    ) -> tuple[ForceResult, float]:
        """
        Run analysis for this force.
        
        Args:
            client: ClientInput
            context: cross-step data (competitors, legal_factor, etc.)
        
        Returns:
            (ForceResult, cost_usd)
        """
        user_prompt = self._build_user_prompt(client, context)
        
        logger.info(f"⚔️ Analyzing Porter force: {self.force}")
        
        data, cost_record = self.llm.chat_json(
            model=self.model,
            system=self.system_prompt,
            user=user_prompt,
            temperature=0.2,
            max_tokens=2500,
        )
        
        result = self._parse_response(data)
        logger.info(
            f"  ✅ {self.force}: threat_level={result.threat_level}, "
            f"{len(result.factors)} factors (cost: ${cost_record.cost_usd:.4f})"
        )
        
        return result, cost_record.cost_usd
