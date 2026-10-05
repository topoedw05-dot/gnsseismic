# -*- coding: utf-8 -*-
"""
inova_parser.py
----------------
Lector del libro Excel (.xls) que exporta Inova (sistema de vibradores
sísmicos VibPro/"APS") con el reporte de producción de un turno -- por
ejemplo `3932_4283.XLS`: 351 disparos, 352 VP, 10 lecturas GNSS por VP.
Es la versión en Python de la macro de Excel `ExtraerCOG_GPSeismic`
(modExtraerCOG_GPSeismic_v2.bas) que el usuario venía usando para sacar
las coordenadas COG (centro de grupo) de cada VP y subirlas a GPSeismic:
el algoritmo es el mismo, para que el resultado coincida con el de la
macro, y el plugin lo lee directo del .xls sin pasar por Excel.

Hojas del libro (nombres con el rango de archivos al final):

  * `COG_<rango>`: una fila por vibro y por VP más una fila "COG" (VibUnit
    = "COG") por VP, con Easting/Northing/Elevation del centro de grupo
    (Easting/Northing en POSGAR 94 faja 2, EPSG:22182, ver abajo) y el
    Status del control de calidad ("Pass"/"Fail"). Es la hoja de donde
    salen los puntos: UNA fila COG = UN punto.
  * `GPS_<rango>`: las lecturas GNSS crudas de cada vibro (≈10 por VP):
    Latitude/Longitude ("38.5719133 S"), Satellites, PDOP/VDOP/HDOP,
    Quality ("4: RTK Fix"), Station ID, Dates, Antenna Height ("0.0
    Meters"). Se agrupan por clave File|SLine|Flag.
  * `TitlePage`: datos del proyecto en celdas "Etiqueta: Valor"
    (Client, Prospect, Contractor, Crew #, Observer, Shooting System...).
  * `GPS_CONVERSION_<rango>`: parámetros de la proyección de las
    coordenadas Easting/Northing (meridiano central, falso este...).
  * `COG_GPSeismic_Export`: la salida de la macro si ya se corrió sobre
    el libro -- se IGNORA (no es una hoja de origen).

Algoritmo (igual que la macro v2):

  * Nombre del punto = SLine + Flag sin espacios ("6018"+"1012" ->
    "60181012", la convención de nombres numéricos del plugin; Track =
    SLine, Bin = Flag).
  * Altura de antena del grupo = primer valor distinto de cero de la
    columna "Antenna Height" de las lecturas GPS del VP; si es 0/vacío
    (típico: no se configuró en campo) o no hay hoja GPS, la estándar de
    los vibros, 2.73 m.
  * Elevación del terreno = Elevation del COG - altura de antena. Aquí
    NO se resta: el parser devuelve la elevación de antena
    (`height`) y la altura de antena (`antenna_height`) por separado, y
    el plugin hace la resta con la celda HI editable de la
    previsualización (igual que Trimble .dc), para que el usuario pueda
    cambiarla.
  * Calidad GPS por VP: promedio de satélites (y mínimo), de PDOP/HDOP/
    VDOP, número de lecturas, tipos de fix, estaciones base (Station ID)
    y fecha/hora de la última lectura (la columna "Dates" está en UTC; la
    hora local se obtiene con UTC-3, ver `LOCAL_UTC_OFFSET_H`) -- sobre TODAS las filas GPS del
    VP, igual que la macro (incluidas las filas compuestas de "7,8,").
  * Unidades (vibros) del VP: las del campo "Unit" de las lecturas
    ("7,", "8,", "7,8,") sin repetir, ordenadas por aparición -> "7 y 8".
    Se sube como Surveyor del punto (como el Unit ID de SourceLink).

Diferencia deliberada con la macro: la macro calcula Latitud/Longitud
como el PROMEDIO de las lecturas GPS del VP, que incluye las filas
compuestas y por eso queda sesgado hacia uno de los vibros (~1 m en el
archivo de referencia). Acá la latitud/longitud se obtienen invirtiendo
la proyección de Easting/Northing del COG (transversa de Mercator con
los parámetros de la hoja GPS_CONVERSION, WGS84), o sea, es exactamente
el mismo punto de las columnas Easting_COG/Northing_COG de la macro.
Sólo si la inversión no es posible se usa el promedio de lecturas.

Lógica pura (sin QGIS/PyQt); el .xls se lee con la copia de xlrd que
viene en `_xlrd/` (BSD, ver `_xlrd/LICENSE`) porque el Python de QGIS no
siempre trae xlrd instalado.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

# Altura de antena estándar de los vibros (m), la misma de la macro.
ALTURA_ANTENA_STD = 2.73

_COG_REQUIRED = ("File", "SLine", "Flag", "VibUnit", "Easting", "Northing", "Elevation")
_GPS_REQUIRED = ("File", "SLine", "Flag", "Unit")

# Hora local de Argentina respecto de UTC (sin horario de verano). La
# columna "Dates" del libro está en UTC: verificado en el archivo de
# referencia -- las lecturas van de 11:29 a 20:10 y la firma del
# observador en TitlePage dice 17:23, o sea 13 minutos después del último
# disparo en hora local = UTC-3 (con "Dates" como hora local la firma
# quedaría ANTES del último disparo).
LOCAL_UTC_OFFSET_H = -3

# Hoja de salida de la macro: nunca es una hoja de origen.
_HOJA_SALIDA_MACRO = "COG_GPSEISMIC_EXPORT"


# ---------------------------------------------------------------------------
# Proyección: transversa de Mercator (inversa), serie de Krüger
# ---------------------------------------------------------------------------

_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563


def _meridian_arc(a: float, e2: float, lat: float) -> float:
    """Longitud de arco de meridiano desde el ecuador hasta `lat` (rad)."""
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
        - (35 * e6 / 3072) * math.sin(6 * lat)
    )


@dataclass
class TMParams:
    """Parámetros de una transversa de Mercator. Por defecto, los de
    POSGAR 94 / Argentina 2 (EPSG:22182)."""
    lon0: float = -69.0
    lat0: float = -90.0
    k0: float = 1.0
    fe: float = 2500000.0
    fn: float = 0.0
    a: float = _WGS84_A
    f: float = _WGS84_F


def tm_inverse(easting: float, northing: float, p: Optional[TMParams] = None) -> Tuple[float, float]:
    """(E, N) -> (lat, lon) en grados, WGS84. Serie de Krüger de 4º orden:
    error < 0.1 mm dentro de una faja de 3° (verificada contra pyproj)."""
    p = p or TMParams()
    n = p.f / (2 - p.f)
    n2, n3, n4 = n * n, n ** 3, n ** 4
    e2 = p.f * (2 - p.f)
    big_a = p.a / (1 + n) * (1 + n2 / 4 + n4 / 64)
    beta = (
        n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360,
        n2 / 48 + n3 / 15 - 437 * n4 / 1440,
        17 * n3 / 480 - 37 * n4 / 840,
        4397 * n4 / 161280,
    )
    delta = (
        2 * n - 2 * n2 / 3 - 2 * n3 + 116 * n4 / 45,
        7 * n2 / 3 - 8 * n3 / 5 - 227 * n4 / 45,
        56 * n3 / 15 - 136 * n4 / 35,
        4279 * n4 / 630,
    )
    m0 = _meridian_arc(p.a, e2, math.radians(p.lat0))
    xi_p = ((northing - p.fn) / p.k0 + m0) / big_a
    eta_p = (easting - p.fe) / (p.k0 * big_a)
    xi, eta = xi_p, eta_p
    for j, b in enumerate(beta, start=1):
        xi -= b * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
        eta -= b * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
    chi = math.asin(math.sin(xi) / math.cosh(eta))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(delta, start=1))
    lon = math.radians(p.lon0) + math.atan2(math.sinh(eta), math.cos(xi))
    return math.degrees(lat), math.degrees(lon)


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass
class InovaPoint:
    name: str  # SLine + Flag, ej. "60181012"
    lat: float
    lon: float
    height: float  # elevación del COG a nivel de ANTENA (sin restar la altura de antena)
    antenna_height: float  # altura de antena del grupo (archivo, o 2.73 si no la trae)
    antenna_from_file: bool  # True si salió de la columna "Antenna Height"
    line_no: int  # número de fila (1-based, 1 = encabezado) en la hoja COG
    file_no: str  # número de archivo de registro ("3932")
    track: str  # SLine
    bin: str  # Flag
    easting: float
    northing: float
    units: List[str] = field(default_factory=list)  # vibros del VP, ej. ["7", "8"]
    status: str = ""  # "Pass" / "Fail" del control de calidad
    quality: Optional[str] = None  # tipos de fix, ej. "RTK Fix"
    n_sats: Optional[int] = None  # promedio redondeado
    n_sats_min: Optional[int] = None
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    n_readings: Optional[int] = None
    base_station: Optional[str] = None
    survey_time_gmt: Optional[str] = None  # "AAAA-MM-DD HH:MM:SS" (última lectura, UTC)
    survey_time_local: Optional[str] = None  # la misma, en hora local (UTC-3)
    julian_date: Optional[str] = None  # AAAADDD (fecha local)
    tipo: str = "SO"  # punto de fuente (vibro)
    is_base: bool = False
    latlon_from_gps_mean: bool = False  # True si no se pudo invertir la proyección

    @property
    def surveyor(self) -> str:
        return " y ".join(self.units)

    @property
    def ground_height(self) -> float:
        """Elevación de terreno (la columna "Elevacion_Terreno" de la macro)."""
        return round(self.height - self.antenna_height, 3)


@dataclass
class InovaFile:
    path: str
    points: List[InovaPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    n_sin_elevacion: int = 0
    n_fail: int = 0
    n_sin_gps: int = 0  # VP sin lecturas en la hoja GPS (altura estándar, sin calidad)
    meta: Dict[str, str] = field(default_factory=dict)  # Client, Prospect, ...
    files_range: str = ""

    @property
    def n_points(self) -> int:
        return len(self.points)

    @property
    def units(self) -> List[str]:
        vistos = {u for p in self.points for u in p.units}
        return sorted(vistos, key=lambda u: (len(u), u))

    @property
    def job_name(self) -> Optional[str]:
        return self.meta.get("Prospect") or None

    @property
    def instrument(self) -> str:
        return self.meta.get("Shooting System") or "Inova"

    def duplicated_names(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.points:
            counts[p.name] = counts.get(p.name, 0) + 1
        return {k: v for k, v in counts.items() if v > 1}


# ---------------------------------------------------------------------------
# Utilidades de celdas
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def _a_numero(v) -> float:
    """Equivalente a `ANumero` de la macro: número tal cual; texto con
    punto o coma decimal; sólo cuenta el número del principio ("2.73
    Meters" -> 2.73); vacío o sin número -> 0."""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v if v is not None else "").strip().replace(",", ".")
    m = _NUM_RE.match(s)
    return float(m.group(0)) if m else 0.0


