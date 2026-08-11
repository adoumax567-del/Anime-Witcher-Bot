import os
import re
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from rapidfuzz import fuzz

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self):
        self.firebase_api_key = os.environ.get("FIREBASE_API_KEY", "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU")
        self.firebase_project_id = os.environ.get("FIREBASE_PROJECT_ID", "animewitcher-1c66d")
        self.algolia_app_id = os.environ.get("ALGOLIA_APP_ID", "D8LH9I7ZL7")
        self.algolia_api_key = os.environ.get("ALGOLIA_API_KEY", "b56c01ef52540ef334bcdbaa00ded9e4")
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        self.id_token = None
        self.refresh_token()

    def refresh_token(self):
        try:
            res = requests.post(self.auth_url, json={"returnSecureToken": True}, timeout=5)
            if res.status_code == 200:
                self.id_token = res.json().get("idToken")
        except: pass

    def search_algolia(self, index, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/{index}/query"
        headers = {"X-Algolia-Application-Id": self.algolia_app_id, "X-Algolia-API-Key": self.algolia_api_key}
        try:
            res = requests.post(url, headers=headers, json={
                "params": f"query={query}&hitsPerPage=20&attributesToRetrieve=name,title,arabic_name,doc_ref,path,poster"
            }, timeout=3)
            return res.json().get("hits", [])
        except: return []

    def search_anime(self, query):
        indices = ["all_anime", "series", "movies", "anime_list"]
        all_hits = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(self.search_algolia, idx, query) for idx in indices]
            for f in futures: all_hits.extend(f.result())
        
        unique = {}
        for h in all_hits:
            oid = h.get("objectID")
            if oid not in unique:
                name = h.get("name") or h.get("title") or h.get("arabic_name") or "Unknown"
                unique[oid] = {
                    "name": name,
                    "doc_ref": h.get("doc_ref") or h.get("path") or f"anime_list/{oid}",
                    "poster": h.get("poster")
                }
        
        results = list(unique.values())
        # Enhanced sorting: Boost exact word matches (critical for 'Naruto')
        query_lower = query.lower()
        def get_score(item_name):
            item_name_lower = item_name.lower()
            score = fuzz.token_set_ratio(query_lower, item_name_lower)
            if query_lower in item_name_lower: score += 20
            if item_name_lower.startswith(query_lower): score += 10
            return score

        results.sort(key=lambda x: get_score(x["name"]), reverse=True)
        return results[:15]

    def get_anime_details(self, doc_ref):
        url = f"{self.firestore_base_url}/{doc_ref}"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            f = res.json().get("fields", {})
            return {
                "name": f.get("name", {}).get("stringValue") or f.get("title", {}).get("stringValue", "Unknown"),
                "story": f.get("story", {}).get("stringValue", "لا يوجد وصف متوفر."),
                "rating": f.get("rating", {}).get("stringValue", "N/A"),
                "poster": f.get("poster", {}).get("stringValue"),
                "status": f.get("status", {}).get("stringValue", "غير معروف"),
                "num_episodes": f.get("num_episodes", {}).get("stringValue") or f.get("episodes_count", {}).get("stringValue", "غير محدد"),
                "year": f.get("year", {}).get("stringValue", "غير معروف"),
                "type": f.get("type", {}).get("stringValue", "أنمي")
            }
        except: return None

    def get_episodes(self, doc_ref):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            docs = res.json().get("documents", [])
            eps = []
            for d in docs:
                f = d.get("fields", {})
                name = f.get("name", {}).get("stringValue", "Unknown")
                eid = d.get("name").split("/")[-1]
                try: order = int("".join(filter(str.isdigit, name)))
                except: order = 999
                eps.append({"id": eid, "name": name, "order": order})
            eps.sort(key=lambda x: x["order"])
            return eps
        except: return []

    def resolve_pd(self, url, mode="view"):
        if "pixeldrain.com" in url:
            match = re.search(r"(?:/u/|/api/file/|/l/)([a-zA-Z0-9]+)", url)
            if match:
                file_id = match.group(1)
                return f"https://pixeldrain.com/u/{file_id}" if mode == "view" else f"https://pixeldrain.com/api/file/{file_id}?download"
        return url

    def get_servers(self, doc_ref, ep_id):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes/{ep_id}/servers"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            docs = res.json().get("documents", [])
            servers = []
            for d in docs:
                f = d.get("fields", {})
                name = f.get("name", {}).get("stringValue", "Server")
                link = f.get("link", {}).get("stringValue", "")
                if not link:
                    for k, b in [("streamtape_video_id", "https://streamtape.com/e/"), ("mixdrop_video_id", "https://mixdrop.co/e/")]:
                        if k in f: link = b + f[k].get("stringValue", ""); break
                if link:
                    servers.append({
                        "name": name, 
                        "url": self.resolve_pd(link, mode="view"), 
                        "app_url": self.resolve_pd(link, mode="download"),
                        "is_pd": "pixeldrain" in link.lower()
                    })
            servers.sort(key=lambda x: x["is_pd"], reverse=True)
            return servers
        except: return []

    def parse_smart_query(self, q):
        m = re.search(r"(.+)\s+(?:الحلقة|حلقة|episode|ep|part)\s+(\d+)", q, re.I)
        if not m: m = re.search(r"(.+)\s+(\d+)$", q)
        if m: return m.group(1).strip(), int(m.group(2))
        return q.strip(), None
