#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
==============================================================================
  Z E M I   H U B   -  one place for all your games
==============================================================================
 Run:      double-click "Play Zemi Hub.pyw"  (or:  pythonw zemi_hub.py)
 Needs:    Windows + Python 3.8 or newer.  Nothing to install.  Works offline.
           The window is Microsoft Edge (or Chrome) in "app" mode, talking to
           a tiny web server that only listens on this PC (127.0.0.1).

 What it does
   * Finds the games in this folder (Blockcraft, Boostball, Tic Tac Toe, and
     any other Python game you drop in) and shows them as cards.
   * Play launches the game; the card shows "Running" while it's open.
   * Card art is a screenshot of your last session, taken automatically.
   * Remembers how long you've played, what you played last, your favourites.
   * "Add a game" picks any .py / .pyw / .exe from anywhere on the PC.

 Files it writes:  %APPDATA%\ZemiHub\settings.json, art\*.png (card pictures) and
           logs\*.log (what each game last printed - read it if a game crashes)
==============================================================================
"""
import ctypes
import ctypes.wintypes as wt
import glob
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

VERSION = '1.0'
HUB_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ZemiHub')
ART_DIR = os.path.join(DATA_DIR, 'art')
GALLERY_DIR = os.path.join(DATA_DIR, 'gallery')  # pictures the hub took while you played (newest kept)
SHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Screenshots')   # your own: Screenshots/<game id>/
GALLERY_KEEP = 16
LOG_DIR = os.path.join(DATA_DIR, 'logs')      # what each game last printed (handy after a crash)
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
LOCK_FILE = os.path.join(DATA_DIR, 'hub.lock')
SELF_NAMES = {'zemi_hub.py', 'play zemi hub.pyw', 'play callum games.pyw', 'callum games.pyw', 'make_bundle.py', 'privacy_launch.py', 'privacy_decoy.py'}

u32 = ctypes.windll.user32 if os.name == 'nt' else None
g32 = ctypes.windll.gdi32 if os.name == 'nt' else None
if u32 is not None:
    # handles are 64-bit: without these, ctypes cuts them to 32-bit ints and the screenshot calls fail at random
    u32.GetDC.restype = wt.HDC
    u32.GetDC.argtypes = [wt.HWND]
    u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    g32.CreateCompatibleDC.restype = wt.HDC
    g32.CreateCompatibleDC.argtypes = [wt.HDC]
    g32.CreateDIBSection.restype = wt.HBITMAP
    g32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
    g32.SelectObject.restype = wt.HGDIOBJ
    g32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    g32.DeleteObject.argtypes = [wt.HGDIOBJ]
    g32.DeleteDC.argtypes = [wt.HDC]

# ----------------------------------------------------------------------------
#  THE GAMES WE KNOW (anything else in the folder gets a plain card)
# ----------------------------------------------------------------------------
KNOWN = [
    dict(id='blockcraft', match=r'^blockcraft.*\.pyw?$', name='Callum Craft', color='#4ade80',
         tagline='Build. Survive. Duel your friends.',
         desc='A voxel world of your own: mine, craft, farm and fight across the overworld, the Nether and the End. '
              'Host a LAN world for the class, drop in your own skin and cape, and settle it in the duel arena with '
              '1.8-style PvP.',
         chips=['1-8 players', 'LAN + internet chat', 'Survival & Creative'],
         controls='WASD move  /  Mouse look  /  Left click mine  /  Right click place  /  E inventory  /  Tab players  /  F3+B hitboxes',
         features=['Overworld, Nether and the End to explore', 'Host a LAN world for the whole class',
                   '1.8-style PvP and a duel arena', 'Preset skins and capes, or drop in your own',
                   'Operators, ranks and an admin menu (/op menu)', 'Animated water, weather and day/night'],
         icon='cube'),
    dict(id='boostball', match=r'^boostball.*\.pyw?$', name='Boostball', color='#fb923c',
         tagline='Rocket-powered car soccer.',
         desc='Boost, jump, flip and score in Soccar, Hoops, Snow Day, Heatseeker and Rumble. Train against bots from '
              'Rookie to Legend, chase the Rings challenge, or host a LAN match. Controllers work too.',
         chips=['1v1 - 4v4', 'LAN', 'Controller'],
         controls='W/S throttle  /  A/D steer  /  Right click jump  /  Left click boost  /  Shift powerslide  /  Space ball cam',
         features=['Soccar, Hoops, Snow Day, Heatseeker and Rumble', 'Bots from Rookie to Legend',
                   'Rings challenge', 'LAN matches', 'Controller support'],
         icon='ball'),
    dict(id='browser', match=r'^(callum_browser|nova).*\.pyw?$', name='Callum Browser', color='#38bdf8',
         tagline='Fast, websites only.',
         desc='A quick browser built on Edge: tabs, bookmarks, history and a clean look. It opens real websites only - '
              'nothing on this PC or a local network (localhost, 127.0.0.1, 192.168.x.x, files) can be opened.',
         chips=['Tabs', 'Bookmarks', 'Websites only'],
         features=['Tabs, bookmarks, history and session restore', 'Websites only: localhost and local addresses are blocked',
                   'Uses the Edge engine that comes with Windows', 'No installs needed'],
         controls='Ctrl+T new tab  /  Ctrl+W close tab  /  Ctrl+L address bar  /  Ctrl+D bookmark  /  F11 full screen',
         icon='globe'),
    dict(id='chess', match=r'^(onyx_)?chess.*\.pyw?$', name='Onyx Chess', color='#e5e7eb',
         tagline='Play beautifully. Think deeply.',
         desc='A polished chess game: every rule, drag-and-drop or click moves, three computer levels, clocks, undo and '
              'redo, PGN save and load, and sound. The first launch sets up its two small libraries by itself.',
         chips=['1-2 players', 'AI levels', 'Clocks & PGN'],
         features=['Every chess rule, including castling, en passant and promotion', 'Easy, Medium and Hard computer opponents',
                   'Chess clocks, undo and redo', 'Save and load games as PGN'],
         controls='Drag a piece  /  Click a piece then a square  /  Right click cancel  /  Ctrl+N new game',
         icon='grid'),
    dict(id='tictactoe', match=r'^tic.?tac.?toe.*\.pyw?$', name='Tic Tac Toe', color='#f472b6',
         tagline='Classic and ULTIMATE, with a coach.',
         desc='Three in a row - or the nine-board ULTIMATE version where every move decides where your opponent goes '
              'next. Play a friend, the computer, or someone on your network, and let the coach grade every move.',
         chips=['1-2 players', 'LAN', 'Coach mode'],
         controls='Click a square  /  Arrows + Enter  /  Ctrl+Z undo  /  R restart  /  F11 full screen',
         features=['Classic 3x3 and ULTIMATE nine-board mode', 'Play a friend, the computer or the network',
                   'A coach that grades every move', 'Undo and restart any time'],
         icon='grid'),
]
PALETTE = ['#a78bfa', '#38bdf8', '#facc15', '#f87171', '#34d399', '#e879f9']


# ----------------------------------------------------------------------------
#  SETTINGS
# ----------------------------------------------------------------------------
def load_settings():
    d = {'title': 'Callum Games', 'accent': '#a78bfa', 'games': [], 'stats': {}, 'favs': [], 'hidden': [],
         'tagline': 'Every game, one place.', 'privacy': False, 'privacy_asked': False,
         'privacy_msg': 'Working on my project - back in a bit!'}
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            d.update(json.load(f))
    except Exception:
        pass
    if d.get('title') == 'Zemi Hub':                  # (renamed: Zemi Hub is now Callum Games)
        d['title'] = 'Callum Games'
    return d


def save_settings(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, SETTINGS_FILE)


def game_id_for(path):
    base = os.path.basename(path).lower()
    for k in KNOWN:
        if re.match(k['match'], base):
            return k['id']
    return 'g_' + hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode('utf-8')).hexdigest()[:10]


def docstring_of(path):
    """The first line of a Python file's docstring (its own description of itself), if any."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            head = f.read(6000)
        m = re.search(r'^\s*(?:#.*\n|\s*\n)*[rR]?("""|\'\'\')(.*?)\1', head, re.S)
        if m:
            lines = [l.strip(' =-#*') for l in m.group(2).strip().splitlines()]
            lines = [l for l in lines if l]
            if lines:
                return re.sub(r'\s+', ' ', lines[0])[:90]
    except Exception:
        pass
    return ''


def nice_name(path):
    n = os.path.splitext(os.path.basename(path))[0]
    n = re.sub(r'\s*\(\d+\)\s*', ' ', n).replace('_', ' ').replace('-', ' ').strip()
    return n.title() if n.islower() else n


# ----------------------------------------------------------------------------
#  FINDING THE GAMES
# ----------------------------------------------------------------------------
def scan_games(settings):
    """Every game we can see: the known ones in the hub folder (best copy of each), other scripts in the folder,
    and the ones added by hand."""
    found = {}
    files = []
    for ext in ('*.py', '*.pyw'):
        files += glob.glob(os.path.join(HUB_DIR, ext))
    for p in files:
        if os.path.basename(p).lower() in SELF_NAMES or os.path.basename(p).lower().startswith('play '):
            continue
        gid = game_id_for(p)
        found.setdefault(gid, []).append(p)
    out = []
    for gid, paths in found.items():
        # the best copy: a plain name beats "name (3).py"; then the newest
        paths.sort(key=lambda p: (bool(re.search(r'\(\d+\)', os.path.basename(p))), -os.path.getmtime(p)))
        path = paths[0]
        k = next((k for k in KNOWN if k['id'] == gid), None)
        if k:
            g = dict(k)
            g.pop('match', None)
        else:
            g = dict(id=gid, name=nice_name(path), color=PALETTE[sum(map(ord, gid)) % len(PALETTE)],
                     tagline=docstring_of(path) or 'A game in your hub folder.', desc='', chips=['Python'],
                     controls='', icon='pad')
        g['path'] = path
        g['copies'] = len(paths)
        g['source'] = 'folder'
        out.append(g)
    for a in settings.get('games', []):
        path = a.get('path', '')
        if not os.path.exists(path):
            continue
        gid = 'a_' + hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode('utf-8')).hexdigest()[:10]
        if any(g['path'] == path for g in out):
            continue
        base = os.path.basename(path).lower()
        k = next((k for k in KNOWN if re.match(k['match'], base)), None)
        g = dict(k) if k else {}
        g.pop('match', None)
        g.setdefault('name', nice_name(path))
        g.setdefault('color', PALETTE[sum(map(ord, gid)) % len(PALETTE)])
        g.setdefault('tagline', (docstring_of(path) if path.lower().endswith(('.py', '.pyw')) else '') or 'Added by you.')
        g.setdefault('desc', '')
        g.setdefault('chips', ['Added'])
        g.setdefault('controls', '')
        g.setdefault('icon', 'pad')
        g.update(id=gid, path=path, copies=1, source='added')
        out.append(g)
    hidden = set(settings.get('hidden', []))
    out = [g for g in out if g['id'] not in hidden]
    order = {k['id']: i for i, k in enumerate(KNOWN)}
    out.sort(key=lambda g: (order.get(g['id'], 99), g['name'].lower()))
    return out


# ----------------------------------------------------------------------------
#  WINDOWS: find a game's window, screenshot it for the card
# ----------------------------------------------------------------------------
def windows_of(pid, minimised=False):
    """A process's visible top-level windows as (handle, width, height); minimised ones only when asked."""
    out = []
    if not u32:
        return out

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            if u32.IsIconic(h):
                if minimised and u32.GetWindowTextLengthW(h) > 0:
                    out.append((h, 0, 0))
                return True
            r = wt.RECT()
            u32.GetClientRect(h, ctypes.byref(r))
            if r.right > 300 and r.bottom > 200:
                out.append((h, r.right, r.bottom))
        return True
    u32.EnumWindows(cb, 0)
    return out


class _BMI(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG), ('biHeight', wt.LONG), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD), ('biSizeImage', wt.DWORD),
                ('biXPelsPerMeter', wt.LONG), ('biYPelsPerMeter', wt.LONG), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


