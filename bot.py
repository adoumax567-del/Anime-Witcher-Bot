import os
import uvicorn
import logging
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    return {"status": "success", "anime": target["name"], "episode": ep_num or 1, "links": servers}

@api_app.post("/telegram-webhook")
async def webhook(request: Request):
    data = await request.json()
    await application.process_update(Update.de_json(data, application.bot))
    return {"status": "ok"}

# --- BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً بك! اكتب اسم الأنمي والحلقة للمشاهدة في المتصفح.\nمثال: `سالي 1` أو `ون بيس 1000`")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    name, ep_num = DATA.parse_smart_query(query)
    status = await update.message.reply_text(f"🔍 جاري البحث عن: {name}...")
    results = DATA.search_anime(name)
    if not results:
        await status.edit_text("❌ لم نجد نتائج.")
        return

    if ep_num:
        target = results[0]
        episodes = DATA.get_episodes(target["doc_ref"])
        target_ep = next((e for e in episodes if e["order"] == ep_num), None)
        if target_ep:
            servers = DATA.get_servers(target["doc_ref"], target_ep["id"])
            if servers:
                btn = [[InlineKeyboardButton("🎬 مشاهدة في المتصفح الآن", url=servers[0]["url"])]]
                await status.delete()
                await update.message.reply_text(f"🎬 **{target['name']}** - الحلقة {ep_num}\n\nاضغط للمشاهدة فوراً:", reply_markup=InlineKeyboardMarkup(btn), parse_mode="Markdown")
                return

    buttons = [[InlineKeyboardButton(r["name"], callback_data=f"eps|{r['doc_ref']}")] for r in results]
    await status.edit_text("✅ اختر الأنمي المطلوب:", reply_markup=InlineKeyboardMarkup(buttons))

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("eps|"):
        doc_ref = data.split("|")[1]
        episodes = DATA.get_episodes(doc_ref)
        buttons = []
        row = []
        for ep in episodes[:40]:
            row.append(InlineKeyboardButton(f"H {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4: buttons.append(row); row = []
        if row: buttons.append(row)
        await query.message.reply_text("🎬 اختر الحلقة للمشاهدة في المتصفح:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("srv|"):
        _, dr, ei, eo = data.split("|")
        servers = DATA.get_servers(dr, ei)
        if servers:
            btn = [[InlineKeyboardButton(f"🎬 {s['name']}", url=s['url'])] for s in servers[:5]]
            await query.message.reply_text(f"🎬 روابط مشاهدة الحلقة {eo}:", reply_markup=InlineKeyboardMarkup(btn))

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
