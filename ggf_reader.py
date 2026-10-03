# -*- coding: utf-8 -*-
"""
ggf_reader.py
-------------
Lector puro (sin dependencias de QGIS ni de GDAL) del formato binario
propietario ".ggf" ("TNL GRID FILE") usado por equipos y software Trimble
para distribuir modelos de geoide (grillas de ondulación N). No existe
documentación oficial del formato; la estructura del encabezado usada
aquí se tomó de la descripción publicada en
https://wiki.openstreetmap.org/wiki/Trimble_GGF y se verificó por
inspección directa contra un archivo real (GEOIDE-Ar16.ggf, modelo de
geoide de Argentina 2016, cuadrícula de 2220x1440 puntos a 1' de paso).

Estructura del encabezado (little-endian):
    offset 0x00 (2 bytes)  : versión (int16), no usada
    offset 0x02 (14 bytes) : firma "TNL GRID FILE\0"
    offset 0x10 (32 bytes) : nombre/descripción del modelo, terminado en \0
    offset 0x30 (8 bytes)  : ymin  -- latitud mínima, grados decimales (double)
    offset 0x38 (8 bytes)  : ymax  -- latitud máxima, grados decimales (double)
    offset 0x40 (8 bytes)  : xmin  -- longitud mínima, convención 0-360 este (double)
    offset 0x48 (8 bytes)  : xmax  -- longitud máxima, convención 0-360 este (double)
    offset 0x50 (8 bytes)  : dy    -- paso de latitud, grados (double)
    offset 0x58 (8 bytes)  : dx    -- paso de longitud, grados (double)
    offset 0x60 (4 bytes)  : nrows -- número de filas / paralelos (int32)
    offset 0x64 (4 bytes)  : ncols -- número de columnas / meridianos (int32)
    ... resto de metadatos (polo N/S, marca de "sin dato", escala, banderas
        de tipo de dato) -- no se usan en este lector ...

Los datos (float32 little-endian) no siempre empiezan exactamente en el
mismo offset en todas las variantes del formato, así que en vez de asumir
un tamaño de encabezado fijo, este lector calcula dónde empiezan a partir
del tamaño del archivo: tamaño_archivo - nrows*ncols*4. En el archivo de
referencia esto da un encabezado de 162 bytes.

El arreglo está guardado fila-mayor, con la fila 0 = ymax (el paralelo
más al NORTE) y la última fila = ymin (el más al sur) -- es decir, el
archivo ya trae las filas en la convención "norte arriba" que este
lector necesita, y NO hay que invertirlas.

CORRECCIÓN (post-v2.49.0): la primera versión de este lector asumía lo
contrario -- fila 0 = sur, requiriendo invertir el arreglo para exponerlo
"norte arriba" -- basándose únicamente en la descripción de la wiki de
OpenStreetMap, sin verificar contra puntos reales de referencia. Esto
producía una ondulación de geoide con el eje de latitud efectivamente
reflejado: por ejemplo, para GEOIDE-Ar16.ggf dicha versión daba N=42.2 m
en Ushuaia (54.8°S) y sólo N=12.5 m en Salta (24.8°S) -- exactamente al
revés de la geofísica real (el "alto" geoidal andino/boliviano está al
norte, cerca de Bolivia/Perú, no en la Patagonia austral). El usuario
reportó el síntoma en un punto concreto de `0502YC.dsc` (recnum
15535147, lat -37.07°): la "Elev. ortométrica" calculada daba 923.184 m,
mientras que GPSeismic y la calculadora del IGN de Argentina daban
920.948 m -- una diferencia de 2.236 m. Se verificó, leyendo el archivo
real byte a byte y probando ambas orientaciones contra ese punto y contra
tres ciudades de referencia (Buenos Aires, Ushuaia, Salta), que quitar la
inversión de filas reproduce el valor esperado en los cuatro casos
(target: 23.966 m vs. 24.009 m esperado -- diferencia de 4 cm, dentro del
margen normal de un método de interpolación bilineal simple vs. el que
use GPSeismic/IGN) y da una ondulación geodésicamente coherente en las
tres ciudades (Buenos Aires ~16.1 m, Ushuaia ~13.6 m, Salta ~33.0 m,
consistente con el alto geoidal conocido cerca de Bolivia/Perú). Ver
`test_real_argentina_file_if_available` para la prueba con el archivo
real.

Se ha observado, en el único archivo real disponible al escribir este
módulo, una celda aislada con un valor absurdo (~3.7e19) cerca de un
borde de la cuadrícula -- posiblemente una marca de "sin dato" o un
defecto del archivo. Por eso `sample()` descarta cualquier valor con
magnitud mayor a `NODATA_ABS_THRESHOLD` (ninguna ondulación de geoide
real en la Tierra supera unas pocas decenas de metros).
"""
from __future__ import annotations

