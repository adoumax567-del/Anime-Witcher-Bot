import os
import uvicorn
from bot import api_app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on port {port}...")
    uvicorn.run("bot:api_app", host="0.0.0.0", port=port, reload=False)
