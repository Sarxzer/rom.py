# 🎮 Terminal ROM Browser & Downloader

A terminal-based ROM browser and downloader written in Python using **curses** and **BeautifulSoup**.  
It allows you to browse, search, and download game ROMs directly from websites (like [Myrient](https://myrient.erista.me)) with a simple, keyboard-driven interface.

---

## 🌍 Compatibility

- ✅ **Windows**
- ✅ **Linux**
- ⚙️ **macOS** (likely works if you can install `beautifulsoup4`, `curses`, and `wget`)

---

## 📦 Installation

1. **Download the latest release** from the [GitHub Releases tab](../../releases).  
2. Extract the files anywhere you like.
3. Run the script for the first time to generate a `config.json`:
   ```bash
   python3 script.py
   ```

4. Edit the generated config file to set up your preferred systems and URLs.

---

## ⚙️ Requirements

* **Python 3.8+**
* Python modules:

  * `beautifulsoup4`
  * `windows-curses` *(Windows only)*
* Optional but recommended:

  * `wget` for faster or more reliable downloads on some sites

The script automatically installs missing dependencies on first run.

---

## 🧩 Features

* **Multi-system support** – Configure multiple consoles (Game Boy, SNES, etc.) in a single config file.
* **Search and filter** – Instantly find games by name.
* **Region grouping** – Organize ROMs by region (e.g., USA, Europe, Japan).
* **Progress display** – Shows download size, speed, and ETA.
* **Configurable folders** – Set global or per-system download directories.
* **Cross-platform TUI** – Runs smoothly on Windows and Linux terminals.

---

## 🎛️ Usage

```bash
python3 script.py
```

### 🕷️ Scraping

On launch, the program scrapes the configured websites for available ROMs and updates a cache file.
This process may take a few moments depending on the number of systems and games but only needs to be done once or when the config changes.

### Controls

| Key       | Action                          |
| --------- | ------------------------------- |
| ↑ / ↓     | Scroll through games            |
| ← / →     | Switch between systems          |
| **ENTER** | Download selected ROM           |
| **r**     | Toggle region grouping          |
| **TAB**   | Cycle through regions           |
| **f**     | Search games                    |
| **i**     | System info                     |
| **d**     | Set per-system download folders |
| **g**     | Set global download folders     |
| **q**     | Quit                            |

When downloading, you can choose to use **wget** for better speed and reliability on some servers.

---

## 🗂️ Configuration

The first launch automatically creates a `config.json` file with an example configuration.
You can define each system’s scraping settings, including:

* Base URL
* HTML selectors for name, size, and link
* Download folder(s)
* Region keywords for automatic sorting

An example entry:

```json
{
  "Nintendo Gameboy": {
    "id": "gb",
    "base_url": "https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy/",
    "entries": "tbody tr",
    "fields": {
      "name": "td.link a",
      "url": "td.link a",
      "size": "td.size"
    },
    "download_folders": ["~/roms/gameboy"],
    "ignore": {
      "size": "-",
      "name_contains": "Parent"
    },
    "regions": {
      "USA": ["(USA)", "(U)"],
      "Europe": ["(Europe)", "(E)"],
      "Japan": ["(Japan)", "(J)"]
    }
  }
}
```

---

## 📚 Documentation

A **Wiki** will soon be available on GitHub with detailed guides on:

* Creating and customizing config files
* Hosting your own ROMs for the program
* Using public ROM-hosting websites like [Myrient](https://myrient.erista.me)

---

## ⚠️ Legal Notice

This tool is intended **for educational purposes only.**  
Do **not** use it to download or distribute copyrighted ROMs that you do not legally own.  
You are fully responsible for how you use this software.

This project is **not affiliated, associated, authorized, endorsed by, or in any way officially connected with**  
**Myrient**, **The Erista Project**, or any other ROM-hosting website.  
All trademarks and content belong to their respective owners.


---

## 💜 Author

**Created by [Sarxzer](https://github.com/Sarxzer)**
A simple project made for retro game lovers and terminal enthusiasts.

## 📝 License

This project is open-source and licensed under the **MIT License**.  
© 2025 Sarxzer

You’re free to use, modify, and share this project, as long as you include the original license.
