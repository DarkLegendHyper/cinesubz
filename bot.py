"""
CineSubz Telegram Bot
=====================
Search, browse and get direct download links (Server 1 / Server 2 / Telegram)
from cinesubz.co  -- with Cloudflare bypass built-in.

Setup
-----
1. Create a bot via https://t.me/BotFather and copy the token.
2. Install deps:
       pip install -r requirements.txt
3. Run:
       python bot.py <YOUR_BOT_TOKEN>
   or set the env var:
       BOT_TOKEN=... python bot.py

If Cloudflare blocks the scraper in your region, run with browser mode:
       USE_BROWSER=1 python bot.py <token>
   (requires Google Chromium / Chrome to be installed.)

Commands
--------
/start        - Welcome message
/help         - Help
/search <q>   - Search movies & TV shows
/movie <url>  - Show details + download servers for a cinesubz URL
/latest       - Latest additions (from homepage)
/trending     - Trending list
/dl <url>     - Resolve download short-links for a cinesubz movie page URL

Inline buttons allow selecting a result, picking Server 1 / Server 2, and
getting the final direct link.
"""

from __future__ import annotations

import os
import re
import sys
import html
import logging
import asyncio
from typing import Dict, Any, List
from urllib.parse import urlparse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from scraper import CineSubz

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("cinesubz-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", sys.argv[1] if len(sys.argv) > 1 else None)
USE_BROWSER = os.environ.get("USE_BROWSER", "0") == "1"
MAX_RESULTS = 10  # search results per page

if not BOT_TOKEN:
    sys.exit("Set BOT_TOKEN env var or pass it as first argument.\n"
             "Example:  python bot.py 123456:ABCDEF...")

# ---------------------------------------------------------------------------
# Scraper singleton
# ---------------------------------------------------------------------------
cs = CineSubz(use_browser=USE_BROWSER)

# In-memory cache:  query -> [results...] ,  url -> details
CACHE: Dict[str, Any] = {}


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


# ---------------------------------------------------------------------------
# Build inline keyboards
# ---------------------------------------------------------------------------
def results_kbd(results: List[Dict[str, Any]], prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for i, r in enumerate(results[:MAX_RESULTS]):
        marker = "🎬" if r.get("type") == "movie" else "📺"
        label = f"{marker} {r['title'][:55]}"
        if r.get("rating"):
            label += f" ⭐{r['rating']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{i}")])
    return InlineKeyboardMarkup(rows)


def servers_kbd(sections: List[Dict[str, Any]], movie_link: str) -> InlineKeyboardMarkup:
    rows = []
    for s in sections:
        rows.append([
            InlineKeyboardButton(f"📥 {s['name']}", callback_data=f"srv:{movie_link}:{s['name']}")
        ])
    rows.append([InlineKeyboardButton("🔄 Resolve all links", callback_data=f"resolve:{movie_link}")])
    return InlineKeyboardMarkup(rows)


