import os
import uvicorn
import asyncio

# Create and set a new event loop before importing pyrogram-based bot
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

if __name__ == "__main__":
    # Delayed import to ensure loop is set
    from bot import api_app
    
    port = int(os.environ.get("PORT", 8000))
    # Run uvicorn
    uvicorn.run(api_app, host="0.0.0.0", port=port)
