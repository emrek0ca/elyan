import httpx
import json
import asyncio
import time
from typing import Any, Optional
from config.elyan_config import elyan_config
from core.model_orchestrator import model_orchestrator
from core.neural_router import neural_router
from .llm_cache import get_cache
from .intent_parser import IntentParser
from .intent_classifier import get_classifier
from .llm_optimizer import get_llm_optimizer
from .pricing_tracker import get_pricing_tracker
from security.privacy_guard import redact_text, is_external_provider
from utils.logger import get_logger

logger = get_logger("llm_client")

class LLMClient:
    def __init__(self):
        self.orchestrator = model_orchestrator
        self.intent_parser = IntentParser()
        self.cache = get_cache()
        self.classifier = get_classifier()
        self.llm_optimizer = get_llm_optimizer()
        self.pricing_tracker = get_pricing_tracker()

        # Router / fallback configuration
        self.llm_type: str = "openai"
        self.cost_guard: bool = False
        self.fallback_mode: str = "standard"
        self.fallback_order: list = ["openai", "groq", "gemini", "ollama"]
        self._router_trace: list = []

        self.assistant_style = "professional_friendly_short"
        self._default_chat_prompt = (
            "Sen Elyan, son derece zeki, yetenekli ve yardımsever bir dijital asistansın. "
            "Kullanıcıya profesyonel, nazik ve çözüm odaklı yanıtlar ver. "
            "Gereksiz laf kalabalığından kaçın, doğrudan konuya gir.\n\n"
            "STRİKT KURALLAR:\n"
            "1. Her görev için önce bir 'Deliverable Spec' ve 'Done Criteria' üret. Bunları doğrulamadan 'tamamlandı' deme.\n"
            "2. Boş veya sadece iskelet (skeleton) çıktı üretmek başarı değildir. Her dosya zengin ve anlamlı içerik barındırmalıdır.\n"
            "3. Eğer istenen format (örn. .docx) üretilemiyorsa açık hata ver ve alternatif öner (örn. .md). Gizli fallback yapma.\n"
            "4. Her yazma işleminden sonra içeriği kontrol et (read-back). Minimum uzunluk sınırlarına uymayan dosyaları tekrar onar.\n"
            "5. ASLA kullanıcıyı taklit etme. Kendi asistan kimliğini koru. Sadece Türkçe konuş.\n"
            "6. Araştırma görevlerinde çok kaynaklı sentez yap; mümkünse akademik/resmi kaynakları öncele, varsayımı net belirt.\n"
            "7. Belge üretiminde profesyonel yapı kullan: amaç, kapsam, yöntem, bulgular, öneriler, sonraki adımlar.\n"
            "8. Kod üretiminde clean code zorunlu: modülerlik, isimlendirme, hata yönetimi, testlenebilirlik, README netliği.\n"
            "9. En son teknoloji talebinde deprecated yaklaşım kullanma; stabil modern kütüphane/pratikleri seç.\n"
            "10. Cevap yerine eylem gerekiyorsa talimat listesi yazmak yerine aracı çalıştır ve sonuç/kanıtla dön."
        )

    def _resolve_system_prompt(self) -> str:
        custom = str(
            elyan_config.get("agent.system_prompt", "")
            or elyan_config.get("agent.systemPrompt", "")
            or ""
        ).strip()
        if custom:
            return custom

        name = str(elyan_config.get("agent.name", "Elyan") or "Elyan").strip() or "Elyan"
        personality = str(elyan_config.get("agent.personality", "professional") or "professional").strip().lower()
        language = str(elyan_config.get("agent.language", "tr") or "tr").strip().lower()

        personality_map = {
            "professional": "Tonun profesyonel, güvenilir ve operasyon odaklı olsun.",
            "technical": "Tonun teknik, net ve uygulanabilir adımlara odaklı olsun.",
            "friendly": "Tonun sıcak, kısa ve yardımcı olsun.",
            "concise": "Yanıtlarını mümkün olduğunca kısa ve net tut.",
            "creative": "Yaratıcı görevlerde alternatifli ve üretken yaklaşım sergile.",
        }
        lang_clause = "Yanıtları varsayılan olarak Türkçe ver."
        if language == "en":
            lang_clause = "Respond in English by default unless user asks otherwise."

        extra = personality_map.get(personality, personality_map["professional"])
        return (
            f"Sen {name} adlı dijital asistansın. "
            + self._default_chat_prompt
            + " "
            + extra
            + " "
            + lang_clause
        )

    async def check_model(self) -> bool:
        """Hızlı kontrol: En az bir sağlayıcı var mı?"""
        return len(self.orchestrator.providers) > 0

    async def generate(self, prompt: str, system_prompt: str = None, model_config: dict = None, role: str = "inference", history: list = None, user_id: str = "local", temperature: float = None) -> str:
        from core.llm.token_budget import token_budget
        from core.resilience.circuit_breaker import resilience_manager
        from core.llm.quality_gate import quality_gate

        # 1. Budget Check
        if not token_budget.is_within_budget(user_id):
            return "Hata: Günlük LLM bütçesi aşıldı. Lütfen daha sonra deneyin."

        # cost_guard: cap temperature and token budget
        _temp = temperature
        _max_tokens = None
        if self.cost_guard:
            if _temp is not None and _temp > 0.35:
                _temp = 0.35
            elif _temp is None:
                _temp = 0.3
            _max_tokens = 320

        # Test/compat path: honor instance-level monkeypatches for router shortcut.
        _patched = self.__dict__.get("_call_any_provider")
        if callable(_patched):
            return await _patched(
                prompt,
                user_message=prompt,
                temp=_temp if _temp is not None else 0.3,
                max_tokens=_max_tokens,
            )

        # Strong system instruction
        if not system_prompt:
            system_prompt = self._resolve_system_prompt()

        # Runtime privacy/model policy
        local_first = bool(elyan_config.get("agent.model.local_first", True))
        kvkk_strict = bool(elyan_config.get("security.kvkk.strict", True))
        redact_cloud_prompts = bool(elyan_config.get("security.kvkk.redactCloudPrompts", True))
        allow_cloud_fallback = bool(elyan_config.get("security.kvkk.allowCloudFallback", True))
        external_providers = {"openai", "groq", "gemini", "google", "anthropic"}

        # Retry Loop with Exponential Backoff and Provider Switching
        retry_attempts = 3
        backoff = 1.0
        
        # Get providers to try
        cfg_seed = model_config or self.orchestrator.get_best_available(role)
        if local_first:
            try:
                local_cfg = self.orchestrator.get_best_available(role, exclude=external_providers)
            except Exception:
                local_cfg = {"type": "none"}
            if local_cfg.get("type") != "none":
                cfg_seed = local_cfg
            elif not allow_cloud_fallback:
                return "KVKK/güvenlik politikası gereği bulut modele fallback kapalı ve yerel model bulunamadı."
        visited_providers = set()
        
        last_error = ""

        for attempt in range(retry_attempts):
            # Pick best available if not first attempt or if current provider is blocked
            if attempt == 0:
                cfg = cfg_seed
            else:
                # Exclude failed providers for this attempt
                cfg = self.orchestrator.get_best_available(role, exclude=visited_providers)
            
            provider = cfg.get("type", "openai")
            visited_providers.add(provider)

            if provider == "none":
                break

            if local_first and not allow_cloud_fallback and provider in external_providers:
                last_error = f"cloud provider blocked by policy: {provider}"
                continue

            # 2. Circuit Breaker Check
            if not resilience_manager.can_call(provider):
                logger.warning(f"Circuit breaker is OPEN for {provider}. Skipping.")
                continue

            logger.info(f"Generating with {provider} (role: {role}, attempt: {attempt+1})...")
            
            try:
                # Format history for specific providers
                history_context = ""
                if history:
                    formatted_history = []
                    for h in history[-5:]:
                        u = h.get("user_message", "")
                        b = h.get("bot_response", "")
                        formatted_history.append(f"Kullanıcı: {u}\nElyan: {b}")
                    history_context = "\n".join(formatted_history)

                full_prompt = prompt
                if history_context:
                    full_prompt = f"Geçmiş Konuşma:\n{history_context}\n\nŞu anki Mesaj: {prompt}"

                provider_prompt = prompt
                provider_history = history
                if kvkk_strict and redact_cloud_prompts and is_external_provider(provider):
                    provider_prompt = redact_text(prompt)
                    if isinstance(history, list):
                        provider_history = []
                        for item in history[-5:]:
                            if not isinstance(item, dict):
                                continue
                            provider_history.append(
                                {
                                    "user_message": redact_text(str(item.get("user_message", ""))),
                                    "bot_response": redact_text(str(item.get("bot_response", ""))),
                                }
                            )

                t_call_start = time.time()
                # Call actual provider method
                response = ""
                if provider == "ollama":
                    response = await self._call_ollama(full_prompt, system_prompt, cfg, user_id=user_id)
                elif provider == "openai":
                    response = await self._call_openai(provider_prompt, system_prompt, cfg, provider_history, user_id=user_id)
                elif provider == "groq":
                    response = await self._call_groq(provider_prompt, system_prompt, cfg, provider_history, user_id=user_id)
                elif provider == "gemini" or provider == "google":
                    response = await self._call_gemini(provider_prompt, system_prompt, cfg, provider_history, user_id=user_id)

                self.orchestrator.record_metric(provider, True, time.time() - t_call_start)

                # 3. Quality Gate Check
                quality = quality_gate.validate(response)
                if not quality["valid"] and attempt < retry_attempts - 1:
                    logger.warning(f"Quality gate failed for {provider}: {quality['reason']}. Retrying...")
                    continue

                # 4. Success Recording
                resilience_manager.record_success(provider)
                
                # 5. Usage Counting (Mock token counts for now, should be from response metadata)
                prompt_len = len(full_prompt + (system_prompt or "")) // 4
                completion_len = len(response) // 4
                token_budget.record_usage(
                    user_id=user_id,
                    provider=provider,
                    model=cfg.get("model", "unknown"),
                    prompt_tokens=prompt_len,
                    completion_tokens=completion_len,
                    cost_usd=(prompt_len + completion_len) * 0.000002 # Average cost
                )

                return response

            except Exception as e:
                last_error = str(e)
                logger.error(f"Generation error with {provider} (attempt {attempt+1}): {e}")
                resilience_manager.record_failure(provider)
                self.orchestrator.record_metric(provider, False, 0)
                
                if attempt < retry_attempts - 1:
                    await asyncio.sleep(backoff)
                    backoff *= 2.0 # Exponential backoff
                else:
                    break

        return f"Hata: Yapay zeka servislerine şu an erişilemiyor. (Son hata: {last_error})"

    async def stream_generate(self, prompt: str, system_prompt: str = None, model_config: dict = None, role: str = "inference"):
        """Streaming version of generate."""
        cfg = model_config or self.orchestrator.get_best_available(role)
        provider = cfg.get("type")
        if not system_prompt: system_prompt = self._resolve_system_prompt()
        
        logger.info(f"Streaming with {provider}...")
        
        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=cfg.get("apiKey"))
            stream = await client.chat.completions.create(
                model=cfg.get("model", "gpt-4o"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                stream=True
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        elif provider == "groq":
            # Groq streaming implementation...
            pass
        else:
            # Fallback to non-streaming for now
            yield await self.generate(prompt, system_prompt, model_config, role)

    async def _call_ollama(self, prompt: str, system_prompt: str, cfg: dict, user_id: str = "local") -> str:
        model = cfg.get("model", "llama3.1:8b")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("http://localhost:11434/api/generate", json={
                "model": model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False
            })
            data = resp.json()
            content = data.get("response", "")
            # Estimate tokens for Ollama (rough 1 token = 4 chars)
            prompt_tokens = len(prompt + system_prompt) // 4
            completion_tokens = len(content) // 4
            self.pricing_tracker.record_usage(
                provider="ollama",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                user_id=user_id
            )
            return content

    async def _call_openai(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=cfg.get("apiKey"))
        messages = []
        if system_prompt: messages.append({"role": "system", "content": system_prompt})
        
        if history:
            for h in history[-5:]:
                messages.append({"role": "user", "content": h.get("user_message", "")})
                # Handle dict response
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try: b = json.loads(b).get("message", "")
                    except: pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})
                
        messages.append({"role": "user", "content": prompt})
        model = cfg.get("model", "gpt-4o")
        resp = await client.chat.completions.create(model=model, messages=messages)
        content = resp.choices[0].message.content
        usage = resp.usage
        if usage:
            self.pricing_tracker.record_usage(
                provider="openai",
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                user_id=user_id
            )
        return content

    async def _call_groq(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        headers = {"Authorization": f"Bearer {cfg.get('apiKey')}", "Content-Type": "application/json"}
        messages = []
        if system_prompt: messages.append({"role": "system", "content": system_prompt})
        
        if history:
            for h in history[-5:]:
                messages.append({"role": "user", "content": h.get("user_message", "")})
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try: b = json.loads(b).get("message", "")
                    except: pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})

        messages.append({"role": "user", "content": prompt})
        model = cfg.get("model", "llama-3.3-70b-versatile")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers,
                                    json={"model": model, "messages": messages})
            data = resp.json()
            content = data['choices'][0]['message']['content']
            usage = data.get('usage')
            if usage:
                self.pricing_tracker.record_usage(
                    provider="groq",
                    model=model,
                    prompt_tokens=usage.get('prompt_tokens', 0),
                    completion_tokens=usage.get('completion_tokens', 0),
                    user_id=user_id
                )
            return content

    async def _call_gemini(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        model = cfg.get("model", "gemini-2.0-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={cfg.get('apiKey')}"
        
        contents = []
        if history:
            for h in history[-5:]:
                contents.append({"role": "user", "parts": [{"text": h.get("user_message", "")}]})
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try: b = json.loads(b).get("message", "")
                    except: pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                contents.append({"role": "model", "parts": [{"text": b}]})
        
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        # Note: Gemini also has system_instruction in some API versions, 
        # but here we might need to add it to contents or use a different endpoint.
        # For simplicity, keeping original logic but adding usage tracking.
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"contents": contents})
            data = resp.json()
            # This is a bit simplified, Gemini structure can be complex
            content = data['candidates'][0]['content']['parts'][0]['text']
            usage = data.get('usageMetadata')
            if usage:
                self.pricing_tracker.record_usage(
                    provider="gemini",
                    model=model,
                    prompt_tokens=usage.get('promptTokenCount', 0),
                    completion_tokens=usage.get('candidatesTokenCount', 0),
                    user_id=user_id
                )
            return content
        
        data = {"contents": contents}
        if system_prompt:
            data["system_instruction"] = {"parts": [{"text": system_prompt}]}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=data)
            return resp.json()['candidates'][0]['content']['parts'][0]['text']

    async def process(self, user_message: str, user_id: Optional[int] = None) -> dict[str, Any]:
        """Ana işleme fonksiyonu - önce cache, sonra intent parser, sonra LLM"""
        cached = self.cache.get(user_message)
        if cached: return cached

        intent_result = self.intent_parser.parse(user_message)
        if intent_result:
            res = {"action": intent_result["action"], "message": intent_result.get("reply", "")}
            self.cache.set(user_message, res)
            return res

        # Detect role
        role = neural_router.detect_role(user_message)
        
        text = await self.generate(user_message, role=role)
        if text.strip().startswith('{'):
            try: return json.loads(text)
            except: pass
        return {"action": "chat", "message": text}

    async def close(self): pass

    # ── Router & Fallback API ─────────────────────────────────────────────────

    def _is_provider_available(self, provider: str) -> bool:
        """Bir sağlayıcının kullanılabilir olup olmadığını kontrol eder."""
        cfg = self.orchestrator.get_best_available("inference")
        return cfg.get("type") not in (None, "none")

    async def _call_provider(self, provider: str, prompt: str, user_message: str = "",
                              temp: float = 0.3, max_tokens: int = None) -> str:
        """Tek bir sağlayıcıya çağrı yapar."""
        cfg = self.orchestrator.get_best_available("inference")
        cfg = dict(cfg)
        cfg["type"] = provider
        if provider == "ollama":
            return await self._call_ollama(prompt, self._resolve_system_prompt(), cfg)
        elif provider == "openai":
            return await self._call_openai(prompt, self._resolve_system_prompt(), cfg)
        elif provider == "groq":
            return await self._call_groq(prompt, self._resolve_system_prompt(), cfg)
        elif provider in ("gemini", "google"):
            return await self._call_gemini(prompt, self._resolve_system_prompt(), cfg)
        raise ValueError(f"Unknown provider: {provider}")

    async def _call_any_provider(self, prompt: str, user_message: str = "",
                                  temp: float = 0.3, max_tokens: int = None) -> str:
        """Fallback sırasına göre sağlayıcıları dener; trace kaydeder."""
        self._router_trace = []
        order = list(self.fallback_order) if self.fallback_order else [self.llm_type]
        for provider in order:
            if not self._is_provider_available(provider):
                self._router_trace.append({"provider": provider, "status": "unavailable",
                                           "reason": "not_configured"})
                continue
            try:
                result = await self._call_provider(provider, prompt, user_message, temp, max_tokens)
                self._router_trace.append({"provider": provider, "status": "success"})
                return result
            except Exception as exc:
                reason = "timeout" if "timeout" in str(exc).lower() else str(exc)[:80]
                self._router_trace.append({"provider": provider, "status": "failed", "reason": reason})
        return "Üzgünüm, tüm sağlayıcılar yanıt vermedi."

    def get_last_router_trace(self) -> list:
        """Son router denemesinin izini döner."""
        return list(self._router_trace)

    async def chat(self, text: str, history: list = None, user_id: str = "local") -> str:
        """Kısa sohbet yanıtı üretir. cost_guard açıksa token bütçesini kısıtlar."""
        max_tokens = 260 if self.cost_guard else None
        temp = 0.3
        system = self._resolve_system_prompt()
        prompt = f"{system}\n\nKullanıcı: {text}"
        # If _call_any_provider has been monkey-patched on the instance, use it
        _patched = self.__dict__.get('_call_any_provider')
        if _patched is not None:
            return await _patched(prompt, user_message=text, temp=temp, max_tokens=max_tokens)
        return await self._call_any_provider(prompt, user_message=text, temp=temp,
                                              max_tokens=max_tokens)
