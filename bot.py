import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import ReplyKeyboardMarkup, Update
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

TABLE_NAME = "облік документів"
WORKSHEET_NAME = "заявки матеріалів"

FIRST_APPLICATION_ROW = 7


# Колонки Google Таблиці
COL_NUMBER = 1            # A — №
COL_DATE = 2              # B — дата заявки
COL_OBJECT = 3            # C — об'єкт
COL_NAME = 4              # D — хто приймає
COL_MATERIALS = 5         # E — опис
COL_SUPPLIER = 6          # F — постачальник
COL_INVOICE_NUMBER = 7    # G — № рахунку
COL_AMOUNT = 8            # H — сума
COL_PAID = 9              # I — оплачено
COL_DELIVERED = 10        # J — доставлено
COL_RECEIVED_DATE = 11    # K — дата отримання
COL_DELIVERY_NOTE = 12    # L — накладна
COL_COMMENT = 13          # M — коментар

# Службові колонки
COL_GROUP_MESSAGE_ID = 14 # N
COL_USER_ID = 15          # O
COL_STATUS = 16           # P


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
    RECEIPT_NUMBER,
    RECEIPT_FILE,
) = range(10)


# ============================================================
# GOOGLE ТАБЛИЦЯ
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
        ["📦 Товар отримано"],
    ],
    resize_keyboard=True,
)

skip_keyboard = ReplyKeyboardMarkup(
    [
        ["⏭️ Пропустити"],
        ["❌ Скасувати"],
    ],
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
    return datetime.now(
        ZoneInfo("Europe/Kyiv")
    ).strftime("%d.%m.%Y %H:%M")


def get_next_application_number() -> int:
    values = worksheet.col_values(COL_NUMBER)

    numbers = []

    for value in values[FIRST_APPLICATION_ROW - 1:]:
        cleaned_value = (
            str(value)
            .replace("№", "")
            .replace(" ", "")
            .strip()
        )

        if not cleaned_value:
            continue

        try:
            numbers.append(int(float(cleaned_value)))
        except ValueError:
            continue

    return max(numbers) + 1 if numbers else 1


def create_telegram_text(
    application_number,
    name,
    obj,
    materials,
    comment,
    application_date,
    status="Нова",
):
    return (
        f"📥 ЗАЯВКА №{application_number}\n\n"
        f"📌 Статус: {status}\n\n"
        f"👷 Хто приймає:\n{name}\n\n"
        f"🏗️ Об'єкт:\n{obj}\n\n"
        f"📦 Матеріали:\n{materials}\n\n"
        f"💬 Коментар:\n{comment}\n\n"
        f"🕒 Дата і час:\n{application_date}"
    )


def find_application_by_number(application_number: str):
    all_values = worksheet.get_all_values()

    searched_number = (
        str(application_number)
        .replace("№", "")
        .replace(" ", "")
        .strip()
    )

    for row_number in range(
        FIRST_APPLICATION_ROW,
        len(all_values) + 1,
    ):
        row = all_values[row_number - 1]

        if not row:
            continue

        saved_number = (
            str(row[0])
            .replace("№", "")
            .replace(" ", "")
            .strip()
        )

        if saved_number == searched_number:
            while len(row) < COL_STATUS:
                row.append("")

            return {
                "row_number": row_number,
                "number": row[COL_NUMBER - 1],
                "date": row[COL_DATE - 1],
                "object": row[COL_OBJECT - 1],
                "name": row[COL_NAME - 1],
                "materials": row[COL_MATERIALS - 1],
                "comment": row[COL_COMMENT - 1],
                "message_id": row[COL_GROUP_MESSAGE_ID - 1],
                "user_id": row[COL_USER_ID - 1],
                "status": row[COL_STATUS - 1],
            }

    return None


def find_last_user_application(telegram_user_id: int):
    all_values = worksheet.get_all_values()

    for row_number in range(
        FIRST_APPLICATION_ROW,
        len(all_values) + 1,
    ):
        row = all_values[row_number - 1]

        while len(row) < COL_STATUS:
            row.append("")

        saved_user_id = row[COL_USER_ID - 1].strip()
        status = row[COL_STATUS - 1].strip()

        if (
            saved_user_id == str(telegram_user_id)
            and status.lower() == "нова"
        ):
            return {
                "row_number": row_number,
                "number": row[COL_NUMBER - 1],
            }

    return None


async def update_group_message_by_row(
    context: ContextTypes.DEFAULT_TYPE,
    row_number: int,
):
    row = worksheet.row_values(row_number)

    while len(row) < COL_STATUS:
        row.append("")

    message_id = row[COL_GROUP_MESSAGE_ID - 1]

    if not message_id:
        print("Не знайдено ID повідомлення заявки.")
        return

    telegram_text = create_telegram_text(
        application_number=row[COL_NUMBER - 1],
        name=row[COL_NAME - 1],
        obj=row[COL_OBJECT - 1],
        materials=row[COL_MATERIALS - 1],
        comment=row[COL_COMMENT - 1] or "Без коментаря",
        application_date=row[COL_DATE - 1],
        status=row[COL_STATUS - 1] or "Нова",
    )

    try:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=int(message_id),
            text=telegram_text,
        )
    except Exception as error:
        print(f"Помилка оновлення заявки в групі: {error}")


