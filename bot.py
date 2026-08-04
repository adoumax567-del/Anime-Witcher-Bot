import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from data_manager import DataManager

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

DATA = DataManager()

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
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **دليل الخدمة السريعة:**\n\n"
        "🔹 **طلب مباشر**: اكتب `[الاسم] [رقم الحلقة]` وسأجلب لك الروابط فوراً.\n"
        "🔹 **البحث**: اكتب اسم الأنمي فقط لعرض النتائج المتاحة.\n"
        "🔹 **سيرفر PD**: هو الأولوية لدينا لدعمه المشاهدة المباشرة داخل تليجرام.\n"
        "🔹 **خدمة الـ API**: متوفرة للمطورين لجلب روابط PD فقط بتنسيق JSON.\n\n"
        "💡 **مثال**: `ون بيس 1000`"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
    await update.message.reply_text(api_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات", "ℹ️ معلومات أنمي"]:
        await update.message.reply_text(f"📝 من فضلك أرسل اسم الأنمي الذي تبحث عنه...")
        context.user_data['action'] = text
        return

    if text == "❓ مساعدة":
        await help_command(update, context)
        return

    # Smart Parsing
    anime_name, ep_num = DATA.parse_smart_query(text)
    
    await update.message.reply_text(f"⏳ جاري البحث عن '{anime_name}'...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await update.message.reply_text("❌ عذراً، لم نجد نتائج. تأكد من كتابة الاسم بشكل صحيح.")
        return

    if ep_num is not None:
        # Service Mode: Directly get links for specific episode
        target_anime = results[0]
        doc_ref = target_anime['doc_ref']
        episodes = DATA.get_episodes(doc_ref)
        
        target_ep = None
        for ep in episodes:
            if ep['order'] == ep_num:
                target_ep = ep
                break
        
        if target_ep:
            servers = DATA.get_servers(doc_ref, target_ep['id'])
            if servers:
                keyboard = []
                for srv in servers:
                    keyboard.append([InlineKeyboardButton(srv['name'], url=srv['url'])])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"✅ **{target_anime['name']} - الحلقة {ep_num}**\n"
                    "تفضل روابط المشاهدة المباشرة:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
            else:
                await update.message.reply_text(f"❌ لم نجد سيرفرات متاحة للحلقة {ep_num} من {target_anime['name']}.")
        else:
            await update.message.reply_text(f"❌ لم نجد الحلقة {ep_num} في قائمة حلقات {target_anime['name']}.")

    # Standard Mode: Show results
    keyboard = []
    for res in results:
        name = res.get('name', 'Unknown')
        doc_ref = res.get('doc_ref')
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
            f"🎬 **الاسم**: {details['name']}\n"
            f"⭐ **التقييم**: {details['rating']}\n"
            f"📅 **سنة العرض**: {details['year']}\n"
            f"🎭 **التصنيف**: {details['genres']}\n"
            f"🏢 **الاستوديو**: {details['studio']}\n"
            f"📺 **عدد الحلقات**: {details['episodes_count']}\n\n"
            f"📖 **القصة**:\n{details['story']}"
        )
        
        keyboard = [
            [InlineKeyboardButton("📺 مشاهدة الحلقات", callback_data=f"eps_{doc_ref}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if details['poster']:
            try:
                await query.message.reply_photo(photo=details['poster'], caption=msg, reply_markup=reply_markup, parse_mode='Markdown')
            except:
                await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("eps_"):
        doc_ref = data.replace("eps_", "")
        episodes = DATA.get_episodes(doc_ref)
        if not episodes:
            await query.message.reply_text("❌ لا توجد حلقات متاحة حالياً.")
            return

        keyboard = []
        row = []
        for i, ep in enumerate(episodes):
            row.append(InlineKeyboardButton(f"Ep {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"🎬 **قائمة الحلقات ({len(episodes)})**\nاختر الحلقة للمشاهدة:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith("srv|"):
        _, doc_ref, ep_id = data.split("|")

        servers = DATA.get_servers(doc_ref, ep_id)
        if not servers:
            await query.message.reply_text("❌ عذراً، لا توجد سيرفرات متاحة لهذه الحلقة.")
            return

        keyboard = []
        for srv in servers:
            keyboard.append([InlineKeyboardButton(srv['name'], url=srv['url'])])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("📺 **اختر سيرفر المشاهدة:**\n(سيرفر PD يدعم المشاهدة المباشرة)", reply_markup=reply_markup, parse_mode='Markdown')

def main():
    token = "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg"
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("api", api_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