def png_bytes(rgb_rows, w, h):
    raw = b''.join(b'\x00' + r for r in rgb_rows)

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def capture_window(h, path, max_w=960):
    """Screenshot a window's client area (even an OpenGL one) and save it as a PNG, scaled down to card size.
    Returns False when the picture is blank (a loading screen, or a window that isn't drawing yet)."""
    r = wt.RECT()
    u32.GetClientRect(h, ctypes.byref(r))
    w, hh = r.right, r.bottom
    if w < 100 or hh < 100:
        return False
    hdc = u32.GetDC(h)
    mdc = g32.CreateCompatibleDC(hdc)
    bmi = _BMI()
    bmi.biSize, bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = ctypes.sizeof(_BMI), w, -hh, 1, 32
    bits = ctypes.c_void_p()
    bmp = g32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = g32.SelectObject(mdc, bmp)
    ok = u32.PrintWindow(h, mdc, 3)                    # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    raw = ctypes.string_at(bits, w * hh * 4) if ok else b''
    g32.SelectObject(mdc, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(h, hdc)
    if not ok:
        return False
    # blank check on a sparse sample
    lit = sum(1 for i in range(0, len(raw) - 4, 4 * 211) if raw[i] + raw[i + 1] + raw[i + 2] > 48)
    if lit < (len(raw) // (4 * 211)) * 0.08:
        return False
    # scale down by whole steps (nearest), BGRA -> RGB rows
    step = max(1, -(-w // max_w))
    ow, oh = w // step, hh // step
    rows = []
    for y in range(oh):
        line = raw[(y * step) * w * 4:(y * step + 1) * w * 4]
        if step == 1:
            rows.append(bytes(b for i in range(0, len(line), 4) for b in (line[i + 2], line[i + 1], line[i])))
        else:
            rows.append(bytes(b for x in range(ow) for b in (line[x * step * 4 + 2], line[x * step * 4 + 1], line[x * step * 4])))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(png_bytes(rows, ow, oh))
    os.replace(tmp, path)
    return True


# ----------------------------------------------------------------------------
#  THE HUB: state, launching, bookkeeping
# ----------------------------------------------------------------------------
def gallery_of(gid):
    """Every picture for a game's page: your own (Screenshots/<id>/) first, then the ones the hub took, newest first.
    -> [{'u': 'own/<file>' or 'hub/<file>', 't': mtime}]"""
    out = []
    for kind, d in (('own', os.path.join(SHOTS_DIR, gid)), ('hub', os.path.join(GALLERY_DIR, gid))):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        pics = []
        for n in names:
            if re.match(r'^[A-Za-z0-9 _().-]+\.(png|jpe?g|gif|webp)$', n, re.I):
                try:
                    pics.append((os.path.getmtime(os.path.join(d, n)), n))
                except OSError:
                    pass
        for t, n in sorted(pics, reverse=True):
            out.append({'u': kind + '/' + n, 't': int(t)})
    return out[:40]


def keep_gallery_shot(gid, src):
    """Copy a fresh card picture into the game's gallery, keeping the newest GALLERY_KEEP."""
    try:
        d = os.path.join(GALLERY_DIR, gid)
        os.makedirs(d, exist_ok=True)
        with open(src, 'rb') as f:
            data = f.read()
        with open(os.path.join(d, time.strftime('%Y%m%d-%H%M%S') + '.png'), 'wb') as f:
            f.write(data)
        old = sorted(n for n in os.listdir(d) if n.endswith('.png'))
        for n in old[:-GALLERY_KEEP]:
            os.remove(os.path.join(d, n))
    except OSError:
        pass


DECOY_SCRIPT = r"""
# Callum Games: the message screen.  It sits exactly behind a hidden game window, the same size; you see the game on
# top, but a screen recording or screen share sees straight through the game - to this.
import ctypes, ctypes.wintypes as wt, sys, tkinter as tk
pid, msg = int(sys.argv[1]), sys.argv[2]
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)            # (real pixels, so it lines up with the game exactly)
except Exception:
    pass
u, k = ctypes.windll.user32, ctypes.windll.kernel32
u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.IsIconic.argtypes = [wt.HWND]
u.IsWindowVisible.argtypes = [wt.HWND]
u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(ctypes.c_ulong)]
proc = k.OpenProcess(0x00100000, False, pid)                  # SYNCHRONIZE: to notice the game closing
import os
r = tk.Tk()
r.title('cg-decoy')                                           # (the hub skips this window when it looks for the game's)
r.overrideredirect(True)
r.configure(bg='#0d0d14')
if os.environ.get('CG_DECOY_TOP') == '1':
    r.attributes('-topmost', True)
r.geometry('10x10+-2000+-2000')
lab = tk.Label(r, text=msg, fg='#f3f3f8', bg='#0d0d14', font=('Segoe UI', 30, 'bold'), justify='center')
lab.place(relx=0.5, rely=0.47, anchor='center')
sub = tk.Label(r, text='', fg='#6b6b80', bg='#0d0d14', font=('Segoe UI', 11))
sub.place(relx=0.5, rely=0.94, anchor='center')
r.update()
me = int(r.wm_frame(), 16)


def game_window():
    best = [None, 0]
    cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, _):
        p = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            rc = wt.RECT()
            u.GetWindowRect(h, ctypes.byref(rc))
            a = (rc.right - rc.left) * (rc.bottom - rc.top)
            if a > best[1]:
                best[0], best[1] = h, a
        return True
    u.EnumWindows(cb_t(cb), 0)
    return best[0]


shown = [None]


def tick():
    if proc and k.WaitForSingleObject(proc, 0) == 0:
        r.destroy()
        return
    h = game_window()
    if not h or u.IsIconic(h):
        if shown[0] is not False:
            r.withdraw()
            shown[0] = False
    else:
        rc = wt.RECT()
        u.GetWindowRect(h, ctypes.byref(rc))
        w_, h_ = rc.right - rc.left, rc.bottom - rc.top
        if shown[0] is not True:
            r.deiconify()
            shown[0] = True
        lab.configure(wraplength=max(200, int(w_ * 0.8)), font=('Segoe UI', max(16, min(48, w_ // 28)), 'bold'))
        u.SetWindowPos(me, h, rc.left, rc.top, w_, h_, 0x0010)      # just behind the game, same place, same size
    r.after(120, tick)


r.after(200, tick)
r.mainloop()
"""


PRIVACY_LAUNCHER = r"""
# Callum Games privacy launcher: runs a game with its windows hidden from screen recording, screen sharing and
# screenshots (Windows' 'exclude from capture'), then gets out of the way.
import ctypes, os, runpy, sys, threading, time
game = sys.argv[1]


def guard():
    u = ctypes.windll.user32
    u.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    me = os.getpid()
    done = set()
    cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == me and h not in done:
            if u.SetWindowDisplayAffinity(h, 0x11):      # WDA_EXCLUDEFROMCAPTURE
                done.add(h)
        return True
    f = cb_t(cb)
    while True:
        u.EnumWindows(f, None)
        time.sleep(0.5)


threading.Thread(target=guard, daemon=True).start()
msg = os.environ.get('CG_PRIVACY_MSG', '').strip()
decoy = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'privacy_decoy.py')
if msg and os.path.isfile(decoy):                             # a message for anyone watching: shown behind the game
    import subprocess
    exe = sys.executable
    if exe.lower().endswith('python.exe') and os.path.exists(exe[:-10] + 'pythonw.exe'):
        exe = exe[:-10] + 'pythonw.exe'
    subprocess.Popen([exe, decoy, str(os.getpid()), msg], creationflags=0x08000000)
sys.argv = [game] + sys.argv[2:]
sys.path.insert(0, os.path.dirname(os.path.abspath(game)))
runpy.run_path(game, run_name='__main__')
"""


def privacy_launcher():
    path = os.path.join(DATA_DIR, 'privacy_launch.py')
    try:
        with open(os.path.join(DATA_DIR, 'privacy_decoy.py'), 'w', encoding='utf-8') as f:
            f.write(DECOY_SCRIPT)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(PRIVACY_LAUNCHER)
    except OSError:
        return None
    return path



# ----------------------------------------------------------------------------
#  LIVE PREVIEW CAPTURE: one window seen two ways - as you see it (asked to draw itself), and as a screen recording
#  would get it (copied off the desktop, where a hidden window is not drawn and the message behind it shows).
# ----------------------------------------------------------------------------
if u32 is not None:
    u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    g32.StretchBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.DWORD]
    g32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC, ctypes.c_int,
                           ctypes.c_int, wt.DWORD]
    g32.SetStretchBltMode.argtypes = [wt.HDC, ctypes.c_int]
    g32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    g32.CreateCompatibleBitmap.restype = wt.HBITMAP
    g32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)        # (real pixels, so a window and its screen copy line up)
    except Exception:
        pass


class _PE32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD), ('szExeFile', ctypes.c_wchar * 260)]


def process_tree(pid):
    """pid and every process started by it (a launcher stub starts the real Python as a child)."""
    kids = {}
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PE32)]
        k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PE32)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        snap = k32.CreateToolhelp32Snapshot(2, 0)
        pe = _PE32()
        pe.dwSize = ctypes.sizeof(_PE32)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            kids.setdefault(pe.th32ParentProcessID, []).append(pe.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
        k32.CloseHandle(snap)
    except Exception:
        pass
    out, todo = [pid], [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in out:
                out.append(c)
                todo.append(c)
    return out


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    u32.GetWindowTextW(hwnd, buf, 128)
    return buf.value


def fast_png(bgra, w, h):
    """Packed 32-bit BGRA rows -> a PNG file, quickly (whole-array slice tricks, no per-pixel loop)."""
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = w * 3
    raw = bytearray((stride + 1) * h)
    for y in range(h):
        o = y * (stride + 1)
        raw[o + 1:o + 1 + stride] = rgb[y * stride:(y + 1) * stride]
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 1)) + chunk(b'IEND', b''))


