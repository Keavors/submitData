from fastapi import FastAPI, HTTPException, status  # Импортируем FastAPI и классы для обработки ошибок
from pydantic import BaseModel, EmailStr, \
    Field  # Импортируем BaseModel для определения структуры данных и EmailStr для валидации email
from typing import Optional, List  # Импортируем Optional и List для указания типов данных
from datetime import datetime  # Для работы с датами и временем
import uvicorn  # Для запуска нашего API
import os  # Для работы с переменными окружения

# Импортируем наш класс DatabaseManager, который мы создали ранее
from db_manager import DatabaseManager

# Создаем экземпляр FastAPI
app = FastAPI(
    title="Pereval Online API",  # Название вашего API
    description="API для отправки данных о горных перевалах в ФСТР",  # Описание API
    version="1.0.0"  # Версия API
)


# --- Определяем модели данных для валидации входящих запросов ---
# FastAPI использует Pydantic для автоматической валидации данных.
# Это означает, что если входящий JSON не соответствует этой структуре,
# FastAPI автоматически вернет ошибку 422 (Unprocessable Entity).

class User(BaseModel):
    # Модель для данных пользователя
    email: EmailStr  # EmailStr проверяет, что это валидный email
    fam: str  # Фамилия
    name: str  # Имя
    otc: Optional[str] = None  # Отчество (необязательное поле, по умолчанию None)
    phone: str  # Телефон


class Coords(BaseModel):
    # Модель для координат перевала
    latitude: str  # Широта (храним как строку, как в примере JSON)
    longitude: str  # Долгота (храним как строку)
    height: str  # Высота (храним как строку)


class Level(BaseModel):
    # Модель для категории трудности перевала
    winter: Optional[str] = None  # Зима (необязательное поле)
    summer: Optional[str] = None  # Лето (необязательное поле)
    autumn: Optional[str] = None  # Осень (необязательное поле)
    spring: Optional[str] = None  # Весна (необязательное поле)


class Image(BaseModel):
    # Модель для информации об изображении
    data: str  # Бинарные данные изображения (скорее всего, base64 строка)
    title: str  # Название изображения


class SubmitDataRequest(BaseModel):
    # Главная модель для тела запроса POST submitData
    beauty_title: str = Field(..., alias="beautyTitle")  # "beauty_title" в коде, но ожидаем "beautyTitle" в JSON
    title: str  # Название перевала
    other_titles: Optional[str] = None  # Другие названия (необязательно)
    connect: Optional[str] = None  # Что соединяет (необязательно)
    add_time: Optional[
        datetime] = None  # Время добавления (необязательно, FastAPI автоматически преобразует строку в datetime)
    user: User  # Данные пользователя, используем модель User
    coords: Coords  # Координаты, используем модель Coords
    level: Level  # Уровень сложности, используем модель Level
    images: List[Image] = []  # Список изображений, используем модель Image, по умолчанию пустой список

    # Конфигурация Pydantic, чтобы позволить полям в JSON быть camelCase
    # и автоматически преобразовывать их в snake_case для Python
    class Config:
        populate_by_name = True  # Позволяет использовать alias для полей
        json_encoders = {datetime: lambda dt: dt.isoformat()}  # Для корректного преобразования datetime в JSON


# --- Инициализация менеджера базы данных ---
db_manager = DatabaseManager()


# --- Определение маршрута API ---

# Декоратор @app.post("/submitData") определяет, что это POST-запрос по пути "/submitData"
@app.post("/submitData", summary="Отправить данные о новом перевале")
async def submit_data(request_data: SubmitDataRequest):
    """
    Принимает данные о новом перевале от мобильного приложения,
    сохраняет их в базу данных и возвращает статус операции.
    """
    # Подключаемся к базе данных
    if not db_manager.connection:  # Если соединение ещё не установлено
        if not db_manager.connect():  # Пытаемся подключиться
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Ошибка подключения к базе данных")

    try:
        # Pydantic уже проверил и распарсил request_data в Python-объект.
        # Мы можем преобразовать его обратно в словарь, который наш db_manager ожидает.
        # .dict() с exclude_unset=True не включает поля, которые не были предоставлены в запросе,
        # но нам нужно всё, что пришло, поэтому без exclude_unset.
        # Также, нам нужно убедиться, что 'beauty_title' преобразуется обратно в 'beautyTitle'
        # для сохранения в 'raw_data' точно как в примере JSON запроса.

        # Преобразуем объект Pydantic в обычный Python-словарь
        # Мы используем dict(by_alias=True) чтобы получить имена полей как в исходном JSON
        # (например, beautyTitle вместо beauty_title)
        data_to_save = request_data.dict(by_alias=True, exclude_none=True)

        # Дополнительная обработка изображений, чтобы они соответствовали формату в примере JSON
        # В примере запроса images - это список объектов с data и title.
        # В нашей БД images - это JSON-поле, содержащее {"images": [...]}
        # Пока мы просто сохраняем images_data как часть raw_data и также в отдельное поле images.
        # В будущем, логика может быть сложнее для обработки бинарных данных.

        # Если add_time есть, преобразуем его в строку ISO формата
        if data_to_save.get('add_time'):
            data_to_save['add_time'] = data_to_save['add_time'].isoformat(timespec='seconds')

        # Извлекаем данные для сохранения в pereval_added
        # raw_data будет весь JSON запрос, а images будет отдельным JSON с массивом картинок

        # Метод add_pereval в db_manager ожидает весь входящий JSON как словарь.
        # Он сам преобразует его в JSON для поля raw_data и images.
        new_pereval_id = db_manager.add_pereval(data_to_save)

        if new_pereval_id is None:
            # Если db_manager.add_pereval вернул None, значит произошла ошибка в БД
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail="Ошибка при добавлении записи в базу данных")

        # Возвращаем успешный ответ
        return {
            "status": status.HTTP_200_OK,
            "message": "Отправлено успешно",
            "id": new_pereval_id
        }

    except HTTPException as e:
        # Перехватываем наши собственные HTTPException
        raise e
    except Exception as e:
        # Перехватываем любые другие неожиданные ошибки
        print(f"Неизвестная ошибка: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Внутренняя ошибка сервера: {e}")


# --- Запуск API (только для прямого запуска файла) ---
# Это позволяет запускать API командой python main.py
if __name__ == "__main__":
    # Убедитесь, что переменные окружения установлены!
    # Если вы их не настроили через конфигурацию запуска PyCharm,
    # вы можете временно раскомментировать и установить их здесь,
    # но помните, что это не рекомендуется для продакшена.
    # os.environ['FSTR_DB_HOST'] = 'localhost'
    # os.environ['FSTR_DB_PORT'] = '5432'
    # os.environ['FSTR_DB_NAME'] = 'pereval_app'
    # os.environ['FSTR_DB_LOGIN'] = 'postgres'
    # os.environ['FSTR_DB_PASS'] = 'admin123' # Замените на ваш реальный пароль!

    # Запускаем Uvicorn
    # host="0.0.0.0" позволяет принимать запросы со всех IP-адресов
    # port=8000 - стандартный порт для FastAPI
    # reload=True - перезагружает сервер при изменении кода (удобно для разработки)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)