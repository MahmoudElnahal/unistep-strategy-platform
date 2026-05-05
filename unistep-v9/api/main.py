"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — Unified FastAPI
═══════════════════════════════════════════════════════════════════

Endpoints:
- GET  /                      → Dashboard
- GET  /wizard                → Wizard 4 صفحات
- GET  /run/{run_id}          → صفحة النتائج

API:
- POST /api/start             → بدء run جديد (selected_steps[])
- GET  /api/stream/{run_id}   → SSE
- GET  /api/state/{run_id}    → حالة الـ run
- GET  /api/result/{run_id}   → نتيجة كاملة
- GET  /api/download/{run_id}/{file_key}  → تحميل ملف
- GET  /api/info              → معلومات المنصة

Multi-step orchestration:
- Wave 1: PESTLE + Benchmarking بشكل متوازي (مستقلين)
- Wave 2: Porter بعد Wave 1 (يحتاج output من Wave 1)
"""
import asyncio
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue, Empty
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.client_input import ClientInput
from core.pipeline_state import PipelineState, StepID, STEP_NAMES_AR, STEP_PHASES

# Steps
from steps.step_01_pestle.orchestrator import PestleStep
from steps.step_02_porter.orchestrator import PorterStep
from steps.step_05_benchmarking.orchestrator import BenchmarkingStep

# Generators
from steps.step_01_pestle.generators.word_generator import generate_pestle_report
from steps.step_02_porter.generators.word_generator import generate_porter_report
from steps.step_05_benchmarking.generators.word_generator import generate_word_report
from steps.step_05_benchmarking.generators.excel_generator import (
    generate_unified_report, generate_output_1, generate_output_2, generate_output_3,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Setup
# ═══════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "ui" / "static"
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="UNISTEP Platform",
    version="9.0.0",
    description="Situation Analysis Framework — 12 Steps. v9: PESTLE + Porter + Benchmarking.",
)

# In-memory tracking
JOBS: dict = {}
QUEUES: dict = {}


# ═══════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════
class StartRequest(BaseModel):
    """طلب بدء run جديد"""
    # Required (Wizard page 1)
    name: str
    sector: str
    specialization: str
    target_audience: str
    
    # Optional (Wizard pages 1-3)
    num_employees: Optional[int] = None
    year_founded: Optional[int] = None
    organization_size: Optional[str] = None
    region: Optional[str] = None
    vision: Optional[str] = None
    mission: Optional[str] = None
    strategic_goals: Optional[list[str]] = None
    sample_program: Optional[str] = None
    current_kpis: Optional[str] = None
    funding_sources: Optional[list[str]] = None
    
    # Steps to run (Wizard page 4)
    selected_steps: list[str]
    
    def to_client_input(self) -> ClientInput:
        d = self.model_dump(exclude={"selected_steps"})
        d = {k: v for k, v in d.items() if v is not None and v != ""}
        return ClientInput(**d)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)


def _generate_outputs(state: PipelineState, run_dir: Path) -> dict:
    """يولّد كل الـ output files (Word + Excel) للخطوات اللي خلصت بنجاح"""
    files = {}
    run_id = state.run_id
    client_name = state.client_input.name.replace(" ", "_").replace("/", "_")[:30]
    
    # Step 1 — PESTLE
    if state.has_completed(StepID.PESTLE):
        try:
            pestle_word = run_dir / f"PESTLE_{client_name}_{run_id}.docx"
            generate_pestle_report(state.pestle_output, str(pestle_word))
            files["pestle_word"] = str(pestle_word)
        except Exception as e:
            logger.warning(f"PESTLE word gen failed: {e}")
    
    # Step 2 — Porter
    if state.has_completed(StepID.PORTER):
        try:
            porter_word = run_dir / f"Porter_{client_name}_{run_id}.docx"
            generate_porter_report(state.porter_output, str(porter_word))
            files["porter_word"] = str(porter_word)
        except Exception as e:
            logger.warning(f"Porter word gen failed: {e}")
    
    # Step 5 — Benchmarking (5 ملفات: word + 4 excel)
    if state.has_completed(StepID.BENCHMARKING):
        bench_out = state.benchmarking_output
        try:
            unified = run_dir / f"Benchmarking_موحد_{client_name}_{run_id}.xlsx"
            generate_unified_report(bench_out, str(unified))
            files["benchmarking_excel"] = str(unified)
            
            o1 = run_dir / f"Benchmarking_معايير_{client_name}_{run_id}.xlsx"
            generate_output_1(bench_out, str(o1))
            files["benchmarking_output_1"] = str(o1)
            
            o2 = run_dir / f"Benchmarking_بيانات_{client_name}_{run_id}.xlsx"
            generate_output_2(bench_out, str(o2))
            files["benchmarking_output_2"] = str(o2)
            
            o3 = run_dir / f"Benchmarking_مصفوفة_{client_name}_{run_id}.xlsx"
            generate_output_3(bench_out, str(o3))
            files["benchmarking_output_3"] = str(o3)
            
            word = run_dir / f"Benchmarking_{client_name}_{run_id}.docx"
            generate_word_report(bench_out, str(word))
            files["benchmarking_word"] = str(word)
        except Exception as e:
            logger.warning(f"Benchmarking gen failed: {e}")
    
    logger.info(f"✅ Generated {len(files)} output files for {run_id}")
    return files


def run_pipeline_in_thread(run_id: str, client_input: ClientInput, selected_steps: list[str]):
    """
    شغّل الـ pipeline كاملاً في thread.
    
    Multi-step orchestration:
    Wave 1 (parallel): PESTLE + Benchmarking (مستقلين عن بعض)
    Wave 2 (sequential): Porter (يحتاج Wave 1 outputs)
    """
    queue = QUEUES[run_id]
    
    def emit(event_type: str, payload: dict):
        try:
            queue.put({"event": event_type, "data": payload})
        except Exception as e:
            logger.warning(f"queue put failed: {e}")
    
    try:
        # خلق state
        state = PipelineState.create(client_input, selected_steps)
        state.run_id = run_id
        
        client = get_openai_client()
        
        emit("pipeline_started", {
            "selected_steps": selected_steps,
            "client": client_input.name,
            "total_steps": len(selected_steps),
        })
        
        # ═══ Determine waves ═══
        # Wave 1: PESTLE, Benchmarking (مستقلين)
        # Wave 2: Porter (يحتاج Wave 1)
        wave_1_steps = [s for s in selected_steps if s in (StepID.PESTLE, StepID.BENCHMARKING)]
        wave_2_steps = [s for s in selected_steps if s == StepID.PORTER]
        
        # ═══ Wave 1: parallel ═══
        if wave_1_steps:
            emit("wave_started", {"wave": 1, "steps": wave_1_steps})
            
            def run_step(step_id):
                if step_id == StepID.PESTLE:
                    step = PestleStep(openai_client=client, progress_callback=lambda e, p: emit(e, p))
                elif step_id == StepID.BENCHMARKING:
                    step = BenchmarkingStep(openai_client=client, progress_callback=lambda e, p: emit(e, p))
                else:
                    return None
                return step.run(state)
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(run_step, s): s for s in wave_1_steps}
                for future in futures:
                    try:
                        future.result()  # propagate exceptions
                    except Exception as e:
                        logger.exception(f"Wave 1 step {futures[future]} failed")
                        # نكمل بدون الخطوة دي
            
            emit("wave_completed", {"wave": 1, "steps": wave_1_steps})
        
        # ═══ Wave 2: sequential (Porter يحتاج state.benchmarking_output أو state.pestle_output) ═══
        if wave_2_steps:
            emit("wave_started", {"wave": 2, "steps": wave_2_steps})
            
            for step_id in wave_2_steps:
                try:
                    if step_id == StepID.PORTER:
                        step = PorterStep(openai_client=client, progress_callback=lambda e, p: emit(e, p))
                        step.run(state)
                except Exception as e:
                    logger.exception(f"Wave 2 step {step_id} failed")
            
            emit("wave_completed", {"wave": 2, "steps": wave_2_steps})
        
        # ═══ Generate output files ═══
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        files = _generate_outputs(state, run_dir)
        
        # حفظ state
        state.save(RUNS_DIR)
        
        # تحديث الـ JOB
        JOBS[run_id]["status"] = "completed"
        JOBS[run_id]["files"] = files
        JOBS[run_id]["state_summary"] = state.summary()
        
        # Done event مع كل اللينكات
        downloads = {key: f"/api/download/{run_id}/{key}" for key in files.keys()}
        
        emit("pipeline_completed", {
            **state.summary(),
            "downloads": downloads,
            "outputs_count": len(files),
        })
        emit("done", {
            **state.summary(),
            "downloads": downloads,
        })
    
    except Exception as e:
        logger.exception(f"Pipeline {run_id} failed completely")
        JOBS[run_id]["status"] = "failed"
        JOBS[run_id]["error"] = str(e)
        emit("error", {"error": str(e)})


# ═══════════════════════════════════════════════════════════════════
# Routes — UI Pages
# ═══════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Dashboard موحّد"""
    p = STATIC_DIR / "dashboard.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return JSONResponse({"error": "dashboard.html not found"}, status_code=404)


