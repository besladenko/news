import asyncio

async def periodic_task(func, interval_sec: int):
    while True:
        await func()
        await asyncio.sleep(interval_sec)

# Пример использования:
# await periodic_task(refresh_gigachat_token, 3600)
