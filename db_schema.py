# -*- coding: utf-8 -*-
"""
db_schema.py
------------
Esquema de la base de datos del proyecto topográfico. Reproduce
EXACTAMENTE las tablas de la base de datos de plantilla adjunta por el
usuario (ADC3D.sqlite): POSTPLOT, PREPLOT y TableDescriptions, para que
cualquier proyecto creado por el plugin sea compatible con el software
de origen de esa plantilla (mismos nombres y tipos de columna).

Se añade además una tabla propia del plugin, COMPARACION, para guardar
los resultados de comparar POSTPLOT contra un CSV de diseño/preplot
cargado por el usuario (funcionalidad pedida explícitamente: "que la
información se pueda subir a la base de datos creada inicialmente").
"""

import os
import re
import sqlite3
from datetime import datetime
from typing import Iterable, Dict, Any, List, Tuple, Optional

SQL_CREATE_POSTPLOT = """
CREATE TABLE IF NOT EXISTS [POSTPLOT] (
    Station_Text TEXT COLLATE NOCASE,
    Station_Value DOUBLE,
    Track INT,
    Bin INT,
    Descriptor TEXT COLLATE NOCASE,
    WGS84_Latitude DOUBLE,
    WGS84_Longitude DOUBLE,
    Local_Latitude DOUBLE,
    Local_Longitude DOUBLE,
    Local_Easting DOUBLE,
    Local_Northing DOUBLE,
    WGS84_Height FLOAT,
    Local_Height FLOAT,
    Geoid_Height FLOAT,
    Scale_Factor DOUBLE,
    Convergence DOUBLE,
    Survey_Mode_Text TEXT COLLATE NOCASE,
    Survey_Mode_Value TINYINT,
    HI FLOAT,
    Offset_North FLOAT,
    Offset_East FLOAT,
    Offset_Range FLOAT,
    Offset_Bearing FLOAT,
    Offset_Inline FLOAT,
    Offset_Crossline FLOAT,
    Offset_Height FLOAT,
    Inline_Azimuth FLOAT,
    Hor_Precision_95 FLOAT,
    Ver_Precision_95 FLOAT,
    CQ FLOAT,
    Number_of_Satellites TINYINT,
    PDOP FLOAT,
    HDOP FLOAT,
    VDOP FLOAT,
    Julian_Date_Local INT,
    Survey_Time_Local DATETIME,
    Survey_Time_GMT DATETIME,
    Serial_Time_GPS INT,
    Elapsed_Time INT,
    Populate_Time DATETIME,
    Local_Datum TEXT COLLATE NOCASE,
    Local_System TEXT COLLATE NOCASE,
    Geoid_Model_File TEXT COLLATE NOCASE,
    Distance_Units TEXT COLLATE NOCASE,
    Distance_Factor DOUBLE,
    Comment TEXT COLLATE NOCASE,
    Download_File TEXT COLLATE NOCASE,
    Collector_Job_Name TEXT COLLATE NOCASE,
    Receiver_Type TEXT COLLATE NOCASE,
    Receiver_SN TEXT COLLATE NOCASE,
    Number_Of_Epochs FLOAT,
    Unit_Variance FLOAT,
    Antenna TEXT COLLATE NOCASE,
    GPS_Baseline DOUBLE,
    GPS_Base_Station TEXT COLLATE NOCASE,
    Occupation_Time FLOAT,
    Init_Block SMALLINT,
    Constellations TEXT COLLATE NOCASE,
    Processor TEXT COLLATE NOCASE,
    Surveyor TEXT COLLATE NOCASE,
    ID INTEGER PRIMARY KEY
);
"""

SQL_CREATE_PREPLOT = """
CREATE TABLE IF NOT EXISTS [PREPLOT] (
    Station_Text TEXT COLLATE NOCASE,
    Station_Value DOUBLE,
    Track INT,
    Bin INT,
    Descriptor TEXT COLLATE NOCASE,
    WGS84_Latitude DOUBLE,
    WGS84_Longitude DOUBLE,
    Local_Latitude DOUBLE,
    Local_Longitude DOUBLE,
    Local_Easting DOUBLE,
    Local_Northing DOUBLE,
    WGS84_Height FLOAT,
    Distance_Units TEXT COLLATE NOCASE,
    Distance_Factor DOUBLE,
    Populate_Time DATETIME,
    Local_Datum TEXT COLLATE NOCASE,
    Local_System TEXT COLLATE NOCASE,
    Processor TEXT COLLATE NOCASE,
    ID INTEGER PRIMARY KEY
);
"""

