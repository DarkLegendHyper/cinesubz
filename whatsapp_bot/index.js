/**
 * 🎬 CineSubz WhatsApp Bot
 * ========================
 * Powered by @whiskeysockets/baileys (WhatsApp Multi-Device).
 * Uses the Python scraper (../scraper.py) via bridge.py for Cloudflare bypass
 * and ad-link resolution.
 *
 * Setup
 * -----
 *   cd whatsapp_bot
 *   npm install
 *   node index.js
 *   → scan the QR (WhatsApp → Settings → Linked Devices → Link a Device)
 *
 * Commands (in any chat with the bot)
 * -----------------------------------
 *   .search <name>          search movies / TV shows
 *   .latest                 latest additions
 *   .trending               trending
 *   .movie <cinesubz URL>   details + servers (no auto resolve)
 *   .dl <cinesubz URL>      details + ALL resolved direct links
 *   .back                   go one step back
 *   .new                    reset conversation state
 *
 * Interactive flow: after a listing, reply with a NUMBER:
 *   search list → movie details → server (1/2/Telegram) → quality → direct link
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
  delay,
  isJidBroadcast,
} = require("@whiskeysockets/baileys");
const P = require("pino");
const QR = require("qrcode-terminal");
const { execFile } = require("child_process");
const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const PYTHON = process.env.PYTHON || path.join(__dirname, "..", ".venv", "bin", "python");
const BRIDGE = path.join(__dirname, "bridge.py");
const AUTH_DIR = process.env.AUTH_DIR || path.join(__dirname, "auth");
const STATE_TTL_MS = 15 * 60 * 1000; // 15 min
const MAX_LIST = 10;

// chatId -> { kind, ts, ... }
const chatState = new Map();

function setState(chatId, state) {
  chatState.set(chatId, { ...state, ts: Date.now() });
}
function getState(chatId) {
  const s = chatState.get(chatId);
  if (!s) return null;
  if (Date.now() - s.ts > STATE_TTL_MS) {
    chatState.delete(chatId);
    return null;
  }
  return s;
}

// ---------------------------------------------------------------------------
// Python bridge
// ---------------------------------------------------------------------------
function callBridge(args, timeoutMs = 90000) {
  return new Promise((resolve) => {
    execFile(
      PYTHON,
      [BRIDGE, ...args.map((a) => String(a))],
      { env: process.env, timeout: timeoutMs, maxBuffer: 20 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if (err) {
          resolve({ ok: false, error: err.message });
          return;
        }
        try {
          resolve(JSON.parse(stdout));
        } catch {
          resolve({ ok: false, error: "bad bridge output: " + String(stdout).slice(0, 300) });
        }
      }
    );
  });
}

// ---------------------------------------------------------------------------
// Text helpers
// ---------------------------------------------------------------------------
function clean(s) {
  return String(s == null ? "" : s).replace(/[*_`~>#]/g, "").trim();
}
function clip(s, n) {
  s = clean(s);
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

const HELP_TEXT =
`🎬 *CineSubz WhatsApp Bot*

සිංහල subtitle සහිත movie direct download links (Server 1 / Server 2 / Telegram) — Cloudflare bypass සමඟ.

*Commands*
🔎 _.search <movie name>_ — search movies/TV
🆕 _.latest_ — latest additions
🔥 _.trending_ — trending list
🎞 _.movie <cinesubz URL>_ — details + servers
📥 _.dl <cinesubz URL>_ — details + ALL resolved links
↩️ _.back_ — one step back
🔄 _.new_ — reset

cinesubz.co link එකක් direct paste කරත් වැඩ කරනවා.

List එකක් ආවම *number* එකක් reply කරන්න (උදා: 2).`;

// ---------------------------------------------------------------------------
// Bot
// ---------------------------------------------------------------------------
const logger = P({ level: "silent" });
let reconnectAttempts = 0;

async function startBot() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch {
    version = [2, 3000, 1015901304]; // fallback known-good
  }

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    browser: Browsers.ubuntu("Chrome"),
    syncFullHistory: false,
    markOnlineOnConnect: true,
    generateHighQualityLinkPreview: false,
    shouldIgnoreJid: (jid) => isJidBroadcast(jid),
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      reconnectAttempts = 0;
      console.log("\n═══════════════════════════════════════════");
      console.log("  SCAN THIS QR WITH YOUR WHATSAPP");
      console.log("  Settings → Linked Devices → Link a Device");
      console.log("═══════════════════════════════════════════\n");
      QR.generate(qr, { small: true });
    }
    if (connection === "open") {
      reconnectAttempts = 0;
      console.log("[wa] ✅ CONNECTED as", sock.user?.id);
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      console.log(`[wa] connection closed (code=${code})`);
      if (loggedOut) {
        console.log("[wa] logged out — deleting auth session. Restart to re-scan QR.");
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        process.exit(1);
      }
      reconnectAttempts++;
      const waitMs = Math.min(3000 * reconnectAttempts, 30000);
      console.log(`[wa] reconnecting in ${waitMs / 1000}s…`);
      setTimeout(startBot, waitMs);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    const msg = messages[0];
    if (!msg.key || msg.key.fromMe) return;
    const from = msg.key.remoteJid;
    if (!from || from === "status@broadcast") return;

    const text =
      msg.message?.conversation ||
      msg.message?.extendedTextMessage?.text ||
      msg.message?.imageMessage?.caption ||
      msg.message?.videoMessage?.caption || "";
    if (!text) return;
    const t = text.trim();
    if (!t) return;

    const isGroup = from.endsWith("@g.us");
    const isCommand = /^[.!#]/.test(t);
    const urlMatch = t.match(/https?:\/\/cinesubz\.(co|net|lk)\/[^\s]+/i);
    const numMatch = isGroup && !isCommand ? null : t.match(/^(\d{1,2})$/);

    if (!isCommand && !urlMatch && !numMatch) {
      // plain text in DM → treat as search
      if (!isGroup && t.length > 2) {
        await runGuarded(sock, from, () => handleSearch(sock, from, t));
      }
      return;
    }

    await runGuarded(sock, from, async () => {
      await sock.readMessages([msg.key]);
      await sock.sendPresenceUpdate("composing", from);

      if (urlMatch && !isCommand) {
        await handleMovieUrl(sock, from, urlMatch[0], { resolve: false });
        return;
      }
      if (numMatch) {
        await handleNumber(sock, from, parseInt(numMatch[1], 10));
        return;
      }

      const [rawCmd, ...rest] = t.replace(/^[.!#]+/, "").split(/\s+/);
      const cmd = rawCmd.toLowerCase();
      const arg = rest.join(" ").trim();

      switch (cmd) {
        case "start":
        case "help":
        case "menu":
          await sendText(sock, from, HELP_TEXT);
          break;
        case "search":
        case "s":
          if (!arg) return sendText(sock, from, "🔎 Usage: _.search <movie name>_");
          await handleSearch(sock, from, arg);
          break;
        case "latest":
          await handleLatest(sock, from);
          break;
        case "trending":
        case "trend":
          await handleTrending(sock, from);
          break;
        case "movie":
        case "m":
          if (!/^https?:\/\//.test(arg)) return sendText(sock, from, "🎞 Usage: _.movie <cinesubz-url>_");
          await handleMovieUrl(sock, from, arg, { resolve: false });
          break;
        case "dl":
        case "download":
          if (!/^https?:\/\//.test(arg)) return sendText(sock, from, "📥 Usage: _.dl <cinesubz-url>_");
          await handleMovieUrl(sock, from, arg, { resolve: true });
          break;
        case "server":
        case "srv": {
          const st = getState(from);
          if (!st || st.kind !== "movie") return sendText(sock, from, "මුලින්ම movie එකක් select කරන්න (_.search …)");
          await handleServerPick(sock, from, st, arg || "1");
          break;
        }
        case "episodes":
        case "ep": {
          const st = getState(from);
          if (!st || !st.details) return sendText(sock, from, "මුලින්ම movie/TV එකක් select කරන්න (_.search …)");
          await handleEpisodes(sock, from, st);
          break;
        }
        case "back": {
          const st = getState(from);
          if (!st) return sendText(sock, from, "කලින් step එකක් නෑ. _.search_ කරන්න.");
          if (st.kind === "server" || st.kind === "quality" || st.kind === "episodes") {
            setState(from, { kind: "movie", details: st.details, url: st.url });
            await sendMovieSummary(sock, from, st.details, st.url);
          } else {
            chatState.delete(from);
            await sendText(sock, from, "↩️ State cleared. _.search_ කරන්න.");
          }
          break;
        }
        case "reset":
        case "new": {
          chatState.delete(from);
          await sendText(sock, from, "🔄 State cleared. _.search_ කරන්න.");
          break;
        }
        case "ping":
          await sendText(sock, from, "pong 🏓");
          break;
        default:
          if (!isGroup && rawCmd.length > 2) await handleSearch(sock, from, t);
          else await sendText(sock, from, "🤔 Command එක තේරුණේ නෑ.\n\n" + HELP_TEXT);
      }
    });
  });
}

async function runGuarded(sock, jid, fn) {
  try {
    await fn();
  } catch (e) {
    console.error(e);
    await sendText(sock, jid, "❌ Error: " + clean(e.message || e));
  }
}

async function sendText(sock, jid, text, quoted) {
  return sock.sendMessage(jid, { text }, quoted ? { quoted } : undefined);
}

// ---------------------------------------------------------------------------
// Listing handlers
// ---------------------------------------------------------------------------
function listingText(items, title) {
  let out = `${title}\n\n`;
  items.forEach((it, i) => {
    const icon = it.type === "tvshow" || /tvshows?|episode/i.test(it.link || "") ? "📺" : "🎬";
    out += `*${i + 1}.* ${icon} *${clip(it.title, 60)}*`;
    if (it.year) out += ` (${clean(it.year)})`;
    if (it.rating) out += ` ⭐${clean(it.rating)}`;
    out += "\n";
  });
  out += "\n_අදාළ *number* එක reply කරන්න._";
  return out;
}

async function handleSearch(sock, jid, q) {
  const wait = await sendText(sock, jid, `🔎 *${clip(q, 50)}* search කරනවා…`);
  const r = await callBridge(["search", q]);
  if (!r.ok) return sendText(sock, jid, "❌ Search failed: " + clean(r.error), wait);
  const items = (r.results || []).slice(0, MAX_LIST);
  if (!items.length) return sendText(sock, jid, "හොයාගන්න බැරි උනා 😕 වෙනත් නමකින් try කරන්න.", wait);
  setState(jid, { kind: "search", results: items, query: q });
  await sendText(sock, jid, listingText(items, `🔎 *Results: ${clip(q, 40)}*`), wait);
}

async function handleLatest(sock, jid) {
  const wait = await sendText(sock, jid, "🆕 Latest list එක ගන්නවා…");
  const r = await callBridge(["latest"]);
  if (!r.ok) return sendText(sock, jid, "❌ " + clean(r.error), wait);
  const items = (r.latest || []).slice(0, MAX_LIST);
  if (!items.length) return sendText(sock, jid, "ලැයිස්තුව හිස්.", wait);
  setState(jid, { kind: "search", results: items });
  await sendText(sock, jid, listingText(items, "🆕 *Latest Additions*"), wait);
}

async function handleTrending(sock, jid) {
  const wait = await sendText(sock, jid, "🔥 Trending ගන්නවා…");
  const r = await callBridge(["trending"]);
  if (!r.ok) return sendText(sock, jid, "❌ " + clean(r.error), wait);
  const items = (r.results || []).slice(0, MAX_LIST);
  if (!items.length) return sendText(sock, jid, "ලැයිස්තුව හිස්.", wait);
  setState(jid, { kind: "search", results: items });
  await sendText(sock, jid, listingText(items, "🔥 *Trending Now*"), wait);
}

// ---------------------------------------------------------------------------
// Number router
// ---------------------------------------------------------------------------
async function handleNumber(sock, jid, n) {
  const st = getState(jid);
  if (!st) {
    return sendText(sock, jid, "List එකක් active නෑ. _.search <name>_ විත් කරන්න.");
  }
  switch (st.kind) {
    case "search": {
      const item = st.results?.[n - 1];
      if (!item) return;
      await handleMovieUrl(sock, jid, item.link, { resolve: false });
      break;
    }
    case "movie": {
      await handleServerPick(sock, jid, st, String(n));
      break;
    }
    case "server": {
      await handleQualityPick(sock, jid, st, n);
      break;
    }
    case "episodes": {
      const ep = st.episodes?.[n - 1];
      if (!ep) return;
      await handleMovieUrl(sock, jid, ep.link, { resolve: true });
      break;
    }
    default:
      chatState.delete(jid);
      await sendText(sock, jid, "State expired. _.search_ කරන්න.");
  }
}

// ---------------------------------------------------------------------------
// Movie / server / quality flow
// ---------------------------------------------------------------------------
async function sendMovieSummary(sock, jid, d, url) {
  const sections = d.download_sections || [];
  let text = `🎬 *${clip(d.title, 80)}*\n\n`;
  if (d.rating) text += `⭐ IMDb: *${clean(d.rating)}*\n`;
  if (d.genres?.length) text += `🎭 ${clip(d.genres.join(", "), 80)}\n`;
  if (d.date) text += `📅 ${clean(d.date)}\n`;
  if (d.country) text += `🌍 ${clean(d.country)}\n`;
  if (d.subtitle_author) text += `✍️ Subtitle: ${clean(d.subtitle_author)}\n`;
  if (d.description) text += `\n_${clip(d.description, 220)}_\n`;

  if (sections.length) {
    text += "\n📥 *Servers:*\n";
    sections.forEach((s, i) => {
      text += `*${i + 1}.* ${clean(s.name)} — ${s.links.length} links\n`;
    });
    text += "\n_Server එකක් තෝරන්න number එකක් reply කරන්න._";
  } else {
    text += "\n⚠️ Download servers හම්බුනේ නෑ.";
  }
  if (d.episodes?.length) {
    text += `\n\n📺 TV series — episodes *${d.episodes.length}* ක් තියෙනවා. _.episodes_ type කරලා list එක බලන්න.`;
    setState(jid, { kind: "movie", details: d, url, hasEpisodes: true });
  } else {
    setState(jid, { kind: "movie", details: d, url });
  }

  if (d.poster) {
    try {
      await sock.sendMessage(jid, { image: { url: d.poster }, caption: text });
      return;
    } catch { /* fall through to text */ }
  }
  await sendText(sock, jid, text);
}

