# 🎬 CineSubz Scraper + WhatsApp / Telegram Bot

සිංහල උපසිරැසි සහිත චිත්‍රපට ඩවුන්ලෝඩ් ලින්ක් (Server 1 / Server 2 / Telegram)
Cloudflare firewall එක bypass කරලා අරගන්න පුලුවන් complete scraper & **WhatsApp bot** එකක්
(+ Telegram bot එකත් තියෙනවා).

> **⚠️ Warning / වැදගත්:** මෙය ඔබට අයිති හෝ නැරඹීමට අවසර ඇති අන්තර්ගතයන්
> සඳහා පමණක් භාවිතා කරන්න. භාවිතය ඔබේ වගකීමකි.

---

## ✅ Features

- 🔎 **Search** — චිත්‍රපට / ටෙලිනාට්‍ය හොයන්න
- 🎞 **Movie/TV pages** — සම්පූර්ණ විස්තර (poster, rating, genres, episodes)
- 📥 **Server 1 / Server 2 / Telegram** — සියලුම ඩවුන්ලෝඩ් ටැබ් extract කරනවා
- ⏭ **Ad-link resolver** — 5-second countdown, "Click here to continue",
  short-link redirect දාම ඔක්කොම auto follow කරලා final direct link
  (Mega / GDrive / MediaFire / Terabox / Telegram) දෙනවා
- 🛡 **Cloudflare bypass** — 3-level strategy:
  1. `curl_cffi` (real Chrome TLS fingerprint) — fast, no browser needed
  2. `cloudscraper` (JS challenge solver)
  3. **DrissionPage** headless Chromium fallback — most reliable
- 🤖 **WhatsApp Bot** — QR එක scan කරලා ඔබේම ගිණුමෙන් වැඩ කරනවා (Baileys multi-device)
- 🤖 **Telegram Bot** — inline buttons වලින් search → pick → server → quality
- 💻 **CLI** — terminal එකෙන් පාවිච්චි කරන්නත් පුලුවන්

---

## 🚀 Quick Start

### 1. Install
```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. CLI Usage

```bash
# චිත්‍රපටයක් හොයන්න
python cli.py search "gajaman"

# සෘජුවම movie page එකක ලින්ක් දෙන්න
python cli.py movie https://cinesubz.co/movies/gajaman-2023-sinhala-subtitles/

# Download links (short-link bypass සමග)
python cli.py dl https://cinesubz.co/movies/gajaman-2023-sinhala-subtitles/

# Latest / Trending lists
python cli.py latest
python cli.py trending

# Movies / TV list pages (pagination)
python cli.py movies 1
python cli.py tvshows 2

# Cloudflare තද නම් --browser flag එක දාන්න (Chromium අවශ්‍යයි)
python cli.py --browser search "kgf"
```

### 3. WhatsApp Bot (Baileys — ඔබේම WhatsApp ගිණුමෙන්)

```bash
cd whatsapp_bot
npm install          # පළවෙනි වරක් පමණයි
node index.js
```

පළවෙනි වර QR code එකක් terminal එකේ පේනවා →
**WhatsApp → Settings → Linked Devices → Link a Device** → QR එක scan කරන්න.
ඊට පස්සේ ඔබේ WhatsApp ගිණුමම bot එක වෙනවා (session `whatsapp_bot/auth/` එකේ save වෙනවා — ආයේ scan කරන්න ඕන නෑ).

**Bot එකේ commands:**

| Command | කරන දේ |
|---|---|
| `.search <movie name>` | චිත්‍රපට / ටෙලිනාට්‍ය search |
| `.latest` | අලුත්ම එකතුවීම් |
| `.trending` | Trending list |
| `.movie <cinesubz URL>` | Details + servers |
| `.dl <cinesubz URL>` | Details + **සියලුම resolved direct links** |
| `.episodes` | TV series episode list |
| `.back` / `.reset` | පිටිපස්සට / reset |
| cinesubz link paste | Auto-detect කරලා details දෙනවා |
| plain text (DM) | Search එකක් විදිහට |

**Interactive flow:** search list එකේ number එකක් reply කරන්න → movie details →
server number (1 = Server 1, 2 = Server 2 …) → quality number (480p/720p/1080p) →
✅ **final direct download link** (Mega/GDrive/MediaFire/Terabox/Telegram) —
මැද ad/short-link දාම ඔක්කොම bot එක auto follow කරනවා.

**Env options:** `PYTHON=/usr/bin/python3 node index.js` (venv path වෙනස් නම්),
`USE_BROWSER=1` (Cloudflare දැඩි නම් Chromium mode).

### 4. Telegram Bot (optional alternative)

1. https://t.me/BotFather ගිහින් bot token එකක් අරගන්න
2. Run:
   ```bash
   BOT_TOKEN="123456:ABC-..." python bot.py
   # or
   python bot.py 123456:ABC-...
   ```
3. Browser mode (strongest bypass):
   ```bash
   USE_BROWSER=1 BOT_TOKEN="..." python bot.py
   ```

**Bot commands:**
- `/start` — Welcome
- `/search <name>` — චිත්‍රපටය හොයන්න
- `/movie <url>` — සෘජු cinesubz URL එකකින්
- `/dl <url>` — සියලුම server links resolve කරන්න
- `/latest`, `/trending`
- Inline buttons වලින් quality තොරලා direct download link එක ගන්න.

---

## 🧠 How the Cloudflare Bypass Works

Cloudflare blocks generic HTTP clients (python `requests`, default `curl`) by
checking:

1. **TLS fingerprint (JA3/JA4)** — `curl_cffi` uses BoringSSL + real Chrome
   cipher suites, so the TLS handshake looks exactly like Chrome 124.
2. **JavaScript challenges** — `cloudscraper` evaluates CF's JS challenge in
   Python and returns valid cookies.
3. **Behavioral / Turnstile** — If both fail, `DrissionPage` launches a real
   Chromium (no webdriver flag, `--disable-blink-features=AutomationControlled`),
   waits for the challenge to clear, and extracts the page.

The short-link chain (after you click a quality link) is followed by:
- Respecting `<meta http-equiv="refresh">` tags
- Clicking `#link` / "Generate Link" buttons (form POST + anchor extraction)
- Detecting final host (mega.nz, drive.google.com, mediafire.com, terabox, t.me)

---

## 📁 Files

| File | Description |
|------|-------------|
| `scraper.py` | Core scraper (CF bypass, search, movie details, link resolver) |
| `whatsapp_bot/index.js` | **WhatsApp bot** (Baileys multi-device) |
| `whatsapp_bot/bridge.py` | Node ↔ Python bridge (scraper calls) |
| `bot.py` | Telegram bot (python-telegram-bot v20) |
| `cli.py` | CLI tool |
| `api.py` | FastAPI HTTP API |
| `requirements.txt` | Python deps |

---

## 🔧 Troubleshooting

**`SSL_ERROR_SYSCALL` / TLS closed:**
The VPS/datacenter IP you're running from may be blacklisted by Cloudflare.
- Try a residential proxy
- Or run locally on your home connection
- Or enable `use_browser=True` with DrissionPage

**Links resolve to ad pages:**
The cinesubz site changes its ad network occasionally. If the chain breaks,
open `scraper.py` → `_resolve_chain()` and add the new domain to `ad_domains`
or detect the new "Continue" button selector.

**DrissionPage can't find Chrome:**
Install Chromium:
```bash
# Ubuntu/Debian
sudo apt install chromium-browser
# or Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
```

---

## 📝 License

Educational / personal use only. Respect copyright and the site's terms.
