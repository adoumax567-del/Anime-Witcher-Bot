import os
import uvicorn
import logging
import asyncio
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
@api_app.get("/")
async def root():
    return {"status": "online", "message": "Anime Witcher API is running"}

@api_app.get("/get_links")
async def get_links(query: str = Query(...)):
    try:
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
    except Exception as e:
        return {"status": "error", "message": str(e)}

@api_app.post("/telegram-webhook")
async def webhook(request: Request):
    data = await request.json()
    await application.process_update(Update.de_json(data, application.bot))
    return {"status": "ok"}

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🎬 مشاهدة", "🔍 بحث"]]
    await update.message.reply_text(
        "🌟 **مرحباً بك في Anime Witcher Pro** 🌟\n\n"
        "أنا دليلك الشامل لمشاهدة الأنمي، الأفلام، والمسلسلات بأعلى جودة وبكل سهولة.\n\n"
        "🚀 **ماذا يمكنني أن أفعل؟**\n"
        "• البحث بالعربي أو الإنجليزي.\n"
        "• عرض معلومات تفصيلية وشاملة.\n"
        "• روابط مشاهدة مباشرة وسريعة.\n\n"
        "👇 **اختر من القائمة أدناه للبدء:**",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "🎬 مشاهدة" or text == "🔍 بحث":
        await update.message.reply_text("🔎 **من فضلك اكتب اسم العمل الذي تبحث عنه:**\n(مثال: ناروتو، One Piece، سالي)")
        context.user_data['waiting_for_name'] = True
        return

    if context.user_data.get('waiting_for_name'):
        name, ep_num = DATA.parse_smart_query(text)
        status = await update.message.reply_text(f"📡 **جاري الفحص والبحث عن:** `{name}`...", parse_mode="Markdown")
        results = DATA.search_anime(name)
        
        if not results:
            await status.edit_text("❌ **عذراً، لم أتمكن من العثور على نتائج.**\nتأكد من كتابة الاسم بشكل صحيح أو جرب لغة أخرى.")
            return

        if len(results) == 1:
            await show_anime_options(update, results[0])
        else:
            buttons = [[InlineKeyboardButton(f"📁 {r['name']}", callback_data=f"opt|{r['doc_ref']}")] for r in results]
            await update.message.reply_text("✨ **إليك أفضل النتائج المتوفرة:**", reply_markup=InlineKeyboardMarkup(buttons))
        
        context.user_data['waiting_for_name'] = False
        return

async def show_anime_options(update: Update, anime):
    details = DATA.get_anime_details(anime['doc_ref'])
    if not details:
        details = {"name": anime['name'], "story": "لا يوجد وصف متوفر.", "rating": "N/A", "status": "غير معروف", "num_episodes": "غير محدد", "year": "غير معروف", "type": "أنمي", "genres": "غير محدد", "season": "غير محدد", "studio": "غير معروف"}

    text = (
        f"🔥 **{details['name']}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⭐ **التقييم:** `{details['rating']}`\n"
        f"📅 **السنة:** `{details['year']}`\n"
        f"📺 **النوع:** `{details['type']}`\n"
        f"🔄 **الحالة:** `{details['status']}`\n"
        f"🔢 **الحلقات:** `{details['num_episodes']}`\n"
        f"🎭 **التصنيف:** `{details['genres']}`\n"
        f"🌸 **الموسم:** `{details['season']}`\n"
        f"🏢 **الاستوديو:** `{details['studio']}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📖 **القصة:**\n_{details['story'][:600]}..._\n"
        f"━━━━━━━━━━━━━━━"
    )
    
    buttons = [
        [InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"eps|{anime['doc_ref']}|0")],
        [InlineKeyboardButton("🔍 بحث جديد", callback_data="new_search")]
    ]
    
    try:
        if details.get("poster"):
            if update.callback_query:
                await update.callback_query.message.reply_photo(photo=details["poster"], caption=text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            else:
                await update.message.reply_photo(photo=details["poster"], caption=text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            else:
                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error showing options: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "new_search":
        await query.message.reply_text("🔎 **اكتب اسم العمل الجديد:**")
        context.user_data['waiting_for_name'] = True

    elif data.startswith("opt|"):
        doc_ref = data.split("|")[1]
        await show_anime_options(update, {"doc_ref": doc_ref})

    elif data.startswith("eps|"):
        parts = data.split("|")
        doc_ref = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0
        limit = 100
        
        episodes = DATA.get_episodes(doc_ref)
        if not episodes:
            await query.message.reply_text("❌ **عذراً، لا توجد حلقات متاحة حالياً.**")
            return
        
        # Slice episodes based on offset and limit
        current_batch = episodes[offset : offset + limit]
        
        buttons = []
        row = []
        for ep in current_batch:
            row.append(InlineKeyboardButton(f"E{ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        
        # Add pagination buttons
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"eps|{doc_ref}|{max(0, offset - limit)}"))
        if offset + limit < len(episodes):
            nav_buttons.append(InlineKeyboardButton("المزيد من الحلقات ➡️", callback_data=f"eps|{doc_ref}|{offset + limit}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        text = f"🎬 **قائمة الحلقات ({offset + 1} - {min(offset + limit, len(episodes))} من {len(episodes)}):**"
        
        if offset == 0 and not update.callback_query.message.photo:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            # Edit existing message to avoid spam if it's a text message, or send new if photo
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
            except:
                await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    elif data.startswith("srv|"):
        _, dr, ei, eo = data.split("|")
        servers = DATA.get_servers(dr, ei)
        if servers:
            btn = [[InlineKeyboardButton("🚀 مشاهدة فورية (المتصفح)", url=servers[0]["url"])]]
            if len(servers) > 1:
                other_btns = [[InlineKeyboardButton(f"🔗 {s['name']}", url=s['url'])] for s in servers[1:4]]
                btn.extend(other_btns)
            
            await query.message.reply_text(
                f"✅ **الحلقة {eo} جاهزة للمشاهدة!**\n\nاضغط على الزر أدناه للانتقال للمشغل المباشر:",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("❌ **عذراً، لم نتمكن من جلب روابط لهذه الحلقة.**")

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
