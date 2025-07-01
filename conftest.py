# -*- coding: utf-8 -*-
import pytest
import os
from dotenv import load_dotenv
from db_manager import DatabaseManager
from main import app  # Импортируем наше FastAPI приложение
from httpx import AsyncClient
import asyncio
import psycopg2
from psycopg2 import Error

import pytest_asyncio # <--- ДОБАВЬТЕ ЭТУ СТРОКУ

# Загружаем переменные окружения из .env файла, если он существует
load_dotenv()


# --- Фикстуры для DatabaseManager (оставляем без изменений) ---

@pytest.fixture(scope="session")
def db_session_manager():
    """
    Фикстура для DatabaseManager с областью видимости "session".
    Используется для создания и удаления тестовой базы данных,
    а также для обеспечения одного подключения на всю тестовую сессию.
    """
    # Установим переменные окружения для тестовой БД.
    # Это гарантирует, что тесты используют именно тестовую БД,
    # а не продакшн или настроенную локально.
    os.environ['FSTR_DB_HOST'] = 'localhost'
    os.environ['FSTR_DB_PORT'] = '5432'
    os.environ['FSTR_DB_NAME'] = 'pereval_test_db'  # Отдельная тестовая БД!
    os.environ['FSTR_DB_LOGIN'] = 'postgres'
    os.environ['FSTR_DB_PASS'] = '111'

    db_manager = DatabaseManager()

    # Попытка подключиться и создать/очистить БД
    try:
        # Сначала подключаемся к общей базе данных (например, 'postgres')
        # для создания/удаления тестовой БД.
        temp_conn = psycopg2.connect(
            host=os.getenv('FSTR_DB_HOST'),
            port=os.getenv('FSTR_DB_PORT'),
            database='postgres',  # Подключаемся к системной БД для управления другими БД
            user=os.getenv('FSTR_DB_LOGIN'),
            password=os.getenv('FSTR_DB_PASS')
        )
        temp_conn.autocommit = True
        temp_cursor = temp_conn.cursor()

        # Проверяем, существует ли тестовая БД и удаляем ее, если да
        temp_cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{os.getenv('FSTR_DB_NAME')}';")
        if temp_cursor.fetchone():
            print(f"Удаление существующей тестовой базы данных: {os.getenv('FSTR_DB_NAME')}")
            temp_cursor.execute(f"DROP DATABASE {os.getenv('FSTR_DB_NAME')} WITH (FORCE);")

        # Создаем новую тестовую БД
        print(f"Создание новой тестовой базы данных: {os.getenv('FSTR_DB_NAME')}")
        temp_cursor.execute(f"CREATE DATABASE {os.getenv('FSTR_DB_NAME')};")

        temp_cursor.close()
        temp_conn.close()

        # Теперь подключаемся к созданной тестовой БД и применяем схему
        db_manager.connect()
        with open('schema.sql', 'r') as f:
            schema_sql = f.read()
        db_manager.cursor.execute(schema_sql)
        db_manager.connection.commit()
        print("Схема БД успешно применена.")

        yield db_manager  # Предоставляем DatabaseManager тестам

    except Error as e:
        print(f"Критическая ошибка при настройке тестовой БД: {e}")
        raise
    finally:
        # Закрытие соединения после завершения всех тестов сессии
        if db_manager.connection:
            db_manager.disconnect()  # Закрываем соединение DatabaseManager

        # Повторно подключаемся к системной БД для удаления тестовой
        try:
            temp_conn = psycopg2.connect(
                host=os.getenv('FSTR_DB_HOST'),
                port=os.getenv('FSTR_DB_PORT'),
                database='postgres',
                user=os.getenv('FSTR_DB_LOGIN'),
                password=os.getenv('FSTR_DB_PASS')
            )
            temp_conn.autocommit = True
            temp_cursor = temp_conn.cursor()
            print(f"Очистка: Удаление тестовой базы данных: {os.getenv('FSTR_DB_NAME')}")
            temp_cursor.execute(f"DROP DATABASE IF EXISTS {os.getenv('FSTR_DB_NAME')} WITH (FORCE);")
            temp_cursor.close()
            temp_conn.close()
        except Error as e:
            print(f"Ошибка при очистке тестовой БД: {e}")


@pytest.fixture(scope="function")
def db_manager_for_tests(db_session_manager):
    """
    Фикстура для DatabaseManager с областью видимости "function".
    Использует session-scoped db_session_manager для подключения.
    Очищает таблицу pereval_added перед каждым тестом.
    """
    db = db_session_manager
    # Убедимся, что соединение активно перед тестом
    if not db.connect():
        print("Соединение или курсор неактивны в фикстуре, пытаемся переподключиться...")
        # Если не удалось переподключиться, это критическая ошибка
        if not db.connect():
            raise Exception("Не удалось восстановить соединение с базой данных для тестов.")

    # Очищаем таблицу перед каждым тестом
    db.cursor.execute("TRUNCATE TABLE pereval_added RESTART IDENTITY CASCADE;")
    db.connection.commit()
    yield db  # Предоставляем экземпляр DatabaseManager
    # После теста таблица будет очищена снова, когда следующий тест вызовет фикстуру


# --- Фикстуры для FastAPI асинхронных тестов ---

@pytest_asyncio.fixture(scope="function") # <--- ИЗМЕНЕНА ЭТА СТРОКА
async def ac_client():
    """
    Асинхронный HTTP клиент для тестирования FastAPI приложения.
    Использует httpx.AsyncClient.
    """
    # Убедимся, что DatabaseManager в main.py использует тестовые переменные окружения.
    # Эти переменные окружения уже установлены в db_session_manager выше.
    # FastAPI приложение будет использовать их при инициализации.

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client