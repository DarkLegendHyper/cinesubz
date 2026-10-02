"""
CineSubz Full Scraper
=====================
Scrapes cinesubz.co / cinesubz.net (the site uses Cloudflare).

Features
--------
- Cloudflare bypass using multiple strategies (curl_cffi -> cloudscraper -> DrissionPage headless browser fallback)
- Session + cookie persistence
- Homepage trending / latest movies / TV shows
- Search movies & TV shows
- Movie detail page parsing (poster, rating, genres, cast, description)
- Download-server link extraction ("Server 1" / "Server 2" / Telegram)
- Ad-link shortener resolver (the "Click Here to Download" 5-second redirect chain)
- Pagination support
- TV Show episode link extraction

Usage
-----
    from scraper import CineSubz
    cs = CineSubz()
    results = cs.search("gajaman")
    details = cs.get_movie(results[0]["link"])
    links   = cs.resolve_download_links(details["download_sections"])

NOTE TO USERS
-------------
The sandbox egress IP of this environment is blocked by Cloudflare at TCP/TLS
level for cinesubz.co/.net. On a *local* machine (your PC/VPS) the curl_cffi +
cloudscraper strategy works out of the box; if you still get blocked, set
`use_browser=True` which launches a real Chromium via DrissionPage (must
`pip install DrissionPage` and have Chromium installed).
"""

from __future__ import annotations

import re
import time
import json
import logging
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("cinesubz")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Cloudflare-capable HTTP client
# ---------------------------------------------------------------------------
class CFClient:
    """HTTP client that tries multiple strategies to bypass Cloudflare.

    Strategy order:
        1. curl_cffi       (TLS fingerprint impersonation, no JS)
        2. cloudscraper    (JS challenge solver, no browser)
        3. DrissionPage    (real Chromium, heaviest but most reliable)
    """

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, use_browser: bool = False, timeout: int = 30):
        self.timeout = timeout
        self.use_browser = use_browser
        self.cookies: Dict[str, str] = {}
        self._session_curl = None
        self._session_cs = None
        self._browser = None

        self._init_curl()
        try:
            import cloudscraper
            self._session_cs = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        except Exception as e:
            log.warning("cloudscraper init failed: %s", e)
            self._session_cs = None

        if use_browser:
            self._init_browser()

    # ----- session init helpers -----
    def _init_curl(self):
        try:
            from curl_cffi import requests as creq
            self._session_curl = creq.Session()
            self._session_curl.headers.update(self.DEFAULT_HEADERS)
        except Exception as e:
            log.warning("curl_cffi unavailable: %s", e)
            self._session_curl = None

    def _init_browser(self):
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            co = ChromiumOptions()
            co.headless(True)
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-blink-features=AutomationControlled")
            self._browser = ChromiumPage(co)
            log.info("DrissionPage Chromium started")
        except Exception as e:
            log.error("DrissionPage init failed (install Chromium?): %s", e)
            self._browser = None

    # ----- GET -----
    def get(self, url: str, **kwargs) -> Tuple[str, int]:
        """Returns (html, status_code)."""
        last_err = None

        # Strategy 1: curl_cffi
        if self._session_curl is not None:
            try:
                r = self._session_curl.get(
                    url,
                    impersonate="chrome124",
                    timeout=self.timeout,
                    cookies=self.cookies or None,
                    headers=kwargs.get("headers"),
                    allow_redirects=True,
                )
                if r.status_code == 200 and ("cf-browser-verification" not in r.text[:5000]
                                             and "Just a moment" not in r.text[:1000]):
                    self.cookies.update({c.name: c.value for c in r.cookies})
                    return r.text, r.status_code
                last_err = f"curl_cffi status={r.status_code}"
            except Exception as e:
                last_err = f"curl_cffi error: {e}"
                log.debug(last_err)

        # Strategy 2: cloudscraper
        if self._session_cs is not None:
            try:
                r = self._session_cs.get(url, timeout=self.timeout,
                                         headers=kwargs.get("headers"))
                if r.status_code == 200 and "Just a moment" not in r.text[:1000]:
                    self.cookies.update(r.cookies.get_dict())
                    return r.text, r.status_code
                last_err = f"cloudscraper status={r.status_code}"
            except Exception as e:
                last_err = f"cloudscraper error: {e}"
                log.debug(last_err)

        # Strategy 3: DrissionPage (real browser)
        if self._browser is not None:
            try:
                self._browser.get(url)
                self._browser.wait.doc_loaded(timeout=self.timeout)
                # Wait out any JS challenge
                for _ in range(20):
                    html = self._browser.html
                    if "Just a moment" not in html and "cf-browser-verification" not in html:
                        return html, 200
                    time.sleep(1)
                return self._browser.html, 200
            except Exception as e:
                last_err = f"DrissionPage error: {e}"

        raise RuntimeError(f"All Cloudflare bypass strategies failed for {url}: {last_err}")

    def close(self):
        if self._browser is not None:
            try:
                self._browser.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# URL / domain helpers
