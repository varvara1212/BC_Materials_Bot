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

TOKEN = os.environ["TELEGRAM_TOKEN"]

GROUP_ID = -5340906174

TABLE_NAME = "Заявки на матеріали"

NAME, OBJECT, MATERIALS, COMMENT = range(4)


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

worksheet = spreadsheet.sheet1


skip_keyboard = ReplyKeyboardMarkup(
    [["⏭️ Пропустити"]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "👋 Вітаю!\n\nВведіть ваше ПІБ:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return NAME


async def get_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["name"] = update.message.text.strip()

    await update.message.reply_text(
        "🏗️ Вкажіть назву об'єкта:"
    )

    return OBJECT


async def get_object(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["object"] = update.message.text.strip()

    await update.message.reply_text(
        "📦 Напишіть матеріали та кількість одним повідомленням.\n\n"
        "Приклад:\n"
        "Газоблок — 50 шт\n"
        "Клей — 8 мішків"
    )

    return MATERIALS


async def get_materials(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["materials"] = update.message.text.strip()

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

    if comment == "⏭️ Пропустити" or comment == "-":
        comment = "Без коментаря"

    name = context.user_data["name"]
    obj = context.user_data["object"]
    materials = context.user_data["materials"]

    current_time = datetime.now(
        ZoneInfo("Europe/Kyiv")
    ).strftime("%d.%m.%Y о %H:%M")

    telegram_text = (
        "📥 НОВА ЗАЯВКА\n\n"
        f"👷 Працівник:\n{name}\n\n"
        f"🏗️ Об'єкт:\n{obj}\n\n"
        f"📦 Матеріали:\n{materials}\n\n"
        f"💬 Коментар:\n{comment}\n\n"
        f"🕒 Дата і час:\n{current_time}"
    )

    telegram_sent = False
    table_saved = False

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=telegram_text,
        )
        telegram_sent = True

    except Exception as error:
        print(
            f"Помилка відправлення в Telegram: {error}"
        )

    try:
        worksheet.append_row(
            [
                current_time,
                name,
                obj,
                materials,
                comment,
            ],
            value_input_option="USER_ENTERED",
        )
        table_saved = True

    except Exception as error:
        print(
            f"Помилка запису в Google Таблицю: {error}"
        )

    if telegram_sent and table_saved:
        answer = (
            "✅ Заявку відправлено в групу "
            "та записано в Google Таблицю."
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

    await update.message.reply_text(
        answer,
        reply_markup=ReplyKeyboardRemove(),
    )

    context.user_data.clear()

    return ConversationHandler.END


async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Створення заявки скасовано.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


app = Application.builder().token(TOKEN).build()

conversation = ConversationHandler(
    entry_points=[
        CommandHandler("start", start)
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
    },
    fallbacks=[
        CommandHandler("cancel", cancel)
    ],
)

app.add_handler(conversation)

print("Бот запущено...")

app.run_polling()