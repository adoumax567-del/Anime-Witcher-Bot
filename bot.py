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
    "🌟 *مرحباً بك في Anime Witcher Bot!* 🌟\n\n"
    "لقد تم تحديثي لأكون أسرع وأكثر دقة في جلب الأنميات والأفلام مباشرة من التطبيق الأصلي.\n\n"
    "استخدم الأزرار بالأسفل للتحكم الكامل. 👇"
)

HELP_MSG = (
    "🛠️ *دليل الاستخدام السريع*\n\n"
    "ℹ️ `/info [اسم الأنمي]` - جلب القصة والتفاصيل.\n"
    "📺 `/watch [اسم الأنمي]` - جلب الحلقات والروابط.\n"
    "🔍 أرسل اسم الأنمي مباشرة للبحث في كل شيء.\n\n"
    "💡 *ملاحظة:* إذا لم تجد الأنمي بالعربي، جرب كتابة اسمه بالإنجليزية."
)

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
        await update.message.reply_text("🔎 أرسل اسم الأنمي أو الفيلم للبحث:")
    elif text == 'ℹ️ معلومات أنمي':
        await update.message.reply_text("ℹ️ أرسل اسم الأنمي للحصول على قصته وتفاصيله:")
    elif text == '📺 مشاهدة حلقات':
        await update.message.reply_text("📺 أرسل اسم الأنمي لعرض حلقات المشاهدة:")
    elif text == '❓ مساعدة':
        await help_cmd(update, context)
    else:
        await search_logic(update, context, mode="all")

async def search_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="all"):
    query = " ".join(context.args) if context.args else update.message.text
    if query.startswith('/'): return
    
    status_msg = await update.message.reply_text(f"📡 جاري البحث عن *{query}* في قاعدة البيانات...", parse_mode="Markdown")
    results = data_manager.search_anime(query)
    
    if not results:
        await status_msg.edit_text("❌ عذراً، لم نجد نتائج. تأكد من كتابة الاسم بشكل صحيح.")
        return

    keyboard = []
    for anime in results:
        # objectID هو المعرف الفريد من Algolia
        aid = anime.get('objectID')
        prefix = "inf_" if mode == "info" else "wat_"
        if mode == "all": prefix = "det_"
        keyboard.append([InlineKeyboardButton(f"✨ {anime.get('name')}", callback_data=f"{prefix}{aid}")])
    
    await status_msg.edit_text("✅ تم العثور على هذه النتائج:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        # تنسيق: srv_collection_animeid_epid
        _, coll, aid, eid = data.split("_")
        await show_servers(query, aid, eid, coll)

async def show_details(query, anime_id, with_watch_btn):
    details = data_manager.get_anime_details(anime_id)
    if not details:
        await query.message.reply_text("❌ فشل جلب تفاصيل هذا الأنمي.")
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
    
    if details['poster']:
        await query.message.reply_photo(photo=details['poster'], caption=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_episodes_list(query, anime_id):
    # جلب التفاصيل أولاً لمعرفة المجموعة (فيلم أم مسلسل)
    details = data_manager.get_anime_details(anime_id)
    coll = details['collection'] if details else "anime_list"
    
    episodes = data_manager.get_episodes(anime_id, coll)
    if not episodes:
        # إذا كان فيلماً، قد لا توجد حلقات، سنحاول جلب السيرفرات مباشرة للحلقة 0 أو الافتراضية
        await query.message.reply_text("⚠️ لا توجد حلقات (قد يكون فيلماً)، جاري البحث عن رابط المشاهدة المباشر...")
        # في الأفلام، غالباً ما تكون هناك "حلقة" واحدة مخفية أو السيرفرات مربوطة بالفيلم نفسه
        # سنحاول جلب السيرفرات باستخدام anime_id كـ episode_id للأفلام
        await show_servers(query, anime_id, anime_id, coll)
        return

    keyboard = []
    row = []
    for ep in episodes:
        # نرسل اسم المجموعة أيضاً في الـ callback لضمان المسار الصحيح
        row.append(InlineKeyboardButton(f"EP {ep['order']}", callback_data=f"srv_{coll}_{anime_id}_{ep['id']}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    await query.message.reply_text(f"🎬 *قائمة الحلقات:*\nاختر الحلقة للمشاهدة:", 
                                   parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_servers(query, anime_id, ep_id, coll):
    servers = data_manager.get_servers(anime_id, ep_id, coll)
    if not servers:
        await query.message.reply_text("❌ نعتذر، روابط المشاهدة غير متوفرة حالياً لهذا الاختيار.")
        return

    keyboard = []
    for s in servers:
        keyboard.append([InlineKeyboardButton(s['name'], url=s['url'])])
    
    await query.message.reply_text("💎 *سيرفرات المشاهدة المتاحة:*", 
                                   parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("info", lambda u, c: search_logic(u, c, mode="info")))
    app.add_handler(CommandHandler("watch", lambda u, c: search_logic(u, c, mode="watch")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_requests))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("🚀 Anime Witcher Bot is Updated and Ready!")
    app.run_polling()
