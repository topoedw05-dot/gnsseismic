# -*- coding: utf-8 -*-
"""
stonex_parser.py
----------------
Lee el archivo de exportación de la app de campo de Stonex ("Cube-a" /
"SurvStar", según el propio Antenna.Type visto en un archivo real: la
versión de software `4.3.38.20210407` de la tabla `Version`). A
diferencia de los otros tres formatos que ya soporta el plugin (Trimble
.dc, Hi-Target CSV/.raw, CHCNav .rw5, todos texto o binario propio), el
de Stonex es directamente una **base de datos SQLite** (el usuario le
había cambiado la extensión a `.PD`, pero el contenido es
`SQLite format 3`) -- así que no hace falta ingeniería inversa de un
formato binario/texto propio, sólo conocer su esquema de tablas.

Verificado contra un archivo real del usuario (`CARGILL.PD`, 48 puntos,
CRS de trabajo declarado en el propio archivo: "MAGNA-SIRGAS / CTM12 -
Origen Nacional"):

- La tabla `Point` trae, por cada punto levantado: `NAME`/`CODE`
  (nombre y código de clasificación de campo, ej. "LD"/"CHK" -- mismo
  criterio que ya usa `chcnav_parser.py` para LD/CT/CHKAM/CHKPM: se
  preserva el código tal cual, sin traducir/adivinar su significado
  exacto), `Latitude`/`Longitude`/`Altitude` (WGS84, grados decimales)
  y `DeleteSign` (1 si el usuario borró el punto en la app de campo --
  se excluye siempre, igual que un `SP` sin coordenadas de CHCNav).
  También trae `North`/`East` en la grilla LOCAL del CRS que declara el
  propio archivo (ver más abajo) -- se ignoran a propósito, mismo
  criterio ya aplicado a la grilla N/E/Z de Hi-Target y al comentario
  `--GS` de CHCNav: el plugin siempre prefiere lat/lon y proyecta él
  mismo al CRS de trabajo del PROYECTO (que puede no ser el mismo que
  declaraba la app de campo).
- **`Point.Altitude` YA es la altura elipsoidal del punto en el TERRENO**
  (con la altura de antena restada) -- verificado contra los 48 puntos
  reales: `Point.Altitude` = `GPSCoordinate.WGS84Altitude` (altura al
  centro de fase de la antena) menos
  `GPSCoordinate.Antenna_AntennaHeight`, exacto en los 48 casos. Por
  eso NO hace falta restar la altura de antena una segunda vez.
- La tabla `GPSCoordinate` (una fila por punto, enlazada por
  `Point.GPSID == GPSCoordinate.ID`) trae, con más detalle que
  cualquiera de los otros tres formatos: `Satellite_Locked` (satélites
  usados en la solución), `PDOP`/`HDOP`/`VDOP`, `Pos_State` (texto real
  del receptor: "FIXED"/"FLOAT"/"DIF3D" en el archivo real -- ver la
  nota sobre "calidad" más abajo), `DistancetoBase` (distancia real a
  la base/referencia, ya calculada por el propio receptor -- no hace
  falta recalcularla con haversine como sí hizo falta para Hi-Target),
  `Base_ID` (identificador de la base/referencia -- en el archivo real,
  "RTCM-Ref 0": una referencia de RED vía RTCM/NTRIP, no una base local
  físicamente ocupada por el propio equipo -- ver "Pendiente"),
  `Antenna_AntennaHeight` (altura de antena YA efectiva, con el offset
  de fase de la antena ya sumado -- ver `Antenna.H`/`R`/`HL1`/`HL2`),
  `LocalDate`/`LocalTime`/`UTCDate`/`UTCTime` (fecha/hora REALES y
  absolutas del punto, a diferencia del reloj de sesión sin fecha que
  traía Hi-Target) e `InstrumentID` (enlaza con la tabla `Antenna` para
  el modelo/serie del equipo, ej. "Stonex S850A"/"S8503119000077").
- **Deliberadamente sin mapear** (mismo criterio que excluyó σN/σE/σZ de
  Hi-Target y HSDV/VSDV de CHCNav): `HRMS`/`VRMS` de `GPSCoordinate` --
  son un RMS de posición, no el mismo dato que espera
  `Hor_Precision_95`/`Ver_Precision_95` de POSTPLOT (precisión al 95%
  de confianza), y convertir uno en el otro sin conocer el método de
  cálculo del receptor sería inventar un número.
- `Undulation` de `GPSCoordinate` viene en `0.0` en el único archivo
  real disponible (no se aplicó ningún geoide en la app de campo) --
  no se usa: el plugin sigue aplicando su PROPIO geoide de proyecto
  (`geoid_utils`), igual que a cualquier otro origen.
- No se pudo verificar cómo se ve una ocupación de BASE LOCAL (el
  equipo propio ocupando físicamente un punto de referencia, como sí
  hacen las ocupaciones `is_base` de Hi-Target/CHCNav) en este formato,
  porque el único archivo real disponible usó una referencia de red
  (RTCM/NTRIP) para los 48 puntos -- por eso `StonexPoint.is_base`
  siempre es `False` en esta versión.
- **Ronda 2.27.0**: a pedido del usuario, que aportó además un CSV
  propio de la app de Stonex (exportación paralela al .PD, mismo
  trabajo "CARGILL") pidiendo poder corregir "la base" con una
  coordenada ajustada por post-proceso -- se agregó lectura de
  `GPSCoordinate.Base_Latitude`/`Base_Longitude`/`Base_Altitude`
  (`StonexPoint.base_lat`/`base_lon`/`base_height`), verificadas contra
  el CSV del usuario (sus columnas `Base_Latitude`/`Base_Longitude` en
  formato DMS con signo -- p.ej. "010d09m43.1308160747s" -- coinciden,
  convertidas a grados decimales, con `Base_Latitude`/`Base_Longitude`
  del archivo `.PD`: 10.161980782242969 / -75.32701219768245). A
  diferencia de Hi-Target/CHCNav (donde la base es una ocupación real,
  un punto más entre los levantados, con sus propias
  coordenadas "libres" medidas en el momento), en Stonex la
  base/referencia (aquí "RTCM-Ref 0", una referencia de red) NUNCA es
  un punto propio del archivo -- es un dato que CADA punto rover trae
  repetido en su fila de `GPSCoordinate`. `StonexFile.unique_bases()`
  las extrae para poder ofrecerlas igual en la sección "Corrección de
  base RTK" del plugin (ver `gnsseismic_windows.py`, que arma una fila
  sintética `is_base=True` por cada una). También se confirmó que el
  propio mecanismo interno de corrección de base del archivo Stonex
  (`GPSCoordinate.BaseChangeCorrect_Latitude/Longitude/Altitude`) está
  sin usar (0.0 en las 48 filas del archivo real) -- coincide con que
  el CSV del usuario trae sus columnas `Correct_Latitude`/
  `Correct_Longitude`/`Correct_Altitude` también en 0.0: la corrección
  que pide el usuario nunca se aplicó dentro de la app de campo, así
  que hace falta que la aplique el plugin.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class StonexPoint:
    row_id: int  # Point.ID -- identidad estable del punto dentro del archivo (equivalente a "line_no" en los parsers de texto)
    name: str
    code: str  # Point.CODE tal cual (ej. "LD"/"chk"/"CHK"), sin normalizar -- ver _stonex_tipo_code() en gnsseismic_windows.py
    lat: float
    lon: float
    height: float  # Point.Altitude: altura elipsoidal WGS84 YA con la altura de antena restada (ver docstring del módulo)
    ant_height: Optional[float] = None  # GPSCoordinate.Antenna_AntennaHeight
    n_sats: Optional[int] = None  # GPSCoordinate.Satellite_Locked
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    pos_state: Optional[str] = None  # "FIXED"/"FLOAT"/"DIF3D" tal cual el receptor, ver GPSCoordinate.Pos_State
    gps_baseline_m: Optional[float] = None  # GPSCoordinate.DistancetoBase
    gps_base_station: Optional[str] = None  # GPSCoordinate.Base_ID (puede ser una referencia de red, no necesariamente una base física)
    base_lat: Optional[float] = None  # GPSCoordinate.Base_Latitude (grados decimales) -- ver "Ronda 2.27.0" en el docstring del módulo
    base_lon: Optional[float] = None  # GPSCoordinate.Base_Longitude
    base_height: Optional[float] = None  # GPSCoordinate.Base_Altitude
    receiver_type: Optional[str] = None  # Antenna.Type (ej. "Stonex S850A")
    receiver_sn: Optional[str] = None  # GPSCoordinate.InstrumentID / Antenna.ID
    occupation_seconds: Optional[float] = None  # Point.EndTime - Point.StartTime
    survey_time_local: Optional[str] = None  # GPSCoordinate.LocalDate + LocalTime
    survey_time_gmt: Optional[str] = None  # GPSCoordinate.UTCDate + UTCTime
    is_base: bool = False  # Nunca True en esta versión -- ver docstring del módulo


@dataclass
class StonexFile:
    path: str
    points: List[StonexPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    coord_system_name: Optional[str] = None  # CoordinateSystemDetail: "CoordSystemName", sólo informativo (nunca se usa para transformar)

    @property
    def n_points(self) -> int:
        return len(self.points)

    def duplicated_names(self) -> List[str]:
        seen, dup = set(), []
        for p in self.points:
            n = (p.name or "").strip().upper()
            if n in seen and n not in dup:
                dup.append(n)
            seen.add(n)
        return dup

    def unique_bases(self):
        """Devuelve las bases/referencias distintas que traen los puntos
        de este archivo, como una lista de tuplas
        (nombre, lat, lon, altura_o_None), en el orden en que aparecen.
        A diferencia de Hi-Target/CHCNav (donde una base es un punto más
        del archivo, con `is_base=True`), en Stonex NINGÚN punto es la
        base en sí -- cada punto rover sólo trae repetida la coordenada
        de la referencia que usó (ver "Ronda 2.27.0" en el docstring del
        módulo). Un punto sin base conocida (`gps_base_station` vacío, o
        sin `base_lat`/`base_lon`) no aporta ninguna entrada."""
        vistas = {}
        orden = []
        for p in self.points:
            if not p.gps_base_station or p.base_lat is None or p.base_lon is None:
                continue
            if p.gps_base_station not in vistas:
                vistas[p.gps_base_station] = (p.gps_base_station, p.base_lat, p.base_lon, p.base_height)
                orden.append(p.gps_base_station)
        return [vistas[k] for k in orden]


_REQUIRED_TABLES = {"Point", "GPSCoordinate", "CoordinateSystemDetail", "Antenna"}


def looks_like_stonex_db(path: str) -> bool:
    """True si `path` es una base SQLite con el esquema de la app de
    campo de Stonex (ver docstring del módulo). No depende de la
    extensión del archivo -- el usuario puede haberla cambiado (el
    archivo real de referencia llegó como `.PD`)."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(16)
    except OSError:
        return False
    if not header.startswith(b"SQLite format 3\x00"):
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            return _REQUIRED_TABLES.issubset(tables)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _parse_dt(date_text, time_text):
    """Combina una fecha y hora de la base (ambas guardadas como texto,
    ej. "2025-08-02"/"09:28:53") en un único texto "YYYY-MM-DD HH:MM:SS",
    sin interpretar más allá de eso (mismo criterio que ya usa CHCNav
    para su fecha/hora de texto libre: sólo informativo)."""
    if not date_text and not time_text:
        return None
    if date_text and time_text:
        return f"{date_text} {time_text}"
    return date_text or time_text


