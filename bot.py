import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from data_manager import DataManager

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

DATA = DataManager()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"👋 أهلاً بك يا {user.first_name} في **Anime Witcher Bot**!\n\n"
        "أنا بوت احترافي مخصص لمساعدتك في استخراج معلومات وحلقات الأنمي والافلام المفضلة لديك.\n\n"
        "🚀 **ماذا يمكنني أن أفعل؟**\n"
        "1️⃣ جلب معلومات الأنمي كاملة.\n"
        "2️⃣ استخراج روابط المشاهدة المباشرة (سيرفر PD).\n"
        "3️⃣ عرض الحلقات مرتبة ومنظمة.\n\n"
        "👇 استخدم الأزرار بالأسفل للتنقل بسهولة!"
    )
    
    keyboard = [
        ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"],
        ["ℹ️ معلومات أنمي", "❓ مساعدة"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **دليل المساعدة التقني:**\n\n"
        "🔹 **للمشاهدة**: اكتب اسم الأنمي مباشرة أو اضغط على '📺 مشاهدة حلقات'.\n"
        "🔹 **للمعلومات**: اكتب `/info [اسم الأنمي]` أو اضغط على 'ℹ️ معلومات أنمي'.\n"
        "🔹 **للبحث المباشر**: اكتب `/watch [اسم الأنمي]`.\n\n"
        "💡 **نصيحة**: نحن نعتمد سيرفر **PD** كأولوية لأنه الأسرع والأعلى جودة. إذا لم يعمل، جرب السيرفرات البديلة."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔍 بحث عن أنمي" or text == "📺 مشاهدة حلقات" or text == "ℹ️ معلومات أنمي":
        await update.message.reply_text(f"📝 من فضلك أرسل اسم الأنمي الذي تبحث عنه الآن...")
        context.user_data['action'] = text
        return

    if text == "❓ مساعدة":
        await help_command(update, context)
        return

    # تنفيذ البحث
    action = context.user_data.get('action', "🔍 بحث عن أنمي")
    await update.message.reply_text("⏳ جاري البحث في السجلات...")
    
    results = DATA.search_anime(text)
    if not results:
        await update.message.reply_text("❌ عذراً، لم نجد نتائج. تأكد من كتابة الاسم بشكل صحيح.")
        return

    keyboard = []
    for res in results:
        name = res.get('name', 'Unknown')
        oid = res.get('objectID')
        keyboard.append([InlineKeyboardButton(name, callback_data=f"details_{oid}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ وجدنا هذه النتائج، اختر الأنمي المطلوب:", reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("details_"):
        anime_id = data.split("_")[1]
        details = DATA.get_anime_details(anime_id)
        if not details:
            await query.edit_message_text("❌ فشل جلب التفاصيل.")
            return

        msg = (
            f"🍥 **معلومات الأنمي**\n\n"
            f"🎬 **الاسم**: {details['name']}\n"
            f"⭐ **التقييم**: {details['rating']}\n"
            f"📅 **سنة العرض**: {details['year']}\n"
            f"🎭 **التصنيف**: {details['genres']}\n"
            f"🏢 **الاستوديو**: {details['studio']}\n"
            f"📺 **عدد الحلقات**: {details['episodes_count']}\n\n"
            f"📖 **القصة**:\n{details['story']}"
        )
        
        keyboard = [
            [InlineKeyboardButton("📺 مشاهدة الحلقات", callback_data=f"eps_{anime_id}_{details['collection']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if details['poster']:
            await query.message.reply_photo(photo=details['poster'], caption=msg, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("eps_"):
        _, anime_id, coll = data.split("_")
        episodes = DATA.get_episodes(anime_id, coll)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
            return

        keyboard = []
        row = []
        for i, ep in enumerate(episodes):
            row.append(InlineKeyboardButton(f"Episode {ep['order']}", callback_data=f"srv_{anime_id}_{ep['id']}_{coll}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"🎬 **قائمة الحلقات ({len(episodes)})**\nاختر الحلقة للمشاهدة:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("srv_"):
        _, anime_id, ep_id, coll = data.split("_")
        servers = DATA.get_servers(anime_id, ep_id, coll)
        if not servers:
            await query.message.reply_text("❌ عذراً، لا توجد سيرفرات متاحة لهذه الحلقة.")
            return

        keyboard = []
        for srv in servers:
            keyboard.append([InlineKeyboardButton(srv['name'], url=srv['url'])])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("📺 **اختر سيرفر المشاهدة:**\n(سيرفر PD في الأعلى دائماً)", reply_markup=reply_markup, parse_mode='Markdown')

def main():
    token = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", handle_message))
    app.add_handler(CommandHandler("watch", handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
