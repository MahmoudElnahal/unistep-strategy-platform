"""
═══════════════════════════════════════════════════════════════════
PESTLE Factor Agent — وكيل لتحليل عامل واحد من الستة
═══════════════════════════════════════════════════════════════════

كل instance من FactorAgent مسؤول عن عامل واحد:
- Political | Economic | Social | Technology | Legal | Environmental

الـ workflow:
1. أخذ ClientInput
2. بناء user prompt مخصص للعامل ده
3. استدعاء LLM (gpt-4o)
4. parse JSON
5. تحويل لصيغة موحدة
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

from core.client_input import ClientInput
from core.llm_client import LLMClient
from steps.step_01_pestle.agents import prompts as pestle_prompts

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Factor mapping
# ═══════════════════════════════════════════════════════════════════
FACTOR_PROMPTS = {
    "political":     pestle_prompts.POLITICAL_PROMPT,
    "economic":      pestle_prompts.ECONOMIC_PROMPT,
    "social":        pestle_prompts.SOCIAL_PROMPT,
    "technology":    pestle_prompts.TECHNOLOGY_PROMPT,
    "legal":         pestle_prompts.LEGAL_PROMPT,
    "environmental": pestle_prompts.ENVIRONMENTAL_PROMPT,
}

FACTOR_LABELS_AR = {
    "political":     "السياسية",
    "economic":      "الاقتصادية",
    "social":        "الاجتماعية",
    "technology":    "التقنية",
    "legal":         "القانونية",
    "environmental": "البيئية",
}


@dataclass
class FactorDriver:
    name: str
    description: str
    impact: str  # high | medium | low


@dataclass
class FactorOpportunityOrThreat:
    title: str
    description: str


@dataclass
class FactorResult:
    """نتيجة تحليل عامل واحد"""
    factor: str  # political, economic, etc.
    factor_label_ar: str
    impact_level: str  # high | medium | low
    summary: str
    key_drivers: list[FactorDriver] = field(default_factory=list)
    opportunities: list[FactorOpportunityOrThreat] = field(default_factory=list)
    threats: list[FactorOpportunityOrThreat] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # للـ barriers_to_entry وغيره
    
    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "factor_label_ar": self.factor_label_ar,
            "impact_level": self.impact_level,
            "summary": self.summary,
            "key_drivers": [
                {"name": d.name, "description": d.description, "impact": d.impact}
                for d in self.key_drivers
            ],
            "opportunities": [
                {"title": o.title, "description": o.description}
                for o in self.opportunities
            ],
            "threats": [
                {"title": t.title, "description": t.description}
                for t in self.threats
            ],
            "extra": self.extra,
        }


# ═══════════════════════════════════════════════════════════════════
# Factor Agent
# ═══════════════════════════════════════════════════════════════════
class FactorAgent:
    """وكيل لتحليل عامل واحد من PESTLE"""
    
    def __init__(
        self,
        llm: LLMClient,
        factor: str,
        model: str = "gpt-4o",
    ):
        if factor not in FACTOR_PROMPTS:
            raise ValueError(f"Unknown factor: {factor}. Must be one of {list(FACTOR_PROMPTS.keys())}")
        self.llm = llm
        self.factor = factor
        self.model = model
        self.system_prompt = FACTOR_PROMPTS[factor]
    
    def _build_user_prompt(self, client: ClientInput) -> str:
        """بناء user prompt من معلومات الجمعية"""
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
        if client.vision:
            parts.append(f"## الرؤية: {client.vision}")
        if client.strategic_goals:
            goals_str = "، ".join(client.strategic_goals)
            parts.append(f"## الأهداف الاستراتيجية: {goals_str}")
        if client.sample_program:
            parts.append(f"## برنامج قائم: {client.sample_program}")
        if client.funding_sources:
            funding_str = "، ".join(client.funding_sources)
            parts.append(f"## مصادر التمويل: {funding_str}")
        
        parts.append(f"\n---\n\nحلّل العوامل **{FACTOR_LABELS_AR[self.factor]}** المؤثرة على هذه الجمعية.")
        return "\n".join(parts)
    
    def _parse_response(self, data: dict) -> FactorResult:
        """تحويل JSON response لـ FactorResult"""
        result = FactorResult(
            factor=self.factor,
            factor_label_ar=FACTOR_LABELS_AR[self.factor],
            impact_level=data.get("impact_level", "medium"),
            summary=data.get("summary", ""),
        )
        
        for d in data.get("key_drivers", []):
            result.key_drivers.append(FactorDriver(
                name=d.get("name", ""),
                description=d.get("description", ""),
                impact=d.get("impact", "medium"),
            ))
        
        for o in data.get("opportunities", []):
            result.opportunities.append(FactorOpportunityOrThreat(
                title=o.get("title", ""),
                description=o.get("description", ""),
            ))
        
        for t in data.get("threats", []):
            result.threats.append(FactorOpportunityOrThreat(
                title=t.get("title", ""),
                description=t.get("description", ""),
            ))
        
        # حقول إضافية (مثل barriers_to_entry للـ legal)
        for key in ("barriers_to_entry",):
            if key in data:
                result.extra[key] = data[key]
        
        return result
    
    def analyze(self, client: ClientInput) -> tuple[FactorResult, float]:
        """
        Run analysis for this factor.
        
        Returns:
            (FactorResult, cost_usd)
        """
        user_prompt = self._build_user_prompt(client)
        
        logger.info(f"🔍 Analyzing PESTLE factor: {self.factor}")
        
        data, cost_record = self.llm.chat_json(
            model=self.model,
            system=self.system_prompt,
            user=user_prompt,
            temperature=0.2,  # شوية creativity للتحليل
            max_tokens=3000,
        )
        
        result = self._parse_response(data)
        logger.info(
            f"  ✅ {self.factor}: {len(result.key_drivers)} drivers, "
            f"{len(result.opportunities)} opps, {len(result.threats)} threats"
            f" (cost: ${cost_record.cost_usd:.4f})"
        )
        
        return result, cost_record.cost_usd
