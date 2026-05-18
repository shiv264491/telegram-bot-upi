import os
import logging
import qrcode
import io
import urllib.parse
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request, jsonify

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
UPI_ID = os.getenv("UPI_ID", "zdxyzofficial-2@okhdfcbank")
UPI_NAME = os.getenv("UPI_NAME", "ZdXyz Official")
APP_PRICE = os.getenv("APP_PRICE", "99")
APP_DOWNLOAD_LINK = os.getenv("APP_DOWNLOAD_LINK", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)
telegram_app = None
main_loop = None
waiting_for_utr = set()


def generate_upi_qr() -> io.BytesIO:
    upi_url = f"upi://pay?pa={UPI_ID}&pn={urllib.parse.quote(UPI_NAME)}&am={APP_PRICE}&cu=INR&tn=App+Purchase"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)
    return bio


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton(f"💳 App Khareedein — ₹{APP_PRICE}", callback_data="buy_app")]]
    await update.message.reply_text(
        f"👋 Namaste *{user.first_name}*!\n\n"
        f"🚀 Premium App khareedne ke liye swagat hai!\n\n"
        f"💎 *Price:* ₹{APP_PRICE}/-\n\n"
        f"✅ UPI se pay karein → UTR bhejein → *Turant app link milega!*\n\n"
        f"👇 Button dabao:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def buy_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ QR Code ban raha hai...")
    qr_bio = generate_upi_qr()
    keyboard = [[InlineKeyboardButton("✅ Maine Pay Kar Diya — UTR Bhejein", callback_data="send_utr")]]
    await query.message.reply_photo(
        photo=qr_bio,
        caption=(
            f"📱 *QR Code Scan Karke Pay Karein!*\n\n"
            f"💰 Amount: *₹{APP_PRICE}/-*\n"
            f"🏦 UPI ID: `{UPI_ID}`\n\n"
            f"*Steps:*\n"
            f"1️⃣ Google Pay / PhonePe se QR scan karein\n"
            f"2️⃣ ₹{APP_PRICE}/- pay karein\n"
            f"3️⃣ UTR number copy karein\n"
            f"4️⃣ Neeche button dabao\n\n"
            f"⚡ *Verify hote hi app link aa jayega!*"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    waiting_for_utr.add(query.from_user.id)
    await query.message.reply_text(
        "📝 *Apna UTR / Transaction ID paste karein:*\n\n"
        "_(Google Pay → Transaction details → UTR Number)_\n\n"
        "👇 UTR yahan paste karein:",
        parse_mode="Markdown"
    )


async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    utr = update.message.text.strip()

    if user.id not in waiting_for_utr:
        return

    if len(utr) < 8 or not any(c.isdigit() for c in utr):
        await update.message.reply_text("❌ *Galat UTR!* Dobara sahi UTR paste karein:", parse_mode="Markdown")
        return

    waiting_for_utr.discard(user.id)
    await update.message.reply_text(
        f"⏳ *Verify ho raha hai...*\nUTR: `{utr}`\nThoda wait karein...",
        parse_mode="Markdown"
    )

    if ADMIN_ID != 0:
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}_{utr}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}")
        ]]
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 *Naya Payment Request!*\n\n"
                    f"👤 User: {user.first_name}\n"
                    f"🆔 ID: `{user.id}`\n"
                    f"💰 Amount: ₹{APP_PRICE}/-\n"
                    f"🧾 UTR: `{utr}`\n\n"
                    f"Approve ya Reject karein:"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Admin notified for user {user.id}")
        except Exception as e:
            logger.error(f"Admin notify error: {e}")
            await send_app_link(context.bot, user.id, utr)
    else:
        await send_app_link(context.bot, user.id, utr)


async def send_app_link(bot, user_id: int, utr: str):
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"🎉 *Payment Verify Ho Gaya!*\n\n"
                f"✅ UTR: `{utr}`\n\n"
                f"📱 *App Download Link:*\n\n"
                f"🔗 {APP_DOWNLOAD_LINK}\n\n"
                f"⚠️ Yeh link sirf aapke liye hai.\n"
                f"❓ Problem ho toh /start karein."
            ),
            parse_mode="Markdown"
        )
        logger.info(f"App link sent to {user_id}")
    except Exception as e:
        logger.error(f"Send app link error: {e}")


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    user_id = int(parts[1])
    utr = parts[2]
    await send_app_link(context.bot, user_id, utr)
    await query.edit_message_text(
        f"✅ *Approved!* User ko link bhej diya!\nUTR: `{utr}`",
        parse_mode="Markdown"
    )


async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[1])
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ *Payment verify nahi hua!*\n\nSahi UTR ke saath dobara try karein.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Reject error: {e}")
    await query.edit_message_text(f"❌ *Rejected!* User `{user_id}`", parse_mode="Markdown")


@flask_app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if telegram_app is None or main_loop is None:
        return jsonify({"status": "error"}), 500
    data = request.get_json()
    future = asyncio.run_coroutine_threadsafe(
        process_update(data),
        main_loop
    )
    try:
        future.result(timeout=30)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return jsonify({"status": "ok"}), 200


async def process_update(data):
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


async def run_bot():
    global telegram_app, main_loop
    main_loop = asyncio.get_event_loop()

    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(buy_app, pattern="^buy_app$"))
    telegram_app.add_handler(CallbackQueryHandler(send_utr, pattern="^send_utr$"))
    telegram_app.add_handler(CallbackQueryHandler(admin_approve, pattern="^approve_"))
    telegram_app.add_handler(CallbackQueryHandler(admin_reject, pattern="^reject_"))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr))

    await telegram_app.initialize()
    await telegram_app.bot.delete_webhook(drop_pending_updates=True)
    await telegram_app.bot.set_webhook(url=f"{WEBHOOK_BASE_URL}/telegram-webhook")
    await telegram_app.start()
    logger.info("✅ Bot start ho gaya!")

    import threading
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False),
        daemon=True
    )
    flask_thread.start()

    # Bot chalata raho
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_bot())
