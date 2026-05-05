"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — Pipeline State
═══════════════════════════════════════════════════════════════════

نظام موحّد لتخزين مخرجات كل خطوة بحيث الخطوات اللاحقة تستفيد منها.

Cross-Step Data Flow في v9:

    [Wizard] → ClientInput
              ↓
    ┌─────────┴─────────┐
    │                   │
[Step 1: PESTLE]   [Step 5: Benchmarking]
    │                   │
    └─────────┬─────────┘
              ↓
    [Step 2: Porter] ← يقرا من PESTLE (legal factor)
                       يقرا من Benchmarking (المنافسين)

كل step بـ load اللي تحتاجه من state، وبـ save مخرجاتها فيه.
"""
import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Any
from pydantic import BaseModel, Field

from core.client_input import ClientInput


class StepStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepRecord(BaseModel):
    """سجل تنفيذ خطوة واحدة"""
    step_id: str
    step_name: str
    status: StepStatus = StepStatus.NOT_STARTED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output: Optional[dict] = None
    error: Optional[str] = None
    cost_usd: Optional[float] = None
    duration_seconds: Optional[float] = None
    
    @property
    def is_done(self) -> bool:
        return self.status == StepStatus.COMPLETED


class PipelineState(BaseModel):
    """الحالة الموحّدة لـ run كامل"""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    client_input: ClientInput
    selected_steps: list[str] = Field(default_factory=list)
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0
    
    # ═══════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════
    
    @classmethod
    def create(cls, client_input: ClientInput, selected_steps: list[str]) -> "PipelineState":
        return cls(client_input=client_input, selected_steps=selected_steps)
    
    @classmethod
    def load(cls, run_id: str, runs_dir: Path) -> Optional["PipelineState"]:
        path = runs_dir / run_id / "state.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)
    
    def save(self, runs_dir: Path):
        self.updated_at = datetime.utcnow()
        run_dir = runs_dir / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "state.json"
        with open(path, "w", encoding="utf-8") as f:
            try:
                json_str = self.model_dump_json(indent=2)
            except AttributeError:
                json_str = self.json(indent=2)
            data = json.loads(json_str)
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    # ═══════════════════════════════════════════════════
    # Step Operations
    # ═══════════════════════════════════════════════════
    
    def start_step(self, step_id: str, step_name: str) -> StepRecord:
        record = StepRecord(
            step_id=step_id, step_name=step_name,
            status=StepStatus.RUNNING, started_at=datetime.utcnow(),
        )
        self.steps[step_id] = record
        return record
    
    def complete_step(self, step_id: str, output: dict, cost_usd: Optional[float] = None):
        if step_id not in self.steps:
            raise ValueError(f"Step {step_id} was never started")
        record = self.steps[step_id]
        record.status = StepStatus.COMPLETED
        record.completed_at = datetime.utcnow()
        record.output = output
        record.cost_usd = cost_usd or 0
        if record.started_at:
            record.duration_seconds = (record.completed_at - record.started_at).total_seconds()
        self.total_cost_usd += record.cost_usd or 0
        self.total_duration_seconds += record.duration_seconds or 0
    
    def fail_step(self, step_id: str, error: str):
        if step_id not in self.steps:
            return
        record = self.steps[step_id]
        record.status = StepStatus.FAILED
        record.error = error
        record.completed_at = datetime.utcnow()
    
    def get_step_output(self, step_id: str) -> Optional[dict]:
        record = self.steps.get(step_id)
        if record and record.is_done:
            return record.output
        return None
    
    # ═══════════════════════════════════════════════════
    # Step-specific accessors
    # ═══════════════════════════════════════════════════
    
    @property
    def benchmarking_output(self) -> Optional[dict]:
        return self.get_step_output(StepID.BENCHMARKING)
    
    @property
    def pestle_output(self) -> Optional[dict]:
        return self.get_step_output(StepID.PESTLE)
    
    @property
    def porter_output(self) -> Optional[dict]:
        return self.get_step_output(StepID.PORTER)
    
    # ═══════════════════════════════════════════════════
    # Cross-step data extraction (used by Porter)
    # ═══════════════════════════════════════════════════
    
    def get_competitors_from_benchmarking(self) -> list[dict]:
        """استخراج المنافسين الـ 7 من Benchmarking output (لـ Porter Force 1)"""
        bench = self.benchmarking_output
        if not bench:
            return []
        local = bench.get("local_organizations", [])
        intl = bench.get("international_organizations", [])
        return local + intl
    
    def get_legal_factor_from_pestle(self) -> Optional[dict]:
        """استخراج العامل القانوني من PESTLE (لـ Porter Force 3 — حواجز الدخول)"""
        pestle = self.pestle_output
        if not pestle:
            return None
        factors = pestle.get("factors", {})
        return factors.get("legal")
    
    # ═══════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════
    
    def has_completed(self, step_id: str) -> bool:
        record = self.steps.get(step_id)
        return record is not None and record.is_done
    
    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "client": self.client_input.name,
            "created_at": self.created_at.isoformat(),
            "selected_steps": self.selected_steps,
            "completed_steps": [s for s in self.steps if self.has_completed(s)],
            "failed_steps": [s for s, r in self.steps.items() if r.status == StepStatus.FAILED],
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_duration_seconds": round(self.total_duration_seconds, 1),
        }


# ═══════════════════════════════════════════════════════════════════
# Step IDs (constants)
# ═══════════════════════════════════════════════════════════════════
class StepID:
    PESTLE = "step_01_pestle"
    PORTER = "step_02_porter"
    BENEFICIARIES = "step_03_beneficiaries"
    DONORS = "step_04_donors"
    BENCHMARKING = "step_05_benchmarking"
    DIGITAL_PRESENCE = "step_06_digital_presence"
    STRATEGY = "step_07_strategy"
    GOVERNANCE = "step_08_governance"
    FINANCIAL = "step_09_financial"
    OPERATIONS = "step_10_operations"
    PROGRAMS = "step_11_programs"
    SYNTHESIS = "step_12_synthesis"
    
    ALL = [
        PESTLE, PORTER, BENEFICIARIES, DONORS, BENCHMARKING,
        DIGITAL_PRESENCE, STRATEGY, GOVERNANCE, FINANCIAL,
        OPERATIONS, PROGRAMS, SYNTHESIS,
    ]
    
    # شغّالين في v9
    AVAILABLE = [PESTLE, PORTER, BENCHMARKING]


STEP_NAMES_AR = {
    StepID.PESTLE: "PESTLE — مسح البيئة الكلية",
    StepID.PORTER: "Porter's 5 Forces — تحليل القوى التنافسية",
    StepID.BENEFICIARIES: "تحليل المستفيدين",
    StepID.DONORS: "تحليل المانحين والشركاء",
    StepID.BENCHMARKING: "Benchmarking — المقارنة المعيارية",
    StepID.DIGITAL_PRESENCE: "تحليل الحضور المؤسسي",
    StepID.STRATEGY: "تحليل الاستراتيجية",
    StepID.GOVERNANCE: "تقييم الحوكمة",
    StepID.FINANCIAL: "الاستدامة المالية",
    StepID.OPERATIONS: "العمليات الرقمية",
    StepID.PROGRAMS: "البرامج وقياس الأثر",
    StepID.SYNTHESIS: "التوليف النهائي",
}

STEP_PHASES = {
    StepID.PESTLE: 1, StepID.PORTER: 1, StepID.BENEFICIARIES: 1,
    StepID.DONORS: 1, StepID.BENCHMARKING: 1, StepID.DIGITAL_PRESENCE: 1,
    StepID.STRATEGY: 2, StepID.GOVERNANCE: 2, StepID.FINANCIAL: 2,
    StepID.OPERATIONS: 2, StepID.PROGRAMS: 2,
    StepID.SYNTHESIS: 3,
}
