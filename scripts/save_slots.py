"""Save slots (issue #71): each game's saves in numbered slots; the game sees the selected one.

The games always save to the same directories (SAVEDATA020 and SAVEDATA02P for Uncharted 2), so a
slot is a whole folder of them. Slot 1 is the game's folder of the saves folder (<saves>/Uncharted 2,
where saves were before slots), slot n <saves>/Save slots/Uncharted 2/Slot n. save_slots.json in the
saves folder keeps each game's selected slot and the slot names: a start from Steam (run.py --play)
uses the slot chosen in the launcher.

Issue #83: with the Windows layout (the launcher's Save folder layout setting, BB_SAVE_LAYOUT=windows)
slot 1 of every game is <saves>/savedata/1/<title ID>, one folder for all three games as the Windows
port keeps them, so that a sync tool can share it with a Windows PC. save_slots.json then holds
"windows": "savedata/1/<title ID>". Slots 2 and up stay where they are.
"""
import json
import os
from pathlib import Path
import shutil

GAMES = ('Uncharted 1', 'Uncharted 2', 'Uncharted 3')
PREFIXES = {'Uncharted 1': 'SAVEDATA01', 'Uncharted 2': 'SAVEDATA02', 'Uncharted 3': 'SAVEDATA03'}
MOST = 10
STATE = 'save_slots.json'
SLOTS_FOLDER = 'Save slots'
WINDOWS_USER = 1   # the user number in the Windows port's savedata/<user>/<title ID>


def relative(game, slot, state=None):
    """The slot's folder, relative to the saves folder."""
    if slot != 1:
        return f'{SLOTS_FOLDER}/{game}/Slot {slot}'
    windows = windows_folder(state if state is not None else {})
    return windows or game


def slot_dir(saves, game, slot):
    return Path(saves) / relative(game, slot, load(saves) if slot == 1 else None)


def load(saves):
    try:
        with open(Path(saves) / STATE, encoding='utf-8') as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def store(saves, state):
    path = Path(saves) / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=1, ensure_ascii=False)
    os.replace(temp, path)


def _game(state, game):
    entry = state.get(game)
    return entry if isinstance(entry, dict) else {}


def selected(saves, game, state=None):
    slot = _game(state if state is not None else load(saves), game).get('selected', 1)
    return slot if isinstance(slot, int) and 1 <= slot <= MOST else 1


def select(saves, game, slot):
    state = load(saves)
    state.setdefault(game, {})['selected'] = slot
    store(saves, state)


def name(saves, game, slot, state=None):
    names = _game(state if state is not None else load(saves), game).get('names', {})
    value = names.get(str(slot), '') if isinstance(names, dict) else ''
    return value if isinstance(value, str) else ''


def rename(saves, game, slot, text):
    state = load(saves)
    names = state.setdefault(game, {}).setdefault('names', {})
    if text.strip():
        names[str(slot)] = text.strip()[:40]
    else:
        names.pop(str(slot), None)
    store(saves, state)


def saves_in(folder, game=None):
    """The save directories in a slot folder (not their .sce_sys metadata); with `game`, only that
    game's (the Windows layout keeps all three games in one folder)."""
    folder = Path(folder)
    pattern = PREFIXES[game] + '*' if game else 'SAVEDATA*'
    return [d for d in folder.glob(pattern) if d.is_dir() and not d.name.endswith('.sce_sys')] \
        if folder.is_dir() else []


def used(saves, game, slot):
    return bool(saves_in(slot_dir(saves, game, slot), game))


def slots(saves, game):
    """The slots to list: 1, every slot with saves, and the selected one."""
    state = load(saves)
    shown = {1, selected(saves, game, state)}
    shown.update(n for n in range(2, MOST + 1) if used(saves, game, n))
    return sorted(shown)


def details(saves, game, slot):
    """(the game's own description of the save, newest save time) or ('', None) for an empty slot.
    The description is the detail of the campaign save's param.bin (OrbisSaveDataParam: title 128,
    subtitle 128, detail 1024 bytes), e.g. 'Campaign 75% Complete - The Monastery'."""
    folder = slot_dir(saves, game, slot)
    found = saves_in(folder, game)
    if not found:
        return '', None
    newest = max(d.stat().st_mtime for d in found)
    text = ''
    for meta in sorted(folder.glob(PREFIXES[game] + '[0-9].sce_sys')):
        try:
            raw = (meta / 'param.bin').read_bytes()[256:256 + 1024]
        except OSError:
            continue
        text = raw.split(b'\0', 1)[0].decode('utf-8', 'replace').strip()
        if text:
            break
    return ' · '.join(line.strip() for line in text.splitlines() if line.strip()), newest


def first_free(saves, game):
    return next((n for n in range(2, MOST + 1) if not used(saves, game, n)
                 and n not in slots(saves, game)), None)


