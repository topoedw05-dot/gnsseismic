# -*- coding: utf-8 -*-
"""
sourcelink_parser.py
---------------------
Lector del CSV que exporta SourceLink (sistema de control de vibradores
sísmicos, "vibroseis") con la posición GNSS de cada disparo de cada
vibrador -- por ejemplo `PSS_2026_02_19_07_19_14.csv`, un reporte de
producción de 2010 disparos de 10 vibradores en 14 líneas
(Neuquén, Argentina). Es el archivo de campo que alimenta POSTPLOT en
levantamientos de fuentes sísmicas (vibros) posicionadas con GNSS.

Formato -- ANALIZADO contra el archivo real aportado por el usuario:

  * CSV con coma, una fila de encabezado y una fila por disparo ("Shot
    ID"). El encabezado termina con una coma de más (una columna final
    sin nombre y sin datos) -- se ignora. 62 columnas con nombre:
    identificación del disparo (Shot ID, File Num, Line, Station, Unit
    ID...), fecha/hora (Date/Time locales, TB Local Time, TB UTC Time),
    control del vibro (fase, fuerza, THD, viscosidad, rigidez...:
    calidad del barrido, no se usan acá) y la posición GNSS del vibro
    (Lat, Lon, Altitude, Sats, PDOP, HDOP, VDOP, Quality, X, Y).

  * Line / Station: número de línea y de estación en el diseño, como
    texto decimal ("5127.00"/"1881.00"). Aquí se arma el nombre del
    punto como Línea+Estación sin separador ("51271881"), la convención
    de nombres numéricos del plugin (Track = línea, Bin = estación), y
    Track/Bin se toman directamente de estas dos columnas (no por la
    heurística de "primeros N dígitos").

  * Unit ID: número del VIBRADOR que hizo el disparo (10 distintos en el
    archivo de referencia, 1..10). Se sube a POSTPLOT como `Surveyor`
    de cada punto (pedido explícito del usuario) -- por eso, para este
    formato, el campo "Surveyor" por archivo de la interfaz no aplica
    (cada fila trae el suyo).

  * Void: la columna dice "Void" en un disparo ANULADO (27 de 2010 en el
    archivo de referencia; casi siempre seguido de una repetición del
    mismo Line/Station). Los anulados se OMITEN. Quedan, en cambio, los
    repetidos NO anulados (3 pares Line/Station en el archivo de
    referencia): son disparos válidos distintos, y el plugin ya avisa
    de nombres repetidos como con cualquier otro formato.

  * Lat/Lon: grados decimales (WGS84), con signo (-37.08, -69.34).
    VERIFICADO con pyproj: transformar Lat/Lon a POSGAR 94 / Argentina
    faja 2 (EPSG:22182) reproduce las columnas X/Y del archivo con una
    diferencia máxima de 0.06 mm en los 2010 puntos -- o sea, X/Y son
    simplemente la proyección de Lat/Lon y no aportan información nueva
    (el plugin recalcula las coordenadas planas con el CRS de trabajo
    del proyecto, así que X/Y se ignoran).

  * Altitude y GPS Altitude son idénticas en las 2010 filas. NO se pudo
    verificar por sí sola si es altura elipsoidal u ortométrica (el
    archivo no lo declara): se sube tal cual como altura del punto.

  * Quality: "RTK-Fix" en las 2010 filas. Se usa como estado de la
    solución (modo de levantamiento Fase/3 si dice fix, Flotante/4 si
    dice float, igual que CHCNav/SurPad).

  * Comment: texto libre del operador (5 de 2010, p.ej. "Desplazada 5097
    1994": punto desplazado de su estación teórica) -- se guarda como
    comentario del punto.

  * Hora: "TB Local Time"/"TB UTC Time" ("2026/02/19 08:25:08.488000",
    local = UTC-3 en el archivo de referencia) dan fecha y hora absolutas
    de cada disparo -- se guardan como Survey_Time_Local/GMT
    ("AAAA-MM-DD HH:MM:SS", sin fracciones) y de la fecha local sale el
    Julian Date (año + día del año).

Devuelve `SourceLinkFile`/`SourceLinkPoint`. Lógica pura, sin QGIS/PyQt.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

try:  # pragma: no cover - depende de si se importa como paquete o suelto
    from .chcnav_parser import leer_texto_con_fallback
except ImportError:
    from chcnav_parser import leer_texto_con_fallback

_REQUIRED = ("Shot ID", "Line", "Station", "Unit ID", "Lat", "Lon")


@dataclass
class SourceLinkPoint:
    name: str  # Línea + Estación, ej. "51271881"
    lat: float
    lon: float
    height: float
    line_no: int  # número de línea del archivo (1 = encabezado)
    shot_id: str
    track: str  # Line como entero en texto
    bin: str  # Station como entero en texto
    unit_id: str  # número del vibrador -> Surveyor
    tipo: str = "SO"  # punto de fuente (vibro)
    quality: Optional[str] = None
    n_sats: Optional[int] = None
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    comment: str = ""
    survey_time_local: Optional[str] = None
    survey_time_gmt: Optional[str] = None
    julian_date_local: Optional[str] = None  # AAAADDD
    is_base: bool = False  # nunca hay bases en este formato (misma interfaz que ChcnavPoint)

    @property
    def surveyor(self) -> str:
        return self.unit_id


@dataclass
class SourceLinkFile:
    path: str
    points: List[SourceLinkPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    n_void: int = 0

    @property
    def n_points(self) -> int:
        return len(self.points)

    @property
    def units(self) -> List[str]:
        vistos = sorted({p.unit_id for p in self.points}, key=lambda u: (len(u), u))
        return vistos

    def duplicated_names(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.points:
            counts[p.name] = counts.get(p.name, 0) + 1
        return {k: v for k, v in counts.items() if v > 1}


def looks_like_sourcelink(text: str) -> bool:
    """True si la primera línea no vacía es un encabezado de SourceLink
    (trae "Shot ID", "Unit ID", "Line", "Station", "Lat" y "Lon")."""
    if not text:
        return False
    for raw in text.splitlines():
        if raw.strip():
            cols = {c.strip() for c in raw.split(",")}
            return all(c in cols for c in _REQUIRED)
    return False


def _float(txt: Optional[str]) -> Optional[float]:
    if txt is None:
        return None
    txt = txt.strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _int_text(txt: Optional[str]) -> str:
    """"5127.00" -> "5127"; un valor no numérico se devuelve recortado."""
    v = _float(txt)
    if v is None:
        return (txt or "").strip()
    return str(int(round(v)))


def _parse_dt(txt: Optional[str]) -> Optional[datetime]:
    """"2026/02/19 08:25:08.488000" -> datetime (descarta las fracciones)."""
    if not txt:
        return None
    base = txt.strip().split(".", 1)[0]
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(base, fmt)
        except ValueError:
            continue
    return None


def _parse_date_time(date_txt: Optional[str], time_txt: Optional[str]) -> Optional[datetime]:
    """Respaldo: "MM/DD/AAAA" + "HH:MM:SS" (columnas Date/Time)."""
    if not date_txt or not time_txt:
        return None
    try:
        return datetime.strptime(f"{date_txt.strip()} {time_txt.strip()}", "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None


def parse_sourcelink_text(text: str, path: str = "") -> SourceLinkFile:
    sf = SourceLinkFile(path=path)
    reader = csv.reader(io.StringIO(text))
    header: Optional[List[str]] = None
    idx: Dict[str, int] = {}
    n_sin_coords = 0
    for row in reader:
        if not row or not any(c.strip() for c in row):
            continue
        if header is None:
            header = [c.strip() for c in row]
            idx = {name: i for i, name in enumerate(header) if name}
            faltan = [c for c in _REQUIRED if c not in idx]
            if faltan:
                raise ValueError(
                    "El archivo no parece un CSV de SourceLink (faltan las columnas: "
                    + ", ".join(faltan) + ")."
                )
            continue

        def get(col: str) -> str:
            i = idx.get(col)
            return row[i].strip() if i is not None and i < len(row) else ""

        if get("Void").lower() == "void":
            sf.n_void += 1
            continue
        lat, lon = _float(get("Lat")), _float(get("Lon"))
        height = _float(get("Altitude"))
        if height is None:
            height = _float(get("GPS Altitude"))
        if lat is None or lon is None or height is None:
            n_sin_coords += 1
            continue
        track, bin_ = _int_text(get("Line")), _int_text(get("Station"))
        dt_local = _parse_dt(get("TB Local Time")) or _parse_date_time(get("Date"), get("Time"))
        dt_gmt = _parse_dt(get("TB UTC Time"))
        julian = None
        if dt_local is not None:
            julian = f"{dt_local.year}{dt_local.timetuple().tm_yday:03d}"
        n_sats = _float(get("Sats"))
        sf.points.append(SourceLinkPoint(
            name=f"{track}{bin_}", lat=lat, lon=lon, height=height,
            line_no=reader.line_num, shot_id=get("Shot ID"),
            track=track, bin=bin_, unit_id=_int_text(get("Unit ID")),
            quality=get("Quality") or None,
            n_sats=int(round(n_sats)) if n_sats is not None else None,
            pdop=_float(get("PDOP")), hdop=_float(get("HDOP")), vdop=_float(get("VDOP")),
            comment=get("Comment"),
            survey_time_local=dt_local.strftime("%Y-%m-%d %H:%M:%S") if dt_local else None,
            survey_time_gmt=dt_gmt.strftime("%Y-%m-%d %H:%M:%S") if dt_gmt else None,
            julian_date_local=julian,
        ))

    if header is None:
        raise ValueError("El archivo está vacío.")
    if sf.n_void:
        sf.warnings.append(f"{sf.n_void} disparo(s) anulado(s) (Void) omitido(s).")
    if n_sin_coords:
        sf.warnings.append(f"{n_sin_coords} disparo(s) sin coordenadas válidas omitido(s).")
    sin_unit = sum(1 for p in sf.points if not p.unit_id)
    if sin_unit:
        sf.warnings.append(f"{sin_unit} disparo(s) sin Unit ID: su Surveyor quedará vacío.")
    dup = sf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        sf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) en el archivo, disparos válidos "
            f"repetidos en la misma estación (ej: {ejemplos})."
        )
    return sf


def parse_sourcelink_file(path: str, encoding: Optional[str] = None) -> SourceLinkFile:
    text = leer_texto_con_fallback(path, encoding)
    if not looks_like_sourcelink(text):
        raise ValueError(
            "El archivo no parece un CSV de SourceLink (se esperaba un encabezado con "
            "Shot ID, Line, Station, Unit ID, Lat y Lon)."
        )
    return parse_sourcelink_text(text, path=path)
