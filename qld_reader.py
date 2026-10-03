# -*- coding: utf-8 -*-
"""Lector del formato binario propietario .qld ("QLD9"), usado por
software de diseño/QC de puntos sísmicos. Reconstruido por ingeniería
inversa contra un archivo real aportado por el usuario
(`RP_QC_19-08-26_final.qld`, 12191 puntos receptores de un levantamiento
en Patagonia, Argentina) y VERIFICADO matemáticamente, no adivinado:
transformando las coordenadas geográficas (WGS84) que trae cada punto a
Gauss-Krüger Faja 2 Argentina con WGS84 como elipsoide (la
proyección/datum que declara el propio encabezado del archivo), el
resultado coincide con las coordenadas planas (Este/Norte) que el mismo
archivo trae para ese punto con una diferencia menor a un milímetro en
los 12191 puntos -- confirma que el layout de bytes de abajo es
correcto, no una coincidencia de offsets.

Layout binario (little-endian, sin dependencias externas para leerlo):

    Encabezado (268 bytes):
        bytes    0- 3  ( 4): firma "QLD9"
        bytes    4-11  ( 8): versión de formato (double) -- 1.0 en la
                              muestra
        bytes   12-75  (64): nombre del sistema de coordenadas (texto,
                              relleno con \\0), ej. "Argentine_Coordinate_Systems"
        bytes   76-139 (64): nombre de la zona/faja (texto), ej. "Zone II"
        bytes  140-203 (64): datum/elipsoide (texto), ej. "WGS84"
        bytes  204-267 (64): unidades (texto), ej. "METERS"

    A partir del byte 268, un registro de 88 bytes por punto:
        bytes  0-15 (16): nombre del punto (texto, relleno con \\0)
        bytes 16-23 ( 8): Este  (double) -- coordenada plana en el
                          sistema que declara el encabezado
        bytes 24-31 ( 8): Norte (double)
        bytes 32-39 ( 8): Cota/Z (double) -- 0.0 en TODOS los puntos del
                          archivo de muestra (parece ser siempre un
                          archivo de diseño puramente horizontal, sin
                          elevación real -- se toma tal cual venga, sin
                          inventar nada si algún otro archivo sí la trae)
        bytes 40-47 ( 8): Latitud  WGS84 (double, grados decimales)
        bytes 48-55 ( 8): Longitud WGS84 (double, grados decimales)
        bytes 56-87 (32): sin usar -- constante ("51" + relleno) en TODO
                          el archivo de muestra; no se expone porque no
                          varía ni una sola vez en los 12191 puntos y no
                          se pudo confirmar su significado contra ningún
                          dato de referencia.

Como el plugin ya tiene, para cualquier otro origen (.dc, Hi-Target), la
regla de preferir siempre las coordenadas geográficas (WGS84) sobre una
grilla local/plana cuando el archivo trae ambas -- porque el CRS de la
grilla no se puede verificar de forma genérica para cualquier
zona/datum que declare el encabezado --, este parser expone también
lat/lon y es eso lo que usa `gnsseismic_windows.py` para transformarlas
al CRS de trabajo del proyecto, dejando Este/Norte sólo como referencia
informativa (no se usan para nada, pero si hiciera falta compararlas
contra las geográficas para depurar un archivo problemático, ya están
disponibles en cada `QldPoint`)."""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import List

MAGIC = b"QLD9"
_HEADER_TEXT_FIELD_LEN = 64
_HEADER_LEN = 4 + 8 + _HEADER_TEXT_FIELD_LEN * 4  # 268
_RECORD_LEN = 88
_NAME_FIELD_LEN = 16


@dataclass
class QldPoint:
    name: str
    line_no: int  # posición del punto dentro del archivo (0-based) -- identidad estable del punto
    este: float
    norte: float
    z: float
    lat: float
    lon: float


@dataclass
class QldFile:
    path: str
    coord_system_name: str
    zone_name: str
    datum: str
    units: str
    points: List[QldPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def n_points(self) -> int:
        return len(self.points)


def looks_like_qld(path: str) -> bool:
    """Reconoce el archivo por su firma binaria (los primeros 4 bytes),
    sin intentar interpretar el resto."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == MAGIC
    except OSError:
        return False


def _read_text_field(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1").strip()


def parse_qld_bytes(data: bytes, path: str = "") -> QldFile:
    if len(data) < _HEADER_LEN or data[0:4] != MAGIC:
        raise ValueError("No es un archivo .qld reconocible (falta la firma 'QLD9').")

    coord_system_name = _read_text_field(data[12:76])
    zone_name = _read_text_field(data[76:140])
    datum = _read_text_field(data[140:204])
    units = _read_text_field(data[204:268])

    body = data[_HEADER_LEN:]
    warnings: List[str] = []
    n_full, remainder = divmod(len(body), _RECORD_LEN)
    if remainder:
        warnings.append(
            f"El archivo trae {remainder} byte(s) sobrantes al final que no "
            f"completan un registro de punto -- se ignoraron."
        )

    # El único archivo real disponible para verificar este formato declara
    # datum "WGS84"; si algún otro archivo declarara un datum distinto, la
    # latitud/longitud que trae probablemente estén en ESE datum, no en
    # WGS84 -- tratarlas igual como WGS84 (lo que hace este parser, y lo
    # que asume `gnsseismic_windows.py` al transformarlas) podría introducir
    # un corrimiento real. Se avisa en vez de asumir en silencio.
    if "wgs84" not in datum.lower():
        warnings.append(
            f"El archivo declara datum '{datum}' (no WGS84) -- la latitud/"
            f"longitud de cada punto se está usando igual como si fueran "
            f"WGS84. Si las coordenadas quedan desplazadas, puede hacer "
            f"falta una transformación de datum adicional para este datum."
        )

    points: List[QldPoint] = []
    for i in range(n_full):
        rec = body[i * _RECORD_LEN:(i + 1) * _RECORD_LEN]
        name = _read_text_field(rec[0:_NAME_FIELD_LEN])
        if not name:
            warnings.append(f"Punto #{i + 1}: sin nombre -- se omitió.")
            continue
        try:
            este, norte, z, lat, lon = struct.unpack("<5d", rec[16:56])
        except struct.error:
            warnings.append(f"Punto #{i + 1} ('{name}'): no se pudo leer sus coordenadas -- se omitió.")
            continue
        points.append(QldPoint(name=name, line_no=i, este=este, norte=norte, z=z, lat=lat, lon=lon))

    repetidos = [nombre for nombre, n in Counter(p.name for p in points).items() if n > 1]
    if repetidos:
        ejemplo = ", ".join(sorted(repetidos)[:5])
        warnings.append(f"{len(repetidos)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplo}).")

    return QldFile(
        path=path, coord_system_name=coord_system_name, zone_name=zone_name,
        datum=datum, units=units, points=points, warnings=warnings,
    )


def parse_qld_file(path: str) -> QldFile:
    with open(path, "rb") as f:
        data = f.read()
    return parse_qld_bytes(data, path=path)
