"""
═══════════════════════════════════════════════════════════════════
Enrichment Pipeline — يربط OCR و Fallback بالـ scraper
═══════════════════════════════════════════════════════════════════

دور هذا الملف: لما الـ scraper الأصلي (v7) يجيب نص من الموقع،
الـ enrichment pipeline:

1. لو فيه روابط PDF (تقارير سنوية) → يستخدم OCR لاستخراج نصوصها
2. لو النص الكلي < threshold → يشغّل Fallback search
3. يدمج كل النصوص مع تتبّع المصادر

المخرج النهائي: نص موحّد + قائمة مصادر مع source_tier لكل واحدة.
هذا الـ enriched_data بيتمرّر للـ extractor عشان يستخرج الحقول الـ 9.
"""
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from steps.step_05_benchmarking.agents.ocr_engine import OCREngine, OCRResult
from steps.step_05_benchmarking.agents.fallback_search import (
    FallbackSearchChain,
    FallbackSearchOutput,
    SearchResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EnrichedSource:
    """مصدر واحد من المصادر اللي تم جمعها"""
    url: str
    text: str
    source_tier: str  # "official_website" | "annual_report" | "linkedin" | "social_media" | "news"
    extraction_method: str  # "html" | "pypdf" | "tesseract" | "vision"
    confidence: str  # "high" | "medium" | "low"


@dataclass
class EnrichedData:
    """البيانات المجمعة من كل المصادر"""
    organization_name: str
    primary_url: str
    sources: list[EnrichedSource] = field(default_factory=list)
    
    @property
    def combined_text(self) -> str:
        """نص موحّد من كل المصادر (مرتب حسب الموثوقية)"""
        parts = []
        # ترتيب: official > annual_report > linkedin > news > social
        tier_order = ["official_website", "annual_report", "linkedin", "news", "social_media"]
        sorted_sources = sorted(
            self.sources,
            key=lambda s: tier_order.index(s.source_tier) if s.source_tier in tier_order else 99
        )
        for src in sorted_sources:
            parts.append(f"\n\n=== مصدر: {src.url} (نوع: {src.source_tier}) ===\n{src.text}")
        return "\n".join(parts).strip()
    
    @property
    def total_chars(self) -> int:
        return sum(len(s.text) for s in self.sources)
    
    @property
    def has_annual_report(self) -> bool:
        return any(s.source_tier == "annual_report" for s in self.sources)


class EnrichmentPipeline:
    """
    pipeline متكامل بيعمل:
    1. اكتشاف روابط PDF في النص الأصلي
    2. تنزيل واستخراج نص الـ PDFs (OCR)
    3. لو النص قليل، تشغيل fallback search
    """
    
    # حد أدنى من النص قبل ما نشغّل fallback
    MIN_TEXT_THRESHOLD = 1500
    
    # أنماط التعرف على روابط التقرير السنوي
    ANNUAL_REPORT_PATTERNS = [
        r'(?i)annual[_\-\s]*report',
        r'(?i)report[_\-\s]*\d{4}',
        r'(?:تقرير[_\-\s]*سنوي|التقرير[_\-\s]*السنوي)',
    ]
    
    def __init__(self, openai_client=None):
        self.ocr = OCREngine(openai_client=openai_client)
        self.fallback = FallbackSearchChain()
        self.openai_client = openai_client
    
    def _is_pdf_url(self, url: str) -> bool:
        """هل الـ URL ده PDF؟"""
        return url.lower().endswith(".pdf") or ".pdf?" in url.lower()
    
    def _is_annual_report_url(self, url: str, anchor_text: str = "") -> bool:
        """هل ده رابط تقرير سنوي؟ (heuristic)"""
        combined = f"{url} {anchor_text}".lower()
        return any(re.search(p, combined) for p in self.ANNUAL_REPORT_PATTERNS)
    
    def _download_pdf(self, url: str, timeout: int = 30) -> Optional[str]:
        """تنزيل PDF لمسار مؤقت"""
        try:
            logger.info(f"⬇️ Downloading: {url}")
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 UNISTEP-Bot/1.0"},
                stream=True,
            )
            response.raise_for_status()
            
            # تأكد من نوع الملف
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not self._is_pdf_url(url):
                logger.warning(f"  Not a PDF (content-type: {content_type})")
                return None
            
            # احفظ في temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                return f.name
        except Exception as e:
            logger.warning(f"  Download failed: {e}")
            return None
    
    def _extract_pdf_links_from_anchors(
        self,
        link_anchors: dict,
        prefer_annual_reports: bool = True,
        max_pdfs: int = 3,
    ) -> list[tuple[str, str]]:
        """
        استخراج روابط PDFs من الـ link_anchors اللي v7 scraper بيرجعها.
        
        link_anchors: dict بصيغة {url: anchor_text}
        
        Returns: list of (url, anchor_text) tuples
        """
        candidates = []
        for url, anchor in link_anchors.items():
            if self._is_pdf_url(url):
                is_report = self._is_annual_report_url(url, anchor)
                # priority: التقارير السنوية أولاً
                priority = 0 if is_report else 1
                candidates.append((priority, url, anchor))
        
        candidates.sort(key=lambda x: x[0])
        return [(url, anchor) for (_, url, anchor) in candidates[:max_pdfs]]
    
    # ═══════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════
    def enrich(
        self,
        organization_name: str,
        primary_url: str,
        primary_text: str,
        link_anchors: Optional[dict] = None,
        country: str = "",
        force_fallback: bool = False,
    ) -> EnrichedData:
        """
        تشغيل الـ pipeline كاملاً.
        
        Args:
            organization_name: اسم الجمعية
            primary_url: الـ URL الأساسي
            primary_text: النص اللي v7 scraper جابه من الموقع الرسمي
            link_anchors: dict {url: anchor} (من scraper output)
            country: الدولة
            force_fallback: تشغيل fallback حتى لو النص كافي
        
        Returns:
            EnrichedData — كل المصادر مدمجة
        """
        enriched = EnrichedData(
            organization_name=organization_name,
            primary_url=primary_url,
        )
        
        # ═══ Source 1: الموقع الرسمي ═══
        if primary_text and len(primary_text) > 200:
            enriched.sources.append(EnrichedSource(
                url=primary_url,
                text=primary_text,
                source_tier="official_website",
                extraction_method="html",
                confidence="high",
            ))
            logger.info(f"  ✓ Primary site: {len(primary_text)} chars")
        
        # ═══ Source 2: التقارير السنوية PDF (لو موجودة) ═══
        if link_anchors:
            pdf_links = self._extract_pdf_links_from_anchors(link_anchors, max_pdfs=3)
            for pdf_url, anchor in pdf_links:
                pdf_path = self._download_pdf(pdf_url)
                if not pdf_path:
                    continue
                
                try:
                    is_annual_report = self._is_annual_report_url(pdf_url, anchor)
                    ocr_result = self.ocr.extract_text(pdf_path)
                    
                    if ocr_result.is_successful:
                        enriched.sources.append(EnrichedSource(
                            url=pdf_url,
                            text=ocr_result.text,
                            source_tier="annual_report" if is_annual_report else "official_website",
                            extraction_method=ocr_result.method,
                            confidence=ocr_result.confidence,
                        ))
                        logger.info(
                            f"  ✓ PDF ({ocr_result.method}): {len(ocr_result.text)} chars"
                            f" {'[annual report]' if is_annual_report else ''}"
                        )
                finally:
                    # نظّف ملف الـ temp
                    try:
                        Path(pdf_path).unlink(missing_ok=True)
                    except Exception:
                        pass
        
        # ═══ Source 3+: Fallback (لو النص لسه قليل) ═══
        needs_fallback = force_fallback or enriched.total_chars < self.MIN_TEXT_THRESHOLD
        
        if needs_fallback:
            logger.info(f"  ⚠️ Need fallback (current: {enriched.total_chars} chars)")
            
            fallback_output = self.fallback.search(
                organization_name=organization_name,
                country=country,
            )
            
            # جمّع snippets من الـ search results (مش هنفتح كل URL — مكلف)
            for results, tier in [
                (fallback_output.linkedin_results, "linkedin"),
                (fallback_output.news_results, "news"),
                (fallback_output.social_results, "social_media"),
            ]:
                for r in results[:3]:  # max 3 من كل tier
                    text = f"العنوان: {r.title}\nالوصف: {r.snippet}"
                    if text.strip():
                        enriched.sources.append(EnrichedSource(
                            url=r.url,
                            text=text,
                            source_tier=tier,
                            extraction_method="search_snippet",
                            confidence="low",  # snippets ليست مصدر موثوق
                        ))
        
        logger.info(
            f"  📊 Enrichment done: {len(enriched.sources)} sources, "
            f"{enriched.total_chars} total chars"
        )
        return enriched
