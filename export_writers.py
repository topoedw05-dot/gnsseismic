# -*- coding: utf-8 -*-
"""
export_writers.py
------------------
Escritura del formato sísmico **SPS (SEG/Shell Processing Support,
rev. 2.1)** — archivos de puntos de Fuente (.S01) y Receptor (.R01),
registro de ancho fijo de 80 columnas. Es lógica pura (sin QGIS/PyQt)
para poder probarla de forma aislada.

Layout del registro de punto (idéntico para 'S' y 'R'), columnas
1-indexadas como las define el estándar:

  col  1     ( 1 char)  Identificador de registro: 'S' o 'R'
  col  2-17  (16 chars) Nombre de línea (formato 4A4)
  col 18-25  ( 8 chars) Número de punto (formato 2A4)
  col 26     ( 1 char)  Índice de punto (I1)
  col 27-28  ( 2 chars) Código de punto (A2)
  col 29-32  ( 4 chars) Corrección estática, ms (I4)
  col 33-36  ( 4 chars) Profundidad, m (F4.1)
  col 37-40  ( 4 chars) Datum sísmico, m (I4)
  col 41-42  ( 2 chars) Tiempo de pozo, ms (I2)
  col 43-46  ( 4 chars) Profundidad de agua, m (F4.1)
  col 47-55  ( 9 chars) Coordenada Este (F9.1)
  col 56-65  (10 chars) Coordenada Norte (F10.1)
  col 66-71  ( 6 chars) Elevación, m (F6.1)
  col 72-74  ( 3 chars) Día del año (I3)
  col 75-80  ( 6 chars) Hora hhmmss (3I2)

Total: 80 columnas por registro.
"""

import csv
from typing import List, Dict, Any, Optional

SPS_RECORD_WIDTH = 80


def write_csv(columns: List[str], rows: List[Dict[str, Any]], out_path: str) -> int:
    """Escribe el resultado de una consulta (v2.21.0, formato "Excel
    (.csv)" del panel de "Base de Datos") a un CSV delimitado por comas:
    todas las columnas y filas tal cual estén en `columns`/`rows`, sin
    pasar por el mapeo de Nombre/X/Y que usan los demás formatos de
    exportación (Shapefile/GeoPackage/SPS) -- así se puede exportar
    cualquier consulta, incluso una sin columnas de coordenadas (por
    ejemplo un `SELECT COUNT(*)`). Se escribe en UTF-8 con BOM
    (`utf-8-sig`) para que Excel detecte tildes/ñ correctamente al
    abrirlo directo, sin tener que elegir la codificación a mano.
    Devuelve el número de filas escritas (sin contar el encabezado)."""
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        n = 0
        for row in rows:
            writer.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
            n += 1
    return n


def _num_field(value, width: int, decimals: int = 0) -> str:
    """Formatea un número a un campo de ancho fijo, alineado a la
    derecha, con `decimals` decimales. Si no cabe en el ancho, se
    trunca el número de decimales antes que el valor entero (evita
    cortar dígitos significativos silenciosamente cuando sea posible).
    """
    if value is None:
        value = 0
    for d in range(decimals, -1, -1):
        s = f"{float(value):.{d}f}"
        if len(s) <= width:
            return s.rjust(width)
    # No cabe ni siquiera sin decimales: se trunca (caso extremo).
    s = f"{float(value):.0f}"
    return s[-width:].rjust(width)


def _int_field(value, width: int) -> str:
    if value is None:
        value = 0
    s = str(int(value))
    return s[-width:].rjust(width)


def format_sps_record(
    tipo: str,
    line_name,
    point_number,
    point_index: int = 1,
    point_code: str = "",
    static_ms: int = 0,
    depth_m: float = 0.0,
    datum_m: int = 0,
    uphole_ms: int = 0,
    water_depth_m: float = 0.0,
    easting: float = 0.0,
    northing: float = 0.0,
    elevation: float = 0.0,
    day_of_year: int = 0,
    time_hhmmss: str = "000000",
) -> str:
    tipo = (tipo or "").strip().upper()
    if tipo not in ("S", "R"):
        raise ValueError("tipo debe ser 'S' (fuente) o 'R' (receptor)")

    time_hhmmss = (time_hhmmss or "000000").strip()
    if not time_hhmmss.isdigit() or len(time_hhmmss) != 6:
        time_hhmmss = "000000"

    campos = [
        tipo,
        _num_field(line_name, 16, decimals=2),
        _num_field(point_number, 8, decimals=2),
        _int_field(point_index, 1),
        (point_code or "").strip()[:2].rjust(2),
        _int_field(static_ms, 4),
        _num_field(depth_m, 4, decimals=1),
        _int_field(datum_m, 4),
        _int_field(uphole_ms, 2),
        _num_field(water_depth_m, 4, decimals=1),
        _num_field(easting, 9, decimals=1),
        _num_field(northing, 10, decimals=1),
        _num_field(elevation, 6, decimals=1),
        _int_field(day_of_year, 3),
        time_hhmmss.rjust(6),
    ]
    record = "".join(campos)
    if len(record) != SPS_RECORD_WIDTH:
        # No debería ocurrir si los anchos anteriores son correctos;
        # se ajusta de forma defensiva en vez de escribir un archivo
        # corrupto silenciosamente.
        record = record[:SPS_RECORD_WIDTH].ljust(SPS_RECORD_WIDTH)
    return record


