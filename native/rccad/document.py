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
        self.info = {'label': 'Początek', 'icon': 'start'}
        self.constraints = []   # więzy wymiarów między szkicami: {a, ai, b, bi, k} - wymiar bi szkicu b = k * wymiar ai szkicu a
        self.variables = {}     # zmienne projektu: nazwa -> wyrażenie (liczone po kolei), używane w polach {'expr': ...}
        self.snapshots = {}   # warianty: nazwa -> dict(states, current, constraints, variables) - pełne osie czasu zapisane w projekcie
        self.backup = None   # poprzednia oś czasu sprzed edycji kroku historii (do cofnięcia edycji)
        self.path: Path | None = None
        self._revision = 0
        self._saved_revision = 0
        self._next_revision = 1
        self.pending_label = None
        self.pending_icon = None
        self.pending_op = None
        self._brep_cache = {}      # id(kształt) -> (kształt, bajty BREP): kolejne zapisy i autozapisy nie eksportują ponownie niezmienionej geometrii
        self._mesh_cache = {}      # id(kształt) -> (kształt, siatka): siatki wyświetlania liczone leniwie, tylko dla bieżącego stanu
        self.keep_future = False   # po przeskoku w historii nowa operacja wstawia się w środek, a późniejsze kroki są przeliczane
        self.deferred = None       # (stan sprzed wstawienia, późniejsze kroki) do przeliczenia w tle

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

    @property
    def label(self):
        return self.info.get('label', '')

    @staticmethod
    def _auto_label(before, after):
        old, new = {b.id: b for b in before}, {b.id: b for b in after}
        added = [b for i, b in new.items() if i not in old]
        removed = [b for i, b in old.items() if i not in new]
        changed = [b for i, b in new.items() if i in old and (old[i].shape is not b.shape or old[i].visible != b.visible or old[i].name != b.name)]
        more = lambda xs: f' (+{len(xs) - 1})' if len(xs) > 1 else ''
        if added and not removed:
            return f'Dodano: {added[0].name}' + more(added), ('sketch' if added[0].kind == 'sketch' else 'file')
        if removed and not added:
            return f'Usunięto: {removed[0].name}' + more(removed), 'trash'
        if changed:
            return f'Zmieniono: {changed[0].name}' + more(changed), 'sketch' if changed[0].kind == 'sketch' else 'move'
        return 'Zmiana', 'move'

    def commit(self, bodies, label=None, icon=None, op=None):
        bodies = tuple(bodies)
        if len({b.id for b in bodies}) != len(bodies):
            raise CadError("Powtórzony identyfikator obiektu.")
        auto_label, auto_icon = self._auto_label(self.bodies, bodies)
        info = {'label': label or self.pending_label or auto_label, 'icon': icon or self.pending_icon or (auto_icon if not (label or self.pending_label) else 'move')}
        op = op or self.pending_op
        if op:
            info['op'] = op
        self._undo.append((self.bodies, self._revision, self.info))
        self._undo = self._undo[-999:]
        if self.keep_future and self._redo:
            self.deferred = (self.bodies, [(e[0], e[2]) for e in reversed(self._redo)])
        self.keep_future = False
        self._redo.clear()
        self.info = info
        self.pending_label = self.pending_icon = self.pending_op = None
        self.bodies = bodies
        self._revision = self._next_revision
        self._next_revision += 1

    def meshed(self, bodies):
        """Bryły z uzupełnionymi siatkami (stany historii wczytane z pliku nie mają siatek, dopóki nie zostaną pokazane)."""
        if all(b.mesh is not None for b in bodies):
            return tuple(bodies)
        out = []
        for b in bodies:
            if b.mesh is None:
                hit = self._mesh_cache.get(id(b.shape))
                if hit is None or hit[0] is not b.shape:
                    if len(self._mesh_cache) > 600:
                        self._mesh_cache.clear()
                    valid(b.shape, b.kind == 'solid')
                    hit = self._mesh_cache[id(b.shape)] = (b.shape, display_mesh(b.shape))
                b = replace(b, mesh=hit[1])
            out.append(b)
        return tuple(out)

    def append_states(self, tail):
        """Dokleja przeliczone późniejsze kroki za bieżący i ustawia widok na ostatnim."""
        states = self.states() + list(tail)
        self._set_states(states, len(states) - 1)

    def undo(self):
        self.keep_future = False
        if self._undo:
            self._redo.append((self.bodies, self._revision, self.info))
            self.bodies, self._revision, self.info = self._undo.pop()
            self.bodies = self.meshed(self.bodies)

    def redo(self):
        self.keep_future = False
        if self._redo:
            self._undo.append((self.bodies, self._revision, self.info))
            self.bodies, self._revision, self.info = self._redo.pop()
            self.bodies = self.meshed(self.bodies)

    # ---------- historia: oś czasu stanów (niezmienne bryły, więc przeskok jest natychmiastowy) ----------
    def timeline(self):
        """(etykiety, indeks bieżącego): stany od najstarszego do najnowszego, razem z cofniętymi (redo)."""
        infos, current = self.infos()
        return [i.get('label', '') for i in infos], current

    def infos(self):
        return [e[2] for e in self._undo] + [self.info] + [e[2] for e in reversed(self._redo)], len(self._undo)

    def states(self):
        """Pełna oś czasu: lista (bryły, info) od pierwszego kroku."""
        return [(e[0], e[2]) for e in self._undo] + [(self.bodies, self.info)] + [(e[0], e[2]) for e in reversed(self._redo)]

    def rewrite(self, states, current, constraints=None, variables=None):
        """Podmienia całą oś czasu (po edycji kroku i przeliczeniu następnych); poprzednią (z więzami) zachowuje do cofnięcia edycji."""
        self.backup = (self.states(), len(self._undo), list(self.constraints), dict(self.variables))
        if constraints is not None:
            self.constraints = list(constraints)
        if variables is not None:
            self.variables = dict(variables)
        self._set_states(states, current)

    def set_info(self, index, **values):
        """Podpis / grupa kroku (bez zmiany geometrii i bez kopii zapasowej)."""
        states = self.states()
        bodies, info = states[index]
        info = dict(info)
        for key, value in values.items():
            if value:
                info[key] = value
            else:
                info.pop(key, None)
        states[index] = (bodies, info)
        self._set_states(states, len(self._undo))

    def snapshot(self, name):
        """Zapamiętuje całą historię pod nazwą (wariant); bryły są niezmienne, więc kopia nic nie kosztuje."""
        self.snapshots[name] = dict(states=self.states(), current=len(self._undo), constraints=list(self.constraints), variables=dict(self.variables))
        self._revision = self._next_revision
        self._next_revision += 1

    def restore_snapshot(self, name):
        snap = self.snapshots[name]
        self.backup = (self.states(), len(self._undo), list(self.constraints), dict(self.variables))
        self.constraints, self.variables = list(snap['constraints']), dict(snap['variables'])
        self._set_states(list(snap['states']), snap['current'])

    def delete_snapshot(self, name):
        if self.snapshots.pop(name, None) is not None:
            self._revision = self._next_revision
            self._next_revision += 1

    def restore_backup(self):
        if self.backup:
            states, current, constraints, variables = self.backup
            self.backup = None
            self.constraints, self.variables = constraints, variables
            self._set_states(states, current)

    def _set_states(self, states, current):
        revisions = list(range(self._next_revision, self._next_revision + len(states)))
        self._next_revision += len(states)
        self._undo = [(b, revisions[i], inf) for i, (b, inf) in enumerate(states[:current])]
        self.bodies, self.info = states[current]
        self.bodies = self.meshed(self.bodies)
        self._redo = [(b, revisions[i], inf) for i, (b, inf) in reversed(list(enumerate(states))[current + 1:])]
        self._revision = revisions[current]
        self.keep_future, self.deferred = False, None

    def goto(self, index):
        labels, current = self.timeline()
        index = max(0, min(index, len(labels) - 1))
        while current > index:
            self.undo(); current -= 1
        while current < index:
            self.redo(); current += 1
        self.keep_future = index < len(labels) - 1

    @staticmethod
    def _entry(body, shape_index):
        entry = dict(id=body.id, name=body.name, kind=body.kind, plane=body.plane, visible=body.visible, shape=shape_index)
        if body.meta:
            entry['meta'] = body.meta
        if isinstance(body.plane, Frame):
            entry['plane'] = 'CUSTOM'
            entry['frame'] = body.plane.to_dict()
        return entry

    def _brep_bytes(self, shape, scratch):
        hit = self._brep_cache.get(id(shape))
        if hit is not None and hit[0] is shape:
            return hit[1]
        cq.exporters.export(shape, str(scratch), exportType="BREP")
        data = scratch.read_bytes()
        scratch.unlink()
        if len(self._brep_cache) > 3000:
            self._brep_cache.clear()
        self._brep_cache[id(shape)] = (shape, data)
        return data

    def save(self, path, mark=True):
        """Zapisuje cały projekt razem z historią: każda unikalna geometria raz (BREP), a kroki jako listy odwołań do niej."""
        path = Path(path)
        states = self.states()
        older = self._undo
        shapes, index = [], {}
        manifest = {"app": "RCCAD_DESKTOP", "version": 2, "units": "mm", "shapes": [], "states": [], "current": len(older), "constraints": self.constraints, "variables": self.variables}
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".rccad-", suffix=".tmp", dir=path.parent)
            os.close(fd)
            with tempfile.TemporaryDirectory(prefix="rccad-brep-") as work, ZipFile(temp_path, "w", ZIP_DEFLATED) as archive:
                def emit(timeline):
                    out = []
                    for bodies, info in timeline:
                        entries = []
                        for body in bodies:
                            key = id(body.shape)
                            if key not in index:
                                index[key] = len(shapes)
                                shapes.append(body.shape)
                                data = self._brep_bytes(body.shape, Path(work) / f"s{index[key]}.brep")
                                archive.writestr(f"shapes/{index[key]}.brep", data)
                                manifest['shapes'].append(f"shapes/{index[key]}.brep")
                            entries.append(self._entry(body, index[key]))
                        out.append(dict(label=info.get('label', ''), icon=info.get('icon', 'move'), op=info.get('op'), stale=bool(info.get('stale')), off=bool(info.get('off')), note=info.get('note'), group=info.get('group'), why=info.get('why'), bodies=entries))
                    return out
                manifest['states'] = emit(states)
                manifest['snapshots'] = [dict(name=name, current=snap['current'], constraints=snap['constraints'], variables=snap['variables'], states=emit(snap['states']))
                                         for name, snap in self.snapshots.items()]
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            os.replace(temp_path, path)
            if mark:      # autozapis (mark=False) nie zmienia ścieżki projektu ani stanu „zapisany”
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
                if not isinstance(files, list) or not isinstance(states, list) or not states or len(states) > 1100 or not isinstance(current, int) or not 0 <= current < len(states):
                    raise CadError("Nieprawidłowa struktura projektu.")
                cache = {}      # numer geometrii -> (kształt, siatka): wczytywane i siatkowane raz, współdzielone przez wszystkie kroki

                def geometry(number, kind):
                    if not isinstance(number, int) or not 0 <= number < len(files) or files[number] != f'shapes/{number}.brep':
                        raise CadError("Nieprawidłowa struktura projektu.")
                    if number not in cache:
                        source = Path(work) / f'{number}.brep'
                        source.write_bytes(archive.read(files[number]))
                        shape = cq.importers.importBrep(str(source)).val()
                        if shape is None or shape.wrapped.IsNull() or (kind == 'solid' and not shape.Solids()):      # pełna walidacja (isValid) przy pierwszym pokazaniu stanu
                            raise CadError("Nieprawidłowa geometria w projekcie.")
                        cache[number] = (shape, None)
                    return cache[number]

                def parse(state_list):
                  built = []
                  for state in state_list:
                      ids, bodies = set(), []
                      for item in state['bodies']:
                          shape, mesh = geometry(item['shape'], item.get('kind', 'solid'))
                          body = cls._parse_body(item, shape, mesh)
                          if body.id in ids:
                              raise CadError("Nieprawidłowa struktura projektu.")
                          ids.add(body.id)
                          bodies.append(body)
                      info = {'label': str(state.get('label', 'Zmiana')), 'icon': str(state.get('icon', 'move'))}
                      if isinstance(state.get('op'), dict):
                          info['op'] = state['op']
                      if state.get('stale'):
                          info['stale'] = True
                      if state.get('off'):
                          info['off'] = True
                      for key in ('note', 'group', 'why'):
                          if isinstance(state.get(key), str) and state[key]:
                              info[key] = state[key][:80]
                      built.append((tuple(bodies), info))
                  return built

                built = parse(states)
                def parse_constraints(cons):
                    return [dict(b=str(c['b']), bi=int(c['bi']), expr=str(c['expr'])) if 'expr' in c else
                            dict(a=str(c['a']), ai=int(c['ai']), b=str(c['b']), bi=int(c['bi']), k=float(c.get('k', 1.0))) for c in cons if isinstance(c, dict)] if isinstance(cons, list) else []

                def parse_variables(variables):
                    return {str(k)[:40]: str(v)[:200] for k, v in variables.items()} if isinstance(variables, dict) else {}

                result.constraints = parse_constraints(manifest.get('constraints', []))
                result.variables = parse_variables(manifest.get('variables', {}))
                for snap in (manifest.get('snapshots') or [])[:30]:
                    if not isinstance(snap, dict) or not isinstance(snap.get('states'), list) or not 0 < len(snap['states']) <= 1100:
                        continue
                    timeline = parse(snap['states'])
                    at = snap.get('current')
                    result.snapshots[str(snap.get('name', 'Wariant'))[:60]] = dict(
                        states=timeline, current=at if isinstance(at, int) and 0 <= at < len(timeline) else len(timeline) - 1,
                        constraints=parse_constraints(snap.get('constraints', [])), variables=parse_variables(snap.get('variables', {})))
                result._next_revision = 1
                revisions = list(range(1, len(built) + 1))
                result._next_revision = len(built) + 1
                result._undo = [(b, revisions[i], inf) for i, (b, inf) in enumerate(built[:current])]
                result.bodies, result.info = built[current]
                result.bodies = result.meshed(result.bodies)
                result._revision = result._saved_revision = revisions[current]
                result._redo = [(b, revisions[i], inf) for i, (b, inf) in reversed(list(enumerate(built))[current + 1:])]
                result.path = Path(path)
                return result
        except CadError:
            raise
        except Exception as exc:
            raise CadError("Nie można otworzyć projektu. Plik może być uszkodzony lub mieć inny format.") from exc
