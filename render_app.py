from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Anime Witcher Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()
    # هنا سيتم تشغيل البوت في نفس العملية
    os.system("python bot.py")
