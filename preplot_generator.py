# -*- coding: utf-8 -*-
"""
preplot_generator.py
---------------------
Generación de puntos de preplot sísmico (diseño), sin dependencias de
QGIS/PyQt: lógica pura para poder probarla de forma aislada.

Dos modos, como se pidió que funcionara "al estilo GPSeismic":

- Grilla 3D: a partir de un punto de origen, un azimut, espaciamientos
  entre líneas y entre estaciones, y cantidad de líneas/estaciones.
- Línea 2D: una sola línea recta, definida entre dos puntos o por un
  punto de origen + azimut + longitud, con estaciones equiespaciadas.

Los nombres de punto (Station_Text) se arman concatenando el número de
línea y el número de estación con ancho fijo (relleno de ceros a la
izquierda), igual que la convención observada en los archivos .dc reales
del usuario (ej. línea 1025 + estación 5092 -> "10255092").
"""

import math
from dataclasses import dataclass
from typing import List


@dataclass
class PreplotPoint:
    name: str
    track: int
    bin: int
    x: float
    y: float
    descriptor: str = ""


def _format_number(n: float, digits: int) -> str:
    """Formatea un número de línea/estación a texto de ancho fijo,
    rellenando con ceros a la izquierda. Acepta enteros o decimales
    (p.ej. líneas "1025.5"): si no es entero, se usan tantos dígitos
    como haga falta y no se trunca (evita perder información), aunque
    eso puede hacer que el nombre resultante sea más largo que
    `digits` en esos casos.
    """
    if float(n).is_integer():
        return str(int(n)).zfill(digits)
    return str(n)


def format_point_name(line_number: float, station_number: float, line_digits: int = 4, station_digits: int = 4) -> str:
    """Arma un nombre de punto concatenando línea + estación con ancho
    fijo (relleno de ceros a la izquierda) -- la misma convención que
    usan los preplots generados por este módulo (ver el docstring de
    arriba). Se reutiliza al importar un preplot externo (SPS) para que
    sus puntos queden nombrados igual que si se hubieran generado aquí.
    """
    return _format_number(line_number, line_digits) + _format_number(station_number, station_digits)


def _bearing_to_dxdy(azimuth_deg: float):
    """Convierte un azimut (grados, medido en sentido horario desde el
    Norte, convención topográfica/náutica estándar) a un vector unitario
    (dx, dy) en un sistema cartesiano X=Este, Y=Norte.
    """
    rad = math.radians(azimuth_deg)
    return math.sin(rad), math.cos(rad)


def generate_grid_preplot(
    origin_x: float,
    origin_y: float,
    azimuth_deg: float,
    line_spacing: float,
    station_spacing: float,
    n_lines: int,
    n_stations: int,
    first_line_number: int = 1,
    line_increment: int = 1,
    first_station_number: int = 1,
    station_increment: int = 1,
    line_digits: int = 4,
    station_digits: int = 4,
    descriptor: str = "",
) -> List[PreplotPoint]:
    """Genera una grilla ortogonal de puntos (preplot 3D).

    `azimuth_deg` es la dirección a lo largo de la cual avanzan las
    estaciones dentro de cada línea (el rumbo de las líneas). Las
    líneas se separan entre sí perpendicularmente a esa dirección
    (azimuth_deg + 90°).

    Es una grilla rectangular recta; no incluye patrones tipo "slalom"
    o desplazamientos irregulares entre líneas (no pedidos).
    """
    if n_lines <= 0 or n_stations <= 0:
        raise ValueError("n_lines y n_stations deben ser mayores que 0")
    if line_spacing <= 0 or station_spacing <= 0:
        raise ValueError("los espaciamientos deben ser mayores que 0")

    dx_estacion, dy_estacion = _bearing_to_dxdy(azimuth_deg)
    dx_linea, dy_linea = _bearing_to_dxdy(azimuth_deg + 90.0)

    puntos = []
    for i in range(n_lines):
        line_number = first_line_number + i * line_increment
        line_origin_x = origin_x + i * line_spacing * dx_linea
        line_origin_y = origin_y + i * line_spacing * dy_linea
        for j in range(n_stations):
            station_number = first_station_number + j * station_increment
            x = line_origin_x + j * station_spacing * dx_estacion
            y = line_origin_y + j * station_spacing * dy_estacion
            name = _format_number(line_number, line_digits) + _format_number(station_number, station_digits)
            puntos.append(PreplotPoint(
                name=name, track=int(line_number), bin=int(station_number),
                x=x, y=y, descriptor=descriptor,
            ))
    return puntos


