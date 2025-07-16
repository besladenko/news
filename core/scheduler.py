# core/scheduler.py
import asyncio
from loguru import logger
from typing import Callable, Coroutine, Awaitable

class Scheduler:
    """
    Простой асинхронный планировщик для выполнения задач по расписанию.
    """
    def __init__(self):
        self._tasks = []
        self._running = False

    def add_task(self, coro_factory: Callable[[], Coroutine[any, any, Awaitable[any]]], interval_seconds: int, name: str = None):
        """
        Добавляет асинхронную задачу для периодического выполнения.
        :param coro_factory: Функция (фабрика), которая возвращает корутину, которую нужно выполнять.
                             Например: `lambda: my_async_function()` или просто `my_async_function`
        :param interval_seconds: Интервал выполнения в секундах.
        :param name: Опциональное имя задачи для логирования.
        """
        task_name = name if name else coro_factory.__name__
        self._tasks.append({"coro_factory": coro_factory, "interval": interval_seconds, "name": task_name})
        logger.info(f"Задача '{task_name}' добавлена в планировщик с интервалом {interval_seconds} секунд.")

    async def _run_task(self, coro_factory: Callable[[], Coroutine[any, any, Awaitable[any]]], interval: int, name: str):
        """Внутренняя функция для выполнения одной задачи."""
        while self._running:
            try:
                logger.info(f"Выполнение задачи '{name}'...")
                await coro_factory() # Call the factory to get a new coroutine object
                logger.info(f"Задача '{name}' выполнена.")
            except asyncio.CancelledError:
                logger.warning(f"Задача '{name}' отменена.")
                break
            except Exception as e:
                logger.error(f"Ошибка при выполнении задачи '{name}': {e}")
            await asyncio.sleep(interval)

    async def start(self):
        """Запускает все запланированные задачи."""
        if self._running:
            logger.warning("Планировщик уже запущен.")
            return

        logger.info("Запуск планировщика...")
        self._running = True
        for task_info in self._tasks:
            asyncio.create_task(self._run_task(task_info["coro_factory"], task_info["interval"], task_info["name"]))
        logger.info(f"Планировщик запущен. Запущено {len(self._tasks)} задач.")

    async def stop(self):
        """Останавливает все запланированные задачи."""
        if not self._running:
            logger.warning("Планировщик не запущен.")
            return

        logger.info("Остановка планировщика...")
        self._running = False
        # Даем время на завершение текущих итераций задач
        await asyncio.sleep(1) # Небольшая задержка
        # Можно добавить более сложную логику отмены задач, если нужно
        logger.info("Планировщик остановлен.")

# Создаем глобальный экземпляр планировщика
scheduler = Scheduler()

if __name__ == "__main__":
    # Пример использования планировщика
    async def periodic_task_1():
        logger.info("Выполняется периодическая задача 1...")
        await asyncio.sleep(0.5)

    async def periodic_task_2():
        logger.info("Выполняется периодическая задача 2...")
        await asyncio.sleep(0.2)

    async def main():
        scheduler.add_task(periodic_task_1, 3, "Задача 1") # Каждые 3 секунды
        scheduler.add_task(periodic_task_2, 5, "Задача 2") # Каждые 5 секунд

        await scheduler.start()
        logger.info("Планировщик запущен. Для остановки нажмите Ctrl+C...")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Получен сигнал KeyboardInterrupt. Остановка...")
        finally:
            await scheduler.stop()
            logger.info("Приложение завершено.")

    asyncio.run(main())
