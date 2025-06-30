-- Таблица для хранения информации о перевалах
CREATE TABLE IF NOT EXISTS public.pereval_added (
    id SERIAL PRIMARY KEY,
    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_data JSONB, -- Для хранения всех исходных данных (user, coords, level и т.д.)
    images JSONB,   -- Для хранения списка изображений в JSON формате
    status VARCHAR(20) DEFAULT 'new' -- 'new', 'pending', 'accepted', 'rejected'
);

-- Таблица для хранения изображений (если нужно отдельное хранение, но сейчас images_json в pereval_added)
-- Если вы решите хранить изображения в отдельной таблице, эту схему нужно будет расширить.
-- Но поскольку вы храните 'images' как JSONB в 'pereval_added', отдельная таблица для них сейчас не нужна.
-- Этот комментарий оставлен для ясности, чтобы вы знали, что такой вариант возможен.

-- Таблица для справочника типов активности, если понадобится.
-- Пока не используется вашим кодом, но может быть полезной для расширения.
CREATE TABLE IF NOT EXISTS public.spr_activities_types (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) UNIQUE NOT NULL
);

-- Добавление начальных типов активности, если таблица пуста
INSERT INTO public.spr_activities_types (title) VALUES
('Пешком'), ('Лыжи'), ('Катамаран'), ('Байдарка'), ('Плот')
ON CONFLICT (title) DO NOTHING;