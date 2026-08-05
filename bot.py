import logging
import re
import asyncio
import os
import uvicorn
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
application = Application.builder().token(TOKEN).build()

# --- API Endpoints ---

@api_app.get("/")
async def health_check():
    return {"status": "active", "service": "Anime Witcher Hybrid Service"}

@api_app.get("/get_links")
async def get_links(query: str = Query(..., description="Anime Name and Episode (e.g. Sally 1)")):
    anime_name, ep_num = DATA.parse_smart_query(query)
    results = DATA.search_anime(anime_name)
    
    if not results:
        return JSONResponse(content={"status": "error", "message": "No anime found"}, status_code=404)
    
    target_anime = results[0]
    doc_ref = target_anime["doc_ref"]
    episodes = DATA.get_episodes(doc_ref)
    
    target_ep = None
    if ep_num is not None:
        for ep in episodes:
            if ep["order"] == ep_num:
                target_ep = ep
                break
    else:
        # Default to first episode if not specified
        target_ep = episodes[0] if episodes else None

    if not target_ep:
        return JSONResponse(content={"status": "error", "message": "Episode not found"}, status_code=404)

    servers = DATA.get_servers(doc_ref, target_ep["id"])
    # Filter for PD links as requested by user for the API service
    pd_only = [s for s in servers if "PD" in s["name"]]
    
    return {
        "status": "success",
        "anime": target_anime["name"],
        "episode": ep_num or 1,
        "links": pd_only if pd_only else servers
    }

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
    user = update.effective_user
    welcome_text = (
        f"👋 أهلاً بك يا {user.first_name} في **Anime Witcher Bot**!\n\n"
        "أنا بوت متخصص في جلب روابط المشاهدة المباشرة للأنمي.\n\n"
        "🚀 **كيفية الاستخدام؟**\n"
        "اكتب اسم الأنمي متبوعاً برقم الحلقة للحصول على الفيديو مباشرة.\n"
        "مثال: `ناروتو 1` أو `Sally Episode 5`\n\n"
        "👇 أو استخدم الأزرار للبحث التقليدي!"
    )
    
    keyboard = [
        ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"],
        ["ℹ️ معلومات أنمي", "❓ مساعدة"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **دليل الاستخدام السريع:**\n\n"
        "🔹 **طلب مباشر**: اكتب `[الاسم] [رقم الحلقة]` وسأجلب لك الفيديو فوراً.\n"
        "🔹 **البحث**: اكتب اسم الأنمي فقط لعرض النتائج المتاحة.\n        "🔹 **المشاهدة المباشرة**: البوت يرسل الفيديو مباشرة لتشاهده داخل تليجرام.\n\n"
        "💡 **مثال**: `ون بيس 1000`"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Removed api_info command as per user request

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات", "ℹ️ معلومات أنمي"]:
        await update.message.reply_text(f"📝 من فضلك أرسل اسم الأنمي الذي تبحث عنه...")
        context.user_data["action"] = text
        return

    if text == "❓ مساعدة":
        await help_command(update, context)
        return

    anime_name, ep_num = DATA.parse_smart_query(text)
    await update.message.reply_text(f"⏳ جاري البحث عن \'{anime_name}\'...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await update.message.reply_text("❌ عذراً، لم نجد نتائج. تأكد من كتابة الاسم بشكل صحيح.")
        return

    if ep_num is not None:
        target_anime = results[0]
        doc_ref = target_anime["doc_ref"]
        episodes = DATA.get_episodes(doc_ref)
        
        target_ep = None
        for ep in episodes:
            if ep["order"] == ep_num:
                target_ep = ep
                break
        
        if target_ep:
            servers = DATA.get_servers(doc_ref, target_ep["id"])
            if servers:
                # Prioritize PD links for direct video sending
                direct_link = next((s["url"] for s in servers if "PD" in s["name"]), None)
                
                if direct_link:
                    await update.message.reply_text(f"✅ جاري إرسال الحلقة {ep_num} من {target_anime["name"]}...")
                    try:
                        await update.message.reply_video(video=direct_link, caption=f"🎬 {target_anime["name"]} - الحلقة {ep_num}")
                    except Exception as e:
                        logger.error(f"Failed to send video: {e}")
                        await update.message.reply_text(f"❌ فشل إرسال الفيديو مباشرة. قد يكون الحجم كبيراً جداً أو هناك مشكلة مؤقتة.")
                else:
                    await update.message.reply_text(f"❌ لم نجد رابط PD مباشر للحلقة {ep_num} من {target_anime["name"]}. لا يمكن إرسال الفيديو مباشرة.")
                return
            else:
                await update.message.reply_text(f"❌ لم نجد سيرفرات متاحة للحلقة {ep_num} من {target_anime["name"]}.")
        else:
            await update.message.reply_text(f"❌ لم نجد الحلقة {ep_num} في قائمة حلقات {target_anime["name"]}.")

    keyboard = [[InlineKeyboardButton(res.get("name", "Unknown"), callback_data=f"details_{res.get("doc_ref")}")] for res in results]
    await update.message.reply_text("✅ وجدنا هذه النتائج، اختر المطلوب:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("details_"):
        doc_ref = data.replace("details_", "")
        details = DATA.get_anime_details(doc_ref)
        if not details:
            await query.edit_message_text("❌ فشل جلب التفاصيل.")
            return

        msg = (
            f"🍥 **معلومات الأنمي**\n\n"
            f"🎬 **الاسم**: {details["name"]}\n"
            f"⭐ **التقييم**: {details["rating"]}\n"
            f"📅 **سنة العرض**: {details["year"]}\n"
            f"🎭 **التصنيف**: {details["genres"]}\n"
            f"📺 **عدد الحلقات**: {details["episodes_count"]}\n\n"
            f"📖 **القصة**:\n{details["story"]}"
        )
        keyboard = [[InlineKeyboardButton("📺 مشاهدة الحلقات", callback_data=f"eps_{doc_ref}")]]
        
        if details["poster"]:
            try:
                await query.message.reply_photo(photo=details["poster"], caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            except:
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("eps_"):
        doc_ref = data.replace("eps_", "")
        episodes = DATA.get_episodes(doc_ref)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
            return

        keyboard = []
        row = []
        for ep in episodes:
            row.append(InlineKeyboardButton(f"Ep {ep["order"]}", callback_data=f"srv|{doc_ref}|{ep["id"]}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        await query.message.reply_text(f"🎬 **قائمة الحلقات ({len(episodes)})**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("srv|"):
        _, doc_ref, ep_id = data.split("|")
        servers = DATA.get_servers(doc_ref, ep_id)
        if not servers:
            await query.message.reply_text("❌ لا توجد سيرفرات متاحة.")
            return

        direct_link = next((s["url"] for s in servers if "PD" in s["name"]), None)
        if direct_link:
            await query.message.reply_text(f"✅ جاري محاولة إرسال الفيديو مباشرة...")
            try:
                await query.message.reply_video(video=direct_link, caption=f"🎬 حلقة من {doc_ref.split("/")[-1]}")
            except Exception as e:
                logger.error(f"Failed to send video from callback: {e}")
                await query.message.reply_text("❌ فشل إرسال الفيديو مباشرة. قد يكون الحجم كبيراً جداً أو هناك مشكلة مؤقتة.")
        else:
            await query.message.reply_text("❌ لم نجد رابط PD مباشر. لا يمكن إرسال الفيديو مباشرة.")

# --- Lifecycle Management ---

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
# application.add_handler(CommandHandler("api", api_info)) # Removed as per user request
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(button_click))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Bot...")
    await application.initialize()
    
    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        await application.bot.set_webhook(url=f"{webhook_url}/telegram-webhook")
        logger.info(f"Webhook set to: {webhook_url}/telegram-webhook")
    else:
        logger.warning("WEBHOOK_URL environment variable not set. Telegram bot will not receive updates via webhook.")

    await application.start()
    yield
    logger.info("Shutting down Bot...")
    await application.stop()
    await application.shutdown()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(api_app, host="0.0.0.0", port=port)
