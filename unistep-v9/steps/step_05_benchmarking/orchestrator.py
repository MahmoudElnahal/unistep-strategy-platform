"""
═══════════════════════════════════════════════════════════════════
Step 5 — Benchmarking Orchestrator (v8 wrapper)
═══════════════════════════════════════════════════════════════════

هذا الـ wrapper بيلف الـ legacy orchestrator (v7) بالـ Core API الجديد.

الجديد في v8:
- يرث من StepOrchestrator (Core base)
- يستخدم PipelineState (مش local state)
- TARGET_LOCAL = 4 (بدل 3)
- يستخدم ClientInput (الـ unified schema)

الموجود من v7 (محفوظ):
- Discovery Agent (15+15 candidates)
- Scraping + Extraction + Validation
- Initiative Filter
- Comparative Analysis
- 3 retry rounds
"""
import logging
import os
from openai import OpenAI

from core.client_input import ClientInput
from core.orchestrator_base import StepOrchestrator
from core.pipeline_state import PipelineState, StepID
from steps.step_05_benchmarking._legacy_orchestrator import BenchmarkOrchestrator as LegacyOrchestrator
from steps.step_05_benchmarking.agents.enrichment_pipeline import EnrichmentPipeline

logger = logging.getLogger(__name__)


class BenchmarkingStep(StepOrchestrator):
    """
    Step 5 — Benchmarking
    
    Pipeline:
    1. Discovery (4 محلية + 3 دولية candidates)
    2. Scraping + Validation
    3. Initiative Extraction
    4. Initiative Filter
    5. Comparative Analysis
    6. توليد المخرجات
    """
    
    STEP_ID = StepID.BENCHMARKING
    
    def __init__(
        self,
        openai_client: OpenAI = None,
        model: str = "gpt-4o",
        progress_callback=None,
    ):
        super().__init__(progress_callback=progress_callback)
        
        # Default client من env
        if openai_client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY environment variable not set")
            openai_client = OpenAI(api_key=api_key)
        
        # نخلق legacy orchestrator مع progress_callback اللي يحول للـ Core emit
        self._legacy = LegacyOrchestrator(
            openai_client=openai_client,
            model_smart=model,
            progress_callback=self._legacy_progress_adapter,
        )
        
        # 🆕 v8: نحقن الـ enrichment pipeline (OCR + fallback)
        self._legacy._enrichment_pipeline = EnrichmentPipeline(openai_client=openai_client)
    
    def _legacy_progress_adapter(self, event_type: str, payload: dict):
        """يحول event من legacy orchestrator لصيغة Core"""
        self.emit(event_type, payload)
    
    def run_internal(self, state: PipelineState) -> dict:
        """
        ينفذ الـ benchmarking pipeline.
        
        ياخد ClientInput من state.client_input، يحوّله لـ v7 dict format،
        يشغّل الـ legacy orchestrator، ويرجّع المخرج كـ dict.
        """
        client_dict = state.client_input.to_v7_dict()
        
        logger.info(
            f"🚀 Starting Benchmarking for: {state.client_input.name} "
            f"(target: {self._legacy.TARGET_LOCAL} محلية + {self._legacy.TARGET_INTERNATIONAL} دولية)"
        )
        
        result = self._legacy.run(client_dict)
        
        return result


# ═══════════════════════════════════════════════════════════════════
# Convenience function
# ═══════════════════════════════════════════════════════════════════
def run_benchmarking(
    client: ClientInput,
    progress_callback=None,
    model: str = "gpt-4o",
) -> tuple[PipelineState, dict]:
    """
    convenience: شغّل step 5 لوحدها على client input.
    
    Returns:
        (state, output) — الـ state بعد التشغيل + المخرج
    """
    state = PipelineState.create(client, [StepID.BENCHMARKING])
    step = BenchmarkingStep(progress_callback=progress_callback, model=model)
    output = step.run(state)
    return state, output
