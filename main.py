from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Union
from datetime import datetime
import uvicorn
import os
import json  # Добавлен импорт json

from db_manager import DatabaseManager

app = FastAPI(
    title="Pereval Online API",
    description="API для отправки данных о горных перевалах в ФСТР",
    version="1.0.0"
)

# Инициализируем менеджер базы данных
db_manager = DatabaseManager()


# --- Определяем модели данных для валидации входящих запросов ---
class User(BaseModel):
    email: EmailStr
    fam: str
    name: str
    otc: Optional[str] = None
    phone: str


class Coords(BaseModel):
    latitude: str
    longitude: str
    height: str


class Level(BaseModel):
    winter: Optional[str] = None
    summer: Optional[str] = None
    autumn: Optional[str] = None
    spring: Optional[str] = None


class Image(BaseModel):
    data: str
    title: str


class SubmitDataRequest(BaseModel):
    beauty_title: str = Field(..., alias="beautyTitle")
    title: str
    other_titles: Optional[str] = None
    connect: Optional[str] = None
    # add_time здесь делаем Optional, так как это поле чаще всего устанавливается на сервере
    # а если приходит, то Pydantic его провалидирует
    add_time: Optional[str] = None
    user: User
    coords: Coords
    level: Level
    images: List[Image] = []  # По умолчанию пустой список изображений


# --- Эндпоинты API ---

@app.post("/submitData")
async def submit_data(data: SubmitDataRequest):
    """
    Добавление новой записи о перевале.
    """
    try:
        # Пытаемся подключиться к БД, если соединение неактивно
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        # Преобразуем RequestModel в словарь, подходящий для сохранения в raw_data
        # Используем dict(by_alias=True) для корректного преобразования beautyTitle
        submit_data_dict = data.model_dump(by_alias=True)

        # Удаляем add_time из submit_data_dict, если оно не было передано,
        # или используем его, если передано. db_manager.add_pereval
        # обрабатывает его самостоятельно, если None.
        add_time_str = submit_data_dict.get('add_time')
        if add_time_str:
            # Если add_time пришло, убедимся, что оно корректно,
            # но его обработка на стороне БД должна быть надежной.
            # Для сохранения в raw_data мы можем оставить его как есть.
            pass
        else:
            # Если add_time не передано, его не будет в raw_data,
            # и БД установит CURRENT_TIMESTAMP.
            submit_data_dict.pop('add_time', None)

        # Отделяем изображения для сохранения в отдельном JSONB поле 'images'
        images_data = submit_data_dict.pop('images', [])

        # Передаем данные в db_manager.add_pereval
        # Теперь db_manager.add_pereval должен принимать submit_data_dict (для raw_data) и images_data
        # В db_manager.add_pereval, images_data будет dumps'иться в JSON.
        pereval_id = db_manager.add_pereval(submit_data_dict, images_data)

        if pereval_id:
            return {"state": 1, "message": "Запись успешно добавлена.", "id": pereval_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"state": 0, "message": "Не удалось добавить запись."}
            )

    except Exception as e:
        # Проверяем, если ошибка связана с уникальностью email
        # Это очень базовая проверка, для продакшена лучше использовать более конкретные исключения psycopg2
        if "duplicate key value violates unique constraint" in str(e).lower() and "user_email_unique" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"state": 0, "message": "Пользователь с таким email уже существует."}
            )
        print(f"Ошибка при обработке submitData: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"state": 0, "message": "Что-то пошло не так на сервере."}
        )
    finally:
        # Опционально: можно закрывать соединение после каждой операции,
        # но для повышения производительности лучше использовать пул соединений.
        # Для простоты текущей реализации оставим как есть, но учитывайте это.
        # db_manager.disconnect()
        pass


@app.get("/submitData/{pereval_id}")
async def get_pereval_by_id(pereval_id: int):
    """
    Получение информации о перевале по его ID.
    """
    try:
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        pereval_data = db_manager.get_pereval_by_id(pereval_id)

        if pereval_data:
            # Логирование для отладки:
            # print(f"get_pereval_by_id: Retrieved data for ID {pereval_id}: {pereval_data}")

            if 'raw_data' in pereval_data and pereval_data['raw_data']:
                response_data = pereval_data['raw_data']
                response_data['id'] = pereval_data['id']

                # Добавляем date_added и status в ответ
                response_data['date_added'] = pereval_data.get('date_added')
                response_data['status'] = pereval_data.get('status')

                images_from_db = pereval_data.get('images', [])
                formatted_images = []
                if images_from_db:
                    try:
                        # Если images_from_db пришло как строка JSON из базы, нужно ее распарсить
                        if isinstance(images_from_db, str):
                            images_from_db = json.loads(images_from_db)
                        if isinstance(images_from_db, list):
                            for img in images_from_db:
                                if isinstance(img, dict) and 'data' in img and 'title' in img:
                                    formatted_images.append({'data': img['data'], 'title': img['title']})
                    except json.JSONDecodeError:
                        print(f"Ошибка декодирования JSON для изображений ID {pereval_id}")
                        formatted_images = []

                response_data['images'] = formatted_images

                # !!! ЭТА СТРОКА БЫЛА ИСТОЧНИКОМ ОШИБКИ И УДАЛЕНА !!!
                # del response_data['images_json'] # <-- УДАЛЕНО

                return response_data
            else:
                # Если raw_data отсутствует или пусто
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Данные перевала неполные.")
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Перевал не найден.")

    except HTTPException:  # Пробрасываем HTTPException без изменений
        raise
    except Exception as e:
        print(f"Ошибка при обработке get_pereval_by_id: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при получении данных о перевале."
        )


