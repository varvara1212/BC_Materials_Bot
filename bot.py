import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

TOKEN = os.environ["TELEGRAM_TOKEN"]
GROUP_ID = -5340906174
APPROVAL_GROUP_ID = int(os.environ["APPROVAL_GROUP_ID"])
ADMIN_USER_ID = int(os.environ["ADMIN_USER_ID"])
APPROVER_USER_ID = int(os.environ["APPROVER_USER_ID"])

TABLE_NAME = "облік документів"
WORKSHEET_NAME = "заявки матеріалів"
FIRST_APPLICATION_ROW = 7

COL_NUMBER = 1
COL_DATE = 2
COL_OBJECT = 3
COL_NAME = 4
COL_MATERIALS = 5
COL_SUPPLIER = 6
COL_INVOICE_NUMBER = 7
COL_AMOUNT = 8
COL_PAID = 9
COL_DELIVERED = 10
COL_RECEIVED_DATE = 11
COL_DELIVERY_NOTE = 12
COL_COMMENT = 13
COL_GROUP_MESSAGE_ID = 14
COL_USER_ID = 15
COL_STATUS = 16

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
    INVOICE_SELECT,
    INVOICE_SUPPLIER,
    INVOICE_NUMBER,
    INVOICE_AMOUNT,
    INVOICE_FILE,
) = range(15)

google_credentials = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])

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


def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        ["➕ Нова заявка"],
        ["✏️ Редагувати останню заявку"],
        ["📦 Товар отримано"],
    ]

    if user_id == ADMIN_USER_ID:
        buttons.append(["🧾 Додати рахунок"])

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


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


def get_current_time() -> str:
    return datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%d.%m.%Y %H:%M")


def clean_number(value) -> str:
    return str(value).replace("№", "").replace(" ", "").strip()


def get_next_application_number() -> int:
    values = worksheet.col_values(COL_NUMBER)
    numbers = []

    for value in values[FIRST_APPLICATION_ROW - 1:]:
        cleaned_value = clean_number(value)

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


def make_application_dict(row_number: int, row: list) -> dict:
    while len(row) < COL_STATUS:
        row.append("")

    return {
        "row_number": row_number,
        "number": row[COL_NUMBER - 1],
        "date": row[COL_DATE - 1],
        "object": row[COL_OBJECT - 1],
        "name": row[COL_NAME - 1],
        "materials": row[COL_MATERIALS - 1],
        "supplier": row[COL_SUPPLIER - 1],
        "invoice_number": row[COL_INVOICE_NUMBER - 1],
        "amount": row[COL_AMOUNT - 1],
        "comment": row[COL_COMMENT - 1],
        "message_id": row[COL_GROUP_MESSAGE_ID - 1],
        "user_id": row[COL_USER_ID - 1],
        "status": row[COL_STATUS - 1],
    }


def find_application_by_number(application_number: str):
    all_values = worksheet.get_all_values()
    searched_number = clean_number(application_number)

    for row_number in range(FIRST_APPLICATION_ROW, len(all_values) + 1):
        row = all_values[row_number - 1]

        if not row:
            continue

        if clean_number(row[COL_NUMBER - 1]) == searched_number:
            return make_application_dict(row_number, row)

    return None


def find_last_user_application(telegram_user_id: int):
    all_values = worksheet.get_all_values()

    for row_number in range(FIRST_APPLICATION_ROW, len(all_values) + 1):
        row = all_values[row_number - 1]

        while len(row) < COL_STATUS:
            row.append("")

        saved_user_id = row[COL_USER_ID - 1].strip()
        status = row[COL_STATUS - 1].strip()

        if saved_user_id == str(telegram_user_id) and status.lower() == "нова":
            return {
                "row_number": row_number,
                "number": row[COL_NUMBER - 1],
            }

    return None


def get_open_applications(limit: int = 25) -> list:
    all_values = worksheet.get_all_values()
    applications = []

    for row_number in range(FIRST_APPLICATION_ROW, len(all_values) + 1):
        row = all_values[row_number - 1]

        if not row:
            continue

        application = make_application_dict(row_number, row)
        status = application["status"].strip().lower()

        if status in {"", "нова", "відхилено"}:
            applications.append(application)

        if len(applications) >= limit:
            break

    return applications


