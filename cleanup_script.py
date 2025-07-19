import os
import shutil
from loguru import logger

# Настройка логирования для скрипта очистки
logger.remove()
logger.add(lambda msg: print(msg.strip()), colorize=True, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

def clean_python_cache(root_dir: str):
    """
    Удаляет директории __pycache__ и .pyc файлы.
    """
    logger.info(f"Начало очистки кэша Python в директории: {root_dir}")
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Удаление директорий __pycache__
        if '__pycache__' in dirnames:
            cache_path = os.path.join(dirpath, '__pycache__')
            shutil.rmtree(cache_path)
            logger.info(f"Удалена директория: {cache_path}")
        
        # Удаление .pyc файлов
        for filename in filenames:
            if filename.endswith('.pyc'):
                pyc_path = os.path.join(dirpath, filename)
                os.remove(pyc_path)
                logger.info(f"Удален файл: {pyc_path}")
    logger.info("Очистка кэша Python завершена.")

def clean_virtual_environment(root_dir: str):
    """
    Удаляет директории виртуального окружения (.venv, venv).
    """
    logger.info(f"Начало очистки виртуального окружения в директории: {root_dir}")
    venv_dirs = ['.venv', 'venv']
    for venv_name in venv_dirs:
        venv_path = os.path.join(root_dir, venv_name)
        if os.path.exists(venv_path) and os.path.isdir(venv_path):
            try:
                shutil.rmtree(venv_path)
                logger.info(f"Удалено виртуальное окружение: {venv_path}")
            except Exception as e:
                logger.error(f"Ошибка при удалении виртуального окружения {venv_path}: {e}")
        else:
            logger.info(f"Виртуальное окружение '{venv_name}' не найдено.")
    logger.info("Очистка виртуального окружения завершена.")

def clean_media_downloads(root_dir: str, media_dir_name: str = "media_downloads"):
    """
    Удаляет директорию с загруженными медиафайлами.
    """
    logger.info(f"Начало очистки директории медиафайлов: {media_dir_name}")
    media_path = os.path.join(root_dir, media_dir_name)
    if os.path.exists(media_path) and os.path.isdir(media_path):
        try:
            shutil.rmtree(media_path)
            logger.info(f"Удалена директория медиафайлов: {media_path}")
        except Exception as e:
            logger.error(f"Ошибка при удалении директории медиафайлов {media_path}: {e}")
    else:
        logger.info(f"Директория медиафайлов '{media_dir_name}' не найдена.")
    logger.info("Очистка директории медиафайлов завершена.")

def clean_log_files(root_dir: str, log_file_name: str = "file.log"):
    """
    Удаляет файл логов.
    """
    logger.info(f"Начало очистки файла логов: {log_file_name}")
    log_path = os.path.join(root_dir, log_file_name)
    if os.path.exists(log_path) and os.path.isfile(log_path):
        try:
            os.remove(log_path)
            logger.info(f"Удален файл логов: {log_path}")
        except Exception as e:
            logger.error(f"Ошибка при удалении файла логов {log_path}: {e}")
    else:
        logger.info(f"Файл логов '{log_file_name}' не найден.")
    logger.info("Очистка файла логов завершена.")

def main():
    current_dir = os.getcwd()
    logger.info(f"Скрипт очистки запущен из: {current_dir}")

    print("\nВыберите, что вы хотите очистить:")
    print("1. Кэш Python (__pycache__, .pyc)")
    print("2. Виртуальное окружение (.venv, venv)")
    print("3. Загруженные медиафайлы (media_downloads)")
    print("4. Файл логов (file.log)")
    print("5. Все вышеперечисленное")
    print("0. Выход")

    choice = input("Введите номер опции: ")

    if choice == '1':
        clean_python_cache(current_dir)
    elif choice == '2':
        clean_virtual_environment(current_dir)
    elif choice == '3':
        clean_media_downloads(current_dir)
    elif choice == '4':
        clean_log_files(current_dir)
    elif choice == '5':
        clean_python_cache(current_dir)
        clean_virtual_environment(current_dir)
        clean_media_downloads(current_dir)
        clean_log_files(current_dir)
    elif choice == '0':
        logger.info("Очистка отменена.")
    else:
        logger.warning("Некорректный выбор. Пожалуйста, введите число от 0 до 5.")

    logger.info("Процесс очистки завершен.")

if __name__ == "__main__":
    main()
