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
        if self.connection and not self.connection.closed:  # Проверяем, если уже подключено и соединение не закрыто
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
            self.connection.autocommit = True
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
            try:
                self.cursor.close()
            except Error as e:
                print(f"Ошибка при закрытии курсора: {e}")
        if self.connection:
            try:
                self.connection.close()
                print("Соединение с базой данных закрыто.")
            except Error as e:
                print(f"Ошибка при закрытии соединения: {e}")
        self.connection = None
        self.cursor = None

    def add_pereval(self, data: dict) -> Optional[int]:
        """
        Добавляет новую запись о перевале в таблицу pereval_added.
        Возвращает id добавленной записи или None в случае ошибки.
        """
        if not self.connect():  # Убедимся, что подключены
            print("Не удалось подключиться для добавления перевала.")
            return None

        try:
            raw_data_json = json.dumps(data)

            images_data_from_json = data.get('images', [])
            images_json = json.dumps({"images": images_data_from_json})

            try:
                add_time_str = data.get('add_time')
                if add_time_str:
                    # Обработка ISO формата (например, "2024-06-30T15:00:00" или "2024-06-30 15:00:00")
                    # Заменяем 'Z' на '+00:00' для корректной обработки UTC offset
                    if 'Z' in add_time_str:
                        date_added = datetime.fromisoformat(add_time_str.replace('Z', '+00:00'))
                    elif ' ' in add_time_str:  # Если формат "YYYY-MM-DD HH:MM:SS"
                        date_added = datetime.strptime(add_time_str, '%Y-%m-%d %H:%M:%S')
                    else:  # Попытка обработки как ISO
                        date_added = datetime.fromisoformat(add_time_str)
                else:
                    date_added = datetime.now()
            except (ValueError, TypeError) as e:
                print(
                    f"Предупреждение: Некорректный формат add_time '{add_time_str}'. Использовано текущее время. Ошибка: {e}")
                date_added = datetime.now()

            sql = """
            INSERT INTO public.pereval_added (date_added, raw_data, images, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """

            values = (
                date_added,
                raw_data_json,
                images_json,
                'new'
            )

            self.cursor.execute(sql, values)
            pereval_id = self.cursor.fetchone()[0]
            print(f"Запись о перевале успешно добавлена. ID: {pereval_id}")
            return pereval_id

        except Error as e:
            print(f"Ошибка при добавлении перевала в базу данных: {e}")
            return None
        finally:
            # Оставляем соединение открытым, чтобы FastAPI мог его переиспользовать
            # db_manager.disconnect() # Это будет вызываться только в блоке if __name__ == "__main__":
            pass

    def get_pereval_by_id(self, pereval_id: int) -> Optional[dict]:
        """
        Получает информацию о перевале по его ID.
        Возвращает словарь с данными перевала или None, если запись не найдена.
        """
        if not self.connect():
            print("Не удалось подключиться для получения перевала по ID.")
            return None

        try:
            sql = """
            SELECT id, date_added, raw_data, images, status
            FROM public.pereval_added
            WHERE id = %s;
            """
            self.cursor.execute(sql, (pereval_id,))

            result = self.cursor.fetchone()

            if result:
                pereval_data = {
                    "id": result[0],
                    "date_added": result[1].isoformat() if result[1] else None,
                    "raw_data": result[2],  # raw_data уже Python dict/json
                    "images_json": result[3],  # images тоже Python dict/json
                    "status": result[4]
                }
                return pereval_data
            else:
                return None

        except Error as e:
            print(f"Ошибка при получении перевала по ID: {e}")
            return None
        finally:
            pass  # Соединение не закрываем

    def update_pereval(self, pereval_id: int, new_data: dict) -> Tuple[int, str]:
        """
        Обновляет существующую запись о перевале по ID.
        Разрешает редактировать только поля в raw_data (кроме user-данных) и images,
        только если статус 'new'.
        Возвращает tuple (state, message).
        state: 1 = успешно, 0 = ошибка.
        message: причина ошибки.
        """
        if not self.connect():
            return 0, "Ошибка подключения к базе данных."

        try:
            # 1. Проверяем текущий статус записи и получаем текущие raw_data
            sql_select = """
            SELECT status, raw_data FROM public.pereval_added WHERE id = %s;
            """
            self.cursor.execute(sql_select, (pereval_id,))
            current_pereval = self.cursor.fetchone()

            if not current_pereval:
                return 0, f"Перевал с ID {pereval_id} не найден."

            current_status = current_pereval[0]
            current_raw_data_obj = current_pereval[1]  # Это уже Python dict

            if current_status != 'new':
                return 0, f"Редактирование запрещено. Статус перевала: '{current_status}'. Разрешено только для 'new'."

            # 2. Объединяем старые и новые данные, сохраняя данные пользователя
            merged_raw_data = current_raw_data_obj.copy()

            # Сохраняем user данные из текущей записи
            user_data_from_db = merged_raw_data.get('user', {})

            # Обновляем остальные поля из new_data, кроме 'user'
            for key, value in new_data.items():
                if key != 'user':  # Не перезаписываем пользовательские данные
                    merged_raw_data[key] = value

            # Возвращаем user данные из БД в merged_raw_data, если они там были
            # Это гарантирует, что user-данные не будут изменены, даже если они пришли в new_data
            merged_raw_data['user'] = user_data_from_db

            # Обработка 'add_time' для merged_raw_data
            if 'add_time' in merged_raw_data and isinstance(merged_raw_data['add_time'], datetime):
                merged_raw_data['add_time'] = merged_raw_data['add_time'].isoformat(timespec='seconds')
            # Если add_time пришло строкой, убедимся что оно в формате ISO, но без микросекунд, если это не datetime
            elif 'add_time' in merged_raw_data and isinstance(merged_raw_data['add_time'], str):
                try:
                    # Попытка привести к datetime и обратно, чтобы унифицировать формат
                    dt_obj = datetime.fromisoformat(merged_raw_data['add_time'].replace('Z', '+00:00'))
                    merged_raw_data['add_time'] = dt_obj.isoformat(timespec='seconds')
                except (ValueError, TypeError):
                    # Если строка не в ISO формате, оставляем как есть или обрабатываем иначе
                    pass  # Для простоты пока оставляем как есть, если не ISO.

            raw_data_json = json.dumps(merged_raw_data)

            # Если 'images' пришли в new_data, используем их для поля images
            images_data_from_json = new_data.get('images', [])
            images_json = json.dumps({"images": images_data_from_json})

            # 3. Обновляем запись в базе данных
            sql_update = """
            UPDATE public.pereval_added
            SET raw_data = %s, images = %s
            WHERE id = %s;
            """
            self.cursor.execute(sql_update, (raw_data_json, images_json, pereval_id))

            return 1, "Запись успешно обновлена."

        except Error as e:
            print(f"Ошибка базы данных при обновлении перевала: {e}")
            return 0, f"Ошибка базы данных: {e}"
        except Exception as e:
            print(f"Неизвестная ошибка при обновлении перевала: {e}")
            return 0, f"Внутренняя ошибка сервера: {e}"
        finally:
            pass  # Соединение не закрываем

    def get_perevals_by_email(self, email: str) -> Optional[List[dict]]:
        """
        Получает список всех перевалов, отправленных пользователем с указанным email.
        Возвращает список словарей с данными перевалов или None в случае ошибки.
        """
        if not self.connect():
            print("Не удалось подключиться для получения перевалов по email.")
            return None

        try:
            sql = """
            SELECT id, date_added, raw_data, images, status
            FROM public.pereval_added
            WHERE raw_data->'user'->>'email' = %s;
            """
            self.cursor.execute(sql, (email,))

            results = self.cursor.fetchall()

            perevals_list = []
            for result in results:
                pereval_data = {
                    "id": result[0],
                    "date_added": result[1].isoformat() if result[1] else None,
                    "raw_data": result[2],
                    "images_json": result[3],
                    "status": result[4]
                }
                perevals_list.append(pereval_data)

            return perevals_list

        except Error as e:
            print(f"Ошибка при получении перевалов по email: {e}")
            return None
        finally:
            pass  # Соединение не закрываем


