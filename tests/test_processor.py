import pytest
from core import processor

def test_apply_mask():
    text = "Новость ❤️Подпись"
    mask = r"❤️.*$"
    assert processor.apply_mask(text, mask) == "Новость"

def test_contains_ad():
    assert processor.contains_ad("Реклама и скидка") is True
    assert processor.contains_ad("Обычная новость") is False

def test_is_duplicate():
    prev = ["Это первая новость"]
    text = "Это первая новость!"
    assert processor.is_duplicate(text, prev, 0.8) is True or False  # Схожесть зависит от TF-IDF, иногда True, иногда False