def _texto(v) -> str:
    """Texto de una celda; un número entero se escribe sin ".0"."""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _clave_texto(v) -> str:
    return _texto(v).strip()


def _parse_latlon(s) -> Optional[float]:
    """"38.5240600 S" -> -38.52406 (S y W negativos); None si no se puede."""
    txt = _texto(s)
    if not txt:
        return None
    partes = txt.split()
    if len(partes) < 2:
        return None
    try:
        val = float(partes[0].replace(",", "."))
    except ValueError:
        return None
    if partes[-1].upper() in ("S", "W"):
        val = -val
    return val


def _parse_fecha(txt: str) -> Optional[datetime]:
    """"2026/08/28 11:29:54.032" -> datetime (descarta las fracciones)."""
    if not txt:
        return None
    base = txt.strip().split(".", 1)[0]
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(base, fmt)
        except ValueError:
            continue
    return None


def _agregar_distinto(actual: List[str], token: str) -> None:
    if token and token not in actual:
        actual.append(token)


def _quitar_numero_fix(q: str) -> str:
    """"4: RTK Fix" -> "RTK Fix"."""
    return re.sub(r"^\s*\d+\s*:\s*", "", q).strip()


def _encabezados(rows: Sequence[Sequence]) -> Dict[str, int]:
    if not rows:
        return {}
    return {_texto(c): i for i, c in enumerate(rows[0]) if _texto(c)}


