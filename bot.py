import os
import uvicorn
import logging
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from data_manager import DataManager
from fastapi import FastAPI, Query, Request
from starlette.responses import JSONResponse

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = DataManager()
api_app = FastAPI()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg")
application = Application.builder().token(TOKEN).build()

# --- API ---
@api_app.get("/get_links")
async def get_links(query: str = Query(...)):
    name, ep_num = DATA.parse_smart_query(query)
    results = DATA.search_anime(name)
    if not results: return {"status": "error", "message": "Not found"}
    target = results[0]
    episodes = DATA.get_episodes(target["doc_ref"])
    target_ep = next((e for e in episodes if e["order"] == ep_num), episodes[0] if episodes else None)
    if not target_ep: return {"status": "error", "message": "Episode not found"}
    servers = DATA.get_servers(target["doc_ref"], target_ep["id"])
    return {
        "status": "success", 
        "anime": target["name"], 
        "episode": ep_num or 1, 
        "links": [{"name": s["name"], "url": s["app_url"]} for s in servers]
    }

@api_app.post("/telegram-webhook")
async def webhook(request: Request):
    data = await request.json()
    await application.process_update(Update.de_json(data, application.bot))
    return {"status": "ok"}

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🎬 مشاهدة", "🔍 بحث"]]
    await update.message.reply_text(
        "👋 أهلاً بك في بوت Anime Witcher!\nاختر ماذا تريد أن تفعل:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🎬 مشاهدة" or text == "🔍 بحث":
        await update.message.reply_text("📝 من فضلك اكتب اسم الفيلم، الأنمي، أو المسلسل:")
        context.user_data['waiting_for_name'] = True
        return

    if context.user_data.get('waiting_for_name'):
        name, ep_num = DATA.parse_smart_query(text)
        status = await update.message.reply_text(f"🔍 جاري البحث عن: {name}...")
        results = DATA.search_anime(name)
        
        if not results:
            await status.edit_text("❌ لم نجد نتائج. حاول كتابة الاسم بشكل صحيح.")
            return

        # If exactly one result or high confidence
        if len(results) == 1:
            target = results[0]
            await status.delete()
            await show_anime_options(update, target)
        else:
            buttons = [[InlineKeyboardButton(r["name"], callback_data=f"opt|{r['doc_ref']}")] for r in results]
            await status.edit_text("✅ اختر من النتائج التالية:", reply_markup=InlineKeyboardMarkup(buttons))
        
        context.user_data['waiting_for_name'] = False
        return

async def show_anime_options(update: Update, anime):
    text = f"🎬 **{anime['name']}**\n\nماذا تريد أن تفعل؟"
    buttons = [
        [InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"eps|{anime['doc_ref']}")],
        [InlineKeyboardButton("📖 وصف الأنمي", callback_data=f"dsc|{anime['doc_ref']}")]
    ]
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("opt|"):
        doc_ref = data.split("|")[1]
        details = DATA.get_anime_details(doc_ref)
        if details:
            await show_anime_options(update, {"name": details["name"], "doc_ref": doc_ref})

    elif data.startswith("dsc|"):
        doc_ref = data.split("|")[1]
        details = DATA.get_anime_details(doc_ref)
        if details:
            text = f"📖 **وصف {details['name']}**\n\n{details['story']}"
            btn = [[InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"eps|{doc_ref}")]]
            if details.get("poster"):
                await query.message.reply_photo(photo=details["poster"], caption=text[:1000], reply_markup=InlineKeyboardMarkup(btn), parse_mode="Markdown")
            else:
                await query.message.reply_text(text[:4000], reply_markup=InlineKeyboardMarkup(btn), parse_mode="Markdown")

    elif data.startswith("eps|"):
        doc_ref = data.split("|")[1]
        episodes = DATA.get_episodes(doc_ref)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
            return
        
        buttons = []
        row = []
        for ep in episodes[:60]: # Show up to 60 episodes
            row.append(InlineKeyboardButton(f"H {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await query.message.reply_text("🎬 اختر الحلقة للمشاهدة في المتصفح:", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("srv|"):
        _, dr, ei, eo = data.split("|")
        servers = DATA.get_servers(dr, ei)
        if servers:
            # Direct view button
            btn = [[InlineKeyboardButton("🎬 مشاهدة الآن في المتصفح", url=servers[0]["url"])]]
            # Also show other servers if available
            if len(servers) > 1:
                other_btns = [[InlineKeyboardButton(f"🔗 {s['name']}", url=s['url'])] for s in servers[1:5]]
                btn.extend(other_btns)
            
            await query.message.reply_text(f"🎬 حلقة {eo} جاهزة للمشاهدة:", reply_markup=InlineKeyboardMarkup(btn))
        else:
            await query.message.reply_text("❌ عذراً، لم يتم العثور على روابط لهذه الحلقة.")

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(CallbackQueryHandler(cb_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await application.initialize()
    url = os.environ.get("WEBHOOK_URL")
    if url: await application.bot.set_webhook(url=f"{url.rstrip('/')}/telegram-webhook")
    await application.start()
    yield
    await application.stop()
    await application.shutdown()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(api_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