def copy(saves, game, source, target):
    """The target slot becomes a copy of the source slot (what was in it is replaced)."""
    src, dst = slot_dir(saves, game, source), slot_dir(saves, game, target)
    temp = dst.with_name(dst.name + '.copying')
    shutil.rmtree(temp, ignore_errors=True)
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.mkdir()
    for entry in src.glob(PREFIXES[game] + '*'):
        (shutil.copytree if entry.is_dir() else shutil.copy2)(entry, temp / entry.name)
    clear(saves, game, target)
    dst.mkdir(parents=True, exist_ok=True)
    for entry in temp.iterdir():
        os.replace(entry, dst / entry.name)
    temp.rmdir()


def clear(saves, game, slot):
    """Deletes the slot's saves (only the game's save directories: slot 1 is the game's folder, or
    with the Windows layout the folder all three games share)."""
    for entry in slot_dir(saves, game, slot).glob(PREFIXES[game] + '*'):
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()


def delete(saves, game, slot):
    """Deletes the slot's saves and its name; slot 1 stays as an empty slot."""
    clear(saves, game, slot)
    if slot != 1:
        shutil.rmtree(slot_dir(saves, game, slot), ignore_errors=True)
    rename(saves, game, slot, '')
    if slot != 1 and selected(saves, game) == slot:
        select(saves, game, 1)


def mapping(saves):
    """BB_SAVEDATA_DIRS for the runtime (runtime_savedata.c mapped_folder): each game's save
    directories in its selected slot."""
    state = load(saves)
    return ';'.join(f'{PREFIXES[g]}={relative(g, selected(saves, g, state), state)}' for g in GAMES)


def windows_folder(state):
    """savedata/1/<title ID> when the saves use the Windows layout, else ''."""
    value = state.get('windows', '') if isinstance(state, dict) else ''
    return value if isinstance(value, str) and value.startswith('savedata/') and '..' not in value else ''


def title_id(game_dir):
    """The game's title ID (CUSA02320, ...) from its sce_sys/param.sfo, or ''."""
    import struct
    try:
        data = (Path(game_dir) / 'sce_sys' / 'param.sfo').read_bytes()
        magic, _version, keys, values, count = struct.unpack_from('<IIIII', data, 0)
        if magic != 0x46535000:
            return ''
        for i in range(count):
            key_at, _fmt, length, _most, value_at = struct.unpack_from('<HHIII', data, 0x14 + i * 16)
            key = data[keys + key_at:data.index(0, keys + key_at)]
            if key == b'TITLE_ID':
                text = data[values + value_at:values + value_at + length].rstrip(b'\0').decode('ascii', 'replace')
                return text if text.isalnum() else ''
    except (OSError, ValueError, struct.error):
        pass
    return ''


def _move_saves(source, target, game):
    """Moves the game's save directories (and their .sce_sys) from source to target; one already
    in the target stays where it is. Returns the names left behind."""
    left = []
    source, target = Path(source), Path(target)
    if not source.is_dir() or source.resolve() == target.resolve():
        return left
    for entry in sorted(source.glob(PREFIXES[game] + '*')):
        destination = target / entry.name
        if destination.exists():
            left.append(entry.name)
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.move(str(entry), str(destination))
    return left


def use_layout(saves, layout, game_dir=''):
    """Issue #83: puts every game's slot-1 saves where `layout` keeps them ('windows':
    savedata/1/<title ID> as the Windows port; anything else: a folder per game) and records the
    choice for mapping(). The title ID comes from the game folder, else the one recorded before,
    else the only savedata/1/<title ID> there is. Returns (layout used, messages)."""
    saves = Path(saves)
    state = load(saves)
    before = windows_folder(state)
    messages = []
    if layout == 'windows':
        title = title_id(game_dir) if game_dir else ''
        folder = f'savedata/{WINDOWS_USER}/{title}' if title else before
        if not folder:
            found = [d for d in (saves / 'savedata' / str(WINDOWS_USER)).glob('*')
                     if d.is_dir() and d.name.isalnum()] if (saves / 'savedata').is_dir() else []
            folder = f'savedata/{WINDOWS_USER}/{found[0].name}' if len(found) == 1 else ''
        if not folder:
            return 'games', ['Saves: the game\'s title ID is unknown; keeping a folder per game']
        for game in GAMES:
            sources = [saves / game] + ([saves / before] if before and before != folder else [])
            for source in sources:
                for name in _move_saves(source, saves / folder, game):
                    messages.append(f'Saves: {name} is in both {source.relative_to(saves)}/ and {folder}/; '
                                    f'the one in {source.relative_to(saves)}/ was left there')
        if folder != before:
            state['windows'] = folder
            store(saves, state)
            messages.append(f'Saves: Windows layout, slot 1 of every game in {folder}/')
        return 'windows', messages
    if before:
        for game in GAMES:
            for name in _move_saves(saves / before, saves / game, game):
                messages.append(f'Saves: {name} is in both {before}/ and {game}/; '
                                f'the one in {before}/ was left there')
        state.pop('windows', None)
        store(saves, state)
        messages.append('Saves: a folder per game again')
    return 'games', messages
