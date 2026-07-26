import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

TOKEN = os.environ["TELEGRAM_TOKEN"]

GROUP_ID = -5340906174

# Назва самого файлу Google Таблиці
TABLE_NAME = "облік документів"

# Назва потрібного аркуша всередині таблиці
WORKSHEET_NAME = "заявки матеріалів"

# У твоїй таблиці заявки починаються із 7-го рядка
FIRST_APPLICATION_ROW = 7


# Стани розмови
(
    NAME,
    OBJECT,
    MATERIALS,
    COMMENT,
    EDIT_CHOICE,
    EDIT_OBJECT,
    EDIT_MATERIALS,
    EDIT_COMMENT,
) = range(8)


# ============================================================
# ПІДКЛЮЧЕННЯ ДО GOOGLE ТАБЛИЦІ
# ============================================================

google_credentials = json.loads(
    os.environ["GOOGLE_CREDENTIALS_JSON"]
)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

credentials = Credentials.from_service_account_info(
    google_credentials,
    scopes=scopes,
)

google_client = gspread.authorize(credentials)

spreadsheet = google_client.open(TABLE_NAME)

worksheet = spreadsheet.worksheet(WORKSHEET_NAME)


# ============================================================
# КНОПКИ
# ============================================================

main_keyboard = ReplyKeyboardMarkup(
    [
        ["➕ Нова заявка"],
        ["✏️ Редагувати останню заявку"],
    ],
    resize_keyboard=True,
)

skip_keyboard = ReplyKeyboardMarkup(
    [["⏭️ Пропустити"], ["❌ Скасувати"]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

cancel_keyboard = ReplyKeyboardMarkup(
    [["❌ Скасувати"]],
    resize_keyboard=True,
)

edit_keyboard = ReplyKeyboardMarkup(
    [
        ["🏗️ Змінити об'єкт"],
        ["📦 Змінити матеріали"],
        ["💬 Змінити коментар"],
        ["✅ Завершити редагування"],
    ],
    resize_keyboard=True,
)


# ============================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# ============================================================

def get_current_time() -> str:
    """Повертає поточні дату й час за Києвом."""
    return datetime.now(
        ZoneInfo("Europe/Kyiv")
    ).strftime("%d.%m.%Y %H:%M")


def get_next_application_number() -> int:
    """
    Знаходить найбільший номер заявки в колонці A
    та повертає наступний.
    """
    values = worksheet.col_values(1)

    numbers = []

    for value in values[FIRST_APPLICATION_ROW - 1:]:
        if not value:
            continue

        cleaned_value = (
            str(value)
            .replace("№", "")
            .replace(" ", "")
            .strip()
        )

        try:
            numbers.append(int(float(cleaned_value)))
        except ValueError:
            continue

    if not numbers:
        return 1

    return max(numbers) + 1


def create_telegram_text(
    application_number: int,
    name: str,
    obj: str,
    materials: str,
    comment: str,
    application_date: str,
    status: str = "Нова",
) -> str:
    """Створює текст заявки для Telegram-групи."""

    return (
        f"📥 ЗАЯВКА №{application_number}\n\n"
        f"📌 Статус: {status}\n\n"
        f"👷 Хто приймає:\n{name}\n\n"
        f"🏗️ Об'єкт:\n{obj}\n\n"
        f"📦 Матеріали:\n{materials}\n\n"
        f"💬 Коментар:\n{comment}\n\n"
        f"🕒 Дата і час:\n{application_date}"
    )


def find_last_user_application(
    telegram_user_id: int,
):
    """
    Знаходить останню нову заявку конкретного працівника.

    Службові колонки:
    L — ID повідомлення в Telegram-групі
    M — Telegram ID працівника
    N — статус заявки
    """

    all_values = worksheet.get_all_values()

    for row_number in range(
        FIRST_APPLICATION_ROW,
        len(all_values) + 1,
    ):
        row = all_values[row_number - 1]

        # Доповнюємо рядок порожніми значеннями,
        # якщо в ньому менше 14 колонок
        while len(row) < 14:
            row.append("")

        saved_user_id = row[12].strip()
        status = row[13].strip()

        if (
            saved_user_id == str(telegram_user_id)
            and status.lower() == "нова"
        ):
            return {
                "row_number": row_number,
                "application_number": row[0],
                "date": row[1],
                "object": row[2],
                "name": row[3],
                "materials": row[4],
                "comment": row[10],
                "message_id": row[11],
                "status": row[13],
            }

    return None


async def show_main_menu(
    update: Update,
    text: str = "Оберіть дію:",
):
    """Показує головне меню."""

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard,
    )


async def update_group_message(
    context: ContextTypes.DEFAULT_TYPE,
):
    """Оновлює повідомлення заявки в Telegram-групі."""

    row_number = context.user_data["edit_row"]

    row = worksheet.row_values(row_number)

    while len(row) < 14:
        row.append("")

    application_number = row[0]
    application_date = row[1]
    obj = row[2]
    name = row[3]
    materials = row[4]
    comment = row[10]
    message_id = row[11]
    status = row[13] or "Нова"

    telegram_text = create_telegram_text(
        application_number=application_number,
        name=name,
        obj=obj,
        materials=materials,
        comment=comment,
        application_date=application_date,
        status=status,
    )

    if not message_id:
        print(
            "Не знайдено ID повідомлення для редагування."
        )
        return

    try:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=int(message_id),
            text=telegram_text,
        )

    except Exception as error:
        print(
            f"Помилка оновлення повідомлення "
            f"в Telegram: {error}"
        )