def parse_amount(text: str) -> Decimal:
    cleaned = (
        text.replace("грн", "")
        .replace("₴", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )

    amount = Decimal(cleaned)

    if amount <= 0:
        raise InvalidOperation

    return amount


def amount_for_sheet(amount: Decimal):
    if amount == amount.to_integral():
        return int(amount)

    return float(amount)


def amount_for_message(amount: Decimal) -> str:
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")

    if formatted.endswith(",00"):
        formatted = formatted[:-3]

    return formatted


async def update_group_message_by_row(
    context: ContextTypes.DEFAULT_TYPE,
    row_number: int,
):
    row = worksheet.row_values(row_number)

    while len(row) < COL_STATUS:
        row.append("")

    message_id = row[COL_GROUP_MESSAGE_ID - 1]

    if not message_id:
        return

    text = create_telegram_text(
        row[COL_NUMBER - 1],
        row[COL_NAME - 1],
        row[COL_OBJECT - 1],
        row[COL_MATERIALS - 1],
        row[COL_COMMENT - 1] or "Без коментаря",
        row[COL_DATE - 1],
        row[COL_STATUS - 1] or "Нова",
    )

    try:
        await context.bot.edit_message_text(
            chat_id=GROUP_ID,
            message_id=int(message_id),
            text=text,
        )
    except Exception as error:
        print(f"Помилка оновлення заявки в групі: {error}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "👋 Вітаю! Оберіть потрібну дію:",
        reply_markup=get_main_keyboard(update.effective_user.id),
    )

    return ConversationHandler.END


async def new_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "👷 Введіть ваше ПІБ або ім'я:",
        reply_markup=cancel_keyboard,
    )

    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["name"] = text

    await update.message.reply_text(
        "🏗️ Вкажіть назву об'єкта:",
        reply_markup=cancel_keyboard,
    )

    return OBJECT


async def get_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["object"] = text

    await update.message.reply_text(
        "📦 Напишіть матеріали та кількість одним повідомленням.\n\n"
        "Наприклад:\nГазоблок — 50 шт\nКлей — 8 мішків",
        reply_markup=cancel_keyboard,
    )

    return MATERIALS


async def get_materials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["materials"] = text

    await update.message.reply_text(
        "💬 Напишіть коментар або натисніть «⏭️ Пропустити»:",
        reply_markup=skip_keyboard,
    )

    return COMMENT


async def get_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            application_number,
            current_time,
            obj,
            name,
            materials,
            "",
            "",
            "",
            False,
            False,
            "",
            "",
            comment,
            group_message_id,
            update.effective_user.id,
            status,
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
        answer = f"✅ Заявку №{application_number} створено."
    elif telegram_sent:
        answer = "⚠️ Заявку відправлено в групу, але не записано в таблицю."
    elif table_saved:
        answer = "⚠️ Заявку записано в таблицю, але не відправлено в групу."
    else:
        answer = "❌ Не вдалося створити заявку."

    context.user_data.clear()

    await update.message.reply_text(
        answer,
        reply_markup=get_main_keyboard(update.effective_user.id),
    )

    return ConversationHandler.END


async def edit_last_application(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    application = find_last_user_application(update.effective_user.id)

    if not application:
        await update.message.reply_text(
            "У вас немає нової заявки, яку можна редагувати.",
            reply_markup=get_main_keyboard(update.effective_user.id),
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


async def edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            reply_markup=get_main_keyboard(update.effective_user.id),
        )
        return ConversationHandler.END

    return EDIT_CHOICE


async def save_edited_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text("Зміну скасовано.", reply_markup=edit_keyboard)
        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]
    worksheet.update_cell(row_number, COL_OBJECT, text)
    await update_group_message_by_row(context, row_number)

    await update.message.reply_text("✅ Об'єкт оновлено.", reply_markup=edit_keyboard)
    return EDIT_CHOICE


async def save_edited_materials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text("Зміну скасовано.", reply_markup=edit_keyboard)
        return EDIT_CHOICE

    row_number = context.user_data["edit_row"]
    worksheet.update_cell(row_number, COL_MATERIALS, text)
    await update_group_message_by_row(context, row_number)

    await update.message.reply_text("✅ Матеріали оновлено.", reply_markup=edit_keyboard)
    return EDIT_CHOICE


async def save_edited_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        await update.message.reply_text("Зміну скасовано.", reply_markup=edit_keyboard)
        return EDIT_CHOICE

    if text in ("⏭️ Пропустити", "-"):
        text = "Без коментаря"

    row_number = context.user_data["edit_row"]
    worksheet.update_cell(row_number, COL_COMMENT, text)
    await update_group_message_by_row(context, row_number)

    await update.message.reply_text("✅ Коментар оновлено.", reply_markup=edit_keyboard)
    return EDIT_CHOICE


