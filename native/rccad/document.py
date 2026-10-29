"""Immutable model revisions, atomic project files and undo/redo."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
import cadquery as cq
from .kernel import CadError, DisplayMesh, Frame, display_mesh, valid


@dataclass(frozen=True)
class Body:
    name: str
    shape: cq.Shape = field(compare=False, repr=False)
    kind: str = "solid"
    plane: object = "XY"   # 'XY' / 'XZ' / 'YZ' albo kernel.Frame (szkic na ścianie)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    visible: bool = True
    mesh: DisplayMesh | None = field(default=None, compare=False, repr=False)
    meta: dict | None = field(default=None, compare=False, repr=False)   # parametry szkicu (narzędzie, punkty, liczba boków) do edycji wymiarów

    def prepared(self):
        return replace(self, mesh=display_mesh(self.shape))

    def changed(self, shape):
        return replace(self, shape=shape, mesh=display_mesh(shape), meta=None)


class Document:
    def __init__(self):
        self.bodies: tuple[Body, ...] = ()
        self._undo = []      # (bryły, rewizja, etykieta) stanów PRZED bieżącym
        self._redo = []
        self.label = 'Początek'
        self.path: Path | None = None
        self._revision = 0
        self._saved_revision = 0
        self._next_revision = 1
        self.pending_label = None

    @property
    def dirty(self):
        return self._revision != self._saved_revision

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def get(self, body_id):
        return next((b for b in self.bodies if b.id == body_id), None)

    @staticmethod
    def _auto_label(before, after):
        old, new = {b.id: b for b in before}, {b.id: b for b in after}
        added = [b for i, b in new.items() if i not in old]
        removed = [b for i, b in old.items() if i not in new]
        changed = [b for i, b in new.items() if i in old and (old[i].shape is not b.shape or old[i].visible != b.visible or old[i].name != b.name)]
        if added and not removed:
            return f'Dodano: {added[0].name}' + (f' (+{len(added) - 1})' if len(added) > 1 else '')
        if removed and not added:
            return f'Usunięto: {removed[0].name}' + (f' (+{len(removed) - 1})' if len(removed) > 1 else '')
        if changed:
            return f'Zmieniono: {changed[0].name}' + (f' (+{len(changed) - 1})' if len(changed) > 1 else '')
        return 'Zmiana'

    def commit(self, bodies, label=None):
        bodies = tuple(bodies)
        if len({b.id for b in bodies}) != len(bodies):
            raise CadError("Powtórzony identyfikator obiektu.")
        self._undo.append((self.bodies, self._revision, self.label))
        self._undo = self._undo[-200:]
        self._redo.clear()
        self.label = label or self.pending_label or self._auto_label(self.bodies, bodies)
        self.pending_label = None
        self.bodies = bodies
        self._revision = self._next_revision
        self._next_revision += 1

    def undo(self):
        if self._undo:
            self._redo.append((self.bodies, self._revision, self.label))
            self.bodies, self._revision, self.label = self._undo.pop()

    def redo(self):
        if self._redo:
            self._undo.append((self.bodies, self._revision, self.label))
            self.bodies, self._revision, self.label = self._redo.pop()

    # ---------- historia: oś czasu stanów (niezmienne bryły, więc przeskok jest natychmiastowy) ----------
    def timeline(self):
        """(etykiety, indeks bieżącego): stany od najstarszego do najnowszego, razem z cofniętymi (redo)."""
        labels = [e[2] for e in self._undo] + [self.label] + [e[2] for e in reversed(self._redo)]
        return labels, len(self._undo)

    def goto(self, index):
        labels, current = self.timeline()
        index = max(0, min(index, len(labels) - 1))
        while current > index:
            self.undo(); current -= 1
        while current < index:
            self.redo(); current += 1

    @staticmethod
    def _entry(body, shape_index):
        entry = dict(id=body.id, name=body.name, kind=body.kind, plane=body.plane, visible=body.visible, shape=shape_index)
        if body.meta:
            entry['meta'] = body.meta
        if isinstance(body.plane, Frame):
            entry['plane'] = 'CUSTOM'
            entry['frame'] = body.plane.to_dict()
        return entry

    def save(self, path):
        """Zapisuje cały projekt razem z historią: każda unikalna geometria raz (BREP), a kroki jako listy odwołań do niej."""
        path = Path(path)
        older = [(e[0], e[2]) for e in self._undo]
        newer = [(e[0], e[2]) for e in reversed(self._redo)]
        states = [*older, (self.bodies, self.label), *newer]
        shapes, index = [], {}
        manifest = {"app": "RCCAD_DESKTOP", "version": 2, "units": "mm", "shapes": [], "states": [], "current": len(older)}
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".rccad-", suffix=".tmp", dir=path.parent)
            os.close(fd)
            with tempfile.TemporaryDirectory(prefix="rccad-brep-") as work, ZipFile(temp_path, "w", ZIP_DEFLATED) as archive:
                for bodies, label in states:
                    entries = []
                    for body in bodies:
                        key = id(body.shape)
                        if key not in index:
                            index[key] = len(shapes)
                            shapes.append(body.shape)
                            source = Path(work) / f"s{index[key]}.brep"
                            cq.exporters.export(body.shape, str(source), exportType="BREP")
                            archive.write(source, f"shapes/{index[key]}.brep")
                            manifest['shapes'].append(f"shapes/{index[key]}.brep")
                        entries.append(self._entry(body, index[key]))
                    manifest['states'].append(dict(label=label, bodies=entries))
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            os.replace(temp_path, path)
            self.path = path
            self._saved_revision = self._revision
        finally:
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()

    @staticmethod
    def _parse_body(item, shape, mesh):
        identifier = str(item['id'])
        if not re.fullmatch('[0-9a-f]{32}', identifier):
            raise CadError("Nieprawidłowa struktura projektu.")
        kind = item.get('kind', 'solid')
        plane = item.get('plane', 'XY')
        if plane == 'CUSTOM' and kind == 'sketch':
            plane = Frame.from_dict(item['frame'])
        if kind not in ('solid', 'mesh', 'sketch') or not (isinstance(plane, Frame) or plane in ('XY', 'XZ', 'YZ')):
            raise CadError("Nieprawidłowy typ obiektu lub płaszczyzna.")
        meta = item.get('meta')
        return Body(str(item['name']), shape, kind, plane, identifier, bool(item.get('visible', True)), mesh=mesh,
                    meta=meta if isinstance(meta, dict) else None)

    @classmethod
    def load(cls, path):
        result = cls()
        try:
            with ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="rccad-open-") as work:
                infos = archive.infolist()
                if len(infos) > 3001 or sum(i.file_size for i in infos) > 2_000_000_000:
                    raise CadError("Projekt jest zbyt duży.")
                if archive.getinfo("manifest.json").file_size > 20_000_000:
                    raise CadError("Nieprawidłowy manifest projektu.")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get('app') != 'RCCAD_DESKTOP' or manifest.get('version') not in (1, 2):
                    raise CadError("To nie jest obsługiwany projekt RCCAD Desktop.")
                if manifest['version'] == 1:
                    if not isinstance(manifest.get('bodies'), list):
                        raise CadError("To nie jest obsługiwany projekt RCCAD Desktop.")
                    bodies, ids = [], set()
                    for item in manifest['bodies']:
                        identifier = str(item['id'])
                        if not re.fullmatch('[0-9a-f]{32}', identifier) or identifier in ids or item['file'] != f'bodies/{identifier}.brep':
                            raise CadError("Nieprawidłowa struktura projektu.")
                        ids.add(identifier)
                        source = Path(work) / (identifier + '.brep')
                        source.write_bytes(archive.read(item['file']))
                        shape = cq.importers.importBrep(str(source)).val()
                        valid(shape, item.get('kind', 'solid') == 'solid')
                        bodies.append(cls._parse_body(item, shape, None).prepared())
                    result.bodies = tuple(bodies)
                    result.path = Path(path)
                    return result
                files, states = manifest.get('shapes'), manifest.get('states')
                current = manifest.get('current')
                if not isinstance(files, list) or not isinstance(states, list) or not states or len(states) > 1000 or not isinstance(current, int) or not 0 <= current < len(states):
                    raise CadError("Nieprawidłowa struktura projektu.")
                cache = {}      # numer geometrii -> (kształt, siatka): wczytywane i siatkowane raz, współdzielone przez wszystkie kroki

                def geometry(number, kind):
                    if not isinstance(number, int) or not 0 <= number < len(files) or files[number] != f'shapes/{number}.brep':
                        raise CadError("Nieprawidłowa struktura projektu.")
                    if number not in cache:
                        source = Path(work) / f'{number}.brep'
                        source.write_bytes(archive.read(files[number]))
                        shape = cq.importers.importBrep(str(source)).val()
                        valid(shape, kind == 'solid')
                        cache[number] = (shape, display_mesh(shape))
                    return cache[number]

                built = []
                for state in states:
                    ids, bodies = set(), []
                    for item in state['bodies']:
                        shape, mesh = geometry(item['shape'], item.get('kind', 'solid'))
                        body = cls._parse_body(item, shape, mesh)
                        if body.id in ids:
                            raise CadError("Nieprawidłowa struktura projektu.")
                        ids.add(body.id)
                        bodies.append(body)
                    built.append((tuple(bodies), str(state.get('label', 'Zmiana'))))
                result._next_revision = 1
                revisions = list(range(1, len(built) + 1))
                result._next_revision = len(built) + 1
                result._undo = [(b, revisions[i], lab) for i, (b, lab) in enumerate(built[:current])]
                result.bodies, result.label = built[current]
                result._revision = result._saved_revision = revisions[current]
                result._redo = [(b, revisions[i], lab) for i, (b, lab) in reversed(list(enumerate(built))[current + 1:])]
                result.path = Path(path)
                return result
        except CadError:
            raise
        except Exception as exc:
            raise CadError("Nie można otworzyć projektu. Plik może być uszkodzony lub mieć inny format.") from exc
