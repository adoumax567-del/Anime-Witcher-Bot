from flask import Flask, request, jsonify
import threading
import os
import subprocess
from data_manager import DataManager

app = Flask(__name__)
DATA = DataManager()

@app.route('/')
def home():
    return "Anime Witcher Bot & API Service is Running!"

@app.route('/get_links', methods=['GET'])
def get_links():
    query = request.args.get('query')
    if not query:
        return jsonify({"status": "error", "message": "No query provided"}), 400
    
    anime_name, ep_num = DATA.parse_smart_query(query)
    results = DATA.search_anime(anime_name)
    
    if not results:
        return jsonify({"status": "error", "message": "Anime not found"}), 404

    if ep_num is None:
        return jsonify({"status": "error", "message": "Please specify an episode number, e.g., 'Naruto 5'"}), 400

    target_anime = results[0]
    doc_ref = target_anime['doc_ref']
    episodes = DATA.get_episodes(doc_ref)
    
    target_ep = None
    for ep in episodes:
        if ep['order'] == ep_num:
            target_ep = ep
            break
    
    if not target_ep:
        return jsonify({"status": "error", "message": f"Episode {ep_num} not found"}), 404

    servers = DATA.get_servers(doc_ref, target_ep['id'])
    # Filter for PD links only
    pd_only = [s for s in servers if "💎 سيرفر PD" in s['name']]
    
    return jsonify({
        "status": "success",
        "anime": target_anime['name'],
        "episode": ep_num,
        "links": pd_only
    })

def run_bot():
    # Run the bot in a separate process
    subprocess.run(["python3", "bot.py"])

if __name__ == "__main__":
    # Start the bot in a background thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Run the Flask API server
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
