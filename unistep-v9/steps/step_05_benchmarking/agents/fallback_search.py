"""
═══════════════════════════════════════════════════════════════════
Fallback Search Chain — للمواقع الفقيرة بالمعلومات
═══════════════════════════════════════════════════════════════════

المشكلة: كثير من الجمعيات (خصوصاً الصغيرة والمتوسطة) عندها مواقع
بسيطة جداً ما فيهاش تفاصيل كافية عن البرامج أو المؤشرات.

الحل: سلسلة بحث بديلة — ترتيبها مهم من الأكثر موثوقية للأقل:

١. التقرير السنوي PDF (موثوقية 🟢) — لو متاح في Google
٢. صفحة LinkedIn الرسمية (🟡) — للمعلومات المؤسسية
٣. حسابات السوشيال (Twitter/Instagram) (🟡) — للنشاطات الحديثة
٤. المواقع الإخبارية (🟡) — للأخبار والإنجازات

كل layer بترجع SearchResult مع source_tier للـ confidence.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """نتيجة بحث من مصدر معين"""
    url: str
    title: str
    snippet: str
    source_tier: str  # "annual_report" | "linkedin" | "social_media" | "news"
    layer: int  # 1, 2, 3, 4
    
    @property
    def domain(self) -> str:
        try:
            return urlparse(self.url).netloc
        except Exception:
            return ""


@dataclass
class FallbackSearchOutput:
    """مخرج Fallback search — كل النتائج من كل الـ layers"""
    organization_name: str
    layers_tried: list[int] = field(default_factory=list)
    annual_reports: list[SearchResult] = field(default_factory=list)
    linkedin_results: list[SearchResult] = field(default_factory=list)
    social_results: list[SearchResult] = field(default_factory=list)
    news_results: list[SearchResult] = field(default_factory=list)
    
    @property
    def has_any_results(self) -> bool:
        return any([
            self.annual_reports, self.linkedin_results,
            self.social_results, self.news_results,
        ])
    
    @property
    def best_results(self) -> list[SearchResult]:
        """الأفضل بالترتيب: annual_reports > linkedin > news > social"""
        return [
            *self.annual_reports,
            *self.linkedin_results,
            *self.news_results,
            *self.social_results,
        ]


class FallbackSearchChain:
    """
    Search chain بديل لما الموقع الرسمي مش بيدّي معلومات كافية.
    
    Usage:
        chain = FallbackSearchChain()
        output = chain.search("جمعية البر بالرياض", country="السعودية")
        for r in output.best_results:
            print(f"{r.source_tier}: {r.url}")
    """
    
    # حد أدنى من النص في الموقع الرسمي لاعتباره "كافي"
    MIN_TEXT_THRESHOLD = 1500
    
    def __init__(self, max_results_per_layer: int = 5):
        self.max_results_per_layer = max_results_per_layer
    
    # ═══════════════════════════════════════════════════
    # Layer 1: Annual Report Search
    # ═══════════════════════════════════════════════════
    def _search_annual_reports(self, org_name: str, country: str = "") -> list[SearchResult]:
        """ابحث عن التقرير السنوي PDF"""
        queries = [
            f'"{org_name}" تقرير سنوي filetype:pdf',
            f'"{org_name}" annual report filetype:pdf',
            f'{org_name} تقرير سنوي 2024',
            f'{org_name} تقرير سنوي 2023',
        ]
        
        all_results = []
        for q in queries:
            results = self._duckduckgo_search(q, max_results=3)
            for r in results:
                # نقبل بس روابط PDF
                if r.url.lower().endswith(".pdf") or "filetype=pdf" in r.url.lower():
                    all_results.append(SearchResult(
                        url=r.url, title=r.title, snippet=r.snippet,
                        source_tier="annual_report", layer=1,
                    ))
            time.sleep(0.5)  # rate limit
            if len(all_results) >= self.max_results_per_layer:
                break
        
        return all_results[:self.max_results_per_layer]
    
    # ═══════════════════════════════════════════════════
    # Layer 2: LinkedIn
    # ═══════════════════════════════════════════════════
    def _search_linkedin(self, org_name: str) -> list[SearchResult]:
        """ابحث عن صفحة LinkedIn الرسمية"""
        queries = [
            f'"{org_name}" site:linkedin.com/company',
            f'{org_name} linkedin',
        ]
        
        all_results = []
        for q in queries:
            results = self._duckduckgo_search(q, max_results=3)
            for r in results:
                if "linkedin.com" in r.url:
                    all_results.append(SearchResult(
                        url=r.url, title=r.title, snippet=r.snippet,
                        source_tier="linkedin", layer=2,
                    ))
            time.sleep(0.5)
            if len(all_results) >= self.max_results_per_layer:
                break
        
        return all_results[:self.max_results_per_layer]
    
    # ═══════════════════════════════════════════════════
    # Layer 3: Social Media (Twitter/Instagram)
    # ═══════════════════════════════════════════════════
    def _search_social(self, org_name: str) -> list[SearchResult]:
        """ابحث في Twitter و Instagram"""
        queries = [
            f'"{org_name}" site:twitter.com',
            f'"{org_name}" site:x.com',
            f'"{org_name}" site:instagram.com',
        ]
        
        all_results = []
        for q in queries:
            results = self._duckduckgo_search(q, max_results=2)
            for r in results:
                if any(d in r.url for d in ["twitter.com", "x.com", "instagram.com"]):
                    all_results.append(SearchResult(
                        url=r.url, title=r.title, snippet=r.snippet,
                        source_tier="social_media", layer=3,
                    ))
            time.sleep(0.5)
            if len(all_results) >= self.max_results_per_layer:
                break
        
        return all_results[:self.max_results_per_layer]
    
    # ═══════════════════════════════════════════════════
    # Layer 4: News
    # ═══════════════════════════════════════════════════
    def _search_news(self, org_name: str, country: str = "") -> list[SearchResult]:
        """ابحث في المواقع الإخبارية"""
        # المواقع الإخبارية السعودية الموثوقة
        news_sites = [
            "alarabiya.net", "alyaum.com", "alriyadh.com",
            "alwatan.com.sa", "okaz.com.sa", "spa.gov.sa",
        ]
        
        queries = [f'"{org_name}" 2024'] + [f'"{org_name}" site:{site}' for site in news_sites[:3]]
        
        all_results = []
        for q in queries:
            results = self._duckduckgo_search(q, max_results=2)
            for r in results:
                # نقبل لو domain من news_sites أو لو snippet بيتكلم عن أخبار
                domain = urlparse(r.url).netloc
                if any(news in domain for news in news_sites) or "news" in domain:
                    all_results.append(SearchResult(
                        url=r.url, title=r.title, snippet=r.snippet,
                        source_tier="news", layer=4,
                    ))
            time.sleep(0.5)
            if len(all_results) >= self.max_results_per_layer:
                break
        
        return all_results[:self.max_results_per_layer]
    
    # ═══════════════════════════════════════════════════
    # Internal: DuckDuckGo search
    # ═══════════════════════════════════════════════════
    def _duckduckgo_search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """استعلام DuckDuckGo (مجاني، بدون API key)"""
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddg:
                for r in ddg.text(query, max_results=max_results, region="xa-ar"):
                    results.append(SearchResult(
                        url=r.get("href", ""),
                        title=r.get("title", ""),
                        snippet=r.get("body", ""),
                        source_tier="unknown",
                        layer=0,
                    ))
            return results
        except Exception as e:
            logger.warning(f"DDG search failed for '{query}': {e}")
            return []
    
    # ═══════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════
    def search(
        self,
        organization_name: str,
        country: str = "",
        layers: Optional[list[int]] = None,
    ) -> FallbackSearchOutput:
        """
        تشغيل الـ fallback chain.
        
        Args:
            organization_name: اسم الجمعية
            country: الدولة (للسياق)
            layers: لو محدد، يشغّل بس الـ layers دي. الافتراضي: الكل.
        
        Returns:
            FallbackSearchOutput — كل النتائج من كل الـ layers
        """
        if layers is None:
            layers = [1, 2, 3, 4]
        
        output = FallbackSearchOutput(organization_name=organization_name)
        
        logger.info(f"🔍 Fallback search for: {organization_name}")
        
        if 1 in layers:
            output.layers_tried.append(1)
            output.annual_reports = self._search_annual_reports(organization_name, country)
            logger.info(f"  Layer 1 (annual reports): {len(output.annual_reports)} results")
        
        if 2 in layers:
            output.layers_tried.append(2)
            output.linkedin_results = self._search_linkedin(organization_name)
            logger.info(f"  Layer 2 (LinkedIn): {len(output.linkedin_results)} results")
        
        if 3 in layers:
            output.layers_tried.append(3)
            output.social_results = self._search_social(organization_name)
            logger.info(f"  Layer 3 (social): {len(output.social_results)} results")
        
        if 4 in layers:
            output.layers_tried.append(4)
            output.news_results = self._search_news(organization_name, country)
            logger.info(f"  Layer 4 (news): {len(output.news_results)} results")
        
        return output
    
    def should_use_fallback(self, raw_text: str) -> bool:
        """قرار: هل المحتوى من الموقع الرسمي 'كافي' أم نحتاج fallback؟"""
        if not raw_text:
            return True
        return len(raw_text) < self.MIN_TEXT_THRESHOLD