# ============================================================
# НОВА ЗАЯВКА
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "👋 Вітаю!\n\nВведіть ваше ПІБ або ім'я:",
        reply_markup=cancel_keyboard,
    )

    return NAME


async def new_application(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
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
        "📦 Напишіть матеріали та кількість одним повідомленням.\n\n"
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
        "💬 Напишіть коментар або натисніть «⏭️ Пропустити»:",
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
        application_number,
        name,
        obj,
        materials,
        comment,
        current_time,
        status,
    )

    telegram_sent = False
    table_saved = False
    group_message_id = ""

    try:
        sent_message = await context.bot.send_message(
            chat_id=GROUP_ID,
            text=telegram_text,
        )

        group_message_id = sent_message.message_id
        telegram_sent = True

    except Exception as error:
        print(f"Помилка відправлення в Telegram: {error}")

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
            "",                          # K — дата отримання
            "",                          # L — накладна
            comment,                     # M — коментар
            group_message_id,            # N — message ID заявки
            update.effective_user.id,    # O — Telegram user ID
            status,                      # P — статус
        ]

        worksheet.insert_row(
            new_row,
            index=FIRST_APPLICATION_ROW,
            value_input_option="USER_ENTERED",
        )

        table_saved = True

    except Exception as error:
        print(f"Помилка запису в Google Таблицю: {error}")

    if telegram_sent and table_saved:
        answer = (
            f"✅ Заявку №{application_number} створено.\n\n"
            "Вона відправлена в групу та записана в таблицю."
        )
    elif telegram_sent:
        answer = (
            "⚠️ Заявку відправлено в групу, "
            "але не записано в таблицю."
        )
    elif table_saved:
        answer = (
            "⚠️ Заявку записано в таблицю, "
            "але не відправлено в групу."
        )
    else:
        answer = "❌ Не вдалося створити заявку."

    context.user_data.clear()

    await update.message.reply_text(
        answer,
        reply_markup=main_keyboard,
    )

    return ConversationHandler.END


# ============================================================
# РЕДАГУВАННЯ
# ============================================================

async def edit_last_application(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    application = find_last_user_application(
        update.effective_user.id
    )

    if not application:
        await update.message.reply_text(
            "У вас немає нової заявки, яку можна редагувати.",
            reply_markup=main_keyboard,
        )
        return ConversationHandler.END

    context.user_data["edit_row"] = application["row_number"]
    context.user_data["edit_number"] = application["number"]

    await update.message.reply_text(
        f"✏️ Редагування заявки №{application['number']}.\n\n"
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
            "Напишіть новий перелік матеріалів:",
            reply_markup=cancel_keyboard,
        )
        return EDIT_MATERIALS

    if choice == "💬 Змінити коментар":
        await update.message.reply_text(
            "Напишіть новий коментар:",
            reply_markup=skip_keyboard,
        )
        return EDIT_COMMENT

    if choice == "✅ Завершити редагування":
        number = context.user_data.get("edit_number", "")
        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Редагування заявки №{number} завершено.",
            reply_markup=main_keyboard,
        )
        return ConversationHandler.END

    return EDIT_CHOICE


async def save_edited_object(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text(
            "Зміну скасовано.",
            reply_markup=edit_keyboard,
        )
        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]

    worksheet.update_cell(
        row_number,
        COL_OBJECT,
        text,
    )

    await update_group_message_by_row(
        context,
        row_number,
    )

    await update.message.reply_text(
        "✅ Об'єкт оновлено.",
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
            "Зміну скасовано.",
            reply_markup=edit_keyboard,
        )
        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]

    worksheet.update_cell(
        row_number,
        COL_MATERIALS,
        text,
    )

    await update_group_message_by_row(
        context,
        row_number,
    )

    await update.message.reply_text(
        "✅ Матеріали оновлено.",
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
            "Зміну скасовано.",
            reply_markup=edit_keyboard,
        )
        return EDIT_CHOICE

    if text in ("⏭️ Пропустити", "-"):
        text = "Без коментаря"

    row_number = context.user_data["edit_row"]

    worksheet.update_cell(
        row_number,
        COL_COMMENT,
        text,
    )

    await update_group_message_by_row(
        context,
        row_number,
    )

    await update.message.reply_text(
        "✅ Коментар оновлено.",
        reply_markup=edit_keyboard,
    )

    return EDIT_CHOICE


