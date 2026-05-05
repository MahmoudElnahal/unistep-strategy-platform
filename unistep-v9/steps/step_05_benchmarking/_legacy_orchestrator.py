"""
═══════════════════════════════════════════════════════════
Orchestrator v7 — يضمن 3 محلية + 3 دولية
═══════════════════════════════════════════════════════════

🎯 الترتيب الصحيح للـ Pipeline:

1. Discovery (15 + 15 candidates)
2. Scraping + Extraction + Validation
   ⭐ يكمل لحد ما يجيب 3 محلية + 3 دولية بالضبط
   ⭐ لو Discovery الأول ما كفاش، يطلب Discovery إضافي
3. Initiative Extraction (لكل الجمعيات الـ 6)
4. Initiative Filter (يفلتر على تخصص العميل)
5. Comparative Analysis (Gap + توصيات)
6. توليد المخرجات

🚨 شرط حاسم: 3 محلية + 3 دولية إجباري — لو فشل، يكمل يحاول
"""
import logging
from typing import Optional, Callable
from dataclasses import dataclass, field

from openai import OpenAI

from steps.step_05_benchmarking.agents.scraper import EnhancedScraper
from steps.step_05_benchmarking.agents.extractor import FieldExtractorV7, FieldEnricher, FundingBooster
from steps.step_05_benchmarking.agents.validator import (
    validate_organization,
    OrganizationValidation,
    ALL_FIELDS,
    FIELD_CATEGORIES,
)
from steps.step_05_benchmarking.agents.discovery import SmartDiscoveryAgent, Candidate
from steps.step_05_benchmarking.agents.initiative_extractor import InitiativeExtractor, InitiativeFilter
from steps.step_05_benchmarking.agents.comparative_analyst import ComparativeAnalyst

logger = logging.getLogger(__name__)


@dataclass
class OrgResult:
    name: str
    url: str
    type: str
    country: str
    region: str = ""
    status: str = "pending"
    
    target_match: bool = False
    specialization_match: bool = False
    has_diverse_programs: bool = False
    institutional_maturity: bool = False
    vision_2030_aligned: bool = False
    geographic_diversity: bool = False
    data_available: bool = False
    diverse_beneficiaries: bool = False
    
    pages_fetched: int = 0
    pages_failed: int = 0
    raw_text_length: int = 0
    raw_text: str = ""

    # خرائط لينكات داخلية (URL → نص الـ anchor) من كل صفحات الجهة — للـ deep-crawl
    link_anchors: dict = field(default_factory=dict)
    # نص التقارير السنوية (PDF/DOCX) لو وُجدت — لاستخدامها في الـ enrichment
    annual_report_text: str = ""

    validation: Optional[OrganizationValidation] = None
    initiatives: list = field(default_factory=list)
    similarity_score: int = 0
    error: Optional[str] = None
    
    @property
    def is_accepted(self) -> bool:
        return self.validation is not None and self.validation.accepted
    
    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "url": self.url,
            "type": self.type,
            "country": self.country,
            "region": self.region,
            "status": self.status,
            "target_match": self.target_match,
            "specialization_match": self.specialization_match,
            "has_diverse_programs": self.has_diverse_programs,
            "institutional_maturity": self.institutional_maturity,
            "vision_2030_aligned": self.vision_2030_aligned,
            "geographic_diversity": self.geographic_diversity,
            "data_available": self.data_available,
            "diverse_beneficiaries": self.diverse_beneficiaries,
            "pages_fetched": self.pages_fetched,
            "pages_failed": self.pages_failed,
            "raw_text_length": self.raw_text_length,
            "is_accepted": self.is_accepted,
            "similarity_score": self.similarity_score,
            "initiatives_count": len(self.initiatives),
            "error": self.error,
        }
        if self.validation:
            d["passed_count"] = self.validation.passed_count
            d["failed_count"] = self.validation.failed_count
            d["completeness"] = self.validation.completeness
            d["vision_2030_compliant"] = self.validation.vision_2030_compliant
            d["vision_2030_keywords"] = self.validation.vision_2030_keywords
            d["fields"] = [
                {
                    "name": f.field_name,
                    "value": f.value,
                    "passed": f.passed,
                    "reason": f.reason,
                    "exact_quote": f.exact_quote[:300] if f.exact_quote else None,
                }
                for f in self.validation.fields
            ]
        return d


