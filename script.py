import json
import os
import urllib.request
import urllib.parse
import re
import sys
import importlib
import subprocess
import hashlib

# helper: ensure a python package is importable, install via pip if missing
def ensure_package(module_name, pip_name=None):
    """
    Try to import module_name; if ImportError, run `python -m pip install pip_name`
    (or module_name if pip_name is None) and re-import. Returns the module on
    success or None on failure.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError:
        to_install = pip_name or module_name
        print(f"'{module_name}' not found — attempting to install '{to_install}'...")
        try:
            rc = subprocess.call([sys.executable, "-m", "pip", "install", to_install])
        except Exception as e:
            print(f"Failed to run pip installer: {e}")
            return None
        if rc != 0:
            print(f"pip install exited with code {rc}")
            return None
        try:
            return importlib.import_module(module_name)
        except Exception as e:
            print(f"Installed but failed to import '{module_name}': {e}")
            return None

# ensure BeautifulSoup (bs4) is available
_bs4 = ensure_package("bs4", "beautifulsoup4")
if not _bs4:
    print("Required package 'beautifulsoup4' could not be installed. Please install it and rerun.")
    sys.exit(1)

# Detect if running on Windows
IS_WINDOWS = (os.name == "nt") or sys.platform.startswith("win")

if IS_WINDOWS:
    _win_curses = ensure_package("curses", "windows-curses")
    if not _win_curses:
        print("Required package 'windows-curses' could not be installed. Please install it and rerun.")
        sys.exit(1)

import curses
from bs4 import BeautifulSoup
import time
import shutil

CACHE_FILE = "rom_cache.json"
CONFIG_FILE = "config.json"
CONFIG_VERSION = 3

# ------------------------------
# Load configuration
# ------------------------------
def load_config():
    # create a sample config (with download folders + ids) if missing
    # updated for the new configuration version
    if not os.path.exists(CONFIG_FILE):
        sample = {
            "_meta": {
                "version" : CONFIG_VERSION
            },
            "systems": {
                "Nintendo Gameboy": {           # fullname for the system
                    "id": "gb",                 # system ID
                    "urls": ["https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy/"],   # URLs for scraping
                    "entries": "tbody tr",
                    "fields": {                 # sample field selectors
                    "name": "td.link a",    # game name
                    "url": "td.link a",     # download URL
                    "size": "td.size"       # file size
                    },
                    "download_folders": "./roms/gameboy",
                    "ignore": {                     # sample ignore rules : skip links with these substrings
                        "size": "-",                # skip when size is "-" (folders and upper directories in Myrient)
                        "name_contains": "Parent"   # skip when name contains "Parent"
                    },
                    "regions": {     # sample region rules : search these substrings in game names
                        "USA": [
                            "(USA)",
                            "(U)",
                            "US"
                        ],
                        "Europe": [
                            "(Europe)",
                            "(E)",
                            "EU"
                        ],
                        "Japan": [
                            "(Japan)",
                            "(J)",
                            "JP"
                        ],
                        "World": [
                            "(World)",
                            "(W)"
                        ]
                    },
                    "types": {      # sample type rules : search these substrings in game names
                        "Demo": [
                            "(Demo)",
                            "Demo"
                        ],
                        "Beta": [
                            "(Beta)",
                            "Beta"
                        ],
                        "Hack": [
                            "(Hack)",
                            "Hack"
                        ],
                        "Translation": [
                            "(Translation)",
                            "Translation"
                        ],
                        "Unlicensed": [
                            "(Unl)",
                            "Unlicensed"
                        ],
                        "Homebrew": [
                            "(Homebrew)",
                            "Homebrew"
                        ],
                        "Aftermarket": [
                            "(Aftermarket)",
                            "Aftermarket"
                        ]
                    }
                }
            }
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)
            print("Created sample config.json — edit it before running again!")
            sys.exit()

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
        if config.get("_meta", {}).get("version") != CONFIG_VERSION:
            print(f"Config version mismatch: {config.get('_meta', {}).get('version')} != {CONFIG_VERSION}")
            sys.exit()
        return config
# ------------------------------
# Load or scrape games
# ------------------------------
def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

# save the config (called when UI edits folders)
def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def compute_config_hash(cfg):
    """
    Compute a stable SHA256 hash of the config dict.
    Falls back to hashing the raw file bytes if json dump fails.
    """
    try:
        s = json.dumps(cfg, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(s.encode('utf-8')).hexdigest()
    except Exception:
        try:
            with open(CONFIG_FILE, 'rb') as f:
                data = f.read()
            return hashlib.sha256(data).hexdigest()
        except Exception:
            return ''


def categorize_by_region(games, region_config):
    # If no region rules provided, place all games into "Unknown"
    if not region_config:
        return {"Unknown": list(games)}

    # Prepare buckets for each defined region and a fallback "Unknown"
    categorized = {region: [] for region in region_config.keys()}
    categorized["Unknown"] = []

    for g in games:
        name = g.get("name", "")
        matched_any = False
        # Allow a game to belong to multiple regions: append to every matching region
        for region, patterns in region_config.items():
            if not patterns:
                continue
            for pat in patterns:
                if not pat:
                    continue
                if pat.lower() in name.lower():
                    # ensure we add the game once per region
                    if g not in categorized[region]:
                        categorized[region].append(g)
                    matched_any = True
                    break
        if not matched_any:
            categorized["Unknown"].append(g)
    return categorized

def categorize_by_type(games, type_config):
    # If no type rules provided, put all games into "None"
    if not type_config:
        return {"None": list(games)}

    categorized = {type_: [] for type_ in type_config.keys()}
    categorized["None"] = []

    for g in games:
        name = g.get("name", "")
        matched_any = False
        # Allow a game to belong to multiple types: append to every matching type
        for type_, patterns in type_config.items():
            if not patterns:
                continue
            for pat in patterns:
                if not pat:
                    continue
                if pat.lower() in name.lower():
                    if g not in categorized[type_]:
                        categorized[type_].append(g)
                    matched_any = True
                    break
        if not matched_any:
            categorized["None"].append(g)
    return categorized


def scrape_games(base_url, config):
    print(f"Scraping games from {base_url} ...")
    try:
        resp = urllib.request.urlopen(base_url)
    except Exception as e:
        print(f"Error fetching {base_url}: {e}")
        return []
    soup = BeautifulSoup(resp.read(), "html.parser")
    games = []

    entries = soup.select(config.get("entries", "a"))
    field_name = config["fields"].get("name", "a")
    field_url = config["fields"].get("url", "a")
    field_size = config["fields"].get("size")

    ignore_name = config.get("ignore", {}).get("name_contains", "")
    ignore_size = config.get("ignore", {}).get("size", "")

    for entry in entries:
        name_tag = entry.select_one(field_name)
        url_tag = entry.select_one(field_url)
        size_tag = entry.select_one(field_size) if field_size else None

        if not name_tag or not url_tag:
            continue

        name = name_tag.text.strip()
        href = url_tag.get("href")
        size = size_tag.text.strip() if size_tag else "?"

        if ignore_name and ignore_name.lower() in name.lower():
            continue
        if ignore_size and size.strip() == ignore_size:
            continue

        if not href:
            continue
        if not href.startswith("http"):
            href = base_url + href

        games.append({
            "name": name,
            "url": href,
            "size": size
        })

    print(f"Found {len(games)} total games!")

    # NEW: categorize by region (only for display)
    categorized = categorize_by_region(games, config.get("regions"))
    for region, lst in categorized.items():
        print(f"  🌎 {region}: {len(lst)} games")

    # NEW: categorize by type (only for display)
    categorized_types = categorize_by_type(games, config.get("types"))
    for type_, lst in categorized_types.items():
        print(f"  🎮 {type_}: {len(lst)} games")

    # Return the flat list expected by the curses UI
    return games


# small helpers for the curses UI
def get_system_entries(systems):
    """
    Return a dict of system entries from the loaded config, filtering out
    top-level keys like 'download_folders' which are not systems.
    """
    return {k: v for k, v in systems.items() if isinstance(v, dict)}

def get_system_id(system_name, systems):
    """
    Return the 'id' for a given system from the config, or empty string.
    """
    info = systems.get(system_name)
    if isinstance(info, dict):
        return info.get("id", "")
    return ""

# Cache config directory path at module level
CONFIG_DIR = os.path.dirname(os.path.abspath(CONFIG_FILE))

def normalize_download_folders(folders):
    """
    Normalize download_folders which can be a string or a list into a list.
    Also expand ~, environment vars and resolve relative paths relative to the
    config file directory so './roms' -> '/abs/path/to/repo/roms'.
    """
    if not folders:
        return []
    # allow a single string or a list
    if isinstance(folders, str):
        folders = [folders]
    if not isinstance(folders, list):
        return []

    out = []
    for f in folders:
        if not isinstance(f, str):
            continue
        p = f.strip()
        # expand user and environment variables
        p = os.path.expanduser(os.path.expandvars(p))
        # if relative, resolve against the config file directory
        if not os.path.isabs(p):
            p = os.path.normpath(os.path.join(CONFIG_DIR, p))
        else:
            p = os.path.normpath(p)
        out.append(p)
    return out

# helper to produce a pretty filename from url or name
def sanitize_filename_from_url_or_name(url, name=None):
    # try to extract basename from url (unquote percent-encoding)
    try:
        path = urllib.parse.unquote(url.split('?')[0])
        base = os.path.basename(path)
    except Exception:
        base = ''
    candidate = base or (name or 'download')
    # convert plus to space
    candidate = candidate.replace('+', ' ')
    # replace characters that are not alnum, dot, dash, space, parentheses with space
    candidate = re.sub(r"[^\w\.\-\s()]+", ' ', candidate)
    # collapse whitespace
    candidate = re.sub(r'\s+', ' ', candidate).strip()
    # if no extension, try to add from original base or name
    if '.' not in candidate:
        ext = ''
        if '.' in base:
            ext = base.split('.')[-1]
        elif isinstance(name, str) and '.' in name:
            ext = name.split('.')[-1]
        if ext:
            candidate = f"{candidate}.{ext}"
    return candidate


def get_download_folders_for_system(system_name, systems):
    """
    Return a list of download folders for a given system, preferring a
    system-specific setting and falling back to the global 'download_folders'.
    Supports either 'download_folders' (list) or legacy 'download_folder' (string).
    """
    info = systems.get(system_name)
    if isinstance(info, dict):
        if info.get("download_folders"):
            return normalize_download_folders(info.get("download_folders"))
        if info.get("download_folder"):
            return normalize_download_folders(info.get("download_folder"))
    # check global keys
    if systems.get("download_folders"):
        return normalize_download_folders(systems.get("download_folders"))
    if systems.get("download_folder"):
        return normalize_download_folders(systems.get("download_folder"))
    return []

# helper functions for downloading
def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def sizeof_fmt(num, suffix='B'):
    if num is None:
        return 'Unknown'
    num = float(num)
    for unit in ['','K','M','G','T','P']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"


# UI globals (initialized when curses session starts)
ICON_GAME = '🎮'
# ICON_ARROW = '➡️'
ICON_ARROW = '→'        # simpler arrow for better alignment on different terminals
ICON_FOLDER = '📁'
ICON_SEARCH = '🔎'
# ICON_DL = '⬇️'
ICON_DL = '↓'           # simpler down arrow for better alignment on different terminals
ICON_OK = '✅'
ICON_ERR = '❌'

# emojis = [ICON_GAME, ICON_ARROW, ICON_FOLDER, ICON_SEARCH, ICON_DL, ICON_OK, ICON_ERR] 

# aligned_emojis = []

# fudge = {
#     "➡️": 1,
#     "⬇️": 2
# }

# max_width = max(wcswidth(e) + fudge.get(e, 0) for e in emojis)

# for e in emojis:
#     width = wcswidth(e) + fudge.get(e, 0)
#     padding = max_width - width
#     print(e + " " * padding + " | aligned!")

# for e in aligned_emojis:
#     print(e + " | aligned!")

HEADER_ATTR = None
INSTR_ATTR = None
SELECTED_ATTR = None
NORMAL_ATTR = None
SIZE_ATTR = None
INFO_ATTR = None
ERR_ATTR = None


def init_ui_colors(stdscr):
    """Initialize curses color pairs and set module-level attribute globals.
    Call this once after curses has been initialized (inside curses_main).
    """
    global HEADER_ATTR, INSTR_ATTR, SELECTED_ATTR, NORMAL_ATTR, SIZE_ATTR, INFO_ATTR, ERR_ATTR
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)   # header
        curses.init_pair(2, curses.COLOR_GREEN, -1)  # success / selected
        curses.init_pair(3, curses.COLOR_RED, -1)    # error
        curses.init_pair(4, curses.COLOR_YELLOW, -1) # info
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)# accent / size
        curses.init_pair(6, curses.COLOR_BLUE, -1)   # instructions / secondary

        HEADER_ATTR = curses.color_pair(1) | curses.A_BOLD
        INSTR_ATTR = curses.color_pair(6)
        SELECTED_ATTR = curses.color_pair(2) | curses.A_BOLD | curses.A_UNDERLINE
        NORMAL_ATTR = curses.A_NORMAL
        SIZE_ATTR = curses.color_pair(5)
        INFO_ATTR = curses.color_pair(4)
        ERR_ATTR = curses.color_pair(3) | curses.A_BOLD
    except Exception:
        # fallback attributes
        HEADER_ATTR = curses.A_BOLD
        INSTR_ATTR = curses.A_NORMAL
        SELECTED_ATTR = curses.A_REVERSE
        NORMAL_ATTR = curses.A_NORMAL
        SIZE_ATTR = curses.A_NORMAL
        INFO_ATTR = curses.A_NORMAL
        ERR_ATTR = curses.A_BOLD


# Horizontal scrolling/marquee support

# state for horizontal marquee/scrolling of long strings
SCROLL_STATES = {}

DEFAULT_TIMEOUT_MS = 120  # main loop will refresh ~8-9 times/sec


def addstr_scroll(stdscr, y, x, text, attr=None, key=None, speed=6, gap=4, max_width=None):
    """Like stdscr.addstr but will clamp to terminal width and, when the text
    is longer than available space, show a horizontal scrolling/marquee for
    the given key (or position if key is None).

    - stdscr: the curses window
    - y, x: position to draw
    - text: the string to draw
    - attr: optional curses attribute
    - key: unique hashable used to keep per-item scroll state (defaults to (y,x))
    - speed: characters per second to advance when scrolling
    - gap: number of spaces to insert between wrap-around
    - max_width: optional integer to override / cap the available width used
                 for this field even if the terminal is wider.
    """
    try:
        h, w = stdscr.getmaxyx()
        avail = max(0, w - x)
        # if caller provided a max_width, respect it (cap to terminal as well)
        if isinstance(max_width, int) and max_width > 0:
            avail = min(avail, max_width)

        if avail <= 0:
            return

        display = text
        if len(text) <= avail:
            # short enough to fit; clear any previous state
            state_key = key if key is not None else (y, x)
            if state_key in SCROLL_STATES:
                SCROLL_STATES.pop(state_key, None)
            if attr is not None:
                try:
                    stdscr.addstr(y, x, display[:avail], attr)
                except Exception:
                    stdscr.addstr(y, x, display[:avail])
            else:
                try:
                    stdscr.addstr(y, x, display[:avail])
                except Exception:
                    pass
            return

        # needs scrolling
        state_key = key if key is not None else (y, x)
        now = time.time()
        buf = text + (" " * gap)
        L = len(buf)

        st = SCROLL_STATES.get(state_key)
        if not st:
            st = {"pos": 0, "last": now}
            SCROLL_STATES[state_key] = st

        # compute how many characters to advance based on elapsed time
        elapsed = now - st["last"]
        advance = int(elapsed * speed)
        if advance > 0:
            st["pos"] = (st["pos"] + advance) % L
            st["last"] = now

        doubled = buf + buf
        start_pos = st["pos"] % L
        display = doubled[start_pos:start_pos + avail]

        # finally draw
        if attr is not None:
            try:
                stdscr.addstr(y, x, display, attr)
            except Exception:
                try:
                    stdscr.addstr(y, x, display)
                except Exception:
                    pass
        else:
            try:
                stdscr.addstr(y, x, display)
            except Exception:
                pass
    except Exception:
        # best-effort fallback
        try:
            term_w = stdscr.getmaxyx()[1]
            use_w = term_w - x
            if isinstance(max_width, int) and max_width > 0:
                use_w = min(use_w, max_width)
            if attr is not None:
                stdscr.addstr(y, x, text[:max(0, use_w)], attr)
            else:
                stdscr.addstr(y, x, text[:max(0, use_w)])
        except Exception:
            pass



def download_with_progress(selected, dest_path, stdscr, h, w):
    url = selected.get('url')
    name = selected.get('name', '')
    start = time.time()
    success = False
    downloaded = 0
    total = None
    err_msg = None
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req)
        total_raw = resp.getheader('Content-Length')
        total = int(total_raw) if total_raw and total_raw.isdigit() else None
        downloaded = 0
        chunk = 8192
        with open(dest_path, 'wb') as out:
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                out.write(data)
                downloaded += len(data)

                elapsed = time.time() - start
                speed = downloaded / elapsed if elapsed > 0 else 0
                percent = (downloaded / total * 100) if total else 0
                eta = int((total - downloaded) / speed) if total and speed > 0 else 0

                # draw progress UI
                try:
                    stdscr.clear()
                    header = f"{ICON_DL} Downloading: {name}"
                    stdscr.addstr(0, 2, header, HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
                    stdscr.addstr(1, 2, f"To: {dest_path}", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(2, 2, f"Size: {sizeof_fmt(total)}", SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(3, 2, f"Downloaded: {sizeof_fmt(downloaded)} ({percent:.1f}%)", SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(4, 2, f"Speed: {sizeof_fmt(speed)}/s  Elapsed: {int(elapsed)}s  ETA: {eta}s", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)

                    bar_w = max(10, w - 12)
                    if total:
                        filled = int(bar_w * downloaded / total)
                    else:
                        filled = int((time.time() * 3) % bar_w)
                    bar = '[' + '#' * filled + '-' * (bar_w - filled) + ']'
                    stdscr.addstr(6, 2, bar[:w-4], SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                    stdscr.refresh()
                except Exception:
                    pass

        success = True
    except Exception as e:
        err_msg = str(e)
        success = False

    # Final summary screen (success or failure)
    try:
        elapsed = time.time() - start
        stdscr.clear()

        if success:
            stdscr.addstr(0, 2, f"{ICON_OK} Download successful", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
            stdscr.addstr(2, 2, f"Name: {name}", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
            stdscr.addstr(3, 2, f"Saved to: {dest_path}", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
            stdscr.addstr(4, 2, f"Total: {sizeof_fmt(downloaded)}", SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
            try:
                avg = sizeof_fmt(int(downloaded/elapsed)) if elapsed > 0 else '0B'
            except Exception:
                avg = '0B'
            stdscr.addstr(5, 2, f"Time: {int(elapsed)}s  Avg speed: {avg}/s", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
        else:
            stdscr.addstr(0, 2, f"{ICON_ERR} Download failed", ERR_ATTR if ERR_ATTR is not None else curses.A_BOLD)
            stdscr.addstr(2, 2, f"Name: {name}")
            stdscr.addstr(3, 2, f"URL: {url}")
            stdscr.addstr(4, 2, f"Error: {err_msg}")
            stdscr.addstr(6, 2, "Partial bytes downloaded: " + sizeof_fmt(downloaded))

        stdscr.addstr(h - 2, 2, "Press any key to continue...")
        stdscr.refresh()
        stdscr.getch()
    except Exception:
        pass


# wget-based downloader (uses system wget to handle throttling/resuming)
def download_with_wget(selected, dest_path, stdscr, h, w):
    url = selected.get('url')
    name = selected.get('name', '')
    start = time.time()
    wget_path = shutil.which('wget')
    if not wget_path:
        # fallback message
        try:
            stdscr.clear()
            stdscr.addstr(0, 2, "wget not found on system; falling back to builtin downloader.")
            stdscr.addstr(2, 2, "Press any key to continue...")
            stdscr.refresh()
            stdscr.getch()
        except Exception:
            pass
        return download_with_progress(selected, dest_path, stdscr, h, w)

    # spawn wget with resume and output to file
    cmd = [wget_path, '-c', '-O', dest_path, url]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    except Exception as e:
        try:
            stdscr.clear()
            stdscr.addstr(0, 2, f"Failed to start wget: {e}")
            stdscr.addstr(2, 2, "Press any key to continue...")
            stdscr.refresh()
            stdscr.getch()
        except Exception:
            pass
        return

    # while wget runs, show combined progress: tail wget output and stat file size
    total = None
    try:
        # try to get total from headers first
        try:
            req = urllib.request.urlopen(url)
            total_raw = req.getheader('Content-Length')
            total = int(total_raw) if total_raw and total_raw.isdigit() else None
        except Exception:
            total = None

        while True:
            # read any available output line
            line = proc.stdout.readline()
            if line:
                # display last line of wget output
                stdscr.clear()
                stdscr.addstr(0, 2, f"{ICON_DL} Downloading with wget: {name}", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
                stdscr.addstr(1, 2, f"To: {dest_path}")
                try:
                    stdscr.addstr(3, 2, line.strip()[:w-4])
                except Exception:
                    pass
            # update file size based progress
            try:
                if os.path.exists(dest_path):
                    downloaded = os.path.getsize(dest_path)
                else:
                    downloaded = 0
                elapsed = time.time() - start
                speed = downloaded / elapsed if elapsed > 0 else 0
                percent = (downloaded / total * 100) if total else 0
                eta = int((total - downloaded) / speed) if total and speed > 0 else 0
                stdscr.addstr(2, 2, f"Size: {sizeof_fmt(total)}")
                stdscr.addstr(4, 2, f"Downloaded: {sizeof_fmt(downloaded)} ({percent:.1f}%)")
                stdscr.addstr(5, 2, f"Speed: {sizeof_fmt(speed)}/s  Elapsed: {int(elapsed)}s  ETA: {eta}s")

                bar_w = max(10, w - 12)
                if total:
                    filled = int(bar_w * downloaded / total)
                else:
                    filled = int((time.time() * 3) % bar_w)
                bar = '[' + '#' * filled + '-' * (bar_w - filled) + ']'
                stdscr.addstr(7, 2, bar[:w-4], SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                stdscr.refresh()
            except Exception:
                pass

            if proc.poll() is not None:
                break

        rc = proc.wait()
        success = (rc == 0)
    except Exception:
        success = False

    # final summary similar to builtin
    try:
        elapsed = time.time() - start
        stdscr.clear()
        if success:
            stdscr.addstr(0, 2, f"{ICON_OK} Download (wget) complete", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
            stdscr.addstr(2, 2, f"Name: {name}")
            stdscr.addstr(3, 2, f"Saved to: {dest_path}")
            try:
                downloaded = os.path.getsize(dest_path)
            except Exception:
                downloaded = 0
            stdscr.addstr(4, 2, f"Total: {sizeof_fmt(downloaded)}")
            try:
                avg = sizeof_fmt(int(downloaded/elapsed)) if elapsed > 0 else '0B'
            except Exception:
                avg = '0B'
            stdscr.addstr(5, 2, f"Time: {int(elapsed)}s  Avg speed: {avg}/s")
        else:
            stdscr.addstr(0, 2, f"{ICON_ERR} wget download failed", ERR_ATTR if ERR_ATTR is not None else curses.A_BOLD)
            stdscr.addstr(2, 2, f"Name: {name}")
            stdscr.addstr(3, 2, f"URL: {url}")
            stdscr.addstr(4, 2, "See wget output above or check network.")

        stdscr.addstr(h - 2, 2, "Press any key to continue...")
        stdscr.refresh()
        stdscr.getch()
    except Exception:
        pass


# helper wrapper to ask user if they want to use wget
def perform_download(selected, dest_path, stdscr, h, w):
    try:
        try:
            stdscr.addstr(h - 2, 2, "Use wget for this download? (y/N): ")
            stdscr.clrtoeol()
            stdscr.refresh()
            set_input_blocking(stdscr, True)
            ch = stdscr.getkey()
        except Exception:
            ch = ''
        finally:
            set_input_blocking(stdscr, False)
        if ch.lower() == 'y':
            download_with_wget(selected, dest_path, stdscr, h, w)
        else:
            download_with_progress(selected, dest_path, stdscr, h, w)
    except Exception:
        # fallback
        download_with_progress(selected, dest_path, stdscr, h, w)


# ------------------------------
# Curses UI
# ------------------------------
def curses_main(stdscr, systems, cache):
    curses.curs_set(0)
    stdscr.timeout(DEFAULT_TIMEOUT_MS)
    stdscr.keypad(True)

    # reduce flicker:
    try:
        stdscr.leaveok(True)   # don't move the cursor during refresh
        stdscr.scrollok(False) # avoid scrolling side effects
    except Exception:
        pass

    # initialize colors and icon styles
    init_ui_colors(stdscr)

    # note: 'systems' may contain top-level keys (like download_folders) — filter
    all_systems = get_system_entries(systems)
    system_names = list(all_systems.keys())
    system_idx = 0

    # selection/state
    game_idx = 0              # index into flat list when not grouped
    # grouping: None / 'region' / 'type'
    group_mode = None
    region_idx = 0            # which region is shown when grouped by region
    region_game_idx = 0       # index into current region list
    type_idx = 0              # which type is shown when grouped by type
    type_game_idx = 0         # index into current type list

    # search state
    search_query = None  # lowercase query or None

    # keep track of the last selected item's scroll key so we can reset it
    prev_selected_key = None

    while True:
        # use erase() (faster) and batch-refresh at the end
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        current_sys = system_names[system_idx]
        games = cache.get(current_sys, [])

        # Header with icon + system name
        try:
            stdscr.addstr(0, 2, f"{ICON_GAME}{current_sys} — {len(games)} games"[:w-4], HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
        except Exception:
            stdscr.addstr(0, 2, f"{current_sys} — {len(games)} games")

        # Instructions (include grouping keys)
        instr_text = "↑↓ scroll | ←→ system | ENTER open/download | r toggle regions | t toggle types | TAB switch region | f search | i info | q quit"
        try:
            addstr_scroll(stdscr, 1, 2, instr_text, INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
        except Exception:
            addstr_scroll(stdscr, 1, 2, instr_text)

        # show system id + one download folder in header (if present)
        sys_id = get_system_id(current_sys, systems)
        dfolders = get_download_folders_for_system(current_sys, systems)
        if dfolders:
            try:
                stdscr.addstr(0, w - 40, f"[id:{sys_id}] {os.path.basename(dfolders[0])}"[:38], SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
            except Exception:
                stdscr.addstr(0, w - 40, f"[id:{sys_id}] {os.path.basename(dfolders[0])}"[:38])

        # compute the base list depending on grouping & region
        if group_mode is None:
            base_list = games
        elif group_mode == 'region':
            categorized = categorize_by_region(games, systems[current_sys].get("regions"))
            region_names = list(categorized.keys()) or ["Unknown"]
            region_idx = region_idx % len(region_names) if region_names else 0
            cur_region = region_names[region_idx]
            base_list = categorized.get(cur_region, [])
        elif group_mode == 'type':
            categorized = categorize_by_type(games, systems[current_sys].get("types"))
            type_names = list(categorized.keys()) or ["None"]
            type_idx = type_idx % len(type_names) if type_names else 0
            cur_type = type_names[type_idx]
            base_list = categorized.get(cur_type, [])
        else:
            base_list = games

        # apply search filter if active
        if search_query:
            display_list = [g for g in base_list if search_query in g["name"].lower()]
        else:
            display_list = base_list

        # header line describing current view
        if search_query:
            stdscr.addstr(2, 2, f"Search: '{search_query}' — {len(display_list)} results")
            list_start_row = 3
        else:
            if group_mode is None:
                stdscr.addstr(2, 2, "Listing: All games")
                list_start_row = 3
            elif group_mode == 'region':
                stdscr.addstr(2, 2, f"Grouped by region: {cur_region} — {len(display_list)} games")
                list_start_row = 4
            elif group_mode == 'type':
                stdscr.addstr(2, 2, f"Grouped by type: {cur_type} — {len(display_list)} games")
                list_start_row = 4
            else:
                stdscr.addstr(2, 2, "Listing: All games")
                list_start_row = 3

        # determine start index (viewport) and visible slice
        # keep a viewport so the selected item is centered when possible
        if group_mode is None:
            selected_index = game_idx
        elif group_mode == 'region':
            selected_index = region_game_idx
        elif group_mode == 'type':
            selected_index = type_game_idx
        else:
            selected_index = game_idx

        visible_h = max(1, h - list_start_row - 1)
        # center the selection in the viewport when possible
        start = max(0, selected_index - (visible_h // 2))
        # make sure start doesn't run past the end
        if len(display_list) > visible_h:
            start = min(start, len(display_list) - visible_h)
        else:
            start = 0

        visible = display_list[start:start + (h - list_start_row - 1)]

        # render list (with selection highlight)
        # determine selected visible index
        # use the active index depending on grouping (none / region / type)
        cur_index = (game_idx if group_mode is None else
                     (region_game_idx if group_mode == 'region' else type_game_idx))
        sel_vis = cur_index - start
        for i, game in enumerate(visible):
            row = list_start_row + i
            is_sel = (i == sel_vis)
            prefix = f"{ICON_ARROW} " if is_sel else "   "
            name = game.get("name", "")
            size = game.get("size", "?")
            try:
                if is_sel:
                    stdscr.addstr(row, 2, prefix, SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL)
                    # pass a stable per-item key so scrolling state ties to the item, not to screen row
                    item_key = (current_sys, game.get('url'))
                    addstr_scroll(stdscr, row, 5, name, SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL, key=item_key, max_width=w-20)
                    stdscr.addstr(row, w - 12, size.rjust(10), SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                else:
                    # non-selected lines: reset any scroll state for this item so it restarts when re-selected
                    item_key = (current_sys, game.get('url'))
                    SCROLL_STATES.pop(item_key, None)
                    truncated = name[:max(10, w - 20)]
                    stdscr.addstr(row, 2, prefix + truncated, NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(row, w - 12, size.rjust(10), SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
            except Exception:
                try:
                    stdscr.addstr(row, 2, prefix + name)
                except Exception:
                    pass

        # footer for regions when grouped (and no active global search override)
        if group_mode == 'region':
            regs_line = " | ".join((f"[{r}]" if idx == region_idx else r) for idx, r in enumerate(region_names))
            try:
                stdscr.addstr(h - 1, 2, regs_line[:w - 4], INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
            except Exception:
                stdscr.addstr(h - 1, 2, regs_line[:w - 4])
        elif group_mode == 'type':
            types_line = " | ".join((f"[{t}]" if idx == type_idx else t) for idx, t in enumerate(type_names))
            try:
                stdscr.addstr(h - 1, 2, types_line[:w - 4], INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
            except Exception:
                stdscr.addstr(h - 1, 2, types_line[:w - 4])

        key = stdscr.getch()
        if key == ord('D'):  # Download selected game
            idx = game_idx if group_mode is None else region_game_idx
            selected = display_list[idx] if 0 <= idx < len(display_list) else None
            if selected:
                sys_folders = get_download_folders_for_system(current_sys, systems)
                default = os.path.join(os.path.expanduser("~"), "Downloads")
                dest_choice = None
                if sys_folders:
                    curses.echo()
                    curses.curs_set(1)
                    stdscr.addstr(h - 2, 2, f"Download to system folder [{sys_folders[0]}] (1), default [{default}] (2), other (3): ")
                    stdscr.clrtoeol()
                    stdscr.refresh()
                    # make this input blocking so the prompt waits for the user
                    set_input_blocking(stdscr, True)
                    try:
                        ch = stdscr.getkey()
                    except Exception:
                        ch = ''
                    finally:
                        set_input_blocking(stdscr, False)
                    curses.noecho()
                    curses.curs_set(0)
                if ch == '1' and sys_folders:
                    dest_choice = sys_folders[0]
                elif ch == '2':
                    dest_choice = default
                elif ch == '3':
                    curses.echo()
                    curses.curs_set(1)
                    stdscr.addstr(h - 2, 2, "Enter folder path: " + " " * (w - 18))
                    stdscr.move(h - 2, 19)
                    stdscr.refresh()
                    try:
                        rawp = stdscr.getstr(h - 2, 19, w - 20)
                        pathinp = rawp.decode("utf-8").strip()
                    except Exception:
                        pathinp = ''
                    curses.noecho()
                    curses.curs_set(0)
                    dest_choice = pathinp if pathinp else default
                else:
                    dest_choice = default
                if not dest_choice:
                    dest_choice = default
                dest_choice = os.path.expanduser(dest_choice)
                ensure_dir(dest_choice)
                fname = sanitize_filename_from_url_or_name(selected.get('url'), selected.get('name'))
                dest_path = os.path.join(dest_choice, fname)
                perform_download(selected, dest_path, stdscr, h, w)
                # continue main loop
                continue

        if key == ord('q'):
            break
        elif key == ord('r'):
            # toggle region grouping
            if group_mode == 'region':
                group_mode = None
            else:
                group_mode = 'region'
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            # reset type indices as well
            type_idx = 0
            type_game_idx = 0
            search_query = None
        elif key == ord('t'):
            # toggle type grouping
            if group_mode == 'type':
                group_mode = None
            else:
                group_mode = 'type'
            game_idx = 0
            type_idx = 0
            type_game_idx = 0
            # reset region indices as well
            region_idx = 0
            region_game_idx = 0
            search_query = None
        elif key == 9:  # TAB -> cycle region/type when grouped
            if group_mode == 'region':
                categorized = categorize_by_region(games, systems[current_sys].get("regions"))
                region_names = list(categorized.keys()) or ["Unknown"]
                if region_names:
                    region_idx = (region_idx + 1) % len(region_names)
                    region_game_idx = 0
            elif group_mode == 'type':
                categorized = categorize_by_type(games, systems[current_sys].get("types"))
                type_names = list(categorized.keys()) or ["None"]
                if type_names:
                    type_idx = (type_idx + 1) % len(type_names)
                    type_game_idx = 0
        elif key == ord('f'):  # search (keyword)
            # prompt
            curses.echo()
            curses.curs_set(1)
            set_input_blocking(stdscr, True)
            stdscr.addstr(h - 2, 2, "Search (empty to clear): " + " " * (w - 24))
            stdscr.move(h - 2, 24)
            stdscr.refresh()
            try:
                raw = stdscr.getstr(h - 2, 24, w - 26)
                query = raw.decode("utf-8").strip()
            except Exception:
                query = ""
            set_input_blocking(stdscr, False)
            curses.noecho()
            curses.curs_set(0)

            if not query:
                # clear search
                search_query = None
                game_idx = 0
                region_game_idx = 0
                continue

            search_query = query.lower()
            # reset indices so results start at top
            game_idx = 0
            region_game_idx = 0
            # if no results show temporary message
            if len(display_list) == 0:
                stdscr.addstr(h - 2, 2, f"No results for '{query}'".ljust(w - 4))
                stdscr.refresh()
                curses.napms(1200)
        elif key == ord('i'):  # show info about current system (id + folders)
            curses.echo()
            curses.curs_set(0)
            stdscr.clear()
            stdscr.addstr(0, 2, f"System: {current_sys}")
            stdscr.addstr(1, 2, f"ID: {get_system_id(current_sys, systems)}")
            folders = get_download_folders_for_system(current_sys, systems)
            stdscr.addstr(3, 2, "Download folders:")
            for i, fldr in enumerate(folders):
                stdscr.addstr(4 + i, 4, fldr)
            stdscr.addstr(6 + len(folders), 2, "Press any key to continue...")
            stdscr.refresh()
            # wait for the user (make blocking while waiting)
            set_input_blocking(stdscr, True)
            try:
                stdscr.getch()
            finally:
                set_input_blocking(stdscr, False)
            curses.noecho()
            curses.curs_set(0)
        elif key == ord('g'):  # set global download folders (comma-separated)
            curses.echo()
            curses.curs_set(1)
            try:
                stdscr.addstr(h - 4, 2, "Configure GLOBAL download folders", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
                stdscr.addstr(h - 3, 2, "Comma separated paths (supports ./, ../, ~). Empty to clear.", INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
            except Exception:
                pass
            stdscr.addstr(h - 2, 2, "Set GLOBAL download folders (comma separated, empty to clear):" + " " * 10)
            stdscr.move(h - 2, 60)
            stdscr.refresh()
            # make getstr blocking so user can type
            set_input_blocking(stdscr, True)
            try:
                raw = stdscr.getstr(h - 2, 60, w - 62)
                inp = raw.decode("utf-8").strip()
            except Exception:
                inp = ""
            finally:
                set_input_blocking(stdscr, False)
            curses.noecho()
            curses.curs_set(0)
            if inp == "":
                systems.pop("download_folders", None)
            else:
                systems["download_folders"] = [p.strip() for p in inp.split(",") if p.strip()]
            save_config(systems)
        elif key == ord('d'):  # set download folders for current system
            curses.echo()
            curses.curs_set(1)
            try:
                stdscr.addstr(h - 4, 2, f"Configure download folders for '{current_sys}'", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
                stdscr.addstr(h - 3, 2, "Comma separated paths (supports ./, ../, ~). Empty to clear.", INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
            except Exception:
                pass
            stdscr.addstr(h - 2, 2, f"Set download folders for '{current_sys}' (comma separated, empty to clear):" + " " * 10)
            stdscr.move(h - 2, 70)
            stdscr.refresh()
            # make getstr blocking so user can type
            set_input_blocking(stdscr, True)
            try:
                raw = stdscr.getstr(h - 2, 70, w - 72)
                inp = raw.decode("utf-8").strip()
            except Exception:
                inp = ""
            finally:
                set_input_blocking(stdscr, False)
            curses.noecho()
            curses.curs_set(0)
            if inp == "":
                if current_sys in systems and isinstance(systems[current_sys], dict):
                    systems[current_sys].pop("download_folders", None)
            else:
                if current_sys in systems and isinstance(systems[current_sys], dict):
                    systems[current_sys]["download_folders"] = [p.strip() for p in inp.split(",") if p.strip()]
            save_config(systems)
        elif key == curses.KEY_DOWN:
            if group_mode is None:
                if game_idx < max(0, len(display_list) - 1):
                    game_idx += 1
            elif group_mode == 'region':
                if region_game_idx < max(0, len(display_list) - 1):
                    region_game_idx += 1
            elif group_mode == 'type':
                if type_game_idx < max(0, len(display_list) - 1):
                    type_game_idx += 1
        elif key == curses.KEY_UP:
            if group_mode is None and game_idx > 0:
                game_idx -= 1
            elif group_mode == 'region' and region_game_idx > 0:
                region_game_idx -= 1
            elif group_mode == 'type' and type_game_idx > 0:
                type_game_idx -= 1
        elif key == curses.KEY_RIGHT:
            system_idx = (system_idx + 1) % len(system_names)
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            type_idx = 0
            type_game_idx = 0
            search_query = None
        elif key == curses.KEY_LEFT:
            system_idx = (system_idx - 1) % len(system_names)
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            type_idx = 0
            type_game_idx = 0
            search_query = None
        elif key in [10, 13]:  # ENTER key -> confirm & download
            # pick from the currently displayed filtered list (use active index)
            idx = cur_index
            selected = display_list[idx] if 0 <= idx < len(display_list) else None

            if selected:
                # prepare destinations
                sys_folders = get_download_folders_for_system(current_sys, systems)
                default = os.path.join(os.path.expanduser("~"), "Downloads")
                dest_choice = None
                size_str = selected.get('size', '?')

                # confirmation loop (colorized)
                while True:
                    stdscr.clear()
                    try:
                        stdscr.addstr(0, 2, "Confirm download", HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
                        stdscr.addstr (1, 2, "Name: ", SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL)
                        addstr_scroll(stdscr, 1, 8, f"{selected.get('name')}", SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL, max_width=w-20)
                        stdscr.addstr(2, 2, f"Size: {size_str}", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
                        stdscr.addstr(3, 2, "URL: ", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                        addstr_scroll(stdscr, 3, 8, f"{selected.get('url')}", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL, max_width=w-20)
                        stdscr.addstr(5, 2, "Destination:", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
                    except Exception:
                        stdscr.addstr(0, 2, "Confirm download")

                    stdscr.refresh()

                    line = 6
                    if sys_folders:
                        try:
                            stdscr.addstr(line, 4, f"1) System folder: {sys_folders[0]}", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                        except Exception:
                            stdscr.addstr(line, 4, f"1) System folder: {sys_folders[0]}")
                        line += 1
                    try:
                        stdscr.addstr(line, 4, f"2) Default: {default}", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                    except Exception:
                        stdscr.addstr(line, 4, f"2) Default: {default}")
                    line += 1
                    try:
                        stdscr.addstr(line, 4, "3) Other...", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                    except Exception:
                        stdscr.addstr(line, 4, "3) Other...")
                    line += 2
                    try:
                        stdscr.addstr(line, 2, "Press number to choose, or 'c' to cancel", INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
                    except Exception:
                        stdscr.addstr(line, 2, "Press number to choose, or 'c' to cancel")
                    stdscr.refresh()

                    try:
                        # confirmation input should block so user can respond
                        set_input_blocking(stdscr, True)
                        try:
                            ch = stdscr.getkey()
                        except Exception:
                            ch = ''
                        finally:
                            set_input_blocking(stdscr, False)
                    except Exception:
                        ch = ''

                    if ch == 'c':
                        dest_choice = None
                        break
                    if ch == '1' and sys_folders:
                        dest_choice = sys_folders[0]
                        break
                    if ch == '2':
                        dest_choice = default
                        break
                    if ch == '3':
                        # prompt for custom path
                        curses.echo()
                        curses.curs_set(1)
                        set_input_blocking(stdscr, True)
                        try:
                            stdscr.addstr(line + 1, 2, "Enter folder path: ", INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
                        except Exception:
                            stdscr.addstr(line + 1, 2, "Enter folder path: ")
                        stdscr.move(line + 1, 20)
                        stdscr.refresh()
                        try:
                            rawp = stdscr.getstr(line + 1, 20, w - 22)
                            pathinp = rawp.decode("utf-8").strip()
                        except Exception:
                            pathinp = ''
                        set_input_blocking(stdscr, False)
                        curses.noecho()
                        curses.curs_set(0)
                        dest_choice = pathinp if pathinp else default
                        break

                # after selection
                if dest_choice:
                    dest_choice = os.path.expanduser(dest_choice)
                    ensure_dir(dest_choice)
                    fname = sanitize_filename_from_url_or_name(selected.get('url'), selected.get('name'))
                    dest_path = os.path.join(dest_choice, fname)
                    perform_download(selected, dest_path, stdscr, h, w)
                # continue main loop
                continue

        stdscr.refresh()

def set_input_blocking(stdscr, blocking=True):
    """
    When blocking=True -> set getch/getstr to block (timeout = -1).
    When blocking=False -> set to DEFAULT_TIMEOUT_MS so UI keeps updating.

    If an exception occurs while setting the timeout, it is silently ignored and no error is raised.
    """
    try:
        if blocking:
            stdscr.timeout(-1)
        else:
            stdscr.timeout(DEFAULT_TIMEOUT_MS)
    except Exception:
        pass


# ------------------------------
# Main entry
# ------------------------------
def main():
    config = load_config()
    config_meta = config.get("_meta") or {}

    cache = load_cache()
    current_cfg_hash = compute_config_hash(config)
    cached_meta = cache.get("_meta") or {}
    cached_cfg_hash = cached_meta.get("config_hash")

    # Normalize legacy cached entries:
    # - Ensure _meta stays a dict (warn & reset if corrupted)
    # - If a system cache value is a dict of lists (old categorized form),
    #   flatten it into a single list of entries.
    for k, v in list(cache.items()):
        if k == "_meta":
            if not isinstance(v, dict):
                print(f"Warning: cached _meta has unexpected type {type(v)}; resetting _meta.")
                cache["_meta"] = {}
            continue

        # Flatten system entries saved as {bucket_name: [items]} -> [items]
        if isinstance(v, dict):
            if any(isinstance(sub, list) for sub in v.values()):
                flat = []
                for sub in v.values():
                    if isinstance(sub, list):
                        flat.extend(sub)
                cache[k] = flat

    def get_system_urls(info):
        """
        Helper to extract a list of URLs from a system info dict.
        Supports 'urls' (list) or legacy 'base_url' (string).
        """
        if not isinstance(info, dict):
            return []
        urls = info.get("urls")
        if isinstance(urls, list) and urls:
            return urls
        base_url = info.get("base_url")
        if isinstance(base_url, str) and base_url:
            return [base_url]
        return []

    if current_cfg_hash != cached_cfg_hash:
        # config changed -> re-scrape all systems to refresh index
        temp_cache = {}
        # only iterate real system entries (skip top-level metadata like version/download_folders)
        for sys_name, info in get_system_entries(config.get("systems", {})).items():
            urls = get_system_urls(info)
            temp_cache[sys_name] = []
            for url in urls:
                try:
                    temp_cache[sys_name].extend(scrape_games(url, info))
                except Exception:
                    pass
        cache = temp_cache
        # update meta and save
        cache["_meta"] = {"config_hash": current_cfg_hash, "updated": int(time.time())}
        save_cache(cache)
    else:
        # config unchanged -> only scrape missing/empty systems (faster)
        for sys_name, info in config.get("systems", {}).items():
            if not cache.get(sys_name):
                urls = get_system_urls(info)
                combined = []
                for url in urls:
                    try:
                        combined.extend(scrape_games(url, info))
                    except Exception:
                        # ignore individual URL failures
                        pass
                cache[sys_name] = combined
        # save once
        save_cache(cache)

    curses.wrapper(curses_main, config.get("systems"), cache)


if __name__ == "__main__":
    main()