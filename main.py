from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Union
from datetime import datetime
import uvicorn
import os
import json

from db_manager import DatabaseManager

app = FastAPI(
    title="Pereval Online API",
    description="API для отправки данных о горных перевалах в ФСТР",
    version="1.0.0"
)

# Инициализируем менеджер базы данных
db_manager = DatabaseManager()


# Определяем модели данных для валидации входящих запросов
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
    add_time: Optional[str] = None
    user: User  # Обязательное поле для POST
    coords: Coords  # Обязательное поле для POST
    level: Level  # Обязательное поле для POST
    images: List[Image] = []  # По умолчанию пустой список изображений


# МОДЕЛЬ ДЛЯ PATCH-ЗАПРОСОВ
class PatchDataRequest(BaseModel):
    beauty_title: Optional[str] = Field(None, alias="beautyTitle")
    title: Optional[str] = None
    other_titles: Optional[str] = None
    connect: Optional[str] = None
    add_time: Optional[str] = None  # add_time обычно не обновляется, но для гибкости оставим Optional
    user: Optional[User] = None  # Делаем Optional, но все равно запретим изменение в логике
    coords: Optional[Coords] = None
    level: Optional[Level] = None
    images: Optional[List[Image]] = None  # Optional для всего списка изображений


# --- Эндпоинты API ---

@app.post("/submitData")
async def submit_data(data: SubmitDataRequest):
    """
    Добавление новой записи о перевале.
    """
    try:
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        submit_data_dict = data.model_dump(by_alias=True)

        pereval_id = db_manager.add_pereval(submit_data_dict)

        if pereval_id:
            return {"state": 1, "message": "Запись успешно добавлена.", "id": pereval_id}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"state": 0, "message": "Не удалось добавить запись."}
            )

    except Exception as e:
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
            if 'raw_data' in pereval_data and pereval_data['raw_data']:
                response_data = pereval_data['raw_data']
                response_data['id'] = pereval_data['id']

                response_data['date_added'] = pereval_data.get('date_added')
                response_data['status'] = pereval_data.get('status')

                images_from_db = pereval_data.get('images', [])
                formatted_images = []
                if images_from_db:
                    try:
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

                return response_data
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Данные перевала неполные.")
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Перевал не найден.")

    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка при обработке get_pereval_by_id: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервера при получении данных о перевале."
        )


@app.patch("/submitData/{pereval_id}")
async def patch_pereval(pereval_id: int, update_data: PatchDataRequest):
    """
    Редактирование данных о перевале по его ID.
    Разрешено редактировать только записи со статусом 'new'.
    Пользовательские данные (user) редактировать нельзя.
    """
    try:
        if not db_manager.connection or db_manager.connection.closed:
            db_manager.connect()

        current_pereval_data = db_manager.get_pereval_by_id(pereval_id)

        if not current_pereval_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"state": 0, "message": "Перевал не найден."}
            )

        if current_pereval_data.get('status') != 'new':
            return {
                "state": 0,
                "message": f"Редактирование запрещено. Статус перевала: '{current_pereval_data.get('status', 'неизвестно')}'. Разрешено только для 'new'."
            }

        update_data_dict = update_data.model_dump(by_alias=True, exclude_unset=True)

        if 'user' in update_data_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"state": 0, "message": "Изменение пользовательских данных запрещено."}
            )

        success = db_manager.update_pereval(pereval_id, update_data_dict)

        if success:
            return {"state": 1, "message": "Запись успешно обновлена."}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"state": 0, "message": "Не удалось обновить запись."}
            )

    except HTTPException:
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

        if perevals_data is not None:
            formatted_list = []
            for pereval in perevals_data:
                formatted_pereval = pereval['raw_data']
                formatted_pereval['id'] = pereval['id']
                formatted_pereval['date_added'] = pereval['date_added']
                formatted_pereval['status'] = pereval['status']

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
    if not db_manager.connect():
        print(
            "Критическая ошибка: Не удалось установить начальное соединение с базой данных. Проверьте переменные окружения и доступность БД.")
        exit(1)

    uvicorn.run(app, host="0.0.0.0", port=8000)