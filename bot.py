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
from fastapi import FastAPI, Query, Request, BackgroundTasks
from starlette.responses import JSONResponse

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATA = DataManager()

# FastAPI App
api_app = FastAPI(title="Anime Witcher MTProto Service")

# Pyrogram Bot Setup (MTProto allows up to 2GB uploads)
# Using official Telegram Desktop credentials as reliable defaults
API_ID = os.environ.get("TELEGRAM_API_ID", "2040") 
API_HASH = os.environ.get("TELEGRAM_API_HASH", "b18441a1ff607e10c989891a5462e627")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7570728074:AAEOACQzg60gq7QxeGoubYT1URNxigfijjg")

# Initialize Pyrogram Client
# We use in_memory=True to avoid database lock issues on ephemeral file systems like Render
bot = Client(
    "anime_witcher_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
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

# --- Video Processing Logic ---

async def process_and_send_video(chat_id, video_url, caption, status_msg_id):
    """Downloads and uploads video in a way that bypasses Bot API limits."""
    file_path = f"video_{int(time.time())}.mp4"
    try:
        # 1. Download with progress
        last_update = 0
        async def progress(current, total, action):
            nonlocal last_update
            if time.time() - last_update > 5:
                percent = (current / total) * 100 if total > 0 else 0
                try:
                    await bot.edit_message_text(
                        chat_id, status_msg_id, 
                        f"⏳ {action}: {percent:.1f}% ({current/(1024*1024):.1f}MB)"
                    )
                except: pass
                last_update = time.time()

        async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
            async with client.stream("GET", video_url) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                with open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
                        downloaded += len(chunk)
                        await progress(downloaded, total_size, "تحميل")

        # 2. Upload with native player support
        await bot.edit_message_text(chat_id, status_msg_id, "✅ اكتمل التحميل. جاري الرفع لتليجرام...")
        await bot.send_video(
            chat_id=chat_id,
            video=file_path,
            caption=caption,
            supports_streaming=True,
            progress=lambda c, t: progress(c, t, "رفع")
        )
        await bot.delete_messages(chat_id, status_msg_id)
        
    except Exception as e:
        logger.error(f"Processing Error: {e}")
        try:
            await bot.edit_message_text(chat_id, status_msg_id, f"❌ حدث خطأ: {str(e)}")
        except: pass
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# --- Bot Handlers ---

@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "👋 أهلاً بك في **Anime Witcher Bot**!\n\n"
        "أنا الآن أدعم إرسال الفيديوهات كبيرة الحجم مباشرة بفضل بروتوكول MTProto.\n"
        "اكتب اسم الأنمي والحلقة (مثال: ون بيس 1000)"
    )

@bot.on_message(filters.text & ~filters.command("start"))
async def handle_text(client, message):
    query = message.text
    anime_name, ep_num = DATA.parse_smart_query(query)
    
    status_msg = await message.reply_text(f"🔍 جاري البحث عن: {anime_name}...")
    results = DATA.search_anime(anime_name)
    
    if not results:
        await status_msg.edit_text("❌ لم نجد نتائج.")
        return

    if ep_num:
        target = results[0]
        episodes = DATA.get_episodes(target["doc_ref"])
        target_ep = next((ep for ep in episodes if ep["order"] == ep_num), None)
        if target_ep:
            servers = DATA.get_servers(target["doc_ref"], target_ep["id"])
            pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
            if pd_link:
                # Run the heavy processing in the background to avoid blocking the bot
                asyncio.create_task(process_and_send_video(
                    message.chat.id, pd_link, 
                    f"🎬 **{target['name']}** - الحلقة {ep_num}", 
                    status_msg.id
                ))
                return

    buttons = [[types.InlineKeyboardButton(res["name"], callback_data=f"det|{res['doc_ref']}")] for res in results]
    await status_msg.edit_text("✅ اختر الأنمي:", reply_markup=types.InlineKeyboardMarkup(buttons))

@bot.on_callback_query()
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
        status_msg = await query.message.reply_text(f"⏳ جاري طلب الحلقة {ep_order}...")
        servers = DATA.get_servers(doc_ref, ep_id)
        pd_link = next((s["url"] for s in servers if "PD" in s["name"] or "pixeldrain" in s["url"].lower()), None)
        if pd_link:
            asyncio.create_task(process_and_send_video(
                query.message.chat.id, pd_link, 
                f"🎬 الحلقة {ep_order}", 
                status_msg.id
            ))
        else:
            await status_msg.edit_text("❌ رابط PD غير متوفر.")

# --- Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure Pyrogram starts correctly within the FastAPI event loop
    await bot.start()
    logger.info("MTProto Bot started successfully.")
    yield
    await bot.stop()

api_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # We use uvicorn to run FastAPI, which will trigger the lifespan and start the bot
    uvicorn.run(api_app, host="0.0.0.0", port=port)
