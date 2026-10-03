# -*- coding: utf-8 -*-
"""
hitarget_parser.py
-------------------
Lector del CSV de puntos que exporta el software de campo de Hi-Target
(HiSurveyor / Hi-Survey), primer formato "de marca" agregado a la
sección "Importar datos de campo" además del .dc de Trimble (v2.8.0).

A diferencia del .dc (formato de ancho de campo, sin separador), este es
un CSV normal, delimitado por comas, con un encabezado fijo observado en
un archivo real de exportación:

    id,Nombre,N,E,Z,B,L,H,AntH,σN,σE,σZ,N Promedios,Estado,
    InicioTiempo Loc,FinTiempo Loc,InicioUTC,FinUTC,Desc,Edad,Sats,
    Sats en común,PDOP,Elevación(°),Nombre VRS,Base B,Base L,
    H Base(Centro Fase),Estación,Incl. Ang.,Incl. Azi

De ahí se usan sólo las columnas necesarias para importar el punto,
IGUAL que se usa un registro KI/SO de un .dc -- nombre + coordenadas
GEOGRÁFICAS (B=latitud, L=longitud, en formato DMS con símbolos °′″) +
altura elipsoidal (H). Deliberadamente NO se usan las columnas N/E/Z
(la grilla local propia del receptor, calibrada en campo por el
usuario con SU PROPIO sistema de coordenadas): no hay forma de saber
desde este archivo en qué CRS están esas dos columnas, así que usarlas
arriesgaría subir coordenadas equivocadas. B/L/H, en cambio, son
geográficas (mismo tipo de dato que ya entrega un .dc), así que se
puede reutilizar tal cual el mismo mecanismo de importación (geoide
opcional, comparación contra PREPLOT, etc.).

A favor de este formato, sí trae de fábrica dos datos que el .dc NO
trae (donde el usuario los tiene que escribir a mano en la
previsualización): la altura de antena (columna AntH) y un comentario
de campo (columna Desc) -- se usan como valor inicial editable de esos
mismos campos.

Las filas con Desc == "set_base" son la ocupación de la base (no un
punto levantado): se leen igual (por si el usuario las quiere revisar
o subir de todas formas) pero se marcan con `is_base=True` para que la
interfaz las deje SIN incluir por defecto.

Este módulo no depende de QGIS ni de PyQt: es lógica pura, igual que
`dc_parser.py`, para poder probarlo de forma aislada.
"""

import csv
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Un ángulo DMS como lo escribe Hi-Target: signo opcional, grados,
# minutos y segundos decimales, con los símbolos °/′ (o el apóstrofo
# recto)/″ (o comilla recta). Ejemplos reales: " 04°36′58.90211″",
# " -74°21′08.62095″", " 00°00′00.00000″".
_DMS_RE = re.compile(r"^\s*(-?)\s*(\d+)\s*°\s*(\d+)\s*[′']\s*([\d.]+)\s*[″\"]\s*$")

# El archivo real analizado también trae "InicioTiempo Loc"/"FinTiempo
# Loc" (y su par en UTC) con este formato -- NO es una hora de reloj
# real (no trae fecha ni hora completa), sino un contador de minutos:
# segundos relativo al inicio de la sesión del receptor (crece de forma
# monótona a lo largo del archivo, p.ej. "01:42.0" al principio y
# "23:10.0" más adelante) -- por eso sólo se usa para calcular la
# DURACIÓN de la ocupación de cada punto (Fin - Inicio), nunca como una
# fecha/hora real.
_MINSEC_RE = re.compile(r"^\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*$")

# Radio medio de la Tierra (m), suficiente para estimar la distancia a
# la base (línea base RTK) a partir de sus coordenadas geográficas --
# no se usa para nada que se suba como coordenada del punto en sí.
_EARTH_RADIUS_M = 6371000.0

# Columnas que debe tener el encabezado para reconocer el archivo como
# un CSV de Hi-Target (no hace falta que estén en este orden ni que no
# haya otras columnas además de éstas).
REQUIRED_HEADERS = ("Nombre", "N", "E", "Z", "B", "L", "H", "AntH", "Estado")

# Distancia máxima (m) para considerar que las coordenadas de "Base
# B"/"Base L" de una fila corresponden a una fila is_base concreta del
# mismo archivo (y así poder ponerle nombre a `base_station_name`, en
# vez de dejar sólo la distancia calculada).
_BASE_MATCH_TOLERANCE_M = 2.0