def quality_kbd(section: Dict[str, Any], movie_link: str) -> InlineKeyboardMarkup:
    rows = []
    for i, l in enumerate(section["links"]):
        label = l["quality"][:50]
        if l.get("size"):
            label += f"  ({l['size']})"
        rows.append([
            InlineKeyboardButton(f"⬇️  {label}",
                                 callback_data=f"get:{movie_link}:{section['name']}:{i}")
        ])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=f"detail:{movie_link}")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎬 <b>CineSubz Bot</b>\n"
        "Search & get direct download links from cinesubz.co\n\n"
        "Commands:\n"
        "🔍 <code>/search &lt;movie name&gt;</code>  – search movies/TV\n"
        "🎞 <code>/movie &lt;cinesubz-url&gt;</code>  – movie details & servers\n"
        "🔥 /trending – trending movies\n"
        "🆕 /latest  – latest additions\n"
        "📥 <code>/dl &lt;url&gt;</code>  – resolve direct links\n"
        "❓ /help"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>How to use</b>\n"
        "1. Send <code>/search your-movie-name</code>\n"
        "2. Tap a result to see details.\n"
        "3. Pick <b>Server 1</b> / <b>Server 2</b> / <b>Telegram</b>.\n"
        "4. Pick a quality (480p/720p/1080p/4K) – the bot will automatically\n"
        "   walk through the 5-second ad redirects and give you the final\n"
        "   download link (Mega/GDrive/MediaFire/Terabox/Telegram).\n\n"
        "You can also just paste any cinesubz.co movie/TV link and I'll fetch\n"
        "the download servers for you."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def _sync_run(fn, *args, **kwargs):
    """Run blocking scraper calls in a thread pool so the bot stays responsive."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def search_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args).strip() if ctx.args else ""
    if not q:
        await update.message.reply_text("Usage: <code>/search movie name</code>",
                                        parse_mode=ParseMode.HTML)
        return
    msg = await update.message.reply_text(f"🔎 Searching for <b>{_esc(q)}</b>…",
                                          parse_mode=ParseMode.HTML)
    try:
        results = await _sync_run(cs.search, q)
    except Exception as e:
        log.exception("search failed")
        await msg.edit_text(f"❌ Search failed: {_esc(e)}")
        return

    if not results:
        await msg.edit_text("No results found. Try a different title.")
        return

    CACHE[f"search:{update.effective_user.id}:{q}"] = results
    text = f"🔎 <b>Results for {_esc(q)}</b>\n\n"
    for i, r in enumerate(results[:MAX_RESULTS], 1):
        marker = "🎬" if r.get("type") == "movie" else "📺"
        text += f"{i}. {marker} {_esc(r['title'])}\n"
        if r.get("year"):
            text += f"   📅 {r['year']}"
        if r.get("rating"):
            text += f"  ⭐{r['rating']}"
        text += "\n\n"
    await msg.edit_text(text, parse_mode=ParseMode.HTML,
                        reply_markup=results_kbd(results, f"pick:{update.effective_user.id}:{q}"))


async def latest_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🆕 Fetching latest movies…")
    try:
        home = await _sync_run(cs.homepage)
        items = home.get("latest", [])[:MAX_RESULTS]
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {_esc(e)}")
        return
    if not items:
        await msg.edit_text("Could not fetch latest list.")
        return
    CACHE[f"latest:{update.effective_user.id}"] = items
    text = "🆕 <b>Latest additions</b>\n\n"
    for i, it in enumerate(items, 1):
        text += f"{i}. 🎬 {_esc(it['title'])}\n"
    await msg.edit_text(text, parse_mode=ParseMode.HTML,
                        reply_markup=results_kbd(items, f"picklatest:{update.effective_user.id}"))


async def trending_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔥 Fetching trending…")
    try:
        home = await _sync_run(cs.homepage)
        items = home.get("trending", []) or home.get("latest", [])[:10]
    except Exception as e:
        await msg.edit_text(f"❌ Failed: {_esc(e)}")
        return
    CACHE[f"trending:{update.effective_user.id}"] = items
    text = "🔥 <b>Trending Now</b>\n\n"
    for i, it in enumerate(items[:MAX_RESULTS], 1):
        text += f"{i}. {_esc(it['title'])}\n"
    await msg.edit_text(text, parse_mode=ParseMode.HTML,
                        reply_markup=results_kbd(items[:MAX_RESULTS],
                                                 f"picktrend:{update.effective_user.id}"))


async def movie_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = " ".join(ctx.args).strip() if ctx.args else ""
    if not url or not url.startswith("http"):
        await update.message.reply_text("Usage: <code>/movie https://cinesubz.co/…</code>",
                                        parse_mode=ParseMode.HTML)
        return
    await _detail_flow(update.effective_chat.id, update.message, url)


async def url_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Auto-detect cinesubz URLs pasted in chat."""
    text = update.message.text or ""
    m = re.search(r"https?://cinesubz\.(co|net|lk)/(movies|tvshows|episodes)/[^\s]+", text)
    if m:
        await _detail_flow(update.effective_chat.id, update.message, m.group(0))


