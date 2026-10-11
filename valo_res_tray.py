"""
Valorant resolution switcher, tray version (Windows only).

Needs two packages:  pip install pystray pillow

What it does:
  - Sits in the system tray.
  - When Valorant starts, switches the desktop to your game resolution.
  - When Valorant closes, switches back to your home resolution.
  - Uses the Windows display API as a temporary change, so there is no
    "keep these display settings" popup.
  - Right click the tray icon, then Game resolution or Home resolution,
    to pick from every resolution your GPU driver knows (this includes
    your custom ones). Your choice is saved automatically.

What it does NOT do: it never reads, writes or injects into any game
file or game process. It only checks whether the process name exists.
"""

import atexit
import ctypes
import json
import os
import subprocess
import sys
import threading
import winreg
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

APP_NAME = "ValoResSwitcher"
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(BASE_DIR, "valo_res_config.json")

DEFAULT_CONFIG = {
    "home_width": 1568,
    "home_height": 1080,
    "game_width": 1280,
    "game_height": 1024,
    "game_process": "VALORANT-Win64-Shipping.exe",
    "check_every_seconds": 3,
    "delay_after_launch_seconds": 0,
}

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_TEST = 0x00000002
DISP_CHANGE_SUCCESSFUL = 0
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# ---------------- config ----------------
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    else:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
    return cfg


def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CFG, f, indent=2)
    except Exception:
        pass


CFG = load_config()
RES = {
    "home": (int(CFG["home_width"]), int(CFG["home_height"])),
    "game": (int(CFG["game_width"]), int(CFG["game_height"])),
}
GAME_PROCESS = CFG["game_process"]
CHECK_EVERY = max(1, int(CFG["check_every_seconds"]))
LAUNCH_DELAY = max(0, int(CFG["delay_after_launch_seconds"]))


# ---------------- display ----------------
def current_res():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    return dm.dmPelsWidth, dm.dmPelsHeight


def list_modes():
    """Every resolution the driver offers for the main display, biggest first."""
    modes = set()
    i = 0
    while True:
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
            break
        if dm.dmPelsWidth >= 800 and dm.dmPelsHeight >= 600:
            modes.add((int(dm.dmPelsWidth), int(dm.dmPelsHeight)))
        i += 1
    return sorted(modes, key=lambda m: (m[0], m[1]), reverse=True)


def mode_available(width, height):
    """True if the GPU driver accepts this resolution (tested, nothing changes)."""
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmFields = dm.dmFields | DM_PELSWIDTH | DM_PELSHEIGHT
    test = user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_TEST, None)
    return test == DISP_CHANGE_SUCCESSFUL


def set_res(width, height):
    if current_res() == (width, height):
        return True

    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmFields = dm.dmFields | DM_PELSWIDTH | DM_PELSHEIGHT

    # Test first so a missing mode never blanks the screen.
    test = user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_TEST, None)
    if test != DISP_CHANGE_SUCCESSFUL:
        return False

    # Flag 0 = dynamic change: no confirm popup, and a reboot resets it.
    result = user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


def game_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return False
    return GAME_PROCESS.lower() in out.lower()


# ---------------- start with windows ----------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(sys.argv[0])}"'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(enable):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass


# ---------------- app state ----------------
state = {"status": "Waiting for Valorant", "paused": False}
stop_event = threading.Event()
icon = None


def set_status(text):
    state["status"] = text
    if icon is not None:
        icon.title = f"Valo Res: {text}"
        try:
            icon.update_menu()
        except Exception:
            pass


def go_game():
    w, h = RES["game"]
    if set_res(w, h):
        set_status(f"Game res {w}x{h}")
    else:
        set_status(f"Could not switch to {w}x{h}")


def go_home():
    w, h = RES["home"]
    if set_res(w, h):
        set_status(f"Home res {w}x{h}")
    else:
        set_status(f"Could not switch to {w}x{h}")


def watcher():
    was_running = False
    while not stop_event.is_set():
        if not state["paused"]:
            running = game_running()
            if running and not was_running:
                set_status("Valorant detected")
                if LAUNCH_DELAY:
                    stop_event.wait(LAUNCH_DELAY)
                go_game()
            elif was_running and not running:
                go_home()
            was_running = running
        stop_event.wait(CHECK_EVERY)


# ---------------- tray ----------------
def make_icon_image():
    # Custom icon: put icon.png or icon.ico next to the app and restart it.
    # It also checks inside the exe itself if the icon was bundled at build time.
    folders = [BASE_DIR, getattr(sys, "_MEIPASS", BASE_DIR)]
    for folder in folders:
        for name in ("icon.png", "icon.ico"):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                try:
                    return Image.open(path).convert("RGBA").resize((64, 64))
                except Exception:
                    pass

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(255, 70, 85, 255))
    d.polygon([(18, 18), (28, 18), (34, 40), (40, 18), (46, 18), (36, 48), (30, 48)], fill="white")
    return img


