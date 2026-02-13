import httpx
import json
import subprocess
import re
import asyncio
import time
from typing import Any, Optional
from datetime import datetime
from pathlib import Path
from config.settings import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_OPTIONS, SYSTEM_PROMPT, HOME_DIR, LLM_TYPE, GOOGLE_API_KEY, GROQ_API_KEY, OPENAI_API_KEY
from .intent_parser import IntentParser
from .llm_cache import get_cache
from .intent_classifier import get_classifier
from .llm_optimizer import QueryComplexity, get_llm_optimizer
from .pricing_tracker import get_pricing_tracker, DEFAULT_PRICING_PER_1K
from .i18n import detect_language, normalize_language_code
from utils.logger import get_logger

logger = get_logger("llm")

# CLAUDE.md cache (lazy loading)
_CLAUDE_MD_CONTENT = None
_CLAUDE_MD_PATH = Path(__file__).parent.parent / "CLAUDE.md"


class LLMClient:
    _default_chat_prompt = (
        "Wiqo - akilli, bilgili ve samimi bir Turkce dijital asistan. "
        "Kullaniciyla dogal ve sicak bir sekilde sohbet et. "
        "Profesyonel ama samimi bir ton kullan - ne robotik ne de asiri rahat. "
        "Kisa ve oze yanit ver (2-4 cumle). "
        "Sadece Turkce konus. Emoji kullanma. Teknik jargonu minimumda tut. "
        "JSON formatinda yanit VERME, sadece duz metin yaz. "
        "Bilmedigini kabul et, uydurma."
    )

    def __init__(self):
        default_models = {
            "groq": "llama-3.3-70b-versatile",
            "gemini": "gemini-2.0-flash",
            "openai": "gpt-4o",
            "ollama": OLLAMA_MODEL
        }

        # Load settings from settings.json (authoritative source)
        try:
            from config.settings_manager import SettingsPanel
            settings = SettingsPanel()
            self.llm_type = self._normalize_provider(settings.get("llm_provider", LLM_TYPE) or LLM_TYPE)

            # Map provider to correct API key
            api_key = settings.get("api_key", "").strip()
            
            self.api_key = ""
            self.groq_api_key = ""
            self.openai_api_key = ""

            if self.llm_type == "groq":
                self.groq_api_key = api_key or GROQ_API_KEY
            elif self.llm_type == "gemini":
                self.api_key = api_key or GOOGLE_API_KEY
            elif self.llm_type == "openai":
                self.openai_api_key = api_key or OPENAI_API_KEY
            
            self.model = settings.get("llm_model", "") or default_models.get(self.llm_type, OLLAMA_MODEL)
            self.fallback_mode = str(settings.get("llm_fallback_mode", "aggressive")).lower()
            if self.fallback_mode not in {"aggressive", "conservative"}:
                self.fallback_mode = "aggressive"
            self.fallback_order = self._normalize_fallback_order(settings.get("llm_fallback_order", []))
            self.sticky_selection = bool(settings.get("llm_sticky_selection", True))
            self.assistant_style = settings.get("assistant_style", "professional_friendly_short")
            self.communication_tone = settings.get("communication_tone", "professional_friendly")
            self.response_length = settings.get("response_length", "short")
            self.llm_temperature = float(settings.get("llm_temperature", 0.7))
            self.llm_max_tokens = int(settings.get("llm_max_tokens", 2048))
            self.preferred_language = normalize_language_code(settings.get("preferred_language", "auto"))
            self.enabled_languages = settings.get("enabled_languages", ["tr", "en"])
            self.assistant_expertise = settings.get("assistant_expertise", "advanced")
            custom_rates = settings.get("pricing_rates_per_1k", {})
            self.pricing_rates = DEFAULT_PRICING_PER_1K.copy()
            if isinstance(custom_rates, dict):
                for provider, rates in custom_rates.items():
                    if isinstance(rates, dict):
                        self.pricing_rates[str(provider).lower()] = {
                            "input": float(rates.get("input", self.pricing_rates.get(str(provider).lower(), {}).get("input", 0.0))),
                            "output": float(rates.get("output", self.pricing_rates.get(str(provider).lower(), {}).get("output", 0.0))),
                        }
            
            # Fallbacks for other keys
            if not self.groq_api_key: self.groq_api_key = GROQ_API_KEY
            if not self.api_key: self.api_key = GOOGLE_API_KEY
            if not self.openai_api_key: self.openai_api_key = OPENAI_API_KEY
            
        except Exception:
            # Fallback to env vars
            self.llm_type = self._normalize_provider(LLM_TYPE)
            self.groq_api_key = GROQ_API_KEY
            self.api_key = GOOGLE_API_KEY
            self.openai_api_key = OPENAI_API_KEY
            self.model = OLLAMA_MODEL
            self.fallback_mode = "aggressive"
            self.fallback_order = ["groq", "gemini", "openai", "ollama"]
            self.sticky_selection = True
            self.assistant_style = "professional_friendly_short"
            self.communication_tone = "professional_friendly"
            self.response_length = "short"
            self.llm_temperature = 0.7
            self.llm_max_tokens = 2048
            self.preferred_language = "auto"
            self.enabled_languages = ["tr", "en"]
            self.assistant_expertise = "advanced"
            self.pricing_rates = DEFAULT_PRICING_PER_1K.copy()

        self.host = OLLAMA_HOST
        self.options = OLLAMA_OPTIONS
        self._client = None
        self.intent_parser = IntentParser()
        self.cache = get_cache()
        self.classifier = get_classifier()
        self.llm_optimizer = get_llm_optimizer()
        self.pricing_tracker = get_pricing_tracker()
        self.cost_guard = settings.get("cost_guard", True) if 'settings' in locals() else True
        self.monthly_budget_usd = float(settings.get("monthly_budget_usd", 20.0)) if 'settings' in locals() else 20.0
        self.budget_alert_threshold_pct = int(settings.get("budget_alert_threshold_pct", 80)) if 'settings' in locals() else 80
        self.pricing_alerts_enabled = bool(settings.get("pricing_alerts_enabled", True)) if 'settings' in locals() else True
        self._budget_alert_state = {"warned_80": False, "warned_100": False}

        # Load CLAUDE.md on first use (lazy loading)
        self._claude_md_optimized = None
        self._last_router_trace: list[dict[str, str]] = []
        if self.assistant_style == "professional_friendly_short":
            tone_map = {
                "professional_friendly": "profesyonel ve samimi",
                "mentor": "rehberlik eden ve destekleyici",
                "formal": "resmi ve kurumsal",
            }
            length_map = {
                "short": "2-4 cumle",
                "medium": "4-6 cumle",
                "detailed": "6-9 cumle",
            }
            expertise_map = {
                "basic": "Teknik detaylari minimumda tut.",
                "advanced": "Gerekirse teknik detayi kisa ve acik ver.",
                "expert": "Teknik dogrulugu yuksek tut ama anlasilir kal.",
            }
            self._default_chat_prompt = (
                f"Wiqo, {tone_map.get(self.communication_tone, 'profesyonel ve samimi')} bir Turkce asistan. "
                f"Yaniti {length_map.get(self.response_length, '2-4 cumle')} ile ver. "
                f"{expertise_map.get(self.assistant_expertise, 'Gerekirse teknik detayi kisa ve acik ver.')} "
                "Gereksiz teknik detay ve jargon kullanma. "
                "Sadece Turkce konus. Emoji kullanma. Uydurma bilgi verme."
            )

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        p = str(provider or "").strip().lower()
        if p == "api":
            return "gemini"
        if p in {"groq", "gemini", "openai", "ollama"}:
            return p
        return "ollama"

    def _normalize_fallback_order(self, fallback_order: Any) -> list[str]:
        if not isinstance(fallback_order, list):
            fallback_order = []
        normalized: list[str] = []
        for provider in fallback_order:
            p = self._normalize_provider(provider)
            if p not in normalized:
                normalized.append(p)

        if self.llm_type not in normalized:
            normalized.insert(0, self.llm_type)
        for provider in ["groq", "gemini", "openai", "ollama"]:
            if provider not in normalized:
                normalized.append(provider)
        return normalized

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily initialize client to ensure correct event loop"""
        try:
            # Check if current client exists and loop is running
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(timeout=120.0)
            
            # Additional safety: try to get current loop to verify it's open
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                logger.warning("Detected closed event loop in LLMClient")
                self._client = httpx.AsyncClient(timeout=120.0)
                
        except (RuntimeError, Exception):
            # Happens if there's no loop in the current thread or other async issues
            self._client = httpx.AsyncClient(timeout=120.0)
            
        return self._client

    async def check_model(self) -> bool:
        if self.llm_type != "ollama":
            return True
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
            if self.model in result.stdout:
                logger.info(f"Ollama modeli {self.model} hazır")
                return True

            logger.info(f"Ollama modeli {self.model} indiriliyor...")
            subprocess.run(["ollama", "pull", self.model], timeout=600)
            return True
        except Exception as e:
            logger.error(f"Ollama model hatası: {e}")
            return False

    async def process(self, user_message: str, user_id: Optional[int] = None) -> dict[str, Any]:
        """Ana işleme fonksiyonu - önce cache, sonra intent parser, sonra LLM"""

        # 0. Check cache first (fastest)
        cached = self.cache.get(user_message)
        if cached:
            logger.info(f"Cache hit: {cached.get('action', 'chat')}")
            return cached

        # 1. Quick classification to understand the query
        classification = self.classifier.classify(user_message)
        logger.debug(f"Classification: {classification['category']} (confidence: {classification['confidence']})")

        # 2. Try IntentParser (fast and reliable rule-based)
        intent_result = self.intent_parser.parse(user_message)
        if intent_result:
            logger.info(f"IntentParser ile çözüldü: {intent_result['action']}")
            response = self._convert_intent_to_response(intent_result)
            self.cache.set(user_message, response)
            return response

        # 3. If classification is confident, try quick action
        if classification["confidence"] >= 0.8:
            quick_action = self.classifier.get_quick_action(user_message)
            if quick_action:
                logger.info(f"Quick action: {quick_action}")
                # Build a minimal response for the action
                response = {"action": quick_action, "message": ""}
                return response

        # 4. Fall back to LLM
        logger.info("IntentParser/Classifier çözemedi, LLM'e soruluyor...")
        response = await self._ask_llm(user_message, user_id=user_id)
        
        # 5. Enhanced parameter extraction for Turkish commands
        if response.get("action") not in ["chat", None]:
            try:
                from core.parameter_extractor import extract_parameters
                extracted_params = extract_parameters(user_message, response["action"])
                
                # Merge with existing params (LLM params take precedence)
                if extracted_params:
                    response["params"] = {**extracted_params, **response.get("params", {})}
                    logger.debug(f"Enhanced params: {response['params']}")
            except Exception as e:
                logger.warning(f"Parameter extraction failed: {e}")
        
        # Cache the response
        self.cache.set(user_message, response)

        return response

    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        return self.cache.get_stats()

    def _convert_intent_to_response(self, intent: dict) -> dict[str, Any]:
        """IntentParser sonucunu agent'ın beklediği formata çevir"""
        response = {
            "action": intent["action"],
            "message": intent.get("reply", "")
        }

        params = intent.get("params", {})

        # Copy all parameters directly
        for key, value in params.items():
            if key == "app_name":
                response["app"] = value
            elif key == "message":
                response["content"] = value
            else:
                response[key] = value

        return response

    async def _ask_llm(self, user_message: str, user_id: Optional[int] = None, context: dict = None) -> dict[str, Any]:
        """LLM'e sor ve yanıtı parse et - gelişmiş versiyon"""

        # Build enhanced context (merge with provided context if any)
        base_context = self._build_enhanced_context(user_message)
        if context:
            base_context.update(context)

        # Create intelligent prompt
        prompt = self._create_intelligent_prompt(user_message, base_context, user_id=user_id)

        try:
            temp = self._get_optimal_temperature(user_message)
            max_tokens = self._resolve_dynamic_max_tokens(user_message, is_chat=False)
            text = await self._call_any_provider(
                prompt,
                user_message=user_message,
                temp=temp,
                max_tokens=max_tokens
            )
            if text:
                logger.info(f"LLM response ({self.llm_type}): {text[:200]}")
                return self._parse(text, user_message)

            # All providers failed
            return self._smart_fallback(user_message)

        except Exception as e:
            logger.error(f"LLM hatası: {e}")
            return self._smart_fallback(user_message)

    # ──────────────────────────────────────
    # Provider-specific LLM call helpers
    # ──────────────────────────────────────

    def _split_prompt(self, prompt: str, user_message: str = "") -> tuple[str, str]:
        """Split combined prompt into system and user parts for chat APIs"""
        # Try to split at "User:" marker
        if "\n\nUser:" in prompt:
            parts = prompt.split("\n\nUser:", 1)
            system_part = parts[0].strip()
            user_part = user_message or parts[1].replace("\nAssistant:", "").strip()
            return system_part, user_part
        if "\n\nKullanıcı:" in prompt:
            parts = prompt.split("\n\nKullanıcı:", 1)
            system_part = parts[0].strip()
            user_part = user_message or parts[1].replace("\nWiqo:", "").strip()
            return system_part, user_part
        # No split marker - use full prompt as system, user_message as user
        if user_message:
            return prompt, user_message
        return prompt, ""

    async def _call_groq(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        user_message: str,
        temp: float,
        max_tokens: int | None = None
    ) -> str | None:
        """Call Groq API (OpenAI-compatible chat completions)"""
        system_part, user_part = self._split_prompt(prompt, user_message)
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        token_cap = 700
        temp_cap = 0.6
        if getattr(self, "cost_guard", True):
            token_cap = 280
            temp_cap = 0.35

        selected_model = str(self.model or "").strip() or "llama-3.3-70b-versatile"
        data = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": system_part},
                {"role": "user", "content": user_part}
            ],
            "temperature": min(temp, temp_cap),
            "max_tokens": min(max_tokens or token_cap, token_cap),
            "stream": False
        }
        response = await client.post(url, json=data, headers=headers, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"].strip()
        usage = body.get("usage", {})
        self._record_usage(
            provider="groq",
            model=data["model"],
            prompt_tokens=int(usage.get("prompt_tokens", self._estimate_tokens(system_part + user_part))),
            completion_tokens=int(usage.get("completion_tokens", self._estimate_tokens(text))),
        )
        logger.info(f"Groq response ({len(text)} chars)")
        return text

    async def _call_openai(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        user_message: str,
        temp: float,
        max_tokens: int | None = None
    ) -> str | None:
        """Call OpenAI API"""
        system_part, user_part = self._split_prompt(prompt, user_message)
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json"
        }
        # Cost-aware caps
        model = str(self.model or "").strip() or "gpt-4o-mini"
        max_tokens_cap = 700
        temp_cap = 0.7
        if getattr(self, "cost_guard", True):
            max_tokens_cap = 280
            temp_cap = 0.35

        requested_tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else max_tokens_cap
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_part},
                {"role": "user", "content": user_part}
            ],
            "temperature": min(temp, temp_cap),
            "max_tokens": min(requested_tokens, max_tokens_cap),
            "stream": False
        }
        response = await client.post(url, json=data, headers=headers, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"].strip()
        usage = body.get("usage", {})
        self._record_usage(
            provider="openai",
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens", self._estimate_tokens(system_part + user_part))),
            completion_tokens=int(usage.get("completion_tokens", self._estimate_tokens(text))),
        )
        logger.info(f"OpenAI response ({len(text)} chars)")
        return text

    async def _call_gemini(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        temp: float,
        max_tokens: int | None = None
    ) -> str | None:
        """Call Google Gemini API"""
        model_name = str(self.model or "").strip() or "gemini-2.0-flash"
        max_tokens_cap = 700
        temp_cap = 0.7
        if getattr(self, "cost_guard", True):
            max_tokens_cap = 280
            temp_cap = 0.35

        requested_tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else max_tokens_cap
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": min(temp, temp_cap),
                "maxOutputTokens": min(requested_tokens, max_tokens_cap)
            }
        }
        response = await client.post(url, json=data, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"].strip()
        usage = body.get("usageMetadata", {}) or {}
        prompt_tokens = int(usage.get("promptTokenCount", self._estimate_tokens(prompt)))
        completion_tokens = int(usage.get("candidatesTokenCount", self._estimate_tokens(text)))
        self._record_usage(
            provider="gemini",
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        logger.info(f"Gemini response ({len(text)} chars)")
        return text

    async def _call_ollama(self, client: httpx.AsyncClient, prompt: str, temp: float, max_tokens: int = None) -> str | None:
        """Call local Ollama API"""
        options = {
            **self.options,
            "temperature": temp,
            "top_p": 0.9,
            "top_k": 40
        }
        if max_tokens:
            options["num_predict"] = max_tokens
        response = await client.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": options
            },
            timeout=90.0
        )
        response.raise_for_status()
        body = response.json()
        text = body.get("response", "").strip()
        prompt_tokens = int(body.get("prompt_eval_count", self._estimate_tokens(prompt)))
        completion_tokens = int(body.get("eval_count", self._estimate_tokens(text)))
        self._record_usage(
            provider="ollama",
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        logger.info(f"Ollama response ({len(text)} chars)")
        return text

    def _is_provider_available(self, provider: str) -> bool:
        if provider == "groq":
            return bool(self.groq_api_key)
        if provider == "gemini":
            return bool(self.api_key)
        if provider == "openai":
            return bool(self.openai_api_key)
        if provider == "ollama":
            return True
        return False

    def _provider_attempt_order(self) -> list[str]:
        if getattr(self, "sticky_selection", True):
            return [self.llm_type]
        if self.fallback_mode == "conservative":
            return [self.llm_type]
        order: list[str] = []
        for provider in self.fallback_order:
            p = self._normalize_provider(provider)
            if p not in order:
                order.append(p)
        if self.llm_type not in order:
            order.insert(0, self.llm_type)
        return order

    def _router_log(self, provider: str, status: str, reason: str, elapsed_ms: int = 0):
        event = {
            "provider": provider,
            "status": status,
            "reason": reason,
            "elapsed_ms": str(elapsed_ms),
        }
        self._last_router_trace.append(event)
        if len(self._last_router_trace) > 20:
            self._last_router_trace = self._last_router_trace[-20:]
        logger.info(f"LLM_ROUTER provider={provider} status={status} reason={reason} elapsed_ms={elapsed_ms}")

    def get_last_router_trace(self) -> list[dict[str, str]]:
        return list(self._last_router_trace)

    async def _call_provider(self, provider: str, prompt: str, user_message: str, temp: float, max_tokens: int = None) -> str | None:
        client = self.client
        if provider == "groq":
            return await self._call_groq(client, prompt, user_message, temp, max_tokens=max_tokens)
        if provider == "gemini":
            return await self._call_gemini(client, prompt, temp, max_tokens=max_tokens)
        if provider == "openai":
            return await self._call_openai(client, prompt, user_message, temp, max_tokens=max_tokens)
        if provider == "ollama":
            return await self._call_ollama(client, prompt, temp, max_tokens)
        return None

    async def _call_any_provider(self, prompt: str, user_message: str = "", temp: float = 0.3, max_tokens: int = None) -> str:
        """Try providers in deterministic order and log fallback reasons."""
        self._last_router_trace = []
        for provider in self._provider_attempt_order():
            if not self._is_provider_available(provider):
                self._router_log(provider, "skipped", "missing_credentials")
                continue
            start = time.time()
            try:
                text = await self._call_provider(provider, prompt, user_message, temp, max_tokens)
                elapsed_ms = int((time.time() - start) * 1000)
                if text and text.strip():
                    self._router_log(provider, "success", "ok", elapsed_ms=elapsed_ms)
                    return text
                self._router_log(provider, "failed", "empty_response", elapsed_ms=elapsed_ms)
            except httpx.TimeoutException:
                elapsed_ms = int((time.time() - start) * 1000)
                self._router_log(provider, "failed", "timeout", elapsed_ms=elapsed_ms)
            except httpx.HTTPStatusError as e:
                elapsed_ms = int((time.time() - start) * 1000)
                status = e.response.status_code if e.response else 0
                if status in (401, 403):
                    reason = "auth"
                elif status == 429:
                    reason = "rate_limit"
                elif status >= 500:
                    reason = "server"
                else:
                    reason = f"http_{status}"
                self._router_log(provider, "failed", reason, elapsed_ms=elapsed_ms)
            except Exception as e:
                elapsed_ms = int((time.time() - start) * 1000)
                self._router_log(provider, "failed", f"error:{type(e).__name__}", elapsed_ms=elapsed_ms)

        return ""

    async def summarize_context(self, history: list) -> str:
        """Summarize long conversation history for sliding window memory"""
        if not history:
            return ""
        
        history_text = "\n".join([
            f"User: {h.get('user_message', '')}\nBot: {h.get('bot_response', '')}"
            for h in history
        ])
        
        prompt = f"""Aşağıdaki konuşma geçmişini 2-3 cümle ile özetle. 
Önemli kararları, kullanıcı tercihlerini ve devam eden görevleri mutlaka belirt.

KONUŞMA:
{history_text}

ÖZET:"""
        
        try:
            summary = await self._ask_llm_with_custom_prompt(prompt, temperature=0.1)
            return summary.strip()
        except Exception as e:
            logger.error(f"Context summarization error: {e}")
            return "Konuşma özeti çıkarılamadı."

    def _parse(self, text: str, user_message: str) -> dict[str, Any]:
        """LLM yanıtını parse et"""
        # Markdown code block temizle
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'^```\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        # JSON bul ve parse et
        try:
            if text.startswith('{'):
                return self._normalize(json.loads(text))
        except:
            pass

        # JSON pattern ara
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return self._normalize(json.loads(match.group()))
            except:
                pass

        # Nested JSON için
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end > start:
            try:
                json_str = text[start:end+1]
                return self._normalize(json.loads(json_str))
            except:
                pass

        # Parse başarısız - akıllı fallback
        logger.warning(f"JSON parse başarısız: {text[:100]}")
        return self._smart_fallback(user_message, text)

    def _normalize(self, obj: dict) -> dict[str, Any]:
        """LLM yanıtını normalize et"""
        action = obj.get("action", "chat")
        message = obj.get("message", "")

        # Action mapping - tüm alternatif isimler
        action_map = {
            # File operations
            "list_files": "list_files",
            "list_dir": "list_files",
            "write_file": "write_file",
            "create_file": "write_file",
            "read_file": "read_file",
            "delete_file": "delete_file",
            "remove_file": "delete_file",
            "search_files": "search_files",
            "find_files": "search_files",
            # App control
            "open_app": "open_app",
            "open_application": "open_app",
            "close_app": "close_app",
            "quit_app": "close_app",
            "kill_process": "kill_process",
            "get_process_info": "get_process_info",
            # System
            "open_url": "open_url",
            "open_website": "open_url",
            "system_info": "get_system_info",
            "get_system_info": "get_system_info",
            "shutdown_system": "shutdown_system",
            "restart_system": "restart_system",
            "sleep_system": "sleep_system",
            "lock_screen": "lock_screen",
            "take_screenshot": "take_screenshot",
            "screenshot": "take_screenshot",
            "read_clipboard": "read_clipboard",
            "clipboard_read": "read_clipboard",
            "write_clipboard": "write_clipboard",
            "clipboard_write": "write_clipboard",
            "set_volume": "set_volume",
            "volume": "set_volume",
            "send_notification": "send_notification",
            "notification": "send_notification",
            "notify": "send_notification",
            # macOS
            "toggle_dark_mode": "toggle_dark_mode",
            "dark_mode": "toggle_dark_mode",
            "wifi_status": "wifi_status",
            "wifi_toggle": "wifi_toggle",
            "get_today_events": "get_today_events",
            "create_event": "create_event",
            "get_reminders": "get_reminders",
            "create_reminder": "create_reminder",
            "spotlight_search": "spotlight_search",
            # Office
            "read_word": "read_word",
            "write_word": "write_word",
            "read_excel": "read_excel",
            "write_excel": "write_excel",
            "read_pdf": "read_pdf",
            "get_pdf_info": "get_pdf_info",
            "summarize_document": "summarize_document",
            "summarize": "summarize_document",
            # General
            "multi_task": "multi_task",
            "chat": "chat"
        }

        action = action_map.get(action, action)

        result = {"action": action, "message": message}

        # Parametreleri normalize et
        if "path" in obj:
            result["path"] = self._resolve_path(obj["path"])
        if "content" in obj:
            result["content"] = obj["content"].replace("\\n", "\n")
        if "app" in obj:
            result["app"] = obj["app"]
        if "app_name" in obj:
            result["app"] = obj["app_name"]
        if "url" in obj:
            url = obj["url"]
            if not url.startswith("http"):
                url = "https://" + url
            result["url"] = url
        if "pattern" in obj:
            result["pattern"] = obj["pattern"]
        if "dir" in obj:
            result["directory"] = self._resolve_path(obj["dir"])
        if "directory" in obj:
            result["directory"] = self._resolve_path(obj["directory"])
        if "tasks" in obj:
            result["tasks"] = [self._normalize(t) for t in obj["tasks"]]

        # Yeni parametreler
        if "filename" in obj:
            result["filename"] = obj["filename"]
        if "text" in obj:
            result["text"] = obj["text"]
        if "level" in obj:
            result["level"] = obj["level"]
        if "mute" in obj:
            result["mute"] = obj["mute"]
        if "title" in obj:
            result["title"] = obj["title"]

        # macOS parameters
        if "enable" in obj:
            result["enable"] = obj["enable"]
        if "start_time" in obj:
            result["start_time"] = obj["start_time"]
        if "end_time" in obj:
            result["end_time"] = obj["end_time"]
        if "date" in obj:
            result["date"] = obj["date"]
        if "due_date" in obj:
            result["due_date"] = obj["due_date"]
        if "due_time" in obj:
            result["due_time"] = obj["due_time"]
        if "query" in obj:
            result["query"] = obj["query"]
        if "file_type" in obj:
            result["file_type"] = obj["file_type"]
        if "reminder" in obj:
            result["title"] = obj["reminder"]
        if "event" in obj:
            result["title"] = obj["event"]

        # Office parameters
        if "pages" in obj:
            result["pages"] = obj["pages"]
        if "style" in obj:
            result["style"] = obj["style"]
        if "sheet" in obj:
            result["sheet"] = obj["sheet"]
        if "data" in obj:
            result["data"] = obj["data"]
        if "headers" in obj:
            result["headers"] = obj["headers"]

        return result

    def _resolve_path(self, path: str) -> str:
        """Yol kısayollarını çöz"""
        if not path:
            return str(HOME_DIR / "Desktop")
        return path.replace("~/", str(HOME_DIR) + "/").replace("$HOME", str(HOME_DIR))

    def _smart_fallback(self, user_message: str, llm_text: str = "") -> dict[str, Any]:
        """Akıllı fallback - son çare olarak kural tabanlı anlama"""
        user_lower = user_message.lower()

        # Selamlaşma
        greetings = ["merhaba", "selam", "hey", "hi", "hello", "sa", "mrb"]
        if any(g in user_lower for g in greetings):
            return {
                "action": "chat",
                "message": "Merhaba! Ben bilgisayar asistanınım. Dosya yönetimi, uygulama kontrolü, ekran görüntüsü, ses ayarları ve daha fazlasında yardımcı olabilirim. Ne yapmamı istersin?"
            }

        # Screenshot
        if any(w in user_lower for w in ["ekran görüntüsü", "screenshot", "ekran resmi", "ss al"]):
            return {"action": "take_screenshot", "message": "Ekran görüntüsü alınıyor..."}

        # Ses kontrolü
        if any(w in user_lower for w in ["sesi kapat", "sessize", "mute"]):
            return {"action": "set_volume", "mute": True, "message": "Ses kapatılıyor..."}
        if any(w in user_lower for w in ["sesi aç", "unmute"]):
            return {"action": "set_volume", "mute": False, "message": "Ses açılıyor..."}

        # Clipboard
        if any(w in user_lower for w in ["panoda", "clipboard", "pano"]):
            return {"action": "read_clipboard", "message": "Pano içeriği okunuyor..."}

        # Sistem bilgisi
        if any(w in user_lower for w in ["sistem", "cpu", "ram", "disk", "pil"]):
            return {"action": "get_system_info", "message": "Sistem bilgileri getiriliyor..."}

        # Güç komutları
        if any(w in user_lower for w in ["bilgisayarı kapat", "bilgisayari kapat", "sistemi kapat", "shut down"]):
            return {"action": "shutdown_system", "message": "Sistem kapatılıyor..."}
        if any(w in user_lower for w in ["yeniden başlat", "yeniden baslat", "restart", "reboot"]):
            return {"action": "restart_system", "message": "Sistem yeniden başlatılıyor..."}
        if any(w in user_lower for w in ["uykuya al", "uyku modu", "sleep mode"]):
            return {"action": "sleep_system", "message": "Sistem uyku moduna alınıyor..."}
        if any(w in user_lower for w in ["ekranı kilitle", "ekrani kilitle", "lock screen"]):
            return {"action": "lock_screen", "message": "Ekran kilitleniyor..."}

        # Masaüstü listele
        if any(w in user_lower for w in ["masaüstü", "desktop"]) and any(w in user_lower for w in ["ne var", "göster", "listele"]):
            return {"action": "list_files", "path": str(HOME_DIR / "Desktop"), "message": "Masaüstünü listeliyorum..."}

        # Eğer LLM bir şey yazdıysa onu göster
        if llm_text and len(llm_text) > 5 and not llm_text.startswith("{"):
            # JSON gibi görünmeyen makul bir yanıt
            clean_text = llm_text[:500]
            return {"action": "chat", "message": clean_text}

        return {
            "action": "chat",
            "message": "Anlamadım. Şunları yapabilirim: dosya işlemleri, uygulama açma/kapatma, ekran görüntüsü, ses kontrolü, sistem bilgisi. Ne yapmamı istersin?"
        }

    def _load_claude_md_optimized(self, intent_category: str = None) -> str:
        """
        Load and optimize CLAUDE.md based on intent category.
        Token-optimized: Returns only relevant sections.
        """
        global _CLAUDE_MD_CONTENT

        # Load full CLAUDE.md once (cache)
        if _CLAUDE_MD_CONTENT is None:
            try:
                if _CLAUDE_MD_PATH.exists():
                    _CLAUDE_MD_CONTENT = _CLAUDE_MD_PATH.read_text(encoding='utf-8')
                    logger.info(f"CLAUDE.md loaded: {len(_CLAUDE_MD_CONTENT)} chars")
                else:
                    logger.warning("CLAUDE.md not found, using SYSTEM_PROMPT fallback")
                    _CLAUDE_MD_CONTENT = SYSTEM_PROMPT
            except Exception as e:
                logger.error(f"Failed to load CLAUDE.md: {e}")
                _CLAUDE_MD_CONTENT = SYSTEM_PROMPT

        # If already optimized for this session, reuse
        if self._claude_md_optimized:
            return self._claude_md_optimized

        # Extract critical sections (token-optimized version)
        # Keep: Identity, behavior rules, response format, Turkish rules
        # Skip: Detailed tool list (use intent-based filtering), long examples

        lines = _CLAUDE_MD_CONTENT.split('\n')
        optimized_sections = []

        # Section markers to include
        include_sections = [
            "## 🎯 SEN KİMSİN?",
            "## 📋 YANIT FORMATI",
            "## 🧠 AKILLI KARAR VERME",
            "## 🗣️ TÜRKÇE KONUŞMA KURALLARI",
            "## ⚡ TOKEN TASARRUFU STRATEJİLERİ",
            "## 🚀 ÖZETİN ÖZETİ"
        ]

        in_relevant_section = False
        for line in lines:
            # Check if entering a relevant section
            if any(marker in line for marker in include_sections):
                in_relevant_section = True
                optimized_sections.append(line)
            # Check if leaving section (next ##)
            elif line.startswith("## ") and in_relevant_section:
                in_relevant_section = False
            # Add line if in relevant section
            elif in_relevant_section:
                # Skip long examples (code blocks)
                if line.strip().startswith("```") or "Örnek:" in line:
                    continue
                optimized_sections.append(line)

        optimized = "\n".join(optimized_sections)

        # If too long (>3000 chars), fall back to core sections only
        if len(optimized) > 3000:
            optimized = self._extract_core_prompt()

        self._claude_md_optimized = optimized
        logger.info(f"CLAUDE.md optimized: {len(optimized)} chars (from {len(_CLAUDE_MD_CONTENT)})")
        return optimized

    def _extract_core_prompt(self) -> str:
        """Extract only the core essence of CLAUDE.md for ultra-compact prompts"""
        return """Wiqo - macOS'ta çalışan akıllı Türkçe asistan.

KİMLİK: Samimi, profesyonel, verimli. Emoji kullanma, kısa ve öz ol.

YANIT FORMATI:
- Tool: {"action":"tool_adi", "message":"açıklama", "params":{...}}
- Chat: {"action":"chat", "message":"yanıt"}

KURALLAR:
1. Intent analizi → Doğru tool seçimi → Parametreler
2. Belirsizse sor (chat ile)
3. Token tasarrufu: Intent-based tool filtreleme
4. Bağlam kullan: Önceki mesajları hatırla
5. Türkçe normalizasyon: masaüstü→Desktop

TOOL KATEGORİLERİ:
- COMMAND: Sistem (14) + macOS (13) = 27 tool
- FILE_OP: Dosya (9) + Belge (5) + Office (7) = 21 tool
- RESEARCH: Web (7) + AI (6) + Görsel (3) = 16 tool
- CODING: Kod (4) + Dosya (3) = 7 tool
- CHAT: 0 tool (sadece sohbet)"""

    def _build_enhanced_context(self, user_message: str) -> dict[str, Any]:
        """Build minimal context - only what's needed"""
        detected = self._detect_message_language(user_message)
        preferred = self.preferred_language
        if preferred != "auto":
            detected = preferred
        return {
            "language": detected,
            "intent_hints": self._extract_intent_hints(user_message),
            "preferred_language": preferred,
            "enabled_languages": self.enabled_languages,
        }

    def _create_intelligent_prompt(self, user_message: str, context: dict, user_id: Optional[int] = None) -> str:
        """Create minimal prompt - no token waste"""
        # Determine if we need a full prompt or a lite one
        # Simple queries (chat, simple tool calls) don't need the 2000+ token SYSTEM_PROMPT
        is_simple = self.classifier.is_simple_query(user_message)

        if is_simple:
            logger.info("Using lightweight system prompt for simple query")
            system = (
                "Wiqo, akilli bir Turkce asistan. "
                "JSON formatinda yanit ver: {\"action\": \"...\", \"message\": \"...\", \"params\": {}}. "
                "Chat ise action: chat yap."
            )
        else:
            # Use optimized CLAUDE.md for complex queries
            try:
                intent_category = context.get("intent_category", "general")
                system = self._load_claude_md_optimized(intent_category)
                logger.info(f"Using optimized CLAUDE.md ({len(system)} chars)")
            except Exception as e:
                logger.warning(f"CLAUDE.md load failed, using enhanced prompt: {e}")
                language = context.get("language", "tr")
                intent_hints = context.get("intent_hints", [])
                system = self._enhance_system_prompt(language, intent_hints)

        # Add context if available (conversation history)
        context_str = context.get("formatted_context", "")
        if context_str:
            system += f"\n\n## Bağlam (Son Konuşmalar)\n{context_str}"

        return f"{system}\n\nUser: {user_message}\nAssistant:"

    def _enhance_system_prompt(self, language: str, intent_hints: list) -> str:
        """Enhance system prompt based on language and intent hints"""
        base_prompt = SYSTEM_PROMPT

        # Language-specific enhancements
        language_labels = {
            "tr": "Turkish",
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "fr": "French",
            "it": "Italian",
            "pt": "Portuguese",
            "ar": "Arabic",
            "ru": "Russian",
        }
        target_label = language_labels.get(language, "user language")
        base_prompt += f"\n\nRespond in {target_label}. Keep language consistent unless user explicitly changes it."

        # Intent-based enhancements
        if "research" in intent_hints or "search" in intent_hints:
            base_prompt += "\n\nFor research tasks: Use advanced_research tool for comprehensive analysis."
        elif "summarize" in intent_hints or "summary" in intent_hints:
            base_prompt += "\n\nFor summarization: Use smart_summarize tool for intelligent summaries."
        elif "file" in intent_hints or "create" in intent_hints:
            base_prompt += "\n\nFor file creation: Use create_smart_file tool for optimized file generation."
        elif "analyze" in intent_hints:
            base_prompt += "\n\nFor analysis: Use analyze_document tool for comprehensive document analysis."

        return base_prompt

    def _resolve_dynamic_max_tokens(self, user_message: str, is_chat: bool = False) -> int:
        """
        Compute a tighter max_tokens budget to reduce token waste.
        Uses complexity + response length + cost guard + user setting cap.
        """
        complexity = self.llm_optimizer.classify_complexity(user_message)

        if is_chat:
            base_limits = {
                QueryComplexity.TRIVIAL: 90,
                QueryComplexity.SIMPLE: 130,
                QueryComplexity.MODERATE: 180,
                QueryComplexity.COMPLEX: 240,
                QueryComplexity.ADVANCED: 320,
            }
        else:
            # JSON/action generation typically needs fewer output tokens than full chat.
            base_limits = {
                QueryComplexity.TRIVIAL: 80,
                QueryComplexity.SIMPLE: 110,
                QueryComplexity.MODERATE: 160,
                QueryComplexity.COMPLEX: 220,
                QueryComplexity.ADVANCED: 320,
            }

        length_multiplier = {"short": 1.0, "medium": 1.25, "detailed": 1.5}
        scale = float(length_multiplier.get(str(self.response_length).lower(), 1.0))
        planned_tokens = int(base_limits.get(complexity, 160) * scale)

        if getattr(self, "cost_guard", True):
            hard_cap = 280
        else:
            hard_cap = 700

        try:
            setting_cap = int(self.llm_max_tokens)
            if setting_cap > 0:
                hard_cap = min(hard_cap, setting_cap)
        except Exception:
            pass

        return max(64, min(planned_tokens, hard_cap))

    def _get_optimal_temperature(self, user_message: str) -> float:
        """Get optimal temperature based on message type"""
        user_lower = user_message.lower()
        base_temp = 0.3

        # Chat and greetings need more personality/realism
        if any(word in user_lower for word in ["selam", "merhaba", "hey", "nasılsın", "naber", "günaydın", "iyi akşamlar"]):
            base_temp = 0.7

        # Creative writing tasks
        elif any(word in user_lower for word in ["yarat", "create", "yaz", "write", "tasarla", "design"]):
            base_temp = 0.8

        # Research, Analysis, and Planning need precision and consistency
        elif any(word in user_lower for word in ["araştır", "research", "analiz", "analyze", "özetle", "summarize", "plan", "görev", "liste"]):
            base_temp = 0.05

        # Code generation needs extreme precision
        elif any(word in user_lower for word in ["kod", "code", "program", "script", "hata", "debug"]):
            base_temp = 0.0

        try:
            configured = float(self.llm_temperature)
            if configured >= 0:
                base_temp = min(base_temp, max(0.0, min(configured, 1.0)))
        except Exception:
            pass

        if getattr(self, "cost_guard", True):
            return min(base_temp, 0.35)
        return base_temp

    def _detect_message_language(self, message: str) -> str:
        """Detect message language"""
        return detect_language(message)

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(str(text or "")) // 4)

    def _record_usage(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int):
        try:
            self.pricing_tracker.record_usage(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                rates=self.pricing_rates,
            )
            self._check_budget_alerts()
        except Exception as exc:
            logger.debug(f"Pricing record failed: {exc}")

    def _check_budget_alerts(self):
        if not self.pricing_alerts_enabled:
            return
        budget = max(float(self.monthly_budget_usd), 0.0)
        if budget <= 0:
            return
        spent = float(self.pricing_tracker.summary().get("lifetime", {}).get("estimated_cost_usd", 0.0))
        ratio = (spent / budget) * 100.0
        warn_level = max(10, min(100, int(self.budget_alert_threshold_pct)))

        should_warn_threshold = ratio >= warn_level and not self._budget_alert_state["warned_80"]
        should_warn_budget = ratio >= 100 and not self._budget_alert_state["warned_100"]

        if should_warn_threshold:
            self._budget_alert_state["warned_80"] = True
            self._emit_budget_warning(
                title="Pricing Uyarısı",
                message=f"Aylık bütçenin %{warn_level} eşiğine yaklaşıldı. Harcama: ${spent:.2f} / ${budget:.2f}",
            )
        if should_warn_budget:
            self._budget_alert_state["warned_100"] = True
            self._emit_budget_warning(
                title="Pricing Limit Aşıldı",
                message=f"Aylık bütçe aşıldı. Harcama: ${spent:.2f} / ${budget:.2f}",
            )

    def _emit_budget_warning(self, title: str, message: str):
        logger.warning(f"{title}: {message}")
        try:
            from core.smart_notifications import (
                NotificationCategory,
                NotificationPriority,
                get_smart_notifications,
            )
            loop = asyncio.get_running_loop()
            loop.create_task(
                get_smart_notifications().send_notification(
                    title=title,
                    message=message,
                    priority=NotificationPriority.HIGH,
                    category=NotificationCategory.WARNING,
                    force=True,
                )
            )
        except Exception:
            pass

    def _extract_intent_hints(self, message: str) -> list[str]:
        """Extract intent hints from message"""
        hints = []
        message_lower = message.lower()

        # Research intents
        if any(word in message_lower for word in ["araştır", "research", "ara", "search", "bul", "find", "öğren", "learn"]):
            hints.append("research")

        # Summarization intents
        if any(word in message_lower for word in ["özetle", "summarize", "summary", "kısalt", "shorten"]):
            hints.append("summarize")

        # File creation intents
        if any(word in message_lower for word in ["oluştur", "create", "yaz", "write", "kaydet", "save", "dosya", "file"]):
            hints.append("file")

        # Analysis intents
        if any(word in message_lower for word in ["analiz", "analyze", "incele", "examine", "çözümle", "solution"]):
            hints.append("analyze")

        # Code intents
        if any(word in message_lower for word in ["kod", "code", "program", "script", "fonksiyon", "function"]):
            hints.append("code")

        return hints

    def _get_recent_cache_entries(self) -> list[dict]:
        """Get recent cache entries for context"""
        try:
            # Get last 5 cache entries
            cache_stats = self.cache.get_stats()
            if cache_stats.get("total", 0) > 0:
                # This is a simplified version - in practice you'd want to get actual recent entries
                return [{"user": "recent_query", "action": "chat"}]
        except:
            pass
        return []

    def _get_basic_system_context(self) -> dict:
        """Get basic system context"""
        return {
            "platform": "macOS",
            "has_ui": True,
            "llm_model": self.model,
            "tools_available": 90  # Total tools count
        }

    async def _ask_llm_with_custom_prompt(self, prompt: str, temperature: Optional[float] = None) -> str:
        """Ask LLM with a custom prompt (used by reasoning module) - provider-aware"""
        try:
            temp = temperature or 0.3
            return await self._call_any_provider(prompt, temp=temp, max_tokens=self._resolve_dynamic_max_tokens(prompt, is_chat=False))
        except Exception as e:
            logger.error(f"Custom prompt LLM error: {e}")
            return ""

    async def generate(self, prompt: str, max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        """Generate text from prompt - provider-aware"""
        try:
            temp = temperature or 0.1
            if getattr(self, "cost_guard", True):
                temp = min(temp, 0.35)
            default_tokens = self._resolve_dynamic_max_tokens(prompt, is_chat=False)
            resolved_max_tokens = min(max_tokens, default_tokens) if isinstance(max_tokens, int) and max_tokens > 0 else default_tokens
            return await self._call_any_provider(prompt, temp=temp, max_tokens=resolved_max_tokens)
        except Exception as e:
            logger.error(f"Generate error: {e}", exc_info=True)
            return ""

    async def chat(self, user_message: str, system_prompt: str = None) -> str:
        """
        Direct chat - no JSON parsing, returns plain text.
        Used for normal conversations, questions, greetings.
        Much faster than process() since it skips tool resolution.
        Routes to user's selected provider first, then fallback chain.
        """
        if not system_prompt:
            system_prompt = self._default_chat_prompt

        prompt = f"{system_prompt}\n\nKullanıcı: {user_message}\nWiqo:"

        try:
            chat_max_tokens = self._resolve_dynamic_max_tokens(user_message, is_chat=True)
            text = await self._call_any_provider(
                prompt=prompt,
                user_message=user_message,
                temp=self._get_optimal_temperature(user_message),
                max_tokens=chat_max_tokens
            )
            if not text:
                return "Bir sorun olustu, tekrar deneyin."
            return text.strip()
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return "Bir sorun olustu, tekrar deneyin."

    async def close(self):
        await self.client.aclose()