def window_view(hwnd, how, out_w=560):
    """PNG bytes of a window's client area.  how = 'me': the window drawn by itself (what you see);
    'them': that same patch of the desktop as a screen capture gets it.  None if it can't be read."""
    rc = wt.RECT()
    if not u32.GetClientRect(hwnd, ctypes.byref(rc)) or rc.right < 64 or rc.bottom < 64:
        return None
    w, h = rc.right, rc.bottom
    pt = wt.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    ow = min(out_w, w)
    oh = max(1, h * ow // w)
    sdc = u32.GetDC(None)
    full_dc = g32.CreateCompatibleDC(sdc)
    full_bmp = g32.CreateCompatibleBitmap(sdc, w, h)
    old1 = g32.SelectObject(full_dc, full_bmp)
    out = None
    try:
        if how == 'me':
            if not u32.PrintWindow(hwnd, full_dc, 3):             # PW_CLIENTONLY | PW_RENDERFULLCONTENT
                return None
        else:
            g32.BitBlt(full_dc, 0, 0, w, h, sdc, pt.x, pt.y, 0x00CC0020)         # SRCCOPY
        small_dc = g32.CreateCompatibleDC(sdc)
        bmi = _BMI()
        bmi.biSize, bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = ctypes.sizeof(_BMI), ow, -oh, 1, 32
        bits = ctypes.c_void_p()
        small_bmp = g32.CreateDIBSection(sdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old2 = g32.SelectObject(small_dc, small_bmp)
        g32.SetStretchBltMode(small_dc, 4)                        # HALFTONE: a smooth, not blocky, shrink
        g32.StretchBlt(small_dc, 0, 0, ow, oh, full_dc, 0, 0, w, h, 0x00CC0020)
        out = fast_png(ctypes.string_at(bits, ow * oh * 4), ow, oh)
        g32.SelectObject(small_dc, old2)
        g32.DeleteObject(small_bmp)
        g32.DeleteDC(small_dc)
    finally:
        g32.SelectObject(full_dc, old1)
        g32.DeleteObject(full_bmp)
        g32.DeleteDC(full_dc)
        u32.ReleaseDC(None, sdc)
    return out


def screen_view(how, test_hwnd=None, twin_hwnd=None, out_w=1280):
    """PNG bytes of your real screen (the main monitor), full detail.  how = 'them': the screen as a screen recording or
    share gets it (a protected window shows the message behind it).  'me': the same screen as you see it - with the test
    window's own picture put back where the protected test window is (Windows gives nobody a protected window's pixels,
    so a real game's own pixels can't be shown here).  None if it can't be read."""
    W = u32.GetSystemMetrics(0)
    H = u32.GetSystemMetrics(1)
    if W < 200 or H < 200:
        return None
    ow = min(out_w, W)
    oh = max(1, H * ow // W)
    sdc = u32.GetDC(None)
    full_dc = g32.CreateCompatibleDC(sdc)
    full_bmp = g32.CreateCompatibleBitmap(sdc, W, H)
    old1 = g32.SelectObject(full_dc, full_bmp)
    out = None
    try:
        g32.BitBlt(full_dc, 0, 0, W, H, sdc, 0, 0, 0x40CC0020)               # SRCCOPY | CAPTUREBLT (layered windows too)
        if how == 'me' and test_hwnd and twin_hwnd:
            rc = wt.RECT()
            if u32.GetClientRect(twin_hwnd, ctypes.byref(rc)) and rc.right > 64:
                pt = wt.POINT(0, 0)
                u32.ClientToScreen(test_hwnd, ctypes.byref(pt))
                tdc = g32.CreateCompatibleDC(sdc)
                tbmp = g32.CreateCompatibleBitmap(sdc, rc.right, rc.bottom)
                told = g32.SelectObject(tdc, tbmp)
                if u32.PrintWindow(twin_hwnd, tdc, 3):
                    g32.BitBlt(full_dc, pt.x, pt.y, rc.right, rc.bottom, tdc, 0, 0, 0x00CC0020)
                g32.SelectObject(tdc, told)
                g32.DeleteObject(tbmp)
                g32.DeleteDC(tdc)
        small_dc = g32.CreateCompatibleDC(sdc)
        bmi = _BMI()
        bmi.biSize, bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = ctypes.sizeof(_BMI), ow, -oh, 1, 32
        bits = ctypes.c_void_p()
        small_bmp = g32.CreateDIBSection(sdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old2 = g32.SelectObject(small_dc, small_bmp)
        g32.SetStretchBltMode(small_dc, 4)                                   # HALFTONE: a smooth shrink
        g32.StretchBlt(small_dc, 0, 0, ow, oh, full_dc, 0, 0, W, H, 0x00CC0020)
        out = fast_png(ctypes.string_at(bits, ow * oh * 4), ow, oh)
        g32.SelectObject(small_dc, old2)
        g32.DeleteObject(small_bmp)
        g32.DeleteDC(small_dc)
    finally:
        g32.SelectObject(full_dc, old1)
        g32.DeleteObject(full_bmp)
        g32.DeleteDC(full_dc)
        u32.ReleaseDC(None, sdc)
    return out


TEST_WINDOW = r"""
# Callum Games: a small animated window for the privacy overlay preview.  (twin = the same scene, not hidden, parked behind it)
import math, sys, time, tkinter as tk
twin = len(sys.argv) > 1 and sys.argv[1] == 'twin'          # the twin: the same scene, not hidden, parked off-screen
r = tk.Tk()
r.title('Overlay twin' if twin else 'Overlay test')
r.geometry('800x500+140+140')                                # (the twin sits right behind the test window: covered, but still painted)
if not twin:
    r.attributes('-topmost', True)
r.configure(bg='#101820')
c = tk.Canvas(r, width=800, height=500, bg='#5aa0ff', highlightthickness=0)
c.pack(fill='both', expand=True)
t0 = time.time()
def frame():
    t = time.time() - t0
    c.delete('all')
    w, h = c.winfo_width(), c.winfo_height()
    c.create_rectangle(0, 0, w, h * 0.55, fill='#5aa0ff', width=0)
    c.create_rectangle(0, h * 0.55, w, h * 0.72, fill='#4ade80', width=0)
    c.create_rectangle(0, h * 0.72, w, h, fill='#7c5a3a', width=0)
    for i in range(5):
        x = (t * 40 + i * 190) % (w + 160) - 80
        c.create_rectangle(x, h * 0.18 + 18 * math.sin(t + i), x + 90, h * 0.18 + 36 + 18 * math.sin(t + i), fill='#ffffff', width=0)
    bx = w / 2 + math.cos(t * 1.4) * w * 0.32
    by = h * 0.5 + math.sin(t * 2.1) * h * 0.18
    c.create_oval(bx - 34, by - 34, bx + 34, by + 34, fill='#ff4d6d', outline='#ffffff', width=4)
    c.create_text(w / 2, h * 0.88, text='THIS IS YOUR GAME', fill='white', font=('Segoe UI', 26, 'bold'))
    c.create_text(w / 2, 22, text='%.0f s' % t, fill='white', font=('Consolas', 14))
    if t > 600:
        r.destroy()
        return
    r.after(16, frame)
r.after(16, frame)
r.mainloop()
"""


class Hub:
    def __init__(self):
        self.settings = load_settings()
        self.lock = threading.Lock()
        self.running = {}            # game id -> dict(proc, t0, pid, shots, next_shot)
        self.last_poll = time.time()
        self.token = secrets.token_urlsafe(18)
        self.games = scan_games(self.settings)
        self.events = []
        self.quit = False
        os.makedirs(ART_DIR, exist_ok=True)

    # -- state for the page ------------------------------------------------------------
    def state(self):
        with self.lock:
            self.last_poll = time.time()
            if time.time() - self.__dict__.get('_scan_t', 0) > 5:
                self.games = scan_games(self.settings)
                self._scan_t = time.time()
            st = self.settings.get('stats', {})
            games = []
            for g in self.games:
                d = dict(g)
                s = st.get(g['id'], {})
                d['stats'] = {'plays': s.get('plays', 0), 'seconds': int(s.get('seconds', 0)), 'last': s.get('last', 0)}
                r = self.running.get(g['id'])
                d['running'] = bool(r)
                d['since'] = r['t0'] if r else 0
                art = os.path.join(ART_DIR, g['id'] + '.png')
                d['art'] = int(os.path.getmtime(art)) if os.path.exists(art) else 0
                d['fav'] = g['id'] in self.settings.get('favs', [])
                d['folder'] = os.path.dirname(g['path'])
                d['file'] = os.path.basename(g['path'])
                d['gallery'] = gallery_of(g['id'])
                d.setdefault('features', [])
                games.append(d)
            ev, self.events = self.events, []
            return {'games': games, 'title': self.settings.get('title', 'Callum Games'),
                    'privacy': bool(self.settings.get('privacy')), 'privacy_asked': bool(self.settings.get('privacy_asked')),
                    'privacy_msg': self.settings.get('privacy_msg', ''),
                    'tagline': self.settings.get('tagline', ''), 'accent': self.settings.get('accent', '#a78bfa'),
                    'folder': HUB_DIR, 'version': VERSION, 'events': ev, 'now': time.time(),
                    'python': sys.version.split()[0]}

    # -- launching ----------------------------------------------------------------------
    def python_for_games(self):
        exe = sys.executable or 'python'
        if exe.lower().endswith('python.exe'):
            w = exe[:-10] + 'pythonw.exe'
            if os.path.exists(w):
                exe = w
        return exe

    def play(self, gid):
        with self.lock:
            g = next((g for g in self.games if g['id'] == gid), None)
            if not g:
                return {'ok': False, 'error': 'That game is not in the list any more.'}
            r = self.running.get(gid)
            if r and r['proc'].poll() is None:
                self.focus(r['proc'].pid)
                return {'ok': True, 'already': True}
            path = g['path']
            try:
                if path.lower().endswith(('.py', '.pyw')):
                    cmd = [self.python_for_games(), path]
                    pl = privacy_launcher() if self.settings.get('privacy') else None
                    if pl:
                        cmd = [self.python_for_games(), pl, path]
                else:
                    cmd = [path]
                flags = 0x00000008 | 0x00000200 if os.name == 'nt' else 0     # DETACHED_PROCESS | NEW_PROCESS_GROUP
                os.makedirs(LOG_DIR, exist_ok=True)
                log = open(os.path.join(LOG_DIR, gid + '.log'), 'w', encoding='utf-8', errors='replace')
                log.write('%s\n%s\n\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), ' '.join(cmd)))
                log.flush()
                env = dict(os.environ, CG_PRIVACY_MSG=self.settings.get('privacy_msg', '') or '')
                proc = subprocess.Popen(cmd, cwd=os.path.dirname(path) or None, creationflags=flags, env=env,
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                log.close()
            except Exception as e:
                return {'ok': False, 'error': 'Could not start it: %s' % e}
            self.running[gid] = {'proc': proc, 't0': time.time(), 'pid': proc.pid, 'shots': 0,
                                 'next_shot': time.time() + 12}
            st = self.settings.setdefault('stats', {}).setdefault(gid, {})
            st['plays'] = st.get('plays', 0) + 1
            st['last'] = time.time()
            save_settings(self.settings)
            return {'ok': True, 'pid': proc.pid}

    def test_hwnd(self, key):
        with self.lock:
            r = self.running.get(key)
        if r and r['proc'].poll() is None:
            ws = [w for pid in process_tree(r['pid']) for w in windows_of(pid) if window_title(w[0]) != 'cg-decoy']
            if ws:
                return max(ws, key=lambda t: t[1] * t[2])[0]
        return None

    def preview_png(self, how, mode='window'):
        """'me': the unprotected twin (a protected window can't be copied by anything, not even by us);
        'them': the protected test window, copied off the desktop the way a screen recording gets it."""
        if mode == 'screen':                                  # your whole screen, full detail
            return screen_view(how, self.test_hwnd('_test'), self.test_hwnd('_twin'))
        h = self.test_hwnd('_twin' if how == 'me' else '_test')
        return window_view(h, how, 900) if h else None

    def test_start(self, priv, msg):
        """Open (or restart) the little test window - protected, with the message behind it, when priv is on."""
        self.test_stop()
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tw = os.path.join(DATA_DIR, 'overlay_test.py')
            with open(tw, 'w', encoding='utf-8') as f:
                f.write(TEST_WINDOW)
            cmd = [self.python_for_games(), tw]
            env = dict(os.environ, CG_PRIVACY_MSG=msg if priv else '', CG_DECOY_TOP='1')
            if priv:
                pl = privacy_launcher()
                if pl:
                    cmd = [self.python_for_games(), pl, tw]
            proc = subprocess.Popen(cmd, env=env, creationflags=0x08000000, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            twin = subprocess.Popen([self.python_for_games(), tw, 'twin'], creationflags=0x08000000,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        with self.lock:
            for key, pr in (('_test', proc), ('_twin', twin)):
                self.running[key] = {'proc': pr, 't0': time.time(), 'pid': pr.pid, 'shots': 99, 'next_shot': 1e18}
        return {'ok': True}

    def test_stop(self):
        with self.lock:
            rs = [self.running.pop(k, None) for k in ('_test', '_twin')]
        for r in rs:
            if r and r['proc'].poll() is None:
                try:
                    r['proc'].terminate()
                except Exception:
                    pass
        return {'ok': True}

    def stop(self, gid):
        with self.lock:
            r = self.running.get(gid)
            if not r:
                return {'ok': True}
            try:
                for h, _, _ in windows_of(r['pid']):
                    u32.PostMessageW(h, 0x0010, 0, 0)          # WM_CLOSE: ask nicely first
                time.sleep(0.8)
                if r['proc'].poll() is None:
                    r['proc'].terminate()
            except Exception:
                pass
            return {'ok': True}

    def focus(self, pid):
        try:
            ws = windows_of(pid)
            if ws:
                h = max(ws, key=lambda t: t[1] * t[2])[0]
                u32.ShowWindow(h, 9)
                u32.SetForegroundWindow(h)
        except Exception:
            pass

    # -- the watcher: play time, art, finished games ----------------------------------------
    def tick(self):
        with self.lock:
            now = time.time()
            for gid, r in list(self.running.items()):
                code = r['proc'].poll()
                if gid.startswith('_'):                              # (the overlay test windows are not games)
                    if code is not None:
                        del self.running[gid]
                    continue
                if code is not None:
                    secs = now - r['t0']
                    st = self.settings.setdefault('stats', {}).setdefault(gid, {})
                    st['seconds'] = st.get('seconds', 0) + secs
                    save_settings(self.settings)
                    del self.running[gid]
                    self.events.append({'t': 'ended', 'id': gid, 'seconds': int(secs), 'code': code})
                    continue
                if now >= r['next_shot']:
                    r['next_shot'] = now + (20 if r['shots'] == 0 else 60)
                    try:
                        ws = windows_of(r['pid'])
                        if ws:
                            h = max(ws, key=lambda t: t[1] * t[2])[0]
                            if capture_window(h, os.path.join(ART_DIR, gid + '.png')):
                                r['shots'] += 1
                                keep_gallery_shot(gid, os.path.join(ART_DIR, gid + '.png'))
                                self.events.append({'t': 'art', 'id': gid})
                    except Exception:
                        traceback.print_exc()

    def shot_now(self, gid):
        with self.lock:
            r = self.running.get(gid)
            if not r:
                return {'ok': False, 'error': 'Start the game first - the picture is taken from its window.'}
            ws = windows_of(r['pid'])
            if not ws:
                return {'ok': False, 'error': "Can't see its window (is it minimised?)."}
            h = max(ws, key=lambda t: t[1] * t[2])[0]
            ok = capture_window(h, os.path.join(ART_DIR, gid + '.png'))
            if ok:
                keep_gallery_shot(gid, os.path.join(ART_DIR, gid + '.png'))
            return {'ok': ok, 'error': None if ok else 'The window looks blank right now - try again in a moment.'}

    # -- adding, removing, settings -------------------------------------------------------
    def add_game(self):
        """A file picker, in its own little process (tkinter is happiest on a main thread of its own)."""
        code = ("import tkinter as tk\nfrom tkinter import filedialog\nr=tk.Tk();r.withdraw();r.attributes('-topmost',1)\n"
                "p=filedialog.askopenfilename(title='Add a game to the hub',"
                "filetypes=[('Games','*.py *.pyw *.exe *.bat *.lnk'),('All files','*.*')])\nprint(p)")
        try:
            out = subprocess.run([self.python_for_games().replace('pythonw.exe', 'python.exe'), '-c', code],
                                 capture_output=True, text=True, timeout=600, creationflags=0x08000000).stdout.strip()
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        if not out:
            return {'ok': False, 'cancelled': True}
        path = os.path.abspath(out)
        with self.lock:
            lst = self.settings.setdefault('games', [])
            if not any(os.path.normcase(a.get('path', '')) == os.path.normcase(path) for a in lst):
                lst.append({'path': path, 'added': time.time()})
            hid = self.settings.setdefault('hidden', [])
            gid_a = 'a_' + hashlib.sha1(os.path.normcase(path).encode('utf-8')).hexdigest()[:10]
            for g in (gid_a, game_id_for(path)):
                if g in hid:
                    hid.remove(g)
            save_settings(self.settings)
            self._scan_t = 0
        return {'ok': True, 'path': path}

    def remove_game(self, gid):
        with self.lock:
            g = next((g for g in self.games if g['id'] == gid), None)
            if not g:
                return {'ok': True}
            if g['source'] == 'added':
                self.settings['games'] = [a for a in self.settings.get('games', [])
                                          if os.path.normcase(a.get('path', '')) != os.path.normcase(g['path'])]
            else:
                self.settings.setdefault('hidden', []).append(gid)
            save_settings(self.settings)
            self._scan_t = 0
            return {'ok': True}

    def restore_hidden(self):
        with self.lock:
            self.settings['hidden'] = []
            save_settings(self.settings)
            self._scan_t = 0
            return {'ok': True}

    def toggle_fav(self, gid):
        with self.lock:
            f = self.settings.setdefault('favs', [])
            if gid in f:
                f.remove(gid)
            else:
                f.append(gid)
            save_settings(self.settings)
            return {'ok': True, 'fav': gid in f}

    def set_settings(self, d):
        with self.lock:
            for k in ('title', 'tagline', 'accent'):
                if k in d and isinstance(d[k], str):
                    v = d[k].strip()[:40]
                    if k == 'accent' and not re.match(r'^#[0-9a-fA-F]{6}$', v):
                        continue
                    self.settings[k] = v or load_settings()[k]
            for k in ('privacy', 'privacy_asked'):
                if k in d:
                    self.settings[k] = bool(d[k])
            if isinstance(d.get('privacy_msg'), str):
                self.settings['privacy_msg'] = d['privacy_msg'].strip()[:90]
            save_settings(self.settings)
            return {'ok': True}

    def open_folder(self, gid):
        g = next((g for g in self.games if g['id'] == gid), None)
        if g:
            try:
                subprocess.Popen(['explorer', '/select,', g['path']])
            except Exception:
                os.startfile(os.path.dirname(g['path']))
        return {'ok': True}


# ----------------------------------------------------------------------------
#  THE PAGE
# ----------------------------------------------------------------------------
PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Callum Games</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23a78bfa'/%3E%3Cpath d='M32 12l17 9.8v20.4L32 52l-17-9.8V21.8z M32 32l17-9.8M32 32v20M32 32L15 22.2' fill='none' stroke='%23fff' stroke-width='4.5' stroke-linejoin='round' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
:root{
  --bg:#0a0a0f; --bg2:#0e0e15; --panel:#12121a; --panel2:#171722; --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.14);
  --text:#f3f3f8; --muted:#9a9aae; --faint:#5f5f72; --accent:#a78bfa; --accent-rgb:167,139,250;
  --pink:#f472b6; --orange:#fb923c; --violet:#a78bfa; --green:#4ade80;
  --r:16px; --font:"Segoe UI Variable Display","Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box} html,body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;-webkit-font-smoothing:antialiased}
body{min-height:100vh;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(900px 500px at 15% -10%, rgba(var(--accent-rgb),.18), transparent 60%),
             radial-gradient(700px 400px at 90% 10%, rgba(244,114,182,.10), transparent 60%),
             radial-gradient(800px 600px at 50% 110%, rgba(56,189,248,.08), transparent 60%)}
body:after{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.35;
  background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
  background-size:36px 36px;mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%);-webkit-mask-image:radial-gradient(ellipse at 50% 0%,#000 30%,transparent 75%)}
a{color:inherit;text-decoration:none} button{font:inherit;color:inherit;cursor:pointer;border:0;background:0}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:18px 28px 60px}

/* top bar */
.top{display:flex;align-items:center;gap:14px;padding:10px 0 26px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--accent),#6d4df0 70%);box-shadow:0 8px 24px rgba(var(--accent-rgb),.35),inset 0 1px 0 rgba(255,255,255,.35)}
.logo svg{width:20px;height:20px}
.brand b{font-size:17px;letter-spacing:.01em;display:block;line-height:1.1}
.brand small{color:var(--muted);font-size:12px}
.nav{display:flex;gap:4px;margin-left:16px;padding:4px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.03)}
.nav button{padding:7px 14px;border-radius:9px;color:var(--muted);font-weight:600;font-size:13px;transition:.18s}
.nav button:hover{color:var(--text)} .nav button.on{background:rgba(255,255,255,.08);color:var(--text)}
.spacer{flex:1}
.search{display:flex;align-items:center;gap:8px;height:38px;padding:0 12px;border:1px solid var(--line);border-radius:11px;background:rgba(255,255,255,.03);color:var(--muted);width:230px;transition:.18s}
.search:focus-within{border-color:rgba(var(--accent-rgb),.6);box-shadow:0 0 0 3px rgba(var(--accent-rgb),.15)}
.search input{flex:1;min-width:0;background:0;border:0;outline:0;color:var(--text);font-size:14px} .search input::placeholder{color:var(--faint)}
.search kbd{font:11px var(--font);color:var(--faint);border:1px solid var(--line2);border-radius:5px;padding:1px 5px}
.btn{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 15px;border-radius:11px;font-weight:700;font-size:13.5px;border:1px solid var(--line2);background:rgba(255,255,255,.04);transition:.18s;white-space:nowrap}
.btn:hover{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.22);transform:translateY(-1px)}
.btn:active{transform:translateY(0)} .btn svg{width:16px;height:16px}
.btn.primary{background:var(--accent);border-color:transparent;color:#120a2a;box-shadow:0 8px 20px rgba(var(--accent-rgb),.3)}
.btn.primary:hover{filter:brightness(1.08)}
.btn.icon{width:38px;padding:0;justify-content:center;color:var(--muted)} .btn.icon:hover{color:var(--text)}

/* hero */
.hero{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:22px;align-items:stretch;margin-bottom:46px}
.card{position:relative;background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.015));border:1px solid var(--line);border-radius:var(--r);
  box-shadow:0 20px 60px rgba(0,0,0,.35)}
.hero .intro{padding:30px 32px;display:flex;flex-direction:column;gap:14px;justify-content:center}
.intro .mark{display:flex;align-items:center;gap:16px}
.intro .mark .logo{width:56px;height:56px;border-radius:17px} .intro .mark .logo svg{width:28px;height:28px}
.intro h1{margin:0;font-size:30px;letter-spacing:-.01em;line-height:1.1}
.intro .tag{color:var(--muted);font-size:14.5px;margin-top:4px}
.intro p{margin:4px 0 0;color:var(--muted);line-height:1.55;font-size:14.5px}
.intro p b{color:var(--text);font-weight:600}
.intro .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
.made{display:inline-flex;align-items:center;gap:8px;color:#fde68a;font-size:12.5px;font-weight:700;letter-spacing:.02em}
.made i{width:6px;height:6px;border-radius:50%;background:#fde68a;box-shadow:0 0 12px #fde68a;display:inline-block}
.hero .feat{overflow:hidden;min-height:300px;display:flex;flex-direction:column}
.feat .shot{flex:1;position:relative;min-height:240px;background:#0c0c13 center/cover no-repeat}
.feat .shot:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 45%,rgba(10,10,15,.92))}
.feat .shot .ph{position:absolute;inset:0;display:grid;place-items:center;color:rgba(255,255,255,.14)} .feat .shot .ph svg{width:120px;height:120px}
.feat .bar{position:absolute;left:0;right:0;bottom:0;padding:18px 22px;display:flex;align-items:flex-end;gap:16px;z-index:1}
.feat .bar .t{flex:1;min-width:0} .feat .bar .k{font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:700}
.feat .bar h2{margin:2px 0 2px;font-size:24px} .feat .bar .s{color:var(--muted);font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.feat .frame{position:absolute;inset:0;pointer-events:none;border-radius:var(--r);box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}

/* section heads */
.sec{display:flex;align-items:baseline;gap:14px;margin:0 0 16px}
.sec h3{margin:0;font-size:20px;letter-spacing:-.01em} .sec span{color:var(--muted);font-size:13.5px}
.sec .right{margin-left:auto;display:flex;gap:8px}

/* game grid */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px;margin-bottom:46px}
.game{display:flex;flex-direction:column;overflow:hidden;transition:transform .22s cubic-bezier(.2,.8,.2,1),box-shadow .22s,border-color .22s;cursor:pointer;outline:0}
.game:hover,.game:focus-visible{transform:translateY(-4px);border-color:rgba(255,255,255,.16);box-shadow:0 26px 60px rgba(0,0,0,.5),0 0 0 1px color-mix(in srgb,var(--c) 35%,transparent),0 0 60px -20px var(--c)}
.game .art{position:relative;aspect-ratio:16/9;background:#0c0c13 center/cover no-repeat;border-bottom:1px solid var(--line)}
.game .art .ph{position:absolute;inset:0;display:grid;place-items:center;background:
  radial-gradient(120% 90% at 20% 0%,color-mix(in srgb,var(--c) 28%,transparent),transparent 60%),linear-gradient(160deg,#171724,#0c0c13)}
.game .art .ph svg{width:72px;height:72px;color:var(--c);filter:drop-shadow(0 10px 30px color-mix(in srgb,var(--c) 50%,transparent))}
.game .art:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 55%,rgba(18,18,26,.9))}
.game .art .badges{position:absolute;top:10px;left:10px;right:10px;display:flex;gap:6px;z-index:1}
.badge{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 9px;border-radius:7px;font-size:11.5px;font-weight:700;letter-spacing:.02em;background:rgba(10,10,15,.72);backdrop-filter:blur(6px);border:1px solid var(--line)}
.badge.run{color:#4ade80;border-color:rgba(74,222,128,.35)} .badge.run i{width:7px;height:7px;border-radius:50%;background:#4ade80;box-shadow:0 0 10px #4ade80;animation:pulse 1.2s infinite}
@keyframes pulse{50%{opacity:.35}}
.badge.fav{margin-left:auto;color:#fde68a;border-color:rgba(253,230,138,.3)}
.game .body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:9px;flex:1}
.game h4{margin:0;font-size:18px;color:var(--c);display:flex;align-items:center;gap:9px}
.game h4 .ico{width:22px;height:22px;border-radius:7px;display:grid;place-items:center;background:color-mix(in srgb,var(--c) 18%,transparent)} .game h4 .ico svg{width:13px;height:13px}
.game .tl{color:var(--text);font-weight:600;font-size:14px;margin-top:-4px}
.game .d{color:var(--muted);font-size:13.5px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.chips{display:flex;flex-wrap:wrap;gap:6px} .chip{font-size:11.5px;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:3px 8px;background:rgba(255,255,255,.02)}
.game .foot{display:flex;align-items:center;gap:10px;margin-top:auto;padding-top:6px}
.game .meta{color:var(--faint);font-size:12px;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.play{height:36px;padding:0 16px;border-radius:10px;font-weight:800;font-size:13.5px;display:inline-flex;align-items:center;gap:8px;color:#0b0b10;background:var(--c);box-shadow:0 8px 22px -6px var(--c);transition:.18s}
.play:hover{filter:brightness(1.08);transform:translateY(-1px)} .play svg{width:14px;height:14px}
.play.busy{opacity:.75;pointer-events:none} .play .spin{width:14px;height:14px;border:2px solid rgba(0,0,0,.25);border-top-color:#000;border-radius:50%;animation:rot .8s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
.play.running{background:rgba(255,255,255,.08);color:var(--text);box-shadow:none;border:1px solid var(--line2)}
.more{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;color:var(--muted);border:1px solid var(--line);transition:.18s} .more:hover{color:var(--text);background:rgba(255,255,255,.06)} .more svg{width:16px;height:16px}
.empty{padding:40px;text-align:center;color:var(--muted);border:1px dashed var(--line2);border-radius:var(--r)}

/* stat tiles ("why us" style) */
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.tile{padding:20px 20px 18px;display:flex;flex-direction:column;gap:8px;min-height:150px}
.tile .ic{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;background:color-mix(in srgb,var(--c) 18%,transparent);color:var(--c)} .tile .ic svg{width:15px;height:15px}
.tile h5{margin:4px 0 0;font-size:15px;color:var(--c)} .tile .v{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1}
.tile p{margin:0;color:var(--muted);font-size:13px;line-height:1.5}

/* menus, modal, toasts */
.menu{position:fixed;z-index:50;min-width:200px;padding:6px;background:#15151f;border:1px solid var(--line2);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.6);display:none}
.menu.open{display:block;animation:pop .14s ease} @keyframes pop{from{opacity:0;transform:scale(.96) translateY(-4px)}}
.menu button{display:flex;width:100%;align-items:center;gap:10px;padding:9px 11px;border-radius:8px;font-size:13.5px;color:var(--text);text-align:left} .menu button:hover{background:rgba(255,255,255,.07)}
.menu button.danger{color:#fb7185} .menu button svg{width:15px;height:15px;color:var(--muted)} .menu hr{border:0;border-top:1px solid var(--line);margin:5px 0}
.scrim{position:fixed;inset:0;z-index:60;background:rgba(5,5,10,.7);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:24px}
.scrim.open{display:flex;animation:fade .18s ease} @keyframes fade{from{opacity:0}}
.modal{width:min(820px,100%);max-height:90vh;overflow:auto;background:#12121a;border:1px solid var(--line2);border-radius:20px;box-shadow:0 40px 120px rgba(0,0,0,.7);animation:up .22s cubic-bezier(.2,.8,.2,1)} @keyframes up{from{transform:translateY(14px);opacity:0}}
.modal .mart{aspect-ratio:21/9;background:#0c0c13 center/cover no-repeat;position:relative;border-bottom:1px solid var(--line)} .modal .mart:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 40%,rgba(18,18,26,.95))}
.modal .mart .ph{position:absolute;inset:0;display:grid;place-items:center;color:var(--c);opacity:.5} .modal .mart .ph svg{width:110px;height:110px}
.modal .mhead{position:absolute;left:26px;right:26px;bottom:18px;z-index:1;display:flex;align-items:flex-end;gap:14px}
.modal .mhead h2{margin:0;font-size:30px;color:var(--c)} .modal .mhead .tl{color:var(--muted);font-size:14px}
.modal .mbody{padding:22px 26px 26px;display:grid;grid-template-columns:1.4fr 1fr;gap:22px}
.modal p{margin:0 0 12px;color:var(--muted);line-height:1.6;font-size:14.5px}
.modal .k{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);font-weight:700;margin:14px 0 6px}
.modal code{font:12.5px Consolas,monospace;color:var(--text);background:rgba(255,255,255,.05);border:1px solid var(--line);border-radius:8px;padding:8px 10px;display:block;white-space:pre-wrap;word-break:break-all}
.modal .stats{display:grid;grid-template-columns:1fr 1fr;gap:10px} .modal .stat{padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.02)}
.modal .stat b{display:block;font-size:20px} .modal .stat span{color:var(--muted);font-size:12px}
.modal .acts{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.x{position:absolute;top:14px;right:14px;z-index:2;width:34px;height:34px;border-radius:10px;background:rgba(10,10,15,.7);border:1px solid var(--line2);display:grid;place-items:center;color:var(--muted)} .x:hover{color:var(--text)} .x svg{width:15px;height:15px}
.form{display:flex;flex-direction:column;gap:12px;padding:26px} .form label{display:flex;flex-direction:column;gap:6px;font-size:12.5px;color:var(--muted);font-weight:600}
.form input[type=text]{height:40px;border-radius:10px;border:1px solid var(--line2);background:rgba(255,255,255,.04);color:var(--text);padding:0 12px;font:inherit;outline:0} .form input[type=text]:focus{border-color:var(--accent)}
.swatches{display:flex;gap:8px;flex-wrap:wrap} .sw{width:30px;height:30px;border-radius:9px;border:2px solid transparent;cursor:pointer;transition:.15s} .sw.on,.sw:hover{border-color:#fff;transform:scale(1.08)}
.toasts{position:fixed;right:22px;bottom:22px;z-index:80;display:flex;flex-direction:column;gap:8px}
.toast{padding:11px 14px;border-radius:12px;background:#15151f;border:1px solid var(--line2);box-shadow:0 16px 40px rgba(0,0,0,.5);font-size:13.5px;display:flex;align-items:center;gap:10px;animation:up .2s ease;max-width:360px}
.toast.bad{border-color:rgba(251,113,133,.4)} .toast i{width:8px;height:8px;border-radius:50%;background:var(--accent);flex:none} .toast.bad i{background:#fb7185}
.foot{margin-top:40px;color:var(--faint);font-size:12.5px;display:flex;gap:14px;flex-wrap:wrap;align-items:center} .foot a{color:var(--muted)} .foot a:hover{color:var(--text)}
.in{animation:in .5s cubic-bezier(.2,.8,.2,1) both} @keyframes in{from{opacity:0;transform:translateY(12px)}}
/* the game page (opens from any Play button) */
.gp{position:fixed;inset:0;z-index:55;overflow-y:auto;background:var(--bg);display:none}
.gp.open{display:block;animation:gpIn .28s cubic-bezier(.2,.8,.2,1)} @keyframes gpIn{from{opacity:0;transform:scale(.985)}}
.gp .bgart{position:absolute;inset:0 0 auto 0;height:620px;background:#0c0c13 center/cover no-repeat;filter:blur(28px) saturate(1.2);opacity:.45;transform:scale(1.1)}
.gp .bgart:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(10,10,15,.2),var(--bg) 92%)}
.gp .gwrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:18px 28px 70px}
.gp .gtop{display:flex;align-items:center;gap:12px;padding:6px 0 22px}
.gp .back{display:inline-flex;align-items:center;gap:8px;height:38px;padding:0 14px;border-radius:11px;border:1px solid var(--line2);background:rgba(10,10,15,.55);backdrop-filter:blur(8px);font-weight:700;font-size:13.5px;color:var(--muted);transition:.18s}
.gp .back:hover{color:var(--text);transform:translateX(-2px)} .gp .back svg{width:16px;height:16px}
.gp .ghero{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:22px;align-items:start}
.viewer{position:relative;aspect-ratio:16/9;border-radius:18px;overflow:hidden;background:#0c0c13;border:1px solid var(--line2);box-shadow:0 30px 80px rgba(0,0,0,.55),0 0 80px -30px var(--c)}
.viewer img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .45s ease,transform 6s ease;cursor:zoom-in}
.viewer img.on{opacity:1;transform:scale(1.035)}
.viewer .ph{position:absolute;inset:0;display:grid;place-items:center;text-align:center;background:radial-gradient(120% 90% at 20% 0%,color-mix(in srgb,var(--c) 30%,transparent),transparent 60%),linear-gradient(160deg,#171724,#0c0c13);color:var(--muted);font-size:13.5px}
.viewer .ph svg{width:96px;height:96px;color:var(--c);display:block;margin:0 auto 14px;filter:drop-shadow(0 10px 30px color-mix(in srgb,var(--c) 50%,transparent))}
.viewer .nav2{position:absolute;top:50%;transform:translateY(-50%);width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:rgba(10,10,15,.6);border:1px solid var(--line2);color:var(--text);opacity:0;transition:.2s;backdrop-filter:blur(6px)}
.viewer:hover .nav2{opacity:1} .viewer .nav2.l{left:12px} .viewer .nav2.r{right:12px} .viewer .nav2 svg{width:18px;height:18px}
.viewer .count{position:absolute;right:12px;bottom:12px;font-size:11.5px;font-weight:700;padding:4px 9px;border-radius:7px;background:rgba(10,10,15,.7);border:1px solid var(--line);color:var(--muted)}
.thumbs{display:flex;gap:10px;margin-top:12px;overflow-x:auto;padding-bottom:6px;scrollbar-width:thin}
.thumbs button{flex:none;width:118px;aspect-ratio:16/9;border-radius:10px;background:#0c0c13 center/cover no-repeat;border:2px solid transparent;opacity:.55;transition:.18s}
.thumbs button:hover{opacity:.9} .thumbs button.on{opacity:1;border-color:var(--c);box-shadow:0 0 18px -4px var(--c)}
.thumbs .addshot{display:grid;place-items:center;color:var(--muted);border:1px dashed var(--line2);background:rgba(255,255,255,.02);font-size:11.5px;font-weight:700;opacity:.8}
.side{display:flex;flex-direction:column;gap:14px}
.side .gico{width:64px;height:64px;border-radius:18px;display:grid;place-items:center;color:var(--c);background:color-mix(in srgb,var(--c) 16%,transparent);border:1px solid color-mix(in srgb,var(--c) 35%,transparent)} .side .gico svg{width:32px;height:32px}
.side h1{margin:0;font-size:38px;letter-spacing:-.02em;line-height:1.05;color:var(--c)}
.side .tl{font-size:16px;font-weight:600;color:var(--text);margin-top:-4px}
.side .d{color:var(--muted);line-height:1.6;font-size:14.5px;margin:0}
.launch{display:flex;align-items:center;justify-content:center;gap:10px;height:56px;border-radius:14px;font-weight:800;font-size:17px;color:#0b0b10;background:var(--c);
  box-shadow:0 14px 40px -10px var(--c),inset 0 1px 0 rgba(255,255,255,.4);transition:.18s;position:relative;overflow:hidden}
.launch:before{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.35) 50%,transparent 70%);transform:translateX(-100%);animation:shine 3.2s ease-in-out infinite}
@keyframes shine{60%,100%{transform:translateX(100%)}}
.launch:hover{filter:brightness(1.08);transform:translateY(-2px)} .launch svg{width:18px;height:18px}
.launch.running{background:rgba(255,255,255,.08);color:var(--text);box-shadow:none;border:1px solid var(--line2)} .launch.running:before{display:none}
.launch.busy{opacity:.8;pointer-events:none} .launch .spin{width:18px;height:18px;border:2px solid rgba(0,0,0,.25);border-top-color:#000;border-radius:50%;animation:rot .8s linear infinite}
.side .sub{display:flex;gap:8px} .side .sub .btn{flex:1;justify-content:center}
.side .live{display:flex;align-items:center;gap:8px;color:#4ade80;font-size:13px;font-weight:700} .side .live i{width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 10px #4ade80;animation:pulse 1.2s infinite}
.gsecs{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:22px;margin-top:34px;align-items:start}
.gbox{padding:22px 24px} .gbox h3{margin:0 0 14px;font-size:16px;display:flex;align-items:center;gap:10px} .gbox h3 i{width:4px;height:16px;border-radius:2px;background:var(--c)}
.feats{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.feat2{display:flex;gap:10px;align-items:flex-start;padding:12px 13px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.02);font-size:13.5px;line-height:1.45;color:var(--text)}
.feat2 b{flex:none;width:20px;height:20px;border-radius:6px;display:grid;place-items:center;background:color-mix(in srgb,var(--c) 18%,transparent);color:var(--c);font-size:11px}
.keys{display:flex;flex-direction:column;gap:8px}
.keyrow{display:flex;align-items:center;gap:10px;font-size:13.5px;color:var(--muted)} .keyrow kbd{min-width:0;font:700 12px var(--font);color:var(--text);padding:5px 9px;border-radius:7px;border:1px solid var(--line2);border-bottom-width:3px;background:rgba(255,255,255,.04);white-space:nowrap}
.gstats{display:grid;grid-template-columns:1fr 1fr;gap:10px} .gstat{padding:14px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.02)} .gstat b{display:block;font-size:22px;letter-spacing:-.01em} .gstat span{color:var(--muted);font-size:12px}
.lightbox{position:fixed;inset:0;z-index:90;background:rgba(5,5,8,.94);display:none;align-items:center;justify-content:center;cursor:zoom-out}
.lightbox.open{display:flex;animation:fade .18s ease} .lightbox img{max-width:94vw;max-height:90vh;border-radius:12px;box-shadow:0 30px 100px rgba(0,0,0,.8)}
@media (max-width:900px){.gp .ghero,.gsecs{grid-template-columns:1fr}.feats{grid-template-columns:1fr}}
/* ---------- motion: living background, springy cards, jelly buttons ---------- */
#fx{position:fixed;inset:0;z-index:0;pointer-events:none}
.blob{position:fixed;z-index:0;pointer-events:none;border-radius:50%;filter:blur(70px);opacity:.38;mix-blend-mode:screen;will-change:transform}
.blob.a{width:520px;height:520px;background:radial-gradient(circle,var(--accent),transparent 65%);left:-120px;top:-140px;animation:drift1 22s ease-in-out infinite alternate}
.blob.b{width:460px;height:460px;background:radial-gradient(circle,#f472b6,transparent 65%);right:-140px;top:120px;animation:drift2 26s ease-in-out infinite alternate}
.blob.c{width:600px;height:600px;background:radial-gradient(circle,#38bdf8,transparent 65%);left:30%;bottom:-320px;animation:drift3 30s ease-in-out infinite alternate}
@keyframes drift1{to{transform:translate(220px,160px) scale(1.25)}}
@keyframes drift2{to{transform:translate(-260px,140px) scale(.85)}}
@keyframes drift3{to{transform:translate(-180px,-140px) scale(1.15)}}
.game{transform-style:preserve-3d;will-change:transform}
.game.in{animation-fill-mode:backwards}
.game:hover,.game:focus-visible{transform:none}
.game .art{transition:background-size .5s}
.game .shine{position:absolute;inset:0;z-index:2;pointer-events:none;border-radius:var(--r);opacity:0;transition:opacity .3s;
  background:radial-gradient(420px circle at var(--mx,50%) var(--my,50%),rgba(255,255,255,.16),transparent 45%)}
.game:hover .shine{opacity:1}
.jelly{animation:jelly .55s cubic-bezier(.3,1.6,.5,1)}
@keyframes jelly{0%{transform:scale(1,1)}25%{transform:scale(1.12,.88)}45%{transform:scale(.92,1.08)}65%{transform:scale(1.04,.96)}82%{transform:scale(.99,1.01)}100%{transform:scale(1,1)}}
.btn,.play,.launch,.nav button{transition:transform .35s cubic-bezier(.3,1.8,.5,1),filter .2s,background .2s,box-shadow .2s}
.btn:hover,.play:hover{transform:translateY(-2px) scale(1.04)}
.btn:active,.play:active,.launch:active{transform:scale(.93)}
.logo{animation:bob 4s ease-in-out infinite}
.logo:hover{animation:wobble .7s cubic-bezier(.3,1.8,.5,1)}
@keyframes bob{50%{transform:translateY(-3px) rotate(-3deg)}}
@keyframes wobble{0%{transform:rotate(0)}20%{transform:rotate(-14deg) scale(1.1)}40%{transform:rotate(10deg)}60%{transform:rotate(-6deg)}80%{transform:rotate(3deg)}100%{transform:rotate(0)}}
.in{animation:popin .8s cubic-bezier(.2,1.5,.4,1) both}
@keyframes popin{0%{opacity:0;transform:translateY(26px) scale(.94)}100%{opacity:1;transform:none}}
#heroTitle,.side h1{background:linear-gradient(90deg,var(--text),var(--accent),#f472b6,var(--text));background-size:300% 100%;
  -webkit-background-clip:text;background-clip:text;color:transparent !important;animation:sheen 6s linear infinite}
.side h1{background:linear-gradient(90deg,var(--c),#fff,var(--c));background-size:300% 100%;-webkit-background-clip:text;background-clip:text}
@keyframes sheen{to{background-position:300% 0}}
.tile{transition:transform .45s cubic-bezier(.3,1.7,.5,1)}
.tile:hover{transform:translateY(-6px) rotate(-1deg) scale(1.02)}
.tile .v{display:inline-block;transition:transform .4s cubic-bezier(.3,2,.5,1)}
.tile:hover .v{transform:scale(1.15)}
.toast{animation:toastin .5s cubic-bezier(.3,1.6,.5,1)}
@keyframes toastin{from{opacity:0;transform:translateX(60px) scale(.9)}}
.modal{animation:modalin .5s cubic-bezier(.25,1.5,.45,1)}
@keyframes modalin{from{opacity:0;transform:translateY(30px) scale(.92)}}
.ripple{position:absolute;border-radius:50%;pointer-events:none;background:rgba(255,255,255,.35);transform:scale(0);animation:rip .6s ease-out forwards}
@keyframes rip{to{transform:scale(4);opacity:0}}
/* settings: the privacy overlay, shown off */
.set{padding:26px;display:flex;flex-direction:column;gap:18px}
.set h2{margin:0;font-size:24px}
.set .grp{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.priv{border-radius:18px;padding:20px;border:1px solid rgba(var(--accent-rgb),.35);
  background:linear-gradient(135deg,rgba(var(--accent-rgb),.16),rgba(244,114,182,.08) 60%,rgba(56,189,248,.08));position:relative;overflow:hidden}
.priv:before{content:"";position:absolute;inset:-40%;background:conic-gradient(from 0deg,transparent,rgba(var(--accent-rgb),.25),transparent 30%);animation:spin 8s linear infinite;opacity:.5}
@keyframes spin{to{transform:rotate(360deg)}}
.priv>*{position:relative}
.priv .hd{display:flex;align-items:center;gap:14px}
.priv .shield{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;background:var(--accent);color:#120a2a;box-shadow:0 10px 30px rgba(var(--accent-rgb),.5)}
.priv .shield svg{width:26px;height:26px}
.priv h3{margin:0;font-size:19px} .priv p{margin:6px 0 0;color:var(--muted);font-size:14px;line-height:1.55}
.screens{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}
.scr{border-radius:12px;border:1px solid var(--line2);overflow:hidden;background:#07070b}
.scr .cap{font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);padding:8px 10px;border-bottom:1px solid var(--line)}
.scr .view{aspect-ratio:16/9;position:relative;display:grid;place-items:center;overflow:hidden}
.scr .game-v{background:linear-gradient(180deg,#5aa0ff 0 45%,#4ade80 45% 62%,#7c5a3a 62%)}
.scr .game-v:after{content:"";position:absolute;width:30%;height:22%;left:35%;top:30%;background:#2f7a2f;box-shadow:40px 10px 0 -6px #2a6a2a,-50px 14px 0 -8px #2a6a2a;animation:float 3s ease-in-out infinite}
@keyframes float{50%{transform:translateY(-5px)}}
.scr .blank{background:#000;transition:background .5s}
.scr .blank .lock{color:var(--muted);text-align:center;font-size:12px;font-weight:700;transition:opacity .4s,transform .5s cubic-bezier(.3,1.8,.5,1)}
.scr .blank .lock svg{width:30px;height:30px;display:block;margin:0 auto 6px;color:var(--accent)}
.scr .blank{background:#0d0d14} .scr .blank .lock{width:86%}
.scr .blank .msg{color:#f3f3f8;font-size:15px;font-weight:800;line-height:1.3;word-break:break-word;animation:none}
.scr .blank .msg:empty:before{content:'(blank window)';color:var(--faint);font-weight:600;font-size:12px}
.scr .view.lv{background:#07070b}
.scr .view.lv img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .25s}
.scr .view.lv img.on{opacity:1}
.scr .view.lv .ph{position:relative;color:var(--faint);font-size:12.5px;font-weight:600;text-align:center;padding:0 14px}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#444;margin-left:6px;vertical-align:middle}
.live.on{background:#4ade80;box-shadow:0 0 10px #4ade80;animation:pulse 1.2s infinite}
.pvbar{display:flex;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}
.screens.big{grid-template-columns:1fr}
.screens.big .scr .view.lv{aspect-ratio:16/9}
.scr .view.lv img{object-fit:contain;image-rendering:auto}
.seg{display:flex;border:1px solid var(--line2);border-radius:10px;overflow:hidden}
.seg button{padding:8px 13px;font-weight:700;font-size:13px;color:var(--muted);background:rgba(255,255,255,.03);transition:.18s}
.seg button.on{background:rgba(var(--accent-rgb),.22);color:var(--text)}
.pvbar span{color:var(--faint);font-size:12px;line-height:1.45}
.priv:not(.on) .blank .lock{opacity:0;transform:scale(.4)}
.toggle{display:flex;align-items:center;gap:14px;margin-top:16px;cursor:pointer;user-select:none}
.toggle .tr{width:62px;height:34px;border-radius:999px;background:rgba(255,255,255,.12);border:1px solid var(--line2);position:relative;transition:background .3s}
.toggle .kn{position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;box-shadow:0 4px 12px rgba(0,0,0,.4);transition:left .45s cubic-bezier(.3,1.8,.5,1),width .2s}
.toggle:active .kn{width:34px}
.priv.on .toggle .tr{background:var(--accent)} .priv.on .toggle .kn{left:31px}
.priv.on .toggle:active .kn{left:23px}
.toggle b{font-size:15px}
@media (prefers-reduced-motion:reduce){*{animation:none !important;transition:none !important}}
@media (max-width:900px){.hero{grid-template-columns:1fr}.tiles{grid-template-columns:1fr 1fr}.nav{display:none}.search{width:160px}.modal .mbody{grid-template-columns:1fr}}
@media (max-width:560px){.wrap{padding:14px 16px 40px}.tiles{grid-template-columns:1fr}.search{display:none}}
</style>
</head>
<body>
<div class="blob a"></div><div class="blob b"></div><div class="blob c"></div><canvas id="fx"></canvas>
<div class="wrap">
  <header class="top in">
    <div class="brand"><div class="logo" id="miniLogo"></div><div><b id="brandName">Callum Games</b><small id="brandSub">Game launcher</small></div></div>
    <nav class="nav" id="nav">
      <button data-f="all" class="on">All games</button><button data-f="recent">Recent</button><button data-f="fav">Favourites</button>
    </nav>
    <div class="spacer"></div>
    <label class="search"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="q" placeholder="Search games"><kbd>/</kbd></label>
    <button class="btn" id="addBtn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>Add a game</button>
    <button class="btn icon" id="setBtn" title="Hub settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg></button>
  </header>

  <section class="hero">
    <div class="card intro in" style="animation-delay:.05s">
      <div class="mark"><div class="logo" id="bigLogo"></div><div><h1 id="heroTitle">Callum Games</h1><div class="tag" id="heroTag">Every game, one place.</div></div></div>
      <p id="heroText">Pick a game and press <b>Play</b>. The hub keeps your favourites, remembers what you played last, and takes a picture of each game while you play for its card.</p>
      <div class="row"><button class="btn primary" id="heroPlay"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg><span>Play</span></button><button class="btn" id="heroPick">Browse games</button></div>
      <div class="made"><i></i>Made by Callum Holland</div>
    </div>
    <div class="card feat in" id="feat" style="animation-delay:.12s">
      <div class="shot" id="featShot"><div class="ph" id="featPh"></div>
        <div class="bar"><div class="t"><div class="k" id="featK">Featured</div><h2 id="featName">-</h2><div class="s" id="featSub"></div></div><button class="play" id="featPlay"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>Play</button></div>
      </div><div class="frame"></div>
    </div>
  </section>

  <div class="sec in" style="animation-delay:.18s"><h3 id="gridTitle">Your games</h3><span id="gridSub"></span><div class="right"><span id="folderNote" style="color:var(--faint);font-size:12.5px"></span></div></div>
  <section class="grid" id="grid"></section>

  <div class="sec in" style="animation-delay:.22s"><h3>Your stats</h3><span>What the hub has seen so far</span></div>
  <section class="tiles in" id="tiles" style="animation-delay:.26s"></section>

  <footer class="foot"><span id="verNote"></span><a href="#" id="openFolder">Open the games folder</a><a href="#" id="restoreHidden">Show hidden games</a><span class="spacer"></span><span>Close this window to close the hub. Games keep running.</span></footer>
</div>

<div class="gp" id="gp"><div class="bgart" id="gpBg"></div><div class="gwrap">
  <div class="gtop"><button class="back" id="gpBack"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M15 6l-6 6 6 6"/></svg>All games</button></div>
  <div id="gpBody"></div></div></div>
<div class="lightbox" id="lb"><img id="lbImg" alt=""></div>
<div class="menu" id="menu"></div>
<div class="scrim" id="scrim"><div class="modal" id="modal"></div></div>
<div class="toasts" id="toasts"></div>

<script>
const HUB = __HUB__;
const api = (p, body) => fetch(HUB.base + '/api/' + p, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)} : {}).then(r => r.json());
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ICONS = {
  cube: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 2.5 21 7v10l-9 4.5L3 17V7z"/><path d="M3 7l9 4.5L21 7M12 11.5V21.5"/></svg>',
  ball: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><circle cx="12" cy="12" r="9.5"/><path d="M12 7.5l4 3-1.5 4.7h-5L8 10.5z"/><path d="M12 2.5v5M16 10.5l5-1.5M14.5 15.2l3 4.3M9.5 15.2l-3 4.3M8 10.5 3 9"/></svg>',
  grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/><path d="M4.5 4.5 7.5 7.5M7.5 4.5 4.5 7.5"/><circle cx="18" cy="18" r="1.6"/></svg>',
  pad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9h12a4 4 0 0 1 4 4v3a3 3 0 0 1-5.4 1.8L15 16H9l-1.6 1.8A3 3 0 0 1 2 16v-3a4 4 0 0 1 4-4z"/><path d="M8 12v3M6.5 13.5h3M16 12h.01M18.5 14h.01"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  star: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="m12 2.8 2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.7l-5.9 3.1 1.2-6.5L2.5 9.7l6.6-.9z"/></svg>',
  dots: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  cam: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  lib: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="3" y="4" width="7" height="16" rx="1.5"/><rect x="12" y="4" width="4" height="16" rx="1"/><path d="m17.5 5 4 1-3.4 14-4-1z"/></svg>',
  fire: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 22c4.4 0 7-2.8 7-6.6 0-3-1.7-5.2-3.4-7.1-.3 1.6-1.1 2.7-2.1 3.2.3-3.3-1-6.3-3.5-8.5.1 3.1-1.3 4.6-2.9 6.4C5.7 11 5 12.8 5 15.4 5 19.2 7.6 22 12 22z"/></svg>',
  globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19M12 2.5c3 3.2 3 16.8 0 19M12 2.5c-3 3.2-3 16.8 0 19"/></svg>',
  hub: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.6v8.8L12 21l-8-4.6V7.6z"/><path d="M12 12l8-4.6M12 12v9M12 12 4 7.4"/></svg>',
};
const hex2rgb = h => { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(','); };
const fmtDur = s => { s = Math.round(s); if (s < 60) return s + 's'; const m = Math.round(s / 60); if (m < 60) return m + ' min'; const h = Math.floor(m / 60); return h + 'h ' + (m % 60) + 'm'; };
const ago = t => { if (!t) return 'never'; const d = Date.now() / 1000 - t; if (d < 60) return 'just now'; if (d < 3600) return Math.round(d / 60) + ' min ago'; if (d < 86400) return Math.round(d / 3600) + ' h ago'; if (d < 86400 * 7) return Math.round(d / 86400) + ' days ago'; return new Date(t * 1000).toLocaleDateString(); };
const artUrl = g => g.art ? HUB.base + '/art/' + g.id + '.png?v=' + g.art : (g.gallery && g.gallery.length ? shotUrl(g, g.gallery[0]) : '');
const hasArt = g => !!(g.art || (g.gallery && g.gallery.length));

let S = null, filter = 'all', query = '', busy = {}, lastJSON = '';
const toast = (msg, bad) => { const t = document.createElement('div'); t.className = 'toast' + (bad ? ' bad' : ''); t.innerHTML = '<i></i>' + esc(msg); $('#toasts').appendChild(t); setTimeout(() => { t.style.transition = '.3s'; t.style.opacity = 0; setTimeout(() => t.remove(), 320); }, 3600); };

function featured(games) {
  if (!games.length) return null;
  const run = games.find(g => g.running); if (run) return run;
  const played = games.filter(g => g.stats.last).sort((a, b) => b.stats.last - a.stats.last);
  return played[0] || games.find(g => g.id === 'blockcraft') || games[0];
}
function visible(games) {
  let v = games.slice();
  if (filter === 'recent') v = v.filter(g => g.stats.last).sort((a, b) => b.stats.last - a.stats.last);
  if (filter === 'fav') v = v.filter(g => g.fav);
  if (query) v = v.filter(g => (g.name + ' ' + g.tagline + ' ' + g.chips.join(' ')).toLowerCase().includes(query));
  return v;
}
function render() {
  if (!S) return;
  document.documentElement.style.setProperty('--accent', S.accent);
  document.documentElement.style.setProperty('--accent-rgb', hex2rgb(S.accent));
  document.title = S.title;
  $('#brandName').textContent = S.title; $('#heroTitle').textContent = S.title; $('#heroTag').textContent = S.tagline || 'Every game, one place.';
  $('#brandSub').textContent = S.games.length + (S.games.length === 1 ? ' game' : ' games');
  $('#miniLogo').innerHTML = ICONS.hub; $('#bigLogo').innerHTML = ICONS.hub;
  $('#verNote').textContent = 'Callum Games ' + S.version + ' · Python ' + S.python;
  $('#folderNote').textContent = S.folder;
  // featured
  const f = featured(S.games);
  const feat = $('#feat');
  if (f) {
    feat.style.setProperty('--c', f.color); feat.dataset.id = f.id;
    $('#featShot').style.backgroundImage = hasArt(f) ? 'url("' + artUrl(f) + '")' : 'none';
    $('#featPh').innerHTML = hasArt(f) ? '' : ICONS[f.icon] || ICONS.pad;
    $('#featK').textContent = f.running ? 'Running now' : (f.stats.last ? 'Last played · ' + ago(f.stats.last) : 'Featured');
    $('#featName').textContent = f.name; $('#featName').style.color = f.color; $('#featSub').textContent = f.tagline;
    $('#featPlay').style.setProperty('--c', f.color); setPlayBtn($('#featPlay'), f);
    $('#heroPlay').querySelector('span').textContent = (f.running ? 'Back to ' : 'Play ') + f.name;
  }
  // grid
  const vis = visible(S.games);
  $('#gridTitle').textContent = filter === 'recent' ? 'Recently played' : filter === 'fav' ? 'Favourites' : 'Your games';
  $('#gridSub').textContent = vis.length ? vis.length + (vis.length === 1 ? ' game' : ' games') : '';
  const grid = $('#grid');
  if (!vis.length) {
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1">' + (S.games.length ? 'Nothing matches.' : 'No games found in ' + esc(S.folder) + '. Put your game files there or use <b>Add a game</b>.') + '</div>';
  } else {
    grid.innerHTML = vis.map((g, i) => `
      <article class="card game in" tabindex="0" data-id="${g.id}" style="--c:${g.color};animation-delay:${.05 + i * .06}s">
        <div class="art" style="${hasArt(g) ? `background-image:url('${artUrl(g)}')` : ''}">
          ${hasArt(g) ? '' : '<div class="ph">' + (ICONS[g.icon] || ICONS.pad) + '</div>'}
          <div class="badges">${g.running ? '<span class="badge run"><i></i>Running</span>' : ''}${g.copies > 1 ? '<span class="badge">' + g.copies + ' copies</span>' : ''}${g.fav ? '<span class="badge fav">' + ICONS.star.replace('<svg', '<svg width="11" height="11"') + ' Favourite</span>' : ''}</div>
        </div>
        <div class="body">
          <h4><span class="ico">${ICONS[g.icon] || ICONS.pad}</span>${esc(g.name)}</h4>
          <div class="tl">${esc(g.tagline)}</div>
          ${g.desc ? '<div class="d">' + esc(g.desc) + '</div>' : ''}
          <div class="chips">${g.chips.map(c => '<span class="chip">' + esc(c) + '</span>').join('')}</div>
          <div class="foot"><div class="meta">${g.running ? 'Running for ' + fmtDur(S.now - g.since) : (g.stats.plays ? fmtDur(g.stats.seconds) + ' played · ' + ago(g.stats.last) : 'Not played yet')}</div>
            <button class="play" data-play="${g.id}"></button><button class="more" data-menu="${g.id}" title="More">${ICONS.dots}</button></div>
        </div>
      </article>`).join('');
    grid.querySelectorAll('[data-play]').forEach(b => setPlayBtn(b, S.games.find(g => g.id === b.dataset.play)));
  }
  // tiles
  const st = S.games.map(g => g.stats);
  const total = st.reduce((a, s) => a + s.seconds, 0);
  const most = S.games.slice().sort((a, b) => b.stats.seconds - a.stats.seconds)[0];
  const last = S.games.filter(g => g.stats.last).sort((a, b) => b.stats.last - a.stats.last)[0];
  const running = S.games.filter(g => g.running);
  $('#tiles').innerHTML = [
    ['--pink', ICONS.lib, 'Library', S.games.length + (S.games.length === 1 ? ' game' : ' games'), S.games.filter(g => g.source === 'added').length ? S.games.filter(g => g.source === 'added').length + ' added by you, the rest found in the hub folder.' : 'All found in the hub folder. Drop a new game file in and it shows up here.'],
    ['--orange', ICONS.clock, 'Time played', fmtDur(total), total ? st.reduce((a, s) => a + s.plays, 0) + ' sessions counted since you started using the hub.' : 'Press Play on something and the clock starts.'],
    ['--violet', ICONS.fire, 'Most played', most && most.stats.seconds ? most.name : '-', most && most.stats.seconds ? fmtDur(most.stats.seconds) + ' over ' + most.stats.plays + (most.stats.plays === 1 ? ' session.' : ' sessions.') : 'Nothing yet. Blockcraft is a good place to start.'],
    ['--green', ICONS.play, running.length ? 'Running now' : 'Last session', running.length ? running.map(g => g.name).join(', ') : (last ? last.name : '-'), running.length ? 'Started ' + ago(running[0].since) + '. Close the game to stop the clock.' : (last ? ago(last.stats.last) + '. The hub keeps a picture of the window for the card.' : 'Your last game will show here.')],
  ].map(([c, ic, h, v, p]) => `<div class="card tile" style="--c:var(${c})"><div class="ic">${ic}</div><div class="v">${esc(v)}</div><h5>${esc(h)}</h5><p>${esc(p)}</p></div>`).join('');
  if (gpId) renderGame();
}
function setPlayBtn(b, g) {
  if (!g) return;
  b.style.setProperty('--c', g.color);
  if (busy[g.id] && !g.running) { b.className = 'play busy'; b.innerHTML = '<span class="spin"></span>Starting'; }
  else if (g.running) { b.className = 'play running'; b.innerHTML = ICONS.play + 'Open'; }
  else { b.className = 'play'; b.innerHTML = ICONS.play + 'Play'; }
}
async function play(id) {
  const g = S.games.find(x => x.id === id); if (!g) return;
  if (!g.running) { busy[id] = Date.now(); render(); }
  const r = await api('play', {id});
  if (!r.ok) { delete busy[id]; toast(r.error || 'Could not start it.', true); render(); return; }
  if (r.already) toast(g.name + ' is already open - brought it to the front.');
  else toast('Starting ' + g.name + '...');
  setTimeout(refresh, 600);
}
async function refresh() {
  try {
    const s = await api('state');
    for (const g of s.games) if (g.running) delete busy[g.id];
    for (const id in busy) if (Date.now() - busy[id] > 15000) delete busy[id];
    for (const e of s.events) {
      const g = s.games.find(x => x.id === e.id) || {name: 'A game'};
      if (e.t === 'ended') toast(g.name + (e.code ? ' crashed (code ' + e.code + ') after ' : ' closed · ') + fmtDur(e.seconds) + (e.code ? ' - see its log (... menu)' : ' played'), !!e.code);
    }
    S = s;
    const j = JSON.stringify([s.games, s.title, s.tagline, s.accent, filter, query, Object.keys(busy)]);
    if (j !== lastJSON) { lastJSON = j; render(); }
  } catch (e) { /* the hub is closing */ }
}
// menu
let menuFor = null;
function openMenu(id, x, y) {
  const g = S.games.find(g => g.id === id); if (!g) return; menuFor = id;
  const m = $('#menu');
  m.innerHTML = `<button data-a="details">${ICONS.info}Details</button><button data-a="fav">${ICONS.star}${g.fav ? 'Remove from favourites' : 'Add to favourites'}</button>
    <button data-a="folder">${ICONS.folder}Show the file</button><button data-a="shot">${ICONS.cam}Take a new card picture</button><button data-a="log">${ICONS.info}Open its last log</button><hr>
    ${g.running ? `<button data-a="stop" class="danger">${ICONS.stop}Close the game</button>` : ''}<button data-a="remove" class="danger">${ICONS.x}${g.source === 'added' ? 'Remove from hub' : 'Hide from hub'}</button>`;
  m.classList.add('open');
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, innerWidth - r.width - 12) + 'px'; m.style.top = Math.min(y, innerHeight - r.height - 12) + 'px';
}
const closeMenu = () => $('#menu').classList.remove('open');
async function menuAction(a) {
  const id = menuFor, g = S.games.find(g => g.id === id); closeMenu(); if (!g) return;
  if (a === 'details') openGame(id);
  else if (a === 'fav') { await api('fav', {id}); refresh(); }
  else if (a === 'folder') api('folder', {id});
  else if (a === 'log') { const r = await api('log', {id}); if (!r.ok) toast(r.error, true); }
  else if (a === 'shot') { const r = await api('shot', {id}); toast(r.ok ? 'New picture saved for ' + g.name + '.' : r.error, !r.ok); refresh(); }
  else if (a === 'stop') { if (confirm('Close ' + g.name + ' now? Unsaved progress may be lost.')) { await api('stop', {id}); toast('Asked ' + g.name + ' to close.'); setTimeout(refresh, 1200); } }
  else if (a === 'remove') { if (confirm((g.source === 'added' ? 'Remove ' : 'Hide ') + g.name + ' from the hub? (The game file is not touched.)')) { await api('remove', {id}); toast(g.name + ' removed. "Show hidden games" at the bottom brings it back.'); refresh(); } }
}
// details modal
function openDetails(id) {
  const g = S.games.find(g => g.id === id); if (!g) return;
  const m = $('#modal'); m.style.setProperty('--c', g.color);
  m.innerHTML = `<div class="mart" style="${g.art ? `background-image:url('${artUrl(g)}')` : ''}">${g.art ? '' : '<div class="ph">' + (ICONS[g.icon] || ICONS.pad) + '</div>'}
      <button class="x" data-close>${ICONS.x}</button>
      <div class="mhead"><div><h2>${esc(g.name)}</h2><div class="tl">${esc(g.tagline)}</div></div></div></div>
    <div class="mbody"><div>
      ${g.desc ? '<p>' + esc(g.desc) + '</p>' : '<p>No description - this card was made from the file name.</p>'}
      ${g.controls ? '<div class="k">Controls</div><p>' + esc(g.controls) + '</p>' : ''}
      <div class="k">File</div><code>${esc(g.path)}</code>${g.copies > 1 ? '<p style="margin-top:8px;font-size:13px">' + g.copies + ' copies of this game were found in the folder; the hub uses this one (the plain name, or the newest).</p>' : ''}
      <div class="acts"><button class="play" data-play="${g.id}"></button><button class="btn" data-a="folder">${ICONS.folder}Show the file</button><button class="btn" data-a="shot">${ICONS.cam}New card picture</button></div>
    </div><div>
      <div class="k">Stats</div><div class="stats">
        <div class="stat"><b>${esc(fmtDur(g.stats.seconds))}</b><span>time played</span></div><div class="stat"><b>${g.stats.plays}</b><span>sessions</span></div>
        <div class="stat"><b>${esc(ago(g.stats.last))}</b><span>last played</span></div><div class="stat"><b>${g.running ? 'Running' : 'Closed'}</b><span>right now</span></div></div>
      <div class="k">Tags</div><div class="chips">${g.chips.map(c => '<span class="chip">' + esc(c) + '</span>').join('')}</div>
    </div></div>`;
  setPlayBtn(m.querySelector('[data-play]'), g);
  m.querySelector('[data-close]').onclick = closeModal;
  m.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { menuFor = id; menuAction(b.dataset.a); });
  m.querySelector('[data-play]').onclick = () => play(id);
  $('#scrim').classList.add('open');
}
const closeModal = () => { if (window.__pvStop) { window.__pvStop(); window.__pvStop = null; } $('#scrim').classList.remove('open'); };
function openSettings() {
  const m = $('#modal'); m.style.removeProperty('--c');
  const sw = ['#a78bfa', '#f472b6', '#fb923c', '#4ade80', '#38bdf8', '#facc15', '#f87171', '#e879f9'];
  let priv = !!S.privacy, accent = S.accent;
  m.innerHTML = `<div class="set"><div style="display:flex;align-items:center;gap:10px"><h2 style="flex:1">Hub settings</h2><button class="x" data-close style="position:static">${ICONS.x}</button></div>
    <div class="priv${priv ? ' on' : ''}" id="pv">
      <div class="hd"><div class="shield"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M12 2.5 20 6v6c0 5-3.5 8.6-8 9.5C7.5 20.6 4 17 4 12V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg></div>
        <div><h3>Privacy overlay</h3><p>Your games, your screen. With this on, games started from the hub are hidden from screen recorders, screen sharing (Discord, Teams, Zoom) and screenshots - they see your message below instead (or a blank window), while you keep playing as normal.</p></div></div>
      <div class="screens" id="pvScr">
        <div class="scr"><div class="cap">What you see <i class="live" id="lvA"></i></div><div class="view lv"><img id="pvMe" alt=""><div class="ph" id="pvMeP">Live preview is off</div></div></div>
        <div class="scr"><div class="cap">What a recording or screen share sees <i class="live" id="lvB"></i></div><div class="view lv"><img id="pvThem" alt=""><div class="ph" id="pvThemP">Live preview is off</div></div></div>
      </div>
      <div class="pvbar"><button class="btn primary" id="pvGo">Start live preview</button>
        <div class="seg" id="pvMode"><button data-m="screen" class="on">My screen</button><button data-m="window">Test window</button></div>
        <span id="pvNote">Shows your real screen, live and sharp, until you stop it or close this window. A small protected test window opens so you can see the difference. Nothing is saved or sent anywhere.</span></div>
      <div style="height:14px"></div><label class="fl">Message people see instead of your game<input type="text" id="sMsg" maxlength="90" value="${esc(S.privacy_msg || '')}" placeholder="Leave empty for a blank window"></label>
      <div class="toggle" id="pvT"><div class="tr"><div class="kn"></div></div><b id="pvL">${priv ? 'Overlay is on' : 'Overlay is off'}</b></div>
    </div>
    <div class="grp"><label class="fl">Hub name<input type="text" id="sTitle" maxlength="40" value="${esc(S.title)}"></label>
      <label class="fl">Tagline<input type="text" id="sTag" maxlength="60" value="${esc(S.tagline)}"></label></div>
    <label class="fl">Accent colour<div class="swatches">${sw.map(c => `<div class="sw${c === S.accent ? ' on' : ''}" data-c="${c}" style="background:${c}"></div>`).join('')}</div></label>
    <p style="margin:0;color:var(--muted);font-size:13px">Games are found in <code style="display:inline;padding:2px 6px">${esc(S.folder)}</code>.</p>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn" data-close>Cancel</button><button class="btn primary" id="sSave">Save</button></div></div>`;
  m.querySelectorAll('.fl').forEach(l => l.style.cssText = 'display:flex;flex-direction:column;gap:6px;font-size:12.5px;color:var(--muted);font-weight:600');
  m.querySelectorAll('input[type=text]').forEach(i => i.style.cssText = 'height:40px;border-radius:10px;border:1px solid var(--line2);background:rgba(255,255,255,.04);color:var(--text);padding:0 12px;font:inherit;outline:0');
  // live preview: real pictures of a test window - as you see it, and as a screen capture gets it
  let live = false, pvTimer = null, pvRestart = null, pvLoading = {};
  const pvPaint = (id, url) => {
    if (pvLoading[id]) return; pvLoading[id] = 1;
    const im = new Image();
    im.onload = () => { $('#' + id).src = url; $('#' + id).classList.add('on'); $('#' + id + 'P').style.display = 'none'; pvLoading[id] = 0; };
    im.onerror = () => { $('#' + id).classList.remove('on'); $('#' + id + 'P').style.display = ''; $('#' + id + 'P').textContent = 'Waiting for the test window...'; pvLoading[id] = 0; };
    im.src = url;
  };
  let pvMode = 'screen';
  const pvQ = () => pvMode === 'screen' ? '&mode=screen' : '';
  const pvTick = () => { const t = Date.now(); pvPaint('pvMe', HUB.base + '/preview/me?t=' + t + pvQ()); pvPaint('pvThem', HUB.base + '/preview/them?t=' + t + pvQ()); };
  const pvLayout = () => { $('#pvScr').classList.toggle('big', pvMode === 'screen'); };
  m.querySelectorAll('#pvMode button').forEach(b => b.onclick = () => { pvMode = b.dataset.m; m.querySelectorAll('#pvMode button').forEach(x => x.classList.toggle('on', x === b)); pvLayout(); });
  pvLayout();
  const pvOpen = async () => { await api('test_start', {privacy: priv, msg: $('#sMsg').value}); };
  const pvStop = async () => {
    clearInterval(pvTimer); pvTimer = null; live = false; await api('test_stop');
    ['pvMe', 'pvThem'].forEach(i => { $('#' + i).classList.remove('on'); $('#' + i + 'P').style.display = ''; $('#' + i + 'P').textContent = 'Live preview is off'; });
    $('#pvGo').textContent = 'Start live preview'; $('#lvA').classList.remove('on'); $('#lvB').classList.remove('on');
  };
  $('#pvGo').onclick = async () => {
    if (live) { pvStop(); return; }
    live = true; $('#pvGo').textContent = 'Stop live preview'; $('#lvA').classList.add('on'); $('#lvB').classList.add('on');
    $('#pvMeP').textContent = $('#pvThemP').textContent = 'Starting the test window...';
    if (!location.hash.includes('liveonly')) await pvOpen();
    pvTimer = setInterval(pvTick, 160);
  };
  const pvAgain = () => { if (!live) return; clearTimeout(pvRestart); pvRestart = setTimeout(pvOpen, 700); };
  $('#sMsg').oninput = pvAgain;
  $('#pvT').onclick = () => { priv = !priv; $('#pv').classList.toggle('on', priv); $('#pvL').textContent = priv ? 'Overlay is on' : 'Overlay is off'; pvAgain(); };
  window.__pvStop = pvStop;
  if (location.hash.includes('live')) setTimeout(() => $('#pvGo').click(), 400);
  m.querySelectorAll('.sw').forEach(d => d.onclick = () => { accent = d.dataset.c; document.documentElement.style.setProperty('--accent', accent); document.documentElement.style.setProperty('--accent-rgb', hex2rgb(accent)); m.querySelectorAll('.sw').forEach(x => x.classList.toggle('on', x === d)); });
  m.querySelectorAll('[data-close]').forEach(b => b.onclick = () => { if (live) pvStop(); closeModal(); render(); });
  $('#sSave').onclick = async () => { if (live) await pvStop(); await api('settings', {title: $('#sTitle').value, tagline: $('#sTag').value, accent, privacy: priv, privacy_asked: true, privacy_msg: $('#sMsg').value}); closeModal(); toast(priv ? 'Saved - the privacy overlay is on.' : 'Saved.'); refresh(); };
  $('#scrim').classList.add('open');
}
// wiring
document.addEventListener('click', e => {
  if (gpId) return;
  const p = e.target.closest('[data-play]'); if (p) { e.stopPropagation(); openGame(p.dataset.play); return; }
  const mb = e.target.closest('[data-menu]'); if (mb) { e.stopPropagation(); const r = mb.getBoundingClientRect(); openMenu(mb.dataset.menu, r.right - 200, r.bottom + 6); return; }
  const ma = e.target.closest('#menu [data-a]'); if (ma) { menuAction(ma.dataset.a); return; }
  closeMenu();
  const card = e.target.closest('.game'); if (card) openGame(card.dataset.id);
});
document.addEventListener('contextmenu', e => { const card = e.target.closest('.game'); if (card) { e.preventDefault(); openMenu(card.dataset.id, e.clientX, e.clientY); } });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeMenu(); closeModal(); }
  if (e.key === '/' && document.activeElement !== $('#q')) { e.preventDefault(); $('#q').focus(); }
  if (e.key === 'Enter' && document.activeElement.classList.contains('game')) openGame(document.activeElement.dataset.id);
});
$('#scrim').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });
$('#nav').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; filter = b.dataset.f; $('#nav').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); render(); });
$('#q').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); render(); });
$('#addBtn').onclick = async () => { toast('Pick the game file in the window that opened.'); const r = await api('add'); if (r.ok) toast('Added ' + r.path.split(/[\\/]/).pop() + '.'); else if (!r.cancelled) toast(r.error, true); refresh(); };
$('#setBtn').onclick = openSettings;
$('#heroPlay').onclick = () => { const f = featured(S.games); if (f) openGame(f.id); };
$('#heroPick').onclick = () => $('#grid').scrollIntoView({behavior: 'smooth', block: 'start'});
$('#featPlay').onclick = e => { e.stopPropagation(); const id = $('#feat').dataset.id; if (id) openGame(id); };
$('#feat').onclick = e => { if (!e.target.closest('.play')) { const id = $('#feat').dataset.id; if (id) openGame(id); } };
$('#openFolder').onclick = e => { e.preventDefault(); api('folder', {id: ''}); };
$('#restoreHidden').onclick = async e => { e.preventDefault(); await api('unhide'); toast('Hidden games are back.'); refresh(); };
// ---- the game page: opens from every Play button; Launch starts the game ----
let gpId = null, gpIdx = 0, gpTimer = null, gpSig = '';
const shotUrl = (g, s) => HUB.base + '/shot/' + g.id + '/' + s.u.split('/').map(encodeURIComponent).join('/') + '?v=' + s.t;
function gpShots(g) {
  const list = (g.gallery || []).map(s => shotUrl(g, s));
  if (g.art) list.push(HUB.base + '/art/' + g.id + '.png?v=' + g.art);
  return list;
}
function openGame(id) {
  const g = S && S.games.find(x => x.id === id); if (!g) return;
  closeMenu(); closeModal();
  gpId = id; gpIdx = 0; gpSig = '';
  renderGame();
  $('#gp').classList.add('open'); $('#gp').scrollTop = 0;
  document.body.style.overflow = 'hidden';
  history.replaceState(null, '', '#game=' + id);
  clearInterval(gpTimer); gpTimer = setInterval(() => gpGo(1, true), 6000);
}
function closeGame() {
  gpId = null; clearInterval(gpTimer);
  $('#gp').classList.remove('open'); document.body.style.overflow = '';
  history.replaceState(null, '', location.pathname);
}
function gpGo(d, auto) {
  const g = S.games.find(x => x.id === gpId); if (!g) return;
  const n = gpShots(g).length; if (n < 2) return;
  gpIdx = (gpIdx + d + n) % n; gpShow();
  if (!auto) { clearInterval(gpTimer); gpTimer = setInterval(() => gpGo(1, true), 9000); }
}
function gpShow() {
  $('#gpViewer').querySelectorAll('img').forEach((im, i) => im.classList.toggle('on', i === gpIdx));
  $('#gpThumbs').querySelectorAll('[data-i]').forEach(b => b.classList.toggle('on', +b.dataset.i === gpIdx));
  const c = $('#gpViewer .count'); if (c) c.textContent = (gpIdx + 1) + ' / ' + $('#gpViewer').querySelectorAll('img').length;
  const on = $('#gpThumbs .on'); if (on) on.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'smooth'});
}
function controlRows(text) {
  return String(text || '').split('/').map(p => p.trim()).filter(Boolean).map(p => {
    const m = p.match(/^(.*?)\s+([a-z][a-z +\-]*)$/i);
    const parts = p.split(/\s+/);
    // "WASD move" -> key "WASD", action "move"; "Left click mine" -> "Left click", "mine"
    let key = p, act = '';
    const verbs = ['move','look','mine','place','inventory','players','hitboxes','throttle','steer','jump','boost','powerslide','cam','square','undo','restart','screen'];
    for (let i = parts.length - 1; i > 0; i--) { if (verbs.includes(parts[i].toLowerCase()) || i === parts.length - 1) { key = parts.slice(0, i).join(' '); act = parts.slice(i).join(' '); break; } }
    return `<div class="keyrow"><kbd>${esc(key)}</kbd><span>${esc(act)}</span></div>`;
  }).join('');
}
function renderGame() {
  const g = S && S.games.find(x => x.id === gpId); if (!g) { if (gpId) closeGame(); return; }
  const shots = gpShots(g);
  const sig = JSON.stringify([g.id, shots, g.running, g.stats, !!busy[g.id], g.fav]);
  if (sig === gpSig) return; gpSig = sig;
  if (gpIdx >= shots.length) gpIdx = 0;
  const p = $('#gp'); p.style.setProperty('--c', g.color);
  const ic = ICONS[g.icon] || ICONS.pad;
  $('#gpBg').style.backgroundImage = shots.length ? 'url("' + shots[0] + '")' : 'none';
  const feats = (g.features && g.features.length ? g.features : g.chips) || [];
  const launchHtml = busy[g.id] && !g.running ? '<span class="spin"></span>Starting...' : g.running ? ICONS.play + 'Switch to ' + esc(g.name) : ICONS.play + 'Launch ' + esc(g.name);
  $('#gpBody').innerHTML = `
    <div class="ghero">
      <div>
        <div class="viewer" id="gpViewer">
          ${shots.length ? shots.map((u, i) => `<img src="${u}" alt="" class="${i === gpIdx ? 'on' : ''}" data-zoom="${i}">`).join('')
            : `<div class="ph"><div>${ic}No screenshots yet.<br>Play for a minute and the hub snaps some for you,<br>or drop your own into the game's Screenshots folder.</div></div>`}
          ${shots.length > 1 ? `<button class="nav2 l" data-gp="-1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M15 6l-6 6 6 6"/></svg></button><button class="nav2 r" data-gp="1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M9 6l6 6-6 6"/></svg></button><span class="count">${gpIdx + 1} / ${shots.length}</span>` : ''}
        </div>
        <div class="thumbs" id="gpThumbs">${shots.map((u, i) => `<button data-i="${i}" class="${i === gpIdx ? 'on' : ''}" style="background-image:url('${u}')"></button>`).join('')}<button class="addshot" data-shots="1">+ Add your own</button></div>
      </div>
      <div class="side">
        <div class="gico">${ic}</div>
        <div><h1>${esc(g.name)}</h1></div>
        <div class="tl">${esc(g.tagline)}</div>
        ${g.running ? '<div class="live"><i></i>Running for ' + fmtDur(S.now - g.since) + '</div>' : ''}
        <button class="launch${g.running ? ' running' : ''}${busy[g.id] && !g.running ? ' busy' : ''}" data-launch="${g.id}">${launchHtml}</button>
        <div class="sub"><button class="btn" data-ga="fav">${ICONS.star}${g.fav ? 'Favourited' : 'Favourite'}</button><button class="btn" data-ga="shot" title="Take a picture of the running game">${ICONS.cam}Screenshot</button><button class="btn icon" data-ga="folder" title="Show the file">${ICONS.folder}</button></div>
        ${g.desc ? '<p class="d">' + esc(g.desc) + '</p>' : ''}
        <div class="chips">${g.chips.map(c => '<span class="chip">' + esc(c) + '</span>').join('')}</div>
      </div>
    </div>
    <div class="gsecs">
      <div class="card gbox"><h3><i></i>What's inside</h3><div class="feats">${feats.map((f, i) => `<div class="feat2"><b>${i + 1}</b><span>${esc(f)}</span></div>`).join('') || '<p class="d">Press Launch to find out.</p>'}</div></div>
      <div style="display:flex;flex-direction:column;gap:22px">
        ${g.controls ? `<div class="card gbox"><h3><i></i>Controls</h3><div class="keys">${controlRows(g.controls)}</div></div>` : ''}
        <div class="card gbox"><h3><i></i>Your stats</h3><div class="gstats">
          <div class="gstat"><b>${esc(fmtDur(g.stats.seconds))}</b><span>time played</span></div><div class="gstat"><b>${g.stats.plays}</b><span>sessions</span></div>
          <div class="gstat"><b>${esc(ago(g.stats.last))}</b><span>last played</span></div><div class="gstat"><b>${shots.length}</b><span>screenshots</span></div></div></div>
      </div>
    </div>`;
}
document.addEventListener('click', e => {
  if (!gpId) return;
  const t = e.target;
  if (t.closest('#gpBack')) { closeGame(); return; }
  const nv = t.closest('[data-gp]'); if (nv) { gpGo(+nv.dataset.gp); return; }
  const th = t.closest('#gpThumbs [data-i]'); if (th) { gpIdx = +th.dataset.i; gpShow(); return; }
  if (t.closest('[data-shots]')) { api('shots_folder', {id: gpId}); toast('Put PNG or JPG pictures in that folder - they show up here.'); return; }
  const z = t.closest('[data-zoom]'); if (z) { $('#lbImg').src = z.src; $('#lb').classList.add('open'); return; }
  const l = t.closest('[data-launch]'); if (l) { play(l.dataset.launch); return; }
  const ga = t.closest('[data-ga]'); if (ga) { menuFor = gpId; menuAction(ga.dataset.ga); return; }
}, true);
$('#lb').onclick = () => $('#lb').classList.remove('open');
document.addEventListener('keydown', e => {
  if (!gpId) return;
  if (e.key === 'Escape') { if ($('#lb').classList.contains('open')) $('#lb').classList.remove('open'); else closeGame(); e.stopImmediatePropagation(); }
  if (e.key === 'ArrowRight') gpGo(1); if (e.key === 'ArrowLeft') gpGo(-1);
}, true);

// ---------- motion ----------
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
// floating sparks behind everything, drifting away from the mouse
(() => {
  const c = $('#fx'); if (!c || calm) return;
  const g = c.getContext('2d'); let W, H, ps = [], mx = -999, my = -999;
  const size = () => { W = c.width = innerWidth * devicePixelRatio; H = c.height = innerHeight * devicePixelRatio; };
  size(); addEventListener('resize', size);
  addEventListener('mousemove', e => { mx = e.clientX * devicePixelRatio; my = e.clientY * devicePixelRatio; });
  for (let i = 0; i < 70; i++) ps.push({x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .3, vy: -.15 - Math.random() * .35, r: 1 + Math.random() * 2.2, a: .2 + Math.random() * .5});
  (function step() {
    g.clearRect(0, 0, W, H);
    const col = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#a78bfa';
    for (const p of ps) {
      const dx = p.x - mx, dy = p.y - my, d2 = dx * dx + dy * dy;
      if (d2 < 22000) { p.vx += dx / 4000; p.vy += dy / 4000; }
      p.vx *= .985; p.vy = p.vy * .985 - .004; p.x += p.vx; p.y += p.vy;
      if (p.y < -10) { p.y = H + 10; p.x = Math.random() * W; p.vy = -.2; }
      if (p.x < -10) p.x = W + 10; if (p.x > W + 10) p.x = -10;
      g.globalAlpha = p.a; g.fillStyle = col; g.beginPath(); g.arc(p.x, p.y, p.r * devicePixelRatio, 0, 6.283); g.fill();
    }
    requestAnimationFrame(step);
  })();
})();
// cards tilt toward the mouse on springs, and wobble back when it leaves
const springs = new Map();
function springFor(el) {
  let s = springs.get(el);
  if (!s) { s = {rx: 0, ry: 0, vx: 0, vy: 0, tx: 0, ty: 0, lift: 0, vl: 0, tl: 0}; springs.set(el, s); }
  return s;
}
document.addEventListener('mousemove', e => {
  if (calm) return;
  const card = e.target.closest('.game'); if (!card) return;
  const r = card.getBoundingClientRect(), s = springFor(card);
  const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
  s.ty = (px - .5) * 16; s.tx = -(py - .5) * 12; s.tl = 1;
  card.style.setProperty('--mx', px * 100 + '%'); card.style.setProperty('--my', py * 100 + '%');
});
document.addEventListener('mouseout', e => {
  const card = e.target.closest && e.target.closest('.game');
  if (card && !card.contains(e.relatedTarget)) { const s = springFor(card); s.tx = s.ty = 0; s.tl = 0; }
});
(function springLoop() {
  for (const [el, s] of springs) {
    if (!el.isConnected) { springs.delete(el); continue; }
    s.vx = (s.vx + (s.tx - s.rx) * .09) * .78; s.vy = (s.vy + (s.ty - s.ry) * .09) * .78; s.vl = (s.vl + (s.tl - s.lift) * .1) * .75;
    s.rx += s.vx; s.ry += s.vy; s.lift += s.vl;
    el.style.transform = `perspective(900px) rotateX(${s.rx}deg) rotateY(${s.ry}deg) translateY(${-6 * s.lift}px) scale(${1 + .02 * s.lift})`;
  }
  requestAnimationFrame(springLoop);
})();
const addShine = () => document.querySelectorAll('.game:not([data-shine])').forEach(c => { c.dataset.shine = 1; const d = document.createElement('div'); d.className = 'shine'; c.appendChild(d); });
new MutationObserver(addShine).observe(document.body, {childList: true, subtree: true});
// every click jiggles what it hit, with a ripple
document.addEventListener('pointerdown', e => {
  const b = e.target.closest('.btn,.play,.launch,.nav button,.game,.tile,.sw,.toggle'); if (!b || calm) return;
  b.classList.remove('jelly'); void b.offsetWidth; if (!b.classList.contains('game')) b.classList.add('jelly');
  else { const s = springFor(b); s.vl -= .9; }
  if (getComputedStyle(b).position === 'static') b.style.position = 'relative';
  const r = b.getBoundingClientRect(), z = Math.max(r.width, r.height) / 2, rp = document.createElement('span');
  rp.className = 'ripple'; rp.style.width = rp.style.height = z + 'px';
  rp.style.left = (e.clientX - r.left - z / 2) + 'px'; rp.style.top = (e.clientY - r.top - z / 2) + 'px';
  b.style.overflow = b.style.overflow || 'hidden'; b.appendChild(rp); setTimeout(() => rp.remove(), 650);
}, true);
window.addEventListener('pagehide', () => { navigator.sendBeacon && navigator.sendBeacon(HUB.base + '/api/bye', '{}'); });
function askPrivacy() {
  if (!S || S.privacy_asked) return;
  const m = $('#modal'); m.style.removeProperty('--c');
  m.innerHTML = `<div class="form"><h2 style="margin:0;font-size:22px">Turn on the privacy overlay?</h2>
    <p style="margin:0;color:var(--muted);line-height:1.6;font-size:14.5px">With it on, games you start from here are hidden from screen recordings, screen sharing (Discord, Teams, Zoom) and screenshots - other people see a blank window, while you play as normal. You can change this any time in Hub settings.</p>
    <div style="display:flex;gap:10px;justify-content:flex-end"><button class="btn" id="pNo">Not now</button><button class="btn primary" id="pYes">Turn it on</button></div></div>`;
  const done = async on => { await api('settings', {privacy: on, privacy_asked: true}); closeModal(); toast(on ? 'Privacy overlay is on for games you start.' : 'OK - it is in Hub settings if you change your mind.'); refresh(); };
  $('#pYes').onclick = () => done(true); $('#pNo').onclick = () => done(false);
  $('#scrim').classList.add('open');
}
refresh().then(() => { if (location.hash.startsWith('#settings')) openSettings(); else askPrivacy(); const m = location.hash.match(/^#game=([A-Za-z0-9_]+)/); if (m) openGame(m[1]); }); setInterval(refresh, 2000);
</script>
</body>
</html>
'''


# ----------------------------------------------------------------------------
#  THE SERVER
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    hub = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8', cache=False):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public, max-age=86400' if cache else 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        """('page'|'api'|'art', rest) when the token matches, else None."""
        parts = self.path.split('?', 1)[0].split('/')
        if len(parts) < 2 or parts[1] != self.hub.token:
            return None
        rest = [unquote(p) for p in parts[2:] if p]
        if not rest:
            return ('page', '')
        if rest[0] == 'api' and len(rest) > 1:
            return ('api', rest[1])
        if rest[0] == 'art' and len(rest) > 1:
            return ('art', rest[1])
        if rest[0] == 'shot' and len(rest) == 4:
            return ('shot', rest[1:])
        if rest[0] == 'preview' and len(rest) == 2:
            return ('preview', rest[1])
        return None

    def do_GET(self):
        r = self._route()
        if r is None:
            return self._send(404, 'not found', 'text/plain')
        kind, what = r
        if kind == 'page':
            cfg = json.dumps({'base': '/' + self.hub.token, 'title': self.hub.settings.get('title', 'Zemi Hub')})
            return self._send(200, PAGE.replace('__HUB__', cfg), 'text/html; charset=utf-8')
        if kind == 'api' and what == 'state':
            return self._send(200, json.dumps(self.hub.state()))
        if kind == 'preview':
            if what not in ('me', 'them'):
                return self._send(404, 'no', 'text/plain')
            try:
                png = self.hub.preview_png(what, 'screen' if 'mode=screen' in self.path else 'window')
            except Exception:
                png = None
            if not png:
                return self._send(404, 'no', 'text/plain')
            return self._send(200, png, 'image/png')
        if kind == 'shot':
            gid, src, name = what
            if not re.match(r'^[A-Za-z0-9_]+$', gid) or src not in ('own', 'hub') or                     not re.match(r'^[A-Za-z0-9 _().-]+\.(png|jpe?g|gif|webp)$', name, re.I):
                return self._send(404, 'no', 'text/plain')
            p = os.path.join(SHOTS_DIR if src == 'own' else GALLERY_DIR, gid, name)
            if not os.path.isfile(p):
                return self._send(404, 'no', 'text/plain')
            ext = name.rsplit('.', 1)[1].lower()
            ctype = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp'}[ext]
            with open(p, 'rb') as f:
                return self._send(200, f.read(), ctype, cache=True)
        if kind == 'art':
            if not re.match(r'^[A-Za-z0-9_]+\.png$', what):
                return self._send(404, 'no', 'text/plain')
            p = os.path.join(ART_DIR, what)
            if not os.path.exists(p):
                return self._send(404, 'no', 'text/plain')
            with open(p, 'rb') as f:
                return self._send(200, f.read(), 'image/png', cache=True)
        return self._send(404, 'not found', 'text/plain')

    def do_POST(self):
        r = self._route()
        if r is None or r[0] != 'api':
            return self._send(404, 'not found', 'text/plain')
        n = int(self.headers.get('Content-Length') or 0)
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
        except Exception:
            body = {}
        what = r[1]
        gid = str(body.get('id', ''))[:40]
        hub = self.hub
        try:
            if what == 'play':
                out = hub.play(gid)
            elif what == 'stop':
                out = hub.stop(gid)
            elif what == 'fav':
                out = hub.toggle_fav(gid)
            elif what == 'folder':
                out = hub.open_folder(gid) if gid else (os.startfile(HUB_DIR) or {'ok': True})
            elif what == 'shot':
                out = hub.shot_now(gid)
            elif what == 'test_start':
                out = hub.test_start(bool(body.get('privacy')), str(body.get('msg', ''))[:90])
            elif what == 'test_stop':
                out = hub.test_stop()
            elif what == 'shots_folder':
                if re.match(r'^[A-Za-z0-9_]+$', gid):
                    d = os.path.join(SHOTS_DIR, gid)
                    os.makedirs(d, exist_ok=True)
                    os.startfile(d)
                out = {'ok': True}
            elif what == 'add':
                out = hub.add_game()
            elif what == 'remove':
                out = hub.remove_game(gid)
            elif what == 'unhide':
                out = hub.restore_hidden()
            elif what == 'settings':
                out = hub.set_settings(body)
            elif what == 'log':
                p = os.path.join(LOG_DIR, re.sub(r'[^A-Za-z0-9_]', '', gid) + '.log')
                if os.path.exists(p):
                    os.startfile(p)
                out = {'ok': os.path.exists(p), 'error': None if os.path.exists(p) else 'No log yet - play it once first.'}
            elif what == 'bye':
                hub.bye_t = time.time()
                out = {'ok': True}
            else:
                out = {'ok': False, 'error': 'unknown call'}
        except Exception as e:
            traceback.print_exc()
            out = {'ok': False, 'error': str(e)}
        self._send(200, json.dumps(out or {'ok': True}))


# ----------------------------------------------------------------------------
#  THE WINDOW (a browser in app mode) AND MAIN
# ----------------------------------------------------------------------------
def find_browser():
    pf, pf86, local = (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                       os.environ.get('LOCALAPPDATA', ''))
    for p in (os.path.join(pf86, r'Microsoft\Edge\Application\msedge.exe'), os.path.join(pf, r'Microsoft\Edge\Application\msedge.exe'),
              os.path.join(pf, r'Google\Chrome\Application\chrome.exe'), os.path.join(pf86, r'Google\Chrome\Application\chrome.exe'),
              os.path.join(local, r'Google\Chrome\Application\chrome.exe'),
              os.path.join(pf, r'BraveSoftware\Brave-Browser\Application\brave.exe')):
        if os.path.exists(p):
            return p
    return None


def open_window(url):
    """The hub's window: Edge/Chrome in app mode with its own little profile (so it never touches yours).
    Returns the browser process, or None when we had to fall back to the default browser."""
    exe = find_browser()
    if exe:
        prof = os.path.join(DATA_DIR, 'window')
        os.makedirs(prof, exist_ok=True)
        try:
            u32.SetProcessDPIAware()
            sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
        except Exception:
            sw, sh = 1600, 900
        w, h = min(1240, sw - 80), min(820, sh - 100)
        args = [exe, '--app=' + url, '--user-data-dir=' + prof, '--window-size=%d,%d' % (w, h),
                '--window-position=%d,%d' % ((sw - w) // 2, max(0, (sh - h) // 2 - 20)),
                '--no-first-run', '--no-default-browser-check', '--disable-features=Translate,msEdgeSidebar',
                '--disable-background-networking', '--disable-sync', '--disable-extensions']
        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    import webbrowser
    webbrowser.open(url)
    return None


def existing_hub():
    """Is a hub already running?  Then just open another window on it."""
    try:
        with open(LOCK_FILE, encoding='utf-8') as f:
            d = json.load(f)
        s = socket.create_connection(('127.0.0.1', int(d['port'])), timeout=0.6)
        s.close()
        return d['url']
    except Exception:
        return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    url = existing_hub()
    if url:
        p = open_window(url)
        if p:
            p.wait()
        return
    hub = Hub()
    Handler.hub = hub
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    srv.daemon_threads = True
    port = srv.server_address[1]
    url = 'http://127.0.0.1:%d/%s/' % (port, hub.token)
    with open(LOCK_FILE, 'w', encoding='utf-8') as f:
        json.dump({'port': port, 'url': url, 'pid': os.getpid()}, f)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if '--no-window' in sys.argv:                           # (for testing: just the server; the page's own browser)
        print(url, flush=True)
        win = None
    else:
        win = open_window(url)
    hub.bye_t = None
    t_open = time.time()
    try:
        while True:
            time.sleep(0.5)
            hub.tick()
            now = time.time()
            if win is not None and win.poll() is not None:
                break                                   # the window was closed
            if win is None and '--no-window' not in sys.argv and now - hub.last_poll > 20 and now - t_open > 30:
                break                                   # (default-browser fallback: the page stopped talking)
            if hub.bye_t and now - hub.bye_t > 4 and now - hub.last_poll > 3:
                break                                   # the page said goodbye and nothing re-opened it
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass
        srv.shutdown()


if __name__ == '__main__':
    main()
