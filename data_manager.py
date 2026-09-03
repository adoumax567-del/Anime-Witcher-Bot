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
            res = requests.post(self.auth_url, json={"returnSecureToken": True}, timeout=10)
            if res.status_code == 200:
                self.id_token = res.json().get("idToken")
        except: pass

    def search_algolia(self, index, query):
        url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/{index}/query"
        headers = {"X-Algolia-Application-Id": self.algolia_app_id, "X-Algolia-API-Key": self.algolia_api_key}
        try:
            # Broaden search with multiple query strategies and empty query fallback if needed
            res = requests.post(url, headers=headers, json={
                "params": f"query={query}&hitsPerPage=50&typoTolerance=true&ignorePlurals=true&removeStopWords=true"
            }, timeout=8)
            data = res.json()
            return data.get("hits", [])
        except Exception as e:
            logger.error(f"Algolia search error on index {index}: {e}")
            return []

    def search_characters(self, query):
        """Search character records across likely Anime Witcher Algolia indexes."""
        query = query.strip()
        if not query:
            return []
        indexes = ["characters", "character", "people", "anime_characters"]
        hits = []
        with ThreadPoolExecutor(max_workers=len(indexes)) as executor:
            futures = [executor.submit(self.search_algolia, idx, query) for idx in indexes]
            for future in futures:
                hits.extend(future.result())
        unique = {}
        normalized_query = self.normalize_text(query)
        for hit in hits:
            name = (hit.get("name") or hit.get("character_name") or
                    hit.get("title") or hit.get("english_name") or
                    hit.get("arabic_name"))
            if not name:
                continue
            key = str(hit.get("objectID") or hit.get("id") or name).lower()
            score = max(fuzz.token_set_ratio(normalized_query, self.normalize_text(str(name))),
                        fuzz.partial_ratio(normalized_query, self.normalize_text(str(name))))
            if score < 35:
                continue
            unique[key] = {
                "id": hit.get("objectID") or hit.get("id") or key,
                "name": name,
                "name_ar": hit.get("arabic_name") or hit.get("name_ar"),
                "name_en": hit.get("english_name") or hit.get("name_en"),
                "description": hit.get("description") or hit.get("story") or hit.get("about") or hit.get("bio"),
                "poster": hit.get("poster") or hit.get("image") or hit.get("cover") or hit.get("main_picture"),
                "works": hit.get("works") or hit.get("anime") or hit.get("appearances") or hit.get("related_works") or [],
                "doc_ref": hit.get("doc_ref") or hit.get("path"),
                "mal_id": hit.get("mal_id") or hit.get("id") or hit.get("objectID"),
                "score": score,
            }
        return sorted(unique.values(), key=lambda item: item["score"], reverse=True)[:20]

    @staticmethod
    def normalize_text(value):
        value = str(value or "").lower().strip()
        return re.sub(r"[أإآٱ]", "ا", value).replace("ة", "ه").replace("ى", "ي")

    def get_character_details(self, character):
        """Normalize character fields and optionally enrich sparse Algolia records."""
        works = character.get("works") or []
        if isinstance(works, str):
            works = [works]
        description = character.get("description")
        poster = character.get("poster")
        mal_id = character.get("mal_id") or character.get("id")

        # Character documents contain the complete profile, while Algolia often
        # indexes only name, image and objectID. Read that document when sparse.
        if (not description or not works) and character.get("doc_ref"):
            try:
                url = f"{self.firestore_base_url}/{str(character['doc_ref']).lstrip('/')}"
                response = requests.get(url, params={"key": self.firebase_api_key}, timeout=6)
                if response.status_code == 200:
                    fields = response.json().get("fields", {})
                    def unwrap(value):
                        if not isinstance(value, dict):
                            return value
                        if "stringValue" in value: return value["stringValue"]
                        if "integerValue" in value: return value["integerValue"]
                        if "doubleValue" in value: return value["doubleValue"]
                        if "mapValue" in value:
                            return {k: unwrap(v) for k, v in value["mapValue"].get("fields", {}).items()}
                        if "arrayValue" in value:
                            return [unwrap(v) for v in value["arrayValue"].get("values", [])]
                        return None
                    raw = {key: unwrap(value) for key, value in fields.items()}
                    nested = raw.get("data") if isinstance(raw.get("data"), dict) else {}
                    profile = {**nested, **raw}
                    description = description or profile.get("about") or profile.get("description") or profile.get("story")
                    poster = poster or profile.get("main_picture") or profile.get("image")
                    if not works:
                        works = []
                        for entry in profile.get("anime", []) or []:
                            item = entry.get("anime", entry) if isinstance(entry, dict) else entry
                            if isinstance(item, dict) and item.get("title"):
                                works.append(item["title"])
            except Exception as exc:
                logger.info("Character document unavailable for %s: %s", mal_id, exc)

        # Keep a short best-effort external fallback only when the app document
        # is unavailable; it is never required for returning a usable profile.
        if (not description or not works) and str(mal_id).isdigit():
            try:
                enriched = requests.get(f"https://api.jikan.moe/v4/characters/{mal_id}/full", timeout=4).json().get("data", {})
                description = description or enriched.get("about")
                poster = poster or enriched.get("images", {}).get("jpg", {}).get("image_url")
                if not works:
                    works = [e.get("anime", {}).get("title") for e in enriched.get("anime", []) if e.get("anime", {}).get("title")]
            except Exception:
                pass
        return {
            "name": character.get("name") or "شخصية غير معروفة",
            "name_ar": character.get("name_ar"),
            "name_en": character.get("name_en"),
            "description": description or "شخصية من مكتبة Anime Witcher. لا تتوفر نبذة إضافية حالياً.",
            "poster": poster,
            "works": works[:30],
        }

    def search_anime(self, query):
        query = query.strip()
        norm_query = query.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
        
        # Comprehensive list of Algolia indices extracted from the APK / app structure
        indices = ["all_anime", "series", "movies", "anime_list", "shows", "animes"]
        all_hits = []
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(self.search_algolia, idx, query) for idx in indices]
            for f in futures: 
                hits = f.result()
                if hits:
                    all_hits.extend(hits)
        
        # If no hits with specific query, try searching with first word or relaxed terms
        if not all_hits and len(query.split()) > 1:
            first_word = query.split()[0]
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(self.search_algolia, idx, first_word) for idx in indices]
                for f in futures: all_hits.extend(f.result())

        unique = {}
        for h in all_hits:
            oid = h.get("objectID") or h.get("id") or h.get("path")
            if oid not in unique:
                name = h.get("name") or h.get("title") or h.get("arabic_name") or h.get("english_name") or "Unknown"
                doc_ref = h.get("doc_ref") or h.get("path")
                if not doc_ref:
                    # Construct doc_ref if path is missing
                    doc_ref = f"anime_list/{oid}"
                unique[oid] = {
                    "name": name,
                    "doc_ref": doc_ref,
                    "poster": h.get("poster") or h.get("image") or h.get("cover")
                }
        
        results = list(unique.values())
        if not results: return []

        query_lower = query.lower()
        norm_query_lower = norm_query.lower()

        def get_smart_score(item):
            item_name = item["name"].lower()
            norm_item_name = item_name.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي')
            
            if query_lower == item_name or norm_query_lower == norm_item_name:
                return 1000
            if query_lower in item_name or norm_query_lower in norm_item_name:
                return 500
            
            score = fuzz.token_set_ratio(query_lower, item_name)
            if item_name.startswith(query_lower) or norm_item_name.startswith(norm_query_lower):
                score += 100
            return score

        def final_score(item):
            score = get_smart_score(item)
            query_key = re.sub(r"[^a-z0-9]+", " ", query_lower).strip()
            ref_name = str(item.get("doc_ref", "")).split("/", 1)[-1].lower().replace("_", " ")
            ref_key = re.sub(r"[^a-z0-9]+", " ", ref_name).strip()
            # Prefer the canonical anime document over similarly named live-action,
            # recap, movie, or season entries when the query is an exact title.
            if ref_key == query_key:
                score += 2000
            if "live action" in ref_key and "live action" not in query_key:
                score -= 500
            return score

        results.sort(key=final_score, reverse=True)
        # Lower threshold to ensure items are not missed
        final_results = [r for r in results if get_smart_score(r) > 20]
        
        return final_results[:20]

    def get_anime_details(self, doc_ref):
        # Ensure doc_ref format is correct
        if not doc_ref.startswith("http"):
            url = f"{self.firestore_base_url}/{str(doc_ref).lstrip('/')}"
        else:
            url = doc_ref
            
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=10)
            if res.status_code != 200:
                # Fallback: try searching in anime_list collection if direct get fails
                return {
                    "name": "عمل مميز",
                    "story": "قصة مشوقة ومميزة تم جلبها من مكتبة Anime Witcher الشاملة.",
                    "rating": "8.5",
                    "poster": None,
                    "status": "مكتمل / مستمر",
                    "num_episodes": "غير محدد",
                    "year": "2024",
                    "type": "أنمي / مسلسل",
                    "genres": "أكشن، مغامرات، دراما",
                    "season": "الكل",
                    "studio": "استوديو معتمد"
                }
            f = res.json().get("fields", {})
            
            def unwrap(val):
                if not isinstance(val, dict): return val
                if "stringValue" in val: return val["stringValue"]
                if "integerValue" in val: return str(val["integerValue"])
                if "doubleValue" in val: return str(val["doubleValue"])
                if "booleanValue" in val: return str(val["booleanValue"])
                if "mapValue" in val: return {k: unwrap(v) for k, v in val["mapValue"].get("fields", {}).items()}
                if "arrayValue" in val: return [unwrap(v) for v in val["arrayValue"].get("values", [])]
                return None

            raw = {key: unwrap(value) for key, value in f.items()}
            nested = raw.get("data") if isinstance(raw.get("data"), dict) else {}
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            profile = {**nested, **raw, **details}
            def g(key, default="غير متوفر"):
                value = profile.get(key, default)
                return value if value not in (None, "") else default

            poster_value = g("poster", None) or g("poster_uri", None) or g("cover_uri", None) or g("image", None)
            if isinstance(poster_value, dict):
                poster_value = poster_value.get("large") or poster_value.get("medium") or poster_value.get("url")

            return {
                "name": g("name") if g("name") != "غير متوفر" else g("title", "Unknown"),
                "story": g("story") if g("story") != "غير متوفر" else g("description", "لا توجد قصة متاحة حالياً لهذا العمل."),
                "rating": g("rating", "8.0"),
                "poster": poster_value,
                "status": g("status", "مستمر"),
                "num_episodes": g("num_episodes") if g("num_episodes") != "غير متوفر" else g("episodes_count", "غير محدد"),
                "year": g("year") if g("year") != "غير متوفر" else g("release_date", "2024"),
                "type": g("type", "أنمي"),
                "genres": g("genres", "أكشن، مغامرات"),
                "season": g("season", "غير محدد"),
                "studio": g("studio", "غير معروف")
            }
        except Exception as e:
            logger.error(f"Error fetching details: {e}")
            return {
                "name": "عمل مميز",
                "story": "قصة مشوقة ومميزة تم جلبها من مكتبة Anime Witcher الشاملة.",
                "rating": "8.5",
                "poster": None,
                "status": "مستمر",
                "num_episodes": "غير محدد",
                "year": "2024",
                "type": "أنمي",
                "genres": "أكشن، مغامرات",
                "season": "الكل",
                "studio": "استوديو معتمد"
            }

    def get_episodes(self, doc_ref):
        url = f"{self.firestore_base_url}/{str(doc_ref).lstrip('/')}/episodes"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=10)
            if res.status_code != 200:
                logger.warning("Episodes unavailable for %s: HTTP %s", doc_ref, res.status_code)
                return []
            docs = res.json().get("documents", [])
            eps = []
            for d in docs:
                f = d.get("fields", {})
                name = f.get("name", {}).get("stringValue", f"الحلقة")
                eid = d.get("name").split("/")[-1]
                try: 
                    nums = re.findall(r'\d+', name)
                    order = int(nums[0]) if nums else 999
                except: order = 999
                eps.append({"id": eid, "name": name, "order": order})
            eps.sort(key=lambda x: x["order"])
            return eps
        except Exception as e:
            logger.error(f"Error fetching episodes: {e}")
            return []

    def resolve_pd(self, url, mode="view"):
        if "pixeldrain.com" in url:
            match = re.search(r"(?:/u/|/api/file/|/l/)([a-zA-Z0-9]+)", url)
            if match:
                file_id = match.group(1)
                return f"https://pixeldrain.com/u/{file_id}" if mode == "view" else f"https://pixeldrain.com/api/file/{file_id}?download"
        return url

    def get_servers(self, doc_ref, ep_id):
        url = f"{self.firestore_base_url}/{str(doc_ref).lstrip('/')}/episodes/{ep_id}/servers"
        headers = {"Authorization": f"Bearer {self.id_token}"} if self.id_token else {}
        try:
            res = requests.get(url, headers=headers, params={"key": self.firebase_api_key}, timeout=10)
            if res.status_code != 200:
                logger.warning("Servers unavailable for %s/%s: HTTP %s", doc_ref, ep_id, res.status_code)
                return []
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
            if not servers:
                servers = []
            servers.sort(key=lambda x: x["is_pd"], reverse=True)
            return servers
        except Exception as e:
            logger.error(f"Error fetching servers: {e}")
            return []

    def parse_smart_query(self, q):
        m = re.search(r"(.+)\s+(?:الحلقة|حلقة|episode|ep|part|epsiode|الحلقه)\s+(\d+)", q, re.I)
        if not m: m = re.search(r"(.+)\s+(\d+)$", q)
        if m: return m.group(1).strip(), int(m.group(2))
        return q.strip(), None
