# bot.py
"""
PUBG Turnir Bot (Aiogram v3)
- .env orqali token va admin ID olinadi
- Google Sheets bilan ishlash
- Obuna tekshirish, to‘lov va admin tasdiqlash
- Inline + Reply keyboard
"""

import os
import asyncio
import logging
from typing import Union

from dotenv import load_dotenv
load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SHEET_JSON = os.getenv("SHEET_JSON", "Reyting-bot.json")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@M24SHaxa_youtube")
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "@M24SHaxa_youtube")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set!")

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------
# BOT & Dispatcher
# ----------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ----------------------------
# GOOGLE SHEETS
# ----------------------------
def connect_to_sheet(spreadsheet_name="Pubg Reyting", worksheet_name="Reyting-bot"):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(SHEET_JSON, scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).worksheet(worksheet_name)
        return sheet
    except Exception as e:
        logger.exception("Google Sheets connection failed:")
        raise

def append_to_sheet(nickname, pubg_id):
    try:
        sheet = connect_to_sheet()
        sheet.append_row([nickname, pubg_id])
        logger.info("Row added to sheet: %s | %s", nickname, pubg_id)
        return True
    except Exception as e:
        logger.exception("Sheet append error")
        return False

# ----------------------------
# FSM STATES
# ----------------------------
class RegistrationState(StatesGroup):
    waiting_for_payment_check = State()
    waiting_for_admin_approval = State()
    waiting_for_pubg_nick = State()

# ----------------------------
# KEYBOARDS
# ----------------------------
inline_main_buttons = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ro'yxatdan o'tish", callback_data="register"),
            InlineKeyboardButton(text="📊 Natijalar", callback_data="results")
        ],
        [
            InlineKeyboardButton(text="🎮 Mening o‘yinlarim", callback_data="my_games"),
            InlineKeyboardButton(text="📮 Admin bilan bog'lanish", callback_data="contact_admin")
        ]
    ]
)

youtube_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="▶️ YouTube 1", url="https://www.youtube.com/@M24_SAHAXA")],
        [InlineKeyboardButton(text="▶️ YouTube 2", url="https://www.youtube.com/@SHAXA_GAMEPLAY")],
        [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")]
    ]
)

reply_social_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📸 Instagram"), KeyboardButton(text="📱 Telegram")],
        [KeyboardButton(text="🎮 Twitch"), KeyboardButton(text="▶️ YouTube")],
        [KeyboardButton(text="📍 ASOSIY MENYU")]
    ],
    resize_keyboard=True
)

approve_buttons_template = lambda user_id: InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To‘g‘ri", callback_data=f"approve:{user_id}"),
            InlineKeyboardButton(text="❌ Noto‘g‘ri", callback_data=f"reject:{user_id}")
        ]
    ]
)

# ----------------------------
# SUBSCRIPTION CHECK
# ----------------------------
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "creator", "administrator")
    except Exception as e:
        logger.warning("Subscription check error for user %s: %s", user_id, e)
        return False

# ----------------------------
# PAYMENT FLOW
# ----------------------------
async def ask_for_payment(target: Union[Message, CallbackQuery], state: FSMContext):
    user_id = target.from_user.id
    text = (
        "💳 <b>Karta turi:</b> HUMO\n"
        "💳 <b>Karta raqami:</b> <code>9860 6004 1512 3691</code>\n\n"
        "📌 Toʻlovni amalga oshirib, CHECK (skrinshot) yuboring.\n"
        "⏳ Sizda 5 soniya bor raqamni nusxalash uchun - soʻngra xabaringiz o'chadi."
    )
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(5)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except Exception:
        pass
    await bot.send_message(user_id, "✅ Endi to‘lovni amalga oshirgach, <b>chekni yuboring</b> (rasm yoki fayl):")
    await state.set_state(RegistrationState.waiting_for_payment_check)

