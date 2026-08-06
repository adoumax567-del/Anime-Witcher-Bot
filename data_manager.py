import firebase_admin
from firebase_admin import credentials, firestore
import os
import re
import requests
import logging
from concurrent.futures import ThreadPoolExecutor
from fuzzywuzzy import fuzz

# Setup Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

class DataManager:
    def __init__(self):
        if not firebase_admin._apps:
            # Use a dictionary to hold credentials if not using a file
            cred_config = {
                "type": os.environ.get("FIREBASE_TYPE"),
                "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
                "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
                "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
                "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
                "token_uri": os.environ.get("FIREBASE_TOKEN_URI"),
                "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
                "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509_CERT_URL")
            }
            cred = credentials.Certificate(cred_config)
            firebase_admin.initialize_app(cred)
        
        self.db = firestore.client()
        self.anime_collection = self.db.collection("anime_list")

        # Correct Algolia Credentials from Settings/search_service
        self.algolia_app_id = os.environ.get("ALGOLIA_APP_ID", "D8LH9I7ZL7")
        self.algolia_api_key = os.environ.get("ALGOLIA_API_KEY", "b56c01ef52540ef334bcdbaa00ded9e4")
        self.firebase_api_key = os.environ.get("FIREBASE_API_KEY", "AIzaSyAcbWRwfFNnCpoydDXlEALWnM_TYVcJOMU")
        self.firebase_project_id = os.environ.get("FIREBASE_PROJECT_ID", "animewitcher-1c66d")
        self.firestore_base_url = f"https://firestore.googleapis.com/v1/projects/{self.firebase_project_id}/databases/(default)/documents"
        self.auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={self.firebase_api_key}"
        
        self.id_token = None
        self.refresh_settings()

    def refresh_settings(self):
        try:
            auth_payload = {"returnSecureToken": True}
            auth_res = requests.post(self.auth_url, json=auth_payload, timeout=5)
            if auth_res.status_code == 200:
                self.id_token = auth_res.json().get("idToken")
                logger.info("Firebase ID token refreshed successfully.")
            else:
                logger.warning(f"Failed to refresh Firebase ID token: {auth_res.status_code} - {auth_res.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during Firebase ID token refresh: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during Firebase ID token refresh: {e}")

    def search_algolia(self, index, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/{index}/query"
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key
        }
        try:
            # Enhanced payload for fuzzy search and multi-language support
            payload = {
                "params": f"query={query}&hitsPerPage=10",
                "queryLanguages": ["en", "ar", "es", "fr", "ja"], # Support multiple languages
                "typoTolerance": "min" # Enable typo tolerance
            }
            response = requests.post(url, headers=headers, json=payload, timeout=3)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return response.json().get("hits", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Algolia search failed for index {index} with query \'{query}\': {e}")
            return []

    def search_anime(self, query):
        # First, try Algolia search
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
                name = hit.get("name")
                doc_ref = hit.get("doc_ref") or hit.get("path")
                if not doc_ref:
                    doc_ref = f"anime_list/{oid}"
                
                unique_hits.append({
                    "objectID": oid,
                    "name": name,
                    "doc_ref": doc_ref
                })
                seen.add(oid)
        
        # If Algolia returns results, sort them by fuzzy ratio and return top 5
        if unique_hits:
            unique_hits.sort(key=lambda x: fuzz.ratio(query.lower(), x.get("name", "").lower()), reverse=True)
            return unique_hits[:5]

        # Fallback to Firestore if Algolia returns no results or fails
        logger.info(f"Algolia returned no results for '{query}', falling back to Firestore fuzzy search.")
        all_anime_docs = self.anime_collection.stream()
        fuzzy_matches = []
        for doc in all_anime_docs:
            data = doc.to_dict()
            anime_name = data.get("name")
            if anime_name:
                score = fuzz.token_set_ratio(query.lower(), anime_name.lower())
                if score > 60:  # Threshold for a reasonable match
                    data["doc_ref"] = doc.reference.path
                    data["score"] = score
                    fuzzy_matches.append(data)
        
        fuzzy_matches.sort(key=lambda x: x["score"], reverse=True)
        return fuzzy_matches[:5]

    def get_anime_details(self, doc_ref):
        url = f"{self.firestore_base_url}/{doc_ref}"
        try:
            res = requests.get(url, params={"key": self.firebase_api_key}, timeout=3)
            res.raise_for_status()
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting anime details for {doc_ref}: {e}")
        except Exception as e:
            logger.error(f"Error getting anime details for {doc_ref}: {e}")
        return None

    def get_episodes(self, doc_ref):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            res.raise_for_status()
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                eps = []
                for doc in docs:
                    f = doc.get("fields", {})
                    name = f.get("name", {}).get("stringValue", "Unknown")
                    eid = doc.get("name").split("/")[-1]
                    try:
                        order = int("".join(filter(str.isdigit, name)))
                    except:
                        order = 999
                    eps.append({"id": eid, "name": name, "order": order})
                eps.sort(key=lambda x: x["order"])
                return eps
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting episodes for {doc_ref}: {e}")
        except Exception as e:
            logger.error(f"Error getting episodes for {doc_ref}: {e}")
        return []

    def resolve_m3u8(self, url):
        """
        Try to resolve a streamable M3u8 link from an iframe/redirector link.
        This function aims to return the most direct video URL for streaming.
        """
        if not url or not url.startswith("http"):
            return url
            
        # 1. PixelDrain Direct Download Link (often streamable)
        if "pixeldrain.com" in url:
            pd_id_match = re.search(r"(?:/u/|/api/file/)([a-zA-Z0-9]+)", url)
            if pd_id_match:
                direct_link = f"https://pixeldrain.com/api/file/{pd_id_match.group(1)}?download"
                logger.info(f"Resolved PixelDrain link to: {direct_link}")
                return direct_link
        
        # 2. MixDrop (requires scraping for direct link, but we can return embed for now)
        if "mixdrop" in url:
            match = re.search(r"/e/([a-zA-Z0-9]+)", url)
            if match:
                embed_link = f"https://mixdrop.co/e/{match.group(1)}"
                logger.info(f"Resolved MixDrop embed link: {embed_link}")
                return embed_link # This is an embed, not direct M3u8, but might work for some players
        
        # 3. StreamTape (embed link)
        if "streamtape.com" in url:
            match = re.search(r"/(?:e|v)/([a-zA-Z0-9]+)", url)
            if match:
                embed_link = f"https://streamtape.com/e/{match.group(1)}"
                logger.info(f"Resolved StreamTape embed link: {embed_link}")
                return embed_link
        
        # 4. StreamWish (embed link)
        if "streamwish" in url or "strwish" in url:
            match = re.search(r"/e/([a-zA-Z0-9]+)", url)
            if match:
                embed_link = f"https://streamwish.to/e/{match.group(1)}"
                logger.info(f"Resolved StreamWish embed link: {embed_link}")
                return embed_link

        # 5. DoodStream (embed link)
        if "doodstream" in url or "dood.to" in url:
            match = re.search(r"/(?:e|d)/([a-zA-Z0-9]+)", url)
            if match:
                embed_link = f"https://dood.to/e/{match.group(1)}"
                logger.info(f"Resolved DoodStream embed link: {embed_link}")
                return embed_link

        logger.info(f"No specific resolution for URL: {url}. Returning as is.")
        return url

    def get_servers(self, doc_ref, episode_id):
        url = f"{self.firestore_base_url}/{doc_ref}/episodes/{episode_id}/servers"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=5)
            res.raise_for_status()
            if res.status_code == 200:
                docs = res.json().get("documents", [])
                all_servers = []
                
                for doc in docs:
                    f = doc.get("fields", {})
                    s_name = f.get("name", {}).get("stringValue", "سيرفر")
                    link = f.get("link", {}).get("stringValue", "")
                    
                    # Check for hidden fields in Anime Witcher's Firestore structure
                    if not link:
                        for key_prefix, base_url in [
                            ("streamtape_video_id", "https://streamtape.com/e/"),
                            ("vidtube_video_id", "https://vidtube.one/e/"),
                            ("mixdrop_video_id", "https://mixdrop.co/e/"),
                            ("doodstream_video_id", "https://dood.to/e/")
                        ]:
                            if key_prefix in f:
                                val = f[key_prefix].get("stringValue", "")
                                if val: # Ensure value is not empty
                                    link = f"{base_url}{val}"
                                    logger.info(f"Found hidden link for {key_prefix}: {link}")
                                    break
                    
                    if link:
                        resolved_link = self.resolve_m3u8(link)
                        is_pd = "pd" in s_name.lower() or "premium" in s_name.lower() or "pixeldrain" in resolved_link.lower()
                        
                        server_info = {
                            "name": f"💎 PD ({s_name})" if is_pd else f"🚀 {s_name}",
                            "url": resolved_link,
                            "priority": 1 if is_pd else 2
                        }
                        all_servers.append(server_info)
                
                # Sort: PD first
                all_servers.sort(key=lambda x: x["priority"])
                return all_servers
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching servers for {doc_ref}/{episode_id}: {e}")
        except Exception as e:
            logger.error(f"Error fetching servers for {doc_ref}/{episode_id}: {e}")
        return []

    def parse_smart_query(self, query):
        patterns = [
            r"(.+)\s+(?:episode|ep|الحلقة|حلقة)\s+(\d+)",
            r"(.+)\s+(\d+)$"
        ]
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip(), int(match.group(2))
        return query, None
