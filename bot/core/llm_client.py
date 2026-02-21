import httpx
import json
import asyncio
from typing import Any, Optional
from config.elyan_config import elyan_config
from core.model_orchestrator import model_orchestrator
from core.neural_router import neural_router
from .llm_cache import get_cache
from .intent_parser import IntentParser
from .intent_classifier import get_classifier
from .llm_optimizer import get_llm_optimizer
from .pricing_tracker import get_pricing_tracker
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
        
        self.assistant_style = "professional_friendly_short"
        self._default_chat_prompt = (
            "Sen Elyan, son derece zeki, yetenekli ve yardımsever bir dijital asistansın. "
            "Kullanıcıya profesyonel, nazik ve çözüm odaklı yanıtlar ver. "
            "Gereksiz laf kalabalığından kaçın, doğrudan konuya gir. "
            "ASLA kullanıcıyı taklit etme (mirroring yapma). Kullanıcı ne derse desin, "
            "kendi kişiliğini ve asistan kimliğini koru. "
            "Eğer bir görev (dosya okuma, uygulama açma vb.) isteniyorsa ve bu bir sohbet mesajı değilse, "
            "görevi yapacağını belirten kısa bir onay ver. "
            "Sadece Türkçe konuş ve yanıtlarını Markdown formatında düzenle."
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

    async def generate(self, prompt: str, system_prompt: str = None, model_config: dict = None, role: str = "inference", history: list = None) -> str:
        # Use provided config or get best available based on role
        cfg = model_config or self.orchestrator.get_best_available(role)
        provider = cfg.get("type")
        
        if provider == "none":
            return "Hata: AI sağlayıcısı bulunamadı."
            
        # Default strong system instruction
        if not system_prompt:
            system_prompt = self._resolve_system_prompt()

        # Format history if provided
        history_context = ""
        if history:
            # history is list of dicts with user_message and bot_response
            formatted_history = []
            for h in history[-5:]: # Last 5 turns for context
                u = h.get("user_message", "")
                b = h.get("bot_response", "")
                if isinstance(b, str) and b.startswith('{'):
                    try:
                        b_data = json.loads(b)
                        b = b_data.get("message", "")
                    except: pass
                elif isinstance(b, dict):
                    b = b.get("message", "")
                
                formatted_history.append(f"Kullanıcı: {u}\nElyan: {b}")
            history_context = "\n".join(formatted_history)

        full_prompt = prompt
        if history_context:
            full_prompt = f"Geçmiş Konuşma:\n{history_context}\n\nŞu anki Mesaj: {prompt}"

        logger.info(f"Generating with {provider} (role: {role})...")
        
        try:
            if provider == "ollama":
                # Ollama can handle history in prompt or as a separate 'system' field
                return await self._call_ollama(full_prompt, system_prompt, cfg)
            elif provider == "openai":
                return await self._call_openai(prompt, system_prompt, cfg, history)
            elif provider == "groq":
                return await self._call_groq(prompt, system_prompt, cfg, history)
            elif provider == "gemini" or provider == "google":
                return await self._call_gemini(prompt, system_prompt, cfg, history)
        except Exception as e:
            logger.error(f"Generation error with {provider}: {e}")
            return f"Hata: {provider} yanıt vermedi. {str(e)}"
        
        return "Bilinmeyen hata"

    async def _call_ollama(self, prompt: str, system_prompt: str, cfg: dict) -> str:
        model = cfg.get("model", "llama3.1:8b")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("http://localhost:11434/api/generate", json={
                "model": model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False
            })
            return resp.json().get("response", "")

    async def _call_openai(self, prompt: str, system_prompt: str, cfg: dict, history: list = None) -> str:
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
        resp = await client.chat.completions.create(model=cfg.get("model", "gpt-4o"), messages=messages)
        return resp.choices[0].message.content

    async def _call_groq(self, prompt: str, system_prompt: str, cfg: dict, history: list = None) -> str:
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
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers,
                                    json={"model": cfg.get("model", "llama-3.3-70b-versatile"), "messages": messages})
            return resp.json()['choices'][0]['message']['content']

    async def _call_gemini(self, prompt: str, system_prompt: str, cfg: dict, history: list = None) -> str:
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
