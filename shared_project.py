# -*- coding: utf-8 -*-
"""
shared_project.py
------------------
Lógica (sin QGIS/PyQt) del MODO COMPARTIDO opcional de un proyecto:
varias personas, en lugares distintos (la oficina de campo en la
Patagonia, la oficina de Buenos Aires...), comparten la carpeta del
proyecto a través de una carpeta sincronizada -- p.ej. Google Drive para
escritorio -- sin pisarse y sin dañar la base de datos SQLite.

Reglas (decididas con el usuario):

  * UN SOLO EDITOR a la vez; el resto abre el proyecto en SOLO LECTURA y
    puede ver el avance. Un lector puede "tomar el control" (si el editor
    terminó o quedó colgado); el editor anterior pasa a solo lectura.
  * El editor NO escribe sobre el archivo sincronizado: trabaja en una
    COPIA LOCAL y la PUBLICA en la carpeta compartida (copia completa,
    consistente, con reemplazo atómico) -- así la sincronización nunca ve
    un archivo a medio escribir y quienes miran siempre reciben una
    versión completa (la última publicada). Los lectores trabajan sobre
    una copia local de esa versión.
  * Un archivo de BLOQUEO junto a la base (`<base>.sqlite.lock.json`) dice
    quién edita: sesión, usuario, equipo, desde cuándo y un "latido"
    (`heartbeat`) que el editor renueva cada tanto. Un latido viejo
    (`STALE_SECONDS`) marca una sesión probablemente caída. Es un
    bloqueo AVISO: la sincronización de Drive tarda (y en campo puede
    estar sin internet), así que dos personas pueden verse "libres" por un
    momento; el plugin lo detecta en el siguiente latido y el editor que
    pierde el control conserva su copia local como respaldo.
  * Un archivo MARCADOR (`<base>.sqlite.shared.json`) marca el proyecto
    como compartido; sin él, todo funciona como siempre (opcional).

Nada de esto se usa en un proyecto que no se haya compartido.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Tuple

SUFFIX_MARKER = ".shared.json"
SUFFIX_LOCK = ".lock.json"

# Un latido más viejo que esto = sesión probablemente caída (el editor lo
# renueva cada ~30 s mientras el proyecto está abierto; el margen cubre la
# demora de sincronización de Drive).
STALE_SECONDS = 20 * 60

MODE_EDITOR = "editor"
MODE_VIEWER = "viewer"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(txt: str) -> Optional[datetime]:
    try:
        return datetime.strptime(txt, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def iso_to_local_text(txt: str) -> str:
    """"2026-10-04T16:25:35Z" -> "2026-10-04 13:25" en hora local del equipo."""
    dt = _parse_iso(txt)
    if dt is None:
        return txt or ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def marker_path(db_path: str) -> str:
    return db_path + SUFFIX_MARKER


def lock_path(db_path: str) -> str:
    return db_path + SUFFIX_LOCK


def is_shared(db_path: str) -> bool:
    return os.path.isfile(marker_path(db_path))


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    _replace_with_retry(tmp, path)


def _replace_with_retry(src: str, dst: str, tries: int = 8, wait: float = 0.4) -> None:
    """`os.replace` con reintentos: en Windows falla con PermissionError si
    otro proceso (el cliente de Drive, un lector copiando el archivo)
    lo tiene abierto en ese instante."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def enable_shared(db_path: str) -> None:
    _atomic_write_json(marker_path(db_path), {
        "shared": True, "created_by": _identity()[0], "created": _now_iso(),
    })


def disable_shared(db_path: str) -> None:
    for p in (marker_path(db_path),):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Bloqueo
# ---------------------------------------------------------------------------

def _identity() -> Tuple[str, str]:
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - sin usuario en el entorno
        user = "?"
    try:
        host = socket.gethostname()
    except Exception:  # pragma: no cover
        host = "?"
    return user, host


@dataclass
class LockInfo:
    session: str
    user: str
    host: str
    since: str
    heartbeat: str
    plugin_version: str = ""

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        hb = _parse_iso(self.heartbeat)
        if hb is None:
            return float("inf")
        now = now or datetime.now(timezone.utc)
        return (now - hb).total_seconds()

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        return self.age_seconds(now) > STALE_SECONDS

    def who(self) -> str:
        return f"{self.user}@{self.host}"


def new_session_id() -> str:
    return uuid.uuid4().hex


