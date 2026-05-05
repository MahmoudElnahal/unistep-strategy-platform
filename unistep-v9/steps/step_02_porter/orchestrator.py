"""
═══════════════════════════════════════════════════════════════════
Porter's 5 Forces Step Orchestrator
═══════════════════════════════════════════════════════════════════

Pipeline:
1. اقرا الـ context من state:
   - competitors من Benchmarking output (لـ Force 1)
   - legal_factor من PESTLE output (لـ Force 3)
2. شغّل الـ 5 قوى بشكل متوازي (مع تمرير الـ context للقوى المعنية)
3. شغّل synthesizer لـ Competitive Position
4. تجميع المخرج النهائي
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from core.client_input import ClientInput
from core.llm_client import LLMClient
from core.orchestrator_base import StepOrchestrator
from core.pipeline_state import PipelineState, StepID
from steps.step_02_porter.agents.force_agent import (
    ForceAgent, ForceResult, FORCE_LABELS_AR,
)
from steps.step_02_porter.agents.synthesizer import CompetitivePositionSynthesizer

logger = logging.getLogger(__name__)


# الـ 5 قوى بالترتيب
FORCES = [
    "direct_competitors",
    "substitutes",
    "new_entrants",
    "donor_power",
    "supplier_power",
]


class PorterStep(StepOrchestrator):
    """Step 2 — Porter's 5 Forces"""
    
    STEP_ID = StepID.PORTER
    
    def __init__(
        self,
        openai_client: OpenAI = None,
        model: str = "gpt-4o",
        progress_callback=None,
        max_workers: int = 3,
    ):
        super().__init__(progress_callback=progress_callback)
        
        if openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")
            openai_client = OpenAI(api_key=api_key)
        
        self.llm = LLMClient(openai_client)
        self.model = model
        self.max_workers = max_workers
    
    def _gather_context(self, state: PipelineState) -> dict:
        """يبني الـ cross-step context"""
        context = {}
        
        # Force 1: المنافسون من Benchmarking
        competitors = state.get_competitors_from_benchmarking()
        if competitors:
            context["competitors"] = competitors
            logger.info(f"  ✓ Loaded {len(competitors)} competitors from Benchmarking")
        else:
            logger.info("  ⚠️ No competitors from Benchmarking (force 1 will use generic analysis)")
        
        # Force 3: العامل القانوني من PESTLE
        legal_factor = state.get_legal_factor_from_pestle()
        if legal_factor:
            context["legal_factor"] = legal_factor
            logger.info("  ✓ Loaded legal factor from PESTLE")
        else:
            logger.info("  ⚠️ No legal factor from PESTLE (force 3 will use generic analysis)")
        
        return context
    
    def _analyze_force(
        self,
        force: str,
        client: ClientInput,
        context: dict,
    ) -> tuple[str, ForceResult, float]:
        """تحليل قوة واحدة — يُستخدم في threading"""
        agent = ForceAgent(self.llm, force=force, model=self.model)
        result, cost = agent.analyze(client, context=context)
        return force, result, cost
    
    def run_internal(self, state: PipelineState) -> dict:
        """تنفيذ Porter كامل"""
        client = state.client_input
        
        # ═══ Step 1: Gather cross-step context ═══
        self.emit("gathering_context", {
            "message": "تجميع السياق من الخطوات السابقة...",
        })
        context = self._gather_context(state)
        
        self.emit("context_ready", {
            "has_competitors": "competitors" in context,
            "has_legal_factor": "legal_factor" in context,
            "competitors_count": len(context.get("competitors", [])),
        })
        
        # ═══ Step 2: تشغيل الـ 5 قوى بشكل متوازي ═══
        self.emit("forces_starting", {
            "message": "جاري تحليل القوى الـ 5 بشكل متوازي...",
            "forces": FORCES,
        })
        
        force_results: dict[str, ForceResult] = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._analyze_force, force, client, context): force
                for force in FORCES
            }
            
            for future in as_completed(futures):
                force_name = futures[future]
                try:
                    force, result, cost = future.result()
                    force_results[force] = result
                    self.track_cost(cost)
                    self.emit("force_completed", {
                        "force": force,
                        "force_label": FORCE_LABELS_AR[force],
                        "threat_level": result.threat_level,
                        "factors_count": len(result.factors),
                    })
                except Exception as e:
                    logger.exception(f"Force {force_name} failed")
                    self.emit("force_failed", {
                        "force": force_name,
                        "error": str(e),
                    })
        
        if not force_results:
            raise RuntimeError("All Porter forces failed")
        
        # ═══ Step 3: Synthesize ═══
        self.emit("synthesizing", {
            "message": "تقييم التموضع التنافسي...",
        })
        
        synthesizer = CompetitivePositionSynthesizer(self.llm, model=self.model)
        position, synth_cost = synthesizer.synthesize(client, force_results)
        self.track_cost(synth_cost)
        
        self.emit("synthesis_complete", {
            "competitive_position": position.competitive_position,
            "overall_attractiveness": position.overall_attractiveness,
            "recommendations_count": len(position.strategic_recommendations),
        })
        
        # ═══ Step 4: تجميع المخرج النهائي ═══
        # Threat summary للعرض السريع
        threat_summary = {}
        for force, result in force_results.items():
            threat_summary[force] = {
                "label": FORCE_LABELS_AR[force],
                "threat_level": result.threat_level,
            }
        
        output = {
            "client": {
                "name": client.name,
                "sector": client.sector,
                "specialization": client.specialization,
            },
            "context_used": {
                "competitors_count": len(context.get("competitors", [])),
                "had_legal_factor": "legal_factor" in context,
            },
            "forces": {
                force: result.to_dict()
                for force, result in force_results.items()
            },
            "threat_summary": threat_summary,
            "competitive_position": position.to_dict(),
            "forces_completed": list(force_results.keys()),
            "forces_failed": [f for f in FORCES if f not in force_results],
            "total_cost_usd": round(self.cost_tracker, 4),
        }
        
        return output