SQL_CREATE_TABLEDESCRIPTIONS = """
CREATE TABLE IF NOT EXISTS [TableDescriptions] (
    Table_Name TEXT COLLATE NOCASE,
    Creation_Date DATETIME,
    Creation_Julian_Date INT,
    Creation_Mode_Text TEXT COLLATE NOCASE,
    Creation_Mode_Value TINYINT,
    Created_By TEXT COLLATE NOCASE,
    Creation_Purpose TEXT COLLATE NOCASE,
    Comment1 TEXT COLLATE NOCASE,
    Comment2 TEXT COLLATE NOCASE,
    Windows_Identity TEXT COLLATE NOCASE,
    ID INTEGER PRIMARY KEY
);
"""

# Tabla adicional propia del plugin (no existe en la plantilla original)
# para guardar el resultado de comparar POSTPLOT contra el CSV de diseño.
SQL_CREATE_COMPARACION = """
CREATE TABLE IF NOT EXISTS [COMPARACION] (
    ID INTEGER PRIMARY KEY,
    Station_Text TEXT COLLATE NOCASE,
    Origen_Diseno TEXT COLLATE NOCASE,
    Este_Diseno DOUBLE,
    Norte_Diseno DOUBLE,
    Cota_Diseno DOUBLE,
    Este_Levantado DOUBLE,
    Norte_Levantado DOUBLE,
    Cota_Levantada DOUBLE,
    Delta_Este DOUBLE,
    Delta_Norte DOUBLE,
    Delta_Cota DOUBLE,
    Distancia_2D DOUBLE,
    Distancia_3D DOUBLE,
    Dentro_Tolerancia TINYINT,
    Tolerancia_m DOUBLE,
    Fecha_Comparacion DATETIME
);
"""

# Tabla propia del plugin (clave/valor) para recordar ajustes del
# proyecto entre sesiones de QGIS, por ejemplo la ruta del modelo de
# geoide asignado al proyecto ("cuando se importe el .dc, se pueda
# aplicar el geoide"). No existe en la plantilla original.
SQL_CREATE_PROJECTSETTINGS = """
CREATE TABLE IF NOT EXISTS [ProjectSettings] (
    Setting_Key TEXT COLLATE NOCASE PRIMARY KEY,
    Setting_Value TEXT
);
"""

ALL_TABLES_SQL = [
    SQL_CREATE_POSTPLOT,
    SQL_CREATE_PREPLOT,
    SQL_CREATE_TABLEDESCRIPTIONS,
    SQL_CREATE_COMPARACION,
    SQL_CREATE_PROJECTSETTINGS,
]

POSTPLOT_COLUMNS = [
    "Station_Text", "Station_Value", "Track", "Bin", "Descriptor",
    "WGS84_Latitude", "WGS84_Longitude", "Local_Latitude", "Local_Longitude",
    "Local_Easting", "Local_Northing", "WGS84_Height", "Local_Height",
    "Geoid_Height", "Scale_Factor", "Convergence", "Survey_Mode_Text",
    "Survey_Mode_Value", "HI", "Offset_North", "Offset_East", "Offset_Range",
    "Offset_Bearing", "Offset_Inline", "Offset_Crossline", "Offset_Height",
    "Inline_Azimuth", "Hor_Precision_95", "Ver_Precision_95", "CQ",
    "Number_of_Satellites", "PDOP", "HDOP", "VDOP", "Julian_Date_Local",
    "Survey_Time_Local", "Survey_Time_GMT", "Serial_Time_GPS", "Elapsed_Time",
    "Populate_Time", "Local_Datum", "Local_System", "Geoid_Model_File",
    "Distance_Units", "Distance_Factor", "Comment", "Download_File",
    "Collector_Job_Name", "Receiver_Type", "Receiver_SN", "Number_Of_Epochs",
    "Unit_Variance", "Antenna", "GPS_Baseline", "GPS_Base_Station",
    "Occupation_Time", "Init_Block", "Constellations", "Processor", "Surveyor",
]