@app.get("/wizard", response_class=HTMLResponse)
def wizard():
    """Wizard 4 صفحات"""
    p = STATIC_DIR / "wizard.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return JSONResponse({"error": "wizard.html not found"}, status_code=404)


@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_page(run_id: str):
    """صفحة النتائج للـ run"""
    p = STATIC_DIR / "results.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return JSONResponse({"error": "results.html not found"}, status_code=404)


# ═══════════════════════════════════════════════════════════════════
# Routes — API
# ═══════════════════════════════════════════════════════════════════
@app.post("/api/start")
def start_pipeline(request: StartRequest):
    """بدء run جديد"""
    # Validate selected_steps
    invalid = [s for s in request.selected_steps if s not in StepID.AVAILABLE]
    if invalid:
        raise HTTPException(400, f"Invalid steps: {invalid}. Available: {StepID.AVAILABLE}")
    
    if not request.selected_steps:
        raise HTTPException(400, "Must select at least one step")
    
    run_id = str(uuid.uuid4())[:8]
    client_input = request.to_client_input()
    
    JOBS[run_id] = {
        "status": "running",
        "client_name": client_input.name,
        "selected_steps": request.selected_steps,
    }
    QUEUES[run_id] = Queue()
    
    thread = threading.Thread(
        target=run_pipeline_in_thread,
        args=(run_id, client_input, request.selected_steps),
        daemon=True,
    )
    thread.start()
    
    return {"run_id": run_id, "status": "started", "selected_steps": request.selected_steps}


