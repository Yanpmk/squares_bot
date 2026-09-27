import asyncio
import os
import random
import sqlite3
import tempfile
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler


# ============================================================
# НАСТРОЙКИ
# ============================================================

VERSION = "0.4.1"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

TIMEZONE = ZoneInfo("Europe/Moscow")

DEFAULT_LOWER_HOUR = 7
DEFAULT_UPPER_HOUR = 21

DEFAULT_MIN_MESSAGES = 3
DEFAULT_MAX_MESSAGES = 6

DEFAULT_LEARNING_INTERVAL = 1
DEFAULT_LEARNING_MODE = 1  # 1=1/day, 2=1 per N days, 3=N/day
DEFAULT_NEW_NUMBERS_PER_DAY = 1

DEFAULT_TEST_QUESTIONS = 10
DEFAULT_TEST_STRICTNESS = 2  # 1=легкая, 2=средняя, 3=сложная
DEFAULT_TEST_TIME_LIMIT = 15

# ID администраторов задаются через переменную окружения ADMIN_IDS.
# Несколько ID: 123456789,987654321
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

REVIEW_INTERVALS = [1, 2, 4, 7, 14, 30]

# Предвычисляем квадраты один раз при запуске.
SQUARES = {n: n * n for n in range(10, 101)}

MORNING_PHRASES = [
    "Доброе утро! ☀️ Сегодня в программе — немного математики и один шаг вперёд.",
    "Подъём! 📚 Квадраты уже проснулись. Теперь твоя очередь.",
    "Утро началось, а значит, память пора немного потренировать 🧠",
    "Доброе утро! Сегодняшние квадраты ждут своей очереди попасть в голову.",
    "Новый день — новая порция квадратов. Поехали 🚀",
    "☀️ Утренний брифинг: мозг включить, квадраты принять, не забыть.",
    "Доброе утро, математический отдел! 📐 Поступило новое задание.",
    "Проверка связи с памятью: раз, два… квадрат! 😄",
    "Сегодня отличный день, чтобы ещё немного приблизиться к 100².",
    "Просыпайся. У тебя сегодня важная встреча с числами 🫡",
    "☕ Кофе — по желанию. Квадраты — по расписанию.",
    "Доброе утро! Один маленький блок квадратов — и день уже продуктивнее.",
    "Математический экспресс отправляется. Следующая остановка — память 🚆",
    "Утро доброе. Квадраты тоже добрые. Особенно если их сегодня выучить 😌",
    "📢 Внимание: сегодняшний учебный материал уже на борту.",
]

EVENING_PHRASES = [
    "Добрый вечер! 🌙 Самое время проверить, что осталось в памяти.",
    "Вечерний контроль: посмотрим, насколько хорошо сегодня закрепились квадраты.",
    "День подходит к концу. Пора дать памяти небольшой экзамен 📋",
    "🌙 Учебный день завершён. Теперь слово за тобой — начинаем тест.",
    "Добрый вечер! Квадраты прошли дневную смену. Проверим результат.",
    "Время вечерней проверки. Без паники — просто отвечаем на вопросы 😎",
    "📊 Итог дня скоро станет известен. Готов к тесту?",
    "Математический диспетчер вызывает тебя на вечерний контроль 🫡",
    "День был длинным, но тест короткий. Ну… обычно 😏",
    "🌙 Пора выяснить: квадраты действительно запомнились или только сделали вид?",
    "Последний учебный пункт на сегодня: пройти тест.",
    "Добрый вечер! Давай устроим памяти небольшой техосмотр 🔧🧠",
    "Сегодняшние числа требуют отчёта. Ты знаешь процедуру.",
    "Вечерний рейс в мир квадратов отправляется прямо сейчас ✈️",
    "Так, учебный день закрываем красиво — проверяем знания.",
]



# ============================================================
# BOT / SCHEDULER
# ============================================================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=TIMEZONE)