PREPLOT_COLUMNS = [
    "Station_Text", "Station_Value", "Track", "Bin", "Descriptor",
    "WGS84_Latitude", "WGS84_Longitude", "Local_Latitude", "Local_Longitude",
    "Local_Easting", "Local_Northing", "WGS84_Height", "Distance_Units",
    "Distance_Factor", "Populate_Time", "Local_Datum", "Local_System",
    "Processor",
]


def create_project_db(path: str, overwrite: bool = False) -> sqlite3.Connection:
    """Crea (o abre) la base de datos del proyecto con el esquema
    completo. Si `overwrite` es True y el archivo ya existe, se elimina
    primero. Devuelve la conexión abierta.
    """
    if overwrite and os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for sql in ALL_TABLES_SQL:
        cur.execute(sql)
    conn.commit()
    return conn


def register_table_description(
    conn: sqlite3.Connection,
    table_name: str,
    created_by: str = "gnsseismic (plugin QGIS)",
    creation_purpose: str = "",
    comment1: str = "",
    comment2: str = "",
    windows_identity: str = "",
) -> None:
    now = datetime.now()
    julian = int(now.strftime("%Y%j"))
    conn.execute(
        """
        INSERT INTO TableDescriptions
            (Table_Name, Creation_Date, Creation_Julian_Date,
             Creation_Mode_Text, Creation_Mode_Value, Created_By,
             Creation_Purpose, Comment1, Comment2, Windows_Identity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            table_name,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            julian,
            "Creado por plugin QGIS",
            0,
            created_by,
            creation_purpose,
            comment1,
            comment2,
            windows_identity,
        ),
    )
    conn.commit()


def insert_rows_with_ids(conn: sqlite3.Connection, table: str, columns: List[str], rows: Iterable[Dict[str, Any]]) -> List[int]:
    """Como `insert_rows`, pero devuelve la lista de `ID` (PRIMARY KEY)
    asignados a cada fila insertada, en orden -- lo usa "Importar datos de
    campo" para poder retirar de la base, después, EXACTAMENTE los puntos
    de una subida (ver `delete_rows_by_id`). Si una inserción falla, se
    hace rollback de las filas ya insertadas de esta llamada (para no
    dejar una subida a medias confirmada por un commit posterior) y se
    relanza el error."""
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    # `table`/`columns` siempre vienen hardcodeados desde el propio plugin, nunca de texto del usuario
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"  # nosec B608
    ids: List[int] = []
    cur = conn.cursor()
    try:
        for row in rows:
            values = [row.get(c) for c in columns]
            cur.execute(sql, values)
            ids.append(cur.lastrowid)
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return ids


def insert_rows(conn: sqlite3.Connection, table: str, columns: List[str], rows: Iterable[Dict[str, Any]]) -> int:
    """Inserta filas (una por diccionario) en `table`, usando sólo las
    claves de `columns` presentes en cada fila (las que falten quedan
    NULL). Devuelve el número de filas insertadas.
    """
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    # `table`/`columns` siempre vienen hardcodeados desde el propio plugin, nunca de texto del usuario
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"  # nosec B608
    n = 0
    cur = conn.cursor()
    for row in rows:
        values = [row.get(c) for c in columns]
        cur.execute(sql, values)
        n += 1
    conn.commit()
    return n


def delete_rows_by_id_chunked(conn: sqlite3.Connection, table: str, ids: Iterable[int], chunk: int = 500) -> int:
    """`delete_rows_by_id` en tandas de `chunk` IDs (SQLite viejo limita a
    999 parámetros por sentencia). Devuelve el total de filas borradas."""
    ids = [i for i in ids if i is not None]
    total = 0
    for k in range(0, len(ids), chunk):
        total += delete_rows_by_id(conn, table, ids[k:k + chunk])
    return total


def fetch_points(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    # `table` siempre viene hardcodeado desde el propio plugin, nunca de texto del usuario
    cur.execute(f"SELECT * FROM {table}")  # nosec B608
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_comparacion_rows(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
    cols = [
        "Station_Text", "Origen_Diseno", "Este_Diseno", "Norte_Diseno", "Cota_Diseno",
        "Este_Levantado", "Norte_Levantado", "Cota_Levantada",
        "Delta_Este", "Delta_Norte", "Delta_Cota", "Distancia_2D", "Distancia_3D",
        "Dentro_Tolerancia", "Tolerancia_m", "Fecha_Comparacion",
    ]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        r.setdefault("Fecha_Comparacion", now)
    return insert_rows(conn, "COMPARACION", cols, rows)


def table_row_count(conn: sqlite3.Connection, table: str) -> int:
    # `table` siempre viene hardcodeado desde el propio plugin, nunca de texto del usuario
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")  # nosec B608
    return cur.fetchone()[0]


# --- Ajustes del proyecto (clave/valor), p.ej. el geoide asignado -----------

def set_project_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO ProjectSettings (Setting_Key, Setting_Value) VALUES (?, ?) "
        "ON CONFLICT(Setting_Key) DO UPDATE SET Setting_Value = excluded.Setting_Value",
        (key, "" if value is None else str(value)),
    )
    conn.commit()


def get_project_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    cur = conn.execute("SELECT Setting_Value FROM ProjectSettings WHERE Setting_Key = ?", (key,))
    row = cur.fetchone()
    if row is None or row[0] in (None, ""):
        return default
    return row[0]


def get_project_setting_from_file(path: str, key: str, default: Any = None) -> Any:
    """Lee un único ajuste de `ProjectSettings` sin necesidad de ya tener
    una conexión abierta a esa base, abriendo y cerrando una conexión de
    sólo lectura propia. Se usa en el selector "Mis proyectos..." para
    mostrar el CRS de cada proyecto conocido sin mantener conexiones
    abiertas a bases que no están en uso en ese momento. Devuelve
    `default` si el archivo no existe, no es una base de datos válida de
    este plugin, o no tiene ese ajuste guardado."""
    if not path or not os.path.exists(path):
        return default
    try:
        conn = sqlite3.connect(path)
        try:
            return get_project_setting(conn, key, default)
        finally:
            conn.close()
    except sqlite3.Error:
        return default


# --- Consultas de sólo lectura (sección "Base de Datos") -------------------
#
# El panel de consultas está pensado para ARMAR EXPORTACIONES (elegir qué
# puntos van a Shapefile/GeoPackage/SPS), no para administrar la base de
# datos: por eso sólo se permiten sentencias SELECT (o CTE "WITH ...
# SELECT"). No es una protección a prueba de un usuario malicioso (esto es
# una herramienta de escritorio de un solo usuario), sino una barrera
# simple contra modificar o borrar datos por accidente desde este panel.
#
# El borrado de datos (v2.14.0) es la única excepción deliberada a "sólo
# lectura": un botón aparte y la capa provisional del mapa permiten borrar
# filas reales, siempre con una confirmación explícita antes de tocar la
# base de datos, y sólo cuando la propia consulta SELECT identifica sin
# ambigüedad una única tabla borrable (ver DELETABLE_TABLES/
# deletable_table_and_where) -- una consulta con JOIN, UNION, GROUP BY o
# un CTE nunca habilita el borrado, porque no hay forma segura de saber a
# qué tabla y qué filas exactas corresponde cada fila del resultado.

_FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "attach", "detach",
    "pragma", "create", "replace", "vacuum", "reindex", "trigger",
)


def is_select_only(sql: str) -> bool:
    s = (sql or "").strip()
    if not s:
        return False
    # No se permite más de una sentencia (evita "SELECT 1; DROP TABLE ...").
    sin_comentarios = re.sub(r"--[^\n]*", "", s)
    cuerpo = sin_comentarios.strip().rstrip(";").strip()
    if ";" in cuerpo:
        return False
    m = re.match(r"^\s*([a-zA-Z]+)", cuerpo)
    if not m or m.group(1).lower() not in ("select", "with"):
        return False
    lowered = cuerpo.lower()
    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", lowered):
            return False
    return True


def run_query(conn: sqlite3.Connection, sql: str, limit: Optional[int] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Ejecuta una consulta SELECT de sólo lectura y devuelve
    (columnas, filas_como_diccionarios). Lanza ValueError si la
    consulta no parece ser de sólo lectura.

    Sin límite por defecto (`limit=None`): trae TODAS las filas que
    matcheen la consulta, sin importar cuántas sean. Antes de la
    v2.19.0 este panel topaba el resultado a 5000 filas fijo (tanto en
    la previsualización como en la capa que se dibuja en el mapa); el
    usuario pidió explícitamente que no se limite -- si la consulta
    devuelve más filas, tiene que verse todo, tanto en la tabla como en
    el mapa. Se deja el parámetro `limit` disponible por si algún
    llamador futuro necesitara acotar el resultado a propósito (no lo
    usa nadie en el plugin actualmente).
    """
    if not is_select_only(sql):
        raise ValueError(
            "Sólo se permiten consultas SELECT (de sólo lectura) en este panel. "
            "Para insertar o modificar datos usa las otras secciones del plugin."
        )
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() if limit is None else cur.fetchmany(limit)
    return cols, [dict(zip(cols, r)) for r in rows]


# --- Borrado controlado desde el panel de consultas (v2.14.0) ---------------
#
# Tablas para las que este panel puede llegar a armar un DELETE real. Se
# excluyen a propósito TableDescriptions y ProjectSettings (metadata del
# propio proyecto/plugin, no datos topográficos/sísmicos) aunque también
# tengan ID -- borrar ahí no tiene un caso de uso real desde este panel.
DELETABLE_TABLES = {"POSTPLOT", "PREPLOT", "COMPARACION"}

_DELETE_JOIN_UNION_RE = re.compile(r"\b(join|union)\b", re.IGNORECASE)
_DELETE_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_DELETE_SELECT_FROM_RE = re.compile(
    r"^select\b.*?\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*"
    r"(?:where\s+(?P<where>.*?))?"
    r"(?:order\s+by\s+.*?)?"
    r"(?:limit\s+\d+(?:\s*,\s*\d+)?\s*)?$",
    re.IGNORECASE | re.DOTALL,
)


def deletable_table_and_where(sql: str) -> Tuple[Optional[str], Optional[str]]:
    """Si `sql` es un SELECT simple sobre UNA sola tabla de
    `DELETABLE_TABLES`, sin JOIN/UNION/GROUP BY y sin ser un CTE ("WITH
    ..."), devuelve (tabla, where_sql_o_None) -- listo para armar un
    "DELETE FROM tabla [WHERE where_sql]" que borre EXACTAMENTE las
    mismas filas que devolvería ese SELECT (sin depender del límite de
    `run_query`, que sólo previsualiza hasta 5000). Si no se puede
    determinar de forma segura una única tabla/filtro, devuelve
    (None, None) -- el llamador debe entonces deshabilitar cualquier
    borrado para esa consulta.
    """
    if not is_select_only(sql):
        return None, None
    sin_comentarios = re.sub(r"--[^\n]*", "", sql or "")
    cuerpo = sin_comentarios.strip().rstrip(";").strip()
    if not cuerpo or re.match(r"^with\b", cuerpo, re.IGNORECASE):
        return None, None
    if _DELETE_JOIN_UNION_RE.search(cuerpo) or _DELETE_GROUP_BY_RE.search(cuerpo):
        return None, None
    m = _DELETE_SELECT_FROM_RE.match(cuerpo)
    if not m:
        return None, None
    tabla = m.group(1).upper()
    if tabla not in DELETABLE_TABLES:
        return None, None
    where_sql = m.group("where")
    return tabla, (where_sql.strip() if where_sql else None)


def count_matching_rows(conn: sqlite3.Connection, table: str, where_sql: Optional[str]) -> int:
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite borrar de la tabla {table} desde este panel.")
    # `table` ya validado contra DELETABLE_TABLES arriba; `where_sql` es el WHERE de la misma consulta que el propio usuario ya escribió y corrió en su editor de SQL (sin frontera de confianza: ya tiene acceso de lectura/escritura completo a su propia base local)
    sql = f"SELECT COUNT(*) FROM {table}"  # nosec B608
    if where_sql:
        sql += f" WHERE {where_sql}"
    return conn.execute(sql).fetchone()[0]


def delete_matching_rows(conn: sqlite3.Connection, table: str, where_sql: Optional[str]) -> int:
    """Borra de `table` todas las filas que matchean `where_sql` (o TODA
    la tabla si `where_sql` es None) y confirma la transacción. Pensado
    para usarse sólo después de que el usuario confirmó explícitamente
    el borrado en la interfaz -- esta función no vuelve a preguntar."""
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite borrar de la tabla {table} desde este panel.")
    # `table` ya validado contra DELETABLE_TABLES arriba; `where_sql` es el WHERE de la misma consulta que el propio usuario ya escribió y corrió en su editor de SQL (sin frontera de confianza: ya tiene acceso de lectura/escritura completo a su propia base local)
    sql = f"DELETE FROM {table}"  # nosec B608
    if where_sql:
        sql += f" WHERE {where_sql}"
    cur = conn.execute(sql)
    conn.commit()
    return cur.rowcount


def delete_rows_by_id(conn: sqlite3.Connection, table: str, ids: Iterable[int]) -> int:
    """Borra de `table` las filas cuyo ID (columna PRIMARY KEY de
    POSTPLOT/PREPLOT/COMPARACION) esté en `ids`. Usado para el borrado
    puntual de puntos seleccionados en la capa provisional del mapa
    (a diferencia de `delete_matching_rows`, que borra por WHERE)."""
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite borrar de la tabla {table} desde este panel.")
    ids = [i for i in ids if i is not None]
    if not ids:
        return 0
    placeholders = ", ".join("?" for _ in ids)
    # `table` ya validado contra DELETABLE_TABLES arriba; `ids` siempre van bindeados como parámetros, nunca concatenados
    cur = conn.execute(f"DELETE FROM {table} WHERE ID IN ({placeholders})", ids)  # nosec B608
    conn.commit()
    return cur.rowcount


# --- Edición en línea desde el panel de consultas (v2.21.0) -----------------

def table_column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    """Nombres reales de columna de `table`, leídos del esquema con
    PRAGMA table_info -- se usa para confirmar, antes de habilitar la
    edición en línea en el panel de consultas, que las columnas del
    resultado de un SELECT corresponden 1 a 1 con columnas reales de la
    tabla (y no, por ejemplo, un alias tipo `SELECT Descriptor AS Tipo
    FROM POSTPLOT`, que rompería un UPDATE armado a partir del nombre de
    columna del resultado). Ver `gnsseismic_windows._es_consulta_editable`."""
    cur = conn.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cur.fetchall()]


