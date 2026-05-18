import os
import logging
import json
import qrcode
import io
import urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request, jsonify
import threading
import asyncio

# ─────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8960302623:AAFPBaBZ_wRVkV1oSCYiijoZY0E6Eu3lWCg")
UPI_ID = os.getenv("UPI_ID", "zdxyzofficial-2@okhdfcbank")
UPI_NAME = os.getenv("UPI_NAME", "ZdXyz Official")
APP_PRICE = os.getenv("APP_PRICE", "99")
APP_DOWNLOAD_LINK = os.getenv("APP_DOWNLOAD_LINK", "https://your-app-download-link.com/app.apk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Aapka Telegram user ID
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://telegram-app-bot-production.up.railway.app")
# ─────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app
flask_app = Flask(__name__)

# Telegram app (global)
telegram_app = None

# UTR wait list — jinse UTR ka wait kar rahe hain
waiting_for_utr = set()

# ─────────────────────────────────────────
#  QR CODE GENERATE
# ─────────────────────────────────────────
def generate_upi_qr(amount: str) -> io.BytesIO:
    upi_url = (
        f"upi://pay?pa={UPI_ID}"
        f"&pn={urllib.parse.quote(UPI_NAME)}"
        f"&am={amount}"
        f"&cu=INR"
        f"&tn=App+Purchase"
    )
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)
    return bio


# ─────────────────────────────────────────
#  TELEGRAM HANDLERS
# ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton(f"💳 App Khareedein — ₹{APP_PRICE}", callback_data="buy_app")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"👋 Namaste *{user.first_name}*!\n\n"
        f"🚀 Hamare premium app ko khareedne ke liye aapka swagat hai!\n\n"
        f"💎 *App Price:* ₹{APP_PRICE}/-\n\n"
        f"✅ UPI se payment karein → UTR number bhejein → *Turant app link milega!*\n\n"
        f"👇 Neeche button dabao:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def buy_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # QR code generate karo
    qr_bio = generate_upi_qr(APP_PRICE)

    caption = (
        f"📱 *UPI QR Code Se Payment Karein!*\n\n"
        f"💰 Amount: *₹{APP_PRICE}/-*\n"
        f"🏦 UPI ID: `{UPI_ID}`\n\n"
        f"*Steps:*\n"
        f"1️⃣ Google Pay / PhonePe / Paytm se QR scan karein\n"
        f"2️⃣ ₹{APP_PRICE}/- pay karein\n"
        f"3️⃣ Payment ke baad *UTR/Transaction ID* copy karein\n"
        f"4️⃣ Neeche button dabao aur UTR bhejein\n\n"
        f"⚡ *Verify hote hi app download link aa jayega!*"
    )

    keyboard = [[InlineKeyboardButton("✅ UTR Number Bhejein", callback_data="send_utr")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("⏳ QR Code generate ho raha hai...", parse_mode="Markdown")

    await query.message.reply_photo(
        photo=qr_bio,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def send_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    waiting_for_utr.add(user.id)

    await query.message.reply_text(
        "📝 *Apna UTR / Transaction ID paste karein:*\n\n"
        "UTR 12 digit ka number hota hai jo payment ke baad milta hai\n"
        "_(Google Pay → Transaction details → UTR Number)_\n\n"
        "👇 Neeche UTR number type/paste karein:",
        parse_mode="Markdown"
    )


async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    utr = update.message.text.strip()

    if user.id not in waiting_for_utr:
        return

    # UTR basic validation
    if len(utr) < 10 or not any(c.isdigit() for c in utr):
        await update.message.reply_text(
            "❌ *Galat UTR format!*\n\n"
            "UTR number 10-12 digit ka hota hai.\n"
            "Dobara sahi UTR paste karein:",
            parse_mode="Markdown"
        )
        return

    waiting_for_utr.discard(user.id)

    # User ko wait message bhejo
    await update.message.reply_text(
        f"⏳ *Verify ho raha hai...*\n\n"
        f"UTR: `{utr}`\n\n"
        f"Thoda wait karein...",
        parse_mode="Markdown"
    )

    # Admin ko notification bhejo verify karne ke liye
    if ADMIN_ID and ADMIN_ID != 0:
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}_{utr}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await telegram_app.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 *Naya Payment Verify Request!*\n\n"
                    f"👤 User: [{user.first_name}](tg://user?id={user.id})\n"
                    f"🆔 User ID: `{user.id}`\n"
                    f"💰 Amount: ₹{APP_PRICE}/-\n"
                    f"🧾 UTR: `{utr}`\n\n"
                    f"Payment verify karke Approve ya Reject karein:"
                ),
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Admin notify error: {e}")

    # Auto approve (agar admin ID set nahi hai)
    if not ADMIN_ID or ADMIN_ID == 0:
        await send_app_link(user.id, utr)


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # approve_USERID_UTR
    parts = data.split("_", 2)
    user_id = int(parts[1])
    utr = parts[2]

    await send_app_link(user_id, utr)

    await query.edit_message_text(
        f"✅ *Approved!*\n\nUser `{user_id}` ko app link bhej diya gaya!\nUTR: `{utr}`",
        parse_mode="Markdown"
    )


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # reject_USERID
    user_id = int(data.split("_")[1])

    try:
        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ *Payment Verify Nahi Hua!*\n\n"
                "Aapka UTR number match nahi kiya.\n\n"
                "Agar payment ki hai toh sahi UTR ke saath dobara try karein ya admin se contact karein."
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error notifying user: {e}")

    await query.edit_message_text(
        f"❌ *Rejected!*\n\nUser `{user_id}` ko reject message bhej diya.",
        parse_mode="Markdown"
    )


async def send_app_link(user_id: int, utr: str):
    try:
        await telegram_app.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 *Payment Verify Ho Gaya! Shukriya!*\n\n"
                f"✅ UTR: `{utr}`\n\n"
                f"📱 *Aapka App Download Link:*\n\n"
                f"🔗 {APP_DOWNLOAD_LINK}\n\n"
                f"⚠️ Yeh link sirf aapke liye hai, share na karein.\n\n"
                f"❓ Koi problem ho toh /start karein."
            ),
            parse_mode="Markdown"
        )
        logger.info(f"App link sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error sending app link: {e}")


# ─────────────────────────────────────────
#  FLASK WEBHOOK
# ─────────────────────────────────────────
@flask_app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if telegram_app is None:
        return jsonify({"status": "error"}), 500
    data = request.get_json()

    async def process():
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(process())
    loop.close()
    return jsonify({"status": "ok"}), 200


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    global telegram_app

    telegram_app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(buy_app, pattern="^buy_app$"))
    telegram_app.add_handler(CallbackQueryHandler(send_utr, pattern="^send_utr$"))
    telegram_app.add_handler(CallbackQueryHandler(admin_approve, pattern="^approve_"))
    telegram_app.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr))

    # Webhook setup
    async def setup():
        await telegram_app.initialize()
        await telegram_app.bot.delete_webhook(drop_pending_updates=True)
        webhook_url = f"{WEBHOOK_BASE_URL}/telegram-webhook"
        await telegram_app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Webhook set: {webhook_url}")
        await telegram_app.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())

    logger.info("✅ Bot start ho gaya!")
    flask_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))


if __name__ == "__main__":
    main()
