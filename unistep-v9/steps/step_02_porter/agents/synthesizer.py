"""
═══════════════════════════════════════════════════════════════════
Porter Synthesizer — تقييم التموضع التنافسي
═══════════════════════════════════════════════════════════════════
"""
import logging
from dataclasses import dataclass, field

from core.client_input import ClientInput
from core.llm_client import LLMClient
from steps.step_02_porter.agents.force_agent import ForceResult
from steps.step_02_porter.agents.prompts import COMPETITIVE_POSITION_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class StrongestForce:
    force: str
    force_label_ar: str
    rationale: str


@dataclass
class StrategicRecommendation:
    priority: int
    title: str
    description: str
    addresses_force: str


@dataclass
class CompetitivePosition:
    competitive_position: str  # strong | average | weak
    overall_attractiveness: str  # high | medium | low
    strongest_force: StrongestForce
    weakest_force: StrongestForce  # نفس الـ structure
    executive_summary: str
    strategic_recommendations: list[StrategicRecommendation] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "competitive_position": self.competitive_position,
            "overall_attractiveness": self.overall_attractiveness,
            "strongest_force": {
                "force": self.strongest_force.force,
                "force_label_ar": self.strongest_force.force_label_ar,
                "rationale": self.strongest_force.rationale,
            },
            "weakest_force": {
                "force": self.weakest_force.force,
                "force_label_ar": self.weakest_force.force_label_ar,
                "rationale": self.weakest_force.rationale,
            },
            "executive_summary": self.executive_summary,
            "strategic_recommendations": [
                {"priority": r.priority, "title": r.title,
                 "description": r.description, "addresses_force": r.addresses_force}
                for r in self.strategic_recommendations
            ],
        }


class CompetitivePositionSynthesizer:
    """يولّف نتائج الـ 5 قوى في تقييم التموضع التنافسي"""
    
    def __init__(self, llm: LLMClient, model: str = "gpt-4o"):
        self.llm = llm
        self.model = model
    
    def _build_user_prompt(
        self,
        client: ClientInput,
        force_results: dict[str, ForceResult],
    ) -> str:
        parts = [
            f"# الجمعية: {client.name}",
            f"## القطاع: {client.sector} — {client.specialization}",
            f"## الحجم: {client.organization_size or 'غير محدد'}",
            "",
            "# نتائج تحليل Porter's 5 Forces",
            "",
        ]
        
        for force_key, result in force_results.items():
            threat_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(result.threat_level, "⚪")
            parts.append(f"## {threat_emoji} {result.force_label_ar} (تهديد: {result.threat_level})")
            parts.append(f"**الملخص:** {result.summary}")
            
            if result.factors:
                parts.append("**العوامل المؤثرة:**")
                for f in result.factors[:5]:
                    parts.append(f"- {f.factor} ({f.impact}): {f.description}")
            
            if result.key_insights:
                parts.append("**رؤى رئيسية:**")
                for ins in result.key_insights:
                    parts.append(f"- {ins}")
            
            if result.strategic_implications:
                parts.append(f"**التضمينات الاستراتيجية:** {result.strategic_implications}")
            
            parts.append("---")
            parts.append("")
        
        parts.append("الآن، ولّد التقييم الاستراتيجي بصيغة JSON المحددة.")
        return "\n".join(parts)
    
    def synthesize(
        self,
        client: ClientInput,
        force_results: dict[str, ForceResult],
    ) -> tuple[CompetitivePosition, float]:
        logger.info("🎯 Synthesizing Porter results...")
        
        user_prompt = self._build_user_prompt(client, force_results)
        
        data, cost_record = self.llm.chat_json(
            model=self.model,
            system=COMPETITIVE_POSITION_PROMPT,
            user=user_prompt,
            temperature=0.2,
            max_tokens=3000,
        )
        
        # Parse strongest/weakest forces
        sf = data.get("strongest_force", {})
        wf = data.get("weakest_force", {})
        
        position = CompetitivePosition(
            competitive_position=data.get("competitive_position", "average"),
            overall_attractiveness=data.get("overall_attractiveness", "medium"),
            strongest_force=StrongestForce(
                force=sf.get("force", ""),
                force_label_ar=sf.get("force_label_ar", ""),
                rationale=sf.get("rationale", ""),
            ),
            weakest_force=StrongestForce(
                force=wf.get("force", ""),
                force_label_ar=wf.get("force_label_ar", ""),
                rationale=wf.get("rationale", ""),
            ),
            executive_summary=data.get("executive_summary", ""),
        )
        
        for r in data.get("strategic_recommendations", []):
            position.strategic_recommendations.append(StrategicRecommendation(
                priority=r.get("priority", 99),
                title=r.get("title", ""),
                description=r.get("description", ""),
                addresses_force=r.get("addresses_force", ""),
            ))
        position.strategic_recommendations.sort(key=lambda x: x.priority)
        
        logger.info(
            f"  ✅ Position: {position.competitive_position}, "
            f"attractiveness: {position.overall_attractiveness}, "
            f"{len(position.strategic_recommendations)} recommendations "
            f"(cost: ${cost_record.cost_usd:.4f})"
        )
        
        return position, cost_record.cost_usd
