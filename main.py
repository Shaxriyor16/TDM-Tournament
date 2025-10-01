# bot.py
"""
To'liq: PUBG turnir bot (aiogram v3 uslubida)
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
from typing import Optional, Union

from dotenv import load_dotenv
load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ChatMember, ChatType,
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
# REQUIRED_CHANNEL — Telegram kanali username yoki id (masalan @MyChannel yoki -100123..)
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
    """
    Connects to Google Sheets and returns worksheet object.
    Requires ServiceAccount JSON (SHEET_JSON).
    """
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
    """
    Adds a new row to the sheet: [nickname, pubg_id]
    """
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
# Keyboards (original + new)
# ----------------------------
# Main inline menu (keeps your original layout)
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

# Subscribe inline keyboard (used when REQUIRED_CHANNEL check fails)
subscribe_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Obuna bo‘ldim", callback_data="check_subscription")]
    ]
)

# Approve/reject template for admin
approve_buttons_template = lambda user_id: InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ To‘g‘ri", callback_data=f"approve:{user_id}"),
            InlineKeyboardButton(text="❌ Noto‘g‘ri", callback_data=f"reject:{user_id}")
        ]
    ]
)

# Reply keyboard social menu (keep original)
reply_social_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📸 Instagram"), KeyboardButton(text="📱 Telegram")],
        [KeyboardButton(text="🎮 Twitch"), KeyboardButton(text="▶️ YouTube")],
        [KeyboardButton(text="📍 ASOSIY MENYU")]
    ],
    resize_keyboard=True
)

# ----------------------------
# NEW: Start inline keyboard with YouTube links + Tekshirish
# ----------------------------
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
    """
    Returns True if user is a member of REQUIRED_CHANNEL (Telegram).
    IMPORTANT: Telegram-only check. YouTube cannot be programmatically checked here.
    """
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        if member.status in ("member", "creator", "administrator"):
            return True
        return False
    except Exception as e:
        logger.warning("check_subscription error for user %s: %s", user_id, e)
        return False

# ----------------------------
# PAYMENT / ASK FOR CHECK
# ----------------------------
async def ask_for_payment(target: Union[Message, CallbackQuery], state: FSMContext):
    """
    Sends payment instructions and sets FSM to waiting_for_payment_check
    Accepts either Message or CallbackQuery (from handlers).
    """
    if isinstance(target, CallbackQuery):
        user_id = target.from_user.id
    else:
        user_id = target.from_user.id

    text = (
        "💳 <b>Karta turi:</b> HUMO\n"
        "💳 <b>Karta raqami:</b> <code>9860 6004 1512 3691</code>\n\n"
        "📌 Toʻlovni amalga oshirib, CHECK (skrinshot) yuboring.\n"
        "⏳ Sizda 5 soniya bor raqamni nusxalash uchun - soʻngra xabaringiz o'chadi."
    )
    # Send message and delete it after 5s so karta raqami qochadi (if possible)
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(5)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except Exception:
        pass

    # Ask for check
    await bot.send_message(user_id, "✅ Endi to‘lovni amalga oshirgach, <b>chekni yuboring</b> (rasm yoki fayl):")
    await state.set_state(RegistrationState.waiting_for_payment_check)

# ----------------------------
# START HANDLER (modified: show youtube inline keyboard at the beginning)
# ----------------------------
@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    """
    /start - immediately sends YouTube links + Tekshirish inline keyboard.
    If user already subscribed to REQUIRED_CHANNEL, show main menu directly.
    """
    user_id = message.from_user.id
    # If user already subscribed, show normal main menu (your original welcome)
    if await check_subscription(user_id):
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM</b>\nTDM TOURNAMENT BOTGA🎮 Xush kelibsiz!\n\n"
            "Bu bot orqali turnirda qatnashishingiz mumkin.\n"
            "⚠️ Turnir <b>pullik</b>. Faqat rozilik bildirganlar uchun!\n\n"
            "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )

        # Try to forward last "Turnir sanasi" from SOURCE_CHANNEL as in your code
        try:
            async for msg in bot.get_chat_history(SOURCE_CHANNEL, limit=30):
                text = msg.text or (getattr(msg, "caption", None) or "")
                if isinstance(text, str) and text.startswith("📅Turnir sanasi"):
                    try:
                        await bot.forward_message(message.chat.id, msg.chat.id, msg.message_id)
                    except Exception:
                        await message.answer(text)
                    break
        except Exception as e:
            logger.warning("Could not fetch channel history: %s", e)
        return

    # If not subscribed: show YouTube links + Tekshirish button
    await message.answer(
        "👋 Assalomu alaykum!\n\n"
        "Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling yoki tekshirib ko‘ring.\n\n"
        "YouTube kanallarni ochib, obuna bo‘ling, so‘ngra ✅ Tekshirish tugmasini bosing 👇",
        reply_markup=youtube_keyboard
    )

# ----------------------------
# CALLBACK: check_subscription (from inline youtube_keyboard)
# ----------------------------
@dp.callback_query(F.data == "check_subscription")
async def subscription_callback(call: CallbackQuery):
    # check REQUIRED_CHANNEL membership
    if await check_subscription(call.from_user.id):
        await call.message.edit_text(
            "✅ Obunangiz tasdiqlandi. Endi botdan to‘liq foydalanishingiz mumkin.",
            reply_markup=inline_main_buttons
        )
    else:
        # If still not subscribed, present subscribe keyboard (telegram channel) and youtube links again
        await call.message.edit_text(
            "❌ Siz hali obuna bo‘lmagansiz. Iltimos, quyidagi kanalga obuna bo‘ling:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Kanalga obuna bo‘lish", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
                    [InlineKeyboardButton(text="▶️ YouTube 1", url="https://www.youtube.com/@M24_SAHAXA")],
                    [InlineKeyboardButton(text="▶️ YouTube 2", url="https://www.youtube.com/@SHAXA_GAMEPLAY")],
                    [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")]
                ]
            )
        )
    await call.answer()

# ----------------------------
# CALLBACK: register / start_payment (payment flow)
# ----------------------------
@dp.callback_query(F.data == "register")
async def register_callback(call: CallbackQuery, state: FSMContext):
    await ask_for_payment(call, state)
    await call.answer()

@dp.callback_query(F.data == "start_payment")
async def start_payment_callback(call: CallbackQuery, state: FSMContext):
    await ask_for_payment(call, state)
    await call.answer()

# ----------------------------
# MESSAGE: handle check (photo/document) while waiting_for_payment_check
# ----------------------------
@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext):
    """
    When user sends photo/document as payment check, forward to admin with approve/reject buttons.
    """
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

    # Set state to waiting_for_admin_approval (admin will set waiting_for_pubg_nick)
    await state.set_state(RegistrationState.waiting_for_admin_approval)

# ----------------------------
# CALLBACK: approve / reject (admin)
# ----------------------------
@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return

    try:
        user_id = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("Xato format", show_alert=True)
        return

    # Notify user and set FSM to waiting_for_pubg_nick
    try:
        await bot.send_message(user_id, "✅ Chekingiz tasdiqlandi. Endi PUBG nickname va ID'ingizni yuboring.")
        # set state for that user
        key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick.state)
        await call.message.edit_reply_markup()  # remove buttons from admin copy
        await call.answer("✅ Tasdiqlandi")
    except Exception as e:
        logger.exception("approve_callback error: %s", e)
        await call.answer("Xatolik yuz berdi.", show_alert=True)

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return

    try:
        user_id = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("Xato format", show_alert=True)
        return

    try:
        await bot.send_message(user_id, "❌ Chekingiz rad etildi. Qayta urinib ko‘ring.")
        key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
        await dp.storage.clear_state(key)
        await call.message.edit_reply_markup()
        await call.answer("❌ Rad etildi")
    except Exception as e:
        logger.exception("reject_callback error: %s", e)
        await call.answer("Xatolik yuz berdi", show_alert=True)

# ----------------------------
# MESSAGE: handle pubg info after admin approved
# ----------------------------
@dp.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_info(message: Message, state: FSMContext):
    """
    When user sends nickname and ID (text), store to Google Sheets and confirm.
    """
    text = message.text or ""
    pubg_nick = text.strip()
    pubg_id = ""
    tokens = text.replace(",", " ").split()
    if len(tokens) >= 2:
        # assume last token is ID
        pubg_id = tokens[-1]
        pubg_nick = " ".join(tokens[:-1])
    else:
        pubg_nick = text.strip()
        pubg_id = ""

    # Append to sheet
    ok = append_to_sheet(pubg_nick or message.from_user.full_name, pubg_id or "ID not provided")
    if ok:
        await message.answer("📋 Ma'lumot qabul qilindi. Reytingga qoʻshildi. Rahmat!", reply_markup=reply_social_menu)
    else:
        await message.answer("⚠️ Reytingga qoʻshishda xatolik yuz berdi. Admin bilan bog‘laning.", reply_markup=reply_social_menu)

    # Notify admin
    try:
        await bot.send_message(ADMIN_ID, f"🆕 Yangi qatnashchi: {message.from_user.full_name}\nPUBG: {pubg_nick} | ID: {pubg_id}\nUser ID: {message.from_user.id}")
    except Exception:
        pass

    await state.clear()

# ----------------------------
# CALLBACK: results / my_games / contact_admin
# ----------------------------
@dp.callback_query(F.data == "results")
async def results_callback(call: CallbackQuery):
    url_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="📊 Reytingni ko‘rish",
            url="https://docs.google.com/spreadsheets/d/1T0JuaRetTKusLkR8Kb21Ie87kA2Z4nv3fDJ2ziyuAh4"
        )]]
    )
    await call.message.answer("📊 Reyting jadvali:", reply_markup=url_button)
    await call.answer()

@dp.callback_query(F.data == "my_games")
async def my_games_callback(call: CallbackQuery):
    await call.message.answer("🎮 Sizda hozircha o‘yin yo‘q.")
    await call.answer()

@dp.callback_query(F.data == "contact_admin")
async def contact_admin_callback(call: CallbackQuery):
    await call.message.answer("✉️ Admin: @M24_SHAXA")
    await call.answer()

# ----------------------------
# REPLY KEYBOARD HANDLERS (social buttons) - keep originals
# ----------------------------
@dp.message(F.text == "📸 Instagram")
async def send_instagram(message: Message):
    await message.answer("Instagram sahifam: https://www.instagram.com/m24_shaxa_/")

@dp.message(F.text == "📱 Telegram")
async def send_telegram(message: Message):
    await message.answer(f"Telegram kanalimiz: https://t.me/M24SHaxa_youtube")

@dp.message(F.text == "🎮 Twitch")
async def send_twitch(message: Message):
    await message.answer("Twitch sahifam: https://www.twitch.tv/m24_shaxa")

@dp.message(F.text == "▶️ YouTube")
async def send_youtube(message: Message):
    await message.answer("YouTube kanalimiz: https://www.youtube.com/@M24_SAHAXA")

@dp.message(F.text == "📍 ASOSIY MENYU")
async def main_menu_return(message: Message, state: FSMContext):
    # Reuse start handler behavior (no new subscription check here)
    await message.answer(
        "🔙 Asosiy menyu",
        reply_markup=inline_main_buttons
    )

# ----------------------------
# COMMANDS: help / about / contactwithadmin / mygames / reyting
# ----------------------------
@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "🆘 <b>Yordam:</b>\n\n"
        "/register – Ro'yxatdan o'tish\n"
        "/mygames – Mening o‘yinlarim\n"
        "/reyting – Reyting jadvali\n"
        "/contactwithadmin – Admin bilan bog‘lanish\n"
        "/about – Bot haqida\n"
        "/help – Yordam"
    )

@dp.message(Command("about"))
async def about_command(message: Message):
    await message.answer(
        "🎮 <b>PUBG MOBILE TURNIR BOT</b> 🎮\n\n"
        "Bu bot orqali siz pullik PUBG Mobile turnirlarida qatnashishingiz,\n"
        "to‘lov qilgan holda ishtirok etishingiz va sovrinli o‘rinlar uchun kurashishingiz mumkin! 🏆"
    )

@dp.message(Command("contactwithadmin"))
async def contact_with_admin_command(message: Message):
    await message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")

@dp.message(Command("mygames"))
async def my_games_command(message: Message):
    await message.answer("🎮 Sizda hozircha o‘yin yo‘q. Tez orada bo‘ladi!")

@dp.message(Command("reyting"))
async def reyting_command(message: Message):
    try:
        sheet = connect_to_sheet()
        data = sheet.get_all_values()
    except Exception as e:
        logger.exception("Get sheet failed")
        await message.answer("⚠️ Reytingni olishda xatolik yuz berdi.")
        return

    if len(data) <= 1:
        await message.answer("📊 Reytinglar hali mavjud emas.")
        return

    # Show top 20
    response_lines = ["🏆 Reyting:\n"]
    for idx, row in enumerate(data[1:21], start=1):
        nickname = row[0] if len(row) > 0 else "-"
        pubg_id = row[1] if len(row) > 1 else "-"
        response_lines.append(f"{idx}. {nickname} (ID: {pubg_id})")
    await message.answer("\n".join(response_lines))

# ----------------------------
# ERROR HANDLING
# ----------------------------
@dp.errors()
async def global_error_handler(update, exception):
    logger.exception("Unhandled exception: %s", exception)
    return True

# ----------------------------
# KEEP ALIVE (optional)
# ----------------------------
def keep_alive():
    """
    If running on Replit or similar service, implement a simple server ping keepalive.
    Otherwise leave empty.
    """
    try:
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"OK")

        server = HTTPServer(("0.0.0.0", 8080), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Keep-alive server started on port 8080")
    except Exception:
        logger.info("Keep-alive not started (environment may not allow)")

# ----------------------------
# MAIN
# ----------------------------
async def main():
    keep_alive()
    logger.info("Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