def _occupation_seconds(start_text, end_text):
    """Duración de la ocupación en segundos, a partir de Point.StartTime/
    EndTime ("YYYY-MM-DD HH:MM:SS"). Nunca se usa como hora absoluta,
    sólo la diferencia -- mismo criterio que la duración calculada para
    Hi-Target (v2.9.0) a partir de su reloj de sesión sin fecha."""
    if not start_text or not end_text:
        return None
    try:
        t0 = datetime.strptime(start_text, "%Y-%m-%d %H:%M:%S")
        t1 = datetime.strptime(end_text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return (t1 - t0).total_seconds()


def parse_stonex_db(path: str) -> StonexFile:
    result = StonexFile(path=path)

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            cur.execute(
                "SELECT Value FROM CoordinateSystemDetail WHERE Title='CoordSystemName'"
            )
            row = cur.fetchone()
            if row:
                result.coord_system_name = row["Value"]
        except sqlite3.Error:
            pass

        antenna_by_id = {}
        try:
            for row in cur.execute("SELECT ID, Type FROM Antenna"):
                antenna_by_id[row["ID"]] = row["Type"]
        except sqlite3.Error:
            pass

        cur.execute(
            """
            SELECT
                p.ID AS row_id, p.NAME AS name, p.CODE AS code,
                p.Latitude AS lat, p.Longitude AS lon, p.Altitude AS height,
                p.StartTime AS start_time, p.EndTime AS end_time,
                p.DeleteSign AS delete_sign, p.GPSID AS gpsid,
                g.ID AS gps_row_id,
                g.Satellite_Locked AS n_sats, g.PDOP AS pdop,
                g.HDOP AS hdop, g.VDOP AS vdop, g.Pos_State AS pos_state,
                g.DistancetoBase AS gps_baseline_m, g.Base_ID AS gps_base_station,
                g.Base_Latitude AS base_lat, g.Base_Longitude AS base_lon,
                g.Base_Altitude AS base_height,
                g.Antenna_AntennaHeight AS ant_height,
                g.LocalDate AS local_date, g.LocalTime AS local_time,
                g.UTCDate AS utc_date, g.UTCTime AS utc_time,
                g.InstrumentID AS instrument_id
            FROM Point p
            LEFT JOIN GPSCoordinate g ON p.GPSID = g.ID
            ORDER BY p.ID
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    n_borrados = 0
    n_sin_gps = 0
    for r in rows:
        if r["delete_sign"]:
            n_borrados += 1
            continue
        # Un `Point` sin fila de `GPSCoordinate` asociada (`GPSID` no
        # matcheó ninguna) no es una medición GNSS real de campo -- esta
        # app también admite puntos CALCULADOS (ver la tabla
        # `CalcPtInfo`: intersecciones, offsets, etc.), que comparten la
        # misma tabla `Point` pero nunca tienen satélites/PDOP/calidad
        # propios. Se descartan igual que un punto sin coordenada.
        if r["gps_row_id"] is None or r["lat"] is None or r["lon"] is None or r["height"] is None:
            n_sin_gps += 1
            continue
        instrument_id = r["instrument_id"]
        result.points.append(StonexPoint(
            row_id=r["row_id"],
            name=(r["name"] or "").strip(),
            code=(r["code"] or "").strip(),
            lat=r["lat"], lon=r["lon"], height=r["height"],
            ant_height=r["ant_height"],
            n_sats=r["n_sats"], pdop=r["pdop"], hdop=r["hdop"], vdop=r["vdop"],
            pos_state=(r["pos_state"] or "").strip() or None,
            gps_baseline_m=r["gps_baseline_m"],
            gps_base_station=(r["gps_base_station"] or "").strip() or None,
            base_lat=r["base_lat"], base_lon=r["base_lon"], base_height=r["base_height"],
            receiver_type=antenna_by_id.get(instrument_id),
            receiver_sn=instrument_id,
            occupation_seconds=_occupation_seconds(r["start_time"], r["end_time"]),
            survey_time_local=_parse_dt(r["local_date"], r["local_time"]),
            survey_time_gmt=_parse_dt(r["utc_date"], r["utc_time"]),
            is_base=False,
        ))

    if n_borrados:
        result.warnings.append(
            f"Se descartaron {n_borrados} punto(s) marcados como eliminados "
            f"en la app de campo (DeleteSign=1)."
        )
    if n_sin_gps:
        result.warnings.append(
            f"Se descartaron {n_sin_gps} punto(s) sin una medición GNSS real "
            f"asociada (posiblemente un punto calculado, no levantado en campo)."
        )
    dups = result.duplicated_names()
    if dups:
        result.warnings.append(
            f"Nombres de punto repetidos: {', '.join(dups[:10])}"
            + (" ..." if len(dups) > 10 else "")
        )

    return result


def parse_stonex_file(path: str) -> StonexFile:
    """Alias con el mismo nombre que usan los demás parsers
    (`parse_dc_file`/`parse_rw5_file`) para que `agregar_stonex()` en
    `gnsseismic_windows.py` siga exactamente el mismo patrón."""
    return parse_stonex_db(path)