# Пример использования (для тестирования)
if __name__ == "__main__":
    # Убедитесь, что переменные окружения установлены в конфигурации запуска PyCharm!
    # ИЛИ раскомментируйте и установите их здесь (ТОЛЬКО для тестирования):
    # os.environ['FSTR_DB_HOST'] = 'localhost'
    # os.environ['FSTR_DB_PORT'] = '5432'
    # os.environ['FSTR_DB_NAME'] = 'pereval_app'
    # os.environ['FSTR_DB_LOGIN'] = 'postgres'
    # os.environ['FSTR_DB_PASS'] = 'admin123' # Замените на ваш реальный пароль!

    # --- Тестирование add_pereval ---
    # Переинициализируем менеджер базы данных для каждого тестового блока
    print("\n--- Тестирование add_pereval ---")
    db_manager_add = DatabaseManager()
    if db_manager_add.connect():
        test_data_add = {
            "beauty_title": "пер. ",
            "title": "Тестовый Перевал для add",
            "other_titles": "ТестДобавления",
            "connect": "connect string",
            "add_time": datetime.now().isoformat(timespec='seconds'),  # Использование текущего времени для уникальности
            "user": {
                "email": "test_add@example.com",
                "fam": "Тестов",
                "name": "Тест",
                "otc": "Адд",
                "phone": "+7 111 222 3344"
            },
            "coords": {
                "latitude": "46.001",
                "longitude": "7.001",
                "height": "2501"
            },
            "level": {
                "winter": "1А",
                "summer": "1Б",
                "autumn": "1Б",
                "spring": "1А"
            },
            "images": [
                {"data": "base64_add_img1", "title": "Вид сверху add"},
                {"data": "base64_add_img2", "title": "Тропа add"}
            ]
        }
        new_pereval_id_add = db_manager_add.add_pereval(test_data_add)
        if new_pereval_id_add:
            print(f"Добавлен новый перевал с ID: {new_pereval_id_add}")
        else:
            print("Не удалось добавить перевал.")
        db_manager_add.disconnect()
    else:
        print("Не удалось подключиться для теста add_pereval.")

    # --- Тестирование get_pereval_by_id ---
    print("\n--- Тестирование get_pereval_by_id ---")
    db_manager_get = DatabaseManager()
    if db_manager_get.connect():
        # Используем ID, который был добавлен в прошлом успешном запуске (например, 2 или 3)
        # Если вы много раз запускали add_pereval, может понадобиться найти ID, который точно есть.
        # Или используйте `new_pereval_id_add` из предыдущего блока, если хотите получить его сразу.
        test_id_for_get = new_pereval_id_add if 'new_pereval_id_add' in locals() and new_pereval_id_add else 1
        pereval_info = db_manager_get.get_pereval_by_id(test_id_for_get)
        if pereval_info:
            print(f"Информация о перевале ID {test_id_for_get}: {pereval_info}")
        else:
            print(f"Перевал ID {test_id_for_get} не найден.")
        db_manager_get.disconnect()
    else:
        print("Не удалось подключиться для теста get_pereval_by_id.")

    # --- Тестирование update_pereval ---
    print("\n--- Тестирование update_pereval ---")
    db_manager_update = DatabaseManager()
    if db_manager_update.connect():
        # Добавляем новую запись специально для обновления, чтобы она была в статусе 'new'
        test_data_for_update_initial = {
            "beauty_title": "пер. ",
            "title": "Исходный Перевал для Обновления",
            "other_titles": "ОБНОВИТЬ",
            "connect": "",
            "add_time": datetime.now().isoformat(timespec='seconds'),
            "user": {
                "email": "update_test_initial@example.com",
                "fam": "Тест",
                "name": "Для",
                "otc": "Обновления",
                "phone": "+7 999 000 1122"
            },
            "coords": {
                "latitude": "47.000",
                "longitude": "8.000",
                "height": "1500"
            },
            "level": {
                "winter": "",
                "summer": "1А",
                "autumn": "1А",
                "spring": ""
            },
            "images": []
        }
        update_id = db_manager_update.add_pereval(test_data_for_update_initial)
        if update_id:
            print(f"Добавлен перевал для обновления с ID: {update_id}")

            new_update_data = {
                "title": "Обновленный Перевал (новое название)",
                "beauty_title": "новое b_title",
                "coords": {
                    "latitude": "47.111",
                    "longitude": "8.222",
                    "height": "1600"
                },
                # Данные пользователя не должны измениться, даже если переданы
                "user": {
                    "email": "changed@example.com",
                    "fam": "НЕ ИЗМЕНИТСЯ",
                    "name": "НЕ ИЗМЕНИТСЯ",
                    "otc": "НЕ ИЗМЕНИТСЯ",
                    "phone": "9999999999"
                },
                "images": [
                    {"data": "new_image_data_A", "title": "Новое фото A"},
                    {"data": "new_image_data_B", "title": "Новое фото B"}
                ]
            }
            state, message = db_manager_update.update_pereval(update_id, new_update_data)
            print(f"Результат обновления ID {update_id}: state={state}, message={message}")

            # Проверим, что данные пользователя не изменились и другие поля обновились
            updated_pereval_info = db_manager_update.get_pereval_by_id(update_id)
            if updated_pereval_info:
                print(f"Проверка обновленного перевала ID {update_id}:")
                print(f"  Статус: {updated_pereval_info['status']}")
                print(f"  Title: {updated_pereval_info['raw_data'].get('title')}")
                print(
                    f"  User Email (должен быть исходным): {updated_pereval_info['raw_data'].get('user', {}).get('email')}")
                if (updated_pereval_info['raw_data'].get('user', {}).get(
                        'email') == "update_test_initial@example.com" and
                        updated_pereval_info['raw_data'].get('title') == "Обновленный Перевал (новое название)"):
                    print("Проверка обновления: Данные пользователя не изменились, title обновился - Ок.")
                else:
                    print("Ошибка: Проверка обновления не удалась.")
            else:
                print("Ошибка: Не удалось получить обновленный перевал для проверки.")

            # Тестирование обновления "не-new" статуса (поменяем статус вручную в БД для теста)
            print("\n--- Тестирование update_pereval для НЕ-'new' статуса ---")
            db_manager_update.cursor.execute("UPDATE public.pereval_added SET status = 'accepted' WHERE id = %s",
                                             (update_id,))
            state_non_new, message_non_new = db_manager_update.update_pereval(update_id, new_update_data)
            print(
                f"Результат обновления ID {update_id} (статус не 'new'): state={state_non_new}, message={message_non_new}")

        db_manager_update.disconnect()
    else:
        print("Не удалось подключиться для теста update_pereval.")

    # --- Тестирование get_perevals_by_email ---
    print("\n--- Тестирование get_perevals_by_email ---")
    db_manager_email_get = DatabaseManager()
    if db_manager_email_get.connect():
        # Добавим ещё одну запись для email, чтобы было что искать
        test_data_for_email_search = {
            "beauty_title": "пер. ",
            "title": "Перевал для поиска по Email",
            "other_titles": "ПоискПочты",
            "connect": "",
            "add_time": datetime.now().isoformat(timespec='seconds'),
            "user": {
                "email": "api_test@mail.ru",  # Используйте этот email для поиска!
                "fam": "Иванов",
                "name": "Иван",
                "otc": "Иванович",
                "phone": "+7 999 123 45 67"
            },
            "coords": {
                "latitude": "48.000",
                "longitude": "9.000",
                "height": "1800"
            },
            "level": {
                "winter": "",
                "summer": "1А",
                "autumn": "1А",
                "spring": ""
            },
            "images": []
        }
        db_manager_email_get.add_pereval(test_data_for_email_search)  # Добавим

        email_to_search = "api_test@mail.ru"  # Используйте email, который вы использовали в Swagger для API
        perevals_by_email = db_manager_email_get.get_perevals_by_email(email_to_search)
        if perevals_by_email:
            print(f"Перевалы для {email_to_search}:")
            for p in perevals_by_email:
                print(f"  ID: {p['id']}, Title: {p['raw_data']['title']}, Status: {p['status']}")
        else:
            print(f"Нет перевалов для {email_to_search} или ошибка.")
        db_manager_email_get.disconnect()
    else:
        print("Не удалось подключиться для теста get_perevals_by_email.")