def generate_line_preplot_two_points(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    station_spacing: float,
    line_number: int,
    first_station_number: int = 1,
    station_increment: int = 1,
    line_digits: int = 4,
    station_digits: int = 4,
    include_end: bool = True,
    descriptor: str = "",
) -> List[PreplotPoint]:
    """Genera una línea 2D de puntos equiespaciados entre dos puntos
    dados. El número de estaciones se calcula a partir de la distancia
    total y el espaciamiento; si `include_end` es True y la distancia
    no es múltiplo exacto del espaciamiento, se agrega igualmente el
    punto final (puede quedar a una distancia distinta del resto).
    """
    if station_spacing <= 0:
        raise ValueError("el espaciamiento debe ser mayor que 0")
    dist = math.hypot(end_x - start_x, end_y - start_y)
    if dist == 0:
        raise ValueError("el punto inicial y final no pueden ser el mismo")
    dx = (end_x - start_x) / dist
    dy = (end_y - start_y) / dist

    n_completas = int(dist // station_spacing) + 1  # incluye la estación en el punto inicial
    puntos = []
    for j in range(n_completas):
        d = j * station_spacing
        station_number = first_station_number + j * station_increment
        x = start_x + d * dx
        y = start_y + d * dy
        name = _format_number(line_number, line_digits) + _format_number(station_number, station_digits)
        puntos.append(PreplotPoint(
            name=name, track=int(line_number), bin=int(station_number),
            x=x, y=y, descriptor=descriptor,
        ))

    ultima_distancia = (n_completas - 1) * station_spacing
    if include_end and abs(ultima_distancia - dist) > 1e-6:
        station_number = first_station_number + n_completas * station_increment
        name = _format_number(line_number, line_digits) + _format_number(station_number, station_digits)
        puntos.append(PreplotPoint(
            name=name, track=int(line_number), bin=int(station_number),
            x=end_x, y=end_y, descriptor=descriptor,
        ))
    return puntos


def generate_line_preplot_azimuth(
    start_x: float,
    start_y: float,
    azimuth_deg: float,
    length: float,
    station_spacing: float,
    line_number: int,
    first_station_number: int = 1,
    station_increment: int = 1,
    line_digits: int = 4,
    station_digits: int = 4,
    descriptor: str = "",
) -> List[PreplotPoint]:
    """Genera una línea 2D a partir de un punto de origen, un azimut y
    una longitud total, con estaciones equiespaciadas (la última
    estación puede quedar antes del extremo exacto si la longitud no es
    múltiplo del espaciamiento).
    """
    if station_spacing <= 0:
        raise ValueError("el espaciamiento debe ser mayor que 0")
    if length <= 0:
        raise ValueError("la longitud debe ser mayor que 0")

    dx, dy = _bearing_to_dxdy(azimuth_deg)
    n_estaciones = int(length // station_spacing) + 1

    puntos = []
    for j in range(n_estaciones):
        d = j * station_spacing
        station_number = first_station_number + j * station_increment
        x = start_x + d * dx
        y = start_y + d * dy
        name = _format_number(line_number, line_digits) + _format_number(station_number, station_digits)
        puntos.append(PreplotPoint(
            name=name, track=int(line_number), bin=int(station_number),
            x=x, y=y, descriptor=descriptor,
        ))
    return puntos
