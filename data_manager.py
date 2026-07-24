import requests

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
        payload = {"params": f"query={query}&hitsPerPage=10"}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            return response.json().get("hits", []) if response.status_code == 200 else []
        except:
            return []

    def get_anime_details(self, anime_id):
        url = f"{self.firestore_base_url}/anime_list/{anime_id}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                fields = response.json().get("fields", {})
                return {
                    "name": fields.get("name", {}).get("stringValue", "N/A"),
                    "story": fields.get("details", {}).get("stringValue", "لا يوجد وصف."),
                    "rating": fields.get("rate", {}).get("stringValue", "N/A"),
                    "year": fields.get("year", {}).get("stringValue", "N/A"),
                    "genres": ", ".join([tag.get("stringValue") for tag in fields.get("tags", {}).get("arrayValue", {}).get("values", [])]),
                    "episodes_count": fields.get("episodes_count", {}).get("stringValue", "غير معروف"),
                    "studio": fields.get("studio", {}).get("stringValue", "غير معروف"),
                    "poster": fields.get("poster_uri", {}).get("stringValue", ""),
                    "type": fields.get("type", {}).get("stringValue", "anime") # anime or movie
                }
        except:
            pass
        return None

    def get_episodes(self, anime_id):
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
                        order = int(''.join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    episodes.append({"id": ep_id, "name": name, "order": order})
                episodes.sort(key=lambda x: x['order'])
                return episodes
        except:
            pass
        return []

    def get_servers(self, anime_id, episode_id):
        url = f"{self.firestore_base_url}/anime_list/{anime_id}/episodes/{episode_id}/servers"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                docs = response.json().get("documents", [])
                servers = []
                for doc in docs:
                    fields = doc.get("fields", {})
                    name = fields.get("name", {}).get("stringValue", "Unknown")
                    links = {}
                    if "streamtape_video_id" in fields:
                        links["Streamtape"] = f"https://streamtape.com/e/{fields['streamtape_video_id']['stringValue']}"
                    if "vidtube_video_id" in fields:
                        links["Vidtube"] = f"https://vidtube.one/e/{fields['vidtube_video_id']['stringValue']}"
                    if "link" in fields:
                        links["سيرفر مباشر"] = fields['link']['stringValue']
                    
                    # جلب الجودات إذا توفرت
                    qualities = []
                    if "1080p" in name: qualities.append("1080p")
                    elif "720p" in name: qualities.append("720p")
                    elif "480p" in name: qualities.append("480p")
                    else: qualities.append("جودة تلقائية")

                    servers.append({"name": name, "links": links, "qualities": qualities})
                return servers
        except:
            pass
        return []
