import requests
import logging
from concurrent.futures import ThreadPoolExecutor

class DataManager:
    def __init__(self):
        self.firebase_api_key = "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU"
        self.firebase_project_id = "animewitcher-1c66d"
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        
        self.algolia_app_id = "4W16Y84U3E"
        self.algolia_api_key = "05615f5e8e815049360862088365922e"
        self.id_token = None
        self.refresh_settings()

    def refresh_settings(self):
        try:
            auth_payload = {"returnSecureToken": True}
            auth_res = requests.post(self.auth_url, json=auth_payload, timeout=5)
            if auth_res.status_code == 200:
                self.id_token = auth_res.json().get("idToken")
        except:
            pass

    def search_algolia(self, index, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/{index}/query"
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key
        }
        try:
            payload = {"params": f"query={query}&hitsPerPage=10"}
            response = requests.post(url, headers=headers, json=payload, timeout=3)
            return response.json().get("hits", [])
        except:
            return []

    def search_anime(self, query):
        indices = ["anime", "series", "movies"]
        all_hits = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.search_algolia, idx, query) for idx in indices]
            for future in futures:
                all_hits.extend(future.result())
        seen = set()
        unique_hits = []
        for hit in all_hits:
            oid = hit.get("objectID")
            if oid not in seen:
                unique_hits.append(hit)
                seen.add(oid)
        return unique_hits[:15]

    def get_anime_details(self, anime_id):
        def fetch(coll):
            url = f"{self.firestore_base_url}/{coll}/{anime_id}"
            try:
                res = requests.get(url, timeout=3)
                if res.status_code == 200:
                    f = res.json().get("fields", {})
                    return {
                        "name": f.get("name", {}).get("stringValue", "غير متوفر"),
                        "story": f.get("details", {}).get("stringValue", "لا يوجد وصف."),
                        "rating": f.get("rate", {}).get("stringValue", "N/A"),
                        "year": f.get("year", {}).get("stringValue", "N/A"),
                        "genres": ", ".join([v.get("stringValue") for v in f.get("tags", {}).get("arrayValue", {}).get("values", [])]),
                        "episodes_count": f.get("episodes_count", {}).get("stringValue", "1"),
                        "studio": f.get("studio", {}).get("stringValue", "غير معروف"),
                        "poster": f.get("poster_uri", {}).get("stringValue", ""),
                        "collection": coll
                    }
            except:
                return None
            return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(fetch, ["anime_list", "anime_list_movies"]))
            for r in results:
                if r: return r
        return None

    def get_episodes(self, anime_id, collection):
        url = f"{self.firestore_base_url}/{collection}/{anime_id}/episodes"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                eps = []
                for doc in docs:
                    f = doc.get("fields", {})
                    name = f.get("name", {}).get("stringValue", "Unknown")
                    eid = doc.get("name").split("/")[-1]
                    try:
                        order = int(''.join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    eps.append({"id": eid, "name": name, "order": order})
                eps.sort(key=lambda x: x['order'])
                return eps
        except:
            pass
        return []

    def get_servers(self, anime_id, episode_id, collection):
        url = f"{self.firestore_base_url}/{collection}/{anime_id}/episodes/{episode_id}/servers"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                pd_links = []
                other_links = []
                for doc in docs:
                    f = doc.get("fields", {})
                    s_name = f.get("name", {}).get("stringValue", "سيرفر")
                    
                    # محاولة استخراج رابط PD (عادة ما يكون في حقل link أو حقل خاص)
                    link = f.get("link", {}).get("stringValue", "")
                    
                    if "pd" in s_name.lower() or "premium" in s_name.lower():
                        if link.startswith("http"):
                            pd_links.append({"name": f"💎 سيرفر PD ({s_name})", "url": link})
                    
                    if "streamtape_video_id" in f:
                        other_links.append({"name": f"🎬 Streamtape ({s_name})", "url": f"https://streamtape.com/e/{f['streamtape_video_id']['stringValue']}"})
                    if "vidtube_video_id" in f:
                        other_links.append({"name": f"🎥 Vidtube ({s_name})", "url": f"https://vidtube.one/e/{f['vidtube_video_id']['stringValue']}"})
                    if link.startswith("http") and not any(l['url'] == link for l in pd_links):
                        other_links.append({"name": f"🚀 مباشر ({s_name})", "url": link})
                
                # إرجاع PD أولاً ثم البقية
                return pd_links + other_links
        except:
            pass
        return []
