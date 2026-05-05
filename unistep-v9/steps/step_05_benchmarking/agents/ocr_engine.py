"""
═══════════════════════════════════════════════════════════════════
OCR Engine — معالجة التقارير السنوية العربية المصورة
═══════════════════════════════════════════════════════════════════

المشكلة: كثير من التقارير السنوية للجمعيات السعودية بتيجي كـ PDF
مصور (scanned)، يعني pypdf مش هيقدر يستخرج منها نص.

الحل: 3 طبقات بالترتيب:
1. pypdf — للـ PDFs النصية (الأسرع)
2. Tesseract OCR — للـ PDFs المصورة (مع دعم العربي 'ara')
3. GPT-4o Vision — fallback للحالات الصعبة (استخراج جداول، تنسيقات معقدة)

الكود مصمم بحيث لو Tesseract مش متثبّت، يتخطّى للـ Vision.
"""
import logging
import os
import io
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# التحقق من وجود الأدوات
# ═══════════════════════════════════════════════════════════════════
def _has_tesseract() -> bool:
    """هل Tesseract متثبّت في النظام؟"""
    try:
        import pytesseract
        # محاولة بسيطة للتحقق
        pytesseract.get_tesseract_version()
        return True
    except (ImportError, Exception):
        return False


def _has_pdf2image() -> bool:
    """هل pdf2image متاح؟ (يحتاج poppler-utils)"""
    try:
        from pdf2image import convert_from_path
        return True
    except ImportError:
        return False


HAS_TESSERACT = _has_tesseract()
HAS_PDF2IMAGE = _has_pdf2image()


@dataclass
class OCRResult:
    """نتيجة استخراج النص من PDF"""
    text: str
    method: str  # "pypdf" | "tesseract" | "vision" | "failed"
    pages_processed: int
    pages_total: int
    confidence: str  # "high" | "medium" | "low"
    error: Optional[str] = None
    
    @property
    def is_successful(self) -> bool:
        return bool(self.text and self.text.strip())


