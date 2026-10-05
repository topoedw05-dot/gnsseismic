# -*- coding: utf-8 -*-
"""
csv_matcher.py
--------------
Compara puntos levantados (típicamente los importados desde un .dc, ya
en la base de datos como POSTPLOT) contra un archivo CSV de diseño /
preplot que el usuario precarga, emparejando por una columna de NOMBRE.

Este módulo es independiente de QGIS: recibe coordenadas ya en un
sistema comparable (mismas unidades, mismo sistema de referencia -
p.ej. ambas en metros, Este/Norte de la misma proyección). La
transformación entre sistemas de coordenadas (geográficas <-> planas,
o entre CRS distintos) se resuelve en la capa del plugin usando la API
de QGIS (QgsCoordinateTransform), antes de llamar a esta función, para
aprovechar el motor de reproyección real de QGIS/PROJ en vez de
aproximaciones caseras.
"""

import csv
import math
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


def sniff_csv_dialect(path: str, encodings: Tuple[str, ...] = ("utf-8-sig", "latin-1")):
    """Detecta delimitador y codificación de un CSV de forma tolerante.
    Devuelve (encoding, delimiter).
    """
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                sample = f.read(4096)
            if not sample:
                continue
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delim = dialect.delimiter
            except csv.Error:
                # fallback simple: el separador que más aparece en la 1a línea
                first_line = sample.splitlines()[0] if sample.splitlines() else ""
                delim = max(",;\t|", key=lambda d: first_line.count(d))
            return enc, delim
        except (UnicodeDecodeError, OSError):
            continue
    return "utf-8", ","


def read_csv_header(path: str, encoding: Optional[str] = None, delimiter: Optional[str] = None) -> List[str]:
    if encoding is None or delimiter is None:
        auto_enc, auto_delim = sniff_csv_dialect(path)
        encoding = encoding or auto_enc
        delimiter = delimiter or auto_delim
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, [])
    return [h.strip() for h in header]