class BenchmarkOrchestrator:
    """Pipeline v7 الكامل"""
    
    TARGET_LOCAL = 4            # 🆕 v8: 4 محلية (4 مناطق سعودية: شرقية/غربية/وسطى/شمالية)
    TARGET_INTERNATIONAL = 3    # حد أدنى — لو زاد، نضيفه كله
    MAX_RETRY_ROUNDS = 3        # عدد محاولات Discovery الإضافية
    
    def __init__(
        self,
        openai_client: OpenAI,
        model_smart: str = "gpt-4o",
        progress_callback: Optional[Callable] = None,
    ):
        self.client = openai_client
        self.model = model_smart
        self.progress_callback = progress_callback
        
        # Components
        self.discovery = SmartDiscoveryAgent(openai_client, model=model_smart)
        self.scraper = EnhancedScraper(use_selenium=True)
        self.extractor = FieldExtractorV7(openai_client, model=model_smart)
        self.field_enricher = FieldEnricher(openai_client, model=model_smart)
        self.funding_booster = FundingBooster(openai_client, model="gpt-4o-mini")
        self.initiative_extractor = InitiativeExtractor(openai_client, model=model_smart)
        self.initiative_filter = InitiativeFilter(openai_client, model=model_smart)
        self.analyst = ComparativeAnalyst(openai_client, model=model_smart)
        
        self.results: list[OrgResult] = []
        self.tried_names: set = set()
    
    def emit_progress(self, event_type: str, payload: dict):
        if self.progress_callback:
            try:
                self.progress_callback(event_type, payload)
            except Exception as e:
                logger.warning(f"progress callback error: {e}")
        logger.info(f"📡 {event_type}")
    
    def run(self, client_data: dict) -> dict:
        try:
            # ═══ Stage 1: Discovery ═══
            self.emit_progress("stage_start", {
                "stage": "discovery",
                "message": "اكتشاف المنافسين بدقة على نفس التخصص...",
            })
            
            discovery_result = self.discovery.discover(client_data)
            local_candidates = discovery_result["local"]
            intl_candidates = discovery_result["international"]
            client_profile = discovery_result.get("client_profile", {})
            
            self.emit_progress("discovery_complete", {
                "client_profile": client_profile,
                "local_count": len(local_candidates),
                "international_count": len(intl_candidates),
                "candidates": {
                    "local": [self._candidate_to_dict(c) for c in local_candidates],
                    "international": [self._candidate_to_dict(c) for c in intl_candidates],
                }
            })
            
            # ═══ Stage 2: Scraping/Extraction/Validation مع شرط 3+3 إجباري ═══
            self.emit_progress("stage_start", {
                "stage": "scraping",
                "message": "جمع البيانات والتحقق منها...",
            })
            
            # محاولة الـ pool الأولى
            local_accepted = self._process_pool_until_target(
                local_candidates, self.TARGET_LOCAL, "محلية", client_data, client_profile
            )
            
            intl_accepted = self._process_pool_until_target(
                intl_candidates, self.TARGET_INTERNATIONAL, "دولية", client_data, client_profile
            )
            
            # ═══ Stage 3: Initiative Extraction ═══
            self.emit_progress("stage_start", {
                "stage": "initiatives",
                "message": "استخراج المبادرات تفصيلياً...",
            })
            
            all_initiatives = self._extract_initiatives()
            
            self.emit_progress("initiatives_complete", {
                "total_initiatives": len(all_initiatives),
            })
            
            # ═══ Stage 4: Filter Initiatives على تخصص العميل ═══
            self.emit_progress("stage_start", {
                "stage": "filter",
                "message": "فلترة المبادرات على تخصصك الدقيق...",
            })
            
            filter_result = self.initiative_filter.filter_initiatives(client_data, all_initiatives)
            matched_initiatives = filter_result.get("matched", [])
            rejected_initiatives = filter_result.get("rejected", [])

            # 🛡 ضمان: لو نوع كامل (محلي أو دولي) اترفض بالكامل من الفلتر،
            # نسترجعه بـ relevance منخفضة عشان المستخدم يشوفه
            for source_type in ("local", "international"):
                has_matched = any(m.get("source_type") == source_type for m in matched_initiatives)
                if not has_matched:
                    rescued = [i for i in all_initiatives if i.get("source_type") == source_type]
                    if rescued:
                        logger.warning(
                            f"⚠️ الفلتر رفض كل مبادرات النوع '{source_type}' — "
                            f"نسترجع {len(rescued)} مبادرة بـ relevance منخفضة"
                        )
                        for init in rescued:
                            init["match_reason"] = "استرجاع تلقائي — في نفس قطاع العميل"
                            init["match_level"] = 3
                            init["relevance_score"] = 3
                        matched_initiatives.extend(rescued)
            
            self.emit_progress("filter_complete", {
                "matched_count": len(matched_initiatives),
                "rejected_count": len(rejected_initiatives),
            })
            
            # ═══ Stage 5: Comparative Analysis ═══
            self.emit_progress("stage_start", {
                "stage": "analysis",
                "message": "التحليل المقارن وتحديد الفرص...",
            })
            
            analysis = self.analyst.analyze(client_data, matched_initiatives)
            
            self.emit_progress("analysis_complete", {
                "selected_count": len(analysis.get("selected_initiatives", [])),
            })
            
            # ═══ النتيجة النهائية ═══
            summary = {
                "total_candidates_tried": len(self.results),
                "local_accepted": len([r for r in self.results if r.is_accepted and r.type == "local"]),
                "international_accepted": len([r for r in self.results if r.is_accepted and r.type == "international"]),
                "total_accepted": len([r for r in self.results if r.is_accepted]),
                "total_initiatives": len(all_initiatives),
                "matched_initiatives": len(matched_initiatives),
                "rejected_initiatives": len(rejected_initiatives),
                "selected_initiatives": len(analysis.get("selected_initiatives", [])),
            }
            
            self.emit_progress("workflow_complete", summary)
            
            # Discovery data للتقارير
            candidate_assessments = {}
            for c in local_candidates + intl_candidates:
                candidate_assessments[c.name] = {
                    "target_match": c.target_match,
                    "specialization_match": c.specialization_match,
                    "has_diverse_programs": c.has_diverse_programs,
                    "institutional_maturity": c.institutional_maturity,
                    "vision_2030_aligned": c.vision_2030_aligned,
                    "geographic_diversity": c.geographic_diversity,
                    "data_available": c.data_available,
                    "diverse_beneficiaries": c.diverse_beneficiaries,
                }
            
            return {
                "client": client_data,
                "client_profile": client_profile,
                "local_organizations": [r.to_dict() for r in self.results if r.type == "local"],
                "international_organizations": [r.to_dict() for r in self.results if r.type == "international"],
                "all_attempts": [r.to_dict() for r in self.results],
                "initiative_matrix": matched_initiatives,
                "rejected_initiatives": rejected_initiatives,
                "analysis": analysis,
                "summary": summary,
                "discovery_data": {"candidate_assessments": candidate_assessments},
            }
        
        finally:
            self.scraper.close()
    
    def _candidate_to_dict(self, c: Candidate) -> dict:
        return {
            "name": c.name, "url": c.url, "country": c.country, "region": c.region,
            "verified": c.verified, "similarity_score": c.similarity_score,
            "mandatory_count": c.mandatory_count, "passes_mandatory": c.passes_mandatory,
        }
    
    def _process_pool_until_target(
        self,
        candidates: list[Candidate],
        target: int,
        label: str,
        client_data: dict,
        profile: dict,
    ) -> list[OrgResult]:
        """
        🎯 الجديد: target = حد أدنى مش حد أقصى.
        - نجرب كل الـ pool الأوّلي بالكامل (نقبل كل اللي ينجح).
        - لو في الآخر < target، نطلب discovery إضافي ونكمّل.
        - لو ≥ target بعد الـ pool الأوّلي، نقف (عندنا كفاية + اللي زاد).
        """
        accepted = []
        retry_round = 0
        type_label = "local" if "محلية" in label else "international"

        while True:
            # 1) نمشي على كل الـ pool الحالي بالكامل بدون break مبكّر
            for candidate in candidates:
                if candidate.name in self.tried_names:
                    continue

                # تخطّي الـ candidates اللي URL بتاعها فشل في الـ verification (404/timeout)
                if candidate.url and not candidate.verified:
                    logger.info(f"  ⏭️ تخطّي {candidate.name} — URL لم يتم التحقق منه ({candidate.verification_status})")
                    self.tried_names.add(candidate.name)
                    self.emit_progress("candidate_skipped", {
                        "name": candidate.name, "url": candidate.url,
                        "reason": f"URL غير صالح ({candidate.verification_status})",
                    })
                    continue

                self.tried_names.add(candidate.name)

                self.emit_progress("candidate_start", {
                    "name": candidate.name, "url": candidate.url,
                    "type": candidate.type, "country": candidate.country,
                    "similarity_score": candidate.similarity_score,
                    "round": retry_round,
                })

                result = self._process_candidate(candidate)
                self.results.append(result)

                self.emit_progress("candidate_complete", result.to_dict())

                if result.is_accepted:
                    accepted.append(result)
                    logger.info(f"  ✅ تم قبول {len(accepted)} {label} (الحد الأدنى {target})")

            # 2) قرّر: نكمّل أم نقف؟
            if len(accepted) >= target:
                logger.info(f"🎯 {label}: تم قبول {len(accepted)} (≥ {target})")
                break

            retry_round += 1
            if retry_round > self.MAX_RETRY_ROUNDS:
                logger.warning(f"⚠️ بعد {retry_round} محاولات، عندنا {len(accepted)}/{target} {label}")
                self.emit_progress("retry_warning", {
                    "type": label,
                    "current": len(accepted),
                    "target": target,
                    "round": retry_round,
                })
                break

            logger.info(f"🔄 محاولة Discovery #{retry_round} لـ {label} (عندنا {len(accepted)}/{target})")
            self.emit_progress("retry_discovery", {
                "type": label,
                "round": retry_round,
                "current": len(accepted),
            })

            exclude = list(self.tried_names)
            candidates = self.discovery.request_more_candidates(
                client_data, profile, type_label, exclude
            )

            if not candidates:
                logger.warning(f"⚠️ لا candidates إضافية متاحة لـ {label}")
                break

        return accepted
    
    def _process_candidate(self, candidate: Candidate) -> OrgResult:
        result = OrgResult(
            name=candidate.name,
            url=candidate.url,
            type=candidate.type,
            country=candidate.country,
            region=candidate.region,
            similarity_score=candidate.similarity_score,
            target_match=candidate.target_match,
            specialization_match=candidate.specialization_match,
            has_diverse_programs=candidate.has_diverse_programs,
            institutional_maturity=candidate.institutional_maturity,
            vision_2030_aligned=candidate.vision_2030_aligned,
            geographic_diversity=candidate.geographic_diversity,
            data_available=candidate.data_available,
            diverse_beneficiaries=candidate.diverse_beneficiaries,
        )
        
        if not candidate.url:
            result.status = "rejected"
            result.error = "لا يوجد رابط"
            return result
        
        # Scraping
        result.status = "scraping"
        try:
            pages = self.scraper.fetch_organization_pages(candidate.url)
            result.pages_fetched = sum(1 for p in pages.values() if p.is_success)
            result.pages_failed = sum(1 for p in pages.values() if not p.is_success)

            if result.pages_fetched == 0:
                result.status = "rejected"
                result.error = "فشل جلب أي صفحة"
                return result

            raw_parts = []
            annual_parts = []
            merged_anchors: dict[str, str] = {}
            for page_type, page in pages.items():
                if not page.is_success:
                    continue
                raw_parts.append(f"\n=== {page_type.upper()} ===\n{page.text}")
                if page_type.startswith("annual_report") or page_type.startswith("document"):
                    annual_parts.append(f"\n=== {page_type.upper()} ===\n{page.text}")
                # نجمّع الـ anchors من الصفحات الـ HTML فقط (مش الـ PDF/DOCX)
                if getattr(page, "link_anchors", None):
                    for url, txt in page.link_anchors.items():
                        merged_anchors.setdefault(url, txt)

            raw_text = "\n".join(raw_parts)
            result.raw_text = raw_text
            result.raw_text_length = len(raw_text)
            result.link_anchors = merged_anchors
            result.annual_report_text = "\n".join(annual_parts)

            # ═══════════════════════════════════════════════════
            # 🆕 v8: Enrichment Pipeline (OCR + Fallback chain)
            # ═══════════════════════════════════════════════════
            try:
                if hasattr(self, "_enrichment_pipeline") and self._enrichment_pipeline is not None:
                    pipeline = self._enrichment_pipeline
                    enriched = pipeline.enrich(
                        organization_name=candidate.name,
                        primary_url=candidate.url,
                        primary_text=raw_text,
                        link_anchors=merged_anchors,
                        country=candidate.country,
                    )
                    # نضيف النصوص الجديدة من الـ enrichment للـ raw_text
                    extra_sources = [
                        s for s in enriched.sources
                        if s.source_tier != "official_website"
                    ]
                    if extra_sources:
                        extra_text = "\n\n".join(
                            f"\n=== {s.source_tier.upper()} ({s.url}) ===\n{s.text}"
                            for s in extra_sources
                        )
                        raw_text = raw_text + "\n" + extra_text
                        result.raw_text = raw_text
                        result.raw_text_length = len(raw_text)
                        # خزّن annual report text لو الـ enrichment جابه
                        annual_from_enrich = "\n\n".join(
                            s.text for s in extra_sources if s.source_tier == "annual_report"
                        )
                        if annual_from_enrich:
                            result.annual_report_text = (
                                (result.annual_report_text or "") + "\n" + annual_from_enrich
                            )
                        logger.info(
                            f"  ✨ Enrichment added {len(extra_sources)} sources, "
                            f"+{len(extra_text)} chars"
                        )
            except Exception as e:
                logger.warning(f"  Enrichment pipeline failed (non-fatal): {e}")

            if len(raw_text) < 500:
                result.status = "rejected"
                result.error = f"النص قصير ({len(raw_text)} حرف)"
                return result

        except Exception as e:
            result.status = "rejected"
            result.error = f"scraping error: {str(e)}"
            return result
        
        # Extraction
        result.status = "extracting"
        try:
            extracted = self.extractor.extract(
                org_name=candidate.name, url=candidate.url, raw_text=raw_text,
            )
            if not extracted:
                result.status = "rejected"
                result.error = "لم يستخرج أي بيانات"
                return result
            
            # 🎯 محاولة إضافية للتمويل لو فاضي
            funding_field = extracted.get("funding_sources", {})
            if not funding_field.get("value"):
                logger.info(f"  💰 محاولة إضافية للتمويل لـ {candidate.name}")
                boost_result = self.funding_booster.boost(raw_text)
                if boost_result.get("found"):
                    extracted["funding_sources"] = {
                        "value": boost_result.get("value"),
                        "exact_quote": boost_result.get("exact_quote"),
                        "source_url": candidate.url,
                    }

            # ⭐ ملء الحقول الفاضية من التقرير السنوي + من نحن (no-hallucination)
            self.field_enricher.enrich_empty_fields(
                extracted=extracted, raw_text=raw_text,
                url=candidate.url, org_name=candidate.name,
            )
            # 📊 تنظيم الأرقام المكدسة في metrics_results
            self.field_enricher.format_metrics(extracted)

        except Exception as e:
            result.status = "rejected"
            result.error = f"extraction error: {str(e)}"
            return result
        
        # Validation
        result.status = "validating"
        try:
            validation = validate_organization(
                org_name=candidate.name, extracted_data=extracted, raw_text=raw_text,
            )
            result.validation = validation
            
            if validation.accepted:
                result.status = "accepted"
                logger.info(f"  ✅ {candidate.name} ({validation.passed_count}/{len(ALL_FIELDS)})")
            else:
                result.status = "rejected"
                result.error = validation.rejection_reason
                logger.info(f"  ❌ {candidate.name} — {validation.rejection_reason}")
        
        except Exception as e:
            result.status = "rejected"
            result.error = f"validation error: {str(e)}"
        
        return result
    
    # حد أقصى لـ deep-crawl لكل جهة (لتفادي تكلفة عالية + بطء)
    MAX_INITIATIVE_DEEP_CRAWL_PER_ORG = 6

    def _extract_initiatives(self) -> list[dict]:
        all_initiatives = []
        accepted = [r for r in self.results if r.is_accepted]
        total_orgs = len(accepted)

        for idx, org in enumerate(accepted, start=1):
            self.emit_progress("initiative_org_start", {
                "org": org.name, "index": idx, "total": total_orgs,
            })
            try:
                initiatives = self.initiative_extractor.extract(
                    org_name=org.name, url=org.url, raw_text=org.raw_text,
                )

                # ⭐ Deep-crawl + enrichment: لكل مبادرة، نحاول نلاقي صفحة تفاصيلها
                # ونملأ الحقول الناقصة منها + من التقرير السنوي.
                self._enrich_initiatives_for_org(org, initiatives)

                for init in initiatives:
                    init["source_org"] = org.name
                    init["source_country"] = org.country
                    init["source_type"] = org.type
                    all_initiatives.append(init)

                org.initiatives = initiatives

                self.emit_progress("initiative_org_complete", {
                    "org": org.name, "index": idx, "total": total_orgs,
                    "initiatives_count": len(initiatives),
                })

            except Exception as e:
                logger.error(f"❌ initiative extraction failed for {org.name}: {e}")
                self.emit_progress("initiative_org_complete", {
                    "org": org.name, "index": idx, "total": total_orgs,
                    "initiatives_count": 0, "error": str(e),
                })

        logger.info(f"📋 إجمالي المبادرات: {len(all_initiatives)}")
        return all_initiatives

    def _enrich_initiatives_for_org(self, org: OrgResult, initiatives: list[dict]) -> None:
        """
        لكل مبادرة:
        1. حدد الحقول الناقصة (description, target_beneficiaries, ...)
        2. لو فيه نقص: دور على لينك صفحة المبادرة في انكور المواقع → اجلبها
        3. اعمل enrich باستخدام نص الصفحة + التقرير السنوي
        """
        if not initiatives:
            return
        if not org.link_anchors and not org.annual_report_text:
            return

        # نبدأ بالمبادرات اللي فيها نقص فعلاً، ونحدّ العدد لتفادي بطء + تكلفة
        from steps.step_05_benchmarking.agents.initiative_extractor import InitiativeExtractor, ENRICH_FIELDS
        needs_enrich = []
        for init in initiatives:
            kpis = init.get("kpis") or []
            if any(InitiativeExtractor._is_empty_value(init.get(f)) for f in ENRICH_FIELDS) \
               or InitiativeExtractor._is_empty_value(kpis):
                needs_enrich.append(init)

        if not needs_enrich:
            return

        annual_text = org.annual_report_text or ""
        deep_crawled = 0

        for init in needs_enrich[: self.MAX_INITIATIVE_DEEP_CRAWL_PER_ORG]:
            init_name = (init.get("name") or "").strip()
            if not init_name:
                continue

            # دور على رابط صفحة تفاصيل المبادرة باسمها
            detail_url = None
            if org.link_anchors:
                # نمرّر pages-like object: نبني dict مؤقت بـ ScrapedPage shim
                detail_url = self._find_initiative_url(init_name, org.link_anchors)

            detail_text = ""
            if detail_url and detail_url != org.url:
                try:
                    self.emit_progress("initiative_deep_crawl", {
                        "org": org.name, "initiative": init_name, "url": detail_url,
                    })
                    detail_page = self.scraper.fetch(detail_url)
                    if detail_page.is_success:
                        detail_text = detail_page.text
                        deep_crawled += 1
                except Exception as e:
                    logger.warning(f"  ⚠️ deep-crawl فشل لـ {init_name}: {e}")

            # حتى لو ما لقينا صفحة تفاصيل، الـ annual_text لوحده ممكن يفيد
            if detail_text or annual_text:
                self.initiative_extractor.enrich(
                    initiative=init,
                    org_name=org.name,
                    detail_text=detail_text,
                    annual_text=annual_text,
                )

        if deep_crawled:
            logger.info(f"  🔬 deep-crawl: {deep_crawled} صفحة مبادرة لـ {org.name}")

    def _find_initiative_url(self, initiative_name: str, link_anchors: dict[str, str]) -> Optional[str]:
        """نسخة مبسطة من EnhancedScraper.find_initiative_link — تشتغل مباشرة على dict واحد."""
        from steps.step_05_benchmarking.agents.scraper import EnhancedScraper
        norm_name = EnhancedScraper._normalize_arabic(initiative_name)
        name_tokens = {t for t in norm_name.split() if len(t) > 2}
        if not name_tokens:
            return None

        best_exact: Optional[str] = None
        best_partial: tuple[int, Optional[str]] = (0, None)

        for url, anchor_text in link_anchors.items():
            norm_anchor = EnhancedScraper._normalize_arabic(anchor_text)
            if not norm_anchor:
                continue

            if norm_name in norm_anchor or (norm_anchor in norm_name and len(norm_anchor) > 5):
                if best_exact is None:
                    best_exact = url
                continue

            anchor_tokens = {t for t in norm_anchor.split() if len(t) > 2}
            overlap = len(name_tokens & anchor_tokens)
            if overlap > best_partial[0] and overlap >= 2:
                best_partial = (overlap, url)

        return best_exact or best_partial[1]