@app.get("/api/stream/{run_id}")
async def stream_progress(run_id: str):
    """SSE stream"""
    if run_id not in QUEUES:
        raise HTTPException(404, "Run not found")
    
    queue = QUEUES[run_id]
    
    async def generator():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: queue.get(timeout=1)
                )
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["event"] in ("done", "error"):
                    break
            except Empty:
                yield ": ping\n\n"
            except Exception as e:
                logger.warning(f"stream error: {e}")
                break
    
    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/state/{run_id}")
def get_state(run_id: str):
    """الحالة الحالية"""
    if run_id in JOBS:
        return JOBS[run_id]
    
    state = PipelineState.load(run_id, RUNS_DIR)
    if state:
        return state.summary()
    
    raise HTTPException(404, "Run not found")


@app.get("/api/result/{run_id}")
def get_result(run_id: str):
    """نتيجة كاملة (كل step output)"""
    state = PipelineState.load(run_id, RUNS_DIR)
    if not state:
        if run_id in JOBS and "state_summary" in JOBS[run_id]:
            return JOBS[run_id]
        raise HTTPException(404, "Run not found")
    
    return {
        "run_id": run_id,
        "summary": state.summary(),
        "client": state.client_input.model_dump(),
        "outputs": {
            "pestle": state.pestle_output,
            "porter": state.porter_output,
            "benchmarking": state.benchmarking_output,
        },
        "files": JOBS.get(run_id, {}).get("files", {}),
    }


@app.get("/api/result/{run_id}/{step_id}")
def get_step_result(run_id: str, step_id: str):
    """نتيجة step واحد"""
    state = PipelineState.load(run_id, RUNS_DIR)
    if not state:
        raise HTTPException(404, "Run not found")
    
    output = state.get_step_output(step_id)
    if output is None:
        raise HTTPException(404, f"Step {step_id} not completed")
    
    return output


@app.get("/api/download/{run_id}/{file_key}")
def download_file(run_id: str, file_key: str):
    """تحميل ملف من output files"""
    if run_id not in JOBS or "files" not in JOBS[run_id]:
        raise HTTPException(404, "Run files not available")
    
    files = JOBS[run_id]["files"]
    path = files.get(file_key)
    
    if not path or not Path(path).exists():
        raise HTTPException(404, f"File '{file_key}' not found. Available: {list(files.keys())}")
    
    filename = Path(path).name
    
    if path.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif path.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(path=path, filename=filename, media_type=media_type)


@app.get("/api/info")
def info():
    """معلومات المنصة"""
    try:
        from steps.step_05_benchmarking.agents.ocr_engine import HAS_TESSERACT, HAS_PDF2IMAGE
    except Exception:
        HAS_TESSERACT = HAS_PDF2IMAGE = False
    
    return {
        "version": "9.0.0",
        "available_steps": StepID.AVAILABLE,
        "all_steps": StepID.ALL,
        "step_names": STEP_NAMES_AR,
        "step_phases": STEP_PHASES,
        "capabilities": {
            "ocr_tesseract": HAS_TESSERACT,
            "ocr_vision": True,
            "pdf_processing": HAS_PDF2IMAGE,
            "fallback_search": True,
            "confidence_system": True,
            "multi_step_orchestration": True,
            "wizard_4_pages": True,
        },
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "active_jobs": len([j for j in JOBS.values() if j.get("status") == "running"]),
    }


# ═══════════════════════════════════════════════════════════════════
# Static
# ═══════════════════════════════════════════════════════════════════
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
