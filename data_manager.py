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
        # المحاولة الأولى: Algolia (البحث الذكي)
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/anime/query"
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key
        }
        payload = {"params": f"query={query}&hitsPerPage=20"}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            hits = response.json().get("hits", [])
            if hits:
                return hits
        except:
            pass

        # المحاولة الثانية: البحث المباشر في Firestore (إذا فشل Algolia)
        # ملاحظة: Firestore لا يدعم البحث الجزئي بسهولة، لذا سنحاول جلب القائمة الرئيسية وفلترتها يدوياً كحل احتياطي
        return self.fallback_search(query)

    def fallback_search(self, query):
        url = f"{self.firestore_base_url}/anime_list?pageSize=100"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                docs = response.json().get("documents", [])
                results = []
                for doc in docs:
                    fields = doc.get("fields", {})
                    name = fields.get("name", {}).get("stringValue", "")
                    if query.lower() in name.lower():
                        results.append({
                            "name": name,
                            "objectID": doc.get("name").split("/")[-1]
                        })
                return results
        except:
            pass
        return []

    def get_anime_details(self, anime_id):
        # محاولة جلب من anime_list (مسلسلات) أو anime_list_movies (أفلام)
        for collection in ["anime_list", "anime_list_movies"]:
            url = f"{self.firestore_base_url}/{collection}/{anime_id}"
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
                        "episodes_count": fields.get("episodes_count", {}).get("stringValue", "1"),
                        "studio": fields.get("studio", {}).get("stringValue", "غير معروف"),
                        "poster": fields.get("poster_uri", {}).get("stringValue", ""),
                        "collection": collection
                    }
            except:
                continue
        return None

    def get_episodes(self, anime_id, collection="anime_list"):
        url = f"{self.firestore_base_url}/{collection}/{anime_id}/episodes"
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
                        order = int(''.join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    episodes.append({"id": ep_id, "name": name, "order": order})
                episodes.sort(key=lambda x: x['order'])
                return episodes
        except:
            pass
        return []

    def get_servers(self, anime_id, episode_id, collection="anime_list"):
        url = f"{self.firestore_base_url}/{collection}/{anime_id}/episodes/{episode_id}/servers"
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                docs = response.json().get("documents", [])
                all_links = []
                for doc in docs:
                    fields = doc.get("fields", {})
                    server_name = fields.get("name", {}).get("stringValue", "سيرفر")
                    
                    # جلب جميع الروابط الممكنة
                    if "streamtape_video_id" in fields:
                        val = fields["streamtape_video_id"]["stringValue"]
                        all_links.append({"name": f"🎬 Streamtape ({server_name})", "url": f"https://streamtape.com/e/{val}"})
                    
                    if "vidtube_video_id" in fields:
                        val = fields["vidtube_video_id"]["stringValue"]
                        all_links.append({"name": f"🎥 Vidtube ({server_name})", "url": f"https://vidtube.one/e/{val}"})
                    
                    if "link" in fields:
                        val = fields["link"]["stringValue"]
                        if val.startswith("http"):
                            all_links.append({"name": f"🚀 مباشر ({server_name})", "url": val})
                
                return all_links
        except:
            pass
        return []