# ============================================================
# ТОВАР ОТРИМАНО
# ============================================================

async def receipt_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "📦 Введіть номер заявки, за якою отримано товар.\n\n"
        "Наприклад: 320",
        reply_markup=cancel_keyboard,
    )

    return RECEIPT_NUMBER


async def receipt_get_number(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    application = find_application_by_number(text)

    if not application:
        await update.message.reply_text(
            "❌ Заявку з таким номером не знайдено.\n\n"
            "Перевірте номер і введіть його ще раз.",
            reply_markup=cancel_keyboard,
        )
        return RECEIPT_NUMBER

    if application["status"].lower() == "доставлено":
        await update.message.reply_text(
            f"ℹ️ Заявка №{application['number']} "
            "вже має статус «Доставлено».",
            reply_markup=main_keyboard,
        )
        return ConversationHandler.END

    context.user_data["receipt_row"] = application["row_number"]
    context.user_data["receipt_number"] = application["number"]
    context.user_data["receipt_object"] = application["object"]
    context.user_data["receipt_materials"] = application["materials"]
    context.user_data["receipt_name"] = application["name"]

    await update.message.reply_text(
        f"✅ Заявку №{application['number']} знайдено.\n\n"
        "Тепер надішліть фото накладної або файл PDF.",
        reply_markup=cancel_keyboard,
    )

    return RECEIPT_FILE


async def receipt_get_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message.text == "❌ Скасувати":
        return await cancel(update, context)

    is_photo = bool(update.message.photo)
    is_document = bool(update.message.document)

    if not is_photo and not is_document:
        await update.message.reply_text(
            "Надішліть фото накладної або файл PDF.",
            reply_markup=cancel_keyboard,
        )
        return RECEIPT_FILE

    if is_document:
        document = update.message.document

        if document.mime_type != "application/pdf":
            await update.message.reply_text(
                "Потрібно надіслати фото або документ у форматі PDF.",
                reply_markup=cancel_keyboard,
            )
            return RECEIPT_FILE

    row_number = context.user_data["receipt_row"]
    application_number = context.user_data["receipt_number"]
    obj = context.user_data["receipt_object"]
    materials = context.user_data["receipt_materials"]
    name = context.user_data["receipt_name"]

    received_time = get_current_time()

    caption = (
        f"📦 ТОВАР ОТРИМАНО\n\n"
        f"🔢 Заявка №{application_number}\n"
        f"🏗️ Об'єкт: {obj}\n"
        f"👷 Прийняв: {name}\n"
        f"📋 Матеріали: {materials}\n"
        f"🕒 Дата отримання: {received_time}"
    )

    try:
        copied_message = await context.bot.copy_message(
            chat_id=GROUP_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            caption=caption,
        )

        delivery_note_value = (
            f"Telegram, повідомлення №{copied_message.message_id}"
        )

        worksheet.update_cell(
            row_number,
            COL_DELIVERED,
            True,
        )

        worksheet.update_cell(
            row_number,
            COL_RECEIVED_DATE,
            received_time,
        )

        worksheet.update_cell(
            row_number,
            COL_DELIVERY_NOTE,
            delivery_note_value,
        )

        worksheet.update_cell(
            row_number,
            COL_STATUS,
            "Доставлено",
        )

        await update_group_message_by_row(
            context,
            row_number,
        )

        await update.message.reply_text(
            f"✅ Отримання товару за заявкою "
            f"№{application_number} підтверджено.\n\n"
            "Накладну відправлено в групу, "
            "а в таблиці поставлено галочку «Доставлено».",
            reply_markup=main_keyboard,
        )

    except Exception as error:
        print(f"Помилка підтвердження отримання: {error}")

        await update.message.reply_text(
            "❌ Не вдалося зберегти накладну або оновити таблицю.",
            reply_markup=main_keyboard,
        )

    context.user_data.clear()

    return ConversationHandler.END


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
# ЗАПУСК
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
            filters.Regex(r"^✏️ Редагувати останню заявку$"),
            edit_last_application,
        ),

        MessageHandler(
            filters.Regex(r"^📦 Товар отримано$"),
            receipt_start,
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

        RECEIPT_NUMBER: [
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                receipt_get_number,
            )
        ],

        RECEIPT_FILE: [
            MessageHandler(
                (
                    filters.PHOTO
                    | filters.Document.ALL
                    | filters.TEXT
                )
                & ~filters.COMMAND,
                receipt_get_file,
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