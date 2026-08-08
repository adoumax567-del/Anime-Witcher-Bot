import logging
import re
import asyncio
import os
import uvicorn
import httpx
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
api_app = FastAPI(title="Anime Witcher Web Service")

# Telegram Bot Setup
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg")
application = Application.builder().token(TOKEN).build()

# --- API Endpoints ---

@api_app.get("/")
async def health_check():
    return {"status": "active", "service": "Anime Witcher Web Service"}

@api_app.get("/get_links")
async def get_links(query: str = Query(..., description="Anime Name and Episode")):
    try:
        anime_name, ep_num = DATA.parse_smart_query(query)
        results = DATA.search_anime(anime_name)
        if not results:
            return JSONResponse(content={"status": "error", "message": "No anime found"}, status_code=404)
        
        target_anime = results[0]
        episodes = DATA.get_episodes(target_anime["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), episodes[0] if episodes else None)
        
        if not target_ep:
            return JSONResponse(content={"status": "error", "message": "Episode not found"}, status_code=404)

        servers = DATA.get_servers(target_anime["doc_ref"], target_ep["id"])
        return {
            "status": "success",
            "anime": target_anime.get("name", "Unknown"),
            "episode": ep_num or 1,
            "links": servers
        }
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

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
    welcome = (
        "👋 أهلاً بك في **Anime Witcher Bot**!\n\n"
        "أنا بوت متخصص في جلب **روابط المشاهدة المباشرة** للأنمي.\n\n"
        "🚀 **كيفية الاستخدام؟**\n"
        "اكتب اسم الأنمي ورقم الحلقة (مثال: ون بيس 1000)\n"
        "وسأعطيك رابط المشاهدة المباشر الذي يفتح في المتصفح فوراً."
    )
    keyboard = [["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"]]
    await update.message.reply_text(welcome, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"]:
        await update.message.reply_text("📝 أرسل اسم الأنمي الذي تبحث عنه...")
        return

    anime_name, ep_num = DATA.parse_smart_query(text)
    status_msg = await update.message.reply_text(f"🔍 جاري البحث عن: {anime_name}...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await status_msg.edit_text("❌ لم نجد نتائج، تأكد من الاسم.")
        return

    if ep_num:
        target = results[0]
        episodes = DATA.get_episodes(target["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), None)
        if target_ep:
            servers = DATA.get_servers(target["doc_ref"], target_ep["id"])
            # Prioritize PixelDrain (PD)
            pd_server = next((s for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
            
            if pd_server:
                keyboard = [[InlineKeyboardButton("🎬 مشاهدة الحلقة الآن (في المتصفح)", url=pd_server["url"])]]
                await status_msg.delete()
                await update.message.reply_text(
                    f"🎬 **{target['name']}** - الحلقة {ep_num}\n\n"
                    f"🔗 **رابط المشاهدة المباشر:**\n`{pd_server['url']}`\n\n"
                    "اضغط على الزر أدناه للمشاهدة فوراً في المتصفح:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
            elif servers:
                keyboard = [[InlineKeyboardButton(f"🔗 {s['name']}", url=s['url'])] for s in servers[:5]]
                await status_msg.edit_text(
                    f"✅ تم العثور على **{target['name']}** - الحلقة {ep_num}\n\nاختر سيرفر المشاهدة (سيفتح في المتصفح):",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return

    buttons = [[InlineKeyboardButton(res["name"], callback_data=f"det|{res['doc_ref']}")] for res in results]
    await status_msg.edit_text("✅ اختر الأنمي المطلوب:", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("det|"):
        doc_ref = data.split("|")[1]
        details = DATA.get_anime_details(doc_ref)
        if details:
            text = f"🍥 **{details['name']}**\n⭐ {details['rating']}\n\n{details['story'][:300]}..."
            btn = [[InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"eps|{doc_ref}")]]
            if details.get("poster"):
                await query.message.reply_photo(photo=details["poster"], caption=text, reply_markup=InlineKeyboardMarkup(btn), parse_mode="Markdown")
            else:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btn), parse_mode="Markdown")
    
    elif data.startswith("eps|"):
        doc_ref = data.split("|")[1]
        episodes = DATA.get_episodes(doc_ref)
        buttons = []
        row = []
        for ep in episodes[:40]:
            row.append(InlineKeyboardButton(f"H {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await query.message.reply_text("🎬 اختر الحلقة للمشاهدة (ستفتح في المتصفح):", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("srv|"):
        _, doc_ref, ep_id, ep_order = data.split("|")
        servers = DATA.get_servers(doc_ref, ep_id)
        if not servers:
            await query.message.reply_text("❌ لا توجد سيرفرات متاحة.")
            return

        keyboard = []
        for s in servers:
            keyboard.append([InlineKeyboardButton(f"🎬 {s['name']}", url=s['url'])])
        
        await query.message.reply_text(
            f"🎬 روابط مشاهدة الحلقة {ep_order}:\n(اضغط على الرابط لفتح المشغل في المتصفح فوراً)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# --- Lifecycle ---

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
