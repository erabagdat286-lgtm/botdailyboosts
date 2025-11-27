import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Используем СИНХРОННЫЙ клиент Google Gemini
from google import genai
from google.genai import types

# ================= КОНФИГУРАЦИЯ =================

# Вставьте свой токен Telegram
TELEGRAM_TOKEN = "8515672629:AAGJzVCydEjIqzc5FRy49PRZlXEo96LxprY"

# Вставьте свой API-ключ Gemini
GEMINI_API_KEY = "AIzaSyBC9sFnr5rky63FG9Jftv2i1KPnnbHHvWI" 

# Установите в False для активации Gemini
USE_MOCK_AI = False 

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Инициализация Gemini клиента (используем СИНХРОННЫЙ клиент!)
if not USE_MOCK_AI:
    try:
        # Используем genai.Client, чтобы избежать ошибки с AsyncClient
        external_client = genai.Client(api_key=GEMINI_API_KEY) 
    except Exception as e:
        logging.error(f"Ошибка инициализации Gemini: {e}. Переход в Mock-режим.")
        USE_MOCK_AI = True
        external_client = None
else:
    external_client = None 

# База данных (SQLite)
DB_FILE = "bot_database.db"

# ================= КОНЕЧНЫЕ АВТОМАТЫ (FSM) =================

class UserStates(StatesGroup):
    waiting_for_time = State()
    waiting_for_topic = State()

# ================= ФУНКЦИИ ИНИЦИАЛИЗАЦИИ И БАЗЫ ДАННЫХ =================

def init_db():
    """Создаем таблицу пользователей, если её нет"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                topic TEXT DEFAULT 'Мотивация и успех',
                notification_time TEXT DEFAULT '09:00'
            )
        ''')
        conn.commit()

# ================= ЛОГИКА AI (ИНТЕГРАЦИЯ GEMINI) =================

async def generate_wish(topic):
    """
    Генерация текста с использованием СИНХРОННОГО Gemini API, 
    обернутая в асинхронный вызов через asyncio.to_thread().
    """
    
    if USE_MOCK_AI or external_client is None:
        return f"🤖 (Тест) Умное напутствие на сегодня по теме '{topic}': Фокусируйся на процессе, а не на результате. Используется Mock-режим. Проверьте ключ API."
    
    # 1. Системная инструкция
    system_instruction = (
        "Ты — высокоэмпатичный и мудрый компаньон. Твоя задача — "
        "каждый день давать пользователю свежее, уникальное и действительно "
        "полезное напутствие. Напиши сообщение объемом 1-3 предложения. Ответ только на русском языке."
    )
    
    # 2. Объединяем системный промпт и пользовательский запрос в одну строку
    full_prompt = (
        f"Системная инструкция: {system_instruction}. "
        f"Сгенерируй напутствие по теме: {topic}"
    )

    # 3. ФОРМИРОВАНИЕ СТРУКТУРЫ ЗАПРОСА (ОКОНЧАТЕЛЬНО ИСПРАВЛЕНО)
    messages = [
        types.Content(role="user", parts=[
            # ИСПОЛЬЗУЕМ ПРЯМОЙ КОНСТРУКТОР types.Part, который не вызывает TypeError.
            types.Part(text=full_prompt) 
        ])
    ]
    
    try:
        # 4. Вызов синхронного метода в отдельном потоке
        response = await asyncio.to_thread(
            external_client.models.generate_content,
            model='gemini-2.5-flash', 
            contents=messages
        )
        
        return response.text
        
    except Exception as e:
        logging.error(f"Ошибка Gemini API во время запроса: {e}")
        return "Сегодня просто желаю тебе хорошего дня! (Ошибка связи с Gemini. Попробуй позже)."
    
# ================= ОБРАБОТЧИКИ КОМАНД (FSM) =================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    
    await message.answer(
        "👋 Привет! Я твой личный AI-компаньон Gemini. Моя цель — давать тебе вдохновение.\n\n"
        "**Команды для настройки:**\n"
        "⏰ /time — изменить время уведомлений.\n"
        "💡 /topic — изменить тему напутствий.\n"
        "🔍 /check — получить сообщение прямо сейчас (для теста)."
    )

## УСТАНОВКА ВРЕМЕНИ 
@dp.message(Command("time"))
async def cmd_time(message: Message, state: FSMContext):
    await state.set_state(UserStates.waiting_for_time)
    await message.answer("⏰ Напиши мне новое время уведомлений в формате **ЧЧ:ММ** (например, `14:30`).")

@dp.message(UserStates.waiting_for_time)
async def process_time_input(message: Message, state: FSMContext):
    time_str = message.text.strip()
    
    try:
        datetime.strptime(time_str, "%H:%M")
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("UPDATE users SET notification_time = ? WHERE user_id = ?", (time_str, message.from_user.id))
            conn.commit()
        
        await message.answer(f"✅ Время уведомлений обновлено на: **{time_str}**")
        await state.clear() 
        
    except ValueError:
        await message.answer("⚠️ Неверный формат. Пожалуйста, используй **ЧЧ:ММ** (например `08:00`).")

## УСТАНОВКА ТЕМЫ 
@dp.message(Command("topic"))
async def cmd_topic(message: Message, state: FSMContext):
    await state.set_state(UserStates.waiting_for_topic)
    await message.answer("💡 Напиши тему, в которой тебе нужна поддержка (например: `Изучение Python`, `Медитация`).")

@dp.message(UserStates.waiting_for_topic)
async def process_topic_input(message: Message, state: FSMContext):
    new_topic = message.text.strip()
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET topic = ? WHERE user_id = ?", (new_topic, message.from_user.id))
        conn.commit()
            
    await message.answer(f"✅ Тема обновлена! Теперь я буду давать напутствия про: **{new_topic}**")
    await state.clear() 

## ТЕСТОВАЯ ОТПРАВКА
@dp.message(Command("check"))
async def cmd_check(message: Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.execute("SELECT topic FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
    if row:
        topic = row[0]
        text = await generate_wish(topic)
        await message.answer(text)
    else:
        await message.answer("Сначала нажми /start")

## ОБРАБОТКА ДРУГОГО ТЕКСТА
@dp.message()
async def handle_unexpected_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await message.answer("Пожалуйста, следуй инструкции для текущей настройки.")
    else:
        await message.answer("Я бот-помощник. Для настроек используй команды /time или /topic.")


# ================= ПЛАНИРОВЩИК (SCHEDULER) =================

async def check_and_send_messages():
    """Эта функция запускается каждую минуту для проверки времени"""
    now_time = datetime.now().strftime("%H:%M")
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.execute("SELECT user_id, topic FROM users WHERE notification_time = ?", (now_time,))
        users_to_notify = cursor.fetchall()
    
    if users_to_notify:
        logging.info(f"⏰ Время {now_time}. Отправляем сообщения {len(users_to_notify)} пользователям.")
        for user_id, topic in users_to_notify:
            text = await generate_wish(topic)
            try:
                await bot.send_message(user_id, text)
            except Exception as e:
                logging.error(f"Не удалось отправить юзеру {user_id}: {e}")

# ================= ЗАПУСК =================

async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    init_db()
    
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_messages, 'interval', minutes=1)
    scheduler.start()
    
    logging.info("🚀 Бот запущен! Ожидание входящих сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен вручную.")