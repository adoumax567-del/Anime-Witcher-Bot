import logging
import re
import asyncio
import os
import uvicorn
import httpx
import time
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
# Increase timeouts for better reliability
application = Application.builder().token(TOKEN).connect_timeout(30).read_timeout(30).write_timeout(30).build()

# --- API Endpoints ---

@api_app.get("/")
async def health_check():
    return {"status": "active", "service": "Anime Witcher Hybrid Service"}

@api_app.get("/get_links")
async def get_links(query: str = Query(..., description="Anime Name and Episode (e.g. Sally 1)")):
    try:
        anime_name, ep_num = DATA.parse_smart_query(query)
        results = DATA.search_anime(anime_name)
        if not results:
            return JSONResponse(content={"status": "error", "message": "No anime found"}, status_code=404)
        
        target_anime = results[0]
        doc_ref = target_anime["doc_ref"]
        episodes = DATA.get_episodes(doc_ref)
        
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), episodes[0] if episodes else None)
        if not target_ep:
            return JSONResponse(content={"status": "error", "message": "Episode not found"}, status_code=404)

        servers = DATA.get_servers(doc_ref, target_ep["id"])
        return {
            "status": "success",
            "anime": target_anime.get("name", "Unknown"),
            "episode": ep_num or 1,
            "links": servers
        }
    except Exception as e:
        logger.error(f"API Error: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

@api_app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        f"👋 أهلاً بك في **Anime Witcher Bot**!\n\n"
        "أنا بوت متخصص في جلب حلقات الأنمي للمشاهدة المباشرة.\n\n"
        "🚀 **كيفية الاستخدام؟**\n"
        "اكتب اسم الأنمي متبوعاً برقم الحلقة.\n"
        "مثال: `ون بيس 1000`"
    )
    keyboard = [["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"], ["ℹ️ معلومات أنمي", "❓ مساعدة"]]
    await update.message.reply_text(welcome_text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")

async def send_video_direct(update: Update, context: ContextTypes.DEFAULT_TYPE, video_url: str, caption: str):
    """Sends video directly using URL to ensure instant playback without server-side download delay."""
    processing_msg = await update.message.reply_text("⏳ جاري استخراج الفيديو... ثوانٍ من فضلك.")
    try:
        # Using URL directly is the fastest way for Telegram to process videos if they are streamable
        await update.message.reply_video(
            video=video_url,
            caption=caption,
            supports_streaming=True,
            parse_mode="Markdown"
        )
        await processing_msg.delete()
    except Exception as e:
        logger.error(f"Direct video send failed: {e}")
        # Fallback: Provide the link if direct video fails
        await processing_msg.edit_text(
            f"❌ فشل تشغيل الفيديو تلقائياً داخل تليجرام.\n\n🔗 **يمكنك المشاهدة عبر الرابط المباشر:**\n[اضغط هنا للمشاهدة]({video_url})",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات", "ℹ️ معلومات أنمي"]:
        await update.message.reply_text("📝 أرسل اسم الأنمي الذي تبحث عنه...")
        return
    if text == "❓ مساعدة":
        await update.message.reply_text("اكتب اسم الأنمي + رقم الحلقة (مثال: ناروتو 1)")
        return

    anime_name, ep_num = DATA.parse_smart_query(text)
    status_msg = await update.message.reply_text(f"🔍 جاري البحث عن: {anime_name}...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await status_msg.edit_text("❌ لم نجد نتائج، تأكد من الاسم.")
        return

    if ep_num is not None:
        target_anime = results[0]
        episodes = DATA.get_episodes(target_anime["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), None)
        
        if target_ep:
            servers = DATA.get_servers(target_anime["doc_ref"], target_ep["id"])
            pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
            if pd_link:
                await status_msg.delete()
                await send_video_direct(update, context, pd_link, f"🎬 **{target_anime['name']}** - الحلقة {ep_order}")
                return
            else:
                await status_msg.edit_text("❌ لم نجد رابط PD مباشر لهذه الحلقة.")
                return

    keyboard = [[InlineKeyboardButton(res["name"], callback_data=f"details_{res['doc_ref']}")] for res in results]
    await status_msg.edit_text("✅ اختر الأنمي المطلوب:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("details_"):
        doc_ref = data.replace("details_", "")
        details = DATA.get_anime_details(doc_ref)
        if details:
            msg = f"🍥 **{details['name']}**\n⭐ التقييم: {details['rating']}\n📺 الحلقات: {details['episodes_count']}\n\n📖 {details['story'][:300]}..."
            keyboard = [[InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"eps_{doc_ref}")]]
            if details.get("poster"):
                await query.message.reply_photo(photo=details["poster"], caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("eps_"):
        doc_ref = data.replace("eps_", "")
        episodes = DATA.get_episodes(doc_ref)
        keyboard = []
        row = []
        for ep in episodes[:40]: # Limit to first 40 for UI
            row.append(InlineKeyboardButton(f"H {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        await query.message.reply_text("🎬 اختر الحلقة:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("srv|"):
        parts = data.split("|")
        doc_ref, ep_id, ep_order = parts[1], parts[2], parts[3]
        servers = DATA.get_servers(doc_ref, ep_id)
        pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
        if pd_link:
            await send_video_direct(query.message, context, pd_link, f"🎬 الحلقة {ep_order}")
        else:
            await query.message.reply_text("❌ رابط PD غير متوفر حالياً.")

# --- Lifecycle ---

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(button_click))

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
