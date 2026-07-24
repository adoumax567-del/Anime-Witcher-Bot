from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Anime Witcher Bot is Running!"

def keep_alive():
    import time
    while True:
        try:
            requests.get("https://anime-witcher-bot.onrender.com")
            print("Ping successful!")
        except:
            print("Ping failed.")
        time.sleep(600) # كل 10 دقائق

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # تشغيل خادم الويب
    t1 = threading.Thread(target=run_flask)
    t1.start()
    
    # تشغيل ميزة البقاء حياً
    t2 = threading.Thread(target=keep_alive)
    t2.start()
    
    # تشغيل البوت
    os.system("python bot.py")