def choose_res(kind, res):
    """Save a new game or home resolution, and apply it if it applies right now."""
    RES[kind] = res
    CFG[f"{kind}_width"], CFG[f"{kind}_height"] = res
    save_config()
    in_game = game_running()
    if kind == "game" and in_game:
        go_game()
    elif kind == "home" and not in_game:
        go_home()
    else:
        set_status(f"{kind.capitalize()} res set to {res[0]}x{res[1]}")


def make_handler(kind, res):
    def handler(icon_, item):
        choose_res(kind, res)
    return handler


def make_checked(kind, res):
    def checked(item):
        return RES[kind] == res
    return checked


def custom_dialog(kind):
    import tkinter as tk
    from tkinter import messagebox, simpledialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        text = simpledialog.askstring(
            "Custom resolution",
            f"Type the {kind} resolution as WIDTHxHEIGHT\nFor example: 1152x1080",
            parent=root,
        )
        if not text:
            return
        try:
            w, h = [int(x) for x in text.lower().replace(" ", "").split("x")]
        except ValueError:
            messagebox.showerror("Custom resolution", "Please type it like 1152x1080", parent=root)
            return
        if (w, h) in list_modes() or mode_available(w, h):
            choose_res(kind, (w, h))
        else:
            messagebox.showinfo(
                "Not in your GPU driver yet",
                f"{w}x{h} is not available yet.\n\n"
                "Add it as a custom resolution in the NVIDIA Control Panel "
                "(Display, Change resolution, Customize, Create custom resolution), "
                "then try again.",
                parent=root,
            )
    finally:
        root.destroy()


def make_custom_handler(kind):
    def handler(icon_, item):
        threading.Thread(target=custom_dialog, args=(kind,), daemon=True).start()
    return handler


def mode_items(kind):
    modes = list_modes()
    if RES[kind] not in modes:
        modes.insert(0, RES[kind])
    items = [pystray.MenuItem("Custom... (type your own)", make_custom_handler(kind)), pystray.Menu.SEPARATOR]
    items += [
        pystray.MenuItem(
            f"{w}x{h}",
            make_handler(kind, (w, h)),
            checked=make_checked(kind, (w, h)),
            radio=True,
        )
        for (w, h) in modes
    ]
    return items


def on_toggle_pause(icon_, item):
    state["paused"] = not state["paused"]
    set_status("Paused" if state["paused"] else "Waiting for Valorant")


def on_game_now(icon_, item):
    go_game()


def on_home_now(icon_, item):
    go_home()


def on_toggle_startup(icon_, item):
    try:
        set_startup(not startup_enabled())
    except Exception as exc:
        set_status(f"Startup change failed: {exc}")


def on_open_config(icon_, item):
    try:
        os.startfile(CONFIG_PATH)
    except Exception:
        pass


def on_quit(icon_, item):
    stop_event.set()
    set_res(*RES["home"])
    icon_.stop()


def build_menu():
    return pystray.Menu(
        pystray.MenuItem(lambda item: state["status"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda item: f"Game resolution ({RES['game'][0]}x{RES['game'][1]})",
            pystray.Menu(lambda: mode_items("game")),
        ),
        pystray.MenuItem(
            lambda item: f"Home resolution ({RES['home'][0]}x{RES['home'][1]})",
            pystray.Menu(lambda: mode_items("home")),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause watching", on_toggle_pause, checked=lambda item: state["paused"]),
        pystray.MenuItem("Switch to game res now", on_game_now),
        pystray.MenuItem("Switch to home res now", on_home_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", on_toggle_startup, checked=lambda item: startup_enabled()),
        pystray.MenuItem("Open settings file", on_open_config),
        pystray.MenuItem("Quit (restores home res)", on_quit),
    )


def main():
    global icon

    if sys.platform != "win32":
        print("This only works on Windows.")
        return

    # Only one copy at a time.
    kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}Mutex")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return

    atexit.register(lambda: set_res(*RES["home"]))

    # If an earlier run was force killed while on game res, fix it now.
    if not game_running() and current_res() == RES["game"] and RES["game"] != RES["home"]:
        set_res(*RES["home"])

    icon = pystray.Icon(APP_NAME, make_icon_image(), "Valo Res: Waiting for Valorant", build_menu())
    threading.Thread(target=watcher, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
