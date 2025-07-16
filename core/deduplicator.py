# core/deduplicator.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Post, Duplicate
from loguru import logger
import re
from difflib import SequenceMatcher
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class Deduplicator:
    """
    Класс для определения дубликатов новостей.
    Использует текстовое совпадение и смысловой анализ (на основе TF-IDF и косинусного сходства).
    """
    def __init__(self, min_text_similarity: float = 0.8, min_semantic_similarity: float = 0.7):
        self.min_text_similarity = min_text_similarity
        self.min_semantic_similarity = min_semantic_similarity
        # Исправлено: TfidfVectorizer не поддерживает 'russian' напрямую.
        # Используем None, чтобы не удалять стоп-слова,
        # или можно предоставить свой список русских стоп-слов.
        self.tfidf_vectorizer = TfidfVectorizer(stop_words=None, max_features=5000)
        self.corpus_fitted = False

    def _preprocess_text(self, text: str) -> str:
        """Очищает текст для сравнения: приводит к нижнему регистру, удаляет пунктуацию и лишние пробелы."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text) # Удаляем все, кроме букв, цифр и пробелов
        text = re.sub(r'\s+', ' ', text).strip() # Заменяем множественные пробелы на один
        return text

    def _get_text_similarity(self, text1: str, text2: str) -> float:
        """Вычисляет текстовое сходство двух строк с помощью SequenceMatcher."""
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1, text2).ratio()

    async def _get_semantic_similarity(self, texts: list[str]) -> np.ndarray:
        """
        Вычисляет косинусное сходство между текстами на основе TF-IDF.
        Возвращает матрицу сходства.
        """
        if not texts:
            return np.array([[]])

        # Если корпус еще не был обучен, обучаем его
        if not self.corpus_fitted:
            logger.info("Обучение TF-IDF векторизатора на корпусе текстов...")
            self.tfidf_vectorizer.fit(texts)
            self.corpus_fitted = True
            logger.info("TF-IDF векторизатор обучен.")

        # Преобразуем тексты в TF-IDF векторы
        tfidf_matrix = self.tfidf_vectorizer.transform(texts)

        # Вычисляем косинусное сходство
        cosine_sim = cosine_similarity(tfidf_matrix)
        return cosine_sim

    async def check_for_duplicates(self, db_session: AsyncSession, new_post_text: str, city_id: int) -> tuple[bool, str | None]:
        """
        Проверяет, является ли новый пост дубликатом уже существующих постов в данном городе.
        :param db_session: Сессия базы данных.
        :param new_post_text: Текст нового поста.
        :param city_id: ID городского канала, для которого проверяется дубликат.
        :return: Кортеж (is_duplicate, reason), где reason - причина дублирования.
        """
        preprocessed_new_text = self._preprocess_text(new_post_text)
        if not preprocessed_new_text:
            logger.warning("Пустой текст нового поста для дедупликации.")
            return False, None

        # Получаем последние N постов для сравнения (например, за последние 24 часа или 100 постов)
        # Для простоты пока возьмем все посты для данного города, которые не были дубликатами
        stmt = select(Post).where(
            Post.city_id == city_id,
            Post.is_duplicate == False,
            Post.status.in_(['published', 'approved']) # Сравниваем только с опубликованными/одобренными
        ).order_by(Post.created_at.desc()).limit(100) # Ограничиваем количество для производительности

        result = await db_session.execute(stmt)
        existing_posts = result.scalars().all()

        if not existing_posts:
            logger.info(f"Нет существующих постов для сравнения в городе {city_id}.")
            return False, None

        # Собираем тексты для TF-IDF
        texts_to_compare = [self._preprocess_text(post.original_text) for post in existing_posts]
        texts_to_compare.append(preprocessed_new_text) # Добавляем новый текст в корпус

        # Вычисляем семантическое сходство
        semantic_similarities = await self._get_semantic_similarity(texts_to_compare)

        # Сравниваем новый пост (последний в списке `texts_to_compare`) с существующими
        new_post_semantic_vector_idx = len(texts_to_compare) - 1

        for i, existing_post in enumerate(existing_posts):
            preprocessed_existing_text = self._preprocess_text(existing_post.original_text)

            # 1. Проверка на текстовое совпадение
            text_similarity = self._get_text_similarity(preprocessed_new_text, preprocessed_existing_text)
            if text_similarity >= self.min_text_similarity:
                logger.info(f"Обнаружен дубликат по текстовому совпадению (сходство: {text_similarity:.2f})")
                await self._record_duplicate(db_session, existing_post.id, None, "text_match") # ID нового поста пока неизвестен
                return True, "text_match"

            # 2. Проверка на смысловое совпадение (если тексты достаточно длинные)
            # Убедимся, что индексы корректны для semantic_similarities
            if semantic_similarities.shape[0] > i and semantic_similarities.shape[1] > new_post_semantic_vector_idx:
                semantic_similarity = semantic_similarities[new_post_semantic_vector_idx, i]
                if semantic_similarity >= self.min_semantic_similarity:
                    logger.info(f"Обнаружен дубликат по смысловому совпадению (сходство: {semantic_similarity:.2f})")
                    await self._record_duplicate(db_session, existing_post.id, None, "semantic_match") # ID нового поста пока неизвестен
                    return True, "semantic_match"

        logger.info("Дубликатов не найдено.")
        return False, None

    async def _record_duplicate(self, db_session: AsyncSession, original_post_id: int, duplicate_post_id: int | None, reason: str):
        """
        Записывает информацию о найденном дубликате в базу данных.
        duplicate_post_id может быть None, если пост еще не сохранен.
        """
        duplicate_entry = Duplicate(
            original_post_id=original_post_id,
            duplicate_post_id=duplicate_post_id, # Будет обновлен позже, если пост будет сохранен
            reason=reason
        )
        db_session.add(duplicate_entry)
        await db_session.commit()
        logger.info(f"Запись о дубликате добавлена: оригинал={original_post_id}, дубликат={duplicate_post_id}, причина={reason}")

# Создаем глобальный экземпляр дедупликатора
deduplicator = Deduplicator()

if __name__ == "__main__":
    # Пример использования (требуется запущенная БД и init_db)
    from db.database import get_session, init_db
    import asyncio

    async def test_deduplicator():
        await init_db() # Убедитесь, что таблицы созданы

        async for session in get_session():
            # Создаем тестовые посты
            city_id = 1 # Предполагаем, что город с ID 1 существует
            await session.merge(Post(
                original_text="Сегодня в городе открылся новый парк, это замечательное место для отдыха.",
                status="published",
                city_id=city_id,
                donor_channel_id=1 # Предполагаем, что донор с ID 1 существует
            ))
            await session.merge(Post(
                original_text="Вчера был сильный дождь, но сегодня погода улучшилась.",
                status="published",
                city_id=city_id,
                donor_channel_id=1
            ))
            await session.commit()

            # Тестовые случаи
            new_text1 = "Сегодня в городе открылся новый парк, это чудесное место для отдыха." # Смысловой дубликат
            new_text2 = "Сегодня в городе открылся новый парк, это замечательное место для отдыха." # Текстовый дубликат
            new_text3 = "Вчера был сильный ливень, но сегодня выглянуло солнце." # Смысловой дубликат
            new_text4 = "Завтра ожидается повышение температуры до +30 градусов." # Не дубликат

            is_dup1, reason1 = await deduplicator.check_for_duplicates(session, new_text1, city_id)
            logger.info(f"'{new_text1[:30]}...' - Дубликат? {is_dup1}, Причина: {reason1}")

            is_dup2, reason2 = await deduplicator.check_for_duplicates(session, new_text2, city_id)
            logger.info(f"'{new_text2[:30]}...' - Дубликат? {is_dup2}, Причина: {reason2}")

            is_dup3, reason3 = await deduplicator.check_for_duplicates(session, new_text3, city_id)
            logger.info(f"'{new_text3[:30]}...' - Дубликат? {is_dup3}, Причина: {reason3}")

            is_dup4, reason4 = await deduplicator.check_for_duplicates(session, new_text4, city_id)
            logger.info(f"'{new_text4[:30]}...' - Дубликат? {is_dup4}, Причина: {reason4}")

    # Запускаем тест
    asyncio.run(test_deduplicator())