async function handleMovieUrl(sock, jid, url, { resolve = false } = {}) {
  const wait = await sendText(
    sock, jid,
    resolve ? "📥 සියලුම links resolve කරනවා (ads bypass — ටිකක් වෙලා යන්න පුළුවන්)…" : "📄 Movie details ගන්නවා…"
  );
  const r = await callBridge([resolve ? "dl" : "movie", url], 120000);
  if (!r.ok) return sendText(sock, jid, "❌ Failed: " + clean(r.error), wait);
  const d = r.result;

  if (resolve) {
    const sections = d.resolved || [];
    let text = `🎬 *${clip(d.title, 80)}* — ✅ *Direct Links*\n`;
    for (const s of sections) {
      text += `\n📥 *${clean(s.name)}*\n`;
      for (const l of s.links.slice(0, 15)) {
        const link = l.direct_url || l.href;
        const host = l.host ? ` _[${clean(l.host)}]_` : "";
        const size = l.size ? ` (${clean(l.size)})` : "";
        text += `• ${clean(l.quality)}${size}${host}\n${link}\n`;
      }
    }
    setState(jid, { kind: "movie", details: d, url });
    return sendText(sock, jid, text, wait);
  }

  await sendMovieSummary(sock, jid, d, url);
}

async function handleServerPick(sock, jid, st, arg) {
  const sections = st.details?.download_sections || [];
  let sec = null;
  if (/^\d+$/.test(arg)) sec = sections[parseInt(arg, 10) - 1];
  else sec = sections.find((s) => clean(s.name).toLowerCase().includes(arg.toLowerCase()));
  if (!sec) return sendText(sock, jid, `Server එක හම්බුනේ නෑ. 1-${sections.length} අතරේ number එකක් දෙන්න.`);

  setState(jid, { kind: "server", details: st.details, url: st.url, sectionName: sec.name });
  let text = `📥 *${clean(sec.name)}* — quality එකක් තෝරන්න:\n\n`;
  sec.links.slice(0, 15).forEach((l, i) => {
    text += `*${i + 1}.* ${clean(l.quality)}`;
    if (l.size) text += ` (${clean(l.size)})`;
    text += "\n";
  });
  text += "\n_number එකක් reply කරන්න · _.back_ ආපහු යන්න._";
  await sendText(sock, jid, text);
}

