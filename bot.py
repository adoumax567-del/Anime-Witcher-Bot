import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from data_manager import DataManager

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
data_manager = DataManager()

# نص رسالة المساعدة
HELP_TEXT = (
    "📖 *دليل استخدام بوت Anime Witcher*\n\n"
    "يمكنك استخدام الأوامر التالية للتحكم في البوت:\n\n"
    "🔍 /start - بدء تشغيل البوت والترحيب.\n"
    "ℹ️ /info [اسم الأنمي] - جلب معلومات الأنمي فقط (القصة، التقييم، إلخ).\n"
    "📺 /watch [اسم الأنمي] - جلب روابط المشاهدة والحلقات مباشرة.\n"
    "❓ /help - عرض هذه الرسالة التعليمية.\n\n"
    "💡 *مثال:* `/info Naruto` أو `/watch One Piece`"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 أهلاً بك في بوت *Anime Witcher* الاحترافي!\n\n"
        "أنا هنا لمساعدتك في العثور على معلومات الأنمي المفضل لديك وروابط مشاهدة الحلقات بأعلى الجودات.\n\n"
        f"{HELP_TEXT}"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def search_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, mode="all"):
    query = " ".join(context.args) if context.args else ""
    
    if not query and update.message.text and not update.message.text.startswith('/'):
        query = update.message.text
    
    if not query:
        await update.message.reply_text("⚠️ يرجى كتابة اسم الأنمي بعد الأمر. مثال: `/watch Naruto`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"⏳ جاري البحث عن '{query}'...")
    results = data_manager.search_anime(query)
    
    if not results:
        await msg.edit_text("❌ لم يتم العثور على نتائج لهذا الاسم.")
        return

    keyboard = []
    for anime in results:
        # تحديد نمط الاستجابة بناءً على المود
        callback_data = f"info_{anime.get('objectID')}" if mode == "info" else f"watch_{anime.get('objectID')}"
        if mode == "all": callback_data = f"details_{anime.get('objectID')}"
        
        keyboard.append([InlineKeyboardButton(anime.get('name'), callback_data=callback_data)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await msg.edit_text("✅ اختر الأنمي المطلوب من القائمة:", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # عرض المعلومات فقط
    if data.startswith("info_"):
        anime_id = data.split("_")[1]
        details = data_manager.get_anime_details(anime_id)
        if details:
            text = format_details_text(details)
            if details['poster']:
                await query.message.reply_photo(photo=details['poster'], caption=text, parse_mode="Markdown")
            else:
                await query.message.reply_text(text, parse_mode="Markdown")

    # عرض الحلقات والمشاهدة فقط
    elif data.startswith("watch_"):
        anime_id = data.split("_")[1]
        await show_episodes(query.message, anime_id)

    # عرض التفاصيل مع زر الحلقات (النمط القديم/الشامل)
    elif data.startswith("details_"):
        anime_id = data.split("_")[1]
        details = data_manager.get_anime_details(anime_id)
        if details:
            text = format_details_text(details)
            keyboard = [[InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"watch_{anime_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if details['poster']:
                await query.message.reply_photo(photo=details['poster'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    elif data.startswith("servers_"):
        _, anime_id, ep_id = data.split("_")
        servers = data_manager.get_servers(anime_id, ep_id)
        if not servers:
            await query.message.reply_text("❌ لا توجد سيرفرات متاحة لهذه الحلقة.")
            return

        keyboard = []
        for s in servers:
            for s_name, s_link in s['links'].items():
                keyboard.append([InlineKeyboardButton(f"🔗 {s_name} - {s['name']}", url=s_link)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🌐 اختر السيرفر للمشاهدة المباشرة:", reply_markup=reply_markup)

def format_details_text(details):
    return (
        f"🍥 *معلومات الأنمي*\n\n"
        f"🎬 *الاسم:* {details['name']}\n"
        f"📖 *القصة:* {details['story'][:700]}...\n\n"
        f"⭐ *التقييم:* {details['rating']}\n"
        f"📅 *سنة العرض:* {details['year']}\n"
        f"🎭 *التصنيف:* {details['genres']}\n"
        f"📺 *عدد الحلقات:* {details['episodes_count']}\n"
        f"🏢 *الاستوديو:* {details['studio']}\n"
    )

async def show_episodes(message, anime_id):
    episodes = data_manager.get_episodes(anime_id)
    if not episodes:
        await message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
        return

    keyboard = []
    row = []
    for i, ep in enumerate(episodes):
        row.append(InlineKeyboardButton(f"الحلقة {ep['order']}", callback_data=f"servers_{anime_id}_{ep['id']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text("📺 اختر الحلقة المطلوبة للمشاهدة:", reply_markup=reply_markup)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    # تعريف الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", lambda u, c: search_logic(u, c, mode="info")))
    app.add_handler(CommandHandler("watch", lambda u, c: search_logic(u, c, mode="watch")))
    
    # التعامل مع الرسائل النصية العادية (بحث شامل)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: search_logic(u, c, mode="all")))
    
    # التعامل مع الأزرار
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🚀 البوت المطور يعمل الآن...")
    app.run_polling()
