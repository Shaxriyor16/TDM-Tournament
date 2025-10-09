# main.py
"""
PUBG turnir bot (aiogram v3.x mos)
- .env orqali token yuklanadi (BOT_TOKEN)
- ADMIN_ID .env yoki kod ichida vergul bilan bir nechta bo'lishi mumkin
- Google Sheets bilan ulangan (SHEET_JSON fayl nomi .env ichida)
- Obuna tekshirish, to'lov cheklarini yuborish va admin tasdiqlash
- Inline keyboard: START -> YouTube 1, YouTube 2, ✅ Tekshirish
"""

import os
import asyncio
import logging
import contextlib
from typing import Union, Optional, List

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
from aiogram.exceptions import TelegramAPIError

# ----------------------------
# CONFIG (from .env)
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "").strip()  # can be "123,456"
SHEET_JSON = os.getenv("SHEET_JSON", "Reyting-bot.json")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@M24SHaxa_youtube")

# parse admin ids into list of ints (fallback to empty list)
ADMINS: List[int] = []
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.split(","):
        part = part.strip()
        if part.isdigit():
            ADMINS.append(int(part))

# if single ADMIN_ID env as int was used previously
if not ADMINS:
    try:
        admin_int = int(os.getenv("ADMIN_ID", "0"))
        if admin_int:
            ADMINS = [admin_int]
    except Exception:
        ADMINS = []

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
# GOOGLE SHEETS HELPERS (with caching)
# ----------------------------
_gspread_client: Optional[gspread.client.Client] = None
_gspread_sheet = None

def connect_to_sheet(spreadsheet_name: str = "Pubg Reyting", worksheet_name: str = "Reyting-bot"):
    """
    Returns a gspread Worksheet object.
    Caches client to avoid re-authenticating on each request.
    """
    global _gspread_client, _gspread_sheet
    if _gspread_sheet:
        return _gspread_sheet
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if not os.path.exists(SHEET_JSON):
            raise FileNotFoundError(f"Google credentials file not found: {SHEET_JSON}")
        creds = ServiceAccountCredentials.from_json_keyfile_name(SHEET_JSON, scope)
        _gspread_client = gspread.authorize(creds)
        _gspread_sheet = _gspread_client.open(spreadsheet_name).worksheet(worksheet_name)
        logger.info("Connected to Google Sheet: %s / %s", spreadsheet_name, worksheet_name)
        return _gspread_sheet
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

def approve_buttons_template(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
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
    """
    Returns True if a user is member/creator/administrator of REQUIRED_CHANNEL.
    Handles API errors gracefully.
    """
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in {"member", "creator", "administrator"}
    except TelegramAPIError as e:
        logger.warning("check_subscription TelegramAPIError for user %s: %s", user_id, e)
        return False
    except Exception as e:
        logger.warning("check_subscription unexpected error for user %s: %s", user_id, e)
        return False

# ----------------------------
# PAYMENT FLOW
# ----------------------------
async def ask_for_payment(target: Union[Message, CallbackQuery], state: FSMContext):
    """
    Send payment instructions directly to the user (private).
    """
    user_id = target.from_user.id
    text = (
        "💳 <b>Karta turi:</b> HUMO\n"
        "💳 <b>Karta raqami:</b> <code>9860 6004 1512 3691</code>\n\n"
        "📌 Toʻlovni amalga oshirib, CHECK (skrinshot) yuboring."
    )
    msg = await bot.send_message(user_id, text)
    # auto-delete the instructional message after 5 seconds (best-effort)
    await asyncio.sleep(5)
    with contextlib.suppress(Exception):
        await bot.delete_message(user_id, msg.message_id)
    await bot.send_message(user_id, "✅ Endi to‘lovni amalga oshirgach, <b>chekni yuboring</b> (rasm yoki fayl):")
    await state.set_state(RegistrationState.waiting_for_payment_check)

# ----------------------------
# START HANDLER
# ----------------------------
@dp.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM</b>\nTDM TOURNAMENT BOTGA🎮 Xush kelibsiz!\n\n"
            "Bu bot orqali turnirda qatnashishingiz mumkin.\n⚠️ Turnir <b>pullik</b>.\n\n"
            "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling va ✅ Tekshirish tugmasini bosing 👇",
            reply_markup=youtube_keyboard
        )

