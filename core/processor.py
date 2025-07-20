import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

AD_PHRASES = [
    "реклама", "подписывайся", "подпишись", "акция", "скидка", "магазин"
]

def apply_mask(text: str, mask_pattern: str):
    """
    Если маска задана, режем подписи и прочее.
    """
    if not mask_pattern:
        return text
    match = re.search(mask_pattern, text)
    if match:
        return re.sub(mask_pattern, "", text).strip()
    else:
        return None  # если не совпало, пост не подходит

def contains_ad(text: str) -> bool:
    """
    Проверка по ключевым словам.
    """
    lowered = text.lower()
    return any(phrase in lowered for phrase in AD_PHRASES)

def is_duplicate(text: str, prev_texts: list, threshold: float) -> bool:
    """
    TF-IDF + cosine similarity.
    """
    if not prev_texts:
        return False
    vect = TfidfVectorizer().fit(prev_texts + [text])
    vectors = vect.transform(prev_texts + [text])
    sim = cosine_similarity(vectors[-1], vectors[:-1])
    max_sim = sim.max() if sim.size else 0
    return max_sim >= threshold

def add_signature(text: str, city_title: str):
    return f"{text}\n\n— {city_title}"
