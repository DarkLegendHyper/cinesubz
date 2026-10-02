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