def parse_dms(text: Optional[str]) -> Optional[float]:
    """Convierte un ángulo DMS con símbolos °′″ (como usa Hi-Target para
    B/L) a grados decimales. Devuelve None si el texto no matchea el
    patrón esperado (en vez de levantar una excepción), para que el
    llamador decida si eso invalida la fila o no."""
    if text is None:
        return None
    m = _DMS_RE.match(text)
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" else 1.0
    deg = float(m.group(2))
    minutes = float(m.group(3))
    seconds = float(m.group(4))
    return sign * (deg + minutes / 60.0 + seconds / 3600.0)


def _parse_float_optional(text) -> Optional[float]:
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int_optional(text) -> Optional[int]:
    val = _parse_float_optional(text)
    if val is None:
        return None
    try:
        return int(round(val))
    except (ValueError, OverflowError):
        return None


def _parse_minsec_seconds(text: Optional[str]) -> Optional[float]:
    """Convierte 'MM:SS.s' (o 'HH:MM:SS.s' si el receptor llega a pasar
    de 99 minutos en la sesión) a segundos totales. Ver la nota junto a
    `_MINSEC_RE`: esto NO es una hora de reloj, sólo sirve para restar
    dos lecturas y obtener una duración."""
    if text is None:
        return None
    m = _MINSEC_RE.match(str(text))
    if not m:
        return None
    horas = float(m.group(1)) if m.group(1) else 0.0
    minutos = float(m.group(2))
    segundos = float(m.group(3))
    return horas * 3600.0 + minutos * 60.0 + segundos


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distancia entre dos puntos geográficos (grados decimales), en
    metros, sobre una Tierra esférica -- suficiente para estimar una
    línea base RTK (unos pocos km como mucho); no se usa para nada que
    se suba como coordenada."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class HiTargetPoint:
    row_id: str  # columna "id" del CSV (texto tal cual; identidad estable de la fila)
    name: str  # columna "Nombre"
    lat: float  # grados decimales, de la columna B
    lon: float  # grados decimales, de la columna L
    height: float  # columna H (altura elipsoidal WGS84)
    ant_height: Optional[float]  # columna AntH
    estado: str  # columna Estado, tal cual ("RTK Fijo"/"RTK Fix"/"RTK Flotante"/"Cálculo"/...)
    desc: str  # columna Desc (comentario de campo)
    is_base: bool  # True si Desc == "set_base" (ocupación de base, no punto levantado)
    line_no: int  # número de línea en el archivo (1 = encabezado)
    # -- Datos adicionales que el archivo SÍ trae con columnas propias
    # (a diferencia de un .dc de Trimble, donde estos datos -- si es que
    # están -- van en dígitos sin documentar después de lat/lon/altura;
    # ver la nota de la v2.9.0 en el registro del proyecto). Todos
    # opcionales porque una versión más vieja del exportador de
    # Hi-Target podría no traer alguna columna.
    n_sats: Optional[int] = None  # columna "Sats": satélites usados en la solución
    pdop: Optional[float] = None  # columna "PDOP"
    n_epochs: Optional[float] = None  # columna "N Promedios": épocas promediadas para el punto
    occupation_seconds: Optional[float] = None  # FinTiempo Loc - InicioTiempo Loc, en segundos
    base_lat: Optional[float] = None  # columna "Base B", grados decimales
    base_lon: Optional[float] = None  # columna "Base L", grados decimales
    base_height: Optional[float] = None  # columna "H Base(Centro Fase)"
    base_baseline_m: Optional[float] = None  # distancia punto-base calculada (ver _haversine_m)
    base_station_name: Optional[str] = None  # nombre de la fila is_base con las mismas coordenadas de base, si se encuentra


