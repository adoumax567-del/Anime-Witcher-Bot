import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from data_manager import DataManager

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
data_manager = DataManager()

# --- رسائل منسقة ---
START_MSG = (
    "🌟 *مرحباً بك في عالم الأنمي!* 🌟\n\n"
    "أنا بوت *Anime Witcher*، دليلك الشامل لمشاهدة ومعرفة كل ما يخص الأنمي والكرتون.\n\n"
    "استخدم الأزرار بالأسفل أو الأوامر لاستكشاف مكتبتنا الضخمة. 🍿"
)

HELP_MSG = (
    "🛠️ *دليل المساعدة التقني*\n\n"
    "للحصول على أفضل تجربة، استخدم الأوامر التالية:\n\n"
    "ℹ️ `/info` - للحصول على قصة ومعلومات الأنمي.\n"
    "📺 `/watch` - للذهاب مباشرة إلى قائمة الحلقات.\n"
    "🔍 أرسل اسم الأنمي مباشرة للبحث الشامل.\n\n"
    "✨ *نصيحة:* اكتب اسم الأنمي بالإنجليزية لنتائج أدق!"
)

# --- لوحة مفاتيح الأوامر الرئيسية ---
main_keyboard = ReplyKeyboardMarkup([
    ['🔍 بحث شامل', 'ℹ️ معلومات أنمي'],
    ['📺 مشاهدة حلقات', '❓ مساعدة']
], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_MSG, parse_mode="Markdown", reply_markup=main_keyboard)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_MSG, parse_mode="Markdown")

async def handle_text_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '🔍 بحث شامل':
        await update.message.reply_text("🔎 أرسل اسم الأنمي للبحث الشامل:")
    elif text == 'ℹ️ معلومات أنمي':
        await update.message.reply_text("ℹ️ أرسل اسم الأنمي للحصول على المعلومات:")
    elif text == '📺 مشاهدة حلقات':
        await update.message.reply_text("📺 أرسل اسم الأنمي لعرض الحلقات:")
    elif text == '❓ مساعدة':
        await help_cmd(update, context)
    else:
        # إذا كان النص ليس أمراً من الكيبورد، نعتبره بحثاً
        await search_logic(update, context, mode="all")

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_logic(update, context, mode="info")

async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await search_logic(update, context, mode="watch")

async def search_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="all"):
    query = " ".join(context.args) if context.args else update.message.text
    if query.startswith('/'): return # تجنب تكرار الأوامر
    
    status_msg = await update.message.reply_text(f"🚀 جاري التنقيب عن *{query}* في الأرشيف...", parse_mode="Markdown")
    results = data_manager.search_anime(query)
    
    if not results:
        await status_msg.edit_text("❌ عذراً، لم نجد هذا الأنمي في سجلاتنا.")
        return

    keyboard = []
    for anime in results:
        prefix = "inf_" if mode == "info" else "wat_"
        if mode == "all": prefix = "det_"
        keyboard.append([InlineKeyboardButton(f"✨ {anime.get('name')}", callback_data=f"{prefix}{anime.get('objectID')}")])
    
    await status_msg.edit_text("✅ اختر النتائج الأقرب لطلبك:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("inf_"):
        anime_id = data.replace("inf_", "")
        await show_details(query, anime_id, with_watch_btn=False)
    
    elif data.startswith("wat_"):
        anime_id = data.replace("wat_", "")
        await show_episodes_list(query, anime_id)
    
    elif data.startswith("det_"):
        anime_id = data.replace("det_", "")
        await show_details(query, anime_id, with_watch_btn=True)

    elif data.startswith("srv_"):
        _, anime_id, ep_id = data.split("_")
        await show_servers(query, anime_id, ep_id)

async def show_details(query, anime_id, with_watch_btn):
    details = data_manager.get_anime_details(anime_id)
    if not details:
        await query.message.reply_text("❌ فشل جلب التفاصيل.")
        return

    text = (
        f"🍥 *{details['name']}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"📖 *القصة:* {details['story'][:800]}...\n\n"
        f"⭐ *التقييم:* `{details['rating']}`\n"
        f"📅 *الإصدار:* `{details['year']}`\n"
        f"🎭 *التصنيف:* {details['genres']}\n"
        f"📺 *الحلقات:* `{details['episodes_count']}`\n"
        f"🏢 *الاستوديو:* {details['studio']}\n"
        f"━━━━━━━━━━━━━━"
    )
    
    keyboard = []
    if with_watch_btn:
        keyboard.append([InlineKeyboardButton("📺 مشاهدة الحلقات", callback_data=f"wat_{anime_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    if details['poster']:
        await query.message.reply_photo(photo=details['poster'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def show_episodes_list(query, anime_id):
    episodes = data_manager.get_episodes(anime_id)
    if not episodes:
        await query.message.reply_text("⚠️ لا توجد حلقات متوفرة لهذا الأنمي حالياً.")
        return

    keyboard = []
    row = []
    for ep in episodes:
        row.append(InlineKeyboardButton(f"EP {ep['order']}", callback_data=f"srv_{anime_id}_{ep['id']}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    await query.message.reply_text(f"🎬 *قائمة الحلقات المتاحة:*\nاختر الحلقة التي ترغب بمشاهدتها:", 
                                   parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_servers(query, anime_id, ep_id):
    servers = data_manager.get_servers(anime_id, ep_id)
    if not servers:
        await query.message.reply_text("❌ نعتذر، روابط هذه الحلقة غير متوفرة حالياً.")
        return

    keyboard = []
    for s in servers:
        keyboard.append([InlineKeyboardButton(s['name'], url=s['url'])])
    
    await query.message.reply_text("💎 *سيرفرات المشاهدة المتاحة:*\nاختر السيرفر والجودة المناسبة لك:", 
                                   parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_requests))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    print("🔥 Anime Witcher Bot is LIVE and Professional!")
    app.run_polling()
