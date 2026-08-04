from fastapi import FastAPI, Query
from data_manager import DataManager
import uvicorn

app = FastAPI(title="Anime Witcher API Service")
DATA = DataManager()

@app.get("/")
async def root():
    return {"message": "Anime Witcher API is running!"}

@app.get("/get_links")
async def get_links(query: str = Query(..., description="Anime name and episode number, e.g., 'Sally 1'")):
    """
    Search for an anime and episode, returning ONLY PD (Direct) links.
    """
    anime_name, ep_num = DATA.parse_smart_query(query)
    
    results = DATA.search_anime(anime_name)
    if not results:
        return {"status": "error", "message": "Anime not found"}

    if ep_num is None:
        return {"status": "error", "message": "Please specify an episode number, e.g., 'Naruto 5'"}

    # Take the best match
    target_anime = results[0]
    doc_ref = target_anime['doc_ref']
    episodes = DATA.get_episodes(doc_ref)
    
    target_ep = None
    for ep in episodes:
        if ep['order'] == ep_num:
            target_ep = ep
            break
    
    if not target_ep:
        return {"status": "error", "message": f"Episode {ep_num} not found for {target_anime['name']}"}

    servers = DATA.get_servers(doc_ref, target_ep['id'])
    
    # Filter for PD links only as requested
    pd_only = [s for s in servers if "💎 سيرفر PD" in s['name']]
    
    return {
        "status": "success",
        "anime": target_anime['name'],
        "episode": ep_num,
        "links": pd_only
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
