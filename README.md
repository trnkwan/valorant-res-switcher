# Valorant Res Switcher

A small Windows tray app that switches your desktop resolution when Valorant starts and switches it back when the game closes. Made for people who play on stretched resolutions and are tired of changing it by hand every time.

> **Note:** I'm a med student, not a programmer. I vibe coded this with AI for my own use and shared it in case it helps someone. Please don't ask me questions about the code or this repo, because I can't answer them. Feel free to fork it and improve it however you like.

## What it does

When Valorant launches, the app changes your desktop to your game resolution (for example 1280x1024). When the game closes, it changes back to your normal resolution (for example 1568x1080). It uses the Windows display API as a temporary change, so there is no "keep these display settings" popup.

It does not read, write or inject into any game file or game process. It only checks whether the game process exists and asks Windows to change the display mode. It is not affiliated with Riot Games. Use it at your own risk.

## Before you start

You need a Windows PC, and the resolutions you want must already exist in your GPU driver. If you use a custom resolution, create it first in the NVIDIA Control Panel (Display, Change resolution, Customize, Create custom resolution) or the AMD or Intel equivalent. Use the same refresh rate as your desktop, otherwise the driver may refuse the switch. In Valorant, set the display mode to windowed fullscreen with the Fill aspect ratio method for stretched resolutions.

## How to use

Download the exe from the Releases page, put it in a folder you will keep it in, and open it. A tray icon appears near your clock. Right click it to pick your Game resolution and Home resolution from the list, or choose Custom to type one like 1152x1080. Your choices are saved automatically in valo_res_config.json next to the exe.

The tray menu also has Pause watching, buttons to switch resolutions right now, a Start with Windows toggle, and Quit. Use Quit to close the app, because it restores your home resolution on the way out. If the app is force closed while you are on the game resolution, just open it again and it fixes your resolution.

## Run from source

Install Python 3 for Windows, then run:

```
pip install pystray pillow
python valo_res_tray.py
```

## Build the exe

```
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --icon=icon.ico --add-data "icon.ico;." valo_res_tray.py
```

The exe appears in the dist folder. Add `--name YourName` to change its file name.

## Settings

valo_res_config.json is created on first run. You can change the game process name, how often the app checks (default every 3 seconds), and a delay after launch if the game window looks off right after the switch.

## Troubleshooting

If the tray status says it could not switch, the driver does not accept that resolution. Check that it exists in your GPU control panel and that its refresh rate matches your desktop. If Windows SmartScreen warns about the exe, that is because it is not code signed. You can also run it from source instead.