def _parse_title_page(rows: Sequence[Sequence]) -> Dict[str, str]:
    """Líneas "Etiqueta: Valor" de TitlePage (incluye celdas multilínea);
    la primera aparición de cada etiqueta gana, igual que la macro."""
    meta: Dict[str, str] = {}
    for row in rows:
        for c in row:
            if not isinstance(c, str):
                continue
            for linea in c.split("\n"):
                pos = linea.find(":")
                if pos > 0:
                    etiqueta = linea[:pos].strip()
                    valor = linea[pos + 1:].strip()
                    if valor and etiqueta not in meta:
                        meta[etiqueta] = valor
    return meta


def _parse_conversion(rows: Sequence[Sequence]) -> Optional[TMParams]:
    """Parámetros de la proyección desde GPS_CONVERSION ("Long. of central
    meridian" -69 degree, "Grid coord. at origin" 2500000 E, 0 N, "Scale
    factor" 1.0). Devuelve None si el libro no declara una transversa de
    Mercator reconocible -- en ese caso no se usa ningún valor supuesto."""
    d: Dict[str, str] = {}
    for r in rows:
        if len(r) >= 2 and _texto(r[0]):
            d[_texto(r[0]).lower()] = _texto(r[1])
    proyeccion = " ".join(v.lower() for k, v in d.items() if "projection" in k)
    if "transverse" not in proyeccion:
        return None
    try:
        lon0 = float(_NUM_RE.match(d.get("long. of central meridian", "").replace(",", ".")).group(0))
        origen = d.get("grid coord. at origin", "")
        m_e = re.search(r"([-+]?\d+\.?\d*)\s*E", origen)
        m_n = re.search(r"([-+]?\d+\.?\d*)\s*N", origen)
        fe = float(m_e.group(1)) if m_e else 0.0
        fn = float(m_n.group(1)) if m_n else 0.0
        k0 = float(_NUM_RE.match(d.get("scale factor", "1").replace(",", ".")).group(0))
        lat0_txt = d.get("grid origin", "")
        lat0 = float(_NUM_RE.match(lat0_txt.replace(",", ".")).group(0)) if lat0_txt else 0.0
    except (AttributeError, ValueError):
        return None
    return TMParams(lon0=lon0, lat0=lat0, k0=k0, fe=fe, fn=fn)


