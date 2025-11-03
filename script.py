# rom_scraper.py
# === TERMINAL ROM BROWSER v0.1 ===
# Coded with chaos, caffeine, and sheer gamer energy 💀💜

import curses
import json
import os
import urllib.request
import urllib.parse
import re
from bs4 import BeautifulSoup
import time

CACHE_FILE = "rom_cache.json"
CONFIG_FILE = "config.json"

# ------------------------------
# Load configuration
# ------------------------------
def load_config():
    # create a sample config (with download folders + ids) if missing
    if not os.path.exists(CONFIG_FILE):
        sample = {
            "download_folders": ["/home/you/roms"],   # global default folders (can be list or single path)
            "Nintendo Gameboy": {
                "id": "gb",
                "base_url": "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy/",
                "entries": "tbody tr",
                "fields": {
                    "name": "td.link a",
                    "url": "td.link a",
                    "size": "td.size"
                },
                "download_folders": ["/home/you/roms/gameboy"],
                "ignore": {
                    "size": "-",
                    "name_contains": "Parent"
                }
            }
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)
        print("Created sample config.json — edit it before running again!")
        exit()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

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


def categorize_by_region(games, region_config):
    if not region_config:
        return {"Unknown": games}

    categorized = {region: [] for region in region_config.keys()}
    categorized["Unknown"] = []

    for g in games:
        name = g["name"]
        matched = False
        for region, patterns in region_config.items():
            if any(pat.lower() in name.lower() for pat in patterns):
                categorized[region].append(g)
                matched = True
                break
        if not matched:
            categorized["Unknown"].append(g)
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

    cfg_dir = os.path.dirname(os.path.abspath(CONFIG_FILE))
    out = []
    for f in folders:
        if not isinstance(f, str):
            continue
        p = f.strip()
        # expand user and environment variables
        p = os.path.expanduser(os.path.expandvars(p))
        # if relative, resolve against the config file directory
        if not os.path.isabs(p):
            p = os.path.normpath(os.path.join(cfg_dir, p))
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
ICON_GAME = '🎮 '
ICON_ARROW = '➡️ '
ICON_FOLDER = '📁 '
ICON_SEARCH = '🔎 '
ICON_DL = '⬇️ '
ICON_OK = '✅ '
ICON_ERR = '❌ '

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


def download_with_progress(selected, dest_path, stdscr, h, w):
    url = selected.get('url')
    name = selected.get('name', '')
    start = time.time()
    success = False
    downloaded = 0
    total = None
    err_msg = None
    try:
        req = urllib.request.urlopen(url)
        total_raw = req.getheader('Content-Length')
        total = int(total_raw) if total_raw and total_raw.isdigit() else None
        downloaded = 0
        chunk = 8192
        with open(dest_path, 'wb') as out:
            while True:
                data = req.read(chunk)
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


