# -*- coding: utf-8 -*-
"""
punto_nombre.py
----------------
Valores que GPSeismic deriva del NOMBRE de un punto (Station Text):
Station (value), Línea (Track) y Estaca (Bin). Lógica pura, compartida
por la previsualización de "Importar datos de campo" (al llenar la tabla
y al editar el nombre de un punto) y por la subida a POSTPLOT.

Comportamiento confirmado contra la base de datos POSTPLOT real de
referencia: un nombre puramente numérico ("60181012") da Station (value)
= ese número y Track/Bin separando los primeros `line_digits` dígitos
(Track "6018", Bin "1012"); un nombre que NO es puramente numérico (por
ejemplo con prefijo "D" o "?") deja Station (value)/Track/Bin en 0.
"""

from typing import Optional, Tuple


def track_bin_de_nombre(nombre: Optional[str], line_digits: int) -> Tuple[Optional[str], Optional[str]]:
    """(Track, Bin) como texto, o (None, None) si el nombre no es
    puramente numérico, es demasiado corto o `line_digits` <= 0."""
    n = (nombre or "").strip()
    if line_digits <= 0 or not n.isdigit() or len(n) <= line_digits:
        return None, None
    return n[:line_digits], n[line_digits:]


def derivados_de_nombre(nombre: Optional[str], line_digits: int) -> Tuple[str, str, str]:
    """(Station value, Track, Bin) como texto, tal como se muestran en la
    previsualización: "0" donde no se puede calcular."""
    n = (nombre or "").strip()
    if n.isdigit():
        station_value = n
        track, bin_ = track_bin_de_nombre(n, line_digits)
    else:
        station_value = "0"
        track, bin_ = None, None
    return station_value, (track if track is not None else "0"), (bin_ if bin_ is not None else "0")


def station_value_numerico(nombre: Optional[str]) -> float:
    """Station (value) como número para la columna Station_Value de
    POSTPLOT: el nombre si es puramente numérico, 0 si no."""
    n = (nombre or "").strip()
    return float(n) if n.isdigit() else 0.0
