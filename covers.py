#!/usr/bin/env python3
"""
cover-rotator: rotating, randomly-picked landscape "covers" for MDBList lists.

Art sources: movies -> TMDB backdrops, TV shows & anime -> TVDB backgrounds.

Every list gets one permanent URL:   http://<host>:<port>/cover/<list-key>.jpg
The image behind that URL changes to a random item from the list every
`rotate_hours` (default 48). Pure standard library - no pip installs needed.

Commands:
  covers.py serve              run web server + background sync/rotation
  covers.py sync [key]         refresh list contents from MDBList
  covers.py rotate [key]       force a new random pick now
  covers.py prefetch [key]     download art for every item (optional, big)
  covers.py urls               print the cover URL for each list
"""
import json, os, random, sys, time, threading, logging
import urllib.request, urllib.parse, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("COVERS_CONFIG", BASE / "config.json"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("covers")

# --------------------------------------------------------------------------- config
ENV_MAP = {
    "MDBLIST_API_KEY": "mdblist_api_key", "TMDB_API_KEY": "tmdb_api_key",
    "TVDB_API_KEY": "tvdb_api_key", "TVDB_PIN": "tvdb_pin", "BASE_URL": "base_url",
    "PORT": "port", "ROTATE_HOURS": "rotate_hours", "SYNC_HOURS": "sync_hours",
    "IMAGE_SIZE": "image_size", "ADMIN_TOKEN": "admin_token", "DATA_DIR": "data_dir",
    "MIN_BACKDROP_WIDTH": "min_backdrop_width", "FALLBACK_TO_TMDB": "fallback_to_tmdb",
}

def _num(v):
    f = float(v)
    return int(f) if f.is_integer() else f

def load_config():
    """config.json (optional) overlaid with environment variables (Docker-friendly)."""
    cfg = {}
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        pass
    for env, key in ENV_MAP.items():
        v = os.environ.get(env)
        if v not in (None, ""):
            cfg[key] = v
    for k in ("port", "rotate_hours", "sync_hours", "min_backdrop_width"):
        if k in cfg:
            cfg[k] = _num(cfg[k])
    if isinstance(cfg.get("fallback_to_tmdb"), str):
        cfg["fallback_to_tmdb"] = cfg["fallback_to_tmdb"].strip().lower() not in ("0", "false", "no", "off")
    # LISTS env: "key=username/slug" entries separated by newlines or commas
    raw = os.environ.get("LISTS", "")
    entries = [e.strip() for e in raw.replace(",", "\n").splitlines() if e.strip()]
    if entries:
        cfg["lists"] = []
        for e in entries:
            if "=" not in e:
                sys.exit(f"Bad LISTS entry '{e}' - expected key=username/list-slug")
            k, src = e.split("=", 1)
            cfg["lists"].append({"key": k.strip(), "source": src.strip()})
    cfg.setdefault("port", 8099)
    cfg.setdefault("rotate_hours", 48)
    cfg.setdefault("sync_hours", 12)
    cfg.setdefault("image_size", "w1280")        # w780 | w1280 | original
    cfg.setdefault("data_dir", str(BASE / "data"))
    cfg.setdefault("base_url", f"http://localhost:{cfg['port']}")
    cfg.setdefault("admin_token", "")
    cfg.setdefault("min_backdrop_width", 1280)
    cfg.setdefault("tvdb_api_key", "")
    cfg.setdefault("tvdb_pin", "")               # only needed for subscriber-model keys
    cfg.setdefault("fallback_to_tmdb", True)     # shows: use TMDB if TVDB has no background
    missing = [k for k in ("mdblist_api_key", "tmdb_api_key") if not cfg.get(k)]
    if missing or not cfg.get("lists"):
        sys.exit("Missing configuration: need MDBLIST_API_KEY, TMDB_API_KEY and at least one list "
                 "(LISTS env var or config.json). See README.")
    return cfg

CFG = load_config()
DATA = Path(CFG["data_dir"])
ART = DATA / "art"
LISTS = DATA / "lists"
STATE_FILE = DATA / "state.json"
for d in (ART, LISTS):
    d.mkdir(parents=True, exist_ok=True)

LOCK = threading.RLock()
PERIOD = CFG["rotate_hours"] * 3600

# --------------------------------------------------------------------------- state
def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"lists": {}, "noart": []}

STATE = _load_state()

def save_state():
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(STATE, f, indent=1)
    os.replace(tmp, STATE_FILE)

