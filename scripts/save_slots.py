"""Save slots (issue #71): each game's saves in numbered slots; the game sees the selected one.

The games always save to the same directories (SAVEDATA020 and SAVEDATA02P for Uncharted 2), so a
slot is a whole folder of them. Slot 1 is the game's folder of the saves folder (<saves>/Uncharted 2,
where saves were before slots), slot n <saves>/Save slots/Uncharted 2/Slot n. save_slots.json in the
saves folder keeps each game's selected slot and the slot names: a start from Steam (run.py --play)
uses the slot chosen in the launcher.
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


def relative(game, slot):
    """The slot's folder, relative to the saves folder."""
    return game if slot == 1 else f'{SLOTS_FOLDER}/{game}/Slot {slot}'


def slot_dir(saves, game, slot):
    return Path(saves) / relative(game, slot)


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


def saves_in(folder):
    """The save directories in a slot folder (not their .sce_sys metadata)."""
    folder = Path(folder)
    return [d for d in folder.glob('SAVEDATA*') if d.is_dir() and not d.name.endswith('.sce_sys')] \
        if folder.is_dir() else []


def used(saves, game, slot):
    return bool(saves_in(slot_dir(saves, game, slot)))


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
    found = saves_in(folder)
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
    for entry in src.glob('SAVEDATA*'):
        (shutil.copytree if entry.is_dir() else shutil.copy2)(entry, temp / entry.name)
    clear(saves, game, target)
    dst.mkdir(parents=True, exist_ok=True)
    for entry in temp.iterdir():
        os.replace(entry, dst / entry.name)
    temp.rmdir()


def clear(saves, game, slot):
    """Deletes the slot's saves (only the save directories: slot 1 is the game's folder)."""
    for entry in slot_dir(saves, game, slot).glob('SAVEDATA*'):
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
    return ';'.join(f'{PREFIXES[g]}={relative(g, selected(saves, g, state))}' for g in GAMES)