settings_sessions = {}


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    "squares_bot.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,

            current_number INTEGER NOT NULL DEFAULT 10,

            started INTEGER NOT NULL DEFAULT 0,
            finished INTEGER NOT NULL DEFAULT 0,

            last_learning_day TEXT,

            pause_until TEXT,

            lower_hour INTEGER NOT NULL DEFAULT 7,
            upper_hour INTEGER NOT NULL DEFAULT 21,

            min_messages INTEGER NOT NULL DEFAULT 3,
            max_messages INTEGER NOT NULL DEFAULT 6,

            learning_interval INTEGER NOT NULL DEFAULT 1,
            learning_days INTEGER NOT NULL DEFAULT 0,
            learning_mode INTEGER NOT NULL DEFAULT 1,
            new_numbers_per_day INTEGER NOT NULL DEFAULT 1,
            day_start_number INTEGER NOT NULL DEFAULT 10,

            test_questions INTEGER NOT NULL DEFAULT 10,
            test_strictness INTEGER NOT NULL DEFAULT 2,
            test_time_limit INTEGER NOT NULL DEFAULT 15,

            last_morning_phrase INTEGER,
            last_evening_phrase INTEGER,

            blocked INTEGER NOT NULL DEFAULT 0,
            last_activity_at TEXT,

            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL,
            number INTEGER NOT NULL,

            correct INTEGER NOT NULL DEFAULT 0,
            wrong INTEGER NOT NULL DEFAULT 0,
            mastered INTEGER NOT NULL DEFAULT 0,

            last_seen TEXT,
            last_learning_at TEXT,

            review_stage INTEGER NOT NULL DEFAULT -1,
            next_review TEXT,

            PRIMARY KEY (user_id, number)
        )
    """)

    # Миграция старой базы: добавляем mastered, если его ещё нет.
    progress_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(progress)").fetchall()
    }

    if "mastered" not in progress_columns:
        db.execute("""
            ALTER TABLE progress
            ADD COLUMN mastered INTEGER NOT NULL DEFAULT 0
        """)

    # Миграция users для новых настроек.
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    migrations = {
        "learning_mode": "ALTER TABLE users ADD COLUMN learning_mode INTEGER NOT NULL DEFAULT 1",
        "new_numbers_per_day": "ALTER TABLE users ADD COLUMN new_numbers_per_day INTEGER NOT NULL DEFAULT 1",
        "day_start_number": "ALTER TABLE users ADD COLUMN day_start_number INTEGER NOT NULL DEFAULT 10",
        "test_questions": "ALTER TABLE users ADD COLUMN test_questions INTEGER NOT NULL DEFAULT 10",
        "test_strictness": "ALTER TABLE users ADD COLUMN test_strictness INTEGER NOT NULL DEFAULT 2",
        "test_time_limit": "ALTER TABLE users ADD COLUMN test_time_limit INTEGER NOT NULL DEFAULT 15",
        "last_morning_phrase": "ALTER TABLE users ADD COLUMN last_morning_phrase INTEGER",
        "last_evening_phrase": "ALTER TABLE users ADD COLUMN last_evening_phrase INTEGER",
        "blocked": "ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0",
        "last_activity_at": "ALTER TABLE users ADD COLUMN last_activity_at TEXT",
    }
    for column, sql in migrations.items():
        if column not in user_columns:
            db.execute(sql)

    progress_columns = {row["name"] for row in db.execute("PRAGMA table_info(progress)").fetchall()}
    if "last_learning_at" not in progress_columns:
        db.execute("ALTER TABLE progress ADD COLUMN last_learning_at TEXT")

    db.execute("""
        CREATE TABLE IF NOT EXISTS answer_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            number INTEGER NOT NULL,
            response_seconds REAL NOT NULL,
            correct INTEGER NOT NULL DEFAULT 0,
            timed_out INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            admin_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (admin_id, message_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,
            test_date TEXT NOT NULL,

            score INTEGER NOT NULL,
            questions INTEGER NOT NULL,

            created_at TEXT NOT NULL
        )
    """)

    db.commit()


# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.now(TIMEZONE)


def today_str():
    return now().date().isoformat()


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()


def is_user_paused(user_id):
    user = get_user(user_id)

    if not user:
        return False

    if not user["pause_until"]:
        return False

    pause_until = date.fromisoformat(user["pause_until"])

    if pause_until >= now().date():
        return True

    # Пауза закончилась
    db.execute("""
        UPDATE users
        SET pause_until = NULL
        WHERE user_id = ?
    """, (user_id,))
    db.commit()

    return False


# ============================================================
# KEYBOARDS
# ============================================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📝 Пройти тест"),
            KeyboardButton(text="📊 Статистика"),
        ],
        [
            KeyboardButton(text="📚 Сегодня"),
            KeyboardButton(text="⚙️ Настройки"),
        ],
        [
            KeyboardButton(text="ℹ️ Помощь"),
        ],
    ],
    resize_keyboard=True
)


settings_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🔄 Сбросить прогресс"),
            KeyboardButton(text="🗑 Очистить все данные"),
        ],
        [
            KeyboardButton(text="🕐 Время сообщений"),
            KeyboardButton(text="🔢 Количество сообщений"),
        ],
        [
            KeyboardButton(text="📚 Интенсивность"),
            KeyboardButton(text="🔢 Изменить число"),
        ],
        [
            KeyboardButton(text="📝 Настройки теста"),
            KeyboardButton(text="✉️ Написать админу"),
        ],
        [
            KeyboardButton(text="⏸ Пауза / остановка"),
        ],
        [
            KeyboardButton(text="⬅️ Назад"),
        ],
    ],
    resize_keyboard=True
)


confirm_reset_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Да, сбросить",
                callback_data="confirm_reset"
            ),
            InlineKeyboardButton(
                text="Отмена",
                callback_data="cancel_action"
            ),
        ]
    ]
)


confirm_clear_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Да, удалить всё",
                callback_data="confirm_clear"
            ),
            InlineKeyboardButton(
                text="Отмена",
                callback_data="cancel_action"
            ),
        ]
    ]
)


# ============================================================
# USER CREATION
# ============================================================

def create_user(message: Message):
    user = get_user(message.from_user.id)

    if user:
        return

    db.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        now().isoformat()
    ))

    db.commit()


def update_user_info(message: Message):
    previous = db.execute("SELECT blocked FROM users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    was_blocked = bool(previous and previous["blocked"])
    db.execute("""
        UPDATE users
        SET
            username = ?,
            first_name = ?,
            blocked = 0,
            last_activity_at = ?
        WHERE user_id = ?
    """, (
        message.from_user.username,
        message.from_user.first_name,
        now().isoformat(),
        message.from_user.id
    ))
    db.commit()

    # Если пользователь снова написал боту после блокировки, возвращаем его
    # в обычное расписание.
    if was_blocked:
        schedule_user_day(message.from_user.id)


def mark_user_activity(user_id):
    db.execute("UPDATE users SET last_activity_at = ?, blocked = 0 WHERE user_id = ?", (now().isoformat(), user_id))
    db.commit()


def mark_user_blocked(user_id):
    db.execute("UPDATE users SET blocked = 1 WHERE user_id = ?", (user_id,))
    db.commit()


def is_user_blocked(user_id):
    row = db.execute("SELECT blocked FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and row["blocked"])


async def safe_send_message(user_id, text, **kwargs):
    if is_user_blocked(user_id):
        return False
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except Exception as e:
        error_text = str(e)
        if "USER_IS_BLOCKED" in error_text or "bot was blocked" in error_text.lower() or "user is deactivated" in error_text.lower():
            mark_user_blocked(user_id)
            print(f"Пользователь {user_id} заблокировал бота или удалён — отключаем исходящие сообщения.")
        else:
            print(f"Ошибка отправки пользователю {user_id}: {e}")
        return False


# ============================================================
# LEARNING PROGRESSION
# ============================================================

def advance_learning_day(user_id):
    """Переходит к следующему учебному дню. Вызывается только дневным планировщиком."""
    user = get_user(user_id)
    if not user:
        return

    today = today_str()
    if user["last_learning_day"] == today:
        return

    if is_user_paused(user_id):
        return

    if not user["started"]:
        db.execute("""
            UPDATE users
            SET started = 1, last_learning_day = ?, learning_days = 1, day_start_number = current_number
            WHERE user_id = ?
        """, (today, user_id))
        db.commit()
        ensure_progress(user_id, user["current_number"])
        return

    if user["finished"]:
        db.execute("UPDATE users SET last_learning_day = ? WHERE user_id = ?", (today, user_id))
        db.commit()
        return

    mode = user["learning_mode"] or 1
    learning_days = user["learning_days"] + 1

    if mode == 2 and learning_days < user["learning_interval"]:
        db.execute("UPDATE users SET learning_days = ?, last_learning_day = ? WHERE user_id = ?", (learning_days, today, user_id))
        db.commit()
        return

    current = user["current_number"]
    step = user["new_numbers_per_day"] if mode == 3 else 1
    new_number = min(100, current + max(1, step))

    db.execute("""
        UPDATE users
        SET current_number = ?, learning_days = 1, last_learning_day = ?, day_start_number = ?
        WHERE user_id = ?
    """, (new_number, today, current + 1, user_id))
    if new_number >= 100:
        db.execute("UPDATE users SET finished = 1 WHERE user_id = ?", (user_id,))
    db.commit()
    for n in range(max(10, current + 1), new_number + 1):
        ensure_progress(user_id, n)


# ============================================================
# PROGRESS
# ============================================================

def ensure_progress(user_id, number):
    db.execute("""
        INSERT OR IGNORE INTO progress (
            user_id,
            number
        )
        VALUES (?, ?)
    """, (
        user_id,
        number
    ))

    db.commit()


def register_correct(user_id, number):
    ensure_progress(user_id, number)

    progress = db.execute("""
        SELECT *
        FROM progress
        WHERE user_id = ?
          AND number = ?
    """, (
        user_id,
        number
    )).fetchone()

    new_stage = progress["review_stage"]

    # Если число уже находится в интервальном повторении
    if new_stage >= 0:

        new_stage += 1

        if new_stage >= len(REVIEW_INTERVALS):
            new_stage = len(REVIEW_INTERVALS) - 1

        next_date = (
            now().date()
            + timedelta(days=REVIEW_INTERVALS[new_stage])
        ).isoformat()

        db.execute("""
            UPDATE progress
            SET
                correct = correct + 1,
                mastered = 1,
                last_seen = ?,
                review_stage = ?,
                next_review = ?
            WHERE user_id = ?
              AND number = ?
        """, (
            now().isoformat(),
            new_stage,
            next_date,
            user_id,
            number
        ))

    else:

        db.execute("""
            UPDATE progress
            SET
                correct = correct + 1,
                mastered = 1,
                last_seen = ?
            WHERE user_id = ?
              AND number = ?
        """, (
            now().isoformat(),
            user_id,
            number
        ))

    db.commit()


def register_wrong(user_id, number):
    ensure_progress(user_id, number)

    tomorrow = (
        now().date() + timedelta(days=1)
    ).isoformat()

    db.execute("""
        UPDATE progress
        SET
            wrong = wrong + 1,
            last_seen = ?,
            review_stage = 0,
            next_review = ?
        WHERE user_id = ?
          AND number = ?
    """, (
        now().isoformat(),
        tomorrow,
        user_id,
        number
    ))

    db.commit()


# ============================================================
# REVIEWS
# ============================================================

def get_due_reviews(user_id):
    today = today_str()

    rows = db.execute("""
        SELECT number
        FROM progress
        WHERE user_id = ?
          AND next_review IS NOT NULL
          AND next_review <= ?
        ORDER BY next_review ASC
    """, (
        user_id,
        today
    )).fetchall()

    return [row["number"] for row in rows]


def get_learned_numbers(user_id):
    """Возвращает числа, которые уже были введены в обучение и находятся
    до текущего числа. Текущее число ещё считается изучаемым, а не выученным.
    """
    user = get_user(user_id)
    if not user:
        return []

    current = user["current_number"]
    if user["finished"]:
        current = 101

    if current <= 10:
        return []

    return list(range(10, min(current, 101)))


def _days_since(iso_value):
    if not iso_value:
        return 999
    try:
        dt = datetime.fromisoformat(iso_value)
        return max(0, (now().date() - dt.date()).days)
    except (ValueError, TypeError):
        return 999


def get_user_average_response_time(user_id):
    row = db.execute("""
        SELECT AVG(response_seconds) AS avg_time
        FROM answer_times
        WHERE user_id = ?
    """, (user_id,)).fetchone()
    return float(row["avg_time"] or 0.0)


def get_number_average_response_time(user_id, number):
    row = db.execute("""
        SELECT AVG(response_seconds) AS avg_time, COUNT(*) AS count
        FROM answer_times
        WHERE user_id = ? AND number = ?
    """, (user_id, number)).fetchone()
    return float(row["avg_time"] or 0.0), int(row["count"] or 0)


def learning_number_score(user_id, number, user_average):
    """Чем выше score, тем вероятнее число попадёт в дневную карточку."""
    progress = db.execute("""
        SELECT * FROM progress WHERE user_id = ? AND number = ?
    """, (user_id, number)).fetchone()

    score = 1.0
    if not progress:
        return 35.0

    wrong = progress["wrong"] or 0
    correct = progress["correct"] or 0
    last_learning_days = _days_since(progress["last_learning_at"])
    last_answer_days = _days_since(progress["last_seen"])

    # Ошибки — главный фактор после обязательного квадрата дня.
    if wrong:
        score += min(80.0, wrong * 12.0)
    if progress["next_review"] and progress["next_review"] <= today_str():
        overdue_days = _days_since(progress["next_review"]) + 1
        score += 100.0 + min(100.0, overdue_days * 15.0)

    # Давно не видели — постепенно увеличиваем приоритет.
    if last_learning_days >= 1:
        score += min(45.0, last_learning_days * 3.0)
    elif last_answer_days >= 1:
        score += min(30.0, last_answer_days * 2.0)

    # Новые/редко проверявшиеся числа тоже должны получать шанс.
    if correct == 0 and wrong == 0:
        score += 35.0

    # Если число заметно медленнее личного среднего, увеличиваем вероятность.
    number_avg, samples = get_number_average_response_time(user_id, number)
    if user_average > 0 and samples >= 2 and number_avg > user_average:
        ratio = number_avg / user_average
        score += min(80.0, max(0.0, (ratio - 1.0) * 70.0))

    # Недавно показанное число немного приглушаем, чтобы не зациклиться на нём.
    if last_learning_days == 0:
        score *= 0.18

    return max(0.1, score)


def choose_learning_number(user_id):
    """Выбирает число для обычной учебной карточки.

    Квадрат дня обязателен как минимум один раз в день; остальные карточки
    выбираются по адаптивному весу из уже введённых чисел.
    """
    user = get_user(user_id)
    if not user:
        return None

    current = min(100, user["current_number"])
    today = today_str()
    day_start = user["day_start_number"] or current

    # До завершения обучения доступны все уже введённые числа.
    if not user["finished"]:
        candidates = list(range(10, current + 1))
    else:
        candidates = list(range(10, 101))

    if not candidates:
        return current

    # Если сегодня ещё не показывали квадрат дня, он всегда первый.
    day_progress = db.execute("""
        SELECT last_learning_at FROM progress
        WHERE user_id = ? AND number = ?
    """, (user_id, current)).fetchone()
    if current in candidates and (not day_progress or not day_progress["last_learning_at"] or _days_since(day_progress["last_learning_at"]) > 0):
        return current

    user_average = get_user_average_response_time(user_id)
    weights = [learning_number_score(user_id, n, user_average) for n in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def get_today_answer_count(user_id, number):
    row = db.execute("""
        SELECT COUNT(*) AS count
        FROM answer_times
        WHERE user_id = ?
          AND number = ?
          AND created_at >= ?
    """, (user_id, number, f"{today_str()}T00:00:00")).fetchone()
    return int(row["count"] or 0)


def test_number_score(user_id, number, user_average):
    """Вес числа для теста с защитой от зацикливания."""
    score = learning_number_score(user_id, number, user_average)
    today_answers = get_today_answer_count(user_id, number)

    if today_answers:
        # Проблемное число всё ещё имеет повышенный вес,
        # но каждый его повтор в этот день заметно уменьшает вероятность.
        score *= 0.20 ** min(today_answers, 4)

    return max(0.01, score)


def choose_test_numbers(user_id, count):
    user = get_user(user_id)
    if not user:
        return []

    current = min(100, user["current_number"])
    strictness = user["test_strictness"] or DEFAULT_TEST_STRICTNESS
    available = list(range(10, current + 1))

    # В сложном режиме исключаем 10, 20, 30, ..., 100.
    if strictness == 3:
        available = [n for n in available if n % 10 != 0]

    if not available:
        return []

    # Квадрат дня обязателен, кроме круглого десятка в сложном режиме.
    result = [current] if current in available else []
    candidates = [n for n in available if n not in result]
    user_average = get_user_average_response_time(user_id)

    while candidates and len(result) < count:
        weights = [test_number_score(user_id, n, user_average) for n in candidates]
        selected = random.choices(candidates, weights=weights, k=1)[0]
        result.append(selected)
        candidates.remove(selected)

    random.shuffle(result)
    return result[:min(count, len(available))]


# ============================================================
# RANDOM TIMES
# ============================================================

def generate_random_times(
    count,
    lower_hour,
    upper_hour
):
    """
    Генерирует случайные минуты.

    Между сообщениями минимум 60 минут.
    """

    start = lower_hour * 60
    end = upper_hour * 60

    if end <= start:
        return []

    max_possible = ((end - start) // 60) + 1

    count = min(count, max_possible)

    if count <= 0:
        return []

    possible = list(
        range(
            start,
            end + 1
        )
    )

    for _ in range(1000):

        result = sorted(
            random.sample(
                possible,
                count
            )
        )

        if all(
            result[i + 1] - result[i] >= 60
            for i in range(len(result) - 1)
        ):
            return result

    # Запасной вариант
    result = []

    current = start

    for _ in range(count):

        if current > end:
            break

        result.append(current)

        current += 60

    return result


# ============================================================
# LEARNING MESSAGE
# ============================================================

async def send_learning_message(user_id):
    user = get_user(user_id)

    if not user or is_user_paused(user_id) or user["blocked"]:
        return

    number = choose_learning_number(user_id)
    if number is None:
        return

    # Фиксируем именно факт показа учебной карточки, отдельно от ответа на тест.
    value = SQUARES[number]
    if random.choice([True, False]):
        text = f"📚 Запомни:\n\n{number}² = {value}"
    else:
        text = f"📚 Запомни:\n\n{value} = {number}²"

    if await safe_send_message(user_id, text):
        db.execute("""
            INSERT OR IGNORE INTO progress (user_id, number)
            VALUES (?, ?)
        """, (user_id, number))
        db.execute("""
            UPDATE progress SET last_learning_at = ?
            WHERE user_id = ? AND number = ?
        """, (now().isoformat(), user_id, number))
        db.commit()


# ============================================================
# SCHEDULING
# ============================================================

phrase_history = {}

def choose_phrase(user_id, kind, phrases):
    key = (user_id, kind)
    history = phrase_history.get(key, [])
    choices = [i for i in range(len(phrases)) if i not in history[-5:]]
    idx = random.choice(choices or list(range(len(phrases))))
    phrase_history[key] = (history + [idx])[-5:]
    return phrases[idx]


async def send_morning_message(user_id):
    user = get_user(user_id)

    if not user or is_user_paused(user_id) or user["blocked"]:
        return

    number = user["current_number"]
    start = user["day_start_number"] if user["day_start_number"] else number
    if user["learning_mode"] == 3 and start <= number and (not user["finished"] or user["last_learning_day"] == today_str()):
        nums = list(range(start, number + 1))
        squares = ", ".join(f"{n}² = {SQUARES[n]}" for n in nums)
        day_text = f"📚 Квадраты дня: {squares}"
    else:
        day_text = f"📚 Число дня: {number}² = {SQUARES[number]}"
    text = f"{choose_phrase(user_id, 'morning', MORNING_PHRASES)}\n\n{day_text}"

    await safe_send_message(user_id, text)


async def send_evening_message(user_id):
    user = get_user(user_id)

    if not user or is_user_paused(user_id) or user["blocked"]:
        return

    number = user["current_number"]
    start = user["day_start_number"] if user["day_start_number"] else number
    if user["learning_mode"] == 3 and start <= number and (not user["finished"] or user["last_learning_day"] == today_str()):
        nums = list(range(start, number + 1))
        squares = ", ".join(f"{n}² = {SQUARES[n]}" for n in nums)
        day_text = f"📚 Квадраты дня: {squares}"
    else:
        day_text = f"📚 Число дня: {number}² = {SQUARES[number]}"
    text = f"{choose_phrase(user_id, 'evening', EVENING_PHRASES)}\n\n{day_text}"

    await safe_send_message(user_id, text)


def remove_user_jobs(user_id):
    prefix = f"user_{user_id}_"

    for job in scheduler.get_jobs():

        if job.id.startswith(prefix):
            scheduler.remove_job(job.id)


def schedule_user_day(user_id, advance=False):
    remove_user_jobs(user_id)

    user = get_user(user_id)
    if not user:
        return

    if is_user_paused(user_id) or user["blocked"]:
        return

    # Переход на новый учебный день выполняется только дневным планировщиком.
    if advance:
        advance_learning_day(user_id)
    user = get_user(user_id)
    if not user:
        return

    lower_hour = user["lower_hour"]
    upper_hour = user["upper_hour"]
    min_messages = user["min_messages"]
    max_messages = user["max_messages"]

    if min_messages > max_messages:
        min_messages, max_messages = max_messages, min_messages

    current_date = now().date()
    current_time = now()

    # Утреннее сообщение — в начале выбранного окна.
    morning_time = datetime(
        current_date.year, current_date.month, current_date.day,
        lower_hour, 0, tzinfo=TIMEZONE
    )

    if morning_time > current_time:
        scheduler.add_job(
            send_morning_message, "date", run_date=morning_time,
            args=[user_id], id=f"user_{user_id}_morning"
        )

    # Вечернее сообщение — в конце выбранного окна.
    if upper_hour == 24:
        evening_time = datetime(
            current_date.year, current_date.month, current_date.day,
            0, 0, tzinfo=TIMEZONE
        ) + timedelta(days=1)
    else:
        evening_time = datetime(
            current_date.year, current_date.month, current_date.day,
            upper_hour, 0, tzinfo=TIMEZONE
        )

    if evening_time > current_time:
        scheduler.add_job(
            send_evening_message, "date", run_date=evening_time,
            args=[user_id], id=f"user_{user_id}_evening"
        )

    # Обычные обучающие сообщения.
    count = random.randint(min_messages, max_messages)
    times = generate_random_times(count, lower_hour, upper_hour)

    for index, minutes in enumerate(times):
        if minutes >= 1440:
            run_time = datetime(
                current_date.year, current_date.month, current_date.day,
                0, 0, tzinfo=TIMEZONE
            ) + timedelta(days=1)
        else:
            hour = minutes // 60
            minute = minutes % 60
            run_time = datetime(
                current_date.year, current_date.month, current_date.day,
                hour, minute, tzinfo=TIMEZONE
            )

        if run_time <= now():
            continue

        scheduler.add_job(
            send_learning_message, "date", run_date=run_time,
            args=[user_id], id=f"user_{user_id}_learning_{index}"
        )


def schedule_all_users(advance=False):
    users = db.execute(
        "SELECT user_id FROM users"
    ).fetchall()

    for user in users:
        schedule_user_day(
            user["user_id"], advance=advance
        )


# ============================================================
# /START
# ============================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):

    create_user(message)
    update_user_info(message)

    schedule_user_day(
        message.from_user.id
    )

    user = get_user(
        message.from_user.id
    )

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я помогу выучить квадраты чисел от 10 до 100.\n\n"
        f"📚 Сейчас изучаем: {user['current_number']}²\n"
        f"⏱ Интенсивность: каждые "
        f"{user['learning_interval']} дн.\n\n"
        f"В течение дня я буду присылать "
        f"карточки со случайными интервалами.\n\n"
        f"Вечером можешь пройти тест через кнопку "
        f"«📝 Пройти тест».",
        reply_markup=main_keyboard
    )


# ============================================================
# TODAY
# ============================================================

@dp.message(F.text == "📚 Сегодня")
async def today_command(message: Message):

    create_user(message)
    update_user_info(message)

    user_id = message.from_user.id

    if is_user_paused(user_id):

        user = get_user(user_id)

        await message.answer(
            f"⏸ Сейчас бот находится на паузе.\n\n"
            f"Пауза до: {user['pause_until']}"
        )

        return

    user = get_user(user_id)

    if user["finished"]:

        await message.answer(
            "🎉 Ты уже выучил все числа от 10 до 100!\n\n"
            "Теперь бот работает в режиме постоянного "
            "повторения."
        )

        return

    number = user["current_number"]

    await message.answer(
        f"📚 Сегодняшнее число:\n\n"
        f"{number}² = {SQUARES[number]}\n\n"
        f"Изучается день "
        f"{user['learning_days']} из "
        f"{user['learning_interval']}."
    )


# ============================================================
# TEST
# ============================================================

test_sessions = {}
test_timeout_tasks = {}


@dp.message(F.text == "📝 Пройти тест")
async def start_test(message: Message):

    create_user(message)
    update_user_info(message)

    user_id = message.from_user.id

    if is_user_paused(user_id):

        await message.answer(
            "⏸ Сейчас бот находится на паузе.\n"
            "Но тест всё равно можно пройти."
        )

    user = get_user(user_id)
    numbers = choose_test_numbers(user_id, user["test_questions"] if user else DEFAULT_TEST_QUESTIONS)
    if not numbers:
        await message.answer("Пока нет доступных чисел для теста.")
        return

    test_sessions[user_id] = {
        "numbers": numbers,
        "index": 0,
        "score": 0,
        "questions": len(numbers),
        "current_number": numbers[0],
        "current_type": random.randint(1, 2),
        "strictness": user["test_strictness"],
        "time_limit": user["test_time_limit"],
        "deadline": None,
        "question_started_at": None,
        "question_token": None,
        "answered": False
    }

    await send_test_question(
        user_id,
        message
    )


async def cancel_test_timeout(user_id):
    task = test_timeout_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


async def timeout_current_question(user_id, question_token):
    try:
        session = test_sessions.get(user_id)
        if not session or session.get("question_token") != question_token or session.get("answered"):
            return
        await asyncio.sleep(max(0, (session["deadline"] - now()).total_seconds()))
        session = test_sessions.get(user_id)
        if not session or session.get("question_token") != question_token or session.get("answered"):
            return
        session["answered"] = True
        number = session["current_number"]
        response_seconds = float(session.get("time_limit", DEFAULT_TEST_TIME_LIMIT))
        record_response_time(user_id, number, response_seconds, correct=False, timed_out=True)
        register_wrong(user_id, number)
        await safe_send_message(user_id, f"⏱ Время вышло!\n\nПравильный ответ: {SQUARES[number] if session['current_type'] == 1 else number}")
        await advance_test_after_answer(user_id)
    except asyncio.CancelledError:
        return
    except Exception as e:
        print(f"Ошибка таймера теста для {user_id}: {e}")


async def send_test_question(user_id, message):
    session = test_sessions[user_id]
    number = session["current_number"]
    question_type = session["current_type"]
    session["answered"] = False
    session["question_token"] = object()

    if question_type == 1:
        text = f"❓ Вопрос {session['index'] + 1}/{session['questions']}\n\n{number}² = ?"
    else:
        text = f"❓ Вопрос {session['index'] + 1}/{session['questions']}\n\n{SQUARES[number]} — квадрат какого числа?"

    await cancel_test_timeout(user_id)
    await message.answer(text)
    session["question_started_at"] = now()

    if session["strictness"] == 3:
        session["deadline"] = session["question_started_at"] + timedelta(seconds=session.get("time_limit", DEFAULT_TEST_TIME_LIMIT))
        token = session["question_token"]
        test_timeout_tasks[user_id] = asyncio.create_task(timeout_current_question(user_id, token))
    else:
        session["deadline"] = None


def record_response_time(user_id, number, response_seconds, correct, timed_out=False):
    db.execute("""
        INSERT INTO answer_times (user_id, number, response_seconds, correct, timed_out, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, number, max(0.0, response_seconds), int(correct), int(timed_out), now().isoformat()))
    db.commit()


