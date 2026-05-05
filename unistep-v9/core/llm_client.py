"""
═══════════════════════════════════════════════════════════════════
UNISTEP v9 — LLM Client Wrapper
═══════════════════════════════════════════════════════════════════

Wrapper حول OpenAI API:
- يوحّد الـ API calls
- يتتبع التكلفة
- يدعم JSON mode

Pricing (مايو 2026):
- gpt-4o-mini:  $0.15 / $0.60  per 1M tokens (أرخص — للاستخراج البسيط)
- gpt-4o:       $2.50 / $10.00 per 1M tokens (للتحليل المتوسط)
- gpt-4.1:      $2.00 / $8.00  per 1M tokens (long-context)
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Pricing (per 1M tokens) — مايو 2026
# ═══════════════════════════════════════════════════════════════════
PRICING = {
    "gpt-4o":      {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1":     {"input": 2.00, "output": 8.00},
}


@dataclass
class CostRecord:
    """سجل تكلفة استدعاء API واحد"""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class LLMClient:
    """
    Wrapper حول OpenAI client.
    
    Usage:
        client = LLMClient(openai_client)
        response, cost = client.chat(
            model="gpt-4o",
            messages=[{"role": "user", "content": "..."}],
            json_mode=True,
        )
    """
    
    def __init__(self, openai_client):
        self.client = openai_client
        self.history: list[CostRecord] = []
    
    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.history)
    
    def chat(
        self,
        model: str,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 4000,
        **kwargs,
    ) -> tuple[str, CostRecord]:
        """
        استدعاء واحد للـ chat completions API.
        
        Returns:
            (text_response, cost_record)
        """
        params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        
        response = self.client.chat.completions.create(**params)
        
        text = response.choices[0].message.content or ""
        
        # احسب التكلفة
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        
        pricing = PRICING.get(model, {"input": 1.0, "output": 4.0})
        cost = (
            input_tokens / 1_000_000 * pricing["input"]
            + output_tokens / 1_000_000 * pricing["output"]
        )
        
        record = CostRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.history.append(record)
        
        return text, record
    
    def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ) -> tuple[dict, CostRecord]:
        """
        استدعاء JSON mode مع system + user prompts.
        
        Returns:
            (parsed_dict, cost_record)
        """
        text, record = self.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}\nText: {text[:500]}")
            data = {}
        return data, record
