"""
═══════════════════════════════════════════════════════════
Web Search Tool — DuckDuckGo
═══════════════════════════════════════════════════════════

🎯 الغرض: حل مشكلة الـ AI hallucination في الـ URLs.

GPT بيرجّع أسماء جمعيات صحيحة لكن URLs مهلوسة (example.org).
الحل: نخلي GPT يرجع الاسم بس، ونبحث في DDG للـ URL الحقيقي.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("⚠️ ddgs not installed — web search disabled")


# URLs مهلوسة أو placeholders — دايماً نرفضها
HALLUCINATION_PATTERNS = [
    "example.org", "example.com", "example.net",
    "localhost", "127.0.0.1", "0.0.0.0",
    "your-website.com", "yoursite.com", "website.com",
    "domain.com", "placeholder",
    "test.com", "sample.com",
]

# مواقع نتجاهلها في نتايج البحث (مش مواقع جمعيات)
SEARCH_BLACKLIST = [
    "wikipedia.org", "wikiwand.com",
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com",
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "saudipedia.com", "spa.gov.sa",  # وكالة الأنباء
    "youtu.be", "pinterest.com", "reddit.com",
    "amazon.com", "aliexpress.com",
    "scholar.google", "academia.edu",
]


def is_hallucinated_url(url: str) -> bool:
    """فحص لو الـ URL مهلوس (placeholder)"""
    if not url:
        return True
    url_lower = url.lower().strip()
    return any(p in url_lower for p in HALLUCINATION_PATTERNS)


def is_blacklisted(url: str) -> bool:
    """فحص لو الـ URL في الـ blacklist (سوشيال/wiki/إلخ)"""
    if not url:
        return True
    url_lower = url.lower()
    return any(b in url_lower for b in SEARCH_BLACKLIST)


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


class WebSearchTool:
    """بحث في DDG عن الموقع الرسمي للجمعية"""

    def __init__(self, max_results: int = 5, region: str = "wt-wt"):
        self.max_results = max_results
        self.region = region

    def search_official_url(self, org_name: str, country_hint: str = "") -> str:
        """
        ابحث عن الموقع الرسمي لجمعية باسمها.
        Returns: URL أو string فاضي لو ما لقاش.
        """
        if not HAS_DDGS or not org_name:
            return ""

        # ابني query أذكى
        queries = [
            f'"{org_name}" official website',
            f'{org_name} الموقع الرسمي',
            org_name,
        ]
        if country_hint:
            queries.insert(0, f'{org_name} {country_hint} official site')

        seen = set()
        for query in queries:
            try:
                results = list(DDGS().text(
                    query,
                    max_results=self.max_results,
                    region=self.region,
                ))
            except Exception as e:
                logger.warning(f"  ⚠️ DDG search failed for '{org_name}': {e}")
                continue

            for r in results:
                url = r.get("href", "") or r.get("url", "")
                if not url:
                    continue
                domain = get_domain(url)
                if not domain or domain in seen:
                    continue
                seen.add(domain)

                if is_hallucinated_url(url) or is_blacklisted(url):
                    continue

                # نتيجة لائقة — رجّع
                logger.info(f"  🔎 {org_name[:40]} → {url}")
                return url.rstrip("/") + "/"

        logger.warning(f"  ⚠️ مفيش URL لـ '{org_name[:40]}'")
        return ""

    def search_orgs_batch(
        self,
        orgs: list[dict],
        country_hint: str = "",
        max_workers: int = 5,
    ) -> list[dict]:
        """
        بحث متوازي لمجموعة جمعيات.
        كل dict فيه على الأقل {"name": ...} — هنحط فيه url.
        """
        def _resolve(item: dict) -> dict:
            name = item.get("name", "")
            existing_url = item.get("url", "")

            # لو الـ URL الموجود مش مهلوس، خليه
            if existing_url and not is_hallucinated_url(existing_url):
                return item

            # دور على URL حقيقي
            real_url = self.search_official_url(name, country_hint)
            item["url"] = real_url
            return item

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_resolve, orgs))


# ═══ Helper for Discovery: search for orgs by topic ═══

class TopicSearchTool:
    """بحث عن جمعيات حسب موضوع/تخصص (لاكتشاف candidates إضافيين)"""

    def __init__(self, max_results: int = 10, region: str = "wt-wt"):
        self.max_results = max_results
        self.region = region

    def find_orgs(self, topic: str, country: str = "Saudi Arabia") -> list[dict]:
        """
        ابحث عن جمعيات في موضوع معين.
        Returns: [{"name": ..., "url": ..., "snippet": ...}]
        """
        if not HAS_DDGS:
            return []

        country_ar = "السعودية" if "saudi" in country.lower() else country
        queries = [
            f'جمعية {topic} {country_ar} الموقع الرسمي',
            f'{topic} non-profit organization {country}',
            f'{topic} foundation {country}',
        ]

        all_results = {}
        for query in queries:
            try:
                results = list(DDGS().text(query, max_results=self.max_results, region=self.region))
            except Exception:
                continue

            for r in results:
                url = r.get("href", "") or r.get("url", "")
                title = r.get("title", "")
                snippet = r.get("body", "")
                if not url or is_hallucinated_url(url) or is_blacklisted(url):
                    continue
                domain = get_domain(url)
                if domain in all_results:
                    continue
                all_results[domain] = {
                    "name": title.strip(),
                    "url": url.rstrip("/") + "/",
                    "snippet": snippet[:200],
                }

        return list(all_results.values())[:15]
