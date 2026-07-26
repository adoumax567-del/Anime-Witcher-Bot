import requests
import logging

class DataManager:
    def __init__(self):
        self.firebase_api_key = "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU"
        self.firebase_project_id = "animewitcher-1c66d"
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.algolia_app_id = "4W16Y84U3E"
        self.algolia_api_key = "05615f5e8e815049360862088365922e"

    def search_anime(self, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/anime/query"
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key
        }
        payload = {"params": f"query={query}&hitsPerPage=15"}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            return response.json().get("hits", []) if response.status_code == 200 else []
        except Exception as e:
            logging.error(f"Search Error: {e}")
            return []

    def get_anime_details(self, anime_id):
        url = f"{self.firestore_base_url}/anime_list/{anime_id}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                fields = response.json().get("fields", {})
                return {
                    "name": fields.get("name", {}).get("stringValue", "غير متوفر"),
                    "story": fields.get("details", {}).get("stringValue", "لا يوجد وصف حالياً."),
                    "rating": fields.get("rate", {}).get("stringValue", "N/A"),
                    "year": fields.get("year", {}).get("stringValue", "N/A"),
                    "genres": ", ".join([tag.get("stringValue") for tag in fields.get("tags", {}).get("arrayValue", {}).get("values", [])]),
                    "episodes_count": fields.get("episodes_count", {}).get("stringValue", "غير معروف"),
                    "studio": fields.get("studio", {}).get("stringValue", "غير معروف"),
                    "poster": fields.get("poster_uri", {}).get("stringValue", ""),
                }
        except Exception as e:
            logging.error(f"Details Error: {e}")
        return None

    def get_episodes(self, anime_id):
        # محاولة جلب الحلقات من المسار الصحيح
        url = f"{self.firestore_base_url}/anime_list/{anime_id}/episodes"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                docs = response.json().get("documents", [])
                episodes = []
                for doc in docs:
                    fields = doc.get("fields", {})
                    name = fields.get("name", {}).get("stringValue", "Unknown")
                    ep_id = doc.get("name").split("/")[-1]
                    try:
                        # استخراج الرقم من الاسم (مثال: "الحلقة 1" -> 1)
                        order = int(''.join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    episodes.append({"id": ep_id, "name": name, "order": order})
                episodes.sort(key=lambda x: x['order'])
                return episodes
        except Exception as e:
            logging.error(f"Episodes Error: {e}")
        return []

    def get_servers(self, anime_id, episode_id):
        # المسار في التطبيق هو anime_list/{id}/episodes/{id}/servers
        url = f"{self.firestore_base_url}/anime_list/{anime_id}/episodes/{episode_id}/servers"
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                docs = response.json().get("documents", [])
                all_links = []
                for doc in docs:
                    fields = doc.get("fields", {})
                    server_name = fields.get("name", {}).get("stringValue", "سيرفر غير معروف")
                    
                    # فحص جميع الحقول الممكنة للروابط
                    if "streamtape_video_id" in fields:
                        val = fields["streamtape_video_id"]["stringValue"]
                        all_links.append({"name": f"🎬 Streamtape ({server_name})", "url": f"https://streamtape.com/e/{val}"})
                    
                    if "vidtube_video_id" in fields:
                        val = fields["vidtube_video_id"]["stringValue"]
                        all_links.append({"name": f"🎥 Vidtube ({server_name})", "url": f"https://vidtube.one/e/{val}"})
                    
                    if "link" in fields:
                        val = fields["link"]["stringValue"]
                        if val.startswith("http"):
                            all_links.append({"name": f"🚀 سيرفر مباشر ({server_name})", "url": val})
                
                return all_links
        except Exception as e:
            logging.error(f"Servers Error: {e}")
        return []
