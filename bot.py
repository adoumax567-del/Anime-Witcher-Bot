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
    keyboard = [
        ["🎬 استكشاف المحتوى", "🔍 البحث المتقدم"],
        ["👤 بحث عن شخصية", "❓ مركز المساعدة"]
    ]
    welcome_text = (
        "💠 **منصة Anime Witcher Pro v2.0** 💠\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "مرحباً بك في الوجهة الأولى لعشاق الأنمي والسينما العالمية. نقدم لك تجربة مشاهدة استثنائية تعتمد على السرعة، الدقة، والاحترافية.\n\n"
        "⚡ **مميزات المنصة:**\n"
        "└ البحث الذكي باللغتين العربية والإنجليزية.\n"
        "└ مكتبة ضخمة من الأفلام والمسلسلات.\n"
        "└ مشغل سحابي مباشر فائق السرعة.\n\n"
        "🛡️ **نحن هنا لخدمتك، يرجى اختيار وجهتك:**"
    )
    await update.message.reply_text(
        welcome_text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def show_help(update: Update):
    help_text = (
        "📖 **دليل الاستخدام والخدمات**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 **كيفية البحث:**\n"
        "استخدم أزرار البحث واكتب اسم العمل. نظامنا يدعم التصحيح التلقائي للأخطاء الإملائية.\n\n"
        "📺 **المشاهدة المباشرة:**\n"
        "عند اختيار الحلقة، سيتم توفير رابط مشغل سحابي آمن يفتح في متصفحك فوراً دون الحاجة للتحميل.\n\n"
        "📁 **الأرشيف الضخم:**\n"
        "في حال الأعمال الطويلة، يمكنك التنقل بين مجموعات الحلقات بسلاسة تامة.\n\n"
        "🆘 **هل تحتاج لمساعدة إضافية؟**\n"
        "يمكنك دائماً العودة للقائمة الرئيسية للبدء من جديد."
    )
    buttons = [[InlineKeyboardButton("🏠 العودة للمنصة الرئيسية", callback_data="go_home")]]
    await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text in ["🎬 استكشاف المحتوى", "🔍 البحث المتقدم", "👤 بحث عن شخصية"]:
        context.user_data['search_mode'] = "character" if text == "👤 بحث عن شخصية" else "anime"
        if text == "👤 بحث عن شخصية":
            prompt = "📥 اكتب اسم الشخصية التي تريد البحث عنها.\nمثال: Naruto Uzumaki أو Conan Edogawa أو Itachi Uchiha"
        else:
            prompt = "📥 اكتب اسم الفيلم أو مسلسل الأنمي كاملاً.\nمثال: One Piece أو Naruto Shippuden أو Detective Conan"
        await update.message.reply_text(prompt)
        context.user_data['waiting_for_name'] = True
        return

    if text == "❓ مركز المساعدة":
        await show_help(update)
        return

    if context.user_data.get('waiting_for_name'):
        name, ep_num = DATA.parse_smart_query(text)
        if context.user_data.get('search_mode') == "character":
            await search_character_flow(update, context, name)
            context.user_data['waiting_for_name'] = False
            return
        status = await update.message.reply_text(f"📡 **جاري الاتصال بقاعدة البيانات...**\nتحليل الطلب: `{name}`", parse_mode="Markdown")
        
        try:
            results = await asyncio.wait_for(asyncio.to_thread(DATA.search_anime, name), timeout=25)
            
            if not results:
                await status.edit_text(
                    "⚠️ **تنبيه: لم يتم العثور على نتائج مطابقة.**\n\n"
                    "يرجى مراجعة الاسم أو تجربة كلمات بحث مختلفة لضمان أفضل وصول للمحتوى.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
                )
                return

            if len(results) == 1:
                await show_anime_options(update, results[0])
            else:
                buttons = [[InlineKeyboardButton(f"📂 {r['name']}", callback_data=f"opt|{r['doc_ref']}")] for r in results]
                buttons.append([InlineKeyboardButton("🏠 العودة للرئيسية", callback_data="go_home")])
                await update.message.reply_text("📋 **نتائج البحث المطابقة لطلبك:**", reply_markup=InlineKeyboardMarkup(buttons))
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            await status.edit_text(
                "🚫 **خطأ في النظام: تعذر إتمام عملية البحث حالياً.**\n"
                "يرجى المحاولة مرة أخرى خلال لحظات.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
            )
        
        context.user_data['waiting_for_name'] = False
        return

async def search_character_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    status = await update.message.reply_text(
        f"📡 جاري البحث عن الشخصية: {name}\nقد تستغرق العملية لحظات قليلة..."
    )
    try:
        matches = await asyncio.wait_for(asyncio.to_thread(DATA.search_characters, name), timeout=25)
        if not matches:
            await status.edit_text(
                "لم أعثر على شخصية مطابقة لهذا البحث.\n\nجرّب الاسم بالإنجليزية أو اكتب اسماً كاملاً، مثل Naruto Uzumaki أو Conan Edogawa.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
            )
            return
        if len(matches) == 1:
            await status.delete()
            await show_character(update, matches[0])
            return
        buttons = [[InlineKeyboardButton(f"👤 {item['name']}", callback_data=f"char|{item['id']}")] for item in matches]
        buttons.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")])
        await status.edit_text("اختر الشخصية المطلوبة من النتائج التالية:", reply_markup=InlineKeyboardMarkup(buttons))
        context.user_data['character_matches'] = {str(item['id']): item for item in matches}
    except asyncio.TimeoutError:
        logger.error("Character search timed out for query=%r", name)
        await status.edit_text("⏱️ استغرق البحث وقتاً أطول من المتوقع. جرّب الاسم الكامل أو أعد المحاولة بعد قليل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]]))
    except Exception:
        logger.exception("Character search error")
        await status.edit_text("تعذر إتمام بحث الشخصيات حالياً. يرجى المحاولة بعد قليل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]]))

async def show_character(update: Update, character):
    try:
        details = await asyncio.wait_for(asyncio.to_thread(DATA.get_character_details, character), timeout=8)
    except asyncio.TimeoutError:
        details = DATA.get_character_details({**character, "description": character.get("description") or "", "works": character.get("works") or []})
    title = details["name"]
    if details.get("name_en") and details["name_en"] != title:
        title = f"{title} | {details['name_en']}"
    works = details.get("works") or []
    works_text = "\n".join(f"• {work.get('title') or work.get('name') or work}" if isinstance(work, dict) else f"• {work}" for work in works)
    text = (
        f"👤 ملف الشخصية\n━━━━━━━━━━━━━━━━━━\n"
        f"الاسم: {title}\n\n"
        f"نبذة:\n{details['description'][:2200]}\n\n"
        f"الأعمال المرتبطة:\n{works_text or 'لا تتوفر قائمة الأعمال حالياً.'}\n━━━━━━━━━━━━━━━━━━"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
    target = update.callback_query.message if update.callback_query else update.message
    if details.get("poster"):
        try:
            # Keep caption short so Telegram accepts the image, then send the
            # complete profile as the following message.
            await target.reply_photo(photo=details["poster"], caption=f"👤 ملف الشخصية\n\n{title}")
            await target.reply_text(text, reply_markup=markup)
            return
        except Exception:
            logger.warning("Character poster could not be sent", exc_info=True)
    await target.reply_text(text, reply_markup=markup)

async def show_anime_options(update: Update, anime):
    details = DATA.get_anime_details(anime['doc_ref'])
    if not details:
        await update.message.reply_text(
            "⚠️ عذراً، حدث خطأ أثناء استرداد بيانات العمل.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
        )
        return

    rating = details['rating']
    if isinstance(rating, dict):
        rating = rating.get('rate') or rating.get('value') or 'غير متوفر'
    genres = details['genres']
    if isinstance(genres, (list, tuple)):
        genres = '، '.join(map(str, genres))
    studio = details['studio']
    if isinstance(studio, (list, tuple)):
        studio = '، '.join(map(str, studio))
    text = (
        f"🎬 معلومات العمل: {details['name']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 التقييم العام: {rating}\n"
        f"📅 سنة الإصدار: {details['year']}\n"
        f"🎭 التصنيف: {genres}\n"
        f"🎬 الاستوديو: {studio}\n"
        f"🔄 الحالة: {details['status']}\n"
        f"🔢 إجمالي الحلقات: {details['num_episodes']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 ملخص القصة:\n{str(details['story'])[:600]}...\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    caption = text[:1000] if len(text) > 1000 else text
    
    buttons = [
        [InlineKeyboardButton("📺 استعراض قائمة الحلقات", callback_data=f"eps|{anime['doc_ref']}|0")],
        [InlineKeyboardButton("🔍 بحث جديد", callback_data="new_search"), InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]
    ]
    
    try:
        if details.get("poster"):
            if update.callback_query:
                await update.callback_query.message.reply_photo(photo=details["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await update.message.reply_photo(photo=details["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"Error showing options: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "go_home":
        keyboard = [["🎬 استكشاف المحتوى", "🔍 البحث المتقدم"], ["👤 بحث عن شخصية", "❓ مركز المساعدة"]]
        await query.message.reply_text(
            "🏠 **تمت العودة إلى المنصة الرئيسية.**\nيرجى اختيار الإجراء المطلوب من القائمة أدناه:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="Markdown"
        )

    elif data == "new_search":
        await query.message.reply_text("📥 **يرجى إدخال عنوان العمل الجديد:**")
        context.user_data['waiting_for_name'] = True

    elif data.startswith("char|"):
        item_id = data.split("|", 1)[1]
        character = context.user_data.get('character_matches', {}).get(item_id)
        if character:
            await show_character(update, character)
        else:
            await query.message.reply_text("انتهت صلاحية نتيجة البحث. ابدأ بحثاً جديداً من القائمة الرئيسية.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]]))

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
            await query.message.reply_text(
                "📁 **المحتوى متوفر، ولكن قائمة الحلقات قيد التحديث.**\nيرجى المحاولة لاحقاً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
            )
            return
        
        current_batch = episodes[offset : offset + limit]
        
        buttons = []
        row = []
        for ep in current_batch:
            row.append(InlineKeyboardButton(f"EP {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ المجموعة السابقة", callback_data=f"eps|{doc_ref}|{max(0, offset - limit)}"))
        if offset + limit < len(episodes):
            nav_buttons.append(InlineKeyboardButton("المجموعة التالية ➡️", callback_data=f"eps|{doc_ref}|{offset + limit}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")])
        
        text = f"🎬 **فهرس الحلقات ({offset + 1} - {min(offset + limit, len(episodes))} من {len(episodes)}):**"
        
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        except:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("srv|"):
        _, dr, ei, eo = data.split("|")
        servers = DATA.get_servers(dr, ei)
        if servers:
            btn = [[InlineKeyboardButton("🎬 تشغيل عبر المشغل السحابي", url=servers[0]["url"])]]
            if len(servers) > 1:
                other_btns = [[InlineKeyboardButton(f"🔗 {s['name']}", url=s['url'])] for s in servers[1:4]]
                btn.extend(other_btns)
            
            btn.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")])
            
            success_text = (
                f"✅ **تم تجهيز الحلقة رقم {eo} بنجاح!**\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "يرجى النقر على الزر أدناه لبدء المشاهدة الفورية عبر متصفحك الآمن."
            )
            
            await query.message.reply_text(
                success_text,
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(
                "❌ **عذراً، تعذر استرداد روابط التشغيل لهذه الحلقة حالياً.**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="go_home")]])
            )

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
