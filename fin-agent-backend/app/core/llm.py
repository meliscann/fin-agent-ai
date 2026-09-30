"""
Birleşik LLM istemcisi.
LLM_PROVIDER=groq  → Groq API (geliştirme/test)
LLM_PROVIDER=gemini → Gemini API (final teslim)

Kullanım:
    from app.core.llm import llm
    response = await llm.chat("Portföyümü analiz et", system="Sen bir yatırım asistanısın.")
"""

from app.config import settings


class LLMClient:
    def __init__(self):
        self.provider = settings.llm_provider
        self._client = None

    def _get_groq_client(self):
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=settings.groq_api_key)
        return self._client

    def _get_gemini_model(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            self._client = genai.GenerativeModel(settings.gemini_model)
        return self._client

    async def chat(
        self,
        user_message: str,
        system: str = "Sen Türk yatırım piyasaları konusunda uzman bir finansal asistansın.",
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> str:
        """
        Tek turlu sohbet tamamlama.
        Her iki sağlayıcı için aynı arayüz.
        """
        if self.provider == "groq":
            return await self._groq_chat(user_message, system, temperature, max_tokens)
        return await self._gemini_chat(user_message, system, temperature, max_tokens)

    async def chat_with_history(
        self,
        messages: list[dict],
        system: str = "Sen Türk yatırım piyasaları konusunda uzman bir finansal asistansın.",
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> str:
        """
        Çok turlu sohbet — mesaj geçmişiyle.
        messages: [{"role": "user"/"assistant", "content": "..."}]
        """
        if self.provider == "groq":
            return await self._groq_chat_history(messages, system, temperature, max_tokens)
        return await self._gemini_chat_history(messages, system, temperature, max_tokens)

    # ── Groq ──────────────────────────────────────────────────────────────────

    async def _groq_chat(self, user_message, system, temperature, max_tokens) -> str:
        import asyncio
        client = self._get_groq_client()

        def _sync_call():
            response = client.chat.completions.create(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content

        return await asyncio.to_thread(_sync_call)

    async def _groq_chat_history(self, messages, system, temperature, max_tokens) -> str:
        import asyncio
        client = self._get_groq_client()

        def _sync_call():
            full_messages = [{"role": "system", "content": system}] + messages
            response = client.chat.completions.create(
                model=settings.groq_model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content

        return await asyncio.to_thread(_sync_call)

    # ── Gemini ────────────────────────────────────────────────────────────────

    async def _gemini_chat(self, user_message, system, temperature, max_tokens) -> str:
        import asyncio
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=system,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        def _sync_call():
            response = model.generate_content(user_message)
            return response.text

        return await asyncio.to_thread(_sync_call)

    async def _gemini_chat_history(self, messages, system, temperature, max_tokens) -> str:
        import asyncio
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=system,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        # Gemini mesaj formatına dönüştür
        gemini_history = []
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        def _sync_call():
            chat = model.start_chat(history=gemini_history)
            last_user_msg = messages[-1]["content"]
            response = chat.send_message(last_user_msg)
            return response.text

        return await asyncio.to_thread(_sync_call)


# Singleton — tüm uygulama bu instance'ı kullanır
llm = LLMClient()
