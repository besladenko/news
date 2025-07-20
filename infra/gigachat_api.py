from config.settings import settings

class DummyLLM:
    async def paraphrase(self, text: str) -> str:
        # Простейшая заглушка — возвращает тот же текст
        return text

    async def detect_ads(self, text: str) -> bool:
        # Простейшая заглушка — никакой рекламы
        return False

llm = DummyLLM()

# Для реального GigaChat API здесь будет асинхронный запрос с токеном и т.д.
