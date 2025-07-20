# llm.py

class DummyLLM:
    async def detect_ads(self, text: str) -> bool:
        return False  # Имитация — всегда не реклама

    async def paraphrase(self, text: str) -> str:
        return text

gigachat = DummyLLM()
