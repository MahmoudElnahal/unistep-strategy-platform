"""
═══════════════════════════════════════════════════════════════════
PESTLE Synthesizer — يجمع 6 عوامل ويولد ملخص استراتيجي
═══════════════════════════════════════════════════════════════════

بعد ما الـ 6 وكلاء يخلصوا، الـ synthesizer:
1. يأخذ مخرجات الـ 6 عوامل
2. يبني meta-prompt للـ LLM
3. يطلب: top opportunities, top threats, executive summary, posture
"""
import logging
from dataclasses import dataclass, field

from core.client_input import ClientInput
from core.llm_client import LLMClient
from steps.step_01_pestle.agents.factor_agent import FactorResult
from steps.step_01_pestle.agents.prompts import SYNTHESIZER_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class TopOpportunity:
    title: str
    description: str
    factors: list[str]  # which PESTLE factors connect
    priority: int


@dataclass
class TopThreat:
    title: str
    description: str
    factors: list[str]
    severity: str  # high | medium | low


@dataclass
class CrossFactorInsight:
    insight: str
    connected_factors: list[str]


@dataclass
class PestleSynthesis:
    """الملخص الاستراتيجي الناتج من توليف الـ 6 عوامل"""
    executive_summary: str
    top_opportunities: list[TopOpportunity] = field(default_factory=list)
    top_threats: list[TopThreat] = field(default_factory=list)
    strategic_posture: str = "balanced"  # defensive | offensive | balanced
    posture_rationale: str = ""
    cross_factor_insights: list[CrossFactorInsight] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "executive_summary": self.executive_summary,
            "top_opportunities": [
                {"title": o.title, "description": o.description,
                 "factors": o.factors, "priority": o.priority}
                for o in self.top_opportunities
            ],
            "top_threats": [
                {"title": t.title, "description": t.description,
                 "factors": t.factors, "severity": t.severity}
                for t in self.top_threats
            ],
            "strategic_posture": self.strategic_posture,
            "posture_rationale": self.posture_rationale,
            "cross_factor_insights": [
                {"insight": i.insight, "connected_factors": i.connected_factors}
                for i in self.cross_factor_insights
            ],
        }


class PestleSynthesizer:
    """يولّف نتائج الـ 6 عوامل في ملخص استراتيجي"""
    
    def __init__(self, llm: LLMClient, model: str = "gpt-4o"):
        self.llm = llm
        self.model = model
    
    def _build_user_prompt(
        self,
        client: ClientInput,
        factor_results: dict[str, FactorResult],
    ) -> str:
        parts = [
            f"# الجمعية: {client.name}",
            f"## القطاع: {client.sector} — {client.specialization}",
            f"## الفئة المستهدفة: {client.target_audience}",
            "",
            "# نتائج تحليل PESTLE",
            "",
        ]
        
        for factor_key, result in factor_results.items():
            parts.append(f"## العامل {result.factor_label_ar} (مستوى التأثير: {result.impact_level})")
            parts.append(f"**الملخص:** {result.summary}")
            parts.append("")
            
            if result.key_drivers:
                parts.append("**العوامل الرئيسية:**")
                for d in result.key_drivers:
                    parts.append(f"- {d.name} ({d.impact}): {d.description}")
                parts.append("")
            
            if result.opportunities:
                parts.append("**الفرص:**")
                for o in result.opportunities:
                    parts.append(f"- {o.title}: {o.description}")
                parts.append("")
            
            if result.threats:
                parts.append("**التهديدات:**")
                for t in result.threats:
                    parts.append(f"- {t.title}: {t.description}")
                parts.append("")
            
            parts.append("---")
            parts.append("")
        
        parts.append("الآن، ولّد الملخص الاستراتيجي بصيغة JSON المحددة في system prompt.")
        return "\n".join(parts)
    
    def synthesize(
        self,
        client: ClientInput,
        factor_results: dict[str, FactorResult],
    ) -> tuple[PestleSynthesis, float]:
        """
        Run synthesis on all 6 factor results.
        
        Returns:
            (PestleSynthesis, cost_usd)
        """
        logger.info("🎯 Synthesizing PESTLE results...")
        
        user_prompt = self._build_user_prompt(client, factor_results)
        
        data, cost_record = self.llm.chat_json(
            model=self.model,
            system=SYNTHESIZER_PROMPT,
            user=user_prompt,
            temperature=0.2,
            max_tokens=3000,
        )
        
        synthesis = PestleSynthesis(
            executive_summary=data.get("executive_summary", ""),
            strategic_posture=data.get("strategic_posture", "balanced"),
            posture_rationale=data.get("posture_rationale", ""),
        )
        
        for o in data.get("top_opportunities", []):
            synthesis.top_opportunities.append(TopOpportunity(
                title=o.get("title", ""),
                description=o.get("description", ""),
                factors=o.get("factors", []),
                priority=o.get("priority", 99),
            ))
        synthesis.top_opportunities.sort(key=lambda x: x.priority)
        
        for t in data.get("top_threats", []):
            synthesis.top_threats.append(TopThreat(
                title=t.get("title", ""),
                description=t.get("description", ""),
                factors=t.get("factors", []),
                severity=t.get("severity", "medium"),
            ))
        
        for i in data.get("cross_factor_insights", []):
            synthesis.cross_factor_insights.append(CrossFactorInsight(
                insight=i.get("insight", ""),
                connected_factors=i.get("connected_factors", []),
            ))
        
        logger.info(
            f"  ✅ Synthesis: {len(synthesis.top_opportunities)} opps, "
            f"{len(synthesis.top_threats)} threats, posture={synthesis.strategic_posture}"
            f" (cost: ${cost_record.cost_usd:.4f})"
        )
        
        return synthesis, cost_record.cost_usd
