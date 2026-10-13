"""Modelo de velocidades VEL-Ar v2.0 (IGN Argentina / Ohio State University):
cambio de época de coordenadas GNSS en Argentina.

Módulo puro (sin Qt/QGIS), con pruebas en `test_gnsseismic.py`.

Por qué existe: en el centro-oeste argentino (Mendoza, Neuquén, San Juan...)
los sismos de Maule (27-feb-2010, época 2010.159) e Illapel (16-sep-2015, época
2015.710) rompieron el movimiento lineal de la corteza, y los modelos de
velocidades lineales como VEMOS no sirven allí (ver el Manual VEL-Ar v2.0 del
IGN). VEL-Ar modela la trayectoria completa del punto:

    X(t) = X0 + v·(t - t0) + Σ_sismos [ b·1(t >= tj) + a·log10(1 + (t - tj)/T) ]

con v la velocidad intersísmica, b el salto cosísmico y a la amplitud de la
deformación postsísmica de cada sismo (T = 0.5 años). El cambio de época entre
`ti` y `tf` es la diferencia de las trayectorias en ambas épocas.

Las cinco grillas (`velar_data/`) son las del IGN. La interpolación y el resto de
la lógica están REPRODUCIDOS a partir del manual y verificados contra el
programa oficial `velar` (Linux x64, v2.0) en cientos de puntos y épocas
aleatorias: diferencia mediana 0.03 cm y máxima menor de 1 cm (el propio modelo
declara unos 5 cm de error):

* Interpolación: ponderación con la inversa del cuadrado de la distancia (en
  proyección UTM) de los 4 nodos más cercanos de cada grilla.
* Corte: en las grillas cosísmica de Maule y postsísmicas, si el 4.º nodo más
  cercano está a más de 30 km el valor es 0 (el programa oficial hace lo mismo).
* Marco: las coordenadas están en POSGAR07b (cercano a IGS14). Cuando la época
  destino es 2006.632 se entrega además POSGAR07 con una transformación de 7
  parámetros; si la época inicial es 2006.632 la entrada se toma como POSGAR07.
* La altura no cambia con el modelo (el movimiento es horizontal).
"""

import heapq
import math
import os
from typing import Dict, List, Optional, Tuple

_A = 6378137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)
_EP2 = _E2 / (1.0 - _E2)

EPOCA_POSGAR07 = 2006.632
T_MAULE = 2010.159
T_ILLAPEL = 2015.710
T_RELAJACION = 0.5          # años (constante T de la deformación postsísmica)
CORTE_M = 30000.0           # corte (m) del 4.º nodo para las grillas con corte
MERIDIANO_CENTRAL = -63.0   # el de las grillas (UTM faja 20); no cambia el resultado
COBERTURA_MAX_M = 80000.0   # nodo de la grilla lineal más cercano a más de esto = fuera de Argentina

ARCHIVOS = {
    "lin": "vel-ar-lin.txt",
    "cos_maule": "vel-ar-cos-maule.txt",
    "cos_illapel": "vel-ar-cos-illapel.txt",
    "log_maule": "vel-ar-log-maule.txt",
    "log_illapel": "vel-ar-log-illapel.txt",
}
_CON_CORTE = {"cos_maule", "log_maule", "log_illapel"}

# Transformación POSGAR07b -> POSGAR07 (7 parámetros, rotaciones pequeñas),
# ajustada a las salidas del programa oficial (residuo < 1e-7 m):
# dX = T + s·X + R × X     (X en metros, geocéntrico)
_HELMERT_T = (-0.00103003, -0.00099998, -0.00062002)
_HELMERT_S = 1.8101031e-09
_HELMERT_R = (7.19998e-10, -4.40003e-10, 5.0e-11)


# --------------------------------------------------------------------------
# Geometría
# --------------------------------------------------------------------------
def geodetica_a_geocentrica(lat: float, lon: float, h: float = 0.0) -> Tuple[float, float, float]:
    p, l = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1.0 - _E2 * math.sin(p) ** 2)
    return ((n + h) * math.cos(p) * math.cos(l), (n + h) * math.cos(p) * math.sin(l),
            (n * (1.0 - _E2) + h) * math.sin(p))


