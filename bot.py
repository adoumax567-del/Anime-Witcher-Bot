import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from data_manager import DataManager

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
data_manager = DataManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً بك في بوت Anime Witcher!\n\n🔍 أرسل اسم الأنمي الذي تبحث عنه وسأجلب لك كافة التفاصيل والحلقات.")

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    await update.message.reply_text(f"⏳ جاري البحث عن '{query}'...")
    results = data_manager.search_anime(query)
    
    if not results:
        await update.message.reply_text("❌ لم يتم العثور على نتائج.")
        return

    keyboard = []
    for anime in results:
        keyboard.append([InlineKeyboardButton(anime.get('name'), callback_data=f"details_{anime.get('objectID')}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ نتائج البحث:", reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("details_"):
        anime_id = data.split("_")[1]
        details = data_manager.get_anime_details(anime_id)
        if details:
            text = (
                f"🍥 *معلومات الأنمي*\n\n"
                f"🎬 *الاسم:* {details['name']}\n"
                f"📖 *القصة:* {details['story'][:500]}...\n"
                f"⭐ *التقييم:* {details['rating']}\n"
                f"📅 *سنة العرض:* {details['year']}\n"
                f"🎭 *التصنيف:* {details['genres']}\n"
                f"📺 *عدد الحلقات:* {details['episodes_count']}\n"
                f"🏢 *الاستوديو:* {details['studio']}\n"
            )
            keyboard = [[InlineKeyboardButton("📺 عرض الحلقات", callback_data=f"episodes_{anime_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if details['poster']:
                await query.message.reply_photo(photo=details['poster'], caption=text, parse_mode="Markdown", reply_markup=reply_markup)
            else:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    elif data.startswith("episodes_"):
        anime_id = data.split("_")[1]
        episodes = data_manager.get_episodes(anime_id)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة.")
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
        await query.message.reply_text("📺 اختر الحلقة:", reply_markup=reply_markup)

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
        await query.message.reply_text("🌐 اختر السيرفر للمشاهدة:", reply_markup=reply_markup)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("🚀 البوت يعمل الآن...")
    app.run_polling()
