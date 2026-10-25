# SPDX-License-Identifier: GPL-2.0-or-later
"""Linux and Steam Deck counterparts of the launcher's Windows calls (this fork's additions).

Kept apart from uncharted_launcher.py so that changes from the Windows project merge cleanly:
the launcher only calls into this module where it would otherwise call a Windows API.
"""
import ctypes
import ctypes.util
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace
import time

import uncharted_logs

APP_ID = 'uncharted-linux'

# The packaged Python and OpenSSL come from Debian and look for certificates in /usr/lib/ssl,
# which Fedora and others do not have: every HTTPS request (update check) failed there. Point
# them, and the game (online play), at the system's bundle.
if not os.environ.get('SSL_CERT_FILE'):
    for _bundle in ('/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt',
                    '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem', '/etc/ssl/cert.pem',
                    '/etc/ssl/ca-bundle.pem'):
        if os.path.isfile(_bundle):
            os.environ['SSL_CERT_FILE'] = _bundle
            break
TITLE = 'Uncharted: The Nathan Drake Collection'


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'uncharted-launcher'


def steam_deck():
    """SteamOS (the Steam Deck and other SteamOS devices)."""
    try:
        return 'ID=steamos' in Path('/etc/os-release').read_text()
    except OSError:
        return False


def clean_env():
    """The environment for programs outside this one: a frozen launcher (PyInstaller) points
    LD_LIBRARY_PATH at its own libraries, which xdg-open or Steam must not get."""
    env = dict(os.environ)
    original = env.pop('LD_LIBRARY_PATH_ORIG', None)
    if getattr(sys, 'frozen', False):
        env.pop('LD_LIBRARY_PATH', None)
        if original:
            env['LD_LIBRARY_PATH'] = original
    return env


def open_path(target):
    """A folder or URL in the desktop's default program."""
    subprocess.Popen(['xdg-open', str(target)], env=clean_env(), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def add_font(path):
    """Makes a bundled TTF available to Tk (fontconfig, this process only); before Tk() starts."""
    try:
        library = ctypes.CDLL(ctypes.util.find_library('fontconfig') or 'libfontconfig.so.1')
        library.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        library.FcConfigAppFontAddFile(None, str(path).encode())
    except (OSError, AttributeError):
        pass


def set_icon(root, tk):
    """The window icon from launcher/uncharted.png (Tk on X11/Wayland does not read .ico)."""
    for folder in (Path(getattr(sys, '_MEIPASS', '')), Path(__file__).resolve().parent):
        png = folder / 'uncharted.png'
        if png.is_file():
            try:
                root._icon = tk.PhotoImage(file=str(png))
                root.iconphoto(True, root._icon)
            except tk.TclError:
                pass
            return


class GameJob:
    """run.py and everything it starts in one process group, so Stop ends all of them."""

    popen_options = {'start_new_session': True}

    def __init__(self, process):
        self.pgid = process.pid

    def terminate(self):
        if self.pgid:
            try:
                os.killpg(self.pgid, signal.SIGTERM)
            except OSError:
                pass

    def close(self):
        self.pgid = None


def wait_for(pid, seconds=60):
    for _ in range(int(seconds * 10)):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)


# ---- Steam ----------------------------------------------------------------------------------

def steam_folder():
    """Steam's data folder (native, the Steam Deck, or the Flatpak), or None."""
    home = Path.home()
    for candidate in (home / '.steam' / 'steam', home / '.local' / 'share' / 'Steam',
                      home / '.var' / 'app' / 'com.valvesoftware.Steam' / '.local' / 'share' / 'Steam'):
        if (candidate / 'userdata').is_dir():
            return candidate.resolve()
    return None


