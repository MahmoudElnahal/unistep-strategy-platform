"""
═══════════════════════════════════════════════════════════
Smart Discovery v7
═══════════════════════════════════════════════════════════

🎯 التركيز:
- التخصص الدقيق (مش القطاع العام)
- مثال: "أطراف صناعية" مش "إعاقة حركية بشكل عام"
- نفس الفئة المستهدفة بالضبط

🚨 يطلب 15 candidate لكل نوع — ضمان للوصول لـ 3+3
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from openai import OpenAI

from steps.step_05_benchmarking.agents.web_search import (
    WebSearchTool,
    is_hallucinated_url,
    is_blacklisted,
)

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    name: str
    url: str
    type: str
    country: str
    region: str
    relevance_reason: str
    
    # 5 إلزاميات
    target_match: bool = False
    specialization_match: bool = False
    has_diverse_programs: bool = False
    institutional_maturity: bool = False
    vision_2030_aligned: bool = False
    
    # 3 ثانوية
    geographic_diversity: bool = False
    data_available: bool = False
    diverse_beneficiaries: bool = False
    
    similarity_score: int = 0
    mandatory_count: int = 0
    
    verified: bool = False
    verification_status: int = 0
    
    @property
    def passes_mandatory(self) -> bool:
        return all([
            self.target_match, self.specialization_match,
            self.has_diverse_programs, self.institutional_maturity,
            self.vision_2030_aligned,
        ])


EXCLUDED_DOMAINS = [
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com",
    "wikipedia.org", "wikiwand.com",
    "saudipedia.com", "bankelarb.net",
    "google.com", "bing.com", "yahoo.com",
]


def is_excluded_domain(url: str) -> bool:
    return any(d in url.lower() for d in EXCLUDED_DOMAINS)


def verify_url(url: str, timeout: int = 8) -> tuple[bool, int]:
    try:
        headers = {"User-Agent": "Mozilla/5.0 Chrome/131.0"}
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
            r.close()
        return (200 <= r.status_code < 400, r.status_code)
    except Exception:
        return (False, 0)


def verify_candidates_parallel(candidates: list, max_workers: int = 5) -> list:
    def _verify(c):
        if c.url:
            verified, status = verify_url(c.url)
            c.verified = verified
            c.verification_status = status
        return c
    
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(_verify, candidates))


PROFILE_ANALYSIS_PROMPT = """أنت مستشار استراتيجي خبير.
حلل بيانات الجمعية العميل، واستنتج ملف "الجمعية المنافسة المثالية" بدقة.

**بيانات العميل:**
- الاسم: {name}
- القطاع العام: {sector}
- التخصص الدقيق: {specialization}
- الفئة المستهدفة (تفصيلاً): {target_audience}
- حجم الجمعية: {organization_size}
- البرامج: {programs}
- الأهداف: {goals}

🚨 **ركز على التخصص الدقيق، مش القطاع العام:**
- لو "أطراف صناعية" → ابحث عن جمعيات أطراف صناعية تحديداً (مش أي إعاقة)
- لو "تأهيل عقلي" → جمعيات تأهيل عقلي (مش أي إعاقة)
- لو "أيتام تعليم عالي" → جمعيات تعليم عالي للأيتام (مش رعاية أيتام عام)

**أرجع JSON:**
```json
{{
  "core_focus": "تركيز أساسي محدد جداً (1 جملة)",
  "ideal_specialization_keywords": [
    "3-5 كلمات/مفاهيم تحدد التخصص الدقيق المطلوب"
  ],
  "key_target_segments": [
    "تفصيل دقيق للفئات المستهدفة"
  ],
  "must_have_features": [
    "ميزات لا غنى عنها — لو مش موجودة فالجمعية مش منافس مناسب"
  ],
  "must_avoid_features": [
    "ميزات تستبعد الجمعية تلقائياً"
  ]
}}
```
"""


DISCOVERY_PROMPT = """أنت خبير في القطاع غير الربحي السعودي والدولي.