async def receipt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "📦 Введіть номер заявки, за якою отримано товар.\n\nНаприклад: 320",
        reply_markup=cancel_keyboard,
    )

    return RECEIPT_NUMBER


async def receipt_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    application = find_application_by_number(text)

    if not application:
        await update.message.reply_text(
            "❌ Заявку з таким номером не знайдено.",
            reply_markup=cancel_keyboard,
        )
        return RECEIPT_NUMBER

    if application["status"].lower() == "доставлено":
        await update.message.reply_text(
            f"ℹ️ Заявка №{application['number']} вже доставлена.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )
        return ConversationHandler.END

    context.user_data["receipt_row"] = application["row_number"]
    context.user_data["receipt_number"] = application["number"]
    context.user_data["receipt_object"] = application["object"]
    context.user_data["receipt_materials"] = application["materials"]
    context.user_data["receipt_name"] = application["name"]

    await update.message.reply_text(
        f"✅ Заявку №{application['number']} знайдено.\n\n"
        "Надішліть фото накладної або PDF.",
        reply_markup=cancel_keyboard,
    )

    return RECEIPT_FILE


async def receipt_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Скасувати":
        return await cancel(update, context)

    is_photo = bool(update.message.photo)
    is_document = bool(update.message.document)

    if not is_photo and not is_document:
        await update.message.reply_text(
            "Надішліть фото накладної або PDF.",
            reply_markup=cancel_keyboard,
        )
        return RECEIPT_FILE

    if is_document and update.message.document.mime_type != "application/pdf":
        await update.message.reply_text(
            "Потрібно надіслати фото або PDF.",
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

        worksheet.update_cell(row_number, COL_DELIVERED, True)
        worksheet.update_cell(row_number, COL_RECEIVED_DATE, received_time)
        worksheet.update_cell(
            row_number,
            COL_DELIVERY_NOTE,
            f"Telegram, повідомлення №{copied_message.message_id}",
        )
        worksheet.update_cell(row_number, COL_STATUS, "Доставлено")

        await update_group_message_by_row(context, row_number)

        await update.message.reply_text(
            f"✅ Отримання товару за заявкою №{application_number} підтверджено.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )

    except Exception as error:
        print(f"Помилка підтвердження отримання: {error}")

        await update.message.reply_text(
            "❌ Не вдалося зберегти накладну або оновити таблицю.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )

    context.user_data.clear()
    return ConversationHandler.END


async def invoice_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text(
            "⛔ У вас немає доступу до додавання рахунків.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )
        return ConversationHandler.END

    applications = get_open_applications()

    if not applications:
        await update.message.reply_text(
            "Немає відкритих заявок для додавання рахунку.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )
        return ConversationHandler.END

    buttons = []

    for application in applications:
        materials = application["materials"].replace("\n", " ")

        if len(materials) > 28:
            materials = materials[:28] + "…"

        buttons.append(
            [
                InlineKeyboardButton(
                    f"№{application['number']} | {application['object']} | {materials}",
                    callback_data=f"invoice_select:{clean_number(application['number'])}",
                )
            ]
        )

    await update.message.reply_text(
        "🧾 Оберіть заявку:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    return INVOICE_SELECT


async def invoice_select_application(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if query.from_user.id != ADMIN_USER_ID:
        await query.answer("У вас немає доступу.", show_alert=True)
        return ConversationHandler.END

    await query.answer()

    application_number = query.data.split(":", 1)[1]
    application = find_application_by_number(application_number)

    if not application:
        await query.edit_message_text("❌ Заявку не знайдено.")
        return ConversationHandler.END

    context.user_data["invoice_application_number"] = application["number"]
    context.user_data["invoice_object"] = application["object"]
    context.user_data["invoice_materials"] = application["materials"]
    context.user_data["invoice_requester_id"] = application["user_id"]

    await query.edit_message_text(
        f"✅ Обрано заявку №{application['number']}\n"
        f"🏗️ {application['object']}\n"
        f"📦 {application['materials']}"
    )

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🏪 Введіть назву постачальника:",
        reply_markup=cancel_keyboard,
    )

    return INVOICE_SUPPLIER


async def invoice_get_supplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["invoice_supplier"] = text

    await update.message.reply_text(
        "🔢 Введіть номер рахунку:",
        reply_markup=cancel_keyboard,
    )

    return INVOICE_NUMBER


async def invoice_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    context.user_data["invoice_document_number"] = text

    await update.message.reply_text(
        "💰 Введіть суму рахунку в гривнях.\n\n"
        "Наприклад: 12500 або 12500,50",
        reply_markup=cancel_keyboard,
    )

    return INVOICE_AMOUNT


async def invoice_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "❌ Скасувати":
        return await cancel(update, context)

    try:
        amount = parse_amount(text)
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "❌ Суму не розпізнано. Введіть число ще раз.",
            reply_markup=cancel_keyboard,
        )
        return INVOICE_AMOUNT

    context.user_data["invoice_amount"] = str(amount)

    await update.message.reply_text(
        "📎 Надішліть фото рахунку або PDF.",
        reply_markup=cancel_keyboard,
    )

    return INVOICE_FILE


async def invoice_get_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Скасувати":
        return await cancel(update, context)

    is_photo = bool(update.message.photo)
    is_document = bool(update.message.document)

    if not is_photo and not is_document:
        await update.message.reply_text(
            "Надішліть фото рахунку або PDF.",
            reply_markup=cancel_keyboard,
        )
        return INVOICE_FILE

    if is_document and update.message.document.mime_type != "application/pdf":
        await update.message.reply_text(
            "Потрібно надіслати фото або PDF.",
            reply_markup=cancel_keyboard,
        )
        return INVOICE_FILE

    application_number = context.user_data["invoice_application_number"]
    obj = context.user_data["invoice_object"]
    materials = context.user_data["invoice_materials"]
    supplier = context.user_data["invoice_supplier"]
    invoice_number = context.user_data["invoice_document_number"]
    requester_id = context.user_data.get("invoice_requester_id", "")

    amount = Decimal(context.user_data["invoice_amount"])
    amount_text = amount_for_message(amount)

    caption = (
        f"🧾 РАХУНОК НА ПОГОДЖЕННЯ\n\n"
        f"🔢 Заявка №{application_number}\n"
        f"🏗️ Об'єкт: {obj}\n"
        f"📦 Матеріали: {materials}\n"
        f"🏪 Постачальник: {supplier}\n"
        f"📄 Рахунок №{invoice_number}\n"
        f"💰 Сума: {amount_text} грн\n\n"
        f"📌 Статус: очікує погодження"
    )

    approval_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Погодити",
                    callback_data=f"invoice_approve:{clean_number(application_number)}",
                ),
                InlineKeyboardButton(
                    "❌ Відхилити",
                    callback_data=f"invoice_reject:{clean_number(application_number)}",
                ),
            ]
        ]
    )

    try:
        await context.bot.copy_message(
            chat_id=APPROVAL_GROUP_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            caption=caption,
            reply_markup=approval_keyboard,
        )

        application = find_application_by_number(application_number)

        if not application:
            raise RuntimeError("Заявку не знайдено під час запису рахунку.")

        row_number = application["row_number"]

        worksheet.update_cell(row_number, COL_SUPPLIER, supplier)
        worksheet.update_cell(row_number, COL_INVOICE_NUMBER, invoice_number)
        worksheet.update_cell(row_number, COL_AMOUNT, amount_for_sheet(amount))
        worksheet.update_cell(row_number, COL_STATUS, "На погодженні")

        await update_group_message_by_row(context, row_number)

        await update.message.reply_text(
            f"✅ Рахунок до заявки №{application_number} "
            "відправлено керівнику.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )

        if requester_id:
            try:
                requester_id_int = int(requester_id)

                if requester_id_int != ADMIN_USER_ID:
                    await context.bot.send_message(
                        chat_id=requester_id_int,
                        text=(
                            f"🧾 До вашої заявки №{application_number} "
                            "додано рахунок і передано керівнику."
                        ),
                        reply_markup=get_main_keyboard(requester_id_int),
                    )
            except (ValueError, TypeError):
                pass

    except Exception as error:
        print(f"Помилка додавання рахунку: {error}")

        await update.message.reply_text(
            "❌ Не вдалося відправити рахунок або оновити таблицю.",
            reply_markup=get_main_keyboard(update.effective_user.id),
        )

    context.user_data.clear()
    return ConversationHandler.END


async def invoice_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.from_user.id != APPROVER_USER_ID:
        await query.answer(
            "⛔ Погоджувати рахунки може лише керівник.",
            show_alert=True,
        )
        return

    if query.message.chat_id != APPROVAL_GROUP_ID:
        await query.answer(
            "Ця дія доступна лише в групі погодження.",
            show_alert=True,
        )
        return

    action, application_number = query.data.split(":", 1)
    application = find_application_by_number(application_number)

    if not application:
        await query.answer("Заявку не знайдено.", show_alert=True)
        return

    current_status = application["status"].strip().lower()

    if current_status in {
        "погоджено до оплати",
        "відхилено",
        "доставлено",
    }:
        await query.answer(
            f"Рішення вже зафіксовано: {application['status']}.",
            show_alert=True,
        )
        return

    await query.answer()

    if action == "invoice_approve":
        new_status = "Погоджено до оплати"
        decision_text = "✅ ПОГОДЖЕНО КЕРІВНИКОМ"
        notification = f"✅ Рахунок до заявки №{application['number']} погоджено."
    else:
        new_status = "Відхилено"
        decision_text = "❌ ВІДХИЛЕНО КЕРІВНИКОМ"
        notification = f"❌ Рахунок до заявки №{application['number']} відхилено."

    try:
        worksheet.update_cell(
            application["row_number"],
            COL_STATUS,
            new_status,
        )

        await update_group_message_by_row(
            context,
            application["row_number"],
        )

        old_caption = query.message.caption or ""

        await query.edit_message_caption(
            caption=(
                f"{old_caption}\n\n"
                f"{decision_text}\n"
                f"👤 {query.from_user.full_name}\n"
                f"🕒 {get_current_time()}"
            ),
            reply_markup=None,
        )

        user_ids = {ADMIN_USER_ID}

        try:
            requester_id = int(application["user_id"])
            if requester_id:
                user_ids.add(requester_id)
        except (ValueError, TypeError):
            pass

        for user_id in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=notification,
                    reply_markup=get_main_keyboard(user_id),
                )
            except Exception as error:
                print(f"Не вдалося сповістити {user_id}: {error}")

    except Exception as error:
        print(f"Помилка погодження рахунку: {error}")

        await query.answer(
            "Не вдалося зберегти рішення.",
            show_alert=True,
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Дію скасовано.",
        reply_markup=get_main_keyboard(update.effective_user.id),
    )

    return ConversationHandler.END


async def show_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"ID цього чату: {update.effective_chat.id}"
    )


app = Application.builder().token(TOKEN).build()

conversation = ConversationHandler(
    entry_points=[
        CommandHandler("start", start),
        MessageHandler(filters.Regex(r"^➕ Нова заявка$"), new_application),
        MessageHandler(
            filters.Regex(r"^✏️ Редагувати останню заявку$"),
            edit_last_application,
        ),
        MessageHandler(filters.Regex(r"^📦 Товар отримано$"), receipt_start),
        MessageHandler(filters.Regex(r"^🧾 Додати рахунок$"), invoice_start),
    ],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_object)],
        MATERIALS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_materials)
        ],
        COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_comment)],
        EDIT_CHOICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choice)
        ],
        EDIT_OBJECT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_object)
        ],
        EDIT_MATERIALS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_materials)
        ],
        EDIT_COMMENT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_comment)
        ],
        RECEIPT_NUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_get_number)
        ],
        RECEIPT_FILE: [
            MessageHandler(
                (filters.PHOTO | filters.Document.ALL | filters.TEXT)
                & ~filters.COMMAND,
                receipt_get_file,
            )
        ],
        INVOICE_SELECT: [
            CallbackQueryHandler(
                invoice_select_application,
                pattern=r"^invoice_select:",
            )
        ],
        INVOICE_SUPPLIER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_get_supplier)
        ],
        INVOICE_NUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_get_number)
        ],
        INVOICE_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_get_amount)
        ],
        INVOICE_FILE: [
            MessageHandler(
                (filters.PHOTO | filters.Document.ALL | filters.TEXT)
                & ~filters.COMMAND,
                invoice_get_file,
            )
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    allow_reentry=True,
)

app.add_handler(conversation)

app.add_handler(
    CallbackQueryHandler(
        invoice_decision,
        pattern=r"^invoice_(approve|reject):",
    )
)

app.add_handler(CommandHandler("id", show_chat_id))

print("Бот запущено...")

app.run_polling()