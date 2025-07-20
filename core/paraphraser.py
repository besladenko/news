from infra.gigachat_api import llm

async def paraphrase_text(text: str) -> str:
    return await llm.paraphrase(text)
