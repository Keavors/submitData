import pytest
from datetime import datetime
import json
from db_manager import \
    DatabaseManager  # Убедитесь, что db_manager.py находится в том же каталоге или доступен через PYTHONPATH


# Фикстура db_manager_for_tests теперь предоставляется из conftest.py
# Она гарантирует очистку базы данных перед каждым тестом.

def test_db_connection_and_disconnection(db_manager_for_tests):
    """Проверяет подключение и отключение от тестовой БД."""
    # Фикстура уже подключила БД, просто проверяем, что объект connection существует
    assert db_manager_for_tests.connection is not None
    assert not db_manager_for_tests.connection.closed

    # Этот тест проверяет функциональность disconnect.
    # После disconnect connection будет None или закрыто.
    db_manager_for_tests.disconnect()

    # Assert that connection is now closed or None
    assert db_manager_for_tests.connection is None or db_manager_for_tests.connection.closed


def test_add_and_get_pereval(db_manager_for_tests):
    """Проверяет добавление нового перевала и его получение по ID."""
    test_data = {
        "beautyTitle": "пер. Тестовый",
        "title": "Тест перевал",
        "other_titles": "ТестовыйДругой",
        "connect": "тест",
        "add_time": datetime.now().isoformat(timespec='seconds'),
        "user": {
            "email": "test@example.com",
            "fam": "Тестов",
            "name": "Тест",
            "otc": "Тестович",
            "phone": "+71234567890"
        },
        "coords": {
            "latitude": "10.0",
            "longitude": "20.0",
            "height": "1000"
        },
        "level": {
            "winter": "1А",
            "summer": "",
            "autumn": "",
            "spring": ""
        },
        "images": [
            {"data": "base64_data_1", "title": "Фото 1"},
            {"data": "base64_data_2", "title": "Фото 2"}
        ]
    }
    pereval_id = db_manager_for_tests.add_pereval(test_data)
    assert pereval_id is not None and isinstance(pereval_id, int)

    retrieved_pereval = db_manager_for_tests.get_pereval_by_id(pereval_id)
    assert retrieved_pereval is not None
    assert retrieved_pereval['id'] == pereval_id
    assert retrieved_pereval['status'] == 'new'

    # Здесь json.loads() удален, так как raw_data уже должна быть словарем
    assert retrieved_pereval['raw_data']['user']['email'] == "test@example.com"
    assert retrieved_pereval['raw_data']['title'] == "Тест перевал"

    # Добавлена проверка на наличие ключа 'images' и его тип, прежде чем проверять длину
    assert 'images' in retrieved_pereval and isinstance(retrieved_pereval['images'], list)
    assert len(retrieved_pereval['images']) == 2
    assert retrieved_pereval['images'][0]['title'] == "Фото 1"


def test_update_pereval_status_new(db_manager_for_tests):
    """Проверяет успешное обновление перевала со статусом 'new'."""
    test_data = {
        "beautyTitle": "пер. Оригинальный",
        "title": "Оригинальный перевал",
        "user": {
            "email": "user_update@example.com",
            "fam": "Оригинал", "name": "Ори", "otc": "Ориг", "phone": "+71111111111"
        },
        "coords": {"latitude": "30.0", "longitude": "40.0", "height": "2000"},
        "level": {"summer": "1А"},
        "add_time": datetime.now().isoformat(timespec='seconds'),
        "images": []
    }
    pereval_id = db_manager_for_tests.add_pereval(test_data)

    update_data = {
        "beautyTitle": "пер. Обновленный",
        "title": "Обновленный перевал",
        "coords": {"latitude": "35.0", "longitude": "45.0", "height": "2500"},
        "level": {"summer": "1Б"},
        "images": [{"data": "new_base64", "title": "Новое фото"}]
    }
    # Имитируем запрос на обновление, который приходит с API
    # API передаст только те поля, которые были изменены
    update_result = db_manager_for_tests.update_pereval(pereval_id, update_data)
    assert update_result['state'] == 1  # Успешное обновление
    assert update_result['id'] == pereval_id

    # Проверим, что данные обновились в БД
    updated_pereval = db_manager_for_tests.get_pereval_by_id(pereval_id)
    assert updated_pereval is not None
    assert updated_pereval['raw_data']['beautyTitle'] == "пер. Обновленный"
    assert updated_pereval['raw_data']['title'] == "Обновленный перевал"
    assert updated_pereval['raw_data']['coords']['latitude'] == "35.0"
    assert updated_pereval['raw_data']['level']['summer'] == "1Б"
    assert 'images' in updated_pereval and isinstance(updated_pereval['images'], list)  # Проверка на наличие и тип
    assert updated_pereval['images'][0]['title'] == "Новое фото"
    # Убедимся, что пользовательские данные не изменились
    assert updated_pereval['raw_data']['user']['email'] == "user_update@example.com"