def geocentrica_a_geodetica(x: float, y: float, z: float) -> Tuple[float, float, float]:
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - _E2))
    h = 0.0
    for _ in range(10):
        n = _A / math.sqrt(1.0 - _E2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - n
        nueva = math.atan2(z, p * (1.0 - _E2 * n / (n + h)))
        if abs(nueva - lat) < 1e-15:
            lat = nueva
            break
        lat = nueva
    return math.degrees(lat), math.degrees(lon), h


def _utm(lat: float, lon: float, lon0: float = MERIDIANO_CENTRAL, k0: float = 0.9996) -> Tuple[float, float]:
    """(este, norte) UTM en metros (sin falsos orígenes) con meridiano central `lon0`."""
    phi = math.radians(lat)
    dl = math.radians(lon - lon0)
    s, c, t = math.sin(phi), math.cos(phi), math.tan(phi)
    n = _A / math.sqrt(1.0 - _E2 * s * s)
    t2, c2, a = t * t, _EP2 * c * c, dl * c
    e4, e6 = _E2 * _E2, _E2 ** 3
    m = _A * ((1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
              - (35 * e6 / 3072) * math.sin(6 * phi))
    x = k0 * n * (a + (1 - t2 + c2) * a ** 3 / 6 + (5 - 18 * t2 + t2 * t2 + 72 * c2 - 58 * _EP2) * a ** 5 / 120)
    y = k0 * (m + n * t * (a * a / 2 + (5 - t2 + 9 * c2 + 4 * c2 * c2) * a ** 4 / 24
                           + (61 - 58 * t2 + t2 * t2 + 600 * c2 - 330 * _EP2) * a ** 6 / 720))
    return x, y


def _neu_a_xyz(lat: float, lon: float, n: float, e: float, u: float) -> Tuple[float, float, float]:
    p, l = math.radians(lat), math.radians(lon)
    sp, cp, sl, cl = math.sin(p), math.cos(p), math.sin(l), math.cos(l)
    return (-sl * e - sp * cl * n + cp * cl * u,
            cl * e - sp * sl * n + cp * sl * u,
            cp * n + sp * u)


def _helmert(x: float, y: float, z: float, signo: float) -> Tuple[float, float, float]:
    """POSGAR07b -> POSGAR07 (signo = +1) o inversa (signo = -1)."""
    tx, ty, tz = _HELMERT_T
    rx, ry, rz = _HELMERT_R
    s = _HELMERT_S
    dx = tx + s * x + (-rz * y + ry * z)
    dy = ty + s * y + (rz * x - rx * z)
    dz = tz + s * z + (-ry * x + rx * y)
    return x + signo * dx, y + signo * dy, z + signo * dz


# --------------------------------------------------------------------------
# Grillas
# --------------------------------------------------------------------------
class _Grilla:
    """Nodos (x, y UTM; componente norte; componente este) con un índice por
    celdas de 100 km para buscar los 4 más cercanos sin recorrer todo."""

    CELDA = 100000.0

    def __init__(self, nodos: List[Tuple[float, float, float, float]], lats: List[float], lons: List[float]):
        self.nodos = nodos
        self.lats = lats
        self.lons = lons
        self.indice: Dict[Tuple[int, int], List[int]] = {}
        for i, (x, y, _, _) in enumerate(nodos):
            self.indice.setdefault((int(x // self.CELDA), int(y // self.CELDA)), []).append(i)

    def cuatro_cercanos(self, x: float, y: float) -> List[Tuple[float, int]]:
        cx, cy = int(x // self.CELDA), int(y // self.CELDA)
        radio = 1
        while True:
            cand = []
            for ix in range(cx - radio, cx + radio + 1):
                for iy in range(cy - radio, cy + radio + 1):
                    cand.extend(self.indice.get((ix, iy), ()))
            if len(cand) >= 4 or radio > 60:
                break
            radio += 1
        # Con `radio` celdas alrededor, la 4.ª distancia puede ser mayor que el
        # alcance seguro (radio * CELDA): se amplía un anillo más para no perder
        # un nodo más cercano que esté justo fuera.
        if len(cand) >= 4:
            radio += 1
            cand = []
            for ix in range(cx - radio, cx + radio + 1):
                for iy in range(cy - radio, cy + radio + 1):
                    cand.extend(self.indice.get((ix, iy), ()))
        dist = ((math.hypot(self.nodos[i][0] - x, self.nodos[i][1] - y), i) for i in cand)
        return heapq.nsmallest(4, dist)

    def interpolar(self, x: float, y: float, con_corte: bool) -> Optional[Tuple[float, float]]:
        """(componente norte, componente este) o None si no hay 4 nodos (o están
        a más de 30 km, en las grillas con corte)."""
        c = self.cuatro_cercanos(x, y)
        if len(c) < 4:
            return None
        if con_corte and c[-1][0] > CORTE_M:
            return None
        if c[0][0] < 1e-6:
            n = self.nodos[c[0][1]]
            return n[2], n[3]
        pesos = [1.0 / (d * d) for d, _ in c]
        tot = sum(pesos)
        vn = sum(p * self.nodos[i][2] for p, (_, i) in zip(pesos, c)) / tot
        ve = sum(p * self.nodos[i][3] for p, (_, i) in zip(pesos, c)) / tot
        return vn, ve


def _leer_grilla(ruta: str) -> _Grilla:
    nodos = []
    lats: List[float] = []
    lons: List[float] = []
    with open(ruta, "r", encoding="latin-1") as fh:
        for linea in fh:
            partes = linea.split()
            if len(partes) < 4:
                continue
            try:
                lat, lon, vn, ve = (float(p) for p in partes[:4])
            except ValueError:
                continue
            x, y = _utm(lat, lon)
            nodos.append((x, y, vn, ve))
            lats.append(lat)
            lons.append(lon)
    if not nodos:
        raise ValueError("velar_sin_datos")
    return _Grilla(nodos, lats, lons)


class ModeloVelAr:
    """Las cinco grillas de VEL-Ar v2.0 cargadas en memoria."""

    def __init__(self, grillas: Dict[str, _Grilla]):
        self.grillas = grillas

    def __len__(self):
        return sum(len(g.nodos) for g in self.grillas.values())

    @classmethod
    def desde_carpeta(cls, carpeta: str) -> "ModeloVelAr":
        return cls({clave: _leer_grilla(os.path.join(carpeta, archivo)) for clave, archivo in ARCHIVOS.items()})

    def cobertura(self) -> Tuple[float, float, float, float]:
        """(lat_min, lat_max, lon_min, lon_max) de los nodos de la grilla lineal."""
        g = self.grillas["lin"]
        return min(g.lats), max(g.lats), min(g.lons), max(g.lons)


# --------------------------------------------------------------------------
# Cambio de época
# --------------------------------------------------------------------------
class ResultadoVelAr:
    """Resultado de llevar un punto de la época `ti` a `tf`."""

    def __init__(self, lat, lon, h, desplazamiento_m, componentes, lat_p07=None, lon_p07=None, h_p07=None):
        self.lat = lat                      # POSGAR07b en `tf` (o POSGAR07 si `tf` = 2006.632, ver `p07`)
        self.lon = lon
        self.h = h
        self.desplazamiento_m = desplazamiento_m
        self.componentes = componentes      # {"intersismica": (n, e), "maule": (n, e), "illapel": (n, e)} en metros
        self.lat_p07 = lat_p07
        self.lon_p07 = lon_p07
        self.h_p07 = h_p07


def _salto(t: float, tj: float) -> float:
    return 1.0 if t >= tj else 0.0


def _log(t: float, tj: float) -> float:
    return math.log10(1.0 + (t - tj) / T_RELAJACION) if t >= tj else 0.0


def esta_en_cobertura(modelo: ModeloVelAr, lat: float, lon: float) -> bool:
    """True si el punto cae dentro de la zona que cubre la grilla de velocidades
    lineales (Argentina y alrededores)."""
    x, y = _utm(lat, lon)
    c = modelo.grillas["lin"].cuatro_cercanos(x, y)
    return bool(c) and c[0][0] <= COBERTURA_MAX_M


def desplazamiento_neu(modelo: ModeloVelAr, lat: float, lon: float, ti: float, tf: float) -> Optional[Dict[str, Tuple[float, float]]]:
    """Desplazamiento horizontal (norte, este) en metros entre `ti` y `tf`, por
    componente. None si el punto está fuera de la cobertura."""
    if not esta_en_cobertura(modelo, lat, lon):
        return None
    x, y = _utm(lat, lon)
    g = modelo.grillas
    v = g["lin"].interpolar(x, y, False) or (0.0, 0.0)
    comp = {"intersismica": (v[0] * (tf - ti), v[1] * (tf - ti))}
    for nombre, tj in (("maule", T_MAULE), ("illapel", T_ILLAPEL)):
        cs = g["cos_" + nombre].interpolar(x, y, "cos_" + nombre in _CON_CORTE) or (0.0, 0.0)
        lg = g["log_" + nombre].interpolar(x, y, True) or (0.0, 0.0)
        ds = _salto(tf, tj) - _salto(ti, tj)
        dl = _log(tf, tj) - _log(ti, tj)
        comp[nombre] = (cs[0] * ds + lg[0] * dl, cs[1] * ds + lg[1] * dl)
    return comp


def cambiar_epoca(modelo: ModeloVelAr, lat: float, lon: float, h: float, ti: float, tf: float) -> Optional[ResultadoVelAr]:
    """Lleva (lat, lon, h) de la época `ti` a `tf` con VEL-Ar. Devuelve None si el
    punto está fuera de la cobertura del modelo.

    * Si `ti` es 2006.632 la coordenada de entrada se toma como POSGAR07 y se
      pasa a POSGAR07b antes de aplicar el desplazamiento.
    * Si `tf` es 2006.632 el resultado principal (`lat`, `lon`, `h`) queda en
      POSGAR07b y `lat_p07`, `lon_p07`, `h_p07` traen la coordenada POSGAR07
      (la oficial); si no, esos tres valores son None."""
    comp = desplazamiento_neu(modelo, lat, lon, ti, tf)
    if comp is None:
        return None
    x, y, z = geodetica_a_geocentrica(lat, lon, h)
    if abs(ti - EPOCA_POSGAR07) < 5e-4:
        x, y, z = _helmert(x, y, z, -1.0)
    n = sum(c[0] for c in comp.values())
    e = sum(c[1] for c in comp.values())
    dx, dy, dz = _neu_a_xyz(lat, lon, n, e, 0.0)
    xf, yf, zf = x + dx, y + dy, z + dz
    lat2, lon2, h2 = geocentrica_a_geodetica(xf, yf, zf)
    res = ResultadoVelAr(lat2, lon2, h2, math.hypot(n, e), comp)
    if abs(tf - EPOCA_POSGAR07) < 5e-4:
        res.lat_p07, res.lon_p07, res.h_p07 = geocentrica_a_geodetica(*_helmert(xf, yf, zf, 1.0))
    return res


def texto_cobertura(modelo: ModeloVelAr) -> str:
    """"55°S a 18°S, 75°W a 40°W" (caja de la grilla lineal) para mostrar en pantalla."""
    la0, la1, lo0, lo1 = modelo.cobertura()

    def lat_txt(v):
        return f"{abs(round(v)):g}°{'N' if v >= 0 else 'S'}"

    def lon_txt(v):
        return f"{abs(round(v)):g}°{'E' if v >= 0 else 'W'}"

    return f"{lat_txt(la0)} a {lat_txt(la1)}, {lon_txt(lo0)} a {lon_txt(lo1)}"
