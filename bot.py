import logging
import re
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from data_manager import DataManager
from fastapi import FastAPI, Query, Request
from starlette.responses import JSONResponse

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

DATA = DataManager()

# FastAPI App
api_app = FastAPI(title="Anime Witcher API Service")

# Telegram Bot Setup
TOKEN = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
application = Application.builder().token(TOKEN).build()

# Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"👋 أهلاً بك يا {user.first_name} في **Anime Witcher Service**!\n\n"
        "أنا بوت خدمي متطور لجلب روابط المشاهدة المباشرة فوراً.\n\n"
        "🌐 **السيرفر الجديد**: https://web-production-68612.up.railway.app/\n\n"
        "🚀 **كيفية الاستخدام؟**\n"
        "اكتب اسم الأنمي متبوعاً برقم الحلقة للحصول على الروابط مباشرة.\n"
        "مثال: `ناروتو 1` أو `Sally Episode 5`\n\n"
        "🔗 **خدمة API**: يمكنك استخدام `/api` لمعرفة كيفية استخدام الخدمة في تطبيقاتك.\n\n"
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
        "📖 **دليل الخدمة السريعة:**\n\n"
        "🔹 **طلب مباشر**: اكتب `[الاسم] [رقم الحلقة]` وسأجلب لك الروابط فوراً.\n"
        "🔹 **البحث**: اكتب اسم الأنمي فقط لعرض النتائج المتاحة.\n"
        "🔹 **سيرفر PD**: هو الأولوية لدينا لدعمه المشاهدة المباشرة داخل تليجرام.\n"
        "🔹 **خدمة الـ API**: متوفرة للمطورين لجلب روابط PD فقط بتنسيق JSON.\n\n"
        "💡 **مثال**: `ون بيس 1000`"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def api_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_text = (
        "🛠 **توثيق خدمة الـ API:**\n\n"
        "يمكنك جلب روابط PD المباشرة لتطبيقك عبر المسار التالي:\n"
        "`GET /get_links?query=اسم_الأنمي_رقم_الحلقة`\n\n"
        "📍 **رابط الخدمة**: `https://web-production-68612.up.railway.app/get_links?query=Sally 1`\n\n"
        "✅ **المميزات**:\n"
        "- يعيد روابط PD فقط.\n"
        "- الروابط محولة تلقائياً لتنسيق `?download` لتعمل كـ M3u8."
    )
    await update.message.reply_text(api_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات", "ℹ️ معلومات أنمي"]:
        await update.message.reply_text(f"📝 من فضلك أرسل اسم الأنمي الذي تبحث عنه...")
        context.user_data["action"] = text
        return

    if text == "❓ مساعدة":
        await help_command(update, context)
        return

    # Smart Parsing
    anime_name, ep_num = DATA.parse_smart_query(text)
    
    await update.message.reply_text(f"⏳ جاري البحث عن \'{anime_name}\'...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await update.message.reply_text("❌ عذراً، لم نجد نتائج. تأكد من كتابة الاسم بشكل صحيح.")
        return

    if ep_num is not None:
        # Service Mode: Directly get links for specific episode
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
                pd_link = next((s["url"] for s in servers if "💎 سيرفر PD" in s["name"]), None)
                
                if pd_link:
                    await update.message.reply_text(f"✅ جاري إرسال الحلقة {ep_num} من {target_anime["name"]}...")
                    try:
                        await update.message.reply_video(video=pd_link, caption=f"🎬 {target_anime["name"]} - الحلقة {ep_num}")
                    except Exception as e:
                        logging.error(f"Failed to send video: {e}")
                        await update.message.reply_text(f"❌ فشل إرسال الفيديو مباشرة. يمكنك تجربة الرابط: {pd_link}")
                else:
                    # If no PD link, show other links as buttons
                    keyboard = []
                    for srv in servers:
                        keyboard.append([InlineKeyboardButton(srv["name"], url=srv["url"])])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        f"❌ لم نجد سيرفر PD مباشر. تفضل الروابط الأخرى للحلقة {ep_num} من {target_anime["name"]}:",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                return
            else:
                await update.message.reply_text(f"❌ لم نجد سيرفرات متاحة للحلقة {ep_num} من {target_anime["name"]}.")
        else:
            await update.message.reply_text(f"❌ لم نجد الحلقة {ep_num} في قائمة حلقات {target_anime["name"]}.")

    # Standard Mode: Show results
    keyboard = []
    for res in results:
        name = res.get("name", "Unknown")
        doc_ref = res.get("doc_ref")
        keyboard.append([InlineKeyboardButton(name, callback_data=f"details_{doc_ref}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ وجدنا هذه النتائج، اختر المطلوب:", reply_markup=reply_markup)

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
            f"🏢 **الاستوديو**: {details["studio"]}\n"
            f"📺 **عدد الحلقات**: {details["episodes_count"]}\n\n"
            f"📖 **القصة**:\n{details["story"]}"
        )
        
        keyboard = [
            [InlineKeyboardButton("📺 مشاهدة الحلقات", callback_data=f"eps_{doc_ref}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if details["poster"]:
            try:
                await query.message.reply_photo(photo=details["poster"], caption=msg, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Failed to send photo: {e}")
                await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="Markdown")

    elif data.startswith("eps_"):
        doc_ref = data.replace("eps_", "")
        episodes = DATA.get_episodes(doc_ref)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
            return

        keyboard = []
        row = []
        for i, ep in enumerate(episodes):
            row.append(InlineKeyboardButton(f"Ep {ep["order"]}", callback_data=f"srv|{doc_ref}|{ep["id"]}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"🎬 **قائمة الحلقات ({len(episodes)})**\nاختر الحلقة للمشاهدة:", reply_markup=reply_markup, parse_mode="Markdown")

    elif data.startswith("srv|"):
        _, doc_ref, ep_id = data.split("|")

        servers = DATA.get_servers(doc_ref, ep_id)
        if not servers:
            await query.message.reply_text("❌ عذراً، لا توجد سيرفرات متاحة لهذه الحلقة.")
            return

        # Prioritize PD links for direct video sending
        pd_link = next((s["url"] for s in servers if "💎 سيرفر PD" in s["name"]), None)

        if pd_link:
            await query.message.reply_text(f"✅ جاري إرسال الفيديو مباشرة...")
            try:
                await query.message.reply_video(video=pd_link, caption=f"🎬 {doc_ref.split("/")[-1]} - الحلقة {ep_id}")
            except Exception as e:
                logging.error(f"Failed to send video: {e}")
                await query.message.reply_text(f"❌ فشل إرسال الفيديو مباشرة. يمكنك تجربة الرابط: {pd_link}")
        else:
            keyboard = []
            for srv in servers:
                keyboard.append([InlineKeyboardButton(srv["name"], url=srv["url"])])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("📺 **اختر سيرفر المشاهدة:**\n(سيرفر PD يدعم المشاهدة المباشرة)", reply_markup=reply_markup, parse_mode="Markdown")

# Add handlers after function definitions
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("api", api_info))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(CallbackQueryHandler(button_click))

@api_app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return JSONResponse(content={"status": "ok"})

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Setting up Telegram webhook...")
    webhook_url = os.environ.get("WEBHOOK_URL") # Ensure this env var is set in Railway/Render
    if webhook_url:
        await application.bot.set_webhook(url=f"{webhook_url}/telegram-webhook")
        logging.info(f"Webhook set to {webhook_url}/telegram-webhook")
    else:
        logging.warning("WEBHOOK_URL environment variable not set. Bot will not receive updates.")
    yield
    logging.info("Shutting down Telegram bot...")
    await application.bot.delete_webhook()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    # This block will only run if bot.py is executed directly, not via uvicorn
    # When deployed with uvicorn, the lifespan event will handle bot startup
    logging.info("Running bot.py directly (for local testing). Starting FastAPI server.")
    uvicorn.run(api_app, host="0.0.0.0", port=8000)
