import logging
import re
import asyncio
import os
import uvicorn
import httpx
import time
import tempfile
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from data_manager import DataManager
from fastapi import FastAPI, Query, Request
from starlette.responses import JSONResponse

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = DataManager()

# FastAPI App
api_app = FastAPI(title="Anime Witcher Service API")

# Telegram Bot Setup
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg")
# Initialize application without starting it immediately to avoid event loop issues
application = Application.builder().token(TOKEN).build()

# --- API Endpoints ---

@api_app.get("/")
async def health_check():
    return {"status": "active", "service": "Anime Witcher Bot Service"}

@api_app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)

# --- Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = "👋 أهلاً بك في **Anime Witcher Bot**!\n\nاكتب اسم الأنمي ورقم الحلقة للمشاهدة المباشرة.\nمثال: `ناروتو 1`"
    keyboard = [["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"]]
    await update.message.reply_text(welcome, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")

async def send_video_native(update: Update, context: ContextTypes.DEFAULT_TYPE, video_url: str, caption: str):
    """Downloads and sends video as a native Telegram video file to ensure it plays in-app."""
    status_msg = await update.message.reply_text("⏳ جاري تجهيز الفيديو للمشاهدة المباشرة... (قد يستغرق وقتاً للحجم الكبير)")
    
    temp_path = None
    try:
        # 1. Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            temp_path = tmp.name
            async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
                async with client.stream("GET", video_url) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    last_update = time.time()
                    
                    for chunk in response.iter_bytes():
                        tmp.write(chunk)
                        downloaded += len(chunk)
                        if time.time() - last_update > 5:
                            percent = (downloaded / total) * 100 if total > 0 else 0
                            await status_msg.edit_text(f"⏳ جاري التحميل: {percent:.1f}%")
                            last_update = time.time()
        
        # 2. Upload as Video
        await status_msg.edit_text("✅ اكتمل التحميل. جاري الرفع لتليجرام...")
        with open(temp_path, "rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=caption,
                supports_streaming=True,
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60
            )
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Native send failed: {e}")
        await status_msg.edit_text(f"❌ فشل الإرسال المباشر. يمكنك استخدام الرابط:\n[مشاهدة مباشرة]({video_url})", parse_mode="Markdown")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    anime_name, ep_num = DATA.parse_smart_query(text)
    
    status = await update.message.reply_text(f"🔍 جاري البحث عن: {anime_name}...")
    results = DATA.search_anime(anime_name)
    
    if not results:
        await status.edit_text("❌ لم نجد نتائج.")
        return

    if ep_num:
        target = results[0]
        episodes = DATA.get_episodes(target["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), None)
        if target_ep:
            servers = DATA.get_servers(target["doc_ref"], target_ep["id"])
            pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
            if pd_link:
                await status.delete()
                await send_video_native(update, context, pd_link, f"🎬 **{target['name']}** - الحلقة {ep_num}")
                return
    
    buttons = [[InlineKeyboardButton(res["name"], callback_data=f"det|{res['doc_ref']}")] for res in results]
    await status.edit_text("✅ اختر الأنمي:", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("det|"):
        doc_ref = data.split("|")[1]
        details = DATA.get_anime_details(doc_ref)
        if details:
            text = f"🍥 **{details['name']}**\n⭐ {details['rating']}\n\n{details['story'][:300]}..."
            btn = [[InlineKeyboardButton("📺 الحلقات", callback_data=f"eps|{doc_ref}")]]
            if details.get("poster"):
                await query.message.reply_photo(photo=details["poster"], caption=text, reply_markup=InlineKeyboardMarkup(btn))
            else:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btn))
    
    elif data.startswith("eps|"):
        doc_ref = data.split("|")[1]
        episodes = DATA.get_episodes(doc_ref)
        buttons = []
        row = []
        for ep in episodes[:40]:
            row.append(InlineKeyboardButton(f"Ep {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await query.message.reply_text("🎬 اختر الحلقة:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("srv|"):
        _, doc_ref, ep_id, ep_order = data.split("|")
        servers = DATA.get_servers(doc_ref, ep_id)
        pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
        if pd_link:
            await send_video_native(update, context, pd_link, f"🎬 الحلقة {ep_order}")
        else:
            await query.message.reply_text("❌ رابط PD غير متوفر.")

# --- Lifecycle ---

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(CallbackQueryHandler(cb_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        await application.bot.set_webhook(url=f"{webhook_url.rstrip('/')}/telegram-webhook")
    await application.start()
    yield
    await application.stop()
    await application.shutdown()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(api_app, host="0.0.0.0", port=port)