**ملف الجمعية العميل:**
- الاسم: {client_name}
- التخصص الدقيق: {specialization}
- الفئة المستهدفة (تفصيلاً): {target_audience}
- حجم الجمعية: {organization_size}
- التركيز الأساسي: {core_focus}
- كلمات التخصص: {specialization_keywords}

**🎯 المطلوب: 15 جمعية محلية سعودية + 15 منظمة دولية**

🚨 **عدد كبير جداً لأن:**
- نحتاج 3 محلية + 3 دولية كحد أدنى مضمون
- بعض المواقع لن تستجيب
- بعض الجمعيات لن تستوفي شروط البيانات
- نريد backup كاف

**🔴 5 شروط إلزامية لكل candidate:**

1. **target_match**: تخدم نفس الفئة الدقيقة (مش القطاع العام)
2. **specialization_match**: نفس التخصص الفرعي تحديداً (مش العام)
3. **has_diverse_programs**: 3+ مبادرات متنوعة
4. **institutional_maturity**: هيكل تنظيمي + تقارير منشورة
5. **vision_2030_aligned**: للجهات المحلية فقط (للدولية: true لو قيمها متوافقة)

**🟡 3 شروط ثانوية:**
6. geographic_diversity
7. data_available
8. diverse_beneficiaries

**🚨 قواعد صارمة:**
- ❌ لا ترشح جمعيات قطاعها مختلف رغم تشابه الاسم
- ❌ مثال خاطئ: عميل = "أطراف صناعية" → ترشح "إعاقة حركية" ❌
- ✅ مثال صحيح: عميل = "أطراف صناعية" → ترشح جمعيات أطراف صناعية فقط
- ❌ لا تشمل: facebook, wikipedia, news sites
- ✅ روابط حقيقية فقط (لو غير متأكد، اتركها فارغة "")
- ✅ تنوع جغرافي (محلية: 4 مناطق سعودية | دولية: USA, UK, Germany, Turkey, Malaysia, Nigeria, إلخ)

**أرجع JSON:**
```json
{{
  "local_candidates": [
    {{
      "name": "اسم الجمعية بالكامل",
      "url": "https://...",
      "country": "Saudi Arabia",
      "region": "الرياض/جدة/الدمام/إلخ",
      "core_focus": "تركيز هذه الجهة بدقة",
      
      "target_match": true,
      "specialization_match": true,
      "has_diverse_programs": true,
      "institutional_maturity": true,
      "vision_2030_aligned": true,
      
      "geographic_diversity": true,
      "data_available": true,
      "diverse_beneficiaries": true,
      
      "similarity_score": 85,
      "relevance_reason": "سبب الاختيار محدد"
    }}
  ],
  "international_candidates": [...نفس البنية، 15 منظمة...]
}}
```