import array
import struct
from typing import List, Optional

SIGNATURE = b"TNL GRID FILE"
_SIGNATURE_OFFSET = 2
_NAME_OFFSET = 0x10
_NAME_LEN = 0x30 - 0x10
_OFF_YMIN = 0x30
_OFF_YMAX = 0x38
_OFF_XMIN = 0x40
_OFF_XMAX = 0x48
_OFF_DY = 0x50
_OFF_DX = 0x58
_OFF_NROWS = 0x60
_OFF_NCOLS = 0x64
_MIN_HEADER_BYTES = _OFF_NCOLS + 4

NODATA_ABS_THRESHOLD = 1000.0  # |N| > esto se trata como celda sin dato válido


class GgfFormatError(ValueError):
    """El archivo no tiene la firma o la estructura esperada de un .ggf."""


class GgfGrid:
    """Grilla de ondulación de geoide ya cargada en memoria, con
    muestreo por interpolación bilineal. `rows_north_first[0]` debe ser
    la fila más al norte (mayor latitud)."""

    def __init__(self, xmin: float, ymin: float, dx: float, dy: float,
                 ncols: int, nrows: int, rows_north_first: List["array.array[float]"],
                 name: str = ""):
        self.xmin = xmin
        self.ymin = ymin
        self.dx = dx
        self.dy = dy
        self.ncols = ncols
        self.nrows = nrows
        self.name = name
        self._rows = rows_north_first
        self.ymax = ymin + (nrows - 1) * dy
        self.xmax = xmin + (ncols - 1) * dx

    def _value(self, row_idx: int, col_idx: int) -> Optional[float]:
        if row_idx < 0 or row_idx >= self.nrows or col_idx < 0 or col_idx >= self.ncols:
            return None
        v = self._rows[row_idx][col_idx]
        if v != v or abs(v) > NODATA_ABS_THRESHOLD:  # v != v detecta NaN
            return None
        return float(v)

    def sample(self, lon: float, lat: float) -> Optional[float]:
        """Interpola bilinealmente la ondulación N (metros) en (lon, lat)
        [WGS84, grados decimales]. Devuelve None si el punto cae fuera de
        la cuadrícula o si alguna de las 4 celdas vecinas no tiene un
        valor válido."""
        lon_n = lon
        # normalizar la longitud a la misma "vuelta" que usa la grilla
        # (el archivo puede usar convención 0-360 este o -180..180)
        while lon_n < self.xmin - 180:
            lon_n += 360
        while lon_n > self.xmin + 180:
            lon_n -= 360

        if not (self.xmin <= lon_n <= self.xmax and self.ymin <= lat <= self.ymax):
            return None
        if self.ncols < 2 or self.nrows < 2:
            return None

        col_f = (lon_n - self.xmin) / self.dx
        row_f = (self.ymax - lat) / self.dy  # fila 0 = norte

        col0 = min(int(col_f), self.ncols - 2)
        row0 = min(int(row_f), self.nrows - 2)
        col1 = col0 + 1
        row1 = row0 + 1
        tx = col_f - col0
        ty = row_f - row0

        v00 = self._value(row0, col0)
        v10 = self._value(row0, col1)
        v01 = self._value(row1, col0)
        v11 = self._value(row1, col1)
        if v00 is None or v10 is None or v01 is None or v11 is None:
            return None

        top = v00 + (v10 - v00) * tx
        bottom = v01 + (v11 - v01) * tx
        return top + (bottom - top) * ty


