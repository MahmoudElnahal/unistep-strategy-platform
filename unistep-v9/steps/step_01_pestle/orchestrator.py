"""
═══════════════════════════════════════════════════════════════════
PESTLE Step Orchestrator
═══════════════════════════════════════════════════════════════════

Pipeline:
1. تشغيل 6 FactorAgents بشكل متوازي (ThreadPoolExecutor)
   - Political, Economic, Social, Technology, Legal, Environmental
2. تشغيل PestleSynthesizer على النتائج
3. تجميع المخرج النهائي
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from core.client_input import ClientInput
from core.llm_client import LLMClient
from core.orchestrator_base import StepOrchestrator
from core.pipeline_state import PipelineState, StepID
from steps.step_01_pestle.agents.factor_agent import (
    FactorAgent, FactorResult, FACTOR_LABELS_AR,
)
from steps.step_01_pestle.agents.synthesizer import PestleSynthesizer

logger = logging.getLogger(__name__)


# الـ 6 عوامل بالترتيب
FACTORS = ["political", "economic", "social", "technology", "legal", "environmental"]


class PestleStep(StepOrchestrator):
    """Step 1 — PESTLE Analysis"""
    
    STEP_ID = StepID.PESTLE
    
    def __init__(
        self,
        openai_client: OpenAI = None,
        model: str = "gpt-4o",
        progress_callback=None,
        max_workers: int = 3,  # max concurrent factors
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
    
    def _analyze_factor(
        self,
        factor: str,
        client: ClientInput,
    ) -> tuple[str, FactorResult, float]:
        """تحليل عامل واحد — يُستخدم في threading"""
        agent = FactorAgent(self.llm, factor=factor, model=self.model)
        result, cost = agent.analyze(client)
        return factor, result, cost
    
    def run_internal(self, state: PipelineState) -> dict:
        """تنفيذ PESTLE كامل"""
        client = state.client_input
        
        self.emit("factors_starting", {
            "message": "جاري تحليل العوامل الـ 6 بشكل متوازي...",
            "factors": FACTORS,
        })
        
        # ═══ Step 1: تشغيل الـ 6 عوامل بشكل متوازي ═══
        factor_results: dict[str, FactorResult] = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._analyze_factor, factor, client): factor
                for factor in FACTORS
            }
            
            for future in as_completed(futures):
                factor_name = futures[future]
                try:
                    factor, result, cost = future.result()
                    factor_results[factor] = result
                    self.track_cost(cost)
                    self.emit("factor_completed", {
                        "factor": factor,
                        "factor_label": FACTOR_LABELS_AR[factor],
                        "drivers_count": len(result.key_drivers),
                        "opportunities_count": len(result.opportunities),
                        "threats_count": len(result.threats),
                        "impact_level": result.impact_level,
                    })
                except Exception as e:
                    logger.exception(f"Factor {factor_name} failed")
                    self.emit("factor_failed", {
                        "factor": factor_name,
                        "error": str(e),
                    })
                    # نكمل بدون العامل ده
        
        if not factor_results:
            raise RuntimeError("All PESTLE factors failed")
        
        # ═══ Step 2: Synthesis ═══
        self.emit("synthesizing", {
            "message": "توليف النتائج وبناء الملخص الاستراتيجي...",
        })
        
        synthesizer = PestleSynthesizer(self.llm, model=self.model)
        synthesis, synth_cost = synthesizer.synthesize(client, factor_results)
        self.track_cost(synth_cost)
        
        self.emit("synthesis_complete", {
            "top_opportunities_count": len(synthesis.top_opportunities),
            "top_threats_count": len(synthesis.top_threats),
            "strategic_posture": synthesis.strategic_posture,
        })
        
        # ═══ Step 3: تجميع المخرج النهائي ═══
        output = {
            "client": {
                "name": client.name,
                "sector": client.sector,
                "specialization": client.specialization,
            },
            "factors": {
                factor: result.to_dict()
                for factor, result in factor_results.items()
            },
            "synthesis": synthesis.to_dict(),
            "factors_completed": list(factor_results.keys()),
            "factors_failed": [f for f in FACTORS if f not in factor_results],
            "total_cost_usd": round(self.cost_tracker, 4),
        }
        
        return output