async def _detail_flow(chat_id, src_msg, url: str):
    msg = await src_msg.reply_text("📄 Loading details…")
    try:
        details = await _sync_run(cs.get_movie, url)
    except Exception as e:
        log.exception("get_movie failed")
        await msg.edit_text(f"❌ Failed to fetch page: {_esc(e)}")
        return
    CACHE[f"detail:{url}"] = details

    text = _format_details(details)
    kbd = servers_kbd(details["download_sections"], url)

    if details.get("poster"):
        try:
            await src_msg.reply_photo(
                photo=details["poster"], caption=text, parse_mode=ParseMode.HTML,
                reply_markup=kbd,
            )
            await msg.delete()
            return
        except Exception:
            pass
    await msg.edit_text(text, parse_mode=ParseMode.HTML,
                        reply_markup=kbd, disable_web_page_preview=True)


def _format_details(d: Dict[str, Any]) -> str:
    lines = [f"🎬 <b>{_esc(d.get('title'))}</b>\n"]
    if d.get("rating"):
        lines.append(f"⭐ IMDb: <b>{_esc(d['rating'])}</b>")
    if d.get("genres"):
        lines.append("🎭 Genres: " + ", ".join(_esc(g) for g in d["genres"]))
    if d.get("date"):
        lines.append("📅 Released: " + _esc(d["date"]))
    if d.get("country"):
        lines.append("🌍 Country: " + _esc(d["country"]))
    if d.get("subtitle_author"):
        lines.append("✍️ Subtitle by: " + _esc(d["subtitle_author"]))
    lines.append("")
    if d.get("description"):
        lines.append(f"<i>{_esc(d['description'][:400])}</i>\n")
    if d.get("episodes"):
        lines.append(f"\n📺 Episodes found: <b>{len(d['episodes'])}</b>")
    lines.append("👇 <b>Pick a server:</b>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Button callbacks
# ---------------------------------------------------------------------------
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    # Pick a search/trending/latest result
    if data.startswith("pick:") or data.startswith("picklatest:") or data.startswith("picktrend:"):
        parts = data.split(":", 2)
        idx = int(parts[-1])
        cache_key = "search:" + data[len("pick:"):] if data.startswith("pick:") else \
                    ("latest:" + data[len("picklatest:"):] if data.startswith("picklatest:")
                     else "trending:" + data[len("picktrend:"):])
        results = CACHE.get(cache_key, [])
        if idx >= len(results):
            await q.edit_message_text("Result expired. Please search again.")
            return
        url = results[idx]["link"]
        try:
            details = await _sync_run(cs.get_movie, url)
        except Exception as e:
            await q.edit_message_text(f"❌ {_esc(e)}")
            return
        CACHE[f"detail:{url}"] = details
        text = _format_details(details)
        await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML,
                                     reply_markup=servers_kbd(details["download_sections"], url))
        # If we were editing a text (not photo), switch to text edit
        try:
            pass
        except Exception:
            pass
        return

    # Back to detail
    if data.startswith("detail:"):
        url = data.split(":", 1)[1]
        details = CACHE.get(f"detail:{url}")
        if not details:
            details = await _sync_run(cs.get_movie, url)
            CACHE[f"detail:{url}"] = details
        text = _format_details(details)
        await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML,
                                     reply_markup=servers_kbd(details["download_sections"], url))
        return

    # Pick a server
    if data.startswith("srv:"):
        _, url, sname = data.split(":", 2)
        details = CACHE.get(f"detail:{url}")
        if not details:
            details = await _sync_run(cs.get_movie, url)
            CACHE[f"detail:{url}"] = details
        section = next((s for s in details["download_sections"] if s["name"] == sname), None)
        if not section:
            await q.answer("Section not found", show_alert=True)
            return
        text = f"📥 <b>{_esc(sname)}</b> — choose quality:\n"
        for l in section["links"][:20]:
            text += f"\n• {_esc(l['quality'])}"
            if l.get("size"):
                text += f"  ({_esc(l['size'])})"
        await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML,
                                     reply_markup=quality_kbd(section, url))
        return

    # Get one link (resolve ad chain)
    if data.startswith("get:"):
        _, url, sname, idx = data.split(":", 3)
        idx = int(idx)
        details = CACHE.get(f"detail:{url}")
        if not details:
            details = await _sync_run(cs.get_movie, url)
            CACHE[f"detail:{url}"] = details
        section = next((s for s in details["download_sections"] if s["name"] == sname), None)
        if not section or idx >= len(section["links"]):
            await q.answer("Link not found.", show_alert=True)
            return
        lnk = section["links"][idx]
        wait = await q.message.reply_text("⏳ Resolving link… (bypassing ads & countdowns)")
        try:
            direct, host = await _sync_run(cs._resolve_chain, lnk["href"])
        except Exception as e:
            await wait.edit_text(f"❌ Resolve failed: {_esc(e)}")
            return
        label = f"{_esc(lnk['quality'])}"
        if lnk.get("size"):
            label += f"  ({_esc(lnk['size'])})"
        if direct:
            host = host or "Direct"
            txt = (f"✅ <b>{label}</b>\n"
                   f"🖥 Host: <b>{_esc(host)}</b>\n\n"
                   f"<a href=\"{_esc(direct)}\">🔗 Click here to download</a>\n\n"
                   f"<code>{_esc(direct)}</code>")
        else:
            txt = f"⚠ Could not resolve fully. Raw link:\n<code>{_esc(lnk['href'])}</code>"
        await wait.edit_text(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    # Resolve all links for a movie
    if data.startswith("resolve:"):
        url = data.split(":", 1)[1]
        details = CACHE.get(f"detail:{url}")
        if not details:
            details = await _sync_run(cs.get_movie, url)
            CACHE[f"detail:{url}"] = details
        wait = await q.message.reply_text("⏳ Resolving all download links (this may take a minute)…")
        try:
            resolved = await _sync_run(cs.resolve_download_links, details["download_sections"])
        except Exception as e:
            await wait.edit_text(f"❌ {_esc(e)}")
            return
        lines = [f"🎬 <b>{_esc(details.get('title',''))}</b>\n"]
        for s in resolved:
            lines.append(f"\n📥 <b>{_esc(s['name'])}</b>")
            for l in s["links"]:
                qtxt = _esc(l["quality"])
                if l.get("host"):
                    qtxt += f"  [{_esc(l['host'])}]"
                link = l.get("direct_url") or l["href"]
                lines.append(f"• <a href=\"{_esc(link)}\">{qtxt}</a>")
        await wait.edit_text("\n".join(lines), parse_mode=ParseMode.HTML,
                             disable_web_page_preview=True)
        return


async def dl_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = " ".join(ctx.args).strip() if ctx.args else ""
    if not re.match(r"https?://cinesubz\.(co|net|lk)/", url):
        await update.message.reply_text("Usage: <code>/dl https://cinesubz.co/movies/…</code>",
                                        parse_mode=ParseMode.HTML)
        return
    msg = await update.message.reply_text("📄 Fetching page & resolving all servers…")
    try:
        details = await _sync_run(cs.get_movie, url)
        CACHE[f"detail:{url}"] = details
        resolved = await _sync_run(cs.resolve_download_links, details["download_sections"])
    except Exception as e:
        await msg.edit_text(f"❌ {_esc(e)}")
        return
    lines = [f"🎬 <b>{_esc(details.get('title',''))}</b>\n"]
    for s in resolved:
        lines.append(f"\n📥 <b>{_esc(s['name'])}</b>")
        for l in s["links"]:
            qtxt = _esc(l["quality"])
            if l.get("host"):
                qtxt += f"  [{_esc(l['host'])}]"
            link = l.get("direct_url") or l["href"]
            lines.append(f"• <a href=\"{_esc(link)}\">{qtxt}</a>")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("movie", movie_cmd))
    app.add_handler(CommandHandler("dl", dl_cmd))
    app.add_handler(CommandHandler("latest", latest_cmd))
    app.add_handler(CommandHandler("trending", trending_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, url_message))

    log.info("Bot started. Polling…")
    try:
        app.run_polling()
    finally:
        cs.close()


if __name__ == "__main__":
    main()
