import requests
import logging
import re
from concurrent.futures import ThreadPoolExecutor

class DataManager:
    def __init__(self):
        # Firebase Credentials
        self.firebase_api_key = "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU"
        self.firebase_project_id = "animewitcher-1c66d"
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        
        # Correct Algolia Credentials from Settings/search_service
        self.algolia_app_id = "D8LH9I7ZL7"
        self.algolia_api_key = "b56c01ef52540ef334bcdbaa00ded9e4"
        
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
        # Using 'all_anime' and 'series' as primary indices
        indices = ["all_anime", "series"]
        all_hits = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.search_algolia, idx, query) for idx in indices]
            for future in futures:
                all_hits.extend(future.result())
        
        unique_hits = []
        seen = set()
        for hit in all_hits:
            oid = hit.get("objectID")
            if oid not in seen:
                # Normalize hit data
                name = hit.get("name")
                doc_ref = hit.get("doc_ref") or hit.get("path")
                if not doc_ref:
                    # Fallback if no doc_ref is provided
                    doc_ref = f"anime_list/{oid}"
                
                unique_hits.append({
                    "objectID": oid,
                    "name": name,
                    "doc_ref": doc_ref
                })
                seen.add(oid)
        
        return unique_hits[:15]

    def get_anime_details(self, doc_ref):
        # doc_ref is something like "anime_list/Naruto"
        url = f"{self.firestore_base_url}/{doc_ref}"
        try:
            res = requests.get(url, params={"key": self.firebase_api_key}, timeout=3)
            if res.status_code == 200:
                f = res.json().get("fields", {})
                details = f.get("details", {}).get("mapValue", {}).get("fields", {})
                return {
                    "name": f.get("name", {}).get("stringValue", "غير متوفر"),
                    "story": f.get("story", {}).get("stringValue", "لا يوجد وصف."),
                    "rating": f.get("rating", {}).get("mapValue", {}).get("fields", {}).get("rate", {}).get("doubleValue", "N/A"),
                    "year": details.get("year", {}).get("stringValue", "N/A"),
                    "genres": ", ".join([v.get("stringValue") for v in f.get("tags", {}).get("arrayValue", {}).get("values", [])]),
                    "episodes_count": details.get("eps_num", {}).get("stringValue", "1"),
                    "studio": ", ".join([v.get("stringValue") for v in details.get("studio", {}).get("arrayValue", {}).get("values", [])]) if "studio" in details else "غير معروف",
                    "poster": f.get("poster_uri", {}).get("stringValue", ""),
                    "doc_ref": doc_ref
                }
        except Exception as e:
            logging.error(f"Error getting anime details: {e}")
        return None

    def get_episodes(self, doc_ref):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes"
        try:
            res = requests.get(url, params={"key": self.firebase_api_key}, timeout=5)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                eps = []
                for doc in docs:
                    f = doc.get("fields", {})
                    name = f.get("name", {}).get("stringValue", "Unknown")
                    eid = doc.get("name").split("/")[-1]
                    try:
                        # Extract episode number from name (e.g., "الحلقة 1" -> 1)
                        order = int("".join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    eps.append({"id": eid, "name": name, "order": order})
                eps.sort(key=lambda x: x["order"])
                return eps
        except:
            pass
        return []

    def get_servers(self, doc_ref, episode_id):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes/{episode_id}/servers"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                pd_links = []
                other_links = []
                for doc in docs:
                    f = doc.get("fields", {})
                    s_name = f.get("name", {}).get("stringValue", "سيرفر")
                    link = f.get("link", {}).get("stringValue", "")
                    
                    if "pd" in s_name.lower() or "premium" in s_name.lower() or "direct" in s_name.lower():
                        if link.startswith("http"):
                            pd_links.append({"name": f"💎 سيرفر PD ({s_name})", "url": link})
                    
                    if "streamtape_video_id" in f:
                        other_links.append({"name": f"🎬 Streamtape ({s_name})", "url": f"https://streamtape.com/e/{f['streamtape_video_id']['stringValue']}"})
                    if "vidtube_video_id" in f:
                        other_links.append({"name": f"🎥 Vidtube ({s_name})", "url": f"https://vidtube.one/e/{f['vidtube_video_id']['stringValue']}"})
                    
                    if link.startswith("http") and not any(l["url"] == link for l in pd_links):
                        other_links.append({"name": f"🚀 {s_name}", "url": link})
                
                return pd_links + other_links
        except:
            pass
        return []

    def parse_smart_query(self, query):
        # Try to match "Anime Name Episode X" or "Anime Name الحلقة X"
        patterns = [
            r"(.+)\s+(?:episode|ep|الحلقة|حلقة)\s+(\d+)",
            r"(.+)\s+(\d+)$"
        ]
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip(), int(match.group(2))
        return query, None
