"""
Simple FastAPI/Flask-style HTTP API wrapper for the CineSubz scraper.

Run:
    pip install fastapi uvicorn
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    GET /search?q=...&page=1
    GET /movie?url=...
    GET /resolve?url=...         # movie page + resolve all links
    GET /latest
    GET /trending
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from scraper import CineSubz

app = FastAPI(title="CineSubz Scraper API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

cs = CineSubz(use_browser=False)


@app.get("/")
def root():
    return {"name": "CineSubz API", "status": "ok", "base": cs.base}


@app.get("/search")
def search(q: str = Query(...), page: int = 1):
    try:
        return {"query": q, "page": page, "results": cs.search(q, page=page)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/latest")
def latest():
    return cs.homepage()


@app.get("/movie")
def movie(url: str = Query(...)):
    try:
        return cs.get_movie(url)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/resolve")
def resolve(url: str = Query(...)):
    try:
        d = cs.get_movie(url)
        d["resolved"] = cs.resolve_download_links(d["download_sections"])
        return d
    except Exception as e:
        raise HTTPException(500, str(e))