async function handleQualityPick(sock, jid, st, n) {
  const sec = (st.details?.download_sections || []).find((s) => s.name === st.sectionName);
  if (!sec) return sendText(sock, jid, "Server expired. _.back_ ඔබන්න.");
  const link = sec.links[n - 1];
  if (!link) return sendText(sock, jid, `1-${sec.links.length} අතරේ number එකක් දෙන්න.`);

  const wait = await sendText(sock, jid, `⏳ *${clip(link.quality, 40)}* link එක resolve කරනවා…`);
  const r = await callBridge(["link", link.href], 90000);
  if (!r.ok) return sendText(sock, jid, "❌ " + clean(r.error), wait);

  let text;
  if (r.direct) {
    text =
`✅ *${clip(link.quality, 50)}*${link.size ? ` (${clean(link.size)})` : ""}
🖥 Host: *${clean(r.host) || "Direct"}*

🔗 ${r.direct}

_Download button එක ඔබන්න හෝ link එක copy කරන්න._`;
  } else {
    text = `⚠️ Auto-resolve වුනේ නෑ. මෙතනින් යන්න:\n${link.href}`;
  }
  await sendText(sock, jid, text, wait);
}

// episodes listing
// (triggered by ".episodes" when a TV show is selected)
async function handleEpisodes(sock, jid, st) {
  const eps = st.details?.episodes || [];
  if (!eps.length) return sendText(sock, jid, "Episodes හම්බුනේ නෑ.");
  setState(jid, { kind: "episodes", details: st.details, url: st.url, episodes: eps });
  let text = `📺 *${clip(st.details.title, 60)}* — Episodes\n\n`;
  eps.slice(0, 30).forEach((e, i) => {
    text += `*${i + 1}.* ${clip(e.title, 60)}\n`;
  });
  if (eps.length > 30) text += `\n_… තව ${eps.length - 30} ක් (first 30 with numbers)_`;
  text += "\n\n_Episode number එකක් reply කරන්න — direct links දෙන්නම්._";
  await sendText(sock, jid, text);
}

// ---------------------------------------------------------------------------
startBot().catch((e) => {
  console.error("fatal:", e);
  process.exit(1);
});
