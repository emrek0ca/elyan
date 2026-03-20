import httpx
import json
import asyncio
import time
import importlib.util
import re
from contextvars import ContextVar
from typing import Any, Optional
from config.elyan_config import elyan_config
from core.model_orchestrator import model_orchestrator
from core.neural_router import neural_router
from .llm_cache import get_cache
from .intent_parser import IntentParser
from .intent_classifier import get_classifier
from .llm_optimizer import get_llm_optimizer
from .pricing_tracker import get_pricing_tracker
from .fast_response import FastResponseSystem, QuestionType
from core.nlu_normalizer import normalize_turkish_text
from core.command_hardening import (
    build_chat_fallback_message,
    build_chat_history_block,
    chat_output_needs_retry,
    sanitize_chat_output,
)
from security.privacy_guard import redact_text, is_external_provider
from utils.logger import get_logger

logger = get_logger("llm_client")
_chat_system_prompt_override: ContextVar[str | None] = ContextVar("llm_chat_system_prompt_override", default=None)

class LLMClient:
    def __init__(self):
        self.orchestrator = model_orchestrator
        self.intent_parser = IntentParser()
        self.cache = get_cache()
        self.classifier = get_classifier()
        self.llm_optimizer = get_llm_optimizer()
        self.pricing_tracker = get_pricing_tracker()
        self.fast_response = FastResponseSystem()

        # Router / fallback configuration
        self.llm_type: str = "openai"
        self.cost_guard: bool = False
        self.fallback_mode: str = "standard"
        self.fallback_order: list = ["openai", "groq", "gemini", "ollama"]
        self._router_trace: list = []
        self._collaboration_trace: list = []

        self.assistant_style = "professional_friendly_short"
        self._default_chat_prompt = (
            "Sen Elyan, son derece zeki, yetenekli ve yardımsever bir dijital asistansın. "
            "Kullanıcıya profesyonel, samimi, sıcak ve çözüm odaklı yanıtlar ver. "
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

    def _role_token_limit(self, role: str) -> int:
        _role = str(role or "inference").strip().lower()
        limits = {
            "chat": 300,
            "inference": 800,
            "code": 4096,
            "code_worker": 4096,
            "reasoning": 2048,
            "planning": 2048,
            "creative": 1500,
            "router": 320,
            "critic": 2048,
            "qa": 2048,
        }
        return int(limits.get(_role, 800))

    def _chat_system_prompt(self) -> str:
        name = str(elyan_config.get("agent.name", "Elyan") or "Elyan").strip() or "Elyan"
        personality = str(elyan_config.get("agent.personality", "professional") or "professional").strip().lower()
        language = str(elyan_config.get("agent.language", "tr") or "tr").strip().lower()

        tone_map = {
            "professional": "Profesyonel ama sıcak kal.",
            "technical": "Net ve uygulanabilir ol.",
            "friendly": "Sıcak ve rahat bir ton kullan.",
            "concise": "Mümkün olduğunca kısa ve net cevap ver.",
            "creative": "Gerekirse yaratıcı ve canlı ifadeler kullan.",
        }
        if language == "en":
            return (
                f"You are {name}. "
                "Reply naturally and briefly. "
                "Keep it to 2-3 sentences. "
                "Do not write meta commentary, task plans, Deliverable Spec, Done Criteria, JSON, tables, or code blocks."
            )

        return (
            f"Sen {name}. "
            "Kısa, samimi, doğal ve net Türkçe yanıtlar ver. "
            "2-3 cümleyi geçme. "
            "Meta açıklama, görev planı, Deliverable Spec, Done Criteria, JSON, tablo veya kod bloğu yazma. "
            f"{tone_map.get(personality, tone_map['professional'])}"
        )

    def _sanitize_chat_output(self, text: Any) -> str:
        return sanitize_chat_output(text)

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
            "professional": "Tonun profesyonel, güvenilir, insan gibi ve operasyon odaklı olsun.",
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

    def _resolve_role_system_prompt(self, role: str) -> str:
        """Return a role-optimised system prompt.

        Falls back to the generic _resolve_system_prompt() for unknown roles.
        """
        _role = str(role or "inference").strip().lower()

        _base_identity = (
            "Sen Elyan, son derece zeki ve yetenekli bir dijital asistansın. "
            "Kullanıcıyla her zaman profesyonel, samimi ve çözüm odaklı iletişim kur. "
            "Yanıtları varsayılan olarak Türkçe ver, kullanıcı başka dil isterse o dilde yanıtla.\n\n"
        )

        if _role in ("code", "code_worker"):
            return (
                _base_identity
                + "SEN UZMAN BİR YAZILIM MÜHENDİSİSİN.\n"
                "KURALLAR:\n"
                "1. Her zaman TAM, ÇALIŞIR, production-ready kod yaz. İskelet veya placeholder ASLA KULLANMA.\n"
                "2. Kod bloklarında dili belirt (```python, ```html vb.).\n"
                "3. Hata yönetimi (try/except, error boundaries) ekle.\n"
                "4. Modern best practice kullan: tip güvenliği, modülerlik, anlamlı isimlendirme.\n"
                "5. Gerekiyorsa dosya yapısını açıkla, her dosyayı tam içerikle ver.\n"
                "6. Kısa açıklama + tam kod ver. Gereksiz laf kalabalığı yapma.\n"
                "7. Kullanıcının dilini anla — Türkçe istekler Türkçe açıklamayla, İngilizce istekler İngilizce.\n"
            )

        if _role in ("reasoning", "planning", "critic", "qa"):
            return (
                _base_identity
                + "SEN ANALİTİK BİR DÜŞÜNÜRSÜN.\n"
                "KURALLAR:\n"
                "1. Adım adım düşün, her adımda mantığını açıkla.\n"
                "2. Artıları ve eksileri listele, karşılaştırmalı değerlendir.\n"
                "3. Varsayımları açıkça belirt, belirsizlikleri işaretle.\n"
                "4. Sonuçta net bir öneri veya karar sun.\n"
                "5. Karmaşık konuları basit, anlaşılır dille açıkla.\n"
            )

        if _role == "chat":
            return self._chat_system_prompt()

        if _role == "creative":
            return (
                _base_identity
                + "SEN YARATICI BİR İÇERİK ÜRETICISISIN.\n"
                "KURALLAR:\n"
                "1. Özgün, etkileyici ve akılda kalıcı içerik üret.\n"
                "2. Türk kültürel bağlamını dikkate al.\n"
                "3. Dil zenginliğini kullan — canlı, görsel ve duygusal ifadeler.\n"
                "4. Format ve yapıyı içerik türüne göre ayarla (blog, hikaye, senaryo vb.).\n"
            )

        # inference / default — concise chat
        return self._resolve_system_prompt()

    async def check_model(self) -> bool:
        """Hızlı kontrol: En az bir sağlayıcı var mı?"""
        return len(self.orchestrator.providers) > 0

    def _collaboration_enabled_for_role(self, prompt: str, role: str) -> bool:
        defaults = {
            "enabled": True,
            "roles": [
                "reasoning",
                "planning",
                "code",
                "critic",
                "qa",
                "research_worker",
                "code_worker",
            ],
        }
        get_settings = getattr(self.orchestrator, "get_collaboration_settings", None)
        if callable(get_settings):
            try:
                cfg = get_settings() or {}
            except Exception:
                cfg = {}
        else:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        cfg = {**defaults, **cfg}
        role_name = str(role or "inference").strip().lower() or "inference"
        if not cfg.get("enabled"):
            return False
        if role_name not in set(cfg.get("roles") or []):
            return False
        words = len(str(prompt or "").split())
        return words >= 10 or role_name in {"reasoning", "planning", "code", "critic", "qa", "research_worker", "code_worker"}

    def _resolve_explicit_model_config(self, model_config: dict | None, role: str) -> dict:
        cfg = dict(model_config or {})
        provider = str(cfg.get("type") or cfg.get("provider") or "").strip().lower()
        model = str(cfg.get("model") or "").strip()
        if model and "/" in model and not provider:
            provider, model = model.split("/", 1)
        if not provider and model:
            provider = str(self.orchestrator.find_provider_for_model(model) or "").strip().lower()
        if not provider:
            provider = str(self.orchestrator.get_best_available(role).get("type") or "openai").strip().lower()
        provider = self.orchestrator._normalize_provider(provider)
        resolved = self.orchestrator.get_provider_config(provider, role=role, model=model or None)
        for key, value in cfg.items():
            if value is not None and key not in {"type", "provider", "model"}:
                resolved[key] = value
        resolved["type"] = provider
        resolved["provider"] = provider
        if model:
            resolved["model"] = self.orchestrator._normalize_model_for_provider(provider, model)
        return resolved

    async def generate_collaborative(
        self,
        prompt: str,
        system_prompt: str = None,
        role: str = "reasoning",
        history: list = None,
        user_id: str = "local",
        temperature: float = None,
        max_models: int | None = None,
    ) -> str:
        collab = self.orchestrator.get_collaboration_settings()
        pool = self.orchestrator.get_collaboration_pool(role=role, max_models=max_models or collab.get("max_models", 3))
        if len(pool) <= 1:
            cfg = pool[0] if pool else None
            return await self.generate(
                prompt,
                system_prompt=system_prompt,
                model_config=cfg,
                role=role,
                history=history,
                user_id=user_id,
                temperature=temperature,
                strict_model_config=bool(cfg),
                disable_collaboration=True,
            )

        self._collaboration_trace = []
        system = system_prompt or self._resolve_system_prompt()
        lenses = [
            ("planner", "Kullanıcının gerçek niyetini, teslim kriterlerini ve eksik anlaşılma risklerini çıkar."),
            ("builder", "Bu isteği en profesyonel şekilde gerçekleştirmek için net çözüm yaklaşımı ve somut üretim yönü ver."),
            ("critic", "Yanlış anlama, boş çıktı, placeholder, teknik risk ve kalite açıklarını agresif şekilde tespit et."),
        ]
        if len(pool) > len(lenses):
            for idx in range(len(lenses), len(pool)):
                lenses.append((f"specialist_{idx+1}", "Önceki görüşleri tekrar etmeyen, fark yaratan iyileştirme önerileri ver."))

        async def _run_lens(cfg: dict, lens_name: str, lens_instruction: str) -> dict:
            augmented_prompt = (
                f"{prompt}\n\n"
                f"COLLABORATION LENS: {lens_name}\n"
                f"Görev: {lens_instruction}\n"
                "Yanıtı kısa ama yüksek sinyalli ver. Kullanıcının asıl isteğini bozma."
            )
            try:
                response = await self.generate(
                    augmented_prompt,
                    system_prompt=system,
                    model_config=cfg,
                    role=role,
                    history=history,
                    user_id=user_id,
                    temperature=temperature,
                    strict_model_config=True,
                    disable_collaboration=True,
                )
                item = {
                    "provider": cfg.get("type") or cfg.get("provider"),
                    "model": cfg.get("model"),
                    "lens": lens_name,
                    "status": "success",
                    "response": str(response or "").strip(),
                }
                self._collaboration_trace.append(item)
                return item
            except Exception as exc:
                item = {
                    "provider": cfg.get("type") or cfg.get("provider"),
                    "model": cfg.get("model"),
                    "lens": lens_name,
                    "status": "failed",
                    "error": str(exc),
                    "response": "",
                }
                self._collaboration_trace.append(item)
                return item

        drafts = await asyncio.gather(
            *[
                _run_lens(cfg, lens_name, lens_instruction)
                for cfg, (lens_name, lens_instruction) in zip(pool, lenses)
            ]
        )
        usable = [item for item in drafts if item.get("status") == "success" and item.get("response")]
        if not usable:
            return await self.generate(
                prompt,
                system_prompt=system,
                model_config=pool[0],
                role=role,
                history=history,
                user_id=user_id,
                temperature=temperature,
                strict_model_config=True,
                disable_collaboration=True,
            )

        synthesis_blocks = []
        for idx, item in enumerate(usable, start=1):
            synthesis_blocks.append(
                f"[{idx}] {item.get('lens')} | {item.get('provider')}/{item.get('model')}\n{item.get('response')}"
            )
        json_guard = "Orijinal istem JSON/structured format istiyorsa aynı formatı koru." if "json" in str(prompt or "").lower() else ""
        synthesis_prompt = (
            f"Kullanıcı isteği:\n{prompt}\n\n"
            "Aşağıda farklı modellerin paralel görüşleri var. Çelişkileri çöz, kullanıcı niyetini keskinleştir "
            "ve tek bir güçlü nihai yanıt üret.\n\n"
            f"{chr(10).join(synthesis_blocks)}\n\n"
            f"{json_guard}\n"
            "Boş, genel geçer veya placeholder cevap verme. Nihai yanıt tek parça olsun."
        )
        final = await self.generate(
            synthesis_prompt,
            system_prompt=system,
            model_config=pool[0],
            role=role,
            history=None,
            user_id=user_id,
            temperature=temperature,
            strict_model_config=True,
            disable_collaboration=True,
        )
        self._collaboration_trace.append(
            {
                "provider": pool[0].get("type") or pool[0].get("provider"),
                "model": pool[0].get("model"),
                "lens": "synthesizer",
                "status": "success",
            }
        )
        return final

    async def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        model_config: dict = None,
        role: str = "inference",
        history: list = None,
        user_id: str = "local",
        temperature: float = None,
        strict_model_config: bool = False,
        disable_collaboration: bool = False,
        model: str | None = None,
    ) -> str:
        from core.llm.token_budget import token_budget
        from core.resilience.circuit_breaker import resilience_manager
        from core.llm.quality_gate import quality_gate

        if model:
            merged_model_config = dict(model_config or {})
            if not merged_model_config.get("model"):
                merged_model_config["model"] = str(model)
            model_config = merged_model_config
            strict_model_config = True

        # 1. Budget Check
        if not token_budget.is_within_budget(user_id):
            return "Hata: Günlük LLM bütçesi aşıldı. Lütfen daha sonra deneyin."

        # cost_guard: role-aware temperature caps; token limits always apply.
        _temp = temperature
        _max_tokens = self._role_token_limit(role)
        if self.cost_guard:
            _role = str(role or "inference").strip().lower()
            _cg_limits = {
                "code":      (0.4,  4096),
                "code_worker": (0.4, 4096),
                "reasoning": (0.3,  2048),
                "planning":  (0.3,  2048),
                "critic":    (0.3,  2048),
                "qa":        (0.3,  2048),
                "creative":  (0.7,  1500),
                "router":    (0.2,  320),
            }
            _cg_temp_cap, _cg_max_tok = _cg_limits.get(_role, (0.5, 800))
            if _temp is not None and _temp > _cg_temp_cap:
                _temp = _cg_temp_cap
            elif _temp is None:
                _temp = _cg_temp_cap
            _max_tokens = min(_max_tokens, _cg_max_tok)

        # Test/compat path: honor instance-level monkeypatches for router shortcut.
        _patched = self.__dict__.get("_call_any_provider")
        if callable(_patched):
            return await _patched(
                prompt,
                user_message=prompt,
                temp=_temp if _temp is not None else 0.3,
                max_tokens=_max_tokens,
            )

        # Strong system instruction — role-aware prompt selection
        if not system_prompt:
            system_prompt = self._resolve_role_system_prompt(role)

        if not disable_collaboration and not model_config and self._collaboration_enabled_for_role(prompt, role):
            return await self.generate_collaborative(
                prompt,
                system_prompt=system_prompt,
                role=role,
                history=history,
                user_id=user_id,
                temperature=temperature,
            )

        # Runtime privacy/model policy
        local_first = bool(elyan_config.get("agent.model.local_first", True))
        kvkk_strict = bool(elyan_config.get("security.kvkk.strict", True))
        redact_cloud_prompts = bool(elyan_config.get("security.kvkk.redactCloudPrompts", True))
        allow_cloud_fallback = bool(elyan_config.get("security.kvkk.allowCloudFallback", True))
        external_providers = {"openai", "groq", "gemini", "google", "anthropic"}

        # Local-first now applies broadly: prefer Ollama for simple and
        # general inference paths, then fall back to cloud providers if needed.
        local_first_effective = local_first

        # Retry Loop with Exponential Backoff and Provider Switching
        retry_attempts = 3
        backoff = 1.0

        # Get providers to try
        cfg_seed = self._resolve_explicit_model_config(model_config, role) if (model_config and strict_model_config) else (model_config or self.orchestrator.get_best_available(role))
        if local_first_effective and not (model_config and strict_model_config):
            try:
                local_cfg = self.orchestrator.get_best_available(role, exclude=external_providers)
            except Exception:
                local_cfg = {"type": "none"}
            if local_cfg.get("type") != "none":
                cfg_seed = local_cfg
            elif not allow_cloud_fallback:
                return "KVKK/güvenlik politikası gereği bulut modele fallback kapalı ve yerel model bulunamadı."
        if model_config and strict_model_config:
            retry_attempts = 1
        visited_providers = set()
        
        last_error = ""

        for attempt in range(retry_attempts):
            # Pick best available if not first attempt or if current provider is blocked
            if attempt == 0:
                cfg = cfg_seed
            else:
                # Exclude failed providers for this attempt
                cfg = self.orchestrator.get_best_available(role, exclude=visited_providers)
            
            provider = str(cfg.get("type") or cfg.get("provider") or "openai").strip().lower()
            visited_providers.add(provider)

            if provider == "none":
                break

            ready, reason = self._provider_runtime_ready(provider, cfg)
            if not ready:
                last_error = reason
                logger.warning(f"Skipping provider {provider}: {reason}")
                continue

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
                elif provider == "anthropic":
                    response = await self._call_anthropic(provider_prompt, system_prompt, cfg, provider_history, user_id=user_id)
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

        # Graceful fallback — try Ollama as last resort if not already tried
        if "ollama" not in visited_providers:
            try:
                logger.info("Last resort: trying Ollama...")
                ollama_cfg = {"type": "ollama", "model": "llama3.2:3b"}
                response = await self._call_ollama(prompt, system_prompt or "", ollama_cfg, user_id=user_id)
                if response:
                    return response
            except Exception as ollama_err:
                last_error = f"Ollama: {ollama_err}"

        # Final graceful message — never crash
        logger.warning(f"All providers failed. Last error: {last_error}")
        return (
            "Şu an yapay zeka servislerine erişilemiyor.\n"
            "Çözüm: Dashboard → LLM sekmesinden provider ayarla "
            "veya terminalde 'elyan setup' komutunu çalıştır."
        )

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
        model = cfg.get("model", "llama3.2:3b")
        endpoint = cfg.get("endpoint") or "http://localhost:11434"
        max_tokens = cfg.get("max_tokens")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "system": system_prompt or "",
                    "stream": False,
                }
                if max_tokens is not None:
                    payload["options"] = {"num_predict": int(max_tokens)}
                resp = await client.post(f"{endpoint}/api/generate", json=payload)
                data = resp.json()

                # Model not found — try to auto-detect an available model
                if data.get("error") and "not found" in str(data.get("error", "")).lower():
                    logger.warning(f"Ollama model '{model}' not found, auto-detecting...")
                    available = await self._ollama_detect_model(endpoint)
                    if available:
                        logger.info(f"Ollama auto-detected model: {available}")
                        payload2 = {
                            "model": available,
                            "prompt": prompt,
                            "system": system_prompt or "",
                            "stream": False,
                        }
                        if max_tokens is not None:
                            payload2["options"] = {"num_predict": int(max_tokens)}
                        resp2 = await client.post(f"{endpoint}/api/generate", json=payload2)
                        data = resp2.json()
                    else:
                        raise RuntimeError(f"Ollama'da hiç model yüklü değil. 'ollama pull llama3.2:3b' komutu ile model indir.")

                content = data.get("response", "")
                # Estimate tokens for Ollama (rough 1 token = 4 chars)
                prompt_tokens = len(prompt + (system_prompt or "")) // 4
                completion_tokens = len(content) // 4
                self.pricing_tracker.record_usage(
                    provider="ollama",
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    user_id=user_id
                )
                return content
        except httpx.ConnectError:
            raise RuntimeError("Ollama çalışmıyor. 'ollama serve' komutu ile başlat.")

    async def _ollama_detect_model(self, endpoint: str = "http://localhost:11434") -> str:
        """Detect best available Ollama model."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{endpoint}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    if models:
                        # Prefer larger models
                        names = [m.get("name", "") for m in models]
                        for preferred in ["llama3.1:8b", "mistral:latest", "llama3.2:3b", "qwen2.5-coder:7b"]:
                            if preferred in names:
                                return preferred
                        return names[0]  # Fallback to first available
        except Exception:
            pass
        return ""

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
                    except (json.JSONDecodeError, AttributeError): pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})

        messages.append({"role": "user", "content": prompt})
        model = cfg.get("model", "gpt-4o")
        kwargs = {"model": model, "messages": messages}
        if cfg.get("max_tokens") is not None:
            kwargs["max_tokens"] = int(cfg.get("max_tokens"))
        resp = await client.chat.completions.create(**kwargs)
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
                    except (json.JSONDecodeError, AttributeError): pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})

        messages.append({"role": "user", "content": prompt})
        model = cfg.get("model", "llama-3.3-70b-versatile")
        async with httpx.AsyncClient(timeout=60.0) as client:
            body = {"model": model, "messages": messages}
            if cfg.get("max_tokens") is not None:
                body["max_tokens"] = int(cfg.get("max_tokens"))
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body)
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
        api_key = cfg.get('apiKey', '')
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

        contents = []
        if history:
            for h in history[-5:]:
                contents.append({"role": "user", "parts": [{"text": h.get("user_message", "")}]})
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try: b = json.loads(b).get("message", "")
                    except (json.JSONDecodeError, AttributeError): pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                contents.append({"role": "model", "parts": [{"text": b}]})
        
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        # Note: Gemini also has system_instruction in some API versions, 
        # but here we might need to add it to contents or use a different endpoint.
        # For simplicity, keeping original logic but adding usage tracking.
        
        data = {"contents": contents}
        if system_prompt:
            data["system_instruction"] = {"parts": [{"text": system_prompt}]}
        if cfg.get("max_tokens") is not None:
            data["generationConfig"] = {"maxOutputTokens": int(cfg.get("max_tokens"))}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=data)
            payload = resp.json()

            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(f"gemini_error:{payload.get('error')}")

            candidates = payload.get("candidates") if isinstance(payload, dict) else None
            if not isinstance(candidates, list) or not candidates:
                raise RuntimeError(f"gemini_invalid_response:{str(payload)[:200]}")

            content_parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
            content = ""
            for part in content_parts:
                if isinstance(part, dict):
                    content += str(part.get("text") or "")
            content = content.strip()
            if not content:
                raise RuntimeError("gemini_empty_response")

            usage = payload.get("usageMetadata") or {}
            if usage:
                self.pricing_tracker.record_usage(
                    provider="gemini",
                    model=model,
                    prompt_tokens=usage.get("promptTokenCount", 0),
                    completion_tokens=usage.get("candidatesTokenCount", 0),
                    user_id=user_id
                )
            return content

    async def _call_anthropic(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        model = cfg.get("model", "claude-3-5-sonnet-latest")
        messages = []
        if history:
            for h in history[-5:]:
                messages.append({"role": "user", "content": h.get("user_message", "")})
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try:
                        b = json.loads(b).get("message", "")
                    except Exception:
                        pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "x-api-key": str(cfg.get("apiKey") or ""),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": int(cfg.get("max_tokens", 2048) or 2048),
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            data = resp.json()
            parts = data.get("content") or []
            content = ""
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    content += str(part.get("text") or "")
            usage = data.get("usage") or {}
            if usage:
                self.pricing_tracker.record_usage(
                    provider="anthropic",
                    model=model,
                    prompt_tokens=usage.get("input_tokens", 0),
                    completion_tokens=usage.get("output_tokens", 0),
                    user_id=user_id,
                )
            return content

    async def _call_deepseek(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        """DeepSeek API — OpenAI-compatible endpoint."""
        model = cfg.get("model", "deepseek-chat")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for h_item in history[-5:]:
                messages.append({"role": "user", "content": h_item.get("user_message", "")})
                b = h_item.get("bot_response", "")
                if isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {cfg.get('apiKey', '')}",
            "Content-Type": "application/json",
        }
        body = {"model": model, "messages": messages, "max_tokens": cfg.get("max_tokens", 2048)}
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post("https://api.deepseek.com/chat/completions", headers=headers, json=body)
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage") or {}
            if usage:
                self.pricing_tracker.record_usage(
                    provider="deepseek", model=model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    user_id=user_id,
                )
            return content

    async def _call_mistral(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        """Mistral API — OpenAI-compatible endpoint."""
        model = cfg.get("model", "mistral-large-latest")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for h_item in history[-5:]:
                messages.append({"role": "user", "content": h_item.get("user_message", "")})
                b = h_item.get("bot_response", "")
                if isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {cfg.get('apiKey', '')}",
            "Content-Type": "application/json",
        }
        body = {"model": model, "messages": messages, "max_tokens": cfg.get("max_tokens", 2048)}
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post("https://api.mistral.ai/v1/chat/completions", headers=headers, json=body)
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage") or {}
            if usage:
                self.pricing_tracker.record_usage(
                    provider="mistral", model=model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    user_id=user_id,
                )
            return content

    async def _call_together(self, prompt: str, system_prompt: str, cfg: dict, history: list = None, user_id: str = "local") -> str:
        """Together AI API — OpenAI-compatible endpoint."""
        model = cfg.get("model", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for h_item in history[-5:]:
                messages.append({"role": "user", "content": h_item.get("user_message", "")})
                b = h_item.get("bot_response", "")
                if isinstance(b, dict):
                    b = b.get("message", "")
                messages.append({"role": "assistant", "content": b})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {cfg.get('apiKey', '')}",
            "Content-Type": "application/json",
        }
        body = {"model": model, "messages": messages, "max_tokens": cfg.get("max_tokens", 2048)}
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post("https://api.together.xyz/v1/chat/completions", headers=headers, json=body)
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage") or {}
            if usage:
                self.pricing_tracker.record_usage(
                    provider="together", model=model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    user_id=user_id,
                )
            return content

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
            except (json.JSONDecodeError, ValueError):
                logger.debug("LLM returned non-JSON text starting with '{', using as chat response")
        return {"action": "chat", "message": text}

    async def close(self):
        """Clean up resources."""
        logger.debug("LLMClient closing")

    # ── Router & Fallback API ─────────────────────────────────────────────────

    def _get_provider_config(self, provider: str, role: str = "inference") -> dict:
        provider_name = self.orchestrator._normalize_provider(provider)
        direct = self.orchestrator.providers.get(provider_name)
        if isinstance(direct, dict):
            cfg = dict(direct)
            cfg["type"] = provider_name
            cfg["provider"] = provider_name
            return cfg
        cfg = dict(self.orchestrator.get_provider_config(provider_name, role=role))
        cfg["type"] = provider_name
        cfg["provider"] = provider_name
        return cfg

    def _provider_runtime_ready(self, provider: str, cfg: Optional[dict] = None) -> tuple[bool, str]:
        provider_name = self.orchestrator._normalize_provider(provider)
        provider_cfg = dict(cfg or self._get_provider_config(provider_name))

        if provider_name == "openai":
            if importlib.util.find_spec("openai") is None:
                return False, "openai_sdk_missing"
            if not provider_cfg.get("apiKey"):
                return False, "openai_api_key_missing"
            return True, "ok"
        if provider_name == "groq":
            return (bool(provider_cfg.get("apiKey")), "groq_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        if provider_name in {"gemini", "google"}:
            return (bool(provider_cfg.get("apiKey")), "google_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        if provider_name == "anthropic":
            return (bool(provider_cfg.get("apiKey")), "anthropic_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        if provider_name == "ollama":
            return True, "ok"
        if provider_name == "deepseek":
            return (bool(provider_cfg.get("apiKey")), "deepseek_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        if provider_name == "mistral":
            return (bool(provider_cfg.get("apiKey")), "mistral_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        if provider_name == "together":
            return (bool(provider_cfg.get("apiKey")), "together_api_key_missing" if not provider_cfg.get("apiKey") else "ok")
        return False, "unknown_provider"

    def _is_provider_available(self, provider: str) -> bool:
        """Bir sağlayıcının kullanılabilir olup olmadığını kontrol eder."""
        cfg = self._get_provider_config(provider, role="inference")
        if cfg.get("type") in (None, "none"):
            return False
        ready, _ = self._provider_runtime_ready(provider, cfg)
        return ready

    async def _call_provider(self, provider: str, prompt: str, user_message: str = "",
                              temp: float = 0.3, max_tokens: int = None) -> str:
        """Tek bir sağlayıcıya çağrı yapar."""
        provider_name = self.orchestrator._normalize_provider(provider)
        cfg = self._get_provider_config(provider_name, role="inference")
        ready, reason = self._provider_runtime_ready(provider, cfg)
        if not ready:
            raise RuntimeError(f"provider_unavailable:{reason}")
        if max_tokens is not None:
            cfg = dict(cfg)
            cfg["max_tokens"] = int(max_tokens)
        sys_prompt = _chat_system_prompt_override.get() or self._resolve_system_prompt()
        if provider_name == "ollama":
            return await self._call_ollama(prompt, sys_prompt, cfg)
        elif provider_name == "openai":
            return await self._call_openai(prompt, sys_prompt, cfg)
        elif provider_name == "groq":
            return await self._call_groq(prompt, sys_prompt, cfg)
        elif provider_name == "anthropic":
            return await self._call_anthropic(prompt, sys_prompt, cfg)
        elif provider_name in ("gemini", "google"):
            return await self._call_gemini(prompt, sys_prompt, cfg)
        elif provider_name == "deepseek":
            return await self._call_deepseek(prompt, sys_prompt, cfg)
        elif provider_name == "mistral":
            return await self._call_mistral(prompt, sys_prompt, cfg)
        elif provider_name == "together":
            return await self._call_together(prompt, sys_prompt, cfg)
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
        # Last resort: try Ollama directly
        if "ollama" not in [t.get("provider") for t in self._router_trace]:
            try:
                result = await self._call_provider("ollama", prompt, user_message, temp, max_tokens)
                self._router_trace.append({"provider": "ollama", "status": "success (last_resort)"})
                return result
            except Exception:
                pass
        return (
            "Şu an yapay zeka servislerine erişilemiyor.\n"
            "Çözüm: Dashboard → LLM sekmesinden provider ayarla "
            "veya terminalde 'elyan setup' komutunu çalıştır."
        )

    def get_last_router_trace(self) -> list:
        """Son router denemesinin izini döner."""
        return list(self._router_trace)

    def get_last_collaboration_trace(self) -> list:
        return list(self._collaboration_trace)

    async def chat(self, text: str, history: list = None, user_id: str = "local", system_prompt: str | None = None) -> str:
        """Kısa sohbet yanıtı üretir. cost_guard açıksa token bütçesini kısıtlar."""
        fast = self.fast_response.get_fast_response(text)
        if fast and fast.question_type == QuestionType.GREETING:
            answer = self._sanitize_chat_output(fast.answer)
            if answer:
                return answer
            return build_chat_fallback_message(language=str(elyan_config.get("agent.language", "tr") or "tr"))
        max_tokens = self._role_token_limit("chat")
        temp = 0.3
        system = str(system_prompt or self._chat_system_prompt()).strip()
        history_block = build_chat_history_block(history, max_pairs=4)
        prompt_parts = [system]
        if history_block:
            prompt_parts.append(history_block)
        prompt_parts.append(f"Kullanıcı: {text}")
        prompt = "\n\n".join(part for part in prompt_parts if part).strip()

        async def _call_once(prompt_text: str, *, temp_value: float = temp) -> str:
            token = _chat_system_prompt_override.set(system)
            try:
                patched = self.__dict__.get("_call_any_provider")
                if patched is not None:
                    return await patched(prompt_text, user_message=text, temp=temp_value, max_tokens=max_tokens)
                return await self._call_any_provider(prompt_text, user_message=text, temp=temp_value, max_tokens=max_tokens)
            finally:
                _chat_system_prompt_override.reset(token)

        try:
            raw = await _call_once(prompt)
        except Exception:
            raw = ""
        sanitized = self._sanitize_chat_output(raw)
        if sanitized and not chat_output_needs_retry(raw, sanitized_text=sanitized):
            return sanitized

        strict_system = (
            system
            + "\n\nSadece kısa, doğal ve tek paragraf bir cevap ver. JSON, tablo, kod bloğu, plan ve meta açıklama yazma."
        )
        strict_parts = [strict_system]
        if history_block:
            strict_parts.append(history_block)
        strict_parts.append(f"Kullanıcı: {text}")
        strict_prompt = "\n\n".join(part for part in strict_parts if part).strip()
        try:
            retry_raw = await _call_once(strict_prompt, temp_value=min(temp, 0.2))
        except Exception:
            retry_raw = ""
        retry_sanitized = self._sanitize_chat_output(retry_raw)
        if retry_sanitized and not chat_output_needs_retry(retry_raw, sanitized_text=retry_sanitized):
            return retry_sanitized

        contextual = self._build_contextual_chat_reply(text, history)
        if contextual:
            return contextual

        return build_chat_fallback_message(language=str(elyan_config.get("agent.language", "tr") or "tr"))

    def _build_contextual_chat_reply(self, text: str, history: list | None = None) -> str | None:
        low = str(text or "").lower()
        followup_markers = (
            "hangi alanlarda",
            "hangi alanlarda mesela",
            "mesela",
            "örnek",
            "ornek",
            "birkaç örnek",
            "bir kac ornek",
            "biraz daha",
            "detay",
            "nasıl yani",
            "nasil yani",
            "ne gibi",
            "nerelerde",
        )
        if not any(marker in low for marker in followup_markers):
            return None

        last_user = ""
        last_assistant = ""
        for item in reversed(history or []):
            if not isinstance(item, dict):
                continue
            last_user = str(item.get("user_message") or item.get("user") or "").strip()
            last_assistant = str(item.get("bot_response") or item.get("assistant_message") or item.get("response") or "").strip()
            if last_user or last_assistant:
                break

        seed = " ".join(part for part in (last_user, last_assistant, str(text or "").strip()) if part).strip()
        if not seed:
            return None

        seed_norm = normalize_turkish_text(seed)
        if any(k in seed_norm for k in ("yapay zeka", "ai", "machine learning", "makine ogrenmesi", "makine öğrenmesi")):
            return (
                "Örneğin sağlık, eğitim, finans, müşteri hizmetleri, ulaşım, üretim ve yazılım geliştirmede kullanılıyor. "
                "İstersen bunlardan birini seçip kısa örneklerle açayım."
            )

        if any(k in low for k in ("hangi alan", "nerede", "nerelerde", "örnek", "ornek")):
            return "Örneğin sağlık, eğitim, finans, müşteri hizmetleri ve yazılım geliştirme gibi alanlarda kullanılıyor. İstersen tek tek örnekleyeyim."
        return None
