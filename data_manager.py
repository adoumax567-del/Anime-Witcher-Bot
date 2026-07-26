import requests
import logging

class DataManager:
    def __init__(self):
        self.firebase_api_key = "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU"
        self.firebase_project_id = "animewitcher-1c66d"
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        
        # قيم افتراضية (سيتم تحديثها ديناميكياً)
        self.algolia_app_id = "4W16Y84U3E"
        self.algolia_api_key = "05615f5e8e815049360862088365922e"
        self.id_token = None
        
        # تحديث الإعدادات عند البدء
        self.refresh_settings()

    def refresh_settings(self):
        """جلب أحدث مفاتيح Algolia وتسجيل الدخول كـ Guest"""
        try:
            # 1. تسجيل الدخول المجهول للحصول على ID Token (تخطي حماية السيرفرات)
            auth_payload = {"returnSecureToken": True}
            auth_res = requests.post(self.auth_url, json=auth_payload, timeout=10)
            if auth_res.status_code == 200:
                self.id_token = auth_res.json().get("idToken")
                logging.info("Firebase Auth Success")

            # 2. جلب مفاتيح Algolia الحالية من Firestore
            settings_url = f"{self.firestore_base_url}/Settings/constants"
            res = requests.get(settings_url, timeout=10)
            if res.status_code == 200:
                fields = res.json().get("fields", {})
                search_settings = fields.get("search_settings", {}).get("mapValue", {}).get("fields", {})
                if search_settings:
                    self.algolia_app_id = search_settings.get("app_id", {}).get("stringValue", self.algolia_app_id)
                    self.algolia_api_key = search_settings.get("api_key", {}).get("stringValue", self.algolia_api_key)
                    logging.info(f"Algolia Keys Updated: {self.algolia_app_id}")
        except Exception as e:
            logging.error(f"Refresh Settings Error: {e}")

    def search_anime(self, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/anime/query"
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key
        }
        # البحث في الـ Index الأساسي "anime" والاحتياطي "series"
        for index in ["anime", "series"]:
            try:
                search_url = url.replace("/anime/", f"/{index}/")
                payload = {"params": f"query={query}&hitsPerPage=15"}
                response = requests.post(search_url, headers=headers, json=payload, timeout=10)
                hits = response.json().get("hits", [])
                if hits:
                    return hits
            except:
                continue
        return self.fallback_search(query)

    def fallback_search(self, query):
        # بحث يدوي في Firestore للمسلسلات والأفلام
        results = []
        for coll in ["anime_list", "anime_list_movies"]:
            try:
                url = f"{self.firestore_base_url}/{coll}?pageSize=50"
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    docs = res.json().get("documents", [])
                    for doc in docs:
                        fields = doc.get("fields", {})
                        name = fields.get("name", {}).get("stringValue", "")
                        if query.lower() in name.lower():
                            results.append({"name": name, "objectID": doc.get("name").split("/")[-1]})
            except:
                continue
        return results

    def get_anime_details(self, anime_id):
        for collection in ["anime_list", "anime_list_movies"]:
            url = f"{self.firestore_base_url}/{collection}/{anime_id}"
            try:
                res = requests.get(url, timeout=10)
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
                        "collection": collection
                    }
            except:
                continue
        return None

    def get_episodes(self, anime_id, collection):
        url = f"{self.firestore_base_url}/{collection}/{anime_id}/episodes"
        try:
            res = requests.get(url, timeout=10)
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
        headers = {}
        if self.id_token:
            headers["Authorization"] = f"Bearer {self.id_token}"
            
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                links = []
                for doc in docs:
                    f = doc.get("fields", {})
                    s_name = f.get("name", {}).get("stringValue", "سيرفر")
                    
                    if "streamtape_video_id" in f:
                        v = f["streamtape_video_id"]["stringValue"]
                        links.append({"name": f"🎬 Streamtape ({s_name})", "url": f"https://streamtape.com/e/{v}"})
                    
                    if "vidtube_video_id" in f:
                        v = f["vidtube_video_id"]["stringValue"]
                        links.append({"name": f"🎥 Vidtube ({s_name})", "url": f"https://vidtube.one/e/{v}"})
                    
                    if "link" in f:
                        v = f["link"]["stringValue"]
                        if v.startswith("http"):
                            links.append({"name": f"🚀 مباشر ({s_name})", "url": v})
                return links
        except:
            pass
        return []