@dataclass
class HiTargetFile:
    path: str
    points: List[HiTargetPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def n_points(self) -> int:
        return len(self.points)

    def duplicated_names(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.points:
            counts[p.name] = counts.get(p.name, 0) + 1
        return {k: v for k, v in counts.items() if v > 1}


def looks_like_hitarget_csv(header) -> bool:
    """True si `header` (lista de nombres de columna) tiene todas las
    columnas que este parser necesita -- se usa para no intentar leer
    como Hi-Target un CSV que en realidad es de otro origen."""
    if not header:
        return False
    presentes = {h.strip() for h in header}
    return all(h in presentes for h in REQUIRED_HEADERS)


def parse_hitarget_csv(path: str, encoding: str = "utf-8-sig") -> HiTargetFile:
    """Lee y parsea un CSV de Hi-Target desde disco. `encoding` por
    defecto es 'utf-8-sig' porque el archivo real analizado venía en
    UTF-8 con BOM (los símbolos °′″ y σ de sus encabezados/valores
    obligan a una codificación Unicode; 'utf-8-sig' además descarta el
    BOM si está presente, sin fallar si no lo está)."""
    hf = HiTargetFile(path=path)
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        if not looks_like_hitarget_csv(header):
            faltantes = [h for h in REQUIRED_HEADERS if h not in {c.strip() for c in header}]
            raise ValueError(
                "El archivo no tiene las columnas esperadas de un CSV de "
                "Hi-Target (faltan: " + ", ".join(faltantes) + ")."
            )
        for i, row in enumerate(reader, start=2):  # la fila 1 es el encabezado
            nombre = (row.get("Nombre") or "").strip()
            if not nombre:
                continue
            lat = parse_dms(row.get("B"))
            lon = parse_dms(row.get("L"))
            if lat is None or lon is None:
                hf.warnings.append(f"Fila {i}: no se pudo interpretar la latitud/longitud (B/L) de '{nombre}'.")
                continue
            altura = _parse_float_optional(row.get("H"))
            if altura is None:
                hf.warnings.append(f"Fila {i}: altura (H) inválida para '{nombre}'.")
                continue
            desc = (row.get("Desc") or "").strip()

            # "Base B"/"Base L" vienen en 0°0'0" cuando la fila no tiene
            # (o no aplica) una base de referencia -- p.ej. en la propia
            # fila is_base de la ocupación. Se tratan como "sin base" en
            # vez de como una coordenada real (0,0 geográfico está en el
            # golfo de Guinea, nunca es un valor válido de una base RTK
            # real).
            base_lat = parse_dms(row.get("Base B"))
            base_lon = parse_dms(row.get("Base L"))
            if base_lat == 0.0 and base_lon == 0.0:
                base_lat = base_lon = None
            base_height = _parse_float_optional(row.get("H Base(Centro Fase)"))

            baseline_m = None
            if base_lat is not None and base_lon is not None:
                baseline_m = _haversine_m(lat, lon, base_lat, base_lon)
                if base_height is not None:
                    dz = altura - base_height
                    baseline_m = math.hypot(baseline_m, dz)

            inicio_s = _parse_minsec_seconds(row.get("InicioTiempo Loc"))
            fin_s = _parse_minsec_seconds(row.get("FinTiempo Loc"))
            ocupacion_s = None
            if inicio_s is not None and fin_s is not None and fin_s >= inicio_s:
                ocupacion_s = fin_s - inicio_s

            hf.points.append(HiTargetPoint(
                row_id=(row.get("id") or "").strip() or str(i),
                name=nombre,
                lat=lat, lon=lon, height=altura,
                ant_height=_parse_float_optional(row.get("AntH")),
                estado=(row.get("Estado") or "").strip(),
                desc=desc,
                is_base=(desc.lower() == "set_base"),
                line_no=i,
                n_sats=_parse_int_optional(row.get("Sats")),
                pdop=_parse_float_optional(row.get("PDOP")),
                n_epochs=_parse_float_optional(row.get("N Promedios")),
                occupation_seconds=ocupacion_s,
                base_lat=base_lat, base_lon=base_lon, base_height=base_height,
                base_baseline_m=baseline_m,
            ))

    # Segunda pasada: si la base de un punto coincide (dentro de
    # `_BASE_MATCH_TOLERANCE_M`) con las coordenadas de una fila is_base
    # del MISMO archivo, se usa su nombre como `base_station_name` -- así
    # "Importar datos de campo" puede mostrar/subir qué base concreta se
    # usó, no sólo la distancia.
    bases = [p for p in hf.points if p.is_base]
    for p in hf.points:
        if p.base_lat is None or p.base_lon is None:
            continue
        mejor_base = None
        mejor_dist = None
        for b in bases:
            d = _haversine_m(p.base_lat, p.base_lon, b.lat, b.lon)
            if mejor_dist is None or d < mejor_dist:
                mejor_dist, mejor_base = d, b
        if mejor_base is not None and mejor_dist <= _BASE_MATCH_TOLERANCE_M:
            p.base_station_name = mejor_base.name

    dup = hf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        hf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplos})."
        )
    return hf