def write_sps(
    rows: List[Dict[str, Any]],
    out_path: str,
    tipo: str,
    line_col: str,
    point_col: str,
    x_col: str,
    y_col: str,
    elev_col: Optional[str] = None,
    code_col: Optional[str] = None,
    code_fijo: str = "",
    point_index: int = 1,
    day_of_year: int = 0,
    time_hhmmss: str = "000000",
) -> int:
    """Escribe un archivo SPS (.S01 para fuentes / .R01 para receptores)
    a partir de una lista de filas (dicts). Devuelve el número de
    registros escritos. Filas sin línea/punto/X/Y válidos se omiten
    (no interrumpen la escritura completa).
    """
    n = 0
    with open(out_path, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        for row in rows:
            try:
                line_name = float(row[line_col])
                point_number = float(row[point_col])
                x = float(row[x_col])
                y = float(row[y_col])
            except (KeyError, TypeError, ValueError):
                continue
            elevation = 0.0
            if elev_col and row.get(elev_col) is not None:
                try:
                    elevation = float(row[elev_col])
                except (TypeError, ValueError):
                    elevation = 0.0
            code = code_fijo
            if code_col and row.get(code_col):
                code = str(row[code_col])

            line = format_sps_record(
                tipo=tipo, line_name=line_name, point_number=point_number,
                point_index=point_index, point_code=code,
                easting=x, northing=y, elevation=elevation,
                day_of_year=day_of_year, time_hhmmss=time_hhmmss,
            )
            f.write(line + "\n")
            n += 1
    return n


# ---------------------------------------------------------------------
# Lectura de SPS (además de escritura): se usa para importar preplots
# externos generados por otro software (p.ej. Omni 3D o la mesa de
# Sercel) que ya vienen en formato SPS rev. 2.1 -- ver "Importar preplot
# externo" en la pestaña de Preplot Sísmico. Es el mismo layout de
# columnas que `format_sps_record`, leído en el mismo orden.
# ---------------------------------------------------------------------

def parse_sps_record(line: str) -> Optional[Dict[str, Any]]:
    """Parsea un único registro SPS de punto (Fuente 'S' o Receptor
    'R'), con el mismo layout de columnas de `format_sps_record`.
    Devuelve un dict con line_name/point_number/point_code/easting/
    northing/elevation, o None si la línea no es un registro de punto
    reconocible -- encabezados, comentarios, líneas en blanco u otros
    tipos de registro se saltan así sin interrumpir la lectura del
    archivo completo, igual que `write_sps` tolera filas inválidas al
    escribir.
    """
    if not line:
        return None
    line = line.rstrip("\r\n")
    tipo = line[0:1].strip().upper()
    if tipo not in ("S", "R"):
        return None
    # Hace falta al menos hasta el campo de Norte (columna 65) para que
    # el registro sea utilizable; se rellena con espacios por si el
    # archivo no trae los últimos campos (fecha/hora), que no se usan.
    if len(line) < 65:
        return None
    line = line.ljust(SPS_RECORD_WIDTH)
    try:
        line_name = float(line[1:17].strip())
        point_number = float(line[17:25].strip())
    except ValueError:
        return None
    point_code = line[26:28].strip()
    try:
        easting = float(line[46:55].strip())
        northing = float(line[55:65].strip())
    except ValueError:
        return None
    try:
        elevation = float(line[65:71].strip())
    except ValueError:
        elevation = None
    return {
        "tipo": tipo,
        "line_name": line_name,
        "point_number": point_number,
        "point_code": point_code,
        "easting": easting,
        "northing": northing,
        "elevation": elevation,
    }


def parse_sps_file(path: str, encoding: str = "ascii") -> List[Dict[str, Any]]:
    """Lee un archivo SPS (.S01 de fuentes, .R01 de receptores, o un
    .sps genérico con ambos tipos mezclados) y devuelve la lista de
    registros de punto ya parseados (ver `parse_sps_record`). Líneas
    que no son un registro de punto válido se saltan en silencio.
    """
    registros: List[Dict[str, Any]] = []
    with open(path, "r", encoding=encoding, errors="replace") as f:
        for raw in f:
            rec = parse_sps_record(raw)
            if rec is not None:
                registros.append(rec)
    return registros