async def advance_test_after_answer(user_id):
    session = test_sessions.get(user_id)
    if not session:
        return

    session["index"] += 1
    if session["index"] >= session["questions"]:
        score = session["score"]
        questions = session["questions"]
        db.execute("""
            INSERT INTO tests (user_id, test_date, score, questions, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, today_str(), score, questions, now().isoformat()))
        db.commit()
        await cancel_test_timeout(user_id)
        del test_sessions[user_id]
        percent = round(score / questions * 100)
        await safe_send_message(user_id, f"🏁 Тест закончен!\n\nРезультат: {score}/{questions}\nТочность: {percent}%\n\nОшибки будут автоматически повторяться по интервальной схеме.", reply_markup=main_keyboard)
        return

    session["current_number"] = session["numbers"][session["index"]]
    session["current_type"] = random.randint(1, 2)
    await send_test_question(user_id, _TestMessageProxy(user_id))


class _TestMessageProxy:
    def __init__(self, user_id):
        self.user_id = user_id

    async def answer(self, text, **kwargs):
        await safe_send_message(self.user_id, text, **kwargs)


# ============================================================
# TEST ANSWERS
# ============================================================

@dp.message()
async def all_text_handler(message: Message):

    create_user(message)
    update_user_info(message)

    user_id = message.from_user.id
    text = (message.text or "").strip()

    if user_id in ADMIN_IDS and message.reply_to_message:
        support = db.execute("""
            SELECT user_id FROM support_messages
            WHERE admin_id = ? AND message_id = ?
        """, (user_id, message.reply_to_message.message_id)).fetchone()

        if support:
            if not text:
                await message.answer("❌ Ответ пустой.")
                return
            sent = await safe_send_message(
                support["user_id"],
                f"✉️ Ответ администратора:\n\n{text}"
            )
            await message.answer(
                "✅ Ответ отправлен пользователю."
                if sent else
                "❌ Не удалось отправить ответ: пользователь заблокировал бота или аккаунт недоступен."
            )
            return

    if user_id in test_sessions:
        if text in ["⚙️ Настройки", "📊 Статистика", "📚 Сегодня", "ℹ️ Помощь", "🔢 Изменить число", "⬅️ Назад"]:
            await message.answer("⚠️ Сначала закончи текущий тест.")
            return

        session = test_sessions[user_id]
        if session.get("answered"):
            return

        # Если таймер уже перевёл тест на следующий вопрос, запоздавший update
        # от предыдущего вопроса не должен стать ответом на новый.
        question_started_at = session.get("question_started_at")
        if question_started_at and message.date:
            message_time = message.date.astimezone(TIMEZONE)
            if message_time < question_started_at:
                return

        # В сложном режиме запоздавший Telegram update тоже считается просроченным,
        # даже если asyncio-таймер ещё не успел обработать вопрос.
        if session.get("deadline") and now() >= session["deadline"]:
            session["answered"] = True
            number = session["current_number"]
            record_response_time(user_id, number, session.get("time_limit", DEFAULT_TEST_TIME_LIMIT), False, True)
            register_wrong(user_id, number)
            await cancel_test_timeout(user_id)
            await message.answer(f"⏱ Время вышло!\n\nПравильный ответ: {SQUARES[number] if session['current_type'] == 1 else number}")
            await advance_test_after_answer(user_id)
            return

        try:
            answer = int(text)
        except ValueError:
            await message.answer("Введите ответ числом.")
            return

        number = session["current_number"]
        correct_answer = SQUARES[number] if session["current_type"] == 1 else number
        strictness = session["strictness"]
        started = session.get("question_started_at", now())
        response_seconds = (now() - started).total_seconds()

        def edit_distance_le_one(a, b):
            if abs(len(a) - len(b)) > 1:
                return False
            if len(a) == len(b):
                return sum(x != y for x, y in zip(a, b)) <= 1
            if len(a) > len(b):
                a, b = b, a
            i = j = diff = 0
            while i < len(a) and j < len(b):
                if a[i] != b[j]:
                    diff += 1
                    j += 1
                    if diff > 1:
                        return False
                else:
                    i += 1
                j += 1
            return True

        is_correct = answer == correct_answer
        if session.get("correction_expected"):
            session["answered"] = True
            await cancel_test_timeout(user_id)
            record_response_time(user_id, number, response_seconds, is_correct, False)
            if is_correct:
                session["score"] += 1
                register_correct(user_id, number)
                await message.answer("✅ Исправлено! Ответ засчитан.")
            else:
                register_wrong(user_id, number)
                await message.answer(f"❌ Неправильно.\nПравильный ответ: {correct_answer}")
            session.pop("correction_expected", None)
            await advance_test_after_answer(user_id)
            return

        if not is_correct and strictness == 1 and edit_distance_le_one(str(answer), str(correct_answer)):
            session["correction_expected"] = True
            await message.answer(f"🟡 Похоже на опечатку: {answer}.\nПопробуй исправить ответ ещё раз.")
            return

        session["answered"] = True
        await cancel_test_timeout(user_id)
        record_response_time(user_id, number, response_seconds, is_correct, False)
        if is_correct:
            session["score"] += 1
            register_correct(user_id, number)
            await message.answer("✅ Правильно!")
        else:
            register_wrong(user_id, number)
            await message.answer(f"❌ Неправильно.\nПравильный ответ: {correct_answer}")
        await advance_test_after_answer(user_id)
        return

    if text.startswith("/broadcast") and user_id in ADMIN_IDS:
        payload = text.partition(" ")[2].strip()
        if payload:
            await broadcast_to_users(payload, user_id)
        else:
            admin_broadcast_sessions.add(user_id)
            await message.answer("📢 Напишите сообщение для рассылки всем пользователям.")
        return

    if text == "/admin" and user_id in ADMIN_IDS:
        await message.answer("👑 Админ-команды:\n/broadcast текст — рассылка всем\n/broadcast — затем отдельным сообщением\n/blocked — список пользователей, заблокировавших бота\n/unblock ID — снова разрешить исходящие сообщения")
        return

    if text == "/blocked" and user_id in ADMIN_IDS:
        rows = db.execute("SELECT user_id, first_name, username FROM users WHERE blocked = 1 ORDER BY user_id").fetchall()
        if not rows:
            await message.answer("🚫 Заблокировавших бота пользователей нет.")
        else:
            lines = [f"{r['user_id']} — {r['first_name'] or 'без имени'}" + (f" (@{r['username']})" if r['username'] else "") for r in rows]
            await message.answer("🚫 Заблокировали бота:\n\n" + "\n".join(lines))
        return

    if text.startswith("/unblock ") and user_id in ADMIN_IDS:
        try:
            target_id = int(text.split(maxsplit=1)[1])
            db.execute("UPDATE users SET blocked = 0 WHERE user_id = ?", (target_id,))
            db.commit()
            await message.answer(f"✅ Пользователь {target_id} снова разрешён для исходящих сообщений.")
        except ValueError:
            await message.answer("❌ Формат: /unblock ID")
        return

    if user_id in admin_broadcast_sessions and user_id in ADMIN_IDS:
        admin_broadcast_sessions.remove(user_id)
        await broadcast_to_users(text, user_id)
        return

    # --------------------------------------------------------
    # НАСТРОЙКИ
    # --------------------------------------------------------

    if text == "⚙️ Настройки":

        await message.answer(
            "⚙️ Настройки",
            reply_markup=settings_keyboard
        )

        return

    if text == "⬅️ Назад":

        await message.answer(
            "Главное меню:",
            reply_markup=main_keyboard
        )

        return

    if text == "🕐 Время сообщений":

        settings_sessions[user_id] = "time"

        user = get_user(user_id)

        await message.answer(
            f"🕐 Время сообщений\n\n"
            f"Сейчас: {user['lower_hour']:02d}:00 — "
            f"{user['upper_hour']:02d}:00\n\n"
            f"Введите два часа через пробел.\n"
            f"Например:\n"
            f"8 22"
        )

        return

    if text == "🔢 Количество сообщений":

        settings_sessions[user_id] = "messages"

        user = get_user(user_id)

        await message.answer(
            f"🔢 Количество сообщений\n\n"
            f"Сейчас: от {user['min_messages']} "
            f"до {user['max_messages']} в день.\n\n"
            f"Введите минимум и максимум.\n"
            f"Например:\n"
            f"3 6"
        )

        return

    if text == "📚 Интенсивность":
        settings_sessions[user_id] = "intensity"
        user = get_user(user_id)
        await message.answer(
            "📚 Интенсивность обучения\n\n"
            f"Сейчас режим: {user['learning_mode']}.\n\n"
            "Выберите режим сообщением:\n"
            "1 — 1 квадрат в день\n"
            "2 N — 1 квадрат раз в N дней\n"
            "3 N — N квадратов в день\n\n"
            "Примеры: 2 3 или 3 4"
        )
        return

    if text == "📝 Настройки теста":
        settings_sessions[user_id] = "test"
        user = get_user(user_id)
        await message.answer(
            "📝 Настройки теста\n\n"
            f"Вопросов: {user['test_questions']}\n"
            f"Строгость: {user['test_strictness']}\n"
            f"Лимит сложного режима: {user['test_time_limit']} сек.\n\n"
            "Введите: количество вопросов и режим (1/2/3).\n"
            "Например: 10 2\n\n"
            "В сложном режиме можно добавить третье число — лимит секунд: 10 3 15"
        )
        return

    if text == "✉️ Написать админу":
        settings_sessions[user_id] = "admin_message"
        await message.answer("✉️ Напишите сообщение. Я передам его администратору.")
        return

    if text == "🔢 Изменить число":
        settings_sessions[user_id] = "number"
        user = get_user(user_id)
        await message.answer(
            f"🔢 Изменить текущее число\n\n"
            f"Сейчас: {user['current_number']}²\n\n"
            f"Введите число от 10 до 100.\n"
            f"Например: 12"
        )
        return

    if text == "⏸ Пауза / остановка":

        settings_sessions[user_id] = "pause"

        await message.answer(
            "⏸ Пауза / остановка\n\n"
            "Введите:\n\n"
            "1 — пауза на 1 день\n"
            "3 — пауза на 3 дня\n"
            "7 — пауза на 7 дней\n"
            "0 — остановить практически навсегда\n"
            "resume — продолжить обучение"
        )

        return

    if text == "🔄 Сбросить прогресс":

        await message.answer(
            "⚠️ Сбросить весь прогресс обучения?\n\n"
            "Настройки бота при этом сохранятся.",
            reply_markup=confirm_reset_keyboard
        )

        return

    if text == "🗑 Очистить все данные":

        await message.answer(
            "⚠️ УДАЛИТЬ ВСЕ ДАННЫЕ?\n\n"
            "Будет удалено:\n"
            "• прогресс\n"
            "• статистика тестов\n"
            "• текущий номер\n"
            "• настройки\n\n"
            "Действие нельзя отменить.",
            reply_markup=confirm_clear_keyboard
        )

        return

    # --------------------------------------------------------
    # SETTINGS INPUT
    # --------------------------------------------------------

    if user_id in settings_sessions:

        action = settings_sessions[user_id]

        # Время
        if action == "time":

            try:
                parts = text.split()

                if len(parts) != 2:
                    raise ValueError

                lower = int(parts[0])
                upper = int(parts[1])

                if not (
                    0 <= lower < 24
                    and 0 <= upper <= 24
                    and lower < upper
                ):
                    raise ValueError

                if upper - lower < 1:
                    raise ValueError

                db.execute("""
                    UPDATE users
                    SET
                        lower_hour = ?,
                        upper_hour = ?
                    WHERE user_id = ?
                """, (
                    lower,
                    upper,
                    user_id
                ))

                db.commit()

                schedule_user_day(user_id)

                del settings_sessions[user_id]

                await message.answer(
                    f"✅ Время изменено:\n"
                    f"{lower:02d}:00 — {upper:02d}:00",
                    reply_markup=settings_keyboard
                )

            except ValueError:

                await message.answer(
                    "❌ Неверный формат.\n\n"
                    "Например: 8 22"
                )

            return

        # Количество сообщений
        if action == "messages":

            try:
                parts = text.split()

                if len(parts) != 2:
                    raise ValueError

                minimum = int(parts[0])
                maximum = int(parts[1])

                if not (
                    1 <= minimum <= maximum <= 20
                ):
                    raise ValueError

                user = get_user(user_id)

                # Проверяем, что окно времени позволяет
                # разместить нужное количество сообщений
                available_hours = (
                    user["upper_hour"]
                    - user["lower_hour"]
                )

                max_possible = available_hours + 1

                if maximum > max_possible:

                    await message.answer(
                        f"❌ Слишком много сообщений "
                        f"для текущего временного окна.\n\n"
                        f"Максимум при интервале 60 минут: "
                        f"{max_possible}\n\n"
                        f"Сначала увеличьте время "
                        f"сообщений."
                    )

                    return

                db.execute("""
                    UPDATE users
                    SET
                        min_messages = ?,
                        max_messages = ?
                    WHERE user_id = ?
                """, (
                    minimum,
                    maximum,
                    user_id
                ))

                db.commit()

                schedule_user_day(user_id)

                del settings_sessions[user_id]

                await message.answer(
                    f"✅ Количество сообщений:\n"
                    f"{minimum}–{maximum} в день.",
                    reply_markup=settings_keyboard
                )

            except ValueError:

                await message.answer(
                    "❌ Неверный формат.\n\n"
                    "Например: 3 6"
                )

            return

        # Интенсивность
        if action == "intensity":
            try:
                parts = text.split()
                if len(parts) not in (1, 2) or int(parts[0]) not in (1, 2, 3):
                    raise ValueError
                mode = int(parts[0])
                value = int(parts[1]) if len(parts) == 2 else 1
                if mode == 1:
                    interval, per_day = 1, 1
                elif mode == 2:
                    if not 1 <= value <= 30: raise ValueError
                    interval, per_day = value, 1
                else:
                    if not 1 <= value <= 20: raise ValueError
                    interval, per_day = 1, value
                db.execute("""UPDATE users SET learning_mode=?, learning_interval=?, new_numbers_per_day=? WHERE user_id=?""", (mode, interval, per_day, user_id))
                db.commit()
                schedule_user_day(user_id)
                del settings_sessions[user_id]
                descriptions = {1: "1 квадрат в день", 2: f"1 квадрат раз в {interval} дн.", 3: f"{per_day} квадратов в день"}
                await message.answer(f"✅ Режим изменён: {descriptions[mode]}.", reply_markup=settings_keyboard)
            except ValueError:
                await message.answer("❌ Формат: 1, 2 N или 3 N. Например: 3 4")
            return

        # Настройки теста
        if action == "test":
            try:
                parts = text.split()
                if len(parts) not in (2,3): raise ValueError
                questions, strictness = int(parts[0]), int(parts[1])
                limit = int(parts[2]) if len(parts) == 3 else DEFAULT_TEST_TIME_LIMIT
                if not 1 <= questions <= 50 or strictness not in (1,2,3): raise ValueError
                if strictness == 3 and not 5 <= limit <= 120: raise ValueError
                db.execute("""UPDATE users SET test_questions=?, test_strictness=?, test_time_limit=? WHERE user_id=?""", (questions, strictness, limit, user_id))
                db.commit(); del settings_sessions[user_id]
                names={1:"лёгкая",2:"средняя",3:"сложная"}
                await message.answer(f"✅ Настройки теста сохранены.\nВопросов: {questions}\nСтрогость: {names[strictness]}" + (f"\nЛимит: {limit} сек." if strictness==3 else ""), reply_markup=settings_keyboard)
            except ValueError:
                await message.answer("❌ Формат: 10 2 или 10 3 15. Вопросов 1–50, режим 1–3, сложный лимит 5–120 сек.")
            return

        if action == "admin_message":
            settings_sessions.pop(user_id, None)
            if not ADMIN_IDS:
                await message.answer("❌ Администратор ещё не настроен.", reply_markup=settings_keyboard)
                return
            text_to_admin = (
                f"✉️ Сообщение от пользователя\n\n"
                f"ID: {user_id}\n"
                f"Имя: {message.from_user.full_name}\n"
                f"Username: @{message.from_user.username or 'нет'}\n\n"
                f"{text}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    sent = await bot.send_message(admin_id, text_to_admin)
                    db.execute("""
                        INSERT OR REPLACE INTO support_messages
                        (admin_id, message_id, user_id, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (admin_id, sent.message_id, user_id, now().isoformat()))
                    db.commit()
                except Exception as e:
                    print(f"Ошибка отправки админу {admin_id}: {e}")
            await message.answer("✅ Сообщение отправлено администратору. Ответ можно отправить Reply на это сообщение.", reply_markup=settings_keyboard)
            return

        # Изменение текущего числа
        if action == "number":
            try:
                new_number = int(text)
                if not 10 <= new_number <= 100:
                    raise ValueError

                user = get_user(user_id)

                # При прыжке вперёд пропущенные числа считаются выученными.
                if new_number > user["current_number"]:
                    for number in range(user["current_number"], new_number):
                        ensure_progress(user_id, number)
                        db.execute("""
                            UPDATE progress
                            SET mastered = 1
                            WHERE user_id = ? AND number = ?
                        """, (user_id, number))

                db.execute("""
                    UPDATE users
                    SET current_number = ?,
                        started = 1,
                        finished = ?,
                        last_learning_day = NULL,
                        learning_days = 1,
                        day_start_number = ?
                    WHERE user_id = ?
                """, (
                    new_number,
                    1 if new_number == 100 else 0,
                    new_number,
                    user_id
                ))

                ensure_progress(user_id, new_number)
                db.commit()

                schedule_user_day(user_id)
                del settings_sessions[user_id]

                await message.answer(
                    f"✅ Текущее число изменено на {new_number}².\n\n"
                    f"📚 {new_number}² = {SQUARES[new_number]}\n\n"
                    f"Предыдущие числа сохранены в прогрессе.",
                    reply_markup=settings_keyboard
                )

            except ValueError:
                await message.answer(
                    "❌ Введите целое число от 10 до 100.\n\n"
                    "Например: 12"
                )
            return

        # Пауза
        if action == "pause":

            if text.lower() == "resume":

                db.execute("""
                    UPDATE users
                    SET pause_until = NULL, last_learning_day = ?
                    WHERE user_id = ?
                """, (today_str(), user_id))

                db.commit()

                schedule_user_day(user_id)

                del settings_sessions[user_id]

                await message.answer(
                    "▶️ Обучение возобновлено.",
                    reply_markup=settings_keyboard
                )

                return

            try:

                days = int(text)

                if days < 0:
                    raise ValueError

                if days == 0:

                    pause_until = (
                        now().date()
                        + timedelta(days=3650)
                    ).isoformat()

                    db.execute("""
                        UPDATE users
                        SET pause_until = ?
                        WHERE user_id = ?
                    """, (
                        pause_until,
                        user_id
                    ))

                    db.commit()

                    remove_user_jobs(user_id)

                    del settings_sessions[user_id]

                    await message.answer(
                        "⏹ Обучение остановлено.\n\n"
                        "Чтобы продолжить, введи "
                        "resume в меню паузы.",
                        reply_markup=settings_keyboard
                    )

                    return

                pause_until = (
                    now().date()
                    + timedelta(days=days)
                ).isoformat()

                db.execute("""
                    UPDATE users
                    SET pause_until = ?
                    WHERE user_id = ?
                """, (
                    pause_until,
                    user_id
                ))

                db.commit()

                remove_user_jobs(user_id)

                del settings_sessions[user_id]

                await message.answer(
                    f"⏸ Обучение приостановлено "
                    f"на {days} дн.\n\n"
                    f"Возобновление: {pause_until}",
                    reply_markup=settings_keyboard
                )

            except ValueError:

                await message.answer(
                    "❌ Введите количество дней "
                    "или resume."
                )

            return

    # --------------------------------------------------------
    # СТАТИСТИКА
    # --------------------------------------------------------

    if text == "📊 Статистика":

        user = get_user(user_id)

        progress = db.execute("""
            SELECT
                SUM(correct) AS correct,
                SUM(wrong) AS wrong
            FROM progress
            WHERE user_id = ?
        """, (
            user_id,
        )).fetchone()

        tests = db.execute("""
            SELECT
                COUNT(*) AS count,
                SUM(score) AS score,
                SUM(questions) AS questions
            FROM tests
            WHERE user_id = ?
        """, (
            user_id,
        )).fetchone()

        correct = progress["correct"] or 0
        wrong = progress["wrong"] or 0

        total_answers = correct + wrong

        if total_answers:
            accuracy = round(
                correct / total_answers * 100
            )
        else:
            accuracy = 0

        # "Выучено" здесь означает количество чисел, которые уже прошли
        # этап введения. Текущее число ещё изучается.
        learned = max(0, min(91, user["current_number"] - 10))
        if user["finished"]:
            learned = 91

        await message.answer(
            f"📊 Статистика\n\n"
            f"📚 Введено в обучение: {learned}/91\n"
            f"🔢 Текущее число: "
            f"{user['current_number']}\n\n"
            f"✅ Правильных ответов: {correct}\n"
            f"❌ Ошибок: {wrong}\n"
            f"🎯 Общая точность: {accuracy}%\n"
            f"⏱ Среднее время ответа: {avg_response_text}\n\n"
            f"📝 Тестов пройдено: "
            f"{tests['count'] or 0}"
        )

        return

    # --------------------------------------------------------
    # ПОМОЩЬ
    # --------------------------------------------------------

    if text == "ℹ️ Помощь":

        await message.answer(
            "ℹ️ Как работает бот\n\n"
            "📚 Каждый день я присылаю несколько "
            "карточек с квадратами.\n\n"
            "📝 Через «Пройти тест» можно проверить "
            "знания.\n\n"
            "❌ Если ошибся, число повторится "
            "на следующий день.\n\n"
            "После правильного ответа интервалы "
            "увеличиваются:\n"
            "1 → 2 → 4 → 7 → 14 → 30 дней.\n\n"
            "⚙️ В настройках можно изменить:\n"
            "• время сообщений\n"
            "• количество сообщений\n"
            "• интенсивность обучения\n"
            "• изменить текущее число\n"
            "• поставить паузу\n"
            "• сбросить прогресс"
        )

        return


# ============================================================
# CONFIRMATION CALLBACKS
# ============================================================

@dp.callback_query(F.data == "confirm_reset")
async def confirm_reset(callback):

    user_id = callback.from_user.id

    db.execute("""
        DELETE FROM progress
        WHERE user_id = ?
    """, (
        user_id,
    ))

    db.execute("""
        DELETE FROM tests
        WHERE user_id = ?
    """, (
        user_id,
    ))
    db.execute("DELETE FROM answer_times WHERE user_id = ?", (user_id,))

    db.execute("""
        UPDATE users
        SET
            current_number = 10,
            started = 0,
            finished = 0,
            last_learning_day = NULL,
            pause_until = NULL,
            learning_days = 0
        WHERE user_id = ?
    """, (
        user_id,
    ))

    db.commit()

    settings_sessions.pop(
        user_id,
        None
    )

    schedule_user_day(user_id)

    await callback.message.edit_text(
        "✅ Прогресс полностью сброшен.\n\n"
        "Настройки сохранены.\n"
        "Начинаем снова с 10²."
    )

    await callback.answer()


@dp.callback_query(F.data == "confirm_clear")
async def confirm_clear(callback):

    user_id = callback.from_user.id

    db.execute("""
        DELETE FROM progress
        WHERE user_id = ?
    """, (
        user_id,
    ))

    db.execute("""
        DELETE FROM tests
        WHERE user_id = ?
    """, (
        user_id,
    ))
    db.execute("DELETE FROM answer_times WHERE user_id = ?", (user_id,))

    db.execute("""
        UPDATE users
        SET
            current_number = 10,
            started = 0,
            finished = 0,
            last_learning_day = NULL,
            pause_until = NULL,

            lower_hour = ?,
            upper_hour = ?,

            min_messages = ?,
            max_messages = ?,

            learning_interval = ?,
            learning_days = 0,
            learning_mode = ?,
            new_numbers_per_day = ?,
            day_start_number = 10,
            test_questions = ?,
            test_strictness = ?,
            test_time_limit = ?,
            last_morning_phrase = NULL,
            last_evening_phrase = NULL,
            blocked = 0,
            last_activity_at = ?
        WHERE user_id = ?
    """, (
        DEFAULT_LOWER_HOUR,
        DEFAULT_UPPER_HOUR,

        DEFAULT_MIN_MESSAGES,
        DEFAULT_MAX_MESSAGES,

        DEFAULT_LEARNING_INTERVAL,
        DEFAULT_LEARNING_MODE,
        DEFAULT_NEW_NUMBERS_PER_DAY,
        DEFAULT_TEST_QUESTIONS,
        DEFAULT_TEST_STRICTNESS,
        DEFAULT_TEST_TIME_LIMIT,
        now().isoformat(),

        user_id
    ))

    db.commit()

    settings_sessions.pop(
        user_id,
        None
    )

    remove_user_jobs(user_id)

    schedule_user_day(user_id)

    await callback.message.edit_text(
        "🗑 Все данные удалены.\n\n"
        "Бот полностью сброшен "
        "до первоначального состояния."
    )

    await callback.answer()


@dp.callback_query(F.data == "cancel_action")
async def cancel_action(callback):

    await callback.message.edit_text(
        "❎ Действие отменено."
    )

    await callback.answer()


# ============================================================
# ADMIN / SUPPORT / BACKUP
# ============================================================

admin_broadcast_sessions = set()

async def broadcast_to_users(text, admin_id):
    users = db.execute("SELECT user_id FROM users WHERE blocked = 0").fetchall()
    sent = failed = 0
    for row in users:
        try:
            if await safe_send_message(row["user_id"], f"📢 Сообщение от администратора\n\n{text}"):
                sent += 1
        except Exception as e:
            failed += 1
            print(f"Broadcast error {row['user_id']}: {e}")
    await bot.send_message(admin_id, f"📢 Рассылка завершена. Отправлено: {sent}. Ошибок: {failed}.")

async def weekly_telemetry():
    if not ADMIN_IDS:
        print("[TELEMETRY] ADMIN_IDS не настроен")
        return
    week_ago = (now() - timedelta(days=7)).isoformat()
    row = db.execute("""
        SELECT
            SUM(CASE WHEN blocked = 0 AND last_activity_at IS NOT NULL AND last_activity_at >= ? THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS new_users,
            SUM(CASE WHEN blocked = 1 THEN 1 ELSE 0 END) AS blocked_users,
            COUNT(*) AS total_users
        FROM users
    """, (week_ago, week_ago)).fetchone()
    text = (
        "📈 Еженедельная телеметрия\n\n"
        f"👥 Активных за 7 дней: {row['active'] or 0}\n"
        f"🆕 Новых за 7 дней: {row['new_users'] or 0}\n"
        f"🚫 Заблокировали бота: {row['blocked_users'] or 0}\n"
        f"👤 Всего зарегистрировано: {row['total_users'] or 0}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            print(f"Telemetry send error {admin_id}: {e}")


async def weekly_backup():
    if not ADMIN_IDS:
        print("[BACKUP] ADMIN_IDS не настроен")
        return
    fd, path = tempfile.mkstemp(prefix="squares_backup_", suffix=".db")
    os.close(fd)
    try:
        backup_db = sqlite3.connect(path)
        with backup_db:
            db.backup(backup_db)
        backup_db.close()
        filename = f"squares_bot_backup_{now().strftime('%Y-%m-%d')}.db"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_document(admin_id, FSInputFile(path, filename=filename), caption=f"🗄 Еженедельный бэкап базы от {today_str()}")
            except Exception as e:
                print(f"Backup send error {admin_id}: {e}")
    finally:
        try: os.remove(path)
        except OSError: pass


# ============================================================
# MIDNIGHT RESCHEDULER
# ============================================================

async def daily_scheduler_task():

    print(
        f"[{now()}] Новый день — "
        f"пересоздаю расписание."
    )

    schedule_all_users(advance=True)


# ============================================================
# MAIN
# ============================================================

async def main():

    init_db()

    scheduler.add_job(
        daily_scheduler_task,
        "cron",
        hour=0,
        minute=1,
        id="daily_scheduler",
        replace_existing=True
    )

    scheduler.add_job(
        weekly_backup,
        "cron",
        day_of_week="sun",
        hour=21,
        minute=0,
        id="weekly_backup",
        replace_existing=True
    )

    scheduler.add_job(
        weekly_telemetry,
        "cron",
        day_of_week="sun",
        hour=21,
        minute=0,
        id="weekly_telemetry",
        replace_existing=True
    )

    scheduler.start()

    # При запуске не двигаем обучение вперёд: иначе перезапуск бота в течение дня
    # мог ошибочно считаться новым учебным днём.
    schedule_all_users(advance=False)

    print("Bot started.")

    try:
        await dp.start_polling(bot)

    finally:

        scheduler.shutdown()

        db.close()


if __name__ == "__main__":
    asyncio.run(main())