🚨 **العدد المطلوب: 15 محلية + 15 دولية. لا تكتفي بأقل.**
"""


class SmartDiscoveryAgent:
    def __init__(self, openai_client: OpenAI, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model
    
    def discover(self, client_data: dict) -> dict:
        logger.info(f"🔍 Smart Discovery v7 لـ: {client_data.get('name')}")
        
        # Step 1: Profile
        profile = self._analyze_profile(client_data)
        logger.info(f"  🧠 التركيز: {profile.get('core_focus')}")
        
        # Step 2: Discovery (15+15)
        candidates = self._discover_with_profile(client_data, profile)
        
        local = self._process_candidates(candidates.get("local_candidates", []), "local")
        international = self._process_candidates(candidates.get("international_candidates", []), "international")
        
        # Verification بالتوازي
        local = verify_candidates_parallel(local)
        international = verify_candidates_parallel(international)
        
        # رتّب: passes_mandatory → verified → similarity_score
        local.sort(key=lambda c: (-int(c.passes_mandatory), -int(c.verified), -c.similarity_score))
        international.sort(key=lambda c: (-int(c.passes_mandatory), -int(c.verified), -c.similarity_score))
        
        passing_local = sum(1 for c in local if c.passes_mandatory)
        passing_intl = sum(1 for c in international if c.passes_mandatory)
        
        logger.info(
            f"  ✅ النتيجة: {len(local)} محلية ({passing_local} تجتاز) + "
            f"{len(international)} دولية ({passing_intl} تجتاز)"
        )
        
        return {
            "local": local,
            "international": international,
            "client_profile": profile,
        }
    
    def _analyze_profile(self, client_data: dict) -> dict:
        goals = client_data.get("strategic_goals") or []
        if isinstance(goals, list):
            goals_text = ", ".join(goals)
        else:
            goals_text = str(goals)
        
        prompt = PROFILE_ANALYSIS_PROMPT.format(
            name=client_data.get("name", ""),
            sector=client_data.get("sector", ""),
            specialization=client_data.get("specialization", ""),
            target_audience=client_data.get("target_audience", ""),
            organization_size=client_data.get("organization_size", "غير محدد"),
            programs=client_data.get("sample_program", "غير محدد"),
            goals=goals_text or "غير محدد",
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "أنت مستشار استراتيجي دقيق."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return json.loads(response.choices[0].message.content)
        
        except Exception as e:
            logger.warning(f"⚠️ profile analysis failed: {e}")
            return {
                "core_focus": client_data.get("specialization", ""),
                "ideal_specialization_keywords": [],
                "key_target_segments": [],
                "must_have_features": [],
                "must_avoid_features": [],
            }
    
    def _web_search(self, query: str) -> str:
        """يستخدم web_search_preview tool عبر Responses API لجلب نتائج بحث حقيقية."""
        try:
            response = self.client.responses.create(
                model=self.model,
                tools=[{"type": "web_search_preview"}],
                input=query,
            )
            return getattr(response, "output_text", "") or ""
        except Exception as e:
            logger.warning(f"⚠️ web search failed: {e}")
            return ""

    def _discover_with_profile(self, client_data: dict, profile: dict) -> dict:
        keywords = profile.get("ideal_specialization_keywords", [])
        keywords_str = ", ".join(keywords) if keywords else client_data.get("specialization", "")
        specialization = client_data.get("specialization", "")
        target_audience = client_data.get("target_audience", "")

        # Step 1: web search حقيقي للمنظمات المحلية والدولية
        logger.info("  🌐 web search عن المنظمات المحلية...")
        local_search = self._web_search(
            f"اذكر بالاسم والـ URL الرسمي لكل جمعية ومركز ومؤسسة سعودية متخصصة في "
            f"{specialization} (تخدم {target_audience}). "
            f"أعطني 15 جهة على الأقل مع الـ URL الرسمي لموقع كل واحدة. "
            f"تأكد إن الـ URLs حقيقية وموجودة فعلاً ومن مصادر موثوقة (المركز الوطني لتنمية القطاع غير الربحي، إحسان، وزارة الموارد البشرية)."
        )

        logger.info("  🌐 web search عن المنظمات الدولية...")
        intl_search = self._web_search(
            f"List 15 real international NGOs and nonprofits specialized in {specialization} "
            f"(serving {target_audience}) with their official website URLs. "
            f"Make sure URLs are real and currently working. "
            f"Only include organizations from reliable sources (Charity Navigator, GuideStar, official org listings)."
        )

        prompt = DISCOVERY_PROMPT.format(
            client_name=client_data.get("name", ""),
            specialization=specialization,
            target_audience=target_audience,
            organization_size=client_data.get("organization_size", "غير محدد"),
            core_focus=profile.get("core_focus", ""),
            specialization_keywords=keywords_str,
        )

        if local_search or intl_search:
            prompt += f"\n\n**🌐 نتائج البحث على الويب — استخدم هذه الـ URLs الحقيقية فقط:**\n\n"
            if local_search:
                prompt += f"### نتائج البحث المحلية:\n{local_search[:6000]}\n\n"
            if intl_search:
                prompt += f"### International search results:\n{intl_search[:6000]}\n\n"
            prompt += (
                "🚨 **التزم بالـ URLs اللي ظهرت في نتائج البحث فقط. "
                "لا تخترع أي URL من عندك. لو منظمة ما لقيت لها URL في النتائج، اتركها.**"
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "خبير في تنظيم نتائج البحث للقطاع غير الربحي. "
                        "تستخدم فقط الـ URLs الموجودة في نتائج البحث المرفقة. "
                        "ممنوع منعاً باتاً اختراع URLs أو تخمينها. "
                        "لو ما لقيت URL لمنظمة في نتائج البحث، اتركها أو اترك url فاضي."
                    )},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=6000,
            )
            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"❌ Discovery failed: {e}")
            return {"local_candidates": [], "international_candidates": []}
    
    def _process_candidates(self, raw: list[dict], type_label: str) -> list[Candidate]:
        # ⭐ Step 1: تنظيف الـ URLs المهلوسة + تجميع الأسماء
        cleaned = []
        seen_names = set()
        for item in raw:
            if isinstance(item, str):
                item = {"name": item}
            elif not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            url = (item.get("url") or "").strip()

            if not name:
                continue
            name_key = name.lower().strip()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)

            if url:
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                url = url.rstrip("/") + "/"

            # ⚠️ رفض URLs المهلوسة من الـ AI (example.org, etc.)
            if url and (is_hallucinated_url(url) or is_blacklisted(url) or is_excluded_domain(url)):
                logger.info(f"  ⚠️ URL مهلوس/blacklisted لـ '{name[:40]}' — هنبحث له")
                url = ""

            item["name"] = name
            item["url"] = url
            cleaned.append(item)

        # ⭐ Step 2: للجمعيات بدون URL — ابحث في DDG
        no_url = [it for it in cleaned if not it.get("url")]
        if no_url:
            logger.info(f"  🔎 بحث في DDG لـ {len(no_url)} جمعية بدون URL...")
            country_hint = "السعودية" if type_label == "local" else ""
            searcher = WebSearchTool()
            searcher.search_orgs_batch(no_url, country_hint=country_hint)

        # ⭐ Step 3: بناء الـ Candidate objects
        candidates = []
        for item in cleaned:
            name = item["name"]
            url = item.get("url", "")
            
            c = Candidate(
                name=name,
                url=url,
                type=type_label,
                country=item.get("country", ""),
                region=item.get("region", ""),
                relevance_reason=item.get("relevance_reason", ""),
                
                target_match=bool(item.get("target_match", False)),
                specialization_match=bool(item.get("specialization_match", False)),
                has_diverse_programs=bool(item.get("has_diverse_programs", False)),
                institutional_maturity=bool(item.get("institutional_maturity", False)),
                vision_2030_aligned=bool(item.get("vision_2030_aligned", False)),
                
                geographic_diversity=bool(item.get("geographic_diversity", False)),
                data_available=bool(item.get("data_available", False)),
                diverse_beneficiaries=bool(item.get("diverse_beneficiaries", False)),
                
                similarity_score=int(item.get("similarity_score", 0)),
            )
            
            c.mandatory_count = sum([
                c.target_match, c.specialization_match,
                c.has_diverse_programs, c.institutional_maturity,
                c.vision_2030_aligned,
            ])
            
            candidates.append(c)
        
        return candidates
    
    def request_more_candidates(self, client_data: dict, profile: dict, type_label: str, exclude_names: list[str]) -> list[Candidate]:
        """طلب candidates إضافيين لو فشلت المحاولة الأولى"""
        logger.info(f"🔄 طلب candidates إضافيين ({type_label})")
        
        exclude_str = "\n".join(f"- {n}" for n in exclude_names) if exclude_names else "(لا يوجد)"
        
        country_default = "Saudi Arabia" if type_label == "local" else "Various"
        specialization = client_data.get("specialization", "")
        target_audience = client_data.get("target_audience", "")

        # web search لجلب URLs حقيقية للـ retry
        if type_label == "local":
            logger.info(f"  🌐 web search retry للمنظمات المحلية (استبعاد {len(exclude_names)})")
            search_results = self._web_search(
                f"اذكر بالاسم والـ URL الرسمي لجمعيات سعودية متخصصة في {specialization} "
                f"(غير: {', '.join(exclude_names[:20])}). "
                f"أعطني 10 جهات بـ URLs حقيقية ومن مصادر موثوقة فقط."
            )
        else:
            logger.info(f"  🌐 web search retry للمنظمات الدولية (استبعاد {len(exclude_names)})")
            search_results = self._web_search(
                f"List 10 real international NGOs specialized in {specialization} with official URLs "
                f"(exclude: {', '.join(exclude_names[:20])})."
            )

        extra_prompt = f"""