# ----------------------------
# START HANDLER
# ----------------------------
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM</b>\nTDM TOURNAMENT BOTGA🎮 Xush kelibsiz!\n\n"
            "Bu bot orqali turnirda qatnashishingiz mumkin.\n⚠️ Turnir <b>pullik</b>. Faqat rozilik bildirganlar uchun!\n\n"
            "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )
        return
    await message.answer(
        "👋 Assalomu alaykum!\nBotdan foydalanish uchun quyidagi kanallarga obuna bo‘ling yoki tekshirib ko‘ring.\n\n"
        "YouTube kanallarni ochib, obuna bo‘ling, so‘ngra ✅ Tekshirish tugmasini bosing 👇",
        reply_markup=youtube_keyboard
    )

# ----------------------------
# CALLBACKS
# ----------------------------
@dp.callback_query(F.data == "check_subscription")
async def subscription_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.edit_text(
            "✅ Obunangiz tasdiqlandi. Endi botdan to‘liq foydalanishingiz mumkin.",
            reply_markup=inline_main_buttons
        )
    else:
        await call.message.edit_text(
            "❌ Siz hali obuna bo‘lmagansiz. Iltimos, quyidagi kanalga obuna bo‘ling:",
            reply_markup=youtube_keyboard
        )
    await call.answer()

@dp.callback_query(F.data == "register")
async def register_callback(call: CallbackQuery, state: FSMContext):
    await ask_for_payment(call, state)
    await call.answer()

# ----------------------------
# HANDLE PAYMENT CHECK
# ----------------------------
@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext):
    await message.answer("🕔 Chekingiz admin tomonidan tekshirilmoqda.")
    approve_buttons = approve_buttons_template(message.from_user.id)
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                ADMIN_ID,
                file_id,
                caption=(
                    f"🥾 Yangi chek:\n"
                    f"👤 <b>{message.from_user.full_name}</b>\n"
                    f"🆔 <code>{message.from_user.id}</code>\n"
                    f"📌 @{message.from_user.username or 'username yo‘q'}"
                ),
                reply_markup=approve_buttons
            )
        else:
            file_id = message.document.file_id
            await bot.send_document(
                ADMIN_ID,
                file_id,
                caption=(
                    f"🥾 Yangi chek (fayl):\n"
                    f"👤 <b>{message.from_user.full_name}</b>\n"
                    f"🆔 <code>{message.from_user.id}</code>\n"
                    f"📌 @{message.from_user.username or 'username yo‘q'}"
                ),
                reply_markup=approve_buttons
            )
    except Exception as e:
        logger.exception("Failed to send check to admin: %s", e)
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi. Keyinroq qayta yuboring.")
        await state.clear()
        return
    await state.set_state(RegistrationState.waiting_for_admin_approval)

# ----------------------------
# ADMIN APPROVE / REJECT
# ----------------------------
@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick.state)
    await bot.send_message(user_id, "✅ Chekingiz tasdiqlandi. Endi PUBG nickname va ID'ingizni yuboring.")
    await call.message.edit_reply_markup()
    await call.answer("✅ Tasdiqlandi")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    await bot.send_message(user_id, "❌ Chekingiz tasdiqlanmadi. Iltimos, qayta urinib ko‘ring.")
    await call.message.edit_reply_markup()
    await call.answer("❌ Rad etildi")

# ----------------------------
# HANDLE PUBG NICKNAME
# ----------------------------
@dp.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_nick(message: Message, state: FSMContext):
    try:
        text = message.text.strip()
        if not text:
            await message.answer("❌ Iltimos, to‘g‘ri nickname yuboring.")
            return
        nickname, pubg_id = text.split()[:2]
        if append_to_sheet(nickname, pubg_id):
            await message.answer("✅ Ma’lumotlaringiz saqlandi! Turnirga muvaffaqiyatli qo‘shildingiz.")
        else:
            await message.answer("⚠️ Ma’lumotlarni saqlashda xatolik yuz berdi.")
    except Exception as e:
        logger.exception("PUBG nickname handler error: %s", e)
        await message.answer("❌ Iltimos, nickname va ID’ni to‘g‘ri formatda yuboring (Nickname ID).")
    finally:
        await state.clear()

# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    import asyncio
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
