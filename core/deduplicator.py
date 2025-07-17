# core/deduplicator.py
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from loguru import logger
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func
import datetime

from config import config
# from db.database import get_session # <-- Original line: Removed direct import
import db.database # <-- Changed: Import the module instead
from db.models import Post, Duplicate # Импортируем Post и Duplicate

class Deduplicator:
    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold
        # Инициализируем векторизатор без стоп-слов, так как они могут быть специфичны для языка
        # и могут быть не всегда актуальны для коротких новостных заголовков.
        # Если нужна поддержка стоп-слов, их можно передать явно: stop_words=stopwords.words('russian')
        # и импортировать NLTK
        self.vectorizer = TfidfVectorizer()
        self.corpus = [] # Список текстов, по которым обучен векторизатор
        self.post_ids = [] # Соответствующие ID постов

    async def _get_corpus_from_db(self, db_session: AsyncSession, city_id: int):
        """
        Загружает тексты опубликованных постов из БД для обучения векторизатора.
        """
        # Загружаем только опубликованные посты для сравнения
        stmt = select(Post.processed_text, Post.id).where(Post.city_id == city_id, Post.status == "published")
        result = await db_session.execute(stmt)
        posts_data = result.all()
        
        self.corpus = [post.processed_text for post in posts_data if post.processed_text]
        self.post_ids = [post.id for post in posts_data if post.processed_text]
        logger.info(f"Загружено {len(self.corpus)} опубликованных постов из БД для дедупликации в городе {city_id}.")

    async def _get_semantic_similarity(self, text1: str, text2: str) -> float:
        """
        Вычисляет косинусное сходство между двумя текстами.
        """
        if not text1 or not text2:
            return 0.0

        # Объединяем тексты для обучения векторизатора
        texts = [text1, text2]
        
        try:
            logger.info("Обучение TF-IDF векторизатора на корпусе текстов...")
            tfidf_matrix = self.vectorizer.fit_transform(texts)
            logger.info("TF-IDF векторизатор обучен.")
            
            # Вычисляем косинусное сходство
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(similarity)
        except Exception as e:
            logger.error(f"Ошибка при вычислении косинусного сходства: {e}")
            return 0.0

    async def check_for_duplicates(self, db_session: AsyncSession, new_text: str, city_id: int) -> tuple[bool, str]:
        """
        Проверяет новый текст на наличие дубликатов среди уже опубликованных постов.
        :param db_session: Асинхронная сессия базы данных.
        :param new_text: Новый текст для проверки.
        :param city_id: ID города, к которому относится пост.
        :return: Кортеж (is_duplicate: bool, reason: str).
        """
        await self._get_corpus_from_db(db_session, city_id)

        if not self.corpus:
            logger.info(f"Нет существующих постов для сравнения в городе {city_id}.")
            return False, "Нет опубликованных постов для сравнения."

        # Добавляем новый текст к корпусу для трансформации
        current_corpus = self.corpus + [new_text]
        
        try:
            # Переобучаем векторизатор на новом корпусе
            tfidf_matrix = self.vectorizer.fit_transform(current_corpus)
            
            # Вектор нового текста - это последний в матрице
            new_text_vector = tfidf_matrix[-1:]
            
            # Сравниваем новый текст со всеми существующими
            similarities = cosine_similarity(new_text_vector, tfidf_matrix[:-1])
            
            for i, sim in enumerate(similarities[0]):
                if sim >= self.similarity_threshold:
                    existing_post_id = self.post_ids[i]
                    logger.info(f"Обнаружен дубликат по текстовому совпадению (сходство: {sim:.2f})")
                    await self._record_duplicate(db_session, existing_post_id, None, "text_match") # ID нового поста пока неизвестен
                    return True, f"Текстовый дубликат (сходство: {sim:.2f})"
            
            return False, "Дубликатов не найдено."

        except Exception as e:
            logger.error(f"Ошибка при проверке на дубликаты: {e}")
            return False, f"Ошибка при дедупликации: {e}"

    async def _record_duplicate(self, db_session: AsyncSession, original_post_id: int, duplicate_post_id: int = None, reason: str = "text_match"):
        """
        Записывает информацию о найденном дубликате в БД.
        """
        new_duplicate = Duplicate(
            original_post_id=original_post_id,
            duplicate_post_id=duplicate_post_id, # Может быть None на первом этапе
            reason=reason,
            created_at=datetime.datetime.now()
        )
        db_session.add(new_duplicate)
        await db_session.commit() # Сохраняем сразу, чтобы получить ID для нового поста
        logger.info(f"Запись о дубликате создана: original_post_id={original_post_id}, duplicate_post_id={duplicate_post_id}")

# Создаем глобальный экземпляр дедупликатора
deduplicator = Deduplicator()

if __name__ == "__main__":
    async def test_deduplicator():
        logger.info("Запуск отладочного режима deduplicator.py...")
        
        # Пример использования с фиктивными данными
        # В реальном приложении session будет получен через get_session()
        class MockSession:
            def __init__(self):
                self.posts = []
                self.duplicates = []

            async def execute(self, stmt):
                # Имитация запроса к БД
                if "FROM posts" in str(stmt):
                    class MockResult:
                        def all(self):
                            return [
                                type('obj', (object,), {'processed_text': "Это первая новость о погоде.", 'id': 1}),
                                type('obj', (object,), {'processed_text': "Вчера был сильный дождь.", 'id': 2}),
                                type('obj', (object,), {'processed_text': "Открытие нового парка в городе.", 'id': 3}),
                            ]
                    return MockResult()
                return None

            def add(self, obj):
                if isinstance(obj, Duplicate):
                    self.duplicates.append(obj)
                else:
                    self.posts.append(obj)

            async def commit(self):
                logger.info("MockSession: commit called.")
                pass # В моке ничего не коммитим

            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_session = MockSession()

        # Тест: новый текст - дубликат
        new_text_duplicate = "Сегодня произошло открытие нового парка в нашем городе."
        is_dup, reason = await deduplicator.check_for_duplicates(mock_session, new_text_duplicate, 1)
        logger.info(f"'{new_text_duplicate[:30]}...' - Дубликат? {is_dup}, Причина: {reason}")
        
        # Тест: новый текст - не дубликат
        new_text_unique = "Ученые обнаружили новый вид бабочек в тропических лесах."
        is_dup, reason = await deduplicator.check_for_duplicates(mock_session, new_text_unique, 1)
        logger.info(f"'{new_text_unique[:30]}...' - Дубликат? {is_dup}, Причина: {reason}")

        logger.info("Дубликаты, записанные в MockSession:")
        for dup in mock_session.duplicates:
            logger.info(f"  Оригинал ID: {dup.original_post_id}, Дубликат ID: {dup.duplicate_post_id}, Причина: {dup.reason}")

    asyncio.run(test_deduplicator())