def _es_hoja_cog(nombre: str, rows: Sequence[Sequence]) -> bool:
    if not nombre.upper().startswith("COG_") or nombre.upper() == _HOJA_SALIDA_MACRO:
        return False
    h = _encabezados(rows)
    return all(c in h for c in _COG_REQUIRED)


def _es_hoja_gps(nombre: str, rows: Sequence[Sequence]) -> bool:
    if not nombre.upper().startswith("GPS_") or nombre.upper().startswith("GPS_CONVERSION"):
        return False
    h = _encabezados(rows)
    return all(c in h for c in _GPS_REQUIRED)


# ---------------------------------------------------------------------------
# Lectura del libro
# ---------------------------------------------------------------------------

def parse_inova_sheets(sheets: Dict[str, List[List]], path: str = "") -> InovaFile:
    """Algoritmo de la macro sobre un libro ya leído: {nombre de hoja:
    filas (lista de listas de celdas)}. Separado de la lectura del .xls
    para poder probarlo sin Excel ni xlrd."""
    inf = InovaFile(path=path)
    hoja_cog = next((n for n, r in sheets.items() if _es_hoja_cog(n, r)), None)
    if hoja_cog is None:
        raise ValueError(
            "El libro no parece un export de Inova: no se encontró ninguna hoja 'COG_...' con "
            "las columnas File, SLine, Flag, VibUnit, Easting, Northing y Elevation."
        )
    hoja_gps = next((n for n, r in sheets.items() if _es_hoja_gps(n, r)), None)
    hoja_title = next((n for n in sheets if n == "TitlePage"), None)
    hoja_conv = next((n for n in sheets if n.upper().startswith("GPS_CONVERSION")), None)
    inf.files_range = hoja_cog[4:]

    if hoja_title:
        inf.meta = _parse_title_page(sheets[hoja_title])

    # --- 1) Agregación de lecturas GPS por File|SLine|Flag ---
    grupos: Dict[str, dict] = {}
    if hoja_gps is None:
        inf.warnings.append(
            "No se encontró la hoja 'GPS_...': se usa la altura de antena estándar de "
            f"{ALTURA_ANTENA_STD:.2f} m y los puntos quedan sin datos de calidad GNSS."
        )
    else:
        gps = sheets[hoja_gps]
        h = _encabezados(gps)
        g_file, g_sline, g_flag, g_unit = (h[c] for c in _GPS_REQUIRED)
        g = {c: h.get(c) for c in (
            "Satellites", "PDOP", "HDOP", "VDOP", "Quality", "Station ID",
            "Dates", "Antenna Height", "Latitude", "Longitude",
        )}

        def celda(row, idx):
            return row[idx] if idx is not None and idx < len(row) else ""

        for row in gps[1:]:
            key = "|".join((
                _clave_texto(celda(row, g_file)),
                _clave_texto(celda(row, g_sline)),
                _clave_texto(celda(row, g_flag)),
            ))
            if key == "||":
                continue
            gr = grupos.get(key)
            if gr is None:
                gr = grupos[key] = {
                    "n": 0, "sum_sat": 0.0, "min_sat": None, "sum_pdop": 0.0,
                    "sum_hdop": 0.0, "sum_vdop": 0.0, "units": [], "quality": [],
                    "station": [], "fecha_max": "", "antena": 0.0,
                    "sum_lat": 0.0, "sum_lon": 0.0, "n_ll": 0,
                }
            gr["n"] += 1
            if g["Satellites"] is not None:
                sat = _a_numero(celda(row, g["Satellites"]))
                gr["sum_sat"] += sat
                if gr["min_sat"] is None or sat < gr["min_sat"]:
                    gr["min_sat"] = sat
            gr["sum_pdop"] += _a_numero(celda(row, g["PDOP"])) if g["PDOP"] is not None else 0.0
            gr["sum_hdop"] += _a_numero(celda(row, g["HDOP"])) if g["HDOP"] is not None else 0.0
            gr["sum_vdop"] += _a_numero(celda(row, g["VDOP"])) if g["VDOP"] is not None else 0.0
            for u in _texto(celda(row, g_unit)).split(","):
                _agregar_distinto(gr["units"], u.strip())
            if g["Quality"] is not None:
                _agregar_distinto(gr["quality"], _texto(celda(row, g["Quality"])))
            if g["Station ID"] is not None:
                _agregar_distinto(gr["station"], _texto(celda(row, g["Station ID"])))
            if g["Dates"] is not None:
                fecha = _texto(celda(row, g["Dates"]))
                if fecha > gr["fecha_max"]:  # comparación de texto, como la macro
                    gr["fecha_max"] = fecha
            if g["Antenna Height"] is not None and gr["antena"] == 0:
                gr["antena"] = _a_numero(celda(row, g["Antenna Height"]))
            if g["Latitude"] is not None and g["Longitude"] is not None:
                la = _parse_latlon(celda(row, g["Latitude"]))
                lo = _parse_latlon(celda(row, g["Longitude"]))
                if la is not None and lo is not None:
                    gr["sum_lat"] += la
                    gr["sum_lon"] += lo
                    gr["n_ll"] += 1

    # Alturas de antena distintas de la estándar: la macro pregunta si se
    # dejan; acá se respetan (son las del archivo) y se avisa -- el usuario
    # puede pisarlas con "Aplicar a todos" > Altura de antena.
    distintas: List[str] = []
    for gr in grupos.values():
        av = gr["antena"]
        if av != 0 and abs(av - ALTURA_ANTENA_STD) > 0.001:
            _agregar_distinto(distintas, f"{av:.3f}")
    if distintas:
        inf.warnings.append(
            f"Hay alturas de antena distintas de {ALTURA_ANTENA_STD:.2f} m en el archivo ("
            + ", ".join(distintas)
            + "): se usan esos valores en cada VP. Se pueden cambiar con 'Aplicar a todos' > "
            "Altura de antena."
        )

    tm = _parse_conversion(sheets[hoja_conv]) if hoja_conv else None

    # --- 2) Una fila COG = un punto ---
    cog = sheets[hoja_cog]
    h = _encabezados(cog)
    c_file, c_sline, c_flag, c_vib, c_e, c_n, c_elev = (h[c] for c in _COG_REQUIRED)
    c_status = h.get("Status")

    def celda_c(row, idx):
        return row[idx] if idx is not None and idx < len(row) else ""

    n_gps_media = 0
    for i, row in enumerate(cog[1:], start=2):
        if _texto(celda_c(row, c_vib)) != "COG":
            continue
        f_arch = _clave_texto(celda_c(row, c_file))
        f_linea = _clave_texto(celda_c(row, c_sline))
        f_vp = _clave_texto(celda_c(row, c_flag))
        if _texto(celda_c(row, c_elev)) == "":
            inf.n_sin_elevacion += 1  # sin elevación: no se inventa, se omite el punto
            continue
        easting = _a_numero(celda_c(row, c_e))
        northing = _a_numero(celda_c(row, c_n))
        elev = _a_numero(celda_c(row, c_elev))
        gr = grupos.get("|".join((f_arch, f_linea, f_vp)))

        if gr is not None and gr["antena"] != 0:
            antena, antena_archivo = gr["antena"], True
        else:
            antena, antena_archivo = ALTURA_ANTENA_STD, False

        # Coordenadas: inversión de la proyección del COG (preferida) o,
        # sin parámetros de proyección, promedio de las lecturas GPS.
        lat = lon = None
        de_media = False
        if tm is not None:
            try:
                lat, lon = tm_inverse(easting, northing, tm)
            except (ValueError, ZeroDivisionError, OverflowError):
                lat = lon = None
        if lat is None and gr is not None and gr["n_ll"]:
            lat, lon = gr["sum_lat"] / gr["n_ll"], gr["sum_lon"] / gr["n_ll"]
            de_media = True
            n_gps_media += 1
        if lat is None or lon is None:
            inf.warnings.append(f"VP {f_linea}{f_vp}: sin coordenadas válidas, omitido.")
            continue

        pt = InovaPoint(
            name=f"{f_linea}{f_vp}", lat=lat, lon=lon, height=elev,
            antenna_height=antena, antenna_from_file=antena_archivo,
            line_no=i, file_no=f_arch, track=f_linea, bin=f_vp,
            easting=easting, northing=northing,
            status=_texto(celda_c(row, c_status)) if c_status is not None else "",
            latlon_from_gps_mean=de_media,
        )
        if gr is not None:
            pt.units = list(gr["units"])
            pt.n_readings = gr["n"]
            pt.n_sats = int(round(gr["sum_sat"] / gr["n"]))
            pt.n_sats_min = int(gr["min_sat"]) if gr["min_sat"] is not None else None
            pt.pdop = round(gr["sum_pdop"] / gr["n"], 2)
            pt.hdop = round(gr["sum_hdop"] / gr["n"], 2)
            pt.vdop = round(gr["sum_vdop"] / gr["n"], 2)
            pt.quality = ", ".join(_quitar_numero_fix(q) for q in gr["quality"] if q) or None
            pt.base_station = " y ".join(gr["station"]) or None
            dt = _parse_fecha(gr["fecha_max"])
            if dt is not None:
                loc = dt + timedelta(hours=LOCAL_UTC_OFFSET_H)
                pt.survey_time_gmt = dt.strftime("%Y-%m-%d %H:%M:%S")
                pt.survey_time_local = loc.strftime("%Y-%m-%d %H:%M:%S")
                pt.julian_date = f"{loc.year}{loc.timetuple().tm_yday:03d}"
        else:
            inf.n_sin_gps += 1
        inf.points.append(pt)

    inf.n_fail = sum(1 for p in inf.points if p.status.lower() == "fail")
    if inf.n_sin_elevacion:
        inf.warnings.append(
            f"{inf.n_sin_elevacion} VP sin elevación en la hoja COG: omitidos (no se inventa la altura)."
        )
    if inf.n_sin_gps and hoja_gps is not None:
        inf.warnings.append(
            f"{inf.n_sin_gps} VP sin lecturas en la hoja GPS: se usó la altura de antena estándar de "
            f"{ALTURA_ANTENA_STD:.2f} m y quedan sin datos de calidad."
        )
    if n_gps_media:
        inf.warnings.append(
            f"{n_gps_media} VP con coordenadas tomadas del promedio de lecturas GPS (no se pudo "
            "invertir la proyección de Easting/Northing)."
        )
    if inf.n_fail:
        inf.warnings.append(f"{inf.n_fail} VP con estado 'Fail' en el control de calidad de Inova (se importan igual).")
    dup = inf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        inf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) (mismo VP registrado en más de un archivo; "
            f"ej: {ejemplos})."
        )
    if not inf.points:
        raise ValueError("La hoja COG no trae ningún VP con fila 'COG', coordenadas y elevación.")
    return inf