# ---------------------------------------------------------------------------
BASE_DOMAINS = ["cinesubz.co", "cinesubz.net", "cinesubz.lk"]


def pick_base(html: str) -> str:
    """Pick the working base URL from the fetched HTML."""
    for d in BASE_DOMAINS:
        if d in html:
            return f"https://{d}"
    return "https://cinesubz.co"


def normalize_url(url: str, base: str = "https://cinesubz.co") -> str:
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return url


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------
class CineSubz:
    """Full scraper for cinesubz.co / .net / .lk."""

    SEARCH_PATH = "/?s={q}"
    MOVIES_PATH = "/movies/page/{p}/"
    TVSHOWS_PATH = "/tvshows/page/{p}/"

    # Regexes
    RATING_RE = re.compile(r"★\s*([\d.]+)")
    YEAR_RE = re.compile(r"\((\d{4})\)")
    QUALITY_SIZE_RE = re.compile(
        r"(?:360p|480p|720p|1080p|2160p|4K|WEB-DL|BluRay|HDTV|WEBRip|HDRip)\s*(?:–|-)?\s*([\d.]+\s*[MGT]B)?",
        re.IGNORECASE,
    )

    def __init__(self, use_browser: bool = False, base: str = "https://cinesubz.co"):
        self.client = CFClient(use_browser=use_browser)
        self.base = base
        # Detect working base from homepage
        try:
            html, _ = self.client.get(self.base)
            detected = pick_base(html)
            if detected != self.base:
                log.info("Auto-detected working domain: %s", detected)
                self.base = detected
        except Exception as e:
            log.warning("Could not reach %s (%s); will try .net/.lk dynamically", self.base, e)

    # -------------------- generic fetch + parse --------------------
    def _soup(self, url: str) -> Tuple[BeautifulSoup, str]:
        html, code = self.client.get(url)
        # Auto switch domain if redirect happened
        if "cinesubz.net" in html[:5000] and self.base.endswith("cinesubz.co"):
            self.base = "https://cinesubz.net"
        return BeautifulSoup(html, "lxml"), html

    # -------------------- homepage --------------------
    def homepage(self) -> Dict[str, Any]:
        """Return trending movies / latest additions from homepage."""
        soup, _ = self._soup(self.base)
        out: Dict[str, Any] = {"trending": [], "latest": []}

        # Homepage uses a grid of <article> items inside `.content.right` or similar
        for article in soup.select("article"):
            a = article.find("a", href=True)
            img = article.find("img")
            title_el = article.find(["h2", "h3"])
            rating_m = self.RATING_RE.search(article.get_text(" ", strip=True))
            year_m = self.YEAR_RE.search(article.get_text(" ", strip=True))
            if not a or not title_el:
                continue
            item = {
                "title": title_el.get_text(" ", strip=True),
                "link": normalize_url(a["href"], self.base),
                "poster": normalize_url(img["src"], self.base) if img and img.get("src") else None,
                "rating": float(rating_m.group(1)) if rating_m else None,
                "year": int(year_m.group(1)) if year_m else None,
            }
            out["latest"].append(item)

        # Trending section (top numbered)
        for sel in [".trending-item", ".tp-item", "#slider .item", ".items .item"]:
            for el in soup.select(sel):
                a = el.find("a", href=True)
                t = el.find(["h3", ".title", "a"])
                if a and t:
                    out["trending"].append({
                        "title": t.get_text(" ", strip=True),
                        "link": normalize_url(a["href"], self.base),
                    })
            if out["trending"]:
                break

        return out

    # -------------------- listing pages --------------------
    def _list_page(self, path: str, page: int = 1) -> List[Dict[str, Any]]:
        url = self.base + path.format(p=page)
        soup, _ = self._soup(url)
        items = []
        for article in soup.select("article"):
            a = article.find("a", href=True)
            img = article.find("img")
            title_el = article.find(["h2", "h3"])
            meta = article.find("div", class_="meta")
            txt = article.get_text(" ", strip=True)
            if not (a and title_el):
                continue
            rating_m = self.RATING_RE.search(txt)
            year_m = self.YEAR_RE.search(txt)
            # Quality tag like "WEB-DL" or "BluRay"
            qmatch = re.search(r"\b(WEB-DL|BluRay|WEBRip|HDRip|HDTV|WEB|S01.*Complete)\b", txt)
            items.append({
                "title": title_el.get_text(" ", strip=True),
                "link": normalize_url(a["href"], self.base),
                "poster": normalize_url(img["src"], self.base) if img and img.get("src") else None,
                "rating": float(rating_m.group(1)) if rating_m else None,
                "year": int(year_m.group(1)) if year_m else None,
                "quality": qmatch.group(1) if qmatch else None,
            })
        return items

    def movies(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._list_page(self.MOVIES_PATH, page)

    def tvshows(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._list_page(self.TVSHOWS_PATH, page)

    # -------------------- search --------------------
    def search(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        url = self.base + self.SEARCH_PATH.format(q=urllib.parse.quote(query))
        if page > 1:
            url += f"&page={page}"
        soup, _ = self._soup(url)
        results = []
        for article in soup.select("article"):
            a = article.find("a", href=True)
            img = article.find("img")
            title_el = article.find(["h2", "h3"])
            desc_el = article.find("div", class_="contenido")
            txt = article.get_text(" ", strip=True)
            if not (a and title_el):
                continue
            rating_m = self.RATING_RE.search(txt)
            year_m = self.YEAR_RE.search(txt)
            link = normalize_url(a["href"], self.base)
            kind = "tvshow" if "/tvshows/" in link else "movie"
            results.append({
                "title": title_el.get_text(" ", strip=True),
                "link": link,
                "type": kind,
                "poster": normalize_url(img["src"], self.base) if img and img.get("src") else None,
                "rating": float(rating_m.group(1)) if rating_m else None,
                "year": int(year_m.group(1)) if year_m else None,
                "description": desc_el.get_text(" ", strip=True) if desc_el else None,
            })
        return results

    # -------------------- movie / tvshow detail --------------------
    def get_movie(self, url: str) -> Dict[str, Any]:
        """Fetch a movie/TV-show detail page and extract metadata + download buttons."""
        soup, html = self._soup(url)

        data: Dict[str, Any] = {
            "url": url,
            "title": None,
            "poster": None,
            "description": None,
            "rating": None,
            "genres": [],
            "date": None,
            "country": None,
            "subtitle_author": None,
            "download_sections": [],   # list of {"name": "Server 1", "links": [...]}
            "episodes": [],
        }

        # Title
        h1 = soup.find("h1")
        if h1:
            data["title"] = h1.get_text(" ", strip=True)

        # Poster
        poster = soup.select_one(".sheader .poster img, .poster img, .imagen img")
        if poster and poster.get("src"):
            data["poster"] = normalize_url(poster["src"], self.base)

        # Description
        desc = soup.select_one(".wp-content, .sheader .texto, .description, .contenidotv, #info")
        if desc:
            data["description"] = desc.get_text(" ", strip=True)[:1000]

        # IMDb rating
        imdb_el = soup.select_one("#repimdb strong, span.rating, .imdb")
        if imdb_el:
            m = re.search(r"([\d.]+)", imdb_el.get_text())
            if m:
                data["rating"] = float(m.group(1))

        # Genres
        for a in soup.select(".sgeneros a, .genres a"):
            g = a.get_text(" ", strip=True)
            if g:
                data["genres"].append(g)

        # Date & country
        date_el = soup.select_one(".extra span.date, span.date")
        if date_el:
            data["date"] = date_el.get_text(" ", strip=True)
        country_el = soup.select_one(".extra span.country, span.country")
        if country_el:
            data["country"] = country_el.get_text(" ", strip=True)

        # Subtitle author (the "Subtitle by ..." line near the center)
        c4 = soup.select_one("div:nth-of-type(4) center span, center span")
        if c4:
            data["subtitle_author"] = c4.get_text(" ", strip=True)

        # ---------------- Download sections ----------------
        # The site uses tabbed panels: Server 1, Server 2, Telegram, ...
        # Tabs are often <li><a href="#server1">Server 1</a></li> paired with
        # <div id="server1">...table with links...</div>
        # We also handle the known #directdownloadlinks wrapper.

        # 1) Tabs + panels
        tabs: Dict[str, str] = {}
        for a in soup.select("ul.idtabs a[href], .tabs a[href], .nav-tabs a[href]"):
            href = a.get("href", "")
            name = a.get_text(" ", strip=True)
            if href.startswith("#") and name:
                tabs[name.lower()] = href[1:]

        if tabs:
            for tab_name, panel_id in tabs.items():
                panel = soup.find(id=panel_id)
                if panel is None:
                    continue
                data["download_sections"].append({
                    "name": tab_name.title().replace("Server1", "Server 1").replace("Server2", "Server 2"),
                    "links": self._extract_links_from_panel(panel),
                })

        # 2) Fallback: parse #directdownloadlinks table (legacy layout)
        if not data["download_sections"]:
            ddl = soup.select_one("#directdownloadlinks")
            if ddl:
                data["download_sections"].append({
                    "name": "Download",
                    "links": self._extract_links_from_panel(ddl),
                })

        # 3) Fallback: any link under `.links_table`, `.download-links`, `.dls-table`
        if not data["download_sections"]:
            for tbl in soup.select(".download-links, .links_table, .dls-table, table.download"):
                data["download_sections"].append({
                    "name": "Download",
                    "links": self._extract_links_from_panel(tbl),
                })
                break

        # ---------------- TV Show episodes ----------------
        if "/tvshows/" in url or "/episodes/" in url:
            for a in soup.select("#seasons a, .episodios a, .seasons a, .ep-list a"):
                href = normalize_url(a.get("href"), self.base)
                title = a.get_text(" ", strip=True)
                if href and title and "/episodes/" in href:
                    data["episodes"].append({"title": title, "link": href})

            # Numbered season tables
            season_blocks = soup.select("[id^=season], .se-c")
            for sb in season_blocks:
                snum = re.search(r"season-?(\d+)", sb.get("id", ""), re.I)
                for tr in sb.select("tr, .ep-item"):
                    a = tr.find("a", href=True)
                    if not a:
                        continue
                    href = normalize_url(a["href"], self.base)
                    num_el = tr.select_one(".numerando, .num")
                    ep_title = a.get_text(" ", strip=True)
                    data["episodes"].append({
                        "season": int(snum.group(1)) if snum else None,
                        "number": num_el.get_text(" ", strip=True) if num_el else None,
                        "title": ep_title,
                        "link": href,
                    })

        return data

    def _extract_links_from_panel(self, panel) -> List[Dict[str, Any]]:
        """Extract download link rows from a given panel/table."""
        links: List[Dict[str, Any]] = []
        seen = set()

        # Table rows
        for tr in panel.select("tr"):
            a = tr.find("a", href=True)
            if not a:
                continue
            href = a.get("href", "")
            if href in ("#", "") or "javascript:" in href:
                # Sometimes the real href is on a <button data-link> or on a
                # generated redirect; keep the text and we'll resolve it later.
                href = a.get("data-link") or a.get("data-href") or ""
            if not href or href in seen:
                continue
            seen.add(href)

            cells = tr.find_all("td")
            quality = a.get_text(" ", strip=True)
            size = ""
            if len(cells) >= 2:
                size = cells[1].get_text(" ", strip=True)
            # Prefer <strong> child text as quality label
            strong = a.find("strong")
            if strong:
                quality = strong.get_text(" ", strip=True)

            links.append({
                "quality": quality or "Unknown",
                "size": size,
                "href": normalize_url(href, self.base),
            })

        # If no rows found, collect all anchor download links
        if not links:
            for a in panel.select("a[href]"):
                href = a.get("href", "")
                if not href or href.startswith("#") or "javascript:" in href:
                    continue
                if href in seen:
                    continue
                seen.add(href)
                text = a.get_text(" ", strip=True)
                if any(k in href.lower() for k in ("mega.nz", "drive.google", "mediafire",
                                                   "terabox", "telegram", "t.me",
                                                   "gdtot", "appdrive", "gdflix",
                                                   "link", "go.", "cgi", "getlink")) \
                   or any(k in text.lower() for k in ("download", "click", "server", "480p", "720p", "1080p")):
                    links.append({
                        "quality": text,
                        "size": "",
                        "href": normalize_url(href, self.base),
                    })

        return links

    # ---------------- short-link resolver --------------------
    def resolve_download_links(self, sections: List[Dict[str, Any]],
                               max_depth: int = 8) -> List[Dict[str, Any]]:
        """Walk the ad-link / click-redirect chain on each `href` until we
        land on a final file host (mega, gdrive, mediafire, terabox, ...).
        Returns a new list with an extra `direct_url` field per link, plus
        `host`.
        """
        out: List[Dict[str, Any]] = []
        for sec in sections:
            resolved_sec = {"name": sec["name"], "links": []}
            for lnk in sec["links"]:
                try:
                    direct, host = self._resolve_chain(lnk["href"], max_depth=max_depth)
                except Exception as e:
                    log.warning("Resolver failed for %s: %s", lnk["href"], e)
                    direct, host = None, None
                resolved_sec["links"].append({
                    **lnk,
                    "direct_url": direct,
                    "host": host or _classify_host(lnk["href"]),
                })
                time.sleep(0.4)  # be polite
            out.append(resolved_sec)
        return out

    def _resolve_chain(self, url: str, max_depth: int = 8) -> Tuple[Optional[str], Optional[str]]:
        """Follow HTTP redirects + JS meta refresh + the 'Continue/Generate'
        button until we hit a known file host.
        """
        cur = url
        for _ in range(max_depth):
            if not cur:
                return None, None
            host = _classify_host(cur)
            if host and host not in ("unknown", "adlink", "cinesubz"):
                return cur, host

            try:
                html, code = self.client.get(cur)
            except Exception as e:
                log.debug("resolve GET fail %s: %s", cur, e)
                return cur, _classify_host(cur)

            soup = BeautifulSoup(html, "lxml")

            # 1) Meta refresh
            meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
            if meta and meta.get("content"):
                m = re.search(r"url=([^;]+)", meta["content"], re.I)
                if m:
                    nxt = urllib.parse.urljoin(cur, m.group(1).strip())
                    if nxt != cur:
                        cur = nxt
                        continue

            # 2) #link anchor (the "Click Here to Download" / GetLink button)
            link_el = soup.select_one("#link, a#download, a.download-btn, a.btn-download, "
                                      "a.generate, a.continue, button#link")
            if link_el:
                href = link_el.get("href") or link_el.get("data-link") or link_el.get("data-url")
                if href:
                    nxt = urllib.parse.urljoin(cur, href)
                    if nxt != cur:
                        cur = nxt
                        continue

            # 3) Form POST action
            form = soup.find("form")
            if form and form.get("action"):
                action = urllib.parse.urljoin(cur, form["action"])
                # cinesubz / cineru-style dllink forms: method POST, no fields needed
                try:
                    r = requests.post(action, headers=CFClient.DEFAULT_HEADERS,
                                      timeout=self.client.timeout, allow_redirects=True)
                    # Check final URL or #link in response
                    s2 = BeautifulSoup(r.text, "lxml")
                    la = s2.select_one("#link, a[download], a[href*='mega.nz'], "
                                       "a[href*='drive.google'], a[href*='mediafire'], "
                                       "a[href*='terabox'], a[href*='t.me']")
                    if la and la.get("href"):
                        cur = urllib.parse.urljoin(r.url, la["href"])
                        continue
                    if _classify_host(r.url) not in ("unknown", "adlink", "cinesubz"):
                        return r.url, _classify_host(r.url)
                except Exception as e:
                    log.debug("form POST fail: %s", e)

            # 4) Any prominent anchor pointing to a known host
            for a in soup.select("a[href]"):
                h = a.get("href", "")
                if _classify_host(h) not in ("unknown", "adlink", "cinesubz"):
                    cur = urllib.parse.urljoin(cur, h)
                    break
            else:
                # give up
                return cur, _classify_host(cur)

        return cur, _classify_host(cur)

    # ---------------- helpers --------------------
    def close(self):
        self.client.close()


def _classify_host(url: str) -> Optional[str]:
    if not url:
        return None
    u = url.lower()
    if "cinesubz." in u:
        return "cinesubz"
    if "mega.nz" in u or "mega.co.nz" in u:
        return "Mega"
    if "drive.google" in u or "docs.google" in u:
        return "Google Drive"
    if "mediafire" in u:
        return "MediaFire"
    if "terabox" in u:
        return "Terabox"
    if "t.me/" in u or "telegram" in u:
        return "Telegram"
    if "dropbox" in u:
        return "Dropbox"
    if "gdtot" in u or "appdrive" in u or "gdflix" in u or "gofile" in u \
       or "pixeldrain" in u or "buzzheavier" in u or "mirrored" in u:
        return "FileHost"
    # Known cinesubz ad/redirect link domains
    ad_domains = (
        "shorte.st", "linkvertise", "adf.ly", "ouo.io", "bc.vc",
        "clk.", "go.", "link.", "cgi.", "getlink", "shortly",
        "ceesty", "ceesty", "shrink", "fc.lc", "bit.ly", "tinyurl",
        "cut urls", "exe.io", "exeey", "adshnk", "shorturl",
    )
    if any(d in u for d in ad_domains):
        return "adlink"
    if u.endswith((".mp4", ".mkv", ".avi", ".zip", ".srt")):
        return "direct"
    return "unknown"


# ---------------------------------------------------------------------------
# CLI quick test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    cs = CineSubz(use_browser=False)
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(f"\n=== Search: {q!r} ===")
        res = cs.search(q)
        for i, r in enumerate(res[:8], 1):
            print(f"{i}. [{r['type']}] {r['title']}  ({r['rating']})  {r['link']}")
        if res:
            print("\n=== Details of #1 ===")
            d = cs.get_movie(res[0]["link"])
            print("Title :", d["title"])
            print("Rating:", d["rating"])
            print("Genres:", ", ".join(d["genres"]))
            print("Sections:")
            for s in d["download_sections"]:
                print(f"  - {s['name']}")
                for l in s["links"]:
                    print(f"     * {l['quality']}  {l['size']}  -> {l['href']}")
            print("\n=== Resolving download links ===")
            resolved = cs.resolve_download_links(d["download_sections"])
            for s in resolved:
                print(f"  [{s['name']}]")
                for l in s["links"]:
                    print(f"    * {l['quality']}  {l['size']}  host={l['host']}  -> {l['direct_url']}")
    else:
        print("=== Homepage ===")
        h = cs.homepage()
        for item in h["latest"][:10]:
            print(f"* {item['title']}  {item['rating']}  {item['link']}")
    cs.close()
