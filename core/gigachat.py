# core/gigachat.py
import httpx
import asyncio
import time
from loguru import logger
from config import config

class GigaChatAPI:
    """
    Класс для взаимодействия с GigaChat API.
    Обрабатывает получение и обновление access_token.
    """
    def __init__(self):
        self.client_id = config.GIGACHAT_CLIENT_ID
        self.client_secret = config.GIGACHAT_CLIENT_SECRET
        self.auth_key = config.GIGACHAT_AUTH_KEY
        self.scope = config.GIGACHAT_SCOPE
        self.rquuid = config.RQUUID
        self.token_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        self.chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        self.access_token = None
        self.token_expires_at = 0
        self.http_client = httpx.AsyncClient(verify=False) # verify=False для самоподписанных сертификатов, в продакшене использовать True

    async def _get_access_token(self):
        """Получает новый access_token от GigaChat API."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": self.rquuid,
            "Authorization": f"Basic {self.auth_key}"
        }
        data = {
            "scope": self.scope
        }
        try:
            logger.info("Запрос нового access_token для GigaChat...")
            response = await self.http_client.post(self.token_url, headers=headers, data=data, timeout=10)
            response.raise_for_status() # Вызывает исключение для статусов 4xx/5xx
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_at") # GigaChat возвращает expires_at в миллисекундах
            self.token_expires_at = expires_in / 1000 # Переводим в секунды
            logger.info(f"Access_token GigaChat получен. Истекает в: {self.token_expires_at}")
            return self.access_token
        except httpx.RequestError as e:
            logger.error(f"Ошибка запроса токена GigaChat: {e}")
            self.access_token = None
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка HTTP статуса при получении токена GigaChat: {e.response.status_code} - {e.response.text}")
            self.access_token = None
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при получении токена GigaChat: {e}")
            self.access_token = None
            return None

    async def get_token(self):
        """Возвращает текущий access_token, обновляя его при необходимости."""
        # Проверяем, если токен отсутствует или истекает менее чем через 5 минут (300 секунд)
        if not self.access_token or self.token_expires_at - time.time() < 300:
            await self._get_access_token()
        return self.access_token

    async def _make_chat_request(self, payload: dict, retries: int = 3, backoff_factor: float = 1.0):
        """
        Внутренний метод для выполнения запросов к GigaChat API с ретраями и экспоненциальной задержкой.
        """
        for attempt in range(retries):
            token = await self.get_token()
            if not token:
                logger.error("Не удалось получить access_token для GigaChat для выполнения запроса.")
                return None

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}"
            }

            try:
                logger.info(f"Отправка запроса в GigaChat (попытка {attempt + 1}/{retries}): {payload['messages'][0]['content'][:50]}...")
                response = await self.http_client.post(self.chat_url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                response_data = response.json()
                if response_data and response_data.get("choices"):
                    generated_text = response_data["choices"][0]["message"]["content"]
                    logger.info(f"GigaChat ответ получен: {generated_text[:50]}...")
                    return generated_text
                else:
                    logger.warning(f"Неожиданный формат ответа от GigaChat: {response_data}")
                    return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429: # Too Many Requests
                    wait_time = backoff_factor * (2 ** attempt)
                    logger.warning(f"Получен 429 Too Many Requests от GigaChat. Повторная попытка через {wait_time:.2f} секунд...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Ошибка HTTP статуса от GigaChat API: {e.response.status_code} - {e.response.text}")
                    return None
            except httpx.RequestError as e:
                logger.error(f"Ошибка запроса к GigaChat API: {e}")
                return None
            except Exception as e:
                logger.error(f"Неизвестная ошибка при работе с GigaChat API: {e}")
                return None
        logger.error(f"Все {retries} попыток запроса к GigaChat API провалились.")
        return None

    async def generate_text(self, prompt: str, model: str = "GigaChat:latest"):
        """
        Отправляет запрос на генерацию текста в GigaChat API.
        :param prompt: Текст запроса для генерации.
        :param model: Модель GigaChat для использования.
        :return: Сгенерированный текст или None в случае ошибки.
        """
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "top_p": 0.9,
            "n": 1,
            "stream": False,
            "max_tokens": 500 # Ограничение на количество токенов в ответе
        }
        return await self._make_chat_request(payload)

    async def check_advertisement(self, text: str) -> bool:
        """
        Проверяет текст на рекламный характер с помощью GigaChat.
        :param text: Текст для проверки.
        :return: True, если текст рекламный, False иначе.
        """
        prompt = f"Является ли следующий текст рекламным? Ответь только 'Да' или 'Нет'.\n\nТекст: {text}"
        response = await self.generate_text(prompt)
        if response:
            return "да" in response.lower()
        return False

    async def rephrase_text(self, text: str) -> str:
        """
        Переформулирует текст без потери смысла с помощью GigaChat.
        :param text: Текст для переформулирования.
        :return: Переформулированный текст.
        """
        prompt = f"Переформулируй следующий текст, сохранив его смысл, но изменив формулировки и структуру предложений. Ответь только переформулированным текстом, без лишних слов.\n\nТекст: {text}"
        response = await self.generate_text(prompt)
        return response if response else text # Возвращаем оригинал, если переформулировать не удалось

# Создаем глобальный экземпляр GigaChatAPI
gigachat_api = GigaChatAPI()

if __name__ == "__main__":
    async def test_gigachat():
        # Тест получения токена
        token = await gigachat_api.get_token()
        if token:
            logger.info(f"Тестовый токен получен: {token[:10]}...")

        # Тест проверки на рекламу
        ad_text = "Купите наш новый продукт! Лучшее предложение на рынке, скидки только сегодня!"
        not_ad_text = "На улице сегодня солнечно, температура воздуха +25 градусов."
        is_ad = await gigachat_api.check_advertisement(ad_text)
        is_not_ad = await gigachat_api.check_advertisement(not_ad_text)
        logger.info(f"'{ad_text[:30]}...' - Реклама? {is_ad}")
        logger.info(f"'{not_ad_text[:30]}...' - Реклама? {is_not_ad}")

        # Тест переформулирования
        original_text = "Сегодня в городе произошло важное событие: открылся новый парк для отдыха горожан. Это прекрасное место для прогулок и активного времяпровождения."
        rephrased_text = await gigachat_api.rephrase_text(original_text)
        logger.info(f"Оригинальный текст:\n{original_text}")
        logger.info(f"Переформулированный текст:\n{rephrased_text}")

    asyncio.run(test_gigachat())