# ============================================================
# СТВОРЕННЯ НОВОЇ ЗАЯВКИ
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Запуск через команду /start."""

    context.user_data.clear()

    await update.message.reply_text(
        "👋 Вітаю!\n\n"
        "Введіть ваше ПІБ або ім'я:",
        reply_markup=cancel_keyboard,
    )

    return NAME


async def new_application(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Запуск нової заявки через кнопку."""

    context.user_data.clear()

    await update.message.reply_text(
        "👷 Введіть ваше ПІБ або ім'я:",
        reply_markup=cancel_keyboard,
    )

    return NAME


async def get_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["name"] = text

    await update.message.reply_text(
        "🏗️ Вкажіть назву об'єкта:",
        reply_markup=cancel_keyboard,
    )

    return OBJECT


async def get_object(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["object"] = text

    await update.message.reply_text(
        "📦 Напишіть матеріали та кількість "
        "одним повідомленням.\n\n"
        "Наприклад:\n"
        "Газоблок — 50 шт\n"
        "Клей — 8 мішків",
        reply_markup=cancel_keyboard,
    )

    return MATERIALS


async def get_materials(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["materials"] = text

    await update.message.reply_text(
        "💬 Напишіть коментар до заявки "
        "або натисніть «⏭️ Пропустити»:",
        reply_markup=skip_keyboard,
    )

    return COMMENT


async def get_comment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    comment = update.message.text.strip()

    if comment == "❌ Скасувати":
        return await cancel(update, context)

    if comment in ("⏭️ Пропустити", "-"):
        comment = "Без коментаря"

    name = context.user_data["name"]
    obj = context.user_data["object"]
    materials = context.user_data["materials"]

    application_number = get_next_application_number()
    current_time = get_current_time()

    status = "Нова"

    telegram_text = create_telegram_text(
        application_number=application_number,
        name=name,
        obj=obj,
        materials=materials,
        comment=comment,
        application_date=current_time,
        status=status,
    )

    telegram_sent = False
    table_saved = False
    group_message_id = ""

    # Спочатку відправляємо повідомлення в групу
    try:
        sent_message = await context.bot.send_message(
            chat_id=GROUP_ID,
            text=telegram_text,
        )

        group_message_id = sent_message.message_id
        telegram_sent = True

    except Exception as error:
        print(
            f"Помилка відправлення в Telegram: {error}"
        )

    # Потім додаємо заявку у 7-й рядок таблиці
    try:
        new_row = [
            application_number,          # A — №
            current_time,                # B — дата заявки
            obj,                         # C — об'єкт
            name,                        # D — хто приймає
            materials,                   # E — опис
            "",                          # F — постачальник
            "",                          # G — № рахунку
            "",                          # H — сума
            False,                       # I — оплачено
            False,                       # J — доставлено
            comment,                     # K — коментар
            group_message_id,            # L — Telegram message ID
            update.effective_user.id,    # M — Telegram user ID
            status,                      # N — статус
        ]

        worksheet.insert_row(
            new_row,
            index=FIRST_APPLICATION_ROW,
            value_input_option="USER_ENTERED",
        )

        table_saved = True

    except Exception as error:
        print(
            f"Помилка запису в Google Таблицю: {error}"
        )

    if telegram_sent and table_saved:
        answer = (
            f"✅ Заявку №{application_number} створено.\n\n"
            "Вона відправлена в групу та записана "
            "в Google Таблицю."
        )

    elif telegram_sent and not table_saved:
        answer = (
            "⚠️ Заявку відправлено в групу, "
            "але не вдалося записати в Google Таблицю."
        )

    elif not telegram_sent and table_saved:
        answer = (
            "⚠️ Заявку записано в Google Таблицю, "
            "але не вдалося відправити в групу."
        )

    else:
        answer = (
            "❌ Не вдалося відправити заявку. "
            "Спробуйте ще раз."
        )

    context.user_data.clear()

    await update.message.reply_text(
        answer,
        reply_markup=main_keyboard,
    )

    return ConversationHandler.END


# ============================================================
# РЕДАГУВАННЯ ЗАЯВКИ
# ============================================================

async def edit_last_application(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Знаходить останню заявку працівника."""

    context.user_data.clear()

    user_id = update.effective_user.id

    try:
        application = find_last_user_application(
            telegram_user_id=user_id
        )

    except Exception as error:
        print(
            f"Помилка пошуку заявки: {error}"
        )

        await update.message.reply_text(
            "❌ Не вдалося знайти заявку в таблиці.",
            reply_markup=main_keyboard,
        )

        return ConversationHandler.END

    if not application:
        await update.message.reply_text(
            "У вас немає нової заявки, "
            "яку можна редагувати.\n\n"
            "Редагувати можна лише останню заявку "
            "зі статусом «Нова».",
            reply_markup=main_keyboard,
        )

        return ConversationHandler.END

    context.user_data["edit_row"] = (
        application["row_number"]
    )

    context.user_data["edit_number"] = (
        application["application_number"]
    )

    await update.message.reply_text(
        f"✏️ Редагування заявки "
        f"№{application['application_number']}.\n\n"
        "Що потрібно змінити?",
        reply_markup=edit_keyboard,
    )

    return EDIT_CHOICE


async def edit_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    choice = update.message.text.strip()

    if choice == "🏗️ Змінити об'єкт":
        await update.message.reply_text(
            "Введіть нову назву об'єкта:",
            reply_markup=cancel_keyboard,
        )

        return EDIT_OBJECT

    if choice == "📦 Змінити матеріали":
        await update.message.reply_text(
            "Напишіть новий перелік матеріалів "
            "та кількість:",
            reply_markup=cancel_keyboard,
        )

        return EDIT_MATERIALS

    if choice == "💬 Змінити коментар":
        await update.message.reply_text(
            "Напишіть новий коментар або натисніть "
            "«⏭️ Пропустити»:",
            reply_markup=skip_keyboard,
        )

        return EDIT_COMMENT

    if choice == "✅ Завершити редагування":
        application_number = context.user_data.get(
            "edit_number",
            "",
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Редагування заявки "
            f"№{application_number} завершено.",
            reply_markup=main_keyboard,
        )

        return ConversationHandler.END

    await update.message.reply_text(
        "Оберіть потрібну дію кнопкою нижче:",
        reply_markup=edit_keyboard,
    )

    return EDIT_CHOICE


async def save_edited_object(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text(
            "Зміну об'єкта скасовано.",
            reply_markup=edit_keyboard,
        )

        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]

    try:
        # Оновлюємо лише колонку C
        worksheet.update_cell(
            row_number,
            3,
            text,
        )

        await update_group_message(
            context=context
        )

        await update.message.reply_text(
            "✅ Об'єкт оновлено.\n\n"
            "Що ще потрібно змінити?",
            reply_markup=edit_keyboard,
        )

    except Exception as error:
        print(
            f"Помилка редагування об'єкта: {error}"
        )

        await update.message.reply_text(
            "❌ Не вдалося оновити об'єкт.",
            reply_markup=edit_keyboard,
        )

    return EDIT_CHOICE


async def save_edited_materials(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text(
            "Зміну матеріалів скасовано.",
            reply_markup=edit_keyboard,
        )

        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]

    try:
        # Оновлюємо лише колонку E
        worksheet.update_cell(
            row_number,
            5,
            text,
        )

        await update_group_message(
            context=context
        )

        await update.message.reply_text(
            "✅ Матеріали оновлено.\n\n"
            "Що ще потрібно змінити?",
            reply_markup=edit_keyboard,
        )

    except Exception as error:
        print(
            f"Помилка редагування матеріалів: {error}"
        )

        await update.message.reply_text(
            "❌ Не вдалося оновити матеріали.",
            reply_markup=edit_keyboard,
        )

    return EDIT_CHOICE


async def save_edited_comment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text(
            "Зміну коментаря скасовано.",
            reply_markup=edit_keyboard,
        )

        return EDIT_CHOICE

    if text in ("⏭️ Пропустити", "-"):
        text = "Без коментаря"

    row_number = context.user_data["edit_row"]

    try:
        # Оновлюємо лише колонку K
        worksheet.update_cell(
            row_number,
            11,
            text,
        )

        await update_group_message(
            context=context
        )

        await update.message.reply_text(
            "✅ Коментар оновлено.\n\n"
            "Що ще потрібно змінити?",
            reply_markup=edit_keyboard,
        )

    except Exception as error:
        print(
            f"Помилка редагування коментаря: {error}"
        )

        await update.message.reply_text(
            "❌ Не вдалося оновити коментар.",
            reply_markup=edit_keyboard,
        )

    return EDIT_CHOICE


# ============================================================
# СКАСУВАННЯ
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=main_keyboard,
    )

    return ConversationHandler.END


# ============================================================
# ЗАПУСК БОТА
# ============================================================

app = Application.builder().token(TOKEN).build()


conversation = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),

        MessageHandler(
            filters.Regex(r"^➕ Нова заявка$"),
            new_application,
        ),

        MessageHandler(
            filters.Regex(
                r"^✏️ Редагувати останню заявку$"
            ),
            edit_last_application,
        ),
    ],

    states={
        NAME: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                get_name,
            )
        ],

        OBJECT: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                get_object,
            )
        ],

        MATERIALS: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                get_materials,
            )
        ],

        COMMENT: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                get_comment,
            )
        ],

        EDIT_CHOICE: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                edit_choice,
            )
        ],

        EDIT_OBJECT: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                save_edited_object,
            )
        ],

        EDIT_MATERIALS: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                save_edited_materials,
            )
        ],

        EDIT_COMMENT: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                save_edited_comment,
            )
        ],
    },

    fallbacks=[
        CommandHandler("cancel", cancel)
    ],

    allow_reentry=True,
)


app.add_handler(conversation)


print("Бот запущено...")


app.run_polling()