def steam_running():
    result = subprocess.run(['pgrep', '-x', 'steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def steam_shutdown(steam):
    if 'com.valvesoftware.Steam' in str(steam):
        command = ['flatpak', 'run', 'com.valvesoftware.Steam', '-shutdown']
    elif shutil.which('steam'):
        command = [shutil.which('steam'), '-shutdown']
    else:
        return
    subprocess.Popen(command, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def launch_target(launcher_file):
    """(program, launch options) that start the game with the saved settings: the packaged
    Uncharted binary, else this Python with the launcher script."""
    if os.environ.get('APPIMAGE'):
        return Path(os.environ['APPIMAGE']), '--play'
    if getattr(sys, 'frozen', False):
        return Path(sys.executable), '--play'
    return Path(sys.executable), f'"{Path(launcher_file).resolve()}" --play'


# ---- Desktop entry --------------------------------------------------------------------------

def desktop_entry(launcher_file, port_dir):
    """Uncharted in the application menu and on the desktop (a .desktop file)."""
    if os.environ.get('APPIMAGE'):
        command = f'"{os.environ["APPIMAGE"]}"'
    elif getattr(sys, 'frozen', False):
        command = f'"{sys.executable}"'
    else:
        command = f'"{sys.executable}" "{Path(launcher_file).resolve()}"'
    icon = Path(port_dir) / 'launcher' / 'uncharted.png'
    if not icon.is_file():
        icon = Path(getattr(sys, '_MEIPASS', port_dir)) / 'uncharted.png'
    text = ('[Desktop Entry]\nType=Application\nName=Uncharted\n'
            f'Comment={TITLE} for Linux\nExec={command}\nPath={port_dir}\nIcon={icon}\n'
            'Terminal=false\nCategories=Game;\n' + report_action(command))
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    written = []
    for folder in (data / 'applications', desktop_folder()):
        if folder and folder.is_dir() or folder == data / 'applications':
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{APP_ID}.desktop'
            path.write_text(text, encoding='utf-8')
            path.chmod(0o755)
            written.append(path)
    return written


def report_action(command):
    """The menu entry's right-click Create bug report (works when the window does not)."""
    return f'Actions=report;\n\n[Desktop Action report]\nName=Create bug report\nExec={command} --report\n'


def add_report_action():
    """Menu and desktop entries made before Create bug report existed (install.sh, Desktop
    shortcut) get it, when they start this AppImage."""
    appimage = os.environ.get('APPIMAGE')
    if not appimage:
        return
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    for folder in (data / 'applications', desktop_folder()):
        path = folder / f'{APP_ID}.desktop' if folder else None
        try:
            text = path.read_text(encoding='utf-8') if path and path.is_file() else ''
        except OSError:
            continue
        exec_line = next((line for line in text.splitlines() if line.startswith('Exec=')), '')
        if appimage not in exec_line or '[Desktop Action report]' in text:
            continue
        try:
            path.write_text(text.rstrip('\n') + '\n' + report_action(exec_line[len('Exec='):]), encoding='utf-8')
        except OSError:
            pass


def report_without_window(settings, data_dir, port_dir, version):
    """--report: the bug report zip in Downloads, its folder opened, without Tk."""
    saves = Path(settings.get('user_dir') or Path(data_dir) / 'user')
    try:
        path = uncharted_logs.create_report(data_dir, saves, settings, port_dir, version, crash_signature)
    except OSError as error:
        print(f'Could not create the bug report: {error}', file=sys.stderr)
        uncharted_logs.tell('Uncharted', f'Could not create the bug report: {error}')
        return 1
    print(f'Bug report: {path}')
    uncharted_logs.tell('Uncharted', f'Bug report saved as {path.name} in {path.parent}. '
                                     'Send this file with your bug report.')
    try:
        open_path(path.parent)
    except OSError:  # no xdg-open: the path was printed and shown
        pass
    return 0


def log_window(root):
    """The window's size and scaling in the launcher's log, then a heartbeat for the watchdog."""
    try:
        uncharted_logs.note(f'Window built: screen {root.winfo_screenwidth()}x{root.winfo_screenheight()}, '
                            f'Tk {root.tk.call("info", "patchlevel")}, {root.winfo_fpixels("1i"):.0f} DPI, '
                            f'font scale {font_scale(root):.2f}, windowing system {root.tk.call("tk", "windowingsystem")}')

        def shown(event):
            if event.widget is root and not getattr(root, 'shown', False):
                root.shown = True
                uncharted_logs.note('Window shown')
        root.bind('<Map>', shown, add='+')
    except Exception as error:  # only the log line
        uncharted_logs.note(f'Window details unavailable: {error}')
    uncharted_logs.heartbeat(root)


def desktop_folder():
    try:
        result = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, env=clean_env())
        folder = Path(result.stdout.strip())
        if result.returncode == 0 and folder != Path.home() and folder.is_dir():
            return folder
    except OSError:
        pass
    folder = Path.home() / 'Desktop'
    return folder if folder.is_dir() else None


# ---- Updates --------------------------------------------------------------------------------

def install_appimage(url, target, progress=None):
    """Downloads the AppImage at `url` next to `target` and puts it in its place (a rename: the
    running AppImage keeps its own mounted copy until it closes)."""
    import urllib.request
    part = target.with_name(target.name + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'uncharted-linux-launcher'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(part, 'wb') as out:
            expected = int(response.headers.get('Content-Length') or 0)
            done, shown = 0, -1
            while chunk := response.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                percent = done * 100 // expected if expected else 0
                if progress and percent != shown:
                    shown = percent
                    progress(percent)
        size = part.stat().st_size
        with open(part, 'rb') as check:
            magic = check.read(4)
        if magic != b'\x7fELF' or size < (1 << 20) or (expected and size != expected):
            raise ValueError('the download is incomplete')
        part.chmod(0o755)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


# ---- The Linux launcher: a row per game with Play and Add to Steam ---------------------------

def flatpak_steam(steam):
    return 'com.valvesoftware.Steam' in str(steam)


def steam_command(steam, launcher_file, game):
    """(Exe, LaunchOptions) of the Steam shortcut that starts `game` (u1/u2/u3). Flatpak Steam runs
    in a sandbox and starts programs on the host through flatpak-spawn --host."""
    exe, options = launch_target(launcher_file)
    options = f'{options} {game}'
    if flatpak_steam(steam):
        return '/usr/bin/flatpak-spawn', f'--host "{exe}" {options}'
    return str(exe), options


REPO_URL = 'https://github.com/spacepepperoni/uncharted_Linux'


def icon_image(name, size, color, background):
    """launcher/icons/<name>.png (white on transparent: Simple Icons, CC0) in `color` on
    `background`, as a PIL image of size x size."""
    from PIL import Image
    folder = Path(getattr(sys, '_MEIPASS', '')) / 'icons'
    if not folder.is_dir():
        folder = Path(__file__).resolve().parent / 'icons'
    mask = Image.open(folder / f'{name}.png').convert('RGBA').getchannel('A').resize((size, size), Image.LANCZOS)

    def rgb(value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    image = Image.new('RGB', (size, size), rgb(background))
    image.paste(Image.new('RGB', (size, size), rgb(color)), (0, 0), mask)
    return image


def download_icon(size, color, background, glow=0.0, glow_color=None):
    """A download symbol (an arrow into a tray) as a PIL image; `glow` 0..1 adds a soft halo."""
    from PIL import Image, ImageDraw, ImageFilter

    def rgb(value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    n = size * 4
    image = Image.new('RGB', (n, n), rgb(background))
    if glow > 0:
        halo = Image.new('L', (n, n), 0)
        ImageDraw.Draw(halo).ellipse((n * 0.22, n * 0.22, n * 0.78, n * 0.78), fill=int(170 * glow))
        halo = halo.filter(ImageFilter.GaussianBlur(n * 0.09))
        image.paste(Image.new('RGB', (n, n), rgb(glow_color or color)), (0, 0), halo)
    draw = ImageDraw.Draw(image)
    w = max(2, int(n * 0.11))
    c = rgb(color)
    draw.line((n * 0.5, n * 0.12, n * 0.5, n * 0.62), fill=c, width=w)            # shaft
    draw.polygon([(n * 0.27, n * 0.44), (n * 0.73, n * 0.44), (n * 0.5, n * 0.7)], fill=c)  # head
    draw.line((n * 0.14, n * 0.66, n * 0.14, n * 0.86), fill=c, width=w)          # tray
    draw.line((n * 0.14, n * 0.86, n * 0.86, n * 0.86), fill=c, width=w)
    draw.line((n * 0.86, n * 0.86, n * 0.86, n * 0.66), fill=c, width=w)
    return image.resize((size, size), Image.LANCZOS)


def desktop_game_entry(launcher_file, key, name):
    """`name` (one game) in the application menu and on the desktop."""
    exe, options = launch_target(launcher_file)
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    icon = data / 'icons' / 'hicolor' / '256x256' / 'apps' / 'uncharted-linux.png'
    text = ('[Desktop Entry]\nType=Application\n'
            f'Name={name}\nExec="{exe}" {options} {key}\nIcon={icon if icon.is_file() else ""}\n'
            'Terminal=false\nCategories=Game;\n')
    written = []
    for folder in (data / 'applications', desktop_folder()):
        if folder is None:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{APP_ID}-{key}.desktop'
        path.write_text(text, encoding='utf-8')
        path.chmod(0o755)
        written.append(path)
    return written


# ---- Crash reports -----------------------------------------------------------------------------

CRASH_MARKERS = ('STOP:', 'Fault:', '*** ASSERTION', 'ASSERTION:', 'Device lost', 'GPU crash: the graphics')


def read_tail(path, size=1 << 20):
    """The last `size` bytes of a file as text. A run log can grow to gigabytes (a message every
    frame); read whole on the window's thread, it froze the launcher black at start."""
    with open(path, 'rb') as log:
        log.seek(0, os.SEEK_END)
        log.seek(max(0, log.tell() - size))
        return log.read().decode('utf-8', errors='replace')


def crash_signature(log_path):
    """The first line of a run log's last megabyte that says how the game stopped, or None (it
    ended normally); with that text."""
    try:
        text = read_tail(log_path)
    except OSError:
        return None, ''
    for line in text.splitlines():
        if line.startswith(CRASH_MARKERS):
            return line.strip(), text
    return None, text


def version_key(text):
    """A comparable form of this fork's versions: the upstream version padded to four parts,
    then the Linux build number ('0.4-linux.57' -> (0, 4, 0, 0, 57)). Joining all the digits, as
    the Windows launcher does, compared 0.4-linux.57 above 0.4.1-linux.60."""
    import re
    match = re.match(r'v?(\d+(?:\.\d+)*)(?:-[a-z]+\.(\d+))?', (text or '').strip())
    if not match:
        return (0,)
    upstream = [int(part) for part in match.group(1).split('.')][:4]
    return tuple(upstream + [0] * (4 - len(upstream))) + (int(match.group(2) or 0),)


def apply_defaults(ns):
    """Linux settings the Windows launcher does not have: Steam Deck mode (on by default on
    SteamOS) and a 30 FPS frame rate."""
    ns['APP_DEFAULTS'].setdefault('steam_deck', steam_deck())
    # No Fixes page: each fix stays automatic (run.py turns it on where it helps), whatever an
    # earlier version saved for it.
    for key, (title, hint, _choices) in ns['FIXES'].items():
        ns['FIXES'][key] = (title, hint, {})
    ns['version_tuple'] = version_key  # the launcher's update check compares with it
    for name in ('WINDOW_SIZES', 'ANTI_ALIASING'):
        ns[name][:] = [(value, text.replace("(the games' own)", '(Default)').replace("(the game's own)", '(Default)'))
                       for value, text in ns[name]]
    ns['FRAME_RATES'][:] = [(value, '60 FPS (Default)' if value == '60' else text) for value, text in ns['FRAME_RATES']]
    if not any(value == '30' for value, _text in ns['FRAME_RATES']):
        ns['FRAME_RATES'].insert(0, ('30', '30 FPS'))
    if not any(value == '1280x800' for value, _text in ns['WINDOW_SIZES']):
        ns['WINDOW_SIZES'].insert(1, ('1280x800', '1280 × 800 (Steam Deck)'))


def saves_for(game_dir):
    return str(Path(game_dir) / 'Saves') if game_dir else ''


def default_saves(settings, data_dir=None):
    """An empty saves folder means <game folder>/Saves."""
    if not settings.get('user_dir') and settings.get('game_dir'):
        settings['user_dir'] = saves_for(settings['game_dir'])


# Steam Deck mode shows its values in these settings while it is on (deck_environment enforces
# the locked ones at launch); turning it off restores what the player had.
DECK_SETTINGS = {'frame_rate': '30', 'window_size': '1280x800', 'present_mode': 'Fifo', 'fullscreen': True,
                 'anti_aliasing': 'off', 'frame_generation': 'off'}
DECK_LOCKED = ('window_size', 'present_mode', 'fullscreen')
DECK_FRAME_RATES = ('30', '60')  # 30 by default: the Deck does not hold 60 yet
# Choices the Deck's hardware cannot run (an RDNA 2 GPU, a 60 Hz screen): greyed out in Steam
# Deck mode, and replaced by these settings' first Deck-safe value at launch.
DECK_UNAVAILABLE = {'anti_aliasing': ('fsr4', 'fsr411', 'dlss'), 'frame_generation': ('dlss',),
                    'frame_gen_multiplier': ('3', '4')}
DECK_FALLBACK = {'anti_aliasing': 'off', 'frame_generation': 'off', 'frame_gen_multiplier': '2'}


# The texts under upstream's settings rows, by row title: replaced, or None for none.
ROW_HINTS = {'Frame rate': None,
             'Window size': 'Set it to the Resolution above for a sharp 1:1 picture',
             'Resolution': "Your screen's resolution. Drake's Fortune draws at most 2880 x 1620",
             'Upscaler': 'DLSS or FSR 4 for upscaling; FSR 1 only enlarges, TAA only smooths edges',
             'Quality': 'Native: anti-aliasing only (DLAA). Quality 1.5x, Balanced 1.7x, Performance 2x, '
                        'Ultra Performance 3x',
             'Sharpness': 'For every upscaler, FSR 1 included (AMD RCAS)', 'Sharpening': None,
             'Anti-aliasing': None,
             'Frame generation': None, 'Multiplier': None, 'Mouse sensitivity': None}


def unsaved_changes(saved, current):
    """The settings whose value in the launcher differs from the saved one."""
    return sorted(key for key in current if current[key] != saved.get(key))


def deck_frame_rate_30(saved):
    """Steam Deck mode's default became 30 FPS (it was 60, which the Deck does not hold yet): saved
    settings from an older launcher switch to 30 once, even when the game starts from Steam without
    the launcher window. 60 can be chosen again. Returns True when `saved` changed."""
    if not saved or saved.get('deck_30fps'):
        return False
    saved['deck_30fps'] = True
    if saved.get('steam_deck') and str(saved.get('frame_rate')) == '60':
        saved['frame_rate'] = '30'
    return True


def deck_allows(key, value):
    """The value can be chosen for this setting in Steam Deck mode."""
    if key == 'frame_rate':
        return value in DECK_FRAME_RATES
    return value not in DECK_UNAVAILABLE.get(key, ())


def deck_environment(settings, env):
    """Steam Deck mode: the Deck's screen and presentation, 30 or 60 FPS, and nothing its GPU
    cannot run. Applied before the player's own Environment entries, which can override any of it.
    The GPU readbacks choice was removed (Off made Uncharted 2's convoy unpassable, Precise hangs
    Uncharted 2 at startup), so a gpu_readbacks value saved by an older launcher is ignored."""
    if not settings.get('steam_deck'):
        return
    rate = str(settings.get('frame_rate') or '')
    env['BB_VBLANK_HZ'] = rate if rate in DECK_FRAME_RATES else DECK_SETTINGS['frame_rate']
    env['BB_WINDOW_SIZE'] = '1280x800'   # the Deck's screen: no 1080p output pass to scale down
    env['BB_RENDER_720P'] = '1'          # all three games render at 1280x720 (scripts/render_720p.py)
    env['BB_PRESENT_MODE'] = 'Fifo'      # gamescope paces FIFO best
    env['BB_FULLSCREEN'] = '1'
    env['BB_FRAME_STATS'] = '1'          # frame time breakdown in last_run.log (tuning the Deck)
    env['BB_DECK_PROMPTS'] = '1'         # Xbox button pictures with black and white A B X Y
    for key, name in (('anti_aliasing', 'BB_UPSCALER'), ('frame_generation', 'BB_FRAME_GEN'),
                      ('frame_gen_multiplier', 'BB_FRAME_GEN_MULTIPLIER')):
        if not deck_allows(key, str(settings.get(key) or '')):
            env[name] = DECK_FALLBACK[key]


def rotate_logs(folder, keep=5):
    """last_run.log -> last_run.1.log ... (the previous runs stay readable)."""
    folder = Path(folder)
    for n in range(keep - 1, 0, -1):
        older = folder / f'last_run.{n}.log'
        newer = folder / ('last_run.log' if n == 1 else f'last_run.{n - 1}.log')
        if newer.is_file():
            try:
                os.replace(newer, older)
            except OSError:
                pass


def plain_info_dialogs(root):
    """Tk's information dialogs ("You have the latest version" and the like) without their
    lightbulb icon: the icon's image is emptied once Tk's dialog code is loaded, as loading it
    creates the icon again."""
    try:
        root.tk.eval('auto_load ::tk::MessageBox; image create photo ::tk::icons::information')
    except Exception:  # another Tk: the dialogs keep their icon
        pass


def update_in_background(latest_release, version_tuple, version, settings):
    """Games started from Steam (Gaming Mode) never open the launcher: the update check runs
    beside the game and the new AppImage is swapped in for the next start. Returns the thread."""
    if not os.environ.get('APPIMAGE') or not settings.get('check_updates', True):
        return None

    def work():
        try:
            newest, url, _page, _notes = latest_release()
            if url and version_tuple(newest) > version_tuple(version):
                install_appimage(url, Path(os.environ['APPIMAGE']))
                print(f'Update: version {newest} installed for the next start')
        except (OSError, ValueError, KeyError):
            pass
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


def load_with_neighbours(path):
    """ctypes.CDLL of a bundled library whose dependencies sit beside it. Only the game process gets
    that folder on its library path, so a missing dependency is loaded from there first."""
    for _ in range(40):
        try:
            return ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
        except OSError as error:
            # PyInstaller rewraps the loader's message; the original is the cause.
            found = re.search(r'([^\s:/]+\.so[.\d]*): cannot open shared object', str(error.__cause__ or error))
            missing = found.group(1) if found else path.name
            beside = path.parent / missing
            if missing == path.name or not beside.exists():
                raise
            load_with_neighbours(beside)  # now loaded, the next attempt finds it by soname
    raise OSError(f'{path}: too many missing dependencies')


class Gamepads:
    """The controller through SDL3 (bundled with the game: bin/lib/libSDL3.so.0), for the update
    prompt shown before a game started from Steam. Steam's virtual gamepad is what a game launched
    in Gaming Mode sees. Silently absent when SDL3 cannot be loaded."""
    SOUTH, EAST, DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 0, 1, 11, 12, 13, 14

    def __init__(self, port_dir):
        self.sdl, self.pads, self.held, self.next_scan = None, [], set(), 0.0
        try:
            sdl = load_with_neighbours(Path(port_dir) / 'bin' / 'lib' / 'libSDL3.so.0')
            sdl.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            sdl.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1')
            sdl.SDL_Init.argtypes = [ctypes.c_uint32]
            sdl.SDL_Init.restype = ctypes.c_bool
            if not sdl.SDL_Init(0x00002000):  # SDL_INIT_GAMEPAD
                return
            sdl.SDL_GetGamepads.argtypes = [ctypes.POINTER(ctypes.c_int)]
            sdl.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
            sdl.SDL_OpenGamepad.argtypes = [ctypes.c_uint32]
            sdl.SDL_OpenGamepad.restype = ctypes.c_void_p
            sdl.SDL_GetGamepadButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
            sdl.SDL_GetGamepadButton.restype = ctypes.c_bool
            sdl.SDL_GetGamepadAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]
            sdl.SDL_GetGamepadAxis.restype = ctypes.c_int16
            sdl.SDL_free.argtypes = [ctypes.c_void_p]
            self.sdl = sdl
        except (OSError, AttributeError):
            self.sdl = None

    def scan(self):
        if not self.sdl or time.monotonic() < self.next_scan:
            return
        self.next_scan = time.monotonic() + 1.0
        count = ctypes.c_int(0)
        ids = self.sdl.SDL_GetGamepads(ctypes.byref(count))
        if ids and count.value and not self.pads:
            self.pads = [p for p in (self.sdl.SDL_OpenGamepad(ids[i]) for i in range(count.value)) if p]
        if ids:
            self.sdl.SDL_free(ids)

    def pressed(self):
        """Buttons newly pressed since the last call: 'left', 'right', 'ok', 'back'."""
        if not self.sdl:
            return []
        self.scan()
        self.sdl.SDL_UpdateGamepads()
        now = set()
        for pad in self.pads:
            get = self.sdl.SDL_GetGamepadButton
            x = self.sdl.SDL_GetGamepadAxis(pad, 0)  # left stick X
            if get(pad, self.DPAD_LEFT) or get(pad, self.DPAD_UP) or x < -20000:
                now.add('left')
            if get(pad, self.DPAD_RIGHT) or get(pad, self.DPAD_DOWN) or x > 20000:
                now.add('right')
            if get(pad, self.SOUTH):
                now.add('ok')
            if get(pad, self.EAST):
                now.add('back')
        new = now - self.held
        self.held = now
        return sorted(new)


# The short list the Gaming Mode update prompt shows, written in the release text as a comment,
# which GitHub does not display on the release page:
#   <!-- Update notes:
#   - Steam Deck performance improvements
#   -->
UPDATE_NOTES = re.compile(r'<!--\s*update notes:(.*?)-->', re.IGNORECASE | re.DOTALL)


def update_highlights(notes, most=6):
    """The release text's update notes as a list of lines (the leading - or * removed)."""
    found = UPDATE_NOTES.search(notes or '')
    if not found:
        return []
    lines = [line.strip().lstrip('-*').strip() for line in found.group(1).splitlines()]
    return [line[:70] for line in lines if line][:most]


def startup_update_prompt(settings, latest_release, version, port_dir):
    """Before a game started from Steam: if this fork has a newer release, a full-screen prompt
    (controller, touch, mouse or keyboard) asks Update or Cancel. Update downloads it with a progress
    bar and then the game closes, to be started again. Returns 'updated', 'declined', 'none' or
    'error' (no prompt could be shown)."""
    if not os.environ.get('APPIMAGE') or not settings.get('check_updates', True):
        return 'none'
    found = {}

    def check():
        try:
            found['release'] = latest_release()
        except Exception:  # offline, rate limited: just play
            pass
    worker = threading.Thread(target=check, daemon=True)
    worker.start()
    worker.join(4.0)
    release = found.get('release')
    if not release or not release[1] or version_key(release[0]) <= version_key(version):
        return 'none'
    newest, url, _page, notes = release
    try:
        import tkinter as tk
        import tkinter.font  # noqa: F401 (tk.font.families)
        root = tk.Tk()
    except Exception:
        return 'error'
    import queue
    root.title('Uncharted update')
    root.configure(bg='#08090a', cursor='')
    root.geometry(f'{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0')
    root.attributes('-fullscreen', True)
    gold, text, muted, card = '#e7c36a', '#f3efe6', '#8e8a82', '#17181b'
    big = ('Fira Code', 26, 'bold') if 'Fira Code' in tk.font.families(root) else ('DejaVu Sans', 26, 'bold')
    mid = (big[0], 15)
    box = tk.Frame(root, bg='#08090a')
    box.place(relx=0.5, rely=0.5, anchor='center')
    title = tk.Label(box, text='Update available', bg='#08090a', fg=gold, font=big)
    title.pack(pady=(0, 18))
    message = tk.Label(box, text=f'Version {newest} is ready to install.\nYou have version {version}.',
                       bg='#08090a', fg=text, font=mid, justify='center')
    message.pack(pady=(0, 34))
    highlights = update_highlights(notes)
    if highlights:
        points = tk.Frame(box, bg='#08090a')
        points.pack(pady=(0, 34))
        for point in highlights:
            row = tk.Frame(points, bg='#08090a')
            row.pack(anchor='w', pady=3)
            tk.Label(row, text='•', bg='#08090a', fg=gold, font=mid).pack(side='left', padx=(0, 12))
            tk.Label(row, text=point, bg='#08090a', fg=text, font=mid).pack(side='left')
    buttons = tk.Frame(box, bg='#08090a')
    buttons.pack()
    state = {'choice': None, 'selected': 0, 'progress': None}
    labels = []
    for i, name in enumerate(('Update', 'Cancel')):
        b = tk.Label(buttons, text=name, font=(big[0], 18, 'bold'), padx=46, pady=16, cursor='hand2')
        b.grid(row=0, column=i, padx=18)
        b.bind('<Button-1>', lambda _e, i=i: choose(i))
        labels.append(b)
    hint = tk.Label(box, text='A  select     B  cancel     ◀ ▶  move', bg='#08090a', fg=muted, font=(big[0], 11))
    hint.pack(pady=(28, 0))
    bar = tk.Canvas(box, width=560, height=22, bg=card, highlightthickness=0)
    pads = Gamepads(port_dir)
    events = queue.Queue()

    def paint():
        for i, b in enumerate(labels):
            on = i == state['selected']
            b.configure(bg=gold if on else card, fg='#16120a' if on else text)

    def choose(i):
        state['selected'] = i
        paint()
        if i == 1:
            state['choice'] = 'declined'
            root.after(50, root.destroy)
            return
        buttons.pack_forget()
        hint.pack_forget()
        title.configure(text='Updating')
        message.configure(text=f'Downloading version {newest}…')
        bar.pack(pady=(10, 0))

        def work():
            try:
                install_appimage(url, Path(os.environ['APPIMAGE']), lambda p: events.put(('progress', p)))
                events.put(('done', None))
            except (OSError, ValueError) as error:
                events.put(('failed', str(error)))
        threading.Thread(target=work, daemon=True).start()
        state['progress'] = 0

    def tick():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'progress':
                    bar.delete('all')
                    bar.create_rectangle(0, 0, 560 * value / 100, 22, fill=gold, width=0)
                    message.configure(text=f'Downloading version {newest}… {value}%')
                elif kind == 'done':
                    title.configure(text='Update installed')
                    message.configure(text=f'Version {newest} is installed.\n'
                                           'The game will close now. Start it again to play.')
                    state['choice'] = 'updated'
                    root.after(5000, root.destroy)
                elif kind == 'failed':
                    message.configure(text=f'The update failed: {value[:80]}\nStarting the game…')
                    state['choice'] = 'declined'
                    root.after(3500, root.destroy)
        except queue.Empty:
            pass
        if state['progress'] is None:  # still choosing
            for key in pads.pressed():
                if key in ('left', 'right'):
                    state['selected'] = 1 - state['selected']
                    paint()
                elif key == 'ok':
                    choose(state['selected'])
                    break
                elif key == 'back':
                    choose(1)
                    break
        root.after(40, tick)

    root.bind('<Left>', lambda _e: (state.update(selected=0), paint()))
    root.bind('<Right>', lambda _e: (state.update(selected=1), paint()))
    root.bind('<Tab>', lambda _e: (state.update(selected=1 - state['selected']), paint()))
    root.bind('<Return>', lambda _e: state['progress'] is None and choose(state['selected']))
    root.bind('<space>', lambda _e: state['progress'] is None and choose(state['selected']))
    root.bind('<Escape>', lambda _e: state['progress'] is None and choose(1))
    paint()
    root.after(40, tick)
    root.focus_force()
    root.mainloop()
    return state['choice'] or 'declined'


def launcher_class(base, ns):
    """A subclass of the launcher's Launcher (ns: the launcher module's globals): the Play page
    lists the three games, each with Add to Steam, Desktop shortcut and Play, usable only when
    that game's executable is in the chosen folder."""
    _ = ns['_']
    GAMES, SURFACE, TEXT, MUTED, CARD = ns['GAMES'], ns['SURFACE'], ns['TEXT'], ns['MUTED'], ns['CARD']
    NAME, PORT_DIR, game_info, GOLD = ns['NAME'], ns['PORT_DIR'], ns['game_info'], ns['GOLD']
    from uncharted_widgets import PillButton, rounded_image

    class IconButton(PillButton):
        """A pill button with an icon (launcher/icons) before its text."""

        def __init__(self, *args, icon_name='steam', **kwargs):
            self.icon_name = icon_name
            super().__init__(*args, **kwargs)

        def draw(self):
            import tkinter.font as tkfont
            from PIL import ImageTk
            super().draw()
            c = self.canvas
            font = tkfont.Font(font=self.font)
            size = font.metrics('ascent') + self.px(2)
            gap = self.px(8)
            text_w = font.measure(self.text)
            w = text_w + size + gap + 2 * self.px(self.padding[0])
            h = int(c['height'])
            c.configure(width=w)
            disabled = self.state != 'normal'
            fill = self.colors['button_hi'] if self.hover and not disabled else self.colors['button']
            fg = self.colors['muted'] if disabled else self.colors['text']
            c.delete('all')
            c.create_image(0, 0, anchor='nw', image=rounded_image(w, h, h // 2, fill, self.bg))
            self._icon = ImageTk.PhotoImage(icon_image(self.icon_name, size, fg, fill))
            x = w // 2 - (text_w + size + gap) // 2
            c.create_image(x, h // 2, anchor='w', image=self._icon)
            c.create_text(x + size + gap, h // 2, text=self.text, anchor='w', fill=fg, font=self.font)

    LAUNCH_TEXTS = (_('Preparing the game; it opens in its own window…'), _('The game is running.'),
                    _('Starting the next game of the collection…'))

    class LinuxLauncher(base):
        def build(self):
            super().build()
            self.saves_autofill()
            self.root.after(2500, self.watch_for_crash)
            self.build_header()
            # No bottom bar: the games start from their own rows; status messages stay hidden.
            self.status.master.master.pack_forget()
            self.build_corner()
            self.root.after(3000, self.periodic_update_check)
            # X11 Tk reports the wheel as buttons 4 and 5, not <MouseWheel>: the pages did not scroll.
            for button, delta in (('<Button-4>', 120), ('<Button-5>', -120)):
                handler = lambda e, d=delta: self.on_wheel(SimpleNamespace(delta=d, widget=e.widget))
                self.root.bind_all(button, handler)
                self.root.bind_class('TCombobox', button, handler)
            self.var('steam_deck').trace_add('write', lambda *_a: self.steam_deck_changed())
            self.steam_deck_changed(startup=True)
            self.build_save_button()

        def build_save_button(self):
            """Save changes, bottom right: dim until a setting changes, then gold until saved.
            Settings were saved only by Play and by closing the window, so a change was lost when
            Steam ended the launcher (Gaming Mode)."""
            right = self.content.master
            self.save_button = PillButton(self.tk, right, _('Save changes'), self.save_changes, ns['COLORS'],
                                          self.px, self.font_button, 'primary', SURFACE, (20, 8))
            self.save_button.canvas.place(relx=1.0, rely=1.0, anchor='se', x=-self.px(22), y=-self.px(18))
            for var in list(self.vars.values()) + list((getattr(self, 'pad_vars', None) or {}).values()):
                var.trace_add('write', lambda *_a: self.after_setting_change())
            self.saved_settings = self.settings_now()
            self.after_setting_change()

        def var(self, key):
            new = key not in self.vars
            var = super().var(key)
            if new and hasattr(self, 'saved_settings'):  # made after the button: watch it too
                var.trace_add('write', lambda *_a: self.after_setting_change())
            return var

        def settings_now(self):
            settings = self.current()
            if getattr(self, 'pad_vars', None):
                settings['pad_bindings'] = {a: v.get() for a, v in self.pad_vars.items()}
            return settings

        def after_setting_change(self):
            if hasattr(self, 'saved_settings'):
                changed = unsaved_changes(self.saved_settings, self.settings_now())
                self.save_button.configure(state='normal' if changed else 'disabled')
                self.tk.Misc.lift(self.save_button.canvas)  # Canvas.lift raises drawn items

        def save_changes(self):
            self.collect()
            label, saved = self.version_label, _('Settings saved')
            if label.cget('text') != saved:  # an update notice comes back afterwards
                self.corner_before = label.cget('text'), label.cget('fg')
            self.show_version(saved, GOLD)
            self.root.after(2500, lambda: label.cget('text') == saved and self.show_version(*self.corner_before))

        def collect(self):
            super().collect()
            if hasattr(self, 'saved_settings'):
                self.saved_settings = self.settings_now()
                self.after_setting_change()

        def choice(self, parent, key, options, width=36):
            """The launcher's drop-down, with the choices the Steam Deck cannot run greyed out
            (and not selectable) while Steam Deck mode is on."""
            var = self.var(key)
            values = [v for v, _t in options]
            box = self.ttk.Combobox(parent, values=[_(t) for _v, t in options], state='readonly', width=width)
            if var.get() not in values:
                var.set(values[0])
            self.boxes = getattr(self, 'boxes', {})
            self.boxes[key] = box

            def blocked(value):
                return bool(self.var('steam_deck').get()) and not deck_allows(key, value)

            def show(*_args):
                box.current(values.index(var.get()) if var.get() in values else 0)

            def picked(_event):
                value = values[box.current()]
                if blocked(value):
                    show()  # not on the Deck: the choice stays as it was
                else:
                    var.set(value)

            def grey():
                # The list is refilled after postcommand runs, so its items are coloured afterwards.
                try:
                    listbox = f"{box.tk.call('ttk::combobox::PopdownWindow', box)}.f.l"
                    for index, value in enumerate(values):
                        if blocked(value):
                            box.tk.call(listbox, 'itemconfigure', index, '-foreground', MUTED,
                                        '-selectforeground', MUTED)
                except Exception:  # only the colours: selection is refused in picked() anyway
                    pass
            box.configure(postcommand=lambda: box.after_idle(grey))
            show()
            box.bind('<<ComboboxSelected>>', picked)
            var.trace_add('write', show)
            return box

        def steam_deck_changed(self, startup=False):
            """Steam Deck mode on: the affected settings switch to the Deck's values (the previous ones
            are kept in deck_saved), the enforced ones are locked, the frame rate is 30 or 60 and the
            choices the Deck cannot run are greyed out. Off: the kept values come back."""
            on = bool(self.var('steam_deck').get())
            saved = self.app.get('deck_saved')
            if on and not isinstance(saved, dict):
                self.app['deck_saved'] = {key: self.var(key).get() for key in DECK_SETTINGS}
                for key, value in DECK_SETTINGS.items():
                    if key == 'frame_rate' and self.var(key).get() in DECK_FRAME_RATES:
                        continue  # 30 or 60 already: the player's choice stays
                    self.var(key).set(value)
            elif not on and isinstance(saved, dict):
                for key, value in saved.items():
                    if key in DECK_SETTINGS:
                        self.var(key).set(value)
                self.app.pop('deck_saved', None)
            elif on and startup:
                for key in DECK_LOCKED:  # what deck_environment will use anyway
                    self.var(key).set(DECK_SETTINGS[key])
            if on:  # a value the Deck cannot run (set before, or in settings.json): its safe one
                if not deck_allows('frame_rate', self.var('frame_rate').get()):
                    self.var('frame_rate').set(DECK_SETTINGS['frame_rate'])
                for key, value in DECK_FALLBACK.items():
                    if key in ns['APP_DEFAULTS'] and not deck_allows(key, self.var(key).get()):
                        self.var(key).set(value)
            for key in DECK_LOCKED:
                box = getattr(self, 'boxes', {}).get(key)
                if box is not None:
                    box.configure(state='disabled' if on else 'readonly')
            if not startup:
                self.collect()

        def nav_pages(self):
            return [('play', _('Library')), ('display', _('Settings')), ('controls', _('Controls')),
                    ('cheats', _('Cheats')), ('trophies', _('Trophies')),
                    ('game', _('Files')), ('advanced', _('Advanced'))]

        def build_header(self):
            """Top of the sidebar: the collection's name, 'Linux port' with Tux, and who made what."""
            from PIL import ImageTk
            tk, bg = self.tk, ns['BG']
            labels = [w for w in self.side.winfo_children() if isinstance(w, tk.Label)][:5]
            title, line1, line2, author, version = labels
            # The collection's name on one line: the largest brand size that fits the sidebar.
            import tkinter.font as tkfont
            name, room = 'THE NATHAN DRAKE COLLECTION', self.px(248) - 2 * self.px(20)
            family, size = self.font_brand_sm[0], self.font_brand_sm[1]
            while size > 7 and tkfont.Font(root=self.root, family=family, size=size).measure(name) > room:
                size -= 1
            line1.configure(text=name, fg=GOLD, font=(family, size))
            line2.pack_forget()
            port = tk.Frame(self.side, bg=bg)
            port.pack(anchor='w', padx=18, pady=(1, 0), after=line1)
            tk.Label(port, text='LINUX PORT', bg=bg, fg=GOLD, font=self.font_brand_sm).pack(side='left')
            self._tux = ImageTk.PhotoImage(icon_image('linux', self.px(17), GOLD, bg))
            tk.Label(port, image=self._tux, bg=bg, bd=0).pack(side='left', padx=(self.px(6), 0))
            version.configure(text=_('Linux port by spacepepperoni'), fg=TEXT, font=self.font_ui_md)
            author.pack_configure(pady=(self.px(12), 0))

        def folder(self, parent, key, title, prompt, hint=None, on_change=None):
            """A folder row whose field shrinks to the window: Browse and Open stay on screen and a
            long path scrolls inside the field."""
            var = self.var(key)
            card = self.target(parent)
            holder = self.tk.Frame(card, bg=CARD)

            def browse():
                chosen = self.filedialog.askdirectory(title=prompt, initialdir=var.get() or str(PORT_DIR))
                if chosen:
                    var.set(str(Path(chosen)))
            self.pill(holder, _('Open'), lambda: self.open_path(var.get(), key), kind='ghost',
                      padding=(12, 6)).pack(side='right', padx=(4, 0))
            self.pill(holder, _('Browse…'), browse, padding=(14, 6)).pack(side='right', padx=(8, 0))
            self.ttk.Entry(holder, textvariable=var, width=20).pack(side='left', fill='x', expand=True)
            if on_change:
                var.trace_add('write', lambda *_a: on_change())
            self.row(parent, title, holder, hint)
            holder.grid_configure(sticky='we')
            card.columnconfigure(1, weight=1)
            return holder

        def build_corner(self):
            """Bottom of the sidebar: the GitHub mark, the download button (grey: up to date;
            glowing and pulsing: a new version, click to install it) and the version."""
            from PIL import ImageTk
            tk, bg, size = self.tk, ns['BG'], self.px(26)
            self.side_note.pack_forget()
            row = tk.Frame(self.side, bg=bg)
            row.pack(anchor='w', fill='x', padx=18, pady=(0, 18))
            self.side_note = row
            self._github = ImageTk.PhotoImage(icon_image('github', size, MUTED, bg))
            self._github_hot = ImageTk.PhotoImage(icon_image('github', size, TEXT, bg))
            github = tk.Label(row, bg=bg, bd=0, image=self._github, cursor='hand2')
            github.pack(side='left')
            github.bind('<Button-1>', lambda _e: open_path(REPO_URL))
            github.bind('<Enter>', lambda _e: github.configure(image=self._github_hot))
            github.bind('<Leave>', lambda _e: github.configure(image=self._github))
            self._download_idle = ImageTk.PhotoImage(download_icon(size, MUTED, bg))
            self._download_hot = ImageTk.PhotoImage(download_icon(size, TEXT, bg))
            self._download_glow = [ImageTk.PhotoImage(download_icon(size, ns['GOLD_HI'], bg, glow=g, glow_color=GOLD))
                                   for g in (0.2, 0.4, 0.6, 0.8, 1.0, 0.8, 0.6, 0.4)]
            self.update_button = tk.Label(row, bg=bg, bd=0, image=self._download_idle, cursor='hand2')
            self.update_button.pack(side='left', padx=(self.px(12), 0))
            self.update_button.bind('<Button-1>', lambda _e: self.update_clicked())
            self.update_button.bind('<Enter>', lambda _e: self.update_state == 'none' and
                                    self.update_button.configure(image=self._download_hot))
            self.update_button.bind('<Leave>', lambda _e: self.update_state == 'none' and
                                    self.update_button.configure(image=self._download_idle))
            self.version_label = tk.Label(row, text=ns['VERSION'], bg=bg, fg=MUTED, font=self.font_ui_sm)
            self.version_label.pack(side='left', padx=(self.px(10), 0))
            self.update_state, self.update_version, self.update_url = 'none', None, None
            self.update_page = ns['RELEASES_PAGE']
            self._glow_frame = 0

        def show_version(self, text=None, fg=None):
            self.version_label.configure(text=text or ns['VERSION'], fg=fg or MUTED)

        def set_update_state(self, state, version=None):
            self.update_state = state
            if version:
                self.update_version = version
            if state in ('available', 'downloading'):
                if not getattr(self, '_glowing', False):
                    self._glowing = True
                    self.glow()
            else:
                self._glowing = False
                self.update_button.configure(image=self._download_idle)

        def glow(self):
            if not self._glowing:
                return
            self._glow_frame = (self._glow_frame + 1) % len(self._download_glow)
            self.update_button.configure(image=self._download_glow[self._glow_frame])
            self.root.after(110, self.glow)

        def periodic_update_check(self):
            """At launch and every 30 minutes while the launcher is open."""
            if self.app.get('check_updates', True) and self.update_state == 'none':
                threading.Thread(target=self.check_update, daemon=True).start()
            self.root.after(30 * 60 * 1000, self.periodic_update_check)

        def update_clicked(self):
            if self.update_state == 'available':
                self.install_update_now()
            elif self.update_state == 'none':
                self.show_version(_('Checking…'))

                def check():
                    self.check_update(manual=True)
                    self.ui_calls.put(lambda: self.update_state == 'none' and self.show_version())
                threading.Thread(target=check, daemon=True).start()

        def install_update_now(self):
            """Downloads the new AppImage, puts it in place and restarts the launcher with it
            (other installs: the release page)."""
            if self.process:
                self.messagebox.showinfo(NAME, _('Close the game before updating.'))
                return
            if not os.environ.get('APPIMAGE') or not self.update_url:
                open_path(self.update_page)
                return
            version = self.update_version
            self.set_update_state('downloading', version)

            def progress(percent):
                self.ui_calls.put(lambda: self.show_version(_('Downloading {}%').format(percent), GOLD))

            def work():
                try:
                    install_appimage(self.update_url, Path(os.environ['APPIMAGE']), progress)
                except (OSError, ValueError) as failure:
                    def failed(error=failure):
                        self.set_update_state('available', version)
                        self.show_version()
                        self.messagebox.showerror(NAME, _('Update failed: {}').format(error))
                    self.ui_calls.put(failed)
                    return
                self.ui_calls.put(self.restart_updated)
            threading.Thread(target=work, daemon=True).start()

        def build_advanced(self):
            """Advanced: options for testing and the game's log."""
            f = self.page('advanced', _('Advanced'), _('Options for testing, logs and bug reports.'))
            self.check(f, 'check_updates', _('Automatic updates'),
                       _('Look for a new version when the launcher or a game starts, and offer to install it.'))
            self.check(f, 'close_on_play', _('Close the launcher when the game starts'))
            extra = self.ttk.Entry(f, textvariable=self.var('extra_env'), width=60)
            self.row(f, _('Environment'), extra, _('Extra variables for the game, NAME=value separated by spaces.'))
            self.section(f, _('Logs and bug reports'))
            self.note(f, _('Something wrong? Copy log for GitHub copies your system details and the last game '
                           'log, without your home folder or user name. Paste it into a new issue in the Issues '
                           'tab of the Uncharted Linux port on GitHub. Create bug report saves all logs of the '
                           'last 5 runs as one zip file in Downloads instead; nothing is uploaded. If the '
                           'launcher window does not work, right-click Uncharted in the application menu and '
                           'choose Create bug report.'), top=2)
            card = self.target(f)
            self.health_label = self.ttk.Label(card, text='', style='Muted.TLabel', wraplength=self.px(680),
                                               justify='left')
            self.health_label.grid(row=self.next_row(card), column=0, columnspan=2, sticky='w', pady=(10, 0))
            self.show_health()
            holder = self.tk.Frame(card, bg=CARD)
            holder.grid(row=self.next_row(card), column=0, columnspan=2, sticky='w', pady=(12, 0))
            self.pill(holder, _('Copy log for GitHub'), self.copy_for_github, kind='primary').pack(side='left')
            self.pill(holder, _('Create bug report'), self.create_report).pack(side='left', padx=(8, 0))
            self.pill(holder, _('Show the game log'), lambda: self.show('log')).pack(side='left', padx=(8, 0))
            self.pill(holder, _('Open the logs folder'),
                      lambda: open_path(uncharted_logs.log_dir(ns['DATA_DIR']))).pack(side='left', padx=(8, 0))

        def show_health(self):
            """What the recent logs say went wrong, under Logs and bug reports."""
            found = uncharted_logs.health(ns['DATA_DIR'], self.saves_folder(), crash_signature)
            if found:
                text = _('Found in the recent logs:') + '\n' + '\n'.join(f'•  {line}' for line in found)
            else:
                text = _('No problems found in the recent logs.')
            self.health_label.configure(text=text, foreground=GOLD if found else MUTED)

        def copy_for_github(self, intro=''):
            """The log for the bug report form on the clipboard, then the form opened."""
            self.collect()
            text = uncharted_logs.issue_text(ns['DATA_DIR'], self.saves_folder(), self.app, ns['VERSION'],
                                             crash_signature)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()  # hand the clipboard over now, not when the dialog closes
            if self.messagebox.askyesno(NAME, intro + _('Your log is copied.\n\nOpen the Issues tab of the Uncharted '
                                                        'Linux port on GitHub now? Fill in the form and paste the log '
                                                        'into its Log field (Ctrl+V). Keep this launcher open until '
                                                        'you have pasted it.')):
                open_path(uncharted_logs.ISSUE_URL)

        def create_report(self):
            self.collect()
            try:
                path = uncharted_logs.create_report(ns['DATA_DIR'], self.saves_folder(), self.app, PORT_DIR,
                                                    ns['VERSION'], crash_signature)
            except OSError as error:
                self.messagebox.showerror(NAME, _('Could not create the bug report: {}').format(error))
                return
            self.show_health()
            open_path(path.parent)
            self.messagebox.showinfo(NAME, _('Bug report saved as {} in {}.\n\nSend this file with your bug report '
                                             '(Discord or a GitHub issue).').format(path.name, path.parent))

        def build_game(self):
            """Files: the game folder, the saves folder and each game's saves, the shader cache."""
            f = self.page('game', _('Files'), '')
            self.folder(f, 'game_dir', _('Game folder'), _('The folder with eboot.bin'),
                        _('The folder with eboot.bin, big2-ps4_Shipping.elf and big3-ps4_Shipping.elf.'),
                        on_change=self.refresh)
            self.folder(f, 'user_dir', _('Saves folder'), _('Where saves and the shader cache are kept'),
                        _('Empty: a Saves folder in the game folder.'))
            self.section(f, _('Saves'))
            card = self.target(f)
            self.saves_rows = self.tk.Frame(card, bg=CARD)
            self.saves_rows.grid(row=self.next_row(card), column=0, columnspan=2, sticky='we')
            self.fill_saves()
            self.section(f, _('Shader cache'))
            self.note(f, _('Recommended to only clear if you have visual issues'), top=2)
            card = self.target(f)
            holder = self.tk.Frame(card, bg=CARD)
            holder.grid(row=self.next_row(card), column=0, columnspan=2, sticky='w', pady=(12, 0))
            self.pill(holder, _('Clear shader cache'), self.clear_cache).pack(side='left')

        def row(self, parent, title, widget, hint=None):
            """Upstream's rows with this fork's shorter texts (ROW_HINTS; None: no text)."""
            hints = {_(key): _(text) if text else None for key, text in ROW_HINTS.items()}
            return super().row(parent, title, widget, hints[title] if title in hints else hint)

        def build_display(self):
            """Settings: display and graphics, and the console (language, player name)."""
            super().build_display()
            f = self.page_inner['display']
            self.section(f, _('Console'))
            self.row(f, _('Language'), self.choice(f, 'language', ns['LANGUAGES'], 30))
            name = self.ttk.Entry(f, textvariable=self.var('player_name'), width=30)
            self.row(f, _('Player name'), name, _('Shown where the game uses the PSN name.'))

        # The upstream defaults (background=CARD) are bound when the module loads: a rounded button
        # or switch could paint its corners in another colour than the card under it (square look).
        def pill(self, parent, text, command, kind='secondary', background=None, padding=(16, 8), icon=None):
            return super().pill(parent, text, command, kind, background or ns['CARD'], padding, icon)

        def toggle(self, parent, variable, background=None):
            return super().toggle(parent, variable, background or ns['CARD'])

        def fill_saves(self):
            import datetime
            tk = self.tk
            for child in self.saves_rows.winfo_children():
                child.destroy()
            base = self.saves_folder()
            folders = (('Uncharted 1', GAMES[0][1]), ('Uncharted 2', GAMES[1][1]), ('Uncharted 3', GAMES[2][1]))
            for r, (folder_name, title) in enumerate(folders):
                folder = base / folder_name
                saves = [d for d in folder.glob('SAVEDATA*') if d.is_dir() and not d.name.endswith('.sce_sys')] \
                    if folder.is_dir() else []
                if saves:
                    newest = max(d.stat().st_mtime for d in saves)
                    info = (_('1 save, last saved {}') if len(saves) == 1 else
                            _('{} saves, last saved {}').replace('{}', str(len(saves)), 1)).format(
                        datetime.datetime.fromtimestamp(newest).strftime('%Y-%m-%d %H:%M'))
                else:
                    info = _('No saves yet')
                block = tk.Frame(self.saves_rows, bg=CARD)
                block.grid(row=r, column=0, sticky='we', pady=(self.px(4) if r else 0, self.px(10)))
                tk.Label(block, text=f'{folder_name}: {title}', bg=CARD, fg=TEXT,
                         font=self.font_brand_md).grid(row=0, column=0, sticky='w')
                tk.Label(block, text=str(folder), bg=CARD, fg=TEXT, font=self.font_ui_sm, justify='left',
                         wraplength=self.px(560), anchor='w').grid(row=1, column=0, sticky='w')
                tk.Label(block, text=info, bg=CARD, fg=MUTED, font=self.font_ui_sm).grid(
                    row=2, column=0, sticky='w')
                self.pill(block, _('Open'), lambda d=folder: (d.mkdir(parents=True, exist_ok=True), open_path(d)),
                          padding=(14, 6)).grid(row=0, column=1, rowspan=3, sticky='e', padx=(self.px(24), 0))
                block.columnconfigure(0, weight=1)

        def show(self, name):
            super().show(name)
            if name == 'game' and hasattr(self, 'saves_rows'):
                self.fill_saves()
            if name == 'log':  # the log belongs to Advanced
                self._nav_style('advanced', active=True)

        def style(self):
            super().style()
            # Dropdowns with round ends, like the buttons (clam draws square ones).
            from PIL import Image, ImageDraw, ImageTk
            h = self.px(30)
            r = h // 2
            images = []
            for color in (ns['CARD_HI'], ns['GOLD_DIM']):
                # Opaque corners in the card colour behind the dropdowns: Tk fills transparent
                # pixels of an element image with the widget's own (field) colour.
                image = Image.new('RGB', (h * 4 * 2, h * 4), CARD)
                ImageDraw.Draw(image).rounded_rectangle((0, 0, h * 8 - 1, h * 4 - 1), r * 4, fill=color)
                images.append(ImageTk.PhotoImage(image.resize((h * 2, h), Image.LANCZOS)))
            self._field_images = images
            s = self.ttk.Style(self.root)
            try:
                s.element_create('Round.field', 'image', images[0], ('focus', images[0]),
                                 border=(r, r // 2, r, r // 2), sticky='nswe')
            except self.tk.TclError:
                pass
            s.layout('TCombobox', [('Round.field', {'sticky': 'nswe', 'children': [
                ('Combobox.downarrow', {'side': 'right', 'sticky': 'ns'}),
                ('Combobox.padding', {'expand': '1', 'sticky': 'nswe', 'children': [
                    ('Combobox.textarea', {'sticky': 'nswe'})]})]})])
            s.configure('TCombobox', arrowcolor=GOLD, background=ns['CARD_HI'], bordercolor=ns['CARD_HI'],
                        lightcolor=ns['CARD_HI'], darkcolor=ns['CARD_HI'], padding=(self.px(4), 2))

        def page(self, name, title, subtitle):
            if name == 'display':
                title, subtitle = _('Settings'), _('Display, graphics and the console.')
            f = super().page(name, title, subtitle)
            self.page_inner = getattr(self, 'page_inner', {})
            self.page_inner[name] = f
            if name == 'display':
                self.check(f, 'steam_deck', _('Steam Deck mode'),
                           _('Optimizes settings for Steam Deck. 1280x800 60FPS'))
            return f

        def build_play(self):
            tk = self.tk
            page = tk.Frame(self.content, bg=SURFACE)
            self.pages['play'] = page
            self.cards, self.card_images = {}, {}
            self.game_rows = {}
            shell = tk.Frame(page, bg=SURFACE)
            shell.pack(fill='both', expand=True, padx=self.px(44), pady=(self.px(36), self.px(10)))
            for key, title, _subtitle, exe in GAMES:
                row = tk.Frame(shell, bg=CARD, highlightthickness=0)
                row.pack(fill='x', pady=(0, self.px(10)))
                text = tk.Frame(row, bg=CARD)
                tk.Label(text, text=f'Uncharted: {title}', bg=CARD, fg=TEXT,
                         font=self.font_brand_md).pack(anchor='w')
                note = tk.Label(text, text='', bg=CARD, fg=MUTED, font=self.font_ui_sm)
                note.pack(anchor='w')
                buttons = tk.Frame(row, bg=CARD)
                play = self.pill(buttons, _('Play'), lambda k=key: self.play_game(k), kind='primary',
                                 background=CARD, padding=(26, 8))
                play.pack(side='right', padx=(self.px(8), self.px(18)))
                shortcut = self.pill(buttons, _('Desktop shortcut'), lambda k=key: self.game_shortcut(k),
                                     background=CARD, padding=(14, 8))
                shortcut.pack(side='right', padx=(self.px(8), 0))
                steam = IconButton(self.tk, buttons, _('Add to Steam'), lambda k=key: self.add_game_to_steam(k),
                                   ns['COLORS'], self.px, self.font_button, 'secondary', CARD, (16, 8),
                                   icon_name='steam')
                steam.pack(side='right')
                row.bind('<Configure>', lambda _e, r=row, t=text, b=buttons: self.fit_game_row(r, t, b))
                self.fit_game_row(row, text, buttons)
                self.game_rows[key] = (play, steam, shortcut, note, exe)
            row = tk.Frame(shell, bg=SURFACE)
            row.pack(fill='x', pady=(self.px(14), self.px(8)))
            self.toggle(row, self.var('fullscreen'), SURFACE).pack(side='left')
            fullscreen = tk.Label(row, text=_('Fullscreen'), bg=SURFACE, fg=TEXT, font=self.font_ui, cursor='hand2')
            fullscreen.pack(side='left', padx=(self.px(10), 0))
            fullscreen.bind('<Button-1>', lambda _e: self.var('fullscreen').set(not self.var('fullscreen').get()))
            # The upstream refresh() writes a line here; it is not shown (the game rows say it).
            self.ready = tk.Label(shell, text='', bg=SURFACE, fg=MUTED, font=self.font_ui_sm)

        def fit_game_row(self, row, text, buttons):
            """The buttons beside the title when the row is wide enough, else under it (large
            display scaling or a narrow window cut Add to Steam off)."""
            wide = row.winfo_width() >= text.winfo_reqwidth() + buttons.winfo_reqwidth() + self.px(36)
            if getattr(row, 'wide', None) == wide:
                return
            row.wide = wide
            text.pack_forget()
            buttons.pack_forget()
            if wide:
                text.pack(side='left', padx=self.px(18), pady=self.px(14))
                buttons.pack(side='right')
            else:
                text.pack(side='top', anchor='w', padx=self.px(18), pady=(self.px(14), self.px(8)))
                buttons.pack(side='top', anchor='w', padx=(self.px(18), 0), pady=(0, self.px(14)))

        def saves_folder(self):
            return Path(self.app.get('user_dir') or ns['DATA_DIR'] / 'user')

        def watch_for_crash(self):
            """After every run (and once at start, for a run started from Steam): a crashed one
            gets an offer to report it."""
            running = bool(self.process)
            before = getattr(self, '_was_running', None)  # None: the launcher just started
            if not running and before is not False:
                self.root.after(1500, self.offer_crash_report)
            self._was_running = running
            self.root.after(1000, self.watch_for_crash)

        def offer_crash_report(self):
            import hashlib
            log = self.saves_folder() / 'last_run.log'
            signature, text = crash_signature(log)
            if not signature:
                return
            key = hashlib.sha1(text.encode(errors='replace')).hexdigest()[:16]
            if self.app.get('reported_crash') == key:
                return
            self.app['reported_crash'] = key  # asked once per crashed run, whatever the answer
            self.collect()
            self.copy_for_github(_('Uncharted stopped with:\n\n{}\n\nPlease check the open issues for the same '
                                   'crash first; nothing is sent until you submit the form.\n\n').format(signature[:160]))

        def saves_autofill(self):
            # Choosing a game folder fills in <folder>/Saves, unless the player chose a saves
            # folder of their own (the field is empty or still holds the previous automatic one).
            game, saves = self.var('game_dir'), self.var('user_dir')
            self._auto_saves = saves_for(game.get())

            def follow(*_args):
                if saves.get() in ('', self._auto_saves):
                    self._auto_saves = saves_for(game.get())
                    saves.set(self._auto_saves)
            game.trace_add('write', follow)
            if not saves.get():
                follow()

        def collect(self):
            for key, var in self.vars.items():
                self.app[key] = var.get()
            before = self.app.get('user_dir')
            default_saves(self.app, ns['DATA_DIR'])
            if self.app.get('user_dir') != before and 'user_dir' in self.vars:
                self.vars['user_dir'].set(self.app['user_dir'])  # the Game page shows it
            super().collect()

        def refresh(self):
            super().refresh()
            info = self.info
            for key, (play, steam, shortcut, note, exe) in getattr(self, 'game_rows', {}).items():
                present = bool(info) and key in info['games']
                play.configure(state='normal' if present and not self.process else 'disabled')
                for button in (steam, shortcut):
                    button.configure(state='normal' if present else 'disabled')
                if not info:
                    note.configure(text=_('Choose the game folder on the Files page'))
                elif present:
                    note.configure(text=_('Ready'))
                else:
                    note.configure(text=_('{} is not in the game folder').format(exe))

        def can_start(self, key):
            """The game's executable is in the chosen folder (else a message says what is missing).
            Not `available`: since 0.3.6 the upstream launcher keeps a dict by that name."""
            self.collect()
            info = game_info(self.app['game_dir'])
            if not info:
                self.messagebox.showerror(NAME, _('Choose the game folder with eboot.bin on the Files page first.'))
                self.show('game')
                return False
            if key not in info['games']:
                exe = next(e for k, _t, _s, e in GAMES if k == key)
                self.messagebox.showerror(NAME, _('{} is not in the game folder, so this game cannot start.').format(exe))
                return False
            return True

        def game_name(self, key):
            number, title = next((n, t) for n, (k, t, _s, _e) in enumerate(GAMES, start=1) if k == key)
            return f'Uncharted {number}: {title}'

        def play_game(self, key):
            if self.can_start(key):
                self.var('start').set(key)
                self.play()

        def play(self):
            if not self.process:
                rotate_logs(Path(self.app.get('user_dir') or ns['DATA_DIR'] / 'user'))
            super().play()

        def game_shortcut(self, key):
            if not self.can_start(key):
                return
            try:
                desktop_game_entry(ns['__file__'], key, self.game_name(key))
            except OSError as error:
                self.messagebox.showerror(NAME, str(error))
                return
            self.messagebox.showinfo(NAME, _('{} is in the application menu and on the desktop.').format(
                self.game_name(key)))

        # No artwork on this page.
        def draw_hero(self):
            pass

        def draw_card(self, key):
            pass

        def fit_posters(self, _event=None):
            pass

        # ---- updates: the AppImage replaces itself with the newest release of this fork ----------
        def offer_update(self, version, url, page):
            """A newer release (at launch or while open): the download button glows; a click
            installs it."""
            if self.update_state in ('downloading',):
                return
            self.update_url, self.update_page = url, page or ns['RELEASES_PAGE']
            self.set_update_state('available', version)
            self.show_version(_('{} available').format(version), GOLD)

        def restart_updated(self):
            if self.process:
                self.messagebox.showinfo(NAME, _('Close the game before restarting.'))
                return
            env = clean_env()
            for name in ('APPIMAGE', 'APPDIR', 'ARGV0', 'OWD'):  # the new AppImage sets its own
                env.pop(name, None)
            subprocess.Popen([os.environ['APPIMAGE']], env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self.close()

        def add_to_steam(self):
            for key, *_rest in GAMES:
                if key in (self.info or {}).get('games', []):
                    self.add_game_to_steam(key)

        def add_game_to_steam(self, key):
            """This game in the Steam library (a non-Steam game started with the settings saved
            in this launcher), only when its executable is in the game folder."""
            if not self.can_start(key):
                return
            import bbport_steam
            steam = steam_folder()
            configs = bbport_steam.user_configs(steam) if steam else []
            if not configs:
                self.messagebox.showerror(NAME, _('Steam was not found on this PC (or nobody has signed in to it yet).'))
                return
            name = self.game_name(key)
            restart = False
            if steam_running():
                if not self.messagebox.askyesno(NAME, _('Steam has to close while the game is added; it starts '
                                                        'again afterwards. Close Steam now?')):
                    return
                steam_shutdown(steam)
                for _i in range(60):
                    time.sleep(0.5)
                    if not steam_running():
                        break
                else:
                    self.messagebox.showerror(NAME, _('Steam did not close. Close it yourself and try again.'))
                    return
                time.sleep(1)
                restart = True
            exe, options = steam_command(steam, ns['__file__'], key)
            # The icon install.sh puts in place (the AppImage's own files are gone once it closes).
            icon = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / \
                'icons' / 'hicolor' / '256x256' / 'apps' / 'uncharted-linux.png'
            if not icon.is_file() and not os.environ.get('APPIMAGE'):
                icon = Path(PORT_DIR) / 'launcher' / 'uncharted.png'
            start_dir = Path(os.environ.get('APPIMAGE') or sys.executable).parent
            try:
                for config in configs:
                    bbport_steam.add_shortcut(config / 'shortcuts.vdf', name, exe, str(start_dir),
                                              str(icon) if icon.is_file() else '', options, match_options=True)
                    try:  # library pictures: SteamGridDB's, else the player's own game folder's
                        import uncharted_art
                        appid = bbport_steam.shortcut_id(f'"{exe}"', name)
                        if not uncharted_art.steamgriddb_artwork(key, config / 'grid', appid):
                            uncharted_art.steam_artwork(self.app['game_dir'], config / 'grid', appid)
                    except Exception:
                        pass
            except (OSError, ValueError) as error:
                self.messagebox.showerror(NAME, _('Could not add the game to Steam: {}').format(error))
                return
            if restart:
                open_path('steam://open/games')
            self.messagebox.showinfo(NAME, _('{} is in your Steam library. It starts with the settings saved '
                                             'in this launcher.').format(name))

    return LinuxLauncher


def font_scale(root):
    """How much larger fonts are drawn than Tk's screen DPI says: KDE/GNOME scaling under
    XWayland sets Xft.dpi (206 at 215 %) while X reports 96 DPI, and Xft draws every font at
    Xft.dpi. The layout is scaled by the same factor so the text fits."""
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XResourceManagerString.restype = ctypes.c_char_p
        x11.XResourceManagerString.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        display = x11.XOpenDisplay(None)
        if not display:
            return 1.0
        try:
            resources = (x11.XResourceManagerString(display) or b'').decode(errors='replace')
        finally:
            x11.XCloseDisplay(display)
        dpi = next((float(line.split(':', 1)[1]) for line in resources.splitlines()
                    if line.split(':', 1)[0].strip() == 'Xft.dpi'), None)
        scale = dpi / root.winfo_fpixels('1i') if dpi else 1.0
    except (OSError, ValueError, AttributeError):
        return 1.0
    return scale if 1.1 <= scale <= 4.0 else 1.0
