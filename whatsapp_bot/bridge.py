#!/usr/bin/env python3
"""
Sub-process bridge: takes a JSON command on stdin / argv, prints JSON on stdout.
Used by whatsapp_bot/index.js so the WhatsApp (Node) side can reuse the Python
scraper with full Cloudflare-bypass support.

Usage:
    python3 bridge.py search "gajaman"
    python3 bridge.py movie  "https://cinesubz.co/movies/xxx/"
    python3 bridge.py dl     "https://cinesubz.co/movies/xxx/"
    python3 bridge.py latest
    python3 bridge.py trending
    python3 bridge.py movies [page]
    python3 bridge.py tvshows [page]

Output is a single JSON object to stdout. Errors are printed as {"error": "..."}.
"""
import sys
import os
import json
import traceback

# Make sure we can import scraper from the parent directory when called as
# `python3 whatsapp_bot/bridge.py ...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import CineSubz


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: bridge.py <cmd> [args...]"}))
        return

    use_browser = os.environ.get("USE_BROWSER", "0") == "1"
    cs = CineSubz(use_browser=use_browser)
    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    try:
        if cmd == "search":
            q = " ".join(args)
            res = cs.search(q)
            print(json.dumps({"ok": True, "results": res}, ensure_ascii=False))

        elif cmd == "latest":
            res = cs.homepage()
            print(json.dumps({"ok": True, **res}, ensure_ascii=False))

        elif cmd == "trending":
            h = cs.homepage()
            res = h.get("trending") or h.get("latest", [])[:10]
            print(json.dumps({"ok": True, "results": res}, ensure_ascii=False))

        elif cmd == "movie":
            url = args[0]
            res = cs.get_movie(url)
            print(json.dumps({"ok": True, "result": res}, ensure_ascii=False))

        elif cmd == "link":
            # resolve a single short/ad link to its final direct URL
            url = args[0]
            direct, host = cs._resolve_chain(url)
            print(json.dumps({"ok": True, "direct": direct, "host": host},
                             ensure_ascii=False))

        elif cmd == "dl":
            url = args[0]
            d = cs.get_movie(url)
            d["resolved"] = cs.resolve_download_links(d["download_sections"])
            print(json.dumps({"ok": True, "result": d}, ensure_ascii=False))

        elif cmd == "movies":
            page = int(args[0]) if args else 1
            res = cs.movies(page=page)
            print(json.dumps({"ok": True, "page": page, "results": res}, ensure_ascii=False))

        elif cmd == "tvshows":
            page = int(args[0]) if args else 1
            res = cs.tvshows(page=page)
            print(json.dumps({"ok": True, "page": page, "results": res}, ensure_ascii=False))

        else:
            print(json.dumps({"ok": False, "error": f"unknown command: {cmd}"}))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc(),
        }, ensure_ascii=False))
    finally:
        cs.close()


if __name__ == "__main__":
    main()
