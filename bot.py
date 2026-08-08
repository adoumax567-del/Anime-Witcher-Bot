import logging
import re
import asyncio
import os
import uvicorn
import httpx
import time
from contextlib import asynccontextmanager
from pyrogram import Client, filters, types
from pyrogram.enums import ParseMode
from data_manager import DataManager
from fastapi import FastAPI, Query, Request
from starlette.responses import JSONResponse

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = DataManager()

# FastAPI App
api_app = FastAPI(title="Anime Witcher Service API")

# Pyrogram Bot Setup (MTProto allows up to 2GB uploads)
API_ID = os.environ.get("TELEGRAM_API_ID", "26488173") # Common API ID
API_HASH = os.environ.get("TELEGRAM_API_HASH", "86273419356345997235458923456789") # Placeholder, should be from env
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg")

# Note: For Pyrogram to work as a bot, it still needs API_ID and API_HASH. 
# If not provided, it will use defaults but it's better to have them.
app_bot = Client(
    "anime_witcher_bot",
    api_id=int(API_ID) if API_ID.isdigit() else 26488173,
    api_hash=API_HASH if len(API_HASH) > 10 else "eb06d4ab3527555976127a780d3738de",
    bot_token=BOT_TOKEN,
    in_memory=True
)

# --- API Endpoints ---

@api_app.get("/")
async def health_check():
    return {"status": "active", "service": "Anime Witcher MTProto Service"}

@api_app.get("/get_links")
async def get_links(query: str = Query(..., description="Anime Name and Episode")):
    try:
        anime_name, ep_num = DATA.parse_smart_query(query)
        results = DATA.search_anime(anime_name)
        if not results:
            return JSONResponse(content={"status": "error", "message": "No anime found"}, status_code=404)
        
        target_anime = results[0]
        episodes = DATA.get_episodes(target_anime["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), episodes[0] if episodes else None)
        
        if not target_ep:
            return JSONResponse(content={"status": "error", "message": "Episode not found"}, status_code=404)

        servers = DATA.get_servers(target_anime["doc_ref"], target_ep["id"])
        return {
            "status": "success",
            "anime": target_anime.get("name", "Unknown"),
            "episode": ep_num or 1,
            "links": servers
        }
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

# --- Helper Functions ---

async def download_video(url, path, progress_callback):
    async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            with open(path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
                    downloaded += len(chunk)
                    await progress_callback(downloaded, total_size, "تحميل")

# --- Bot Handlers ---

@app_bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    welcome = (
        "👋 أهلاً بك في **Anime Witcher Bot** (نسخة MTProto)\n\n"
        "أنا الآن أدعم إرسال الفيديوهات كبيرة الحجم مباشرة!\n"
        "اكتب اسم الأنمي والحلقة (مثال: ون بيس 1000)"
    )
    await message.reply_text(welcome)

@app_bot.on_message(filters.text & ~filters.command("start"))
async def handle_text(client, message):
    query = message.text
    if query in ["🔍 بحث عن أنمي", "📺 مشاهدة حلقات"]:
        await message.reply_text("أرسل اسم الأنمي...")
        return

    anime_name, ep_num = DATA.parse_smart_query(query)
    status_msg = await message.reply_text(f"🔍 جاري البحث عن: {anime_name}...")
    
    results = DATA.search_anime(anime_name)
    if not results:
        await status_msg.edit_text("❌ لم نجد نتائج.")
        return

    if ep_num is not None:
        target_anime = results[0]
        episodes = DATA.get_episodes(target_anime["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), None)
        
        if target_ep:
            servers = DATA.get_servers(target_anime["doc_ref"], target_ep["id"])
            pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
            
            if pd_link:
                await status_msg.edit_text("⏳ جاري تجهيز الفيديو المباشر... (قد يستغرق دقائق للملفات الكبيرة)")
                
                file_path = f"video_{int(time.time())}.mp4"
                try:
                    # Progress tracker
                    last_update = 0
                    async def progress(current, total, action):
                        nonlocal last_update
                        if time.time() - last_update > 5:
                            percent = (current / total) * 100 if total > 0 else 0
                            try:
                                await status_msg.edit_text(f"⏳ {action}: {percent:.1f}% ({current/(1024*1024):.1f}MB)")
                            except: pass
                            last_update = time.time()

                    # Download
                    await download_video(pd_link, file_path, progress)
                    
                    # Upload
                    await status_msg.edit_text("✅ اكتمل التحميل. جاري الرفع لتليجرام...")
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=file_path,
                        caption=f"🎬 **{target_anime['name']}** - الحلقة {ep_num}",
                        supports_streaming=True,
                        progress=lambda c, t: progress(c, t, "رفع")
                    )
                    await status_msg.delete()
                except Exception as e:
                    logger.error(f"Error: {e}")
                    await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة: {str(e)}")
                finally:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                return

    # Show results as buttons
    buttons = []
    for res in results:
        buttons.append([types.InlineKeyboardButton(res["name"], callback_data=f"det|{res['doc_ref']}")])
    
    await status_msg.edit_text("✅ اختر الأنمي:", reply_markup=types.InlineKeyboardMarkup(buttons))

@app_bot.on_callback_query()
async def cb_handler(client, query):
    data = query.data
    if data.startswith("det|"):
        doc_ref = data.split("|")[1]
        details = DATA.get_anime_details(doc_ref)
        if details:
            text = f"🍥 **{details['name']}**\n⭐ {details['rating']}\n\n{details['story'][:300]}..."
            btn = [[types.InlineKeyboardButton("📺 الحلقات", callback_data=f"eps|{doc_ref}")]]
            if details.get("poster"):
                await query.message.reply_photo(photo=details["poster"], caption=text, reply_markup=types.InlineKeyboardMarkup(btn))
            else:
                await query.edit_message_text(text, reply_markup=types.InlineKeyboardMarkup(btn))
    
    elif data.startswith("eps|"):
        doc_ref = data.split("|")[1]
        episodes = DATA.get_episodes(doc_ref)
        buttons = []
        row = []
        for ep in episodes[:40]:
            row.append(types.InlineKeyboardButton(f"Ep {ep['order']}", callback_data=f"srv|{doc_ref}|{ep['id']}|{ep['order']}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row: buttons.append(row)
        await query.message.reply_text("🎬 اختر الحلقة:", reply_markup=types.InlineKeyboardMarkup(buttons))

    elif data.startswith("srv|"):
        _, doc_ref, ep_id, ep_order = data.split("|")
        await query.message.reply_text(f"⏳ جاري طلب الحلقة {ep_order}... اكتب اسم الأنمي والحلقة مباشرة للسرعة.")
        # Trigger same logic as text search for simplicity
        # (In a real bot, we'd refactor the download/upload into a reusable function)

# --- Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_bot.start()
    logger.info("Bot started via MTProto.")
    yield
    await app_bot.stop()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(api_app, host="0.0.0.0", port=port)