def read_csv_rows(path: str, encoding: Optional[str] = None, delimiter: Optional[str] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    if encoding is None or delimiter is None:
        auto_enc, auto_delim = sniff_csv_dialect(path)
        encoding = encoding or auto_enc
        delimiter = delimiter or auto_delim
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        header = [h.strip() for h in (reader.fieldnames or [])]
        rows = [{(k.strip() if k else k): v for k, v in r.items()} for r in reader]
    return header, rows


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".") if isinstance(value, str) else value
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def read_csv_points(
    path: str,
    name_col: str,
    x_col: str,
    y_col: str,
    z_col: Optional[str] = None,
    encoding: Optional[str] = None,
    delimiter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lee el CSV y devuelve una lista de puntos:
    {'name': str, 'x': float, 'y': float, 'z': float|None, 'row': dict}
    Las filas sin nombre o sin X/Y numéricos válidos se omiten (no
    interrumpen la carga completa).
    """
    _, rows = read_csv_rows(path, encoding=encoding, delimiter=delimiter)
    points = []
    for row in rows:
        name = (row.get(name_col) or "").strip()
        x = _to_float(row.get(x_col))
        y = _to_float(row.get(y_col))
        z = _to_float(row.get(z_col)) if z_col else None
        if not name or x is None or y is None:
            continue
        points.append({"name": name, "x": x, "y": y, "z": z, "row": row})
    return points


def normalize_name(name: str) -> str:
    """Normaliza un nombre de punto para intentar un emparejamiento
    aproximado cuando el emparejamiento exacto falla: quita todo lo que
    no sea alfanumérico, pasa a mayúsculas y elimina ceros a la
    izquierda de cada bloque numérico.
    """
    s = re.sub(r"[^0-9A-Za-z]", "", name).upper()
    s = re.sub(r"(?<![0-9])0+(?=[0-9])", "", s)
    return s


@dataclass
class MatchResult:
    matched: List[Dict[str, Any]] = field(default_factory=list)
    solo_en_diseno: List[Dict[str, Any]] = field(default_factory=list)
    solo_en_levantado: List[Dict[str, Any]] = field(default_factory=list)
    nombres_duplicados_diseno: Dict[str, int] = field(default_factory=dict)
    nombres_duplicados_levantado: Dict[str, int] = field(default_factory=dict)

    @property
    def n_matched(self) -> int:
        return len(self.matched)

    @property
    def n_dentro_tolerancia(self) -> int:
        return sum(1 for m in self.matched if m["dentro_tolerancia"])


def _dup_counts(points: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for p in points:
        counts[p["name"]] = counts.get(p["name"], 0) + 1
    return {k: v for k, v in counts.items() if v > 1}


def match_by_name(
    levantado: List[Dict[str, Any]],
    diseno: List[Dict[str, Any]],
    tolerancia_m: float = 0.10,
    permitir_aproximado: bool = True,
) -> MatchResult:
    """Empareja puntos por nombre.

    `levantado`: puntos ya en la base de datos (p.ej. POSTPLOT, desde el
        .dc importado) -> [{'name','x','y','z'}, ...] en un sistema de
        coordenadas plano/comparable (metros).
    `diseno`: puntos del CSV cargado por el usuario, en el mismo
        sistema de coordenadas.
    `tolerancia_m`: distancia 2D máxima (metros) para considerar el
        punto "dentro de tolerancia".
    `permitir_aproximado`: si un nombre no calza exactamente, intenta
        un segundo pase normalizando ambos nombres (ver
        `normalize_name`) antes de darlo por no encontrado.
    """
    result = MatchResult()
    result.nombres_duplicados_diseno = _dup_counts(diseno)
    result.nombres_duplicados_levantado = _dup_counts(levantado)

    lev_by_name: Dict[str, Dict[str, Any]] = {}
    for p in levantado:
        lev_by_name.setdefault(p["name"], p)  # primer valor si hay duplicados

    used_lev_names = set()
    unmatched_diseno = []

    for dp in diseno:
        lp = lev_by_name.get(dp["name"])
        if lp is not None:
            used_lev_names.add(dp["name"])
            result.matched.append(_build_match(dp, lp, tolerancia_m, "exacto"))
        else:
            unmatched_diseno.append(dp)

    if permitir_aproximado and unmatched_diseno:
        lev_by_norm: Dict[str, Dict[str, Any]] = {}
        for p in levantado:
            if p["name"] in used_lev_names:
                continue
            lev_by_norm.setdefault(normalize_name(p["name"]), p)

        still_unmatched = []
        for dp in unmatched_diseno:
            key = normalize_name(dp["name"])
            lp = lev_by_norm.get(key)
            if lp is not None and lp["name"] not in used_lev_names:
                used_lev_names.add(lp["name"])
                result.matched.append(_build_match(dp, lp, tolerancia_m, "aproximado"))
            else:
                still_unmatched.append(dp)
        unmatched_diseno = still_unmatched

    result.solo_en_diseno = unmatched_diseno
    result.solo_en_levantado = [p for p in levantado if p["name"] not in used_lev_names]
    return result


def _build_match(dp: Dict[str, Any], lp: Dict[str, Any], tolerancia_m: float, tipo: str) -> Dict[str, Any]:
    dx = lp["x"] - dp["x"]
    dy = lp["y"] - dp["y"]
    dz = None
    if lp.get("z") is not None and dp.get("z") is not None:
        dz = lp["z"] - dp["z"]
    dist2d = math.hypot(dx, dy)
    dist3d = math.sqrt(dist2d ** 2 + dz ** 2) if dz is not None else dist2d
    return {
        "name_diseno": dp["name"],
        "name_levantado": lp["name"],
        "tipo_match": tipo,
        "x_diseno": dp["x"], "y_diseno": dp["y"], "z_diseno": dp.get("z"),
        "x_levantado": lp["x"], "y_levantado": lp["y"], "z_levantado": lp.get("z"),
        "delta_x": dx, "delta_y": dy, "delta_z": dz,
        "distancia_2d": dist2d, "distancia_3d": dist3d,
        "dentro_tolerancia": dist2d <= tolerancia_m,
    }


# --- Utilidades de proyección aproximada (uso opcional / pruebas fuera
#     de QGIS). Dentro del plugin real se prefiere QgsCoordinateTransform
#     con el CRS que el usuario seleccione, por ser exacto y consistente
#     con el resto de QGIS. ---

_EARTH_RADIUS_M = 6378137.0


def geographic_to_local_xy(lat: float, lon: float, lat0: float, lon0: float) -> Tuple[float, float]:
    """Proyección equirectangular simple centrada en (lat0, lon0),
    válida como aproximación para distancias cortas (hasta varios km),
    típico de comparaciones de puntos dentro de un mismo levantamiento.
    """
    lat0_rad = math.radians(lat0)
    x = math.radians(lon - lon0) * _EARTH_RADIUS_M * math.cos(lat0_rad)
    y = math.radians(lat - lat0) * _EARTH_RADIUS_M
    return x, y


# --- Puntos a partir del resultado de una consulta SQL (v2.68.0) ------------
_QUERY_NAME_CANDIDATES = ("station_text", "nombre", "name", "punto", "point", "codigo", "código")


def points_from_query_rows(cols: List[str], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convierte el resultado de una consulta SQL de la base del proyecto
    (columnas + filas como diccionarios, p.ej. de `db_schema.run_query`)
    en puntos comparables por nombre.

    Detecta las columnas por nombre (sin distinguir mayúsculas):
      * nombre: Station_Text (o Nombre/Name/Punto/...);
      * coordenadas: WGS84_Longitude/WGS84_Latitude (kind="geo", se
        transforman luego al CRS de trabajo con QGIS) y, para las filas que
        no las tengan, Local_Easting/Local_Northing (kind="local", ya en el
        CRS de trabajo);
      * cota: WGS84_Height (o Local_Height), opcional.

    Devuelve [{"name", "kind", "a", "b", "z"}] -- "a","b" = lon,lat (geo)
    o este,norte (local). Las filas sin nombre o sin coordenadas utilizables
    se omiten. Lanza ValueError("no_name") o ValueError("no_coords") si la
    consulta no trae las columnas necesarias.
    """
    low = {c.lower(): c for c in cols}
    name_col = next((low[c] for c in _QUERY_NAME_CANDIDATES if c in low), None)
    if name_col is None:
        raise ValueError("no_name")
    lat_col, lon_col = low.get("wgs84_latitude"), low.get("wgs84_longitude")
    e_col, n_col = low.get("local_easting"), low.get("local_northing")
    tiene_geo = lat_col is not None and lon_col is not None
    tiene_local = e_col is not None and n_col is not None
    if not (tiene_geo or tiene_local):
        raise ValueError("no_coords")
    z_col = low.get("wgs84_height") or low.get("local_height")

    puntos = []
    for row in rows:
        nombre = row.get(name_col)
        if nombre is None or str(nombre).strip() == "":
            continue
        z = _to_float(row.get(z_col)) if z_col else None
        lat = _to_float(row.get(lat_col)) if tiene_geo else None
        lon = _to_float(row.get(lon_col)) if tiene_geo else None
        if lat is not None and lon is not None:
            puntos.append({"name": str(nombre).strip(), "kind": "geo", "a": lon, "b": lat, "z": z})
            continue
        este = _to_float(row.get(e_col)) if tiene_local else None
        norte = _to_float(row.get(n_col)) if tiene_local else None
        if este is not None and norte is not None:
            puntos.append({"name": str(nombre).strip(), "kind": "local", "a": este, "b": norte, "z": z})
    return puntos