class OCREngine:
    """
    محرك OCR متعدد الطبقات للتقارير العربية.
    
    Usage:
        engine = OCREngine(openai_client=client)
        result = engine.extract_text("/path/to/report.pdf")
        if result.is_successful:
            print(result.text)
    """
    
    def __init__(self, openai_client=None, vision_model: str = "gpt-4o"):
        self.openai_client = openai_client
        self.vision_model = vision_model
        
        # log الإمكانيات المتاحة
        if not HAS_TESSERACT:
            logger.warning("⚠️ Tesseract not installed — falling back to GPT-4o Vision only")
        if not HAS_PDF2IMAGE:
            logger.warning("⚠️ pdf2image not installed — image-based extraction unavailable")
    
    # ═══════════════════════════════════════════════════
    # Layer 1: pypdf (للنصوص العادية)
    # ═══════════════════════════════════════════════════
    def _extract_with_pypdf(self, pdf_path: str) -> OCRResult:
        """استخراج النص من PDF نصي باستخدام pypdf"""
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            pages_text = []
            for page in reader.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
            full_text = "\n\n".join(pages_text).strip()
            
            # لو النص فاضي أو قليل جداً، الـ PDF مصور
            if len(full_text) < 100:
                return OCRResult(
                    text="",
                    method="pypdf",
                    pages_processed=0,
                    pages_total=len(reader.pages),
                    confidence="low",
                    error="PDF appears to be image-based (no text extracted)",
                )
            
            return OCRResult(
                text=full_text,
                method="pypdf",
                pages_processed=len(reader.pages),
                pages_total=len(reader.pages),
                confidence="high",
            )
        except Exception as e:
            logger.warning(f"pypdf failed: {e}")
            return OCRResult(
                text="", method="pypdf", pages_processed=0, pages_total=0,
                confidence="low", error=str(e),
            )
    
    # ═══════════════════════════════════════════════════
    # Layer 2: Tesseract (للنصوص العربية المصورة)
    # ═══════════════════════════════════════════════════
    def _extract_with_tesseract(self, pdf_path: str, max_pages: int = 50) -> OCRResult:
        """استخراج النص باستخدام Tesseract OCR (دعم عربي)"""
        if not HAS_TESSERACT or not HAS_PDF2IMAGE:
            return OCRResult(
                text="", method="tesseract", pages_processed=0, pages_total=0,
                confidence="low", error="Tesseract or pdf2image not available",
            )
        
        try:
            from pdf2image import convert_from_path
            import pytesseract
            
            # تحويل PDF لصور
            images = convert_from_path(pdf_path, dpi=200, last_page=max_pages)
            
            pages_text = []
            for i, img in enumerate(images):
                # نستخدم 'ara+eng' (عربي + إنجليزي معاً)
                text = pytesseract.image_to_string(img, lang="ara+eng")
                pages_text.append(text)
            
            full_text = "\n\n".join(pages_text).strip()
            
            if not full_text:
                return OCRResult(
                    text="", method="tesseract", pages_processed=len(images),
                    pages_total=len(images), confidence="low",
                    error="Tesseract found no text",
                )
            
            return OCRResult(
                text=full_text,
                method="tesseract",
                pages_processed=len(images),
                pages_total=len(images),
                confidence="medium",  # Tesseract العربي مش 100% دقيق
            )
        except Exception as e:
            logger.warning(f"Tesseract failed: {e}")
            return OCRResult(
                text="", method="tesseract", pages_processed=0, pages_total=0,
                confidence="low", error=str(e),
            )
    
    # ═══════════════════════════════════════════════════
    # Layer 3: GPT-4o Vision (لحالات الصعبة جداً)
    # ═══════════════════════════════════════════════════
    def _extract_with_vision(self, pdf_path: str, max_pages: int = 10) -> OCRResult:
        """استخراج النص باستخدام GPT-4o Vision (مكلف، نستخدمه عند الضرورة)"""
        if not self.openai_client or not HAS_PDF2IMAGE:
            return OCRResult(
                text="", method="vision", pages_processed=0, pages_total=0,
                confidence="low", error="OpenAI client or pdf2image not available",
            )
        
        try:
            from pdf2image import convert_from_path
            import base64
            
            # تحويل PDF لصور (max 10 pages عشان التكلفة)
            images = convert_from_path(pdf_path, dpi=150, last_page=max_pages)
            
            pages_text = []
            for i, img in enumerate(images):
                # تحويل الصورة لـ base64
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode()
                
                # استدعاء Vision
                response = self.openai_client.chat.completions.create(
                    model=self.vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "استخرج النص العربي والإنجليزي الكامل من هذه الصفحة. حافظ على التنسيق والجداول. لا تترجم. لا تلخّص.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=4000,
                )
                page_text = response.choices[0].message.content or ""
                pages_text.append(page_text)
                logger.info(f"  Vision page {i+1}/{len(images)} extracted")
            
            full_text = "\n\n".join(pages_text).strip()
            
            return OCRResult(
                text=full_text,
                method="vision",
                pages_processed=len(images),
                pages_total=len(images),
                confidence="high",  # Vision عادة أدق من Tesseract للعربي
            )
        except Exception as e:
            logger.exception(f"Vision OCR failed: {e}")
            return OCRResult(
                text="", method="vision", pages_processed=0, pages_total=0,
                confidence="low", error=str(e),
            )
    
    # ═══════════════════════════════════════════════════
    # Public API: استخراج بترتيب الطبقات
    # ═══════════════════════════════════════════════════
    def extract_text(
        self,
        pdf_path: str,
        prefer_vision: bool = False,
    ) -> OCRResult:
        """
        استخراج النص من PDF بأفضل طريقة متاحة.
        
        Args:
            pdf_path: المسار للـ PDF
            prefer_vision: لو True، يستخدم Vision مباشرة (للجداول المعقدة)
        
        Returns:
            OCRResult — مع .text و .method و .confidence
        """
        if not Path(pdf_path).exists():
            return OCRResult(
                text="", method="failed", pages_processed=0, pages_total=0,
                confidence="low", error=f"File not found: {pdf_path}",
            )
        
        logger.info(f"📄 OCR processing: {pdf_path}")
        
        # لو طلب Vision مباشرة
        if prefer_vision and self.openai_client:
            return self._extract_with_vision(pdf_path)
        
        # Layer 1: pypdf
        result = self._extract_with_pypdf(pdf_path)
        if result.is_successful:
            logger.info(f"✅ pypdf extracted {len(result.text)} chars")
            return result
        
        # Layer 2: Tesseract
        if HAS_TESSERACT and HAS_PDF2IMAGE:
            logger.info("📷 Falling back to Tesseract...")
            result = self._extract_with_tesseract(pdf_path)
            if result.is_successful:
                logger.info(f"✅ Tesseract extracted {len(result.text)} chars")
                return result
        
        # Layer 3: Vision
        if self.openai_client:
            logger.info("🔭 Falling back to GPT-4o Vision...")
            result = self._extract_with_vision(pdf_path)
            if result.is_successful:
                logger.info(f"✅ Vision extracted {len(result.text)} chars")
                return result
        
        # كل الطبقات فشلت
        return OCRResult(
            text="", method="failed", pages_processed=0, pages_total=0,
            confidence="low", error="All extraction methods failed",
        )