نحتاج candidates إضافيين من نوع {type_label} (محلية سعودية أو دولية).

**استبعد هؤلاء (تم تجربتهم بالفعل):**
{exclude_str}

**نريد 10 candidates جدد** بنفس المعايير:
- التخصص الدقيق: {client_data.get('specialization', '')}
- الفئة المستهدفة: {client_data.get('target_audience', '')}
- التركيز: {profile.get('core_focus', '')}

🚨 **مهم جداً:** كل candidate يجب أن يكون object كامل بكل هذه الحقول:
- name (اسم الجمعية)
- url (الرابط الرسمي — لو ما تعرفه يقيناً، خمّن أقرب رابط محتمل مثل <name>.org)
- country
- region
- target_match, specialization_match, has_diverse_programs,
  institutional_maturity, vision_2030_aligned (booleans)
- geographic_diversity, data_available, diverse_beneficiaries (booleans)
- similarity_score (رقم 0-100)
- relevance_reason (سبب الترشيح)

أرجع JSON بهذا الشكل بالضبط:
```json
{{
  "candidates": [
    {{
      "name": "اسم المنظمة",
      "url": "https://example.org/",
      "country": "{country_default}",
      "region": "الرياض",
      "target_match": true,
      "specialization_match": true,
      "has_diverse_programs": true,
      "institutional_maturity": true,
      "vision_2030_aligned": true,
      "geographic_diversity": true,
      "data_available": true,
      "diverse_beneficiaries": true,
      "similarity_score": 80,
      "relevance_reason": "سبب الترشيح"
    }}
  ]
}}
```