# ----------------------------
# COMMAND HANDLERS
# ----------------------------
async def require_subscription(message: Message) -> bool:
    if not await check_subscription(message.from_user.id):
        await message.answer("❌ Kanalga obuna bo‘lishingiz kerak. ✅ Tekshirish tugmasini bosing.", reply_markup=youtube_keyboard)
        return False
    return True

@dp.message(Command("register"))
async def cmd_register(message: Message, state: FSMContext):
    if not await require_subscription(message):
        return
    await ask_for_payment(message, state)

@dp.message(Command("mygames"))
async def cmd_mygames(message: Message):
    if not await require_subscription(message):
        return
    await message.answer("🎮 Sizda hozircha o‘yin yo‘q.")

@dp.message(Command("contactwithadmin"))
async def cmd_contact_admin(message: Message):
    if not await require_subscription(message):
        return
    await message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")

@dp.message(Command("about"))
async def cmd_about(message: Message):
    if not await require_subscription(message):
        return
    await message.answer(
        "🎮 PUBG MOBILE TURNIR BOT 🎮\n\n"
        "Bu bot orqali siz pullik PUBG Mobile turnirlarida qatnashishingiz,\n"
        "to‘lov qilgan holda ishtirok etishingiz va sovrinli o‘rinlar uchun kurashishingiz mumkin! 🏆"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "/start\n/register\n/mygames\n/contactwithadmin\n/about\n/help\n/reyting"
    )

@dp.message(Command("reyting"))
async def cmd_reyting(message: Message):
    try:
        sheet = connect_to_sheet()
        data = sheet.get_all_values()
    except Exception:
        await message.answer("⚠️ Reytingni olishda xatolik yuz berdi.")
        return
    if len(data) <= 1:
        await message.answer("📊 Reytinglar hali mavjud emas.")
        return
    lines = ["🏆 Reyting:\n"]
    for idx, row in enumerate(data[1:21], start=1):
        nickname = row[0] if len(row) > 0 else "-"
        pubg_id = row[1] if len(row) > 1 else "-"
        lines.append(f"{idx}. {nickname} (ID: {pubg_id})")
    await message.answer("\n".join(lines))

# ----------------------------
# CALLBACK HANDLERS
# ----------------------------
@dp.callback_query(F.data == "check_subscription")
async def subscription_callback(call: CallbackQuery):
    user_id = call.from_user.id
    if await check_subscription(user_id):
        await call.message.edit_text(
            "✅ Obunangiz tasdiqlandi. Endi botdan to‘liq foydalanishingiz mumkin.",
            reply_markup=inline_main_buttons
        )
    else:
        await call.message.edit_text(
            "❌ Siz hali kanalga obuna bo‘lmagansiz.\n"
            "Iltimos, YouTube kanallarga obuna bo‘ling va ✅ Tekshirish tugmasini yana bosing 👇",
            reply_markup=youtube_keyboard
        )
    await call.answer()

@dp.callback_query(F.data == "register")
async def register_callback(call: CallbackQuery, state: FSMContext):
    if not await check_subscription(call.from_user.id):
        await call.message.edit_text(
            "❌ Kanalga obuna bo‘lishingiz kerak. ✅ Tekshirish tugmasini bosing.",
            reply_markup=youtube_keyboard
        )
        await call.answer()
        return
    await ask_for_payment(call, state)
    await call.answer()