def read_lock(db_path: str) -> Optional[LockInfo]:
    """El bloqueo actual, o None si no hay (o está ilegible/a medio
    sincronizar -- se trata como libre, igual que ausente)."""
    try:
        with open(lock_path(db_path), "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return LockInfo(
            session=str(d["session"]), user=str(d.get("user", "?")), host=str(d.get("host", "?")),
            since=str(d.get("since", "")), heartbeat=str(d.get("heartbeat", "")),
            plugin_version=str(d.get("plugin_version", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_lock(db_path: str, info: LockInfo) -> None:
    _atomic_write_json(lock_path(db_path), asdict(info))


def acquire_lock(db_path: str, session: str, plugin_version: str = "", force: bool = False) -> Tuple[bool, Optional[LockInfo]]:
    """Intenta tomar el bloqueo. Devuelve (True, None) si quedó a nombre de
    `session`; (False, bloqueo_ajeno) si lo tiene otra sesión y no se
    pidió `force` (tomar el control)."""
    actual = read_lock(db_path)
    if actual is not None and actual.session != session and not force:
        return False, actual
    user, host = _identity()
    now = _now_iso()
    since = actual.since if (actual is not None and actual.session == session) else now
    _write_lock(db_path, LockInfo(session, user, host, since, now, plugin_version))
    return True, None


def renew_lock(db_path: str, session: str) -> bool:
    """Latido del editor. False si el bloqueo ya es de OTRA sesión (se
    perdió el control: alguien lo tomó); si el archivo desapareció se
    vuelve a escribir (alguien lo borró a mano) y devuelve True."""
    actual = read_lock(db_path)
    if actual is not None and actual.session != session:
        return False
    user, host = _identity()
    now = _now_iso()
    since = actual.since if actual is not None else now
    version = actual.plugin_version if actual is not None else ""
    _write_lock(db_path, LockInfo(session, user, host, since, now, version))
    return True


def release_lock(db_path: str, session: str) -> None:
    """Libera el bloqueo sólo si es de esta sesión."""
    actual = read_lock(db_path)
    if actual is not None and actual.session == session:
        try:
            os.remove(lock_path(db_path))
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Copias de trabajo, publicación y versión publicada
# ---------------------------------------------------------------------------

def work_dir(local_root: str, db_path: str) -> str:
    """Carpeta local propia de un proyecto compartido (distinta para cada
    ruta publicada, aunque dos proyectos se llamen igual)."""
    clave = hashlib.sha256(os.path.normcase(os.path.abspath(db_path)).encode("utf-8")).hexdigest()[:10]
    nombre = os.path.splitext(os.path.basename(db_path))[0]
    carpeta = os.path.join(local_root, f"{nombre}_{clave}")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def editor_copy_path(local_root: str, db_path: str) -> str:
    return os.path.join(work_dir(local_root, db_path), "editor.sqlite")


def viewer_copy_path(local_root: str, db_path: str) -> str:
    return os.path.join(work_dir(local_root, db_path), "viewer.sqlite")


def published_signature(db_path: str) -> Optional[Tuple[int, int]]:
    """(mtime_ns, tamaño) de la versión publicada, o None si no existe."""
    try:
        st = os.stat(db_path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def published_mtime_text(db_path: str) -> str:
    try:
        return datetime.fromtimestamp(os.stat(db_path).st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


def copy_atomic(src: str, dst: str) -> None:
    """Copia `src` a `dst` sin dejar nunca un `dst` a medias (copia a un
    temporal junto a `dst` y lo reemplaza)."""
    tmp = f"{dst}.{os.getpid()}.copy"
    shutil.copyfile(src, tmp)
    _replace_with_retry(tmp, dst)


def snapshot_published(db_path: str, dest: str) -> None:
    """Copia local de la versión publicada (para editar o para mirar)."""
    for ext in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(dest + ext)
        except FileNotFoundError:
            pass
    copy_atomic(db_path, dest)


def publish(conn: sqlite3.Connection, db_path: str, scratch_dir: str) -> None:
    """Publica la base abierta en `conn` (la copia local del editor) en
    `db_path` (la carpeta compartida): confirma, hace una copia completa y
    consistente con la API de respaldo de SQLite a un temporal LOCAL, la
    copia junto al destino y la deja en su lugar con un reemplazo
    atómico. Si algo falla antes del reemplazo, la versión publicada
    anterior queda intacta."""
    conn.commit()
    os.makedirs(scratch_dir, exist_ok=True)
    local_tmp = os.path.join(scratch_dir, "publish.tmp.sqlite")
    try:
        os.remove(local_tmp)
    except FileNotFoundError:
        pass
    with closing(sqlite3.connect(local_tmp)) as dst:
        conn.backup(dst)
    remote_tmp = f"{db_path}.{os.getpid()}.publish"
    try:
        shutil.copyfile(local_tmp, remote_tmp)
        _replace_with_retry(remote_tmp, db_path)
    finally:
        for p in (remote_tmp, local_tmp):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass


@dataclass
class SharedSession:
    """Estado de la sesión compartida abierta en la ventana."""
    db_path: str  # versión PUBLICADA (carpeta compartida)
    mode: str  # MODE_EDITOR / MODE_VIEWER
    session_id: str
    local_path: str  # copia local sobre la que trabaja la conexión
    baseline_changes: int = 0  # conn.total_changes en la última publicación (editor)
    signature: Optional[Tuple[int, int]] = None  # versión publicada que se está viendo/editando
    remote_newer: bool = False  # (lector) hay una versión publicada más nueva
    lock_seen: Optional[LockInfo] = None  # (lector) bloqueo visto en la última revisión
    last_publish_text: str = ""
    last_error: str = ""