def update_row_by_id(conn: sqlite3.Connection, table: str, row_id: int, changes: Dict[str, Any]) -> None:
    """Actualiza, en `table`, la fila cuyo ID (PRIMARY KEY de
    POSTPLOT/PREPLOT/COMPARACION) es `row_id`, aplicando `changes` (dict
    columna -> valor nuevo). Usado por la edición en línea del panel de
    consultas de "Base de Datos" (botón "Guardar cambios en la base de
    datos...") -- sólo se llama después de que el usuario confirmó
    explícitamente el guardado, y sólo con columnas ya validadas contra
    `table_column_names` al habilitar la edición. Vuelve a validarlas acá
    de todos modos (nunca confiar en que el llamador ya lo hizo) antes de
    armar el UPDATE, para no poder inyectar un nombre de columna
    arbitrario en el SQL."""
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite editar la tabla {table} desde este panel.")
    if not changes:
        return
    columnas_reales = set(table_column_names(conn, table))
    for col in changes:
        if col not in columnas_reales:
            raise ValueError(f"'{col}' no es una columna real de {table}.")
    set_sql = ", ".join(f"[{col}] = ?" for col in changes)
    valores = list(changes.values()) + [row_id]
    # `table`/columnas de `set_sql` ya validados contra DELETABLE_TABLES/table_column_names arriba; los valores siempre van bindeados como parámetros
    conn.execute(f"UPDATE [{table}] SET {set_sql} WHERE ID = ?", valores)  # nosec B608
    conn.commit()