# --------------------------------------------------------------------------- http
def http_get(url, headers=None, retries=4, data=None, method=None):
    h = {"User-Agent": "cover-rotator/1.0", "Accept": "*/*"}
    h.update(headers or {})
    shown = url.split("?")[0]                    # never log API keys
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                try:
                    wait = int(e.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    wait = 2 ** attempt
                log.warning("HTTP %s from %s, retrying in %ss", e.code, shown, wait)
                time.sleep(min(wait, 30))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            log.warning("network error on %s: %s", shown, e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"giving up on {shown}")

# --------------------------------------------------------------------------- MDBList
def mdblist_items(source):
    """source: 'username/list-slug' or a numeric list id. Returns normalised items."""
    path = source.strip("/")
    out, seen, offset, limit = [], set(), 0, 1000
    while True:
        qs = urllib.parse.urlencode({"apikey": CFG["mdblist_api_key"], "limit": limit, "offset": offset})
        try:
            data = json.loads(http_get(f"https://api.mdblist.com/lists/{path}/items?{qs}"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"list '{path}' not found - source must be 'username/list-slug' "
                                   f"(or a numeric list id)") from None
            raise
        if isinstance(data, dict):               # new format: {"movies":[..], "shows":[..]}
            batch = [dict(i, _kind="movie") for i in data.get("movies") or []] + \
                    [dict(i, _kind="show") for i in data.get("shows") or []]
        else:                                    # older format: flat list
            batch = data
        if not batch:
            break
        for i in batch:
            mt = (i.get("mediatype") or i.get("_kind") or "movie").lower()
            kind = "movie" if mt == "movie" else "show"
            tmdb = i.get("id") or i.get("tmdb_id") or None
            it = {
                "type": kind,
                "tmdb": int(tmdb) if tmdb else None,
                "tvdb": i.get("tvdb_id") or None,
                "imdb": i.get("imdb_id") or None,
                "title": i.get("title") or i.get("name") or "?",
                "year": i.get("release_year") or i.get("year"),
            }
            k = ikey(it)
            if k not in seen and not k.endswith(":None"):
                seen.add(k)
                out.append(it)
        if len(batch) < limit:
            break
        offset += limit
    return out

def ikey(it):
    if it["type"] == "show":
        return f"show:{it.get('tvdb') or it.get('tmdb') or it.get('imdb')}"
    return f"movie:{it.get('tmdb') or it.get('imdb')}"

# --------------------------------------------------------------------------- TMDB
def tmdb_get(path, params=None):
    params = dict(params or {})
    headers = {}
    key = CFG["tmdb_api_key"]
    if key.startswith("eyJ"):                    # v4 read-access token
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
    return json.loads(http_get(url, headers))

def resolve_tmdb(it):
    """Use TVDB / IMDb ids to find a TMDB id when MDBList didn't give one."""
    for src, field in (("tvdb_id", "tvdb"), ("imdb_id", "imdb")):
        if it.get(field):
            try:
                r = tmdb_get(f"/find/{it[field]}", {"external_source": src})
            except Exception as e:
                log.warning("find failed for %s: %s", it["title"], e)
                continue
            res = r.get("movie_results" if it["type"] == "movie" else "tv_results") or []
            if res:
                return res[0]["id"]
    return None

def art_path(it):
    return ART / (ikey(it).replace(":", "_") + ".jpg")

class Transient(Exception):
    """Temporary failure (network/API) - don't blacklist the item."""

def _pick_and_download(cands, url_of, lang_of):
    big = [c for c in cands if c.get("width", 0) >= CFG["min_backdrop_width"]] or cands
    # prefer textless (no title/logo burned in), then English, then best score, then widest
    big.sort(key=lambda c: (lang_of(c) is None, lang_of(c) in ("en", "eng"),
                            c.get("vote_average", c.get("score", 0)) or 0, c.get("width", 0)),
             reverse=True)
    try:
        return http_get(url_of(big[0]))
    except Exception as e:
        raise Transient(f"download failed: {e}")

def tmdb_backdrop(it):
    tmdb = it.get("tmdb") or resolve_tmdb(it)
    if not tmdb:
        return None
    try:
        imgs = tmdb_get(f"/{'movie' if it['type'] == 'movie' else 'tv'}/{tmdb}/images",
                        {"include_image_language": "null,en"})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Transient(f"TMDB images: {e}")
    except Exception as e:
        raise Transient(f"TMDB images: {e}")
    backs = imgs.get("backdrops") or []
    if not backs:
        return None
    return _pick_and_download(
        backs, lambda b: f"https://image.tmdb.org/t/p/{CFG['image_size']}{b['file_path']}",
        lambda b: b.get("iso_639_1"))

# ---- TVDB v4
TVDB_API = "https://api4.thetvdb.com/v4"
_TVDB = {"token": None, "at": 0}

def tvdb_login():
    body = {"apikey": CFG["tvdb_api_key"]}
    if CFG["tvdb_pin"]:
        body["pin"] = CFG["tvdb_pin"]
    r = json.loads(http_get(f"{TVDB_API}/login", {"Content-Type": "application/json"},
                            data=json.dumps(body).encode(), method="POST"))
    _TVDB["token"], _TVDB["at"] = r["data"]["token"], time.time()

def tvdb_get(path, params=None):
    if not _TVDB["token"] or time.time() - _TVDB["at"] > 20 * 86400:
        tvdb_login()
    url = TVDB_API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    for attempt in (0, 1):
        try:
            return json.loads(http_get(url, {"Authorization": f"Bearer {_TVDB['token']}"}))
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                tvdb_login()
                continue
            raise

def resolve_tvdb(it):
    """TVDB series id: from MDBList, else via TMDB external_ids, else TVDB remote-id search (IMDb)."""
    if it.get("tvdb"):
        return int(it["tvdb"])
    if it.get("tmdb"):
        try:
            t = tmdb_get(f"/tv/{it['tmdb']}/external_ids").get("tvdb_id")
            if t:
                return int(t)
        except Exception:
            pass
    if it.get("imdb"):
        try:
            for r in tvdb_get(f"/search/remoteid/{it['imdb']}").get("data") or []:
                if (r.get("series") or {}).get("id"):
                    return int(r["series"]["id"])
        except Exception:
            pass
    return None

def tvdb_backdrop(it):
    tvdb = resolve_tvdb(it)
    if not tvdb:
        return None
    try:
        r = tvdb_get(f"/series/{tvdb}/artworks", {"type": 3})   # type 3 = series background
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Transient(f"TVDB artworks: {e}")
    except Exception as e:
        raise Transient(f"TVDB artworks: {e}")
    arts = [a for a in ((r.get("data") or {}).get("artworks") or [])
            if a.get("type") == 3 and a.get("image")]
    if not arts:
        return None
    full = lambda a: a["image"] if a["image"].startswith("http") else "https://artworks.thetvdb.com" + a["image"]
    return _pick_and_download(arts, full, lambda a: a.get("language"))

_warned_tvdb = False

def fetch_art(it):
    """Movies -> TMDB. Shows/anime -> TVDB (TMDB fallback). Returns Path or None."""
    global _warned_tvdb
    p = art_path(it)
    if p.exists():
        return p
    k = ikey(it)
    if k in STATE["noart"]:
        return None
    try:
        if it["type"] == "movie":
            data = tmdb_backdrop(it)
        elif CFG["tvdb_api_key"]:
            data = tvdb_backdrop(it)
            if data is None and CFG["fallback_to_tmdb"]:
                data = tmdb_backdrop(it)
        else:
            if not _warned_tvdb:
                log.warning("no tvdb_api_key set - using TMDB for shows")
                _warned_tvdb = True
            data = tmdb_backdrop(it)
    except Transient as e:
        log.warning("%s: %s", it["title"], e)
        return None
    if data is None:
        STATE["noart"].append(k); save_state()
        return None
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    log.info("art saved: %s (%s)", it["title"], it["type"])
    return p

# --------------------------------------------------------------------------- lists
def list_defs():
    return {l["key"]: l for l in CFG["lists"]}

def load_items(key):
    try:
        return json.loads((LISTS / f"{key}.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def sync_list(key):
    src = list_defs()[key]["source"]
    log.info("syncing %s (%s)", key, src)
    items = mdblist_items(src)
    if not items:
        log.warning("%s returned 0 items - keeping previous copy", key)
        return
    (LISTS / f"{key}.json").write_text(json.dumps(items))
    with LOCK:
        STATE["lists"].setdefault(key, {})["synced_at"] = time.time()
        save_state()
    log.info("%s: %d items", key, len(items))

def due(key):
    st = STATE["lists"].get(key, {})
    return not st.get("file") or time.time() - st.get("picked_at", 0) >= PERIOD

def rotate(key, force=False, blocking=True):
    """Pick a new random item if due (or forced). Returns True if a pick happened."""
    if not LOCK.acquire(blocking=blocking):
        return False
    try:
        st = STATE["lists"].setdefault(key, {})
        if not force and not due(key):
            return False
        items = load_items(key)
        if not items:
            try:
                sync_list(key); items = load_items(key)
            except Exception as e:
                log.error("cannot sync %s: %s", key, e)
        if not items:
            return False

        cur = st.get("item_key")
        ok = [i for i in items if ikey(i) not in STATE["noart"]]
        used = set(st.get("used", []))
        pool = [i for i in ok if ikey(i) not in used and ikey(i) != cur]
        if not pool:                              # everything shown once -> new cycle
            used = set()
            pool = [i for i in ok if ikey(i) != cur] or ok
        random.shuffle(pool)

        for it in pool:
            p = fetch_art(it)
            if p:
                now = time.time()
                prev = st.get("picked_at")
                if prev and not force:            # stay on a fixed 48h grid, no drift
                    now = prev + int((now - prev) // PERIOD) * PERIOD
                used.add(ikey(it))
                st.update(item_key=ikey(it), file=p.name, title=it["title"], year=it.get("year"),
                          picked_at=now, used=sorted(used))
                save_state()
                log.info("[%s] new cover: %s", key, it["title"])
                return True
        log.warning("[%s] no item with usable art found", key)
        return False
    finally:
        LOCK.release()

def cover_url(key):
    return f"{CFG['base_url'].rstrip('/')}/cover/{key}.jpg"

# --------------------------------------------------------------------------- background worker
def worker():
    while True:
        for key in list_defs():
            try:
                st = STATE["lists"].get(key, {})
                if time.time() - st.get("synced_at", 0) >= CFG["sync_hours"] * 3600:
                    sync_list(key)
                rotate(key)
            except Exception as e:
                log.error("worker error on %s: %s", key, e)
        time.sleep(600)

# --------------------------------------------------------------------------- web
class H(BaseHTTPRequestHandler):
    server_version = "cover-rotator"

    def log_message(self, fmt, *a):
        log.debug(fmt, *a)

    def _send(self, code, body=b"", ctype="text/plain", extra=None, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        url = urllib.parse.urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]

        if parts[:1] == ["cover"] and len(parts) == 2:
            key = parts[1].rsplit(".", 1)[0]
            if key not in list_defs():
                return self._send(404, b"unknown list", head=head)
            # rotate lazily if due; if another thread is mid-rotation, serve the old image
            if due(key):
                rotate(key, blocking=not STATE["lists"].get(key, {}).get("file"))
            st = STATE["lists"].get(key, {})
            f = ART / st["file"] if st.get("file") else None
            if not f or not f.exists():
                return self._send(503, b"no cover available yet", head=head)
            etag = f'"{st["file"]}-{int(st["picked_at"])}"'
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", extra={"ETag": etag}, head=head)
            return self._send(200, f.read_bytes(), "image/jpeg", head=head, extra={
                "ETag": etag, "Cache-Control": "public, max-age=900"})

        if parts[:1] == ["rotate"] and len(parts) == 2:
            q = urllib.parse.parse_qs(url.query)
            if not CFG["admin_token"] or q.get("token", [""])[0] != CFG["admin_token"]:
                return self._send(403, b"forbidden", head=head)
            if parts[1] not in list_defs():
                return self._send(404, b"unknown list", head=head)
            rotate(parts[1], force=True)
            return self._send(200, b"rotated", head=head)

        if parts[:1] == ["health"]:
            return self._send(200, b"ok", head=head)

        if parts[:1] == ["status"]:
            out = {k: {"url": cover_url(k), "title": STATE["lists"].get(k, {}).get("title"),
                       "next_rotation": (STATE["lists"].get(k, {}).get("picked_at", 0) + PERIOD)}
                   for k in list_defs()}
            return self._send(200, json.dumps(out, indent=1).encode(), "application/json", head=head)

        if not parts:
            rows = "".join(
                f'<div style="margin:12px"><b>{k}</b> &mdash; {STATE["lists"].get(k, {}).get("title", "(pending)")}<br>'
                f'<code>{cover_url(k)}</code><br><img src="/cover/{k}.jpg" width="400"></div>'
                for k in list_defs())
            return self._send(200, f"<html><body style='font-family:sans-serif'>{rows}</body></html>".encode(),
                              "text/html", head=head)
        self._send(404, b"not found", head=head)

# --------------------------------------------------------------------------- CLI
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    only = sys.argv[2] if len(sys.argv) > 2 else None
    keys = [only] if only else list(list_defs())

    if cmd == "serve":
        threading.Thread(target=worker, daemon=True).start()
        srv = ThreadingHTTPServer(("0.0.0.0", CFG["port"]), H)
        log.info("listening on :%s", CFG["port"])
        srv.serve_forever()
    elif cmd == "sync":
        for k in keys:
            try: sync_list(k)
            except Exception as e: log.error("[%s] sync failed: %s", k, e)
    elif cmd == "rotate":
        for k in keys:
            try:
                if not load_items(k): sync_list(k)
                rotate(k, force=True)
            except Exception as e: log.error("[%s] rotate failed: %s", k, e)
    elif cmd == "prefetch":
        for k in keys:
            try:
                for it in load_items(k) or (sync_list(k) or load_items(k)):
                    fetch_art(it); time.sleep(0.15)
            except Exception as e: log.error("[%s] prefetch failed: %s", k, e)
    elif cmd == "urls":
        for k in list_defs(): print(f"{k:30} {cover_url(k)}")
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