# ------------------------------
# Curses UI
# ------------------------------
def curses_main(stdscr, systems, cache):
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    # initialize colors and icon styles
    init_ui_colors(stdscr)

    # note: 'systems' may contain top-level keys (like download_folders) — filter
    all_systems = get_system_entries(systems)
    system_names = list(all_systems.keys())
    system_idx = 0

    # selection/state
    game_idx = 0              # index into flat list when not grouped
    grouped = False           # toggle grouping by region
    region_idx = 0            # which region is shown when grouped
    region_game_idx = 0       # index into current region list

    # search state
    search_query = None  # lowercase query or None

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        current_sys = system_names[system_idx]
        games = cache.get(current_sys, [])

        # Header with icon + system name
        try:
            stdscr.addstr(0, 2, f"{ICON_GAME}{current_sys} — {len(games)} games"[:w-4], HEADER_ATTR if HEADER_ATTR is not None else curses.A_BOLD)
        except Exception:
            stdscr.addstr(0, 2, f"{current_sys} — {len(games)} games")

        # Instructions (include grouping keys)
        instr_text = "↑↓ scroll | ←→ system | ENTER open/download | r toggle regions | TAB switch region | f search | i info | q quit"
        try:
            stdscr.addstr(1, 2, instr_text, INSTR_ATTR if INSTR_ATTR is not None else curses.A_NORMAL)
        except Exception:
            stdscr.addstr(1, 2, instr_text)

        # show system id + one download folder in header (if present)
        sys_id = get_system_id(current_sys, systems)
        dfolders = get_download_folders_for_system(current_sys, systems)
        if dfolders:
            try:
                stdscr.addstr(0, w - 40, f"[id:{sys_id}] {os.path.basename(dfolders[0])}"[:38], SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
            except Exception:
                stdscr.addstr(0, w - 40, f"[id:{sys_id}] {os.path.basename(dfolders[0])}"[:38])

        # compute the base list depending on grouping & region
        if not grouped:
            base_list = games
        else:
            categorized = categorize_by_region(games, systems[current_sys].get("regions"))
            region_names = list(categorized.keys()) or ["Unknown"]
            region_idx = region_idx % len(region_names)
            cur_region = region_names[region_idx]
            base_list = categorized.get(cur_region, [])

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
            if not grouped:
                stdscr.addstr(2, 2, "Listing: All games")
                list_start_row = 3
            else:
                stdscr.addstr(2, 2, f"Grouped by region: {cur_region} — {len(display_list)} games")
                list_start_row = 4

        # determine start index and visible slice
        if not grouped:
            start = game_idx
        else:
            start = region_game_idx

        visible = display_list[start:start + (h - list_start_row - 1)]

        # render list (with selection highlight)
        # determine selected visible index
        sel_vis = (game_idx if not grouped else region_game_idx) - start
        for i, game in enumerate(visible):
            row = list_start_row + i
            is_sel = (i == sel_vis)
            prefix = f"{ICON_ARROW} " if is_sel else "   "
            name = game.get("name", "")[:max(10, w - 20)]
            size = game.get("size", "?")
            try:
                if is_sel:
                    stdscr.addstr(row, 2, prefix + name, SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(row, w - 12, size.rjust(10), SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
                else:
                    stdscr.addstr(row, 2, prefix + name, NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                    stdscr.addstr(row, w - 12, size.rjust(10), SIZE_ATTR if SIZE_ATTR is not None else curses.A_NORMAL)
            except Exception:
                try:
                    stdscr.addstr(row, 2, prefix + name)
                except Exception:
                    pass

        # footer for regions when grouped (and no active global search override)
        if grouped:
            regs_line = " | ".join((f"[{r}]" if idx == region_idx else r) for idx, r in enumerate(region_names))
            try:
                stdscr.addstr(h - 1, 2, regs_line[:w - 4], INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
            except Exception:
                stdscr.addstr(h - 1, 2, regs_line[:w - 4])

        key = stdscr.getch()
        if key == ord('D'):  # Download selected game
            idx = game_idx if not grouped else region_game_idx
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
                    try:
                        ch = stdscr.getkey()
                    except Exception:
                        ch = ''
                    curses.noecho()
                    curses.curs_set(0)
                    if ch == '1':
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
                download_with_progress(selected, dest_path, stdscr, h, w)
                # continue main loop
                continue

        if key == ord('q'):
            break
        elif key == ord('r'):
            # toggle grouping, reset indices and clear search
            grouped = not grouped
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            search_query = None
        elif key == 9:  # TAB -> cycle region when grouped
            if grouped:
                categorized = categorize_by_region(games, systems[current_sys].get("regions"))
                region_names = list(categorized.keys()) or ["Unknown"]
                region_idx = (region_idx + 1) % len(region_names)
                region_game_idx = 0
        elif key == ord('f'):  # search (keyword)
            # prompt
            curses.echo()
            curses.curs_set(1)
            stdscr.addstr(h - 2, 2, "Search (empty to clear): " + " " * (w - 24))
            stdscr.move(h - 2, 24)
            stdscr.refresh()
            try:
                raw = stdscr.getstr(h - 2, 24, w - 26)
                query = raw.decode("utf-8").strip()
            except Exception:
                query = ""
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
            stdscr.getch()
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
            try:
                raw = stdscr.getstr(h - 2, 60, w - 62)
                inp = raw.decode("utf-8").strip()
            except Exception:
                inp = ""
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
            try:
                raw = stdscr.getstr(h - 2, 70, w - 72)
                inp = raw.decode("utf-8").strip()
            except Exception:
                inp = ""
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
            if not grouped:
                if game_idx < max(0, len(display_list) - 1):
                    game_idx += 1
            else:
                if region_game_idx < max(0, len(display_list) - 1):
                    region_game_idx += 1
        elif key == curses.KEY_UP:
            if not grouped and game_idx > 0:
                game_idx -= 1
            elif grouped and region_game_idx > 0:
                region_game_idx -= 1
        elif key == curses.KEY_RIGHT:
            system_idx = (system_idx + 1) % len(system_names)
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            search_query = None
        elif key == curses.KEY_LEFT:
            system_idx = (system_idx - 1) % len(system_names)
            game_idx = 0
            region_idx = 0
            region_game_idx = 0
            search_query = None
        elif key in [10, 13]:  # ENTER key -> confirm & download
            # pick from the currently displayed filtered list
            idx = game_idx if not grouped else region_game_idx
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
                        stdscr.addstr(1, 2, f"Name: {selected.get('name')}", SELECTED_ATTR if SELECTED_ATTR is not None else curses.A_NORMAL)
                        stdscr.addstr(2, 2, f"Size: {size_str}", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
                        stdscr.addstr(3, 2, f"URL: {selected.get('url')}", NORMAL_ATTR if NORMAL_ATTR is not None else curses.A_NORMAL)
                        stdscr.addstr(5, 2, "Destination:", INFO_ATTR if INFO_ATTR is not None else curses.A_NORMAL)
                    except Exception:
                        stdscr.addstr(0, 2, "Confirm download")

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
                        ch = stdscr.getkey()
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
                    download_with_progress(selected, dest_path, stdscr, h, w)
                # continue main loop
                continue

        stdscr.refresh()

# ------------------------------
# Main entry
# ------------------------------
def main():
    config = load_config()
    cache = load_cache()

    # Normalize any old cached categorized dicts into flat lists
    for k, v in list(cache.items()):
        if isinstance(v, dict):
            flat = []
            for sub in v.values():
                if isinstance(sub, list):
                    flat.extend(sub)
            cache[k] = flat

    # Scrape missing systems
    for sys_name, info in config.items():
        if sys_name not in cache or not cache.get(sys_name):
            cache[sys_name] = scrape_games(info["base_url"], info)
            save_cache(cache)

    curses.wrapper(curses_main, config, cache)


if __name__ == "__main__":
    main()
