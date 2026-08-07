import os
import uvicorn
from bot import api_app

if __name__ == "__main__":
    # Get port from environment variable for Render/Railway
    port = int(os.environ.get("PORT", 8000))
    # Run the FastAPI app which also manages the Telegram bot lifecycle
    uvicorn.run(api_app, host="0.0.0.0", port=port)
