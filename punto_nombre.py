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


# ---------------------------------------------------------------------------
# Línea + estación -> nombre del punto (Station_Text) y Station_Value
# ---------------------------------------------------------------------------
# Un preplot sísmico nombra cada punto con la línea y la estación pegadas, con
# ancho fijo (línea 1025 + estación 5092 -> "10255092"); ese texto es el
# Station_Text y su valor numérico (10255092) es el Station_Value. Si una capa
# de QGIS trae la línea y la estación en columnas separadas pero ninguna
# columna con las dos pegadas, el plugin la arma con estas funciones.

def _es_vacio(valor) -> bool:
    return valor is None or str(valor).strip() == ""


def _texto_numero(valor, digitos: int) -> str:
    """Un número de línea/estación como texto de ancho fijo (ceros a la
    izquierda). Los valores no numéricos ("A", "L1") se dejan tal cual."""
    s = str(valor).strip()
    try:
        f = float(s)
    except ValueError:
        return s
    if f.is_integer():
        return str(int(f)).zfill(max(int(digitos), 1))
    return str(f)


def concatenar_linea_estacion(track, bin_, line_digits: int = 4, station_digits: int = 4) -> Optional[str]:
    """Nombre de punto = línea + estación con ancho fijo, o None si falta
    alguna de las dos."""
    if _es_vacio(track) or _es_vacio(bin_):
        return None
    return _texto_numero(track, line_digits) + _texto_numero(bin_, station_digits)


def nombre_ya_concatenado(nombre, track, bin_, line_digits: int = 4, station_digits: int = 4) -> bool:
    """True si `nombre` ya es la línea + la estación pegadas, con ceros a la
    izquierda (10255092) o sin ellos (10255092 también si 1025 y 5092 traen
    4 dígitos; "15092" para línea 1 y estación 5092)."""
    if _es_vacio(nombre) or _es_vacio(track) or _es_vacio(bin_):
        return False
    n = str(nombre).strip().upper()
    con_ceros = concatenar_linea_estacion(track, bin_, line_digits, station_digits)
    sin_ceros = concatenar_linea_estacion(track, bin_, 1, 1)
    return n in {(con_ceros or "").upper(), (sin_ceros or "").upper()}


def digitos_de_numeros(valores, minimo: int = 1) -> int:
    """Cantidad de dígitos que hace falta para escribir el mayor de los
    `valores` (parte entera), nunca menos que `minimo`."""
    mayor = max(int(minimo), 1)
    for v in valores:
        if _es_vacio(v):
            continue
        try:
            mayor = max(mayor, len(str(abs(int(float(str(v).strip()))))))
        except ValueError:
            continue
    return mayor
