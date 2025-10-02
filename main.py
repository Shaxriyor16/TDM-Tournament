# bot.py
"""
PUBG turnir bot (aiogram v3.22+ mos)
- .env orqali token yuklanadi (BOT_TOKEN)
- ADMIN_ID .env yoki kod ichida berilishi mumkin
- Google Sheets bilan ulangan (Reyting-bot.json)
- Obuna tekshirish, to'lov cheklarini yuborish va admin tasdiqlash
- Inline keyboard: START -> YouTube 1, YouTube 2, ✅ Tekshirish
- Keep-alive funksiyasi (Replit/Render uchun)
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
# CONFIG (ENV)
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SHEET_JSON = os.getenv("SHEET_JSON", "Reyting-bot.json")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@M24SHaxa_youtube")
SOURCE_CHANNEL = os.getenv("SOURCE_CHANNEL", "@M24SHaxa_youtube")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it into .env as BOT_TOKEN=your_token")

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# BOT SETUP
# ----------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# ----------------------------
# GOOGLE SHEETS HELPERS
# ----------------------------
def connect_to_sheet(spreadsheet_name: str = "Pubg Reyting", worksheet_name: str = "Reyting-bot"):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(SHEET_JSON, scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).worksheet(worksheet_name)
        return sheet
    except Exception as e:
        logger.exception("Google Sheetsga ulanishda xatolik:")
        raise

def append_to_sheet(nickname: str, pubg_id: str):
    try:
        sheet = connect_to_sheet()
        sheet.append_row([nickname, pubg_id])
        logger.info("Row added to sheet: %s | %s", nickname, pubg_id)
        return True
    except Exception as e:
        logger.exception("sheet append error")
        return False

# ----------------------------
# FSM (States)
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

subscribe_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Obuna bo‘ldim", callback_data="check_subscription")]
    ]
)

approve_buttons_template = lambda user_id: InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To‘g‘ri", callback_data=f"approve:{user_id}"),
            InlineKeyboardButton(text="❌ Noto‘g‘ri", callback_data=f"reject:{user_id}")
        ]
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

youtube_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="▶️ YouTube 1", url="https://www.youtube.com/@M24_SAHAXA")],
        [InlineKeyboardButton(text="▶️ YouTube 2", url="https://www.youtube.com/@SHAXA_GAMEPLAY")],
        [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")]
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
        logger.warning("check_subscription error for user %s: %s", user_id, e)
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
    except: 
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
            "Bu bot orqali turnirda qatnashishingiz mumkin.\n⚠️ Turnir <b>pullik</b>.\n\n"
            "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )
        return
    await message.answer(
        "👋 Assalomu alaykum!\n\n"
        "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling yoki tekshirib ko‘ring.\n\n"
        "YouTube kanallarni ochib, obuna bo‘ling, so‘ngra ✅ Tekshirish tugmasini bosing 👇",
        reply_markup=youtube_keyboard
    )

# ----------------------------
# CALLBACKS, PAYMENT & FSM HANDLERS
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

# Chekni qabul qilish
@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext):
    await message.answer("🕔 Chekingiz admin tomonidan tekshirilmoqda.")
    approve_buttons = approve_buttons_template(message.from_user.id)
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                ADMIN_ID, file_id,
                caption=(f"🥾 Yangi chek:\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yo‘q'}"),
                reply_markup=approve_buttons
            )
        else:
            file_id = message.document.file_id
            await bot.send_document(
                ADMIN_ID, file_id,
                caption=(f"🥾 Yangi chek (fayl):\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yo‘q'}"),
                reply_markup=approve_buttons
            )
    except Exception as e:
        logger.exception("Failed to send check to admin: %s", e)
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi. Keyinroq qayta yuboring.")
        await state.clear()
        return
    await state.set_state(RegistrationState.waiting_for_admin_approval)

# Admin approve/reject
@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    await bot.send_message(user_id, "✅ Chekingiz tasdiqlandi. Endi PUBG nickname va ID'ingizni yuboring.")
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick.state)
    await call.message.edit_reply_markup()
    await call.answer("✅ Tasdiqlandi")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.clear_state(key)
    await bot.send_message(user_id, "❌ Chekingiz rad etildi. Qayta urinib ko‘ring.")
    await call.message.edit_reply_markup()
    await call.answer("❌ Rad etildi")

# PUBG info qabul qilish
@dp.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_info(message: Message, state: FSMContext):
    text = message.text or ""
    pubg_nick = text.strip()
    pubg_id = ""
    tokens = text.replace(",", " ").split()
    if len(tokens) >= 2:
        pubg_id = tokens[-1]
        pubg_nick = " ".join(tokens[:-1])
    ok = append_to_sheet(pubg_nick or message.from_user.full_name, pubg_id or "ID not provided")
    if ok:
        await message.answer("📋 Ma'lumot qabul qilindi. Reytingga qoʻshildi. Rahmat!", reply_markup=reply_social_menu)
    else:
        await message.answer("⚠️ Reytingga qoʻshishda xatolik yuz berdi. Admin bilan bog‘laning.", reply_markup=reply_social_menu)
    try:
        await bot.send_message(ADMIN_ID, f"🆕 Yangi qatnashchi: {message.from_user.full_name}\nPUBG: {pubg_nick} | ID: {pubg_id}\nUser ID: {message.from_user.id}")
    except Exception: pass
    await state.clear()

# ----------------------------
# MAIN
# ----------------------------
async def main():
    logger.info("Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