# --- "Buscar / Buscar y reemplazar" del panel de consultas (v2.53.0) --------
#
# Pedido explícito del usuario: una sección aparte del editor de SQL
# libre, para poder buscar (y reemplazar en bloque) por CUALQUIER columna
# de POSTPLOT/PREPLOT/COMPARACION sin tener que escribir SQL a mano. La
# búsqueda en sí reutiliza `run_query` (arma un SELECT con la columna/
# valor elegidos y lo corre igual que una consulta manual, ver
# `gnsseismic_windows.buscar_por_columna`); lo nuevo acá es el reemplazo
# masivo, que sigue el mismo criterio de seguridad que `update_row_by_id`:
# sólo tablas de `DELETABLE_TABLES`, columna validada contra el esquema
# real (nunca un nombre arbitrario armado con texto del usuario), valores
# siempre como parámetros bindeados (nunca concatenados al SQL) y nunca
# se permite tocar la columna ID.

def count_replace_matches(conn: sqlite3.Connection, table: str, column: str, search_value: str, exact: bool) -> int:
    """Cuenta cuántas filas de `table.column` matchean `search_value`
    -- comparación exacta (`column = search_value`) si `exact=True`, o
    "contiene" (`column LIKE '%search_value%'`) si no -- para mostrarle
    al usuario cuántas filas se verían afectadas ANTES de pedirle que
    confirme un reemplazo masivo (ver `replace_in_column`)."""
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite buscar/reemplazar en la tabla {table} desde este panel.")
    if column not in set(table_column_names(conn, table)):
        raise ValueError(f"'{column}' no es una columna real de {table}.")
    if exact:
        # `table`/`column` ya validados contra DELETABLE_TABLES/table_column_names arriba; el valor buscado siempre va bindeado como parámetro
        sql = f"SELECT COUNT(*) FROM [{table}] WHERE [{column}] = ?"  # nosec B608
        params = [search_value]
    else:
        # mismo motivo que la rama anterior
        sql = f"SELECT COUNT(*) FROM [{table}] WHERE [{column}] LIKE ?"  # nosec B608
        params = [f"%{search_value}%"]
    return conn.execute(sql, params).fetchone()[0]