def test_update_pereval_status_not_new(db_manager_for_tests):
    """Проверяет попытку обновления перевала со статусом, отличным от 'new'."""
    test_data = {
        "beautyTitle": "пер. Модерируемый",
        "title": "Модерируемый перевал",
        "user": {
            "email": "user_moderated@example.com",
            "fam": "Мод", "name": "Модератор", "otc": "Ович", "phone": "+72222222222"
        },
        "coords": {"latitude": "50.0", "longitude": "60.0", "height": "3000"},
        "level": {"summer": "2А"},
        "add_time": datetime.now().isoformat(timespec='seconds'),
        "images": []
    }
    pereval_id = db_manager_for_tests.add_pereval(test_data)

    # Имитируем изменение статуса (как будто модератор изменил)
    db_manager_for_tests.cursor.execute(
        "UPDATE pereval_added SET status = 'pending' WHERE id = %s;", (pereval_id,)
    )
    db_manager_for_tests.connection.commit()

    update_data = {
        "beautyTitle": "пер. Попытка_обновления",
        "title": "Попытка_обновления",
        "coords": {"latitude": "55.0", "longitude": "65.0", "height": "3500"}
    }
    update_result = db_manager_for_tests.update_pereval(pereval_id, update_data)
    assert update_result['state'] == 0  # Ожидаем, что обновление не произошло
    assert update_result['id'] == pereval_id

    # Проверим, что данные не изменились в БД
    not_updated_pereval = db_manager_for_tests.get_pereval_by_id(pereval_id)
    assert not_updated_pereval is not None
    assert not_updated_pereval['raw_data']['beautyTitle'] == "пер. Модерируемый"
    assert not_updated_pereval['status'] == 'pending'


def test_get_perevals_by_email(db_manager_for_tests):
    """Проверяет получение перевалов по email пользователя."""
    email1 = "user1@test.com"
    email2 = "user2@test.com"
    data1 = {
        "beautyTitle": "пер. Для Юзера1_1", "title": "Юзер1_1",
        "user": {"email": email1, "fam": "А", "name": "Б", "otc": "В", "phone": "1"},
        "coords": {"latitude": "1", "longitude": "1", "height": "1"},
        "level": {"summer": "1А"},
        "add_time": datetime.now().isoformat(timespec='seconds'), "images": []
    }
    data2 = {
        "beautyTitle": "пер. Для Юзера1_2", "title": "Юзер1_2",
        "user": {"email": email1, "fam": "А", "name": "Б", "otc": "В", "phone": "1"},
        "coords": {"latitude": "2", "longitude": "2", "height": "2"},
        "level": {"summer": "1Б"},
        "add_time": datetime.now().isoformat(timespec='seconds'), "images": []
    }
    data3 = {
        "beautyTitle": "пер. Для Юзера2_1", "title": "Юзер2_1",
        "user": {"email": email2, "fam": "Г", "name": "Д", "otc": "Е", "phone": "2"},
        "coords": {"latitude": "3", "longitude": "3", "height": "3"},
        "level": {"summer": "2А"},
        "add_time": datetime.now().isoformat(timespec='seconds'), "images": []
    }
    db_manager_for_tests.add_pereval(data1)
    db_manager_for_tests.add_pereval(data2)
    db_manager_for_tests.add_pereval(data3)

    perevals_user1 = db_manager_for_tests.get_perevals_by_email(email1)
    assert len(perevals_user1) == 2
    # Здесь json.loads() удален, так как raw_data уже должна быть словарем
    titles_user1 = {p['raw_data']['title'] for p in perevals_user1}
    assert "Юзер1_1" in titles_user1
    assert "Юзер1_2" in titles_user1

    perevals_user2 = db_manager_for_tests.get_perevals_by_email(email2)
    assert len(perevals_user2) == 1
    assert perevals_user2[0]['raw_data']['title'] == "Юзер2_1"

    perevals_nonexistent = db_manager_for_tests.get_perevals_by_email("nonexistent@test.com")
    assert len(perevals_nonexistent) == 0