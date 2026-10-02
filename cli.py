#!/usr/bin/env python3
"""
CineSubz CLI
------------
Command-line interface for the CineSubz scraper.

Usage:
    python cli.py search "movie name"
    python cli.py movie https://cinesubz.co/movies/xxx/
    python cli.py dl https://cinesubz.co/movies/xxx/
    python cli.py latest
    python cli.py trending
    python cli.py movies [page]
    python cli.py tvshows [page]

Add --browser flag to launch headless Chromium (strongest Cloudflare bypass,
requires Chromium/Chrome to be installed).
"""

import argparse
import sys
import json
from scraper import CineSubz


def _print_item(i, it):
    marker = "🎬" if it.get("type", "movie") == "movie" else "📺"
    rating = f" ⭐{it['rating']}" if it.get("rating") else ""
    year = f" ({it['year']})" if it.get("year") else ""
    print(f"{i:2d}. {marker} {it['title']}{year}{rating}")
    if it.get("link"):
        print(f"     🔗 {it['link']}")
    if it.get("poster"):
        print(f"     🖼 {it['poster']}")


def cmd_search(args, cs):
    res = cs.search(args.query)
    print(f"\n🔎 Results for '{args.query}': {len(res)} hit(s)\n")
    for i, r in enumerate(res, 1):
        _print_item(i, r)


def cmd_movie(args, cs):
    d = cs.get_movie(args.url)
    print("\n🎬", d["title"])
    print("-" * 60)
    if d.get("rating"):
        print("Rating :", d["rating"])
    if d.get("genres"):
        print("Genres :", ", ".join(d["genres"]))
    if d.get("date"):
        print("Date   :", d["date"])
    if d.get("country"):
        print("Country:", d["country"])
    if d.get("description"):
        print("\n" + d["description"][:500])
    print("\n📥 Download sections:")
    for s in d["download_sections"]:
        print(f"\n  ── {s['name']} ──")
        for l in s["links"]:
            size = f"  [{l['size']}]" if l.get("size") else ""
            print(f"   • {l['quality']}{size}")
            print(f"     -> {l['href']}")
    if d.get("episodes"):
        print(f"\n📺 Episodes: {len(d['episodes'])}")
        for ep in d["episodes"][:30]:
            print(f"   • {ep['title']}  {ep['link']}")
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(d, indent=2, ensure_ascii=False))


def cmd_dl(args, cs):
    d = cs.get_movie(args.url)
    print(f"\n🎬 {d['title']}")
    print("Resolving download links...\n")
    sections = cs.resolve_download_links(d["download_sections"])
    for s in sections:
        print(f"── {s['name']} ──")
        for l in s["links"]:
            host = f"[{l['host']}]" if l.get("host") else ""
            size = f"({l['size']})" if l.get("size") else ""
            print(f"  • {l['quality']} {size} {host}")
            print(f"    {l['direct_url'] or l['href']}")
        print()


def cmd_latest(args, cs):
    h = cs.homepage()
    items = h.get("latest", [])
    print(f"\n🆕 Latest: {len(items)} items\n")
    for i, it in enumerate(items, 1):
        _print_item(i, it)


def cmd_trending(args, cs):
    h = cs.homepage()
    items = h.get("trending", []) or h.get("latest", [])[:10]
    print(f"\n🔥 Trending: {len(items)} items\n")
    for i, it in enumerate(items, 1):
        _print_item(i, it)


def cmd_movies(args, cs):
    items = cs.movies(page=args.page)
    print(f"\n🎬 Movies page {args.page}: {len(items)} items\n")
    for i, it in enumerate(items, 1):
        _print_item(i, it)


def cmd_tvshows(args, cs):
    items = cs.tvshows(page=args.page)
    print(f"\n📺 TV Shows page {args.page}: {len(items)} items\n")
    for i, it in enumerate(items, 1):
        _print_item(i, it)


def main():
    p = argparse.ArgumentParser(description="CineSubz CLI scraper")
    p.add_argument("--browser", action="store_true",
                   help="Use DrissionPage headless Chromium (strongest CF bypass)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search"); sp.add_argument("query")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("movie"); sp.add_argument("url"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_movie)

    sp = sub.add_parser("dl"); sp.add_argument("url")
    sp.set_defaults(func=cmd_dl)

    sp = sub.add_parser("latest"); sp.set_defaults(func=cmd_latest)
    sp = sub.add_parser("trending"); sp.set_defaults(func=cmd_trending)

    sp = sub.add_parser("movies"); sp.add_argument("page", nargs="?", type=int, default=1)
    sp.set_defaults(func=cmd_movies)

    sp = sub.add_parser("tvshows"); sp.add_argument("page", nargs="?", type=int, default=1)
    sp.set_defaults(func=cmd_tvshows)

    args = p.parse_args()

    cs = CineSubz(use_browser=args.browser)
    try:
        args.func(args, cs)
    finally:
        cs.close()


if __name__ == "__main__":
    main()
