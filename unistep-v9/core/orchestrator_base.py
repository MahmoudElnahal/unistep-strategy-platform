"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — Step Orchestrator Base
═══════════════════════════════════════════════════════════════════

كل خطوة من الـ 12 ترث من StepOrchestrator.

Subclass بتعرّف:
- STEP_ID: constant
- run_internal(state): الشغل الفعلي
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Callable

from core.pipeline_state import PipelineState, STEP_NAMES_AR

logger = logging.getLogger(__name__)


class StepOrchestrator(ABC):
    """Base class لكل الـ 12 خطوة"""
    
    STEP_ID: str = ""  # subclass overrides
    
    def __init__(self, progress_callback: Optional[Callable] = None):
        self.progress_callback = progress_callback
        self.cost_tracker: float = 0.0
    
    @property
    def step_name_ar(self) -> str:
        return STEP_NAMES_AR.get(self.STEP_ID, self.STEP_ID)
    
    def emit(self, event_type: str, payload: dict):
        """ترسل event للـ frontend (SSE)"""
        if self.progress_callback:
            try:
                self.progress_callback(event_type, {
                    "step_id": self.STEP_ID,
                    "step_name_ar": self.step_name_ar,
                    **payload,
                })
            except Exception as e:
                logger.warning(f"progress callback error: {e}")
        logger.info(f"📡 [{self.STEP_ID}] {event_type}")
    
    def track_cost(self, cost_usd: float):
        self.cost_tracker += cost_usd
    
    def run(self, state: PipelineState) -> dict:
        """Entry point — يدير lifecycle كامل"""
        record = state.start_step(self.STEP_ID, self.step_name_ar)
        self.emit("step_started", {"message": f"بدء {self.step_name_ar}"})
        
        start_time = time.time()
        try:
            output = self.run_internal(state)
            duration = time.time() - start_time
            state.complete_step(self.STEP_ID, output=output, cost_usd=self.cost_tracker)
            self.emit("step_completed", {
                "duration_seconds": round(duration, 1),
                "cost_usd": round(self.cost_tracker, 4),
            })
            return output
        except Exception as e:
            logger.exception(f"Step {self.STEP_ID} failed")
            state.fail_step(self.STEP_ID, str(e))
            self.emit("step_failed", {"error": str(e)})
            raise
    
    @abstractmethod
    def run_internal(self, state: PipelineState) -> dict:
        """الشغل الفعلي للـ step. Subclass overrides."""
        ...