🚨 لا ترجع strings داخل candidates — كل عنصر يجب أن يكون object كامل.
"""

        if search_results:
            extra_prompt += f"\n\n**🌐 نتائج البحث على الويب — استخدم هذه الـ URLs الحقيقية فقط:**\n{search_results[:6000]}\n\n"
            extra_prompt += "🚨 ممنوع اختراع URLs. استخدم فقط ما ظهر في نتائج البحث."

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "خبير في تنظيم نتائج البحث للقطاع غير الربحي. "
                        "تستخدم فقط الـ URLs اللي في نتائج البحث المرفقة. "
                        "ممنوع اختراع URLs أو تخمينها."
                    )},
                    {"role": "user", "content": extra_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000,
            )

            data = json.loads(response.choices[0].message.content)
            raw = data.get("candidates", [])

            normalized = []
            for item in raw:
                if isinstance(item, str):
                    normalized.append({"name": item, "country": country_default})
                    continue
                if not isinstance(item, dict):
                    continue
                if "country" not in item or not item.get("country"):
                    item["country"] = country_default
                normalized.append(item)
            raw = normalized

            extras = self._process_candidates(raw, type_label)
            extras = verify_candidates_parallel(extras)
            extras.sort(key=lambda c: (-int(c.passes_mandatory), -int(c.verified), -c.similarity_score))
            
            logger.info(f"  ✅ أضيف {len(extras)} {type_label}")
            return extras
        
        except Exception as e:
            logger.error(f"❌ extra discovery failed: {e}")
            return []
