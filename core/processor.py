import re

def clean_mask_from_text(text: str, mask: str) -> str:
    """
    Удаляет маску из конца текста, даже если там есть эмодзи/разделители/лишние табы
    """
    if not text or not mask:
        return text.strip()
    # Готовим паттерн: ищем маску в самом конце, с любыми табами/разделителями до неё
    mask_escaped = re.escape(mask.strip())
    pattern = re.compile(rf"[\n\t ]*{mask_escaped}[\n\t ]*$", flags=re.DOTALL)
    cleaned = pattern.sub("", text).strip()
    return cleaned

def process_post(text: str, donor) -> str:
    """
    Основная функция для очистки поста: убирает подпись-маску, режет лишнее.
    """
    mask = donor.mask_pattern if hasattr(donor, "mask_pattern") else None
    if mask:
        text = clean_mask_from_text(text, mask)
    return text.strip()