def _importar_xlrd():
    try:  # pragma: no cover - depende de si se importa como paquete o suelto
        from . import _xlrd as xlrd
    except ImportError:
        import _xlrd as xlrd
    return xlrd


def read_xls_sheets(path: str) -> Dict[str, List[List]]:
    """Lee un .xls con xlrd (copia incluida en `_xlrd/`) -> {hoja: filas}."""
    xlrd = _importar_xlrd()
    wb = xlrd.open_workbook(path)
    return {
        sh.name: [sh.row_values(r) for r in range(sh.nrows)]
        for sh in wb.sheets()
    }


def looks_like_inova_sheets(sheets: Dict[str, List[List]]) -> bool:
    return any(_es_hoja_cog(n, r) for n, r in sheets.items())


def parse_inova_file(path: str) -> InovaFile:
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".xls", ".xlsx"):
        raise ValueError("Se esperaba un archivo .xls exportado por Inova.")
    if ext == ".xlsx":
        raise ValueError(
            "El archivo es .xlsx: este formato lee el .xls original de Inova. Abra el libro en "
            "Excel y use 'Guardar como' > 'Libro de Excel 97-2003 (*.xls)'."
        )
    try:
        sheets = read_xls_sheets(path)
    except Exception as e:  # xlrd lanza varios tipos (XLRDError, CompDocError...)
        raise ValueError(f"No se pudo leer el libro Excel: {e}") from e
    return parse_inova_sheets(sheets, path=path)
