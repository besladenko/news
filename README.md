# SetiNews

Автоматизированная городская новостная сеть для Telegram.

## Запуск

1. Установить зависимости:
    ```
    pip install -r requirements.txt
    ```

2. Подготовить `.env` с настройками (пример см. в репозитории).

3. Запустить проект:
    ```
    python main.py
    ```

## Архитектура

- **Парсер** — Telethon
- **Боты** — aiogram 3.x
- **Фильтрация** — TF-IDF + regex
- **LLM** — интеграция с GigaChat/Dummy

## Команды

- `/addcity <link>`
- `/adddonor <city_id> <link> [mask]`
- `/pending`
- `/publish <post_id>`

## Структура БД

- **City** — городской канал
- **DonorChannel** — канал-доnor
- **Post** — новостной пост
- **Admin** — админ
