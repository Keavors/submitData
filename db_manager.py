import os
import psycopg2
from psycopg2 import Error
import json
from datetime import datetime


class DatabaseManager:
    """
    Класс для управления базой данных PostgreSQL.
    Позволяет подключаться к БД и добавлять новые записи о перевалах.
    """

    def __init__(self):
        # Получаем данные для подключения из переменных окружения
        # Это более безопасный способ, чем хранить их прямо в коде
        self.db_host = os.getenv('FSTR_DB_HOST', 'localhost')  # По умолчанию 'localhost'
        self.db_port = os.getenv('FSTR_DB_PORT', '5432')  # По умолчанию '5432'
        self.db_name = os.getenv('FSTR_DB_NAME', 'pereval_app')  # Имя нашей БД
        self.db_user = os.getenv('FSTR_DB_LOGIN', 'postgres')  # Пользователь, созданный при установке
        self.db_password = os.getenv('FSTR_DB_PASS', 'admin123')  # Пароль, который вы задали

        self.connection = None  # Переменная для хранения подключения к БД
        self.cursor = None  # Переменная для выполнения SQL-запросов

    def connect(self):
        """
        Устанавливает соединение с базой данных.
        """
        try:
            self.connection = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password
            )
            self.connection.autocommit = True  # Автоматически подтверждать изменения
            self.cursor = self.connection.cursor()
            print("Успешное подключение к базе данных PostgreSQL")
            return True
        except Error as e:
            print(f"Ошибка при подключении к базе данных: {e}")
            self.connection = None
            self.cursor = None
            return False

    def disconnect(self):
        """
        Закрывает соединение с базой данных.
        """
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            print("Соединение с базой данных закрыто.")

    def add_pereval(self, data: dict) -> int or None:
        """
        Добавляет новую запись о перевале в таблицу pereval_added.
        Возвращает id добавленной записи или None в случае ошибки.
        """
        if not self.connection or not self.cursor:
            print("Нет активного соединения с базой данных.")
            return None

        try:
            # Преобразуем входящие данные в JSON-строки для полей raw_data и images
            # Важно: имя поля 'images' в JSON, который мы получаем,
            # отличается от имени таблицы 'pereval_images'.
            # Здесь мы пока просто сохраняем images как JSON.
            # В будущем, если бы картинки хранились отдельно, логика была бы сложнее.
            raw_data_json = json.dumps(data)  # Весь входящий JSON сохраняем как raw_data

            # Поскольку поле 'images' в JSON может быть списком словарей,
            # мы извлекаем его и сохраняем как JSON.
            # Если поле 'images' отсутствует или не является списком,
            # создаем пустой JSON массив.
            images_data_from_json = data.get('images', [])
            images_json = json.dumps(
                {"images": images_data_from_json})  # Оборачиваем в {"images": ...} как в примере БД

            # Извлекаем дату добавления из JSON или используем текущую
            # Если data['add_time'] отсутствует или имеет неверный формат, psycopg2 может выдать ошибку.
            # Лучше использовать текущее время или обработать возможные ошибки формата.
            # Для простоты, пока используем текущее время, если data['add_time'] некорректно.
            try:
                add_time_str = data.get('add_time')
                if add_time_str:
                    date_added = datetime.fromisoformat(
                        add_time_str.replace('Z', '+00:00') if 'Z' in add_time_str else add_time_str)
                else:
                    date_added = datetime.now()
            except ValueError:
                date_added = datetime.now()  # Если формат неверный, используем текущее время

            # SQL-запрос для вставки данных
            # Обратите внимание на поле "status", мы устанавливаем его в 'new' по умолчанию
            # и указываем его в списке колонок и значений
            sql = """
            INSERT INTO public.pereval_added (date_added, raw_data, images, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """

            # Значения, которые будут вставлены в запрос
            values = (
                date_added,
                raw_data_json,
                images_json,
                'new'  # Статус по умолчанию при добавлении
            )

            self.cursor.execute(sql, values)

            # Получаем id только что вставленной записи
            pereval_id = self.cursor.fetchone()[0]
            print(f"Запись о перевале успешно добавлена. ID: {pereval_id}")
            return pereval_id

        except Error as e:
            print(f"Ошибка при добавлении перевала в базу данных: {e}")
            return None


# Пример использования (для тестирования)
if __name__ == "__main__":
    # Для запуска этого блока вам нужно будет установить переменные окружения
    # ИЛИ раскомментировать строки ниже и задать значения напрямую для теста.
    # В реальном приложении всегда используйте переменные окружения.

    # os.environ['FSTR_DB_HOST'] = 'localhost'
    # os.environ['FSTR_DB_PORT'] = '5432'
    # os.environ['FSTR_DB_NAME'] = 'pereval_app'
    # os.environ['FSTR_DB_LOGIN'] = 'postgres'
    # os.environ['FSTR_DB_PASS'] = 'admin123' # Замените на ваш реальный пароль!

    db_manager = DatabaseManager()

    if db_manager.connect():
        # Пример данных для добавления
        test_data = {
            "beauty_title": "пер. ",
            "title": "Тестовый Перевал",
            "other_titles": "Тест",
            "connect": "",
            "add_time": "2024-06-30 15:00:00",  # Пример даты
            "user": {
                "email": "test@example.com",
                "fam": "Иванов",
                "name": "Иван",
                "otc": "Иванович",
                "phone": "+7 999 123 45 67"
            },
            "coords": {
                "latitude": "46.000",
                "longitude": "7.000",
                "height": "2500"
            },
            "level": {
                "winter": "",
                "summer": "1Б",
                "autumn": "1Б",
                "spring": ""
            },
            "images": [
                {"data": "<изображение1_в_base64>", "title": "Вид сверху"},
                {"data": "<изображение2_в_base64>", "title": "Тропа"}
            ]
        }

        new_pereval_id = db_manager.add_pereval(test_data)
        if new_pereval_id:
            print(f"Добавлен новый перевал с ID: {new_pereval_id}")
        else:
            print("Не удалось добавить перевал.")

        db_manager.disconnect()
    else:
        print("Не удалось подключиться к базе данных.")