# ----------------------------
# INLINE MAIN BUTTON CALLBACK HANDLERS
# ----------------------------
@dp.callback_query(F.data == "results")
async def results_callback(call: CallbackQuery):
    try:
        sheet = connect_to_sheet()
        data = sheet.get_all_values()
    except Exception:
        await call.message.answer("⚠️ Reytingni olishda xatolik yuz berdi.")
        await call.answer()
        return
    if len(data) <= 1:
        await call.message.answer("📊 Reytinglar hali mavjud emas.")
        await call.answer()
        return
    lines = ["🏆 Reyting:\n"]
    for idx, row in enumerate(data[1:21], start=1):
        nickname = row[0] if len(row) > 0 else "-"
        pubg_id = row[1] if len(row) > 1 else "-"
        lines.append(f"{idx}. {nickname} (ID: {pubg_id})")
    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "my_games")
async def my_games_callback(call: CallbackQuery):
    await call.message.answer("🎮 Sizda hozircha o‘yin yo‘q.")
    await call.answer()

@dp.callback_query(F.data == "contact_admin")
async def contact_admin_callback(call: CallbackQuery):
    await call.message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")
    await call.answer()

# ----------------------------
# PAYMENT CHECK HANDLER
# ----------------------------
@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext):
    await message.answer("🕔 Chekingiz admin tomonidan tekshirilmoqda.")
    approve_buttons = approve_buttons_template(message.from_user.id)
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                ADMINS[0] if ADMINS else 0, file_id,
                caption=(f"🥾 Yangi chek:\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yoq'}"),
                reply_markup=approve_buttons
            )
        else:
            file_id = message.document.file_id
            await bot.send_document(
                ADMINS[0] if ADMINS else 0, file_id,
                caption=(f"🥾 Yangi chek (fayl):\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yoq'}"),
                reply_markup=approve_buttons
            )
    except Exception as e:
        logger.exception("Failed to send check to admin: %s", e)
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi.")
        await state.clear()
        return
    await state.set_state(RegistrationState.waiting_for_admin_approval)

# ----------------------------
# ADMIN APPROVE/REJECT HANDLER
# ----------------------------
@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    try:
        user_id = int(call.data.split(":")[1])
    except Exception:
        await call.answer("User ID topilmadi.", show_alert=True)
        return
    await bot.send_message(user_id, "✅ Chekingiz tasdiqlandi. Endi PUBG nickname va ID'ingizni yuboring.")
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick.state)
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup()
    await call.answer("✅ Tasdiqlandi")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(call: CallbackQuery):
    if call.from_user.id not in ADMINS:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    try:
        user_id = int(call.data.split(":")[1])
    except Exception:
        await call.answer("User ID topilmadi.", show_alert=True)
        return
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.clear_state(key)
    await bot.send_message(user_id, "❌ Chekingiz rad etildi. Qayta urinib ko‘ring.")
    with contextlib.suppress(Exception):
        await call.message.edit_reply_markup()
    await call.answer("❌ Rad etildi")

# ----------------------------
# PUBG INFO HANDLER
# ----------------------------
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
        await bot.send_message(ADMINS[0] if ADMINS else 0,
                               f"🆕 Yangi qatnashchi: {message.from_user.full_name}\nPUBG: {pubg_nick} | ID: {pubg_id}\nUser ID: {message.from_user.id}")
    except Exception:
        pass
    await state.clear()

# ----------------------------
# MAIN
# ----------------------------
async def main():
    logger.info("Bot ishga tushmoqda...")
    # warn if admin not set
    if not ADMINS:
        logger.warning("ADMIN_ID muhit o'zgaruvchisi aniqlanmadi. Admin funktsiyalari ishlamaydi.")
    # Try to pre-connect Google Sheets (optional)
    try:
        connect_to_sheet()
    except Exception:
        logger.info("Google Sheetsga avtomatik ulanishda muammo yuz berdi — ishlash davom etadi, ammo /reyting va append funksiyalari xatolik beradi.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot to‘xtatildi.")

if __name__ == "__main__":
    asyncio.run(main())