def replace_in_column(
    conn: sqlite3.Connection, table: str, column: str,
    search_value: str, replace_value: str, exact: bool,
) -> int:
    """Reemplaza, en `table.column`, `search_value` por `replace_value`
    en todas las filas que matcheen. Dos modos, igual que
    `count_replace_matches`:

    - `exact=True` ("Coincidencia exacta"): reemplaza el valor COMPLETO
      de la celda -- `UPDATE table SET column = replace_value WHERE
      column = search_value` --, pensado para columnas de valor único
      (un código, un nombre de base, un Descriptor), donde buscar
      "1234567" y reemplazarlo por "7654321" tiene que cambiar la celda
      entera, no una subcadena.
    - `exact=False` ("contiene"): reemplaza sólo la parte de la celda
      que matchea, con la función `REPLACE()` de SQLite -- `UPDATE table
      SET column = REPLACE(column, search_value, replace_value) WHERE
      column LIKE '%search_value%'` --, conservando el resto del texto
      de la celda; pensado para columnas de texto libre (un comentario)
      donde sólo una parte necesita corregirse.

    Nunca se permite reemplazar en la columna ID (rompería la clave
    primaria) ni en una tabla fuera de `DELETABLE_TABLES`; la columna se
    vuelve a validar acá contra el esquema real, igual que
    `update_row_by_id`, para no poder inyectar un nombre de columna
    arbitrario en el SQL. Devuelve la cantidad de filas modificadas.
    Pensada para usarse sólo después de que el usuario confirmó
    explícitamente el reemplazo en la interfaz, mostrando antes cuántas
    filas se verían afectadas (`count_replace_matches`) -- esta función
    no vuelve a preguntar."""
    if table not in DELETABLE_TABLES:
        raise ValueError(f"No se permite buscar/reemplazar en la tabla {table} desde este panel.")
    if column == "ID":
        raise ValueError("No se puede reemplazar en la columna ID.")
    if column not in set(table_column_names(conn, table)):
        raise ValueError(f"'{column}' no es una columna real de {table}.")
    if exact:
        # `table`/`column` ya validados contra DELETABLE_TABLES/table_column_names arriba; los valores siempre van bindeados como parámetros
        sql = f"UPDATE [{table}] SET [{column}] = ? WHERE [{column}] = ?"  # nosec B608
        params = [replace_value, search_value]
    else:
        # mismo motivo que la rama anterior
        sql = f"UPDATE [{table}] SET [{column}] = REPLACE([{column}], ?, ?) WHERE [{column}] LIKE ?"  # nosec B608
        params = [search_value, replace_value, f"%{search_value}%"]
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount
