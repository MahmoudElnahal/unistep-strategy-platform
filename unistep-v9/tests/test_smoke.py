"""
Smoke Test — يتأكد إن كل المكونات بـ import وبتشتغل صح.
لا يحتاج OPENAI_API_KEY حقيقي.

Usage:
    PYTHONPATH=. python tests/test_smoke.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-stub")


def test_core_imports():
    print("📦 Testing Core...")
    from core.client_input import ClientInput, get_size_from_employees
    from core.confidence import ConfidenceRecord, ConfidenceLevel, SourceTier
    from core.pipeline_state import PipelineState, StepID, STEP_NAMES_AR, STEP_PHASES
    from core.orchestrator_base import StepOrchestrator
    from core.llm_client import LLMClient, PRICING
    
    assert StepID.PESTLE == "step_01_pestle"
    assert StepID.PORTER == "step_02_porter"
    assert StepID.BENCHMARKING == "step_05_benchmarking"
    assert len(StepID.AVAILABLE) == 3
    assert get_size_from_employees(35) == "متوسطة"
    assert "gpt-4o" in PRICING
    print("  ✅ Core OK")


def test_client_input():
    print("📦 Testing ClientInput...")
    from core.client_input import ClientInput
    
    c = ClientInput(
        name="جمعية اختبار", sector="رعاية", specialization="كفالة",
        target_audience="أيتام", num_employees=35,
    )
    assert c.organization_size == "متوسطة"
    assert c.to_v7_dict()["organization_size"] == "متوسطة"
    
    c2 = ClientInput(
        name="جمعية كبيرة", sector="X", specialization="Y",
        target_audience="Z", num_employees=80,
    )
    assert c2.organization_size == "كبيرة"
    print("  ✅ ClientInput OK")


def test_pipeline_state():
    print("📦 Testing PipelineState...")
    from core.client_input import ClientInput
    from core.pipeline_state import PipelineState, StepID
    
    client = ClientInput(
        name="جمعية", sector="رعاية", specialization="كفالة",
        target_audience="أيتام", num_employees=35,
    )
    state = PipelineState.create(client, [StepID.PESTLE, StepID.PORTER])
    
    # Cross-step accessors (empty case)
    assert state.get_competitors_from_benchmarking() == []
    assert state.get_legal_factor_from_pestle() is None
    
    # Save/load
    runs_dir = Path("/tmp/unistep_v9_test")
    state.start_step(StepID.PESTLE, "PESTLE")
    state.complete_step(StepID.PESTLE, output={"factors_completed": ["political"]}, cost_usd=0.5)
    state.save(runs_dir)
    
    loaded = PipelineState.load(state.run_id, runs_dir)
    assert loaded.has_completed(StepID.PESTLE)
    assert loaded.pestle_output["factors_completed"] == ["political"]
    print(f"  ✅ PipelineState OK (run: {state.run_id})")


def test_step_05_benchmarking():
    print("📦 Testing Step 5 (Benchmarking)...")
    from core.orchestrator_base import StepOrchestrator
    from steps.step_05_benchmarking.orchestrator import BenchmarkingStep
    from steps.step_05_benchmarking._legacy_orchestrator import BenchmarkOrchestrator
    
    assert issubclass(BenchmarkingStep, StepOrchestrator)
    assert BenchmarkingStep.STEP_ID == "step_05_benchmarking"
    assert BenchmarkOrchestrator.TARGET_LOCAL == 4
    assert BenchmarkOrchestrator.TARGET_INTERNATIONAL == 3
    
    step = BenchmarkingStep()
    assert step._legacy._enrichment_pipeline is not None
    print("  ✅ Step 5 OK (TARGET=4+3, enrichment wired)")


def test_step_01_pestle():
    print("📦 Testing Step 1 (PESTLE)...")
    from core.orchestrator_base import StepOrchestrator
    from steps.step_01_pestle.orchestrator import PestleStep, FACTORS
    from steps.step_01_pestle.agents.factor_agent import FactorAgent, FACTOR_LABELS_AR, FACTOR_PROMPTS
    from steps.step_01_pestle.agents.synthesizer import PestleSynthesizer
    from steps.step_01_pestle.generators.word_generator import generate_pestle_report
    
    assert issubclass(PestleStep, StepOrchestrator)
    assert PestleStep.STEP_ID == "step_01_pestle"
    assert len(FACTORS) == 6
    assert all(f in FACTOR_PROMPTS for f in FACTORS)
    assert all(f in FACTOR_LABELS_AR for f in FACTORS)
    
    step = PestleStep()
    assert step.max_workers == 3
    print("  ✅ Step 1 OK (6 factors)")


def test_step_02_porter():
    print("📦 Testing Step 2 (Porter)...")
    from core.orchestrator_base import StepOrchestrator
    from steps.step_02_porter.orchestrator import PorterStep, FORCES
    from steps.step_02_porter.agents.force_agent import ForceAgent, FORCE_LABELS_AR, FORCE_PROMPTS
    from steps.step_02_porter.agents.synthesizer import CompetitivePositionSynthesizer
    from steps.step_02_porter.generators.word_generator import generate_porter_report
    
    assert issubclass(PorterStep, StepOrchestrator)
    assert PorterStep.STEP_ID == "step_02_porter"
    assert len(FORCES) == 5
    assert all(f in FORCE_PROMPTS for f in FORCES)
    
    step = PorterStep()
    print("  ✅ Step 2 OK (5 forces)")


def test_cross_step_data():
    print("📦 Testing Cross-Step Data Flow...")
    from core.client_input import ClientInput
    from core.pipeline_state import PipelineState, StepID
    
    client = ClientInput(
        name="جمعية اختبار", sector="رعاية", specialization="كفالة",
        target_audience="أيتام", num_employees=35,
    )
    state = PipelineState.create(client, [StepID.PESTLE, StepID.PORTER, StepID.BENCHMARKING])
    
    # Simulate Benchmarking output
    state.start_step(StepID.BENCHMARKING, "Bench")
    state.complete_step(StepID.BENCHMARKING, output={
        "local_organizations": [{"name": "Local 1"}, {"name": "Local 2"}],
        "international_organizations": [{"name": "Intl 1"}],
    })
    
    # Simulate PESTLE output
    state.start_step(StepID.PESTLE, "PESTLE")
    state.complete_step(StepID.PESTLE, output={
        "factors": {
            "legal": {
                "summary": "...", 
                "extra": {"barriers_to_entry": {"level": "high"}},
            }
        }
    })
    
    # Cross-step access works
    competitors = state.get_competitors_from_benchmarking()
    assert len(competitors) == 3
    
    legal = state.get_legal_factor_from_pestle()
    assert legal is not None
    assert legal.get("extra", {}).get("barriers_to_entry", {}).get("level") == "high"
    print("  ✅ Cross-step data flow OK")


def test_fastapi_loads():
    print("📦 Testing FastAPI...")
    from api.main import app
    
    routes = {route.path for route in app.routes if hasattr(route, "path")}
    expected = {
        "/", "/wizard", "/run/{run_id}",
        "/api/start", "/api/stream/{run_id}", "/api/state/{run_id}",
        "/api/result/{run_id}", "/api/result/{run_id}/{step_id}",
        "/api/download/{run_id}/{file_key}", "/api/info",
    }
    missing = expected - routes
    assert not missing, f"Missing routes: {missing}"
    print(f"  ✅ FastAPI OK ({len(routes)} routes)")


def test_static_files():
    print("📦 Testing Static Files...")
    base = Path(__file__).parent.parent / "ui" / "static"
    expected = ["dashboard.html", "wizard.html", "results.html", "css/shared.css"]
    for f in expected:
        path = base / f
        assert path.exists(), f"Missing: {path}"
    print(f"  ✅ Static OK ({len(expected)} files)")


def test_ocr_engine():
    print("📦 Testing OCR Engine...")
    from steps.step_05_benchmarking.agents.ocr_engine import (
        OCREngine, HAS_TESSERACT, HAS_PDF2IMAGE
    )
    print(f"  ⓘ HAS_TESSERACT: {HAS_TESSERACT}")
    print(f"  ⓘ HAS_PDF2IMAGE: {HAS_PDF2IMAGE}")
    engine = OCREngine()
    result = engine.extract_text("/tmp/nonexistent.pdf")
    assert result.method == "failed"
    print("  ✅ OCR OK")


def test_llm_client():
    print("📦 Testing LLM Client...")
    from core.llm_client import LLMClient, PRICING, CostRecord
    
    # Just verify pricing exists for our models
    assert "gpt-4o" in PRICING
    assert "gpt-4o-mini" in PRICING
    
    # Cost calculation
    cost_per_1k_input = PRICING["gpt-4o"]["input"] / 1000
    print(f"  ⓘ gpt-4o input: ${PRICING['gpt-4o']['input']}/1M tokens")
    print("  ✅ LLM Client OK")


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║         UNISTEP Platform v9 — Smoke Test                     ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    
    tests = [
        test_core_imports,
        test_client_input,
        test_pipeline_state,
        test_llm_client,
        test_ocr_engine,
        test_step_05_benchmarking,
        test_step_01_pestle,
        test_step_02_porter,
        test_cross_step_data,
        test_fastapi_loads,
        test_static_files,
    ]
    
    passed = 0
    failed = []
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"  ❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'═' * 64}")
    print(f"Results: {passed}/{len(tests)} passed")
    
    if failed:
        print(f"\n❌ Failures:")
        for name, err in failed:
            print(f"  • {name}: {err}")
        sys.exit(1)
    
    print(f"\n✅ All tests passed! v9 is ready.")
    print(f"\nنشغّل المنصة:")
    print(f"  export OPENAI_API_KEY=sk-...")
    print(f"  ./run.sh")
    print(f"  افتح http://localhost:8000")
    sys.exit(0)


if __name__ == "__main__":
    main()