def read_ggf(path: str) -> GgfGrid:
    """Lee un archivo .ggf (TNL GRID FILE) de disco y devuelve un
    `GgfGrid` listo para muestrear. Lanza `GgfFormatError` si el archivo
    no tiene la firma esperada o si el tamaño del archivo no cuadra con
    las dimensiones declaradas en el encabezado."""
    with open(path, "rb") as f:
        data = f.read()
    return parse_ggf_bytes(data)


def parse_ggf_bytes(data: bytes) -> GgfGrid:
    if len(data) < _MIN_HEADER_BYTES:
        raise GgfFormatError("Archivo demasiado pequeño para ser un .ggf válido.")

    sig = data[_SIGNATURE_OFFSET:_SIGNATURE_OFFSET + len(SIGNATURE)]
    if sig != SIGNATURE:
        raise GgfFormatError(
            "No es un archivo .ggf de Trimble: falta la firma 'TNL GRID FILE'."
        )

    name_raw = data[_NAME_OFFSET:_NAME_OFFSET + _NAME_LEN]
    name = name_raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()

    try:
        ymin = struct.unpack_from("<d", data, _OFF_YMIN)[0]
        ymax_hdr = struct.unpack_from("<d", data, _OFF_YMAX)[0]
        xmin = struct.unpack_from("<d", data, _OFF_XMIN)[0]
        xmax_hdr = struct.unpack_from("<d", data, _OFF_XMAX)[0]
        dy = struct.unpack_from("<d", data, _OFF_DY)[0]
        dx = struct.unpack_from("<d", data, _OFF_DX)[0]
        nrows = struct.unpack_from("<i", data, _OFF_NROWS)[0]
        ncols = struct.unpack_from("<i", data, _OFF_NCOLS)[0]
    except struct.error as e:
        raise GgfFormatError(f"Encabezado .ggf incompleto o corrupto: {e}")

    if nrows <= 1 or ncols <= 1 or dx <= 0 or dy <= 0:
        raise GgfFormatError(
            "Encabezado .ggf inválido: dimensiones o paso de grilla no positivos "
            f"(nrows={nrows}, ncols={ncols}, dx={dx}, dy={dy})."
        )

    # Normalizar longitudes a la convención estándar (-180, 180], por si
    # el archivo las trae en convención 0-360 este (como el de referencia).
    if xmin > 180:
        xmin -= 360
    if xmax_hdr > 180:
        xmax_hdr -= 360

    n_points = nrows * ncols
    data_bytes_needed = n_points * 4
    header_size = len(data) - data_bytes_needed
    if header_size < _MIN_HEADER_BYTES or header_size > 4096:
        raise GgfFormatError(
            "El tamaño del archivo no coincide con nrows*ncols para datos "
            f"float32: se esperaban {data_bytes_needed} bytes de datos, mas un "
            f"encabezado razonable, mas quedaron {header_size} bytes de "
            "encabezado calculado."
        )

    raw = data[header_size:header_size + data_bytes_needed]
    flat = array.array("f")
    flat.frombytes(raw)

    # El archivo YA guarda la fila 0 = norte (ymax) -- confirmado contra
    # puntos reales de referencia, ver nota de corrección arriba en el
    # docstring del módulo. No hay que invertir el arreglo.
    rows_north_first = [flat[r * ncols:(r + 1) * ncols] for r in range(nrows)]

    return GgfGrid(
        xmin=xmin, ymin=ymin, dx=dx, dy=dy, ncols=ncols, nrows=nrows,
        rows_north_first=rows_north_first, name=name,
    )
