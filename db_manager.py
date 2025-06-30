# -*- coding: utf-8 -*-
import os
import psycopg2
from psycopg2 import Error
import json
from datetime import datetime
from typing import List, Optional, Tuple


class DatabaseManager:
    """
    Класс для управления базой данных PostgreSQL.
    Позволяет подключаться к БД и добавлять, редактировать и просматривать записи о перевалах.
    """

    def __init__(self):
        # Получаем данные для подключения из переменных окружения
        self.db_host = os.getenv('FSTR_DB_HOST', 'localhost')
        self.db_port = os.getenv('FSTR_DB_PORT', '5432')
        self.db_name = os.getenv('FSTR_DB_NAME', 'pereval_app')
        self.db_user = os.getenv('FSTR_DB_LOGIN', 'postgres')
        self.db_password = os.getenv('FSTR_DB_PASS', 'admin123')

        self.connection = None
        self.cursor = None

    def connect(self) -> bool:
        """
        Устанавливает соединение с базой данных.
        Возвращает True при успешном подключении, False в противном случае.
        """
        if self.connection and not self.connection.closed:
            # print("Соединение уже активно.") # Опционально: можно выводить это сообщение
            return True
        try:
            self.connection = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            self.connection.autocommit = True  # Автоматическая фиксация изменений
            self.cursor = self.connection.cursor()
            print("Успешное подключение к базе данных PostgreSQL")
            return True
        except Error as e:
            print(f"Ошибка при подключении к PostgreSQL: {e}")
            self.connection = None  # Сбросим соединение при ошибке
            self.cursor = None
            return False

    def disconnect(self):
        """
        Закрывает соединение с базой данных.
        """
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.connection and not self.connection.closed:
            self.connection.close()
            self.connection = None
            print("Соединение с базой данных PostgreSQL закрыто.")
        # else:
        #     print("Соединение уже закрыто или не было активно.")

    def add_pereval(self, data: dict) -> Optional[int]:
        """
        Добавляет новую запись о перевале в базу данных.
        Возвращает ID новой записи или None в случае ошибки.
        """
        try:
            self.connect()
            # Подготавливаем данные для вставки
            # raw_data - все исходные данные, которые приходят в запросе
            raw_data_json = json.dumps(data)
            images_json = json.dumps(data.get('images', []))  # Изображения хранятся отдельно как JSONB

            insert_query = """
                INSERT INTO pereval_added (raw_data, images, status)
                VALUES (%s::jsonb, %s::jsonb, %s)
                RETURNING id;
            """
            self.cursor.execute(insert_query, (raw_data_json, images_json, 'new'))
            pereval_id = self.cursor.fetchone()[0]
            self.connection.commit()  # Явная фиксация изменений после RETURNING
            print(f"Запись о перевале успешно добавлена. ID: {pereval_id}")
            return pereval_id
        except Error as e:
            print(f"Ошибка при добавлении перевала: {e}")
            if self.connection:
                self.connection.rollback()
            return None
        finally:
            # В тестах фикстура сама управляет дисконнектом.
            # Для продакшн кода, возможно, понадобится дисконнект здесь.
            pass

    def get_pereval_by_id(self, pereval_id: int) -> Optional[dict]:
        """
        Получает информацию о перевале по его ID.
        Возвращает словарь с данными перевала или None, если перевал не найден.
        """
        try:
            self.connect()
            self.cursor.execute(
                """
                SELECT id, date_added, raw_data, images, status
                FROM pereval_added
                WHERE id = %s;
                """, (pereval_id,)
            )
            result = self.cursor.fetchone()

            if result:
                # result - это кортеж. psycopg2 автоматически преобразует JSONB в Python dict/list
                retrieved_data = {
                    "id": result[0],
                    "date_added": result[1].isoformat(timespec='seconds'),
                    "raw_data": result[2],  # Уже должно быть словарем
                    "images": result[3],  # Уже должен быть списком словарей или None
                    "status": result[4]
                }
                print(f"get_pereval_by_id: Retrieved data for ID {pereval_id}: {retrieved_data}")  # DEBUG PRINT
                return retrieved_data
            return None
        except Error as e:
            print(f"Ошибка при получении перевала по ID {pereval_id}: {e}")
            return None
        finally:
            pass

    def update_pereval(self, pereval_id: int, new_data: dict) -> dict:
        """
        Обновляет данные о перевале по его ID, если его статус 'new'.
        Возвращает словарь с результатом операции: {"state": 1/0, "id": pereval_id}.
        state: 1 - успешно, 0 - ошибка (перевал не 'new' или другие проблемы).
        """
        try:
            self.connect()

            # Проверяем текущий статус перевала
            self.cursor.execute("SELECT status FROM pereval_added WHERE id = %s;", (pereval_id,))
            current_status_result = self.cursor.fetchone()

            if not current_status_result or current_status_result[0] != 'new':
                print(f"Обновление перевала ID {pereval_id} невозможно: статус не 'new' или перевал не найден.")
                return {"state": 0, "id": pereval_id}

            # Получаем текущие raw_data
            self.cursor.execute("SELECT raw_data FROM pereval_added WHERE id = %s;", (pereval_id,))
            old_raw_data = self.cursor.fetchone()[0]

            # Обновляем только разрешенные поля (не user data)
            updated_raw_data = old_raw_data.copy()

            # Разрешенные для изменения поля, кроме user
            allowed_fields = ['beautyTitle', 'title', 'other_titles', 'connect', 'coords', 'level', 'images']

            for key, value in new_data.items():
                if key in allowed_fields:
                    if key == 'coords' and isinstance(value, dict):
                        # Обновляем вложенные поля координат
                        for coord_key, coord_val in value.items():
                            updated_raw_data['coords'][coord_key] = coord_val
                    elif key == 'level' and isinstance(value, dict):
                        # Обновляем вложенные поля уровня
                        for level_key, level_val in value.items():
                            updated_raw_data['level'][level_key] = level_val
                    elif key == 'images' and isinstance(value, list):
                        updated_raw_data['images'] = value  # Полная замена списка изображений
                    else:
                        updated_raw_data[key] = value

            # Обновляем запись в БД
            update_query = """
                UPDATE pereval_added
                SET raw_data = %s::jsonb,
                    images = %s::jsonb
                WHERE id = %s AND status = 'new';
            """
            # Если images были обновлены в new_data, используем их, иначе используем те, что были в updated_raw_data
            # (они будут обновлены если new_data['images'] присутствовал и был обработан выше)
            images_for_update = updated_raw_data.get('images', [])
            self.cursor.execute(update_query, (json.dumps(updated_raw_data), json.dumps(images_for_update), pereval_id))
            self.connection.commit()
            print(f"Обновление перевала ID {pereval_id} успешно.")
            return {"state": 1, "id": pereval_id}

        except Error as e:
            print(f"Ошибка при обновлении перевала ID {pereval_id}: {e}")
            if self.connection:
                self.connection.rollback()
            return {"state": 0, "id": pereval_id}
        finally:
            pass

    def get_perevals_by_email(self, email: str) -> List[dict]:
        """
        Получает все перевалы, добавленные пользователем с указанным email.
        Возвращает список словарей с данными перевалов.
        """
        try:
            self.connect()
            self.cursor.execute(
                """
                SELECT id, date_added, raw_data, images, status
                FROM pereval_added
                WHERE raw_data->'user'->>'email' = %s;
                """, (email,)
            )
            results = self.cursor.fetchall()
            perevals = []
            for result in results:
                perevals.append({
                    "id": result[0],
                    "date_added": result[1].isoformat(timespec='seconds'),
                    "raw_data": result[2],  # Уже должен быть словарем
                    "images": result[3],  # Уже должен быть списком словарей или None
                    "status": result[4]
                })
            print(f"get_perevals_by_email: Retrieved {len(perevals)} perevals for email {email}")  # DEBUG PRINT
            return perevals
        except Error as e:
            print(f"Ошибка при получении перевалов по email {email}: {e}")
            return []
        finally:
            pass


# Пример использования (можно удалить или закомментировать в продакшн-коде)
if __name__ == '__main__':
    # Установка переменных окружения для тестирования.
    # В реальном приложении они должны быть настроены в вашей среде.
    os.environ['FSTR_DB_HOST'] = 'localhost'
    os.environ['FSTR_DB_PORT'] = '5432'
    os.environ['FSTR_DB_NAME'] = 'pereval_app'
    os.environ['FSTR_DB_LOGIN'] = 'postgres'
    os.environ['FSTR_DB_PASS'] = 'admin123'  # Замените на ваш реальный пароль!

    db_manager = DatabaseManager()

    # Тест подключения
    if db_manager.connect():
        print("Пробное подключение успешно.")
        db_manager.disconnect()
    else:
        print("Пробное подключение не удалось. Проверьте настройки БД.")