@app.patch("/submitData/{pereval_id}")
async def patch_pereval(pereval_id: int, update_data: SubmitDataRequest):
    """
    Редактирование данных о перевале по его ID.
    Разрешено редактировать только записи со статусом 'new'.
    Пользовательские данные (user) редактировать нельзя.
    """
    try:
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        # Получаем текущие данные перевала для проверки статуса
        current_pereval_data = db_manager.get_pereval_by_id(pereval_id)

        if not current_pereval_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"state": 0, "message": "Перевал не найден."}
            )

        # Проверка статуса
        if current_pereval_data.get('status') != 'new':
            # Если статус не "new", возвращаем ошибку, как в ваших тестах.
            # Для PATCH запроса, который не позволяет изменение, 200 OK с сообщением об ошибке приемлем.
            # Если бы это был более строгий API, можно было бы вернуть 403 Forbidden.
            return {
                "state": 0,
                "message": f"Редактирование запрещено. Статус перевала: '{current_pereval_data.get('status', 'неизвестно')}'. Разрешено только для 'new'."
            }

        # Преобразуем RequestModel в словарь
        update_data_dict = update_data.model_dump(by_alias=True,
                                                  exclude_unset=True)  # exclude_unset=True для частичного обновления

        # Проверяем, пытаются ли изменить пользовательские данные
        if 'user' in update_data_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"state": 0, "message": "Изменение пользовательских данных запрещено."}
            )

        # Отделяем изображения, если они есть в update_data
        images_to_update = update_data_dict.pop('images', None)

        # Вызываем метод обновления в db_manager
        # db_manager.update_pereval должен обновлять только те поля, что переданы
        success = db_manager.update_pereval(pereval_id, update_data_dict, images_to_update)

        if success:
            return {"state": 1, "message": "Запись успешно обновлена."}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"state": 0, "message": "Не удалось обновить запись."}
            )

    except HTTPException:  # Пробрасываем HTTPException без изменений
        raise
    except Exception as e:
        print(f"Ошибка при обработке patch_pereval: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"state": 0, "message": "Внутренняя ошибка сервера при обновлении перевала."}
        )


@app.get("/submitData")
async def get_perevals_by_email(user__email: EmailStr):
    """
    Получение списка перевалов, отправленных пользователем, по его email.
    """
    try:
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        perevals_data = db_manager.get_perevals_by_email(user__email)

        if perevals_data is not None:  # Проверяем на None, так как get_perevals_by_email может вернуть пустой список
            formatted_list = []
            for pereval in perevals_data:
                # Преобразуем raw_data и images обратно в словари/списки
                formatted_pereval = pereval['raw_data']
                formatted_pereval['id'] = pereval['id']
                formatted_pereval['date_added'] = pereval['date_added']  # Добавляем date_added
                formatted_pereval['status'] = pereval['status']  # Добавляем status

                images_from_db = pereval.get('images', [])
                processed_images = []
                if images_from_db:
                    try:
                        if isinstance(images_from_db, str):
                            images_from_db = json.loads(images_from_db)
                        if isinstance(images_from_db, list):
                            for img in images_from_db:
                                if isinstance(img, dict) and 'data' in img and 'title' in img:
                                    processed_images.append({'data': img['data'], 'title': img['title']})
                    except json.JSONDecodeError:
                        print(f"Ошибка декодирования JSON для изображений при получении по email.")
                        processed_images = []
                formatted_pereval['images'] = processed_images
                formatted_list.append(formatted_pereval)

            return {
                "status": status.HTTP_200_OK,
                "message": "Успешно получено",
                "data": formatted_list
            }
        else:
            # Если db_manager.get_perevals_by_email вернул None (хотя он должен возвращать список)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Ошибка при получении данных о перевалах.")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка при обработке get_perevals_by_email: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Ошибка при получении данных о перевалах.")


# --- Запуск API (только для прямого запуска файла) ---
if __name__ == "__main__":
    # Убедитесь, что переменные окружения установлены в конфигурации запуска PyCharm!
    # ИЛИ временно раскомментируйте и установите их здесь (не рекомендуется для продакшена):
    # os.environ['FSTR_DB_HOST'] = 'localhost'
    # os.environ['FSTR_DB_PORT'] = '5432'
    # os.environ['FSTR_DB_NAME'] = 'pereval_app'
    # os.environ['FSTR_DB_LOGIN'] = 'postgres'
    # os.environ['FSTR_DB_PASS'] = 'admin123' # Замените на ваш реальный пароль!

    # Перед запуском Uvicorn, убедимся, что db_manager может подключиться хотя бы раз.
    # Это полезно для быстрой диагностики проблем с БД при запуске API.
    # Если подключение не удастся, Uvicorn не будет запущен.
    if not db_manager.connect():
        print(
            "Критическая ошибка: Не удалось установить начальное соединение с базой данных. Проверьте переменные окружения и доступность БД.")
        exit(1)  # Завершаем выполнение, если нет подключения к БД

    uvicorn.run(app, host="0.0.0.0", port=8000)