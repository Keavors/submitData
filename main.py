from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Union
from datetime import datetime
import uvicorn
import os

from db_manager import DatabaseManager

app = FastAPI(
    title="Pereval Online API",
    description="API для отправки данных о горных перевалах в ФСТР",
    version="1.0.0"
)


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
    # а если приходит, то Pydantic попытается его распарсить.
    add_time: Optional[datetime] = None
    user: User
    coords: Coords
    level: Level
    images: List[Image] = []

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda dt: dt.isoformat(timespec='seconds')}  # Уточняем формат ISO

class UpdatePerevalRequest(BaseModel):
    beauty_title: Optional[str] = Field(None, alias="beautyTitle")
    title: Optional[str] = None
    other_titles: Optional[str] = None
    connect: Optional[str] = None
    add_time: Optional[datetime] = None
    # user: User # Исключаем user, так как его нельзя менять
    coords: Optional[Coords] = None
    level: Optional[Level] = None
    images: Optional[List[Image]] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda dt: dt.isoformat(timespec='seconds')}


# --- Инициализация менеджера базы данных ---
db_manager = DatabaseManager()


# --- Определение маршрутов API ---

@app.post("/submitData", summary="Отправить данные о новом перевале", response_model=dict)
async def submit_data(request_data: SubmitDataRequest):
    """
    Принимает данные о новом перевале от мобильного приложения,
    сохраняет их в базу данных и возвращает статус операции.
    """
    # Подключаемся к базе данных
    if not db_manager.connect():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Ошибка подключения к базе данных")

    try:
        # ИСХОДНО: data_to_save = request_data.dict(by_alias=True, exclude_none=True)
        # ИСПРАВЛЕНИЕ: Используем model_dump с mode='json' для правильной сериализации datetime
        data_to_save = request_data.model_dump(mode='json', by_alias=True, exclude_none=True)

        new_pereval_id = db_manager.add_pereval(data_to_save)

        if new_pereval_id is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Ошибка при добавлении записи в базу данных")

        return {
            "status": status.HTTP_200_OK,
            "message": "Отправлено успешно",
            "id": new_pereval_id
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Неизвестная ошибка в submit_data: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Внутренняя ошибка сервера: {e}")


@app.get("/submitData/{pereval_id}", summary="Получить данные о перевале по ID", response_model=dict)
async def get_pereval_by_id(pereval_id: int):
    """
    Возвращает полную информацию об объекте перевала по его ID, включая статус модерации.
    """
    if not db_manager.connect():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Ошибка подключения к базе данных")

    pereval_info = db_manager.get_pereval_by_id(pereval_id)

    if pereval_info:
        # raw_data и images_json уже являются объектами Python (словарями),
        # поэтому FastAPI автоматически преобразует их в JSON.
        # Можем их вернуть как есть или преобразовать структуру, чтобы она выглядела
        # ближе к исходному запросу (без images_json, а просто images).
        # Давайте сделаем, чтобы images_json было просто images и содержимое его словаря "images"

        # Создаем копию для изменения перед возвратом
        response_data = pereval_info.copy()
        # Извлекаем список картинок из 'images_json'
        if 'images_json' in response_data and isinstance(response_data['images_json'], dict):
            response_data['images'] = response_data['images_json'].get('images', [])
        else:
            response_data['images'] = []  # Если нет или неверный формат, то пустой список
        del response_data['images_json']  # Удаляем оригинальное поле

        return {
            "status": status.HTTP_200_OK,
            "message": "Успешно получено",
            "data": response_data
        }
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Перевал с ID {pereval_id} не найден.")


@app.patch("/submitData/{pereval_id}", summary="Отредактировать данные о перевале")
async def update_pereval_data(pereval_id: int, request_data: UpdatePerevalRequest): # Изменено на UpdatePerevalRequest
    """
    Редактирует существующую запись о перевале по ее ID,
    только если она находится в статусе 'new'.
    Редактировать можно все поля, кроме ФИО, адреса почты и номера телефона.
    """
    if not db_manager.connect():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Ошибка подключения к базе данных")

    # Если вы хотите передать только измененные поля в db_manager.update_pereval,
    # используйте request_data.dict(by_alias=True, exclude_unset=True)
    # exclude_unset=True означает, что будут включены только те поля,
    # которые были явно предоставлены в запросе, а не None значения.
    data_to_update = request_data.dict(by_alias=True, exclude_unset=True)

    state, message = db_manager.update_pereval(pereval_id, data_to_update)

    if state == 1:
        return {
            "state": 1,
            "message": message
        }
    else:
        return {
            "state": 0,
            "message": message
        }


@app.get("/submitData/", summary="Получить все перевалы пользователя по Email", response_model=dict)
async def get_perevals_by_user_email(user__email: EmailStr):
    """
    Возвращает список всех объектов перевала, отправленных пользователем с указанным email,
    а также их статусы.
    """
    if not db_manager.connect():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Ошибка подключения к базе данных")

    perevals_list = db_manager.get_perevals_by_email(user__email)

    if perevals_list is not None:
        # Для каждого перевала в списке, изменим структуру, чтобы она выглядела
        # ближе к исходному запросу (без images_json, а просто images)
        formatted_list = []
        for pereval_info in perevals_list:
            response_data = pereval_info.copy()
            if 'images_json' in response_data and isinstance(response_data['images_json'], dict):
                response_data['images'] = response_data['images_json'].get('images', [])
            else:
                response_data['images'] = []
            del response_data['images_json']
            formatted_list.append(response_data)

        return {
            "status": status.HTTP_200_OK,
            "message": "Успешно получено",
            "data": formatted_list
        }
    else:
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
        print("Критическая ошибка: Не удалось установить начальное соединение с базой данных. Проверьте настройки БД.")
    else:
        db_manager.disconnect()  # Закроем начальное соединение, Uvicorn откроет свои.
        print("Начальная проверка подключения к БД успешна. Запускаю API...")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)