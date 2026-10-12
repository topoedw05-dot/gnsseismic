"""Modelos de velocidades VEMOS (SIRGAS) y corrección de época de coordenadas.

Módulo puro (sin Qt/QGIS), con pruebas unitarias en `test_gnsseismic.py`.

Los modelos VEMOS (Velocity Model for SIRGAS, DGFI-TUM) son grillas de 1° x 1°
con la velocidad horizontal media de la superficie terrestre para América
Latina y el Caribe (México, Centroamérica, el Caribe y Sudamérica -- NO sólo
Sudamérica, y tampoco el resto del mundo). Cada nodo trae las componentes
sur-norte (VSN) y oeste-este (VWE) en m/año, en el marco de referencia del
modelo. El archivo de texto no es un rectángulo completo: faltan nodos, así
que la cobertura real se calcula de los propios datos (`VemosGrid.cobertura`).

Cálculo (ver también la documentación del proyecto):

1. Para un punto P se buscan los 4 nodos de su celda y se pondera con la
   inversa de la distancia geodésica (los nodos sin dato no entran ni en el
   numerador ni en el denominador):
       VSNp = sum(VSN_i / D_i) / sum(1 / D_i)       (igual para VWEp)
2. La velocidad horizontal se lleva a componentes geocéntricas (Vx, Vy, Vz)
   rotando (VWE, VSN, 0) del sistema local este-norte-arriba al geocéntrico.
   Es lo mismo que pasar P a P3 = (lat + sn, lon + we) con incrementos
   angulares por año y restar las coordenadas geocéntricas de P3 y P, sin la
   ambigüedad de usar un arco de 1" de longitud (que cuenta dos veces cos(lat)).
3. Cambio de época: X(t_ref) = X(t_obs) + V * (t_ref - t_obs).

El modelo sólo describe el movimiento medio dentro de su periodo de vigencia;
los saltos cosísmicos (terremotos) no están incluidos.
"""

import math
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Elipsoide GRS80 (el de SIRGAS/MAGNA-SIRGAS/ITRF)
_A = 6378137.0
_F = 1.0 / 298.257222101
_E2 = _F * (2.0 - _F)
_R_MEDIO = 6371008.8  # sólo para las distancias de ponderación (ver `distancia_m`)

BASE_URL = "https://www.sirgas.org/fileadmin/docs/"

# clave -> datos del modelo. `t_ini`/`t_fin`: periodo (año decimal) de los datos
# que dieron origen al modelo, según el encabezado de cada archivo.
MODELOS: Dict[str, Dict] = {
    "VEMOS2022": {
        "nombre": "VEMOS2022", "marco": "ITRF2020", "t_ini": 2017.1, "t_fin": 2022.0,
        "archivo": "VEMOS2022.TXT",
    },
    "VEMOS2017": {
        "nombre": "VEMOS2017", "marco": "IGS14/ITRF2014", "t_ini": 2014.0, "t_fin": 2017.1,
        "archivo": "VEMOS2017.TXT",
    },
    "VEMOS2015": {
        "nombre": "VEMOS2015", "marco": "IGb08/ITRF2008", "t_ini": 2010.2, "t_fin": 2015.2,
        "archivo": "VEMOS2015.TXT",
    },
    "VEMOS2009": {
        "nombre": "VEMOS2009", "marco": "ITRF2005", "t_ini": 2000.0, "t_fin": 2009.6,
        "archivo": "VEMOS2009.TXT",
    },
}
ORDEN_MODELOS = ["VEMOS2022", "VEMOS2017", "VEMOS2015", "VEMOS2009"]

EPOCA_MAGNA_SIRGAS = 2018.0  # MAGNA-SIRGAS: ITRF2014, época 2018.0 (Resolución IGAC 715 de 2018)


def url_modelo(clave: str) -> str:
    return BASE_URL + MODELOS[clave]["archivo"]


# --------------------------------------------------------------------------
# Lectura de la grilla
# --------------------------------------------------------------------------
class VemosGrid:
    """Grilla VEMOS en memoria: {(lat, lon): (vsn, vwe)} en m/año."""

    def __init__(self, nodos: Dict[Tuple[float, float], Tuple[float, float]], paso: float = 1.0,
                 marco: Optional[str] = None, periodo: Optional[Tuple[float, float]] = None):
        self.nodos = nodos
        self.paso = paso
        self.marco = marco
        self.periodo = periodo
        lats = [k[0] for k in nodos]
        lons = [k[1] for k in nodos]
        self.lat_min, self.lat_max = min(lats), max(lats)
        self.lon_min, self.lon_max = min(lons), max(lons)

    def __len__(self):
        return len(self.nodos)

    def cobertura(self) -> Tuple[float, float, float, float]:
        """(lat_min, lat_max, lon_min, lon_max) de los nodos con dato."""
        return self.lat_min, self.lat_max, self.lon_min, self.lon_max

    def nodo(self, lat: float, lon: float) -> Optional[Tuple[float, float]]:
        return self.nodos.get((round(lat, 3), round(lon, 3)))


_NUM = r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?"
_FILA_RE = re.compile(r"^\s*(" + _NUM + r")\s+(" + _NUM + r")\s+(" + _NUM + r")\s+(" + _NUM + r")(?:\s+" + _NUM + r")*\s*$")


def parse_vemos_text(texto: str) -> VemosGrid:
    """Lee el texto de un VEMOS*.TXT. Las filas de datos son
    `lat lon VSN VWE [sigma_VSN sigma_VWE]` (VEMOS2009 trae sólo 4 columnas).
    Las líneas de encabezado se ignoran, salvo para leer "Reference frame" y
    "Time span" y detectar si las velocidades vienen en mm/a en vez de m/a.
    (El encabezado de VEMOS2015 rotula mal el orden de las columnas, pero sus
    filas siguen el mismo orden que los demás: lat, lon, VSN, VWE.)
    Lanza ValueError si no hay ninguna fila de datos."""
    nodos: Dict[Tuple[float, float], Tuple[float, float]] = {}
    marco = None
    periodo = None
    escala = 1.0
    for linea in texto.splitlines():
        m = _FILA_RE.match(linea)
        if m:
            lat, lon, vsn, vwe = (float(m.group(i)) for i in range(1, 5))
            if lon > 180.0:
                lon -= 360.0
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                nodos[(round(lat, 3), round(lon, 3))] = (vsn * escala, vwe * escala)
            continue
        mm = re.match(r"\s*Reference\s+Frame\s*:\s*(.+?)\s*$", linea, re.IGNORECASE)
        if mm:
            marco = mm.group(1)
            continue
        mm = re.match(r"\s*Time\s+span\s*:\s*(\d{4}(?:\.\d+)?)\s*-\s*(\d{4}(?:\.\d+)?)", linea, re.IGNORECASE)
        if mm:
            periodo = (float(mm.group(1)), float(mm.group(2)))
            continue
        if re.search(r"Velocity.*\[mm/a\]", linea, re.IGNORECASE):
            escala = 0.001
    if not nodos:
        raise ValueError("vemos_sin_datos")
    return VemosGrid(nodos, 1.0, marco, periodo)


def leer_vemos(ruta: str) -> VemosGrid:
    """Lee un VEMOS*.TXT de disco (los encabezados traen caracteres que no son
    UTF-8, por eso se lee como latin-1)."""
    with open(ruta, "r", encoding="latin-1") as fh:
        return parse_vemos_text(fh.read())


# --------------------------------------------------------------------------
# Geometría
# --------------------------------------------------------------------------
def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia (m) sobre la esfera de radio medio entre dos puntos. Sólo
    sirve para ponderar entre nodos de 1°: usar la distancia elipsoidal exacta
    cambia los pesos en menos de 0.5 %, es decir, la velocidad interpolada en
    mucho menos de 0.01 mm/año."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * _R_MEDIO * math.asin(min(1.0, math.sqrt(a)))


def geodetica_a_geocentrica(lat: float, lon: float, h: float = 0.0) -> Tuple[float, float, float]:
    p, l = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1.0 - _E2 * math.sin(p) ** 2)
    return (
        (n + h) * math.cos(p) * math.cos(l),
        (n + h) * math.cos(p) * math.sin(l),
        (n * (1.0 - _E2) + h) * math.sin(p),
    )


def geocentrica_a_geodetica(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """(lat°, lon°, h) por iteración (converge a < 1e-12 m en 4-5 pasos)."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - _E2))
    h = 0.0
    for _ in range(10):
        n = _A / math.sqrt(1.0 - _E2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n if abs(math.cos(lat)) > 1e-10 else abs(z) / abs(math.sin(lat)) - n * (1.0 - _E2)
        nueva = math.atan2(z, p * (1.0 - _E2 * n / (n + h)))
        if abs(nueva - lat) < 1e-15:
            lat = nueva
            break
        lat = nueva
    return math.degrees(lat), math.degrees(lon), h


# --------------------------------------------------------------------------
# Interpolación de la velocidad
# --------------------------------------------------------------------------
def interpolar_velocidad(grid: VemosGrid, lat: float, lon: float) -> Optional[Tuple[float, float, int]]:
    """(VSN, VWE, n_nodos) en m/año para P = (lat, lon), por ponderación con la
    inversa de la distancia entre los nodos de su celda que tengan dato.
    Devuelve None si NINGUNO de los 4 nodos de la celda tiene dato (el punto
    está fuera de la cobertura del modelo)."""
    if lon > 180.0:
        lon -= 360.0
    paso = grid.paso
    lat0 = math.floor(lat / paso) * paso
    lon0 = math.floor(lon / paso) * paso
    num_n = num_e = den = 0.0
    usados = 0
    for la in (lat0, lat0 + paso):
        for lo in (lon0, lon0 + paso):
            v = grid.nodo(la, lo)
            if v is None:
                continue
            d = distancia_m(lat, lon, la, lo)
            if d < 1e-6:  # P coincide con un nodo
                return v[0], v[1], 1
            num_n += v[0] / d
            num_e += v[1] / d
            den += 1.0 / d
            usados += 1
    if usados == 0:
        return None
    return num_n / den, num_e / den, usados


def velocidad_geocentrica(lat: float, lon: float, vsn: float, vwe: float) -> Tuple[float, float, float]:
    """(Vx, Vy, Vz) en m/año a partir de la velocidad horizontal local."""
    p, l = math.radians(lat), math.radians(lon)
    este = (-math.sin(l), math.cos(l), 0.0)
    norte = (-math.sin(p) * math.cos(l), -math.sin(p) * math.sin(l), math.cos(p))
    return tuple(vwe * este[i] + vsn * norte[i] for i in range(3))  # type: ignore[return-value]


def velocidad_geocentrica_por_incrementos(lat: float, lon: float, vsn: float, vwe: float) -> Tuple[float, float, float]:
    """Misma velocidad por el camino de incrementos angulares (P -> P3), con d
    = longitud de 1" de arco de meridiano; se deja sólo como contraste de
    `velocidad_geocentrica` (coinciden a menos de 0.1 mm/año)."""
    p = math.radians(lat)
    m = _A * (1.0 - _E2) / (1.0 - _E2 * math.sin(p) ** 2) ** 1.5
    d = m * math.radians(1.0 / 3600.0)
    sn = vsn / (3600.0 * d)
    we = vwe / (3600.0 * d * math.cos(p))
    x, y, z = geodetica_a_geocentrica(lat, lon)
    x3, y3, z3 = geodetica_a_geocentrica(lat + sn, lon + we)
    return x3 - x, y3 - y, z3 - z


# --------------------------------------------------------------------------
# Cambio de época
# --------------------------------------------------------------------------
class ResultadoEpoca:
    """Resultado de llevar un punto a otra época."""

    def __init__(self, lat, lon, h, desplazamiento_m, n_nodos, vsn, vwe):
        self.lat = lat
        self.lon = lon
        self.h = h
        self.desplazamiento_m = desplazamiento_m
        self.n_nodos = n_nodos
        self.vsn = vsn
        self.vwe = vwe


def cambiar_epoca(grid: VemosGrid, lat: float, lon: float, h: float,
                  t_obs: float, t_ref: float) -> Optional[ResultadoEpoca]:
    """Lleva (lat, lon, h) de la época `t_obs` a `t_ref` (años decimales) con la
    velocidad interpolada del modelo: X(t_ref) = X(t_obs) + V * (t_ref - t_obs).
    None si el punto está fuera de la cobertura del grid."""
    v = interpolar_velocidad(grid, lat, lon)
    if v is None:
        return None
    vsn, vwe, n = v
    vx, vy, vz = velocidad_geocentrica(lat, lon, vsn, vwe)
    dt = t_ref - t_obs
    x, y, z = geodetica_a_geocentrica(lat, lon, h)
    dx, dy, dz = vx * dt, vy * dt, vz * dt
    lat2, lon2, h2 = geocentrica_a_geodetica(x + dx, y + dy, z + dz)
    return ResultadoEpoca(lat2, lon2, h2, math.sqrt(dx * dx + dy * dy + dz * dz), n, vsn, vwe)


def fuera_de_vigencia(clave_modelo: str, t_obs: float, margen: float = 0.0) -> bool:
    """True si `t_obs` queda fuera del periodo de datos del modelo."""
    m = MODELOS[clave_modelo]
    return t_obs < m["t_ini"] - margen or t_obs > m["t_fin"] + margen


# --------------------------------------------------------------------------
# Época de observación a partir de las fechas de los archivos de campo
# --------------------------------------------------------------------------
def epoca_decimal(anio: int, dia_del_anio: float) -> float:
    """Año decimal de (año, día del año 1..366) a mediodía local aprox."""
    dias = 366 if (anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)) else 365
    return anio + (dia_del_anio - 0.5) / dias


def epoca_de_fecha(fecha: datetime) -> float:
    return epoca_decimal(fecha.year, fecha.timetuple().tm_yday)


def epoca_desde_juliano(texto) -> Optional[float]:
    """Año decimal de una fecha juliana "AAAADDD" (p. ej. "2018018")."""
    if texto is None:
        return None
    s = str(texto).strip()
    if not re.fullmatch(r"\d{7}", s):
        return None
    anio, dia = int(s[:4]), int(s[4:])
    if not (1 <= dia <= 366) or anio < 1980:
        return None
    return epoca_decimal(anio, dia)


_FORMATOS_FECHA = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%m/%d/%y %H:%M:%S", "%m/%d/%y",
)


def epoca_desde_texto_fecha(texto) -> Optional[float]:
    """Año decimal de un texto de fecha (y hora opcional) en alguno de los
    formatos habituales (ISO, mes/día/año). None si no se reconoce."""
    if not texto:
        return None
    s = str(texto).strip()
    for fmt in _FORMATOS_FECHA:
        try:
            return epoca_de_fecha(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None


def epoca_de_fila(fila: dict) -> Optional[float]:
    """Época de observación de una fila de la previsualización: fecha juliana
    del archivo si existe; si no, la fecha del punto (GMT y luego local)."""
    e = epoca_desde_juliano(fila.get("julian_date_local"))
    if e is not None:
        return e
    for clave in ("survey_time_gmt", "survey_time_local"):
        e = epoca_desde_texto_fecha(fila.get(clave))
        if e is not None:
            return e
    return None


def texto_cobertura(grid: VemosGrid) -> str:
    """"55°S a 32°N, 120°W a 35°W" para mostrar en pantalla."""
    la0, la1, lo0, lo1 = grid.cobertura()

    def lat_txt(v):
        return f"{abs(v):g}°{'N' if v >= 0 else 'S'}"

    def lon_txt(v):
        return f"{abs(v):g}°{'E' if v >= 0 else 'W'}"

    return f"{lat_txt(la0)} a {lat_txt(la1)}, {lon_txt(lo0)} a {lon_txt(lo1)}"


def nodos_vecinos_faltantes(grid: VemosGrid, lat: float, lon: float) -> List[Tuple[float, float]]:
    """Nodos de la celda de P sin dato (para depurar/avisar de cobertura parcial)."""
    paso = grid.paso
    lat0 = math.floor(lat / paso) * paso
    lon0 = math.floor(lon / paso) * paso
    return [(la, lo) for la in (lat0, lat0 + paso) for lo in (lon0, lon0 + paso) if grid.nodo(la, lo) is None]
