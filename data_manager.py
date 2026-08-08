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
            res = requests.post(url, headers=headers, json={"params": f"query={query}&hitsPerPage=20"}, timeout=3)
            return res.json().get("hits", [])
        except: return []

    def search_anime(self, query):
        # Broad search across all possible indices to find movies, series, and anime
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
                    "doc_ref": h.get("doc_ref") or h.get("path") or f"anime_list/{oid}"
                }
        
        results = list(unique.values())
        results.sort(key=lambda x: fuzz.ratio(query.lower(), x["name"].lower()), reverse=True)
        return results[:10]

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
        """
        mode='view': For browser playback (prevents Hotlink error)
        mode='download': For app M3u8 playback
        """
        if "pixeldrain.com" in url:
            match = re.search(r"(?:/u/|/api/file/|/l/)([a-zA-Z0-9]+)", url)
            if match:
                file_id = match.group(1)
                if mode == "view":
                    return f"https://pixeldrain.com/u/{file_id}"
                else:
                    return f"https://pixeldrain.com/api/file/{file_id}?download"
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
                    # We store both to be flexible
                    view_url = self.resolve_pd(link, mode="view")
                    download_url = self.resolve_pd(link, mode="download")
                    servers.append({
                        "name": name, 
                        "url": view_url, 
                        "app_url": download_url,
                        "is_pd": "pixeldrain" in view_url
                    })
            servers.sort(key=lambda x: x["is_pd"], reverse=True)
            return servers
        except: return []

    def parse_smart_query(self, q):
        m = re.search(r"(.+)\s+(?:الحلقة|حلقة|episode|ep|part)\s+(\d+)", q, re.I)
        if not m: m = re.search(r"(.+)\s+(\d+)$", q)
        if m: return m.group(1).strip(), int(m.group(2))
        return q.strip(), None
