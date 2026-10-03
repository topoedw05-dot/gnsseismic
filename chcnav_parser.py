# -*- coding: utf-8 -*-
"""
chcnav_parser.py
-----------------
Lector del archivo .rw5 que exporta el software de campo LandStar de
CHCNav, segunda marca (después de Hi-Target, v2.8.0/v2.9.0) agregada a
la sección "Importar datos de campo" además del .dc de Trimble.

Reconstruido por ingeniería inversa contra un archivo real aportado por
el usuario (`02082025JV.rw5`, 55 puntos GNSS de un levantamiento
topográfico cerca de Cartagena, Colombia) y VERIFICADO matemáticamente,
no adivinado: transformando la latitud/longitud (WGS84) de cada uno de
los 55 registros GPS del archivo a MAGNA-SIRGAS/Origen-Nacional
(EPSG:9377 -- el mismo CRS que el propio encabezado del archivo declara,
"User Defined:ORIGEN NACIONAL"/"WGS84/32 CM -73.0N", y que además es el
CRS de trabajo por defecto del plugin) con `pyproj`, el resultado
coincide con las coordenadas de grilla local (columnas N/E) que el
mismo archivo trae en su propio comentario "--GS" inmediatamente después
de cada registro GPS, con una diferencia máxima de 6.0e-7 m en Este y
3.7e-5 m en Norte en los 55 puntos (sub-milimétrico) -- confirma que la
convención de LA/LN (grados decimales con signo, sin conversión DMS) es
correcta, y que este archivo en particular no tiene localización/
calibración de sitio aplicada (su propio encabezado dice
"Localization File:None"/"Grid Adjustment:None", así que sus LA/LN son
WGS84 sin ajustar).

Formato del archivo (texto, delimitado por comas):

    Cada línea que no empieza con "--" es un REGISTRO: el primer campo
    (antes de la primera coma) es el código de registro (JB, MO, BP,
    GS, LS, GPS, SP); los campos siguientes son un código de 2 letras
    pegado a su valor, sin separador (ej. "PN200" = campo PN, valor
    "200"; "LA10.162030337814702" = campo LA con ese valor decimal). Un
    campo sin valor queda como el código solo (ej. "PN" a secas en un
    BP sin nombre). Puede traer, al final, un código de sufijo/
    clasificación de punto: como su propio campo separado por coma
    (",--LD") o pegado sin coma al valor del campo anterior
    ("EL15.567857143469155--BASE") -- este módulo reconoce ambas
    formas.

    Las líneas que empiezan con "--" son comentarios. La mayoría son
    metadatos de equipo/antena sin uso para importar, pero justo
    después de cada registro GPS puede venir (no siempre -- ver más
    abajo) un bloque de comentarios con estadísticas de calidad de ESE
    punto, con este formato real observado:

        GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD
        --GS,PN200,N 2681840.8278161627,E 4745123.686076916,EL13.575632946765422,--LD
        --Valid Readings: 5 of 5
        --Fixed Readings: 5 of 5
        --Nor Min: ... (varias líneas de estadística de grilla local, no usadas)
        --HSDV:0.011, VSDV:0.022, STATUS:FIXED, SATS:25, AGE:1.0, PDOP:1.574, HDOP:0.705, VDOP:1.407, TDOP:1.465, GDOP:2.150, NSDV:0.008, ESDV:0.007
        --DT08-02-2025
        --TM09:30:53

    Del bloque anterior, este módulo sólo usa: SATS, PDOP, HDOP, VDOP,
    STATUS (de la línea con "STATUS:", que es la única forma
    confiable de reconocerla) y el numerador de "Valid Readings: N of
    M" (N) como número de épocas -- igual de ambiguo/no-ambiguo que
    "N Promedios" de Hi-Target. Deliberadamente NO se usan HSDV/VSDV
    (desviación estándar cruda, no la precisión al 95% que espera
    POSTPLOT -- convertir uno en el otro sin conocer el método exacto
    del receptor sería inventar un número, el mismo criterio ya usado
    para excluir σN/σE/σZ de Hi-Target) ni AGE/TDOP/GDOP/NSDV/ESDV ni
    los mín/máx/prom de NRMS/ERMS (no hay una columna clara de POSTPLOT
    para ellos). DT/TM sólo se guardan como texto tal cual (nunca se
    interpreta su formato de fecha/hora). El comentario "--GS,..." con
    la posición en grilla local del propio punto se ignora por
    completo -- mismo criterio que ya se aplica a Hi-Target y a
    cualquier grilla local no verificable: siempre se prefiere
    transformar la latitud/longitud del registro GPS con el CRS de
    trabajo del proyecto.

    Formato alterno del bloque de calidad ("Avg/Min/Max", sin
    "STATUS:") -- VERIFICADO contra un archivo .rw5 real exportado por
    la app de campo SurPad (`LASUIZA.rw5`, 1239 puntos): para un punto
    tomado con lecturas repetidas/promediadas, en vez de la línea
    única "--HSDV:..., STATUS:..., SATS:..., PDOP:..." de arriba,
    SurPad escribe una línea POR CAMPO, cada una con su propio
    promedio/mínimo/máximo, ej.:

        --HDOP Avg: 0.6000 Min: 0.6000 Max: 0.6000
        --VDOP Avg: 1.0000 Min: 1.0000 Max: 1.0000
        --PDOP Avg: 1.2000 Min: 1.2000 Max: 1.2000
        --Number of Satellites Avg: 11 Min: 11 Max: 12

    Este módulo reconoce también estas 4 líneas (independientes entre
    sí, cada una opcional) como alternativa a la línea con "STATUS:",
    usando el valor "Avg" de cada una para PDOP/HDOP/VDOP/SATS -- NUNCA
    se infiere STATUS de aquí (este formato no trae ningún dato de
    fijo/flotante; `point.status` queda en None, igual que si el
    archivo no traiga ningún bloque de calidad). "Valid Readings: N of
    M" sigue siendo la fuente de "número de épocas" para este formato
    también -- el archivo de referencia lo trae igual en ambos casos.
    Esto permite reutilizar este mismo parser, sin ningún cambio en su
    lógica de registros GPS/BP/LS, para importar archivos .rw5 de
    SurPad (misma familia de formato que LandStar/CHCNav -- mismos
    códigos de registro JB/MO/BP/LS/GPS de 2 letras pegadas a su
    valor): de 1232 puntos de campo (no-base) del archivo de
    referencia, 1198 ya traían el bloque "STATUS:" de arriba sin
    cambios, y los 34 restantes (lecturas promediadas iniciales de
    cada punto) sólo se completan gracias a este formato alterno.

    Tipos de registro y su tratamiento:
      GPS  -> el punto a importar (lat/lon/altura elipsoidal WGS84 +
              sufijo de clasificación + estadísticas de calidad
              opcionales, ver arriba).
      BP   -> ocupación de la BASE (no un punto de campo) -- desde la
              versión que agrega la "corrección de base RTK" (import
              opcional de una coordenada de base ya corregida por
              sesión estática, ver más abajo) SÍ se convierte en un
              `ChcnavPoint` con `is_base=True`, en vez de excluirse.
              VERIFICADO contra el archivo real de referencia
              (`02082025JV.rw5`): un registro 'BP' trae los mismos
              campos PN/LA/LN/EL que un 'GPS' (mismo formato de 2
              letras + valor, sin separador), aunque casi siempre con
              'PN' vacío (sin nombre asignado) -- por eso se le arma un
              nombre sintético "BASE1"/"BASE2"/... por orden de
              aparición en el archivo cuando no trae uno propio. El
              archivo de referencia trae 4 registros 'BP' (3
              precedidos de un comentario "--Base Configuration by
              Local Coordinate"/"--Entered Base HR:...", y un 4to sin
              ese preámbulo, con campos extra AG/PA/AT/SR que este
              módulo no necesita ni interpreta) -- sus 4 coordenadas
              difieren entre sí por hasta ~0.5 m en horizontal y ~35 cm
              en altura, coherente con que cada una es una posición
              autónoma/libre (sin corregir) tomada en un instante
              distinto para la MISMA base física, exactamente el
              escenario que motiva la corrección opcional. De los 4,
              sólo BASE4 (el último, justo antes del primer 'GPS' del
              archivo) queda vigente para los 55 puntos de campo: no
              vuelve a aparecer ningún 'BP' después de él -- BASE1/2/3
              son reconfiguraciones/pruebas de enlace previas al inicio
              real del levantamiento (preceden al primer 'GPS' del
              archivo), nunca la base bajo la cual se tomó ningún
              punto. Por eso la asociación punto-base NO se hace por
              distancia (las 4 posiciones son casi idénticas entre sí
              -- unos 0.5 m -- así que "la más cercana" sería casi
              arbitraria/ruido) sino por ORDEN de aparición en el
              archivo, igual que ya hace este módulo con la altura de
              antena ('LS'/`current_ant_height`): a cada punto GPS se
              le asigna la ocupación de base 'BP' MÁS RECIENTE vista
              antes que él en el archivo ("vigente hasta que otro 'BP'
              la cambie"), quedando en None si el archivo no trae
              ningún 'BP' antes de ese punto.
      GS   -> posición en grilla local de una base o de un punto GPS;
              se ignora siempre (ver arriba).
      LS   -> altura de jalón/vara (campo "HR") VIGENTE para los
              siguientes registros GPS, hasta que otro 'LS' la cambie --
              desde la v2.22.0 se usa como altura de antena de cada
              punto GPS que venga después (ver `ChcnavPoint.ant_height`
              y la nota de verificación más abajo).
      SP   -> punto guardado SOLO con coordenadas de grilla local (N/E),
              sin latitud/longitud -- se excluye (no se puede
              transformar de forma segura sin un CRS verificado) pero
              se cuenta y se avisa cuántos se omitieron y por qué.
      JB/MO -> encabezado del trabajo, informativo -- se ignora.

    Líneas de encabezado sin estructura de comas (ej. "User Defined:
    ORIGEN NACIONAL", "WGS84/32 CM -73.0N") se ignoran sin lanzar error.

    Altura de antena/jalón (registro 'LS', campo 'HR') -- VERIFICADO
    matemáticamente, no adivinado: en el archivo real de referencia
    (`02082025JV.rw5`) cada 'LS,HR<valor>' viene precedido de un
    comentario "--Entered Rover HR:<altura_ingresada>,H Vertical" con la
    altura que el topógrafo ingresó en el colector, y de un
    "--Antenna Type:[...],RA...,SHMP<offset>,..." con el offset vertical
    de esa antena -- en las 6 apariciones del archivo, el valor de 'HR'
    coincide EXACTAMENTE (a 4 decimales) con
    altura_ingresada + SHMP (2.0 + 0.1194 = 2.1194 en las 6), así que
    'HR' es la altura de antena YA CORREGIDA por el offset del equipo,
    lista para usar directamente. La última 'LS' del archivo (línea 78)
    queda vigente para los 55 registros GPS restantes (no vuelve a
    aparecer ninguna 'LS' después) -- confirma que es "la altura vigente
    hasta que cambie", igual que el registro '57KI' de un .dc de
    Trimble, y no un dato ligado a un único punto.

Este módulo no depende de QGIS ni de PyQt: es lógica pura, igual que
`dc_parser.py`/`hitarget_parser.py`, para poder probarlo de forma
aislada.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# `_haversine_m` ya está escrita y probada en hitarget_parser.py (usada
# ahí para asociar un punto con su base RTK más cercana) -- se reutiliza
# aquí en vez de duplicarla, con el mismo patrón de import dual que ya usa
# `hitarget_raw_parser.py` (import relativo dentro del paquete del plugin,
# absoluto cuando se ejecuta suelto como en `test_gnsseismic.py`).
try:  # pragma: no cover - depende de si se importa como paquete o suelto
    from .hitarget_parser import _haversine_m
except ImportError:
    from hitarget_parser import _haversine_m

# Sufijo pegado sin coma al final del valor de un campo, ej. la "--BASE"
# de "EL15.567857143469155--BASE" o la "--LD" de "N 2681840...,--LD"
# (aunque en este segundo caso también podría venir como su propio
# token -- ver `_split_rw5_record`).
_TRAILING_SUFFIX_RE = re.compile(r"--(\w+)$")

# "--Localization File:None" / "--Grid Adjustment:None" (o un nombre de
# archivo en vez de "None") -- si alguno de los dos NO es None, LA/LN
# podría no ser WGS84 puro (calibración/ajuste de sitio aplicado).
_LOCALIZATION_RE = re.compile(r"^--Localization File:\s*(.*)$", re.IGNORECASE)
_GRID_ADJ_RE = re.compile(r"^--Grid Adjustment:\s*(.*)$", re.IGNORECASE)

# "--Valid Readings: 5 of 5" -- el numerador se usa como número de
# épocas del punto (mismo rol que "N Promedios" de Hi-Target).
_VALID_READINGS_RE = re.compile(r"^--Valid Readings:\s*(\d+)\s+of\s+(\d+)", re.IGNORECASE)

# Formato alterno "Avg/Min/Max" del bloque de calidad (sin "STATUS:"),
# una línea por campo -- ver la nota en el docstring del módulo sobre
# por qué existe (SurPad, lecturas promediadas) y por qué sólo se usa
# el valor "Avg" de cada una. El "Min"/"Max" que sigue en la misma
# línea no se captura -- no hace falta, sólo se usa para reconocer la
# línea (y porque las columnas de POSTPLOT a llenar sólo admiten un
# único valor por punto, no un rango).
_SURPAD_HDOP_RE = re.compile(r"^--HDOP\s+Avg:\s*([\d.]+)", re.IGNORECASE)
_SURPAD_VDOP_RE = re.compile(r"^--VDOP\s+Avg:\s*([\d.]+)", re.IGNORECASE)
_SURPAD_PDOP_RE = re.compile(r"^--PDOP\s+Avg:\s*([\d.]+)", re.IGNORECASE)
_SURPAD_NSATS_RE = re.compile(r"^--Number of Satellites\s+Avg:\s*(\d+)", re.IGNORECASE)

# "--DT08-02-2025" / "--TM09:30:53" -- se guardan tal cual, como texto,
# nunca se interpreta el formato de fecha/hora.
_DT_RE = re.compile(r"^--DT(.+)$")
_TM_RE = re.compile(r"^--TM(.+)$")

# Registros que se excluyen del import (silenciosamente, ver el
# docstring del módulo) además de GPS (importado), SP (excluido con
# advertencia, manejado aparte), LS (desde la v2.22.0 manejado aparte
# también -- ver `parse_rw5_text` -- para capturar su campo 'HR') y BP
# (desde la corrección de base RTK, manejado aparte para capturarlo
# como un `ChcnavPoint` con `is_base=True` en vez de descartarlo).
_RECORD_CODES_IGNORADOS = {"GS", "JB", "MO"}

# A diferencia de hitarget_parser.py/hitarget_raw_parser.py (que asocian
# cada punto con una base por DISTANCIA, porque el CSV/raw de Hi-Target
# no tiene una noción clara de "orden temporal de ocupaciones"), un .rw5
# de CHCNav SÍ es estrictamente secuencial: un 'BP' representa la
# ocupación de base VIGENTE desde ese momento del archivo en adelante,
# hasta que otro 'BP' la reemplace -- mismo patrón ya usado en este
# módulo para `current_ant_height`/'LS'. Ver la nota en el docstring
# del módulo (bajo "BP ->") sobre por qué la distancia sería aquí
# engañosa (varias ocupaciones casi idénticas entre sí, sólo una
# realmente vigente).


@dataclass
class ChcnavPoint:
    name: str  # campo PN del registro GPS
    lat: float  # campo LA, grados decimales (positivo=N, negativo=W -- sin conversión DMS)
    lon: float  # campo LN, grados decimales
    height: float  # campo EL: altura elipsoidal WGS84
    tipo: str  # código de sufijo tal cual viene en el archivo (LD/CT/CHKAM/CHKPM/... o "" si no trae)
    line_no: int  # número de línea del registro GPS en el archivo (1 = primera línea)
    # -- Estadísticas de calidad, tomadas del bloque de comentarios que
    # puede venir justo después del registro GPS (ver el docstring del
    # módulo) -- OPCIONALES: sólo 41 de los 55 puntos GPS del archivo de
    # referencia traen este bloque, los otros 14 quedan en None (no es
    # un error, el bloque simplemente no está en el archivo).
    status: Optional[str] = None  # ej. "FIXED"
    n_sats: Optional[int] = None
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    n_epochs: Optional[int] = None  # numerador de "Valid Readings: N of M"
    date_text: Optional[str] = None  # "--DT..." tal cual, sin interpretar
    time_text: Optional[str] = None  # "--TM..." tal cual, sin interpretar
    # Altura de antena/jalón vigente al momento de este punto -- desde la
    # v2.22.0, tomada del campo 'HR' del último registro 'LS' visto antes
    # de este punto (ver la nota de verificación en el docstring del
    # módulo). None si el archivo no trae ningún 'LS' antes de este
    # punto, o si su valor no se pudo interpretar.
    ant_height: Optional[float] = None
    # -- Ocupación de base (registro 'BP'), agregado para la corrección
    # opcional de base RTK libre -> corregida (ver el docstring del
    # módulo y `gnsseismic_windows.py`): True si este punto es en
    # realidad una ocupación de base (no un punto de campo levantado).
    # `base_baseline_m`/`base_station_name` son, para un punto NO-base,
    # la distancia (3D, metros) y el nombre de la ocupación de base
    # VIGENTE al momento de este punto -- el último 'BP' visto antes de
    # él en el archivo, no el más cercano por distancia (ver la nota
    # junto a `_split_rw5_record`/el docstring del módulo sobre por qué
    # aquí es por orden y no por distancia, a diferencia de
    # `hitarget_raw_parser.py`). None en ambos si el archivo no trae
    # ningún 'BP' antes de este punto. Para un punto is_base, ambos
    # quedan en None (no aplica).
    is_base: bool = False
    base_baseline_m: Optional[float] = None
    base_station_name: Optional[str] = None


@dataclass
class ChcnavFile:
    path: str
    points: List[ChcnavPoint] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    localization_file: Optional[str] = None  # None si el archivo declara "None" (sin calibración)
    grid_adjustment: Optional[str] = None

    @property
    def n_points(self) -> int:
        return len(self.points)

    def duplicated_names(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.points:
            counts[p.name] = counts.get(p.name, 0) + 1
        return {k: v for k, v in counts.items() if v > 1}


def looks_like_rw5(text: str) -> bool:
    """True si `text` tiene al menos un registro 'JB,' (encabezado del
    trabajo) y al menos un registro 'GPS,' (punto levantado) -- evita
    confundir un .rw5 de CHCNav con un .dc de Trimble (ancho fijo, sin
    comas) o un CSV de otra marca."""
    if not text:
        return False
    has_jb = False
    has_gps = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("JB,"):
            has_jb = True
        elif s.startswith("GPS,"):
            has_gps = True
        if has_jb and has_gps:
            return True
    return False


def _parse_float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(text: Optional[str]) -> Optional[int]:
    val = _parse_float(text)
    if val is None:
        return None
    try:
        return int(round(val))
    except (ValueError, OverflowError):
        return None


def _split_rw5_record(line: str) -> Optional[Tuple[str, Dict[str, str], Optional[str]]]:
    """Divide una línea de REGISTRO (no un comentario "--") en
    (código_de_registro, {código_de_2_letras: valor}, sufijo_o_None).
    Devuelve None si la línea no tiene estructura de comas o no
    arranca con un código de registro alfabético (p.ej. una línea de
    encabezado suelta como "User Defined:ORIGEN NACIONAL")."""
    if "," not in line:
        return None
    parts = line.split(",")
    record_code = parts[0].strip()
    if not record_code or not record_code.isalpha():
        return None

    fields: Dict[str, str] = {}
    suffix: Optional[str] = None
    for tok in parts[1:]:
        if tok == "":
            continue
        if tok.startswith("--"):
            # Sufijo/comentario como su propio token, ej. ",--LD".
            val = tok[2:].strip()
            if val:
                suffix = val
            continue
        m = _TRAILING_SUFFIX_RE.search(tok)
        if m:
            # Sufijo pegado sin coma al valor del campo anterior, ej.
            # "EL15.567857143469155--BASE".
            suffix = m.group(1)
            tok = tok[: m.start()]
        if len(tok) < 2:
            continue
        code = tok[:2]
        value = tok[2:].strip()
        fields[code] = value

    return record_code.upper(), fields, suffix


def _accumulate_quality_line(line: str, point: ChcnavPoint) -> None:
    """Actualiza `point` en el sitio con lo que se pueda reconocer de
    una línea de comentario ("--...") del bloque que sigue a su propio
    registro GPS. Cualquier línea no reconocida (estadísticas de
    grilla local, equipo/antena, el "--GS,..." con la posición en
    grilla local del propio punto, etc.) se ignora sin error -- ver el
    docstring del módulo para qué se usa y qué se deja fuera a
    propósito."""
    if "STATUS:" in line:
        # ej. "--HSDV:0.011, VSDV:0.022, STATUS:FIXED, SATS:25,
        # AGE:1.0, PDOP:1.574, HDOP:0.705, VDOP:1.407, TDOP:1.465,
        # GDOP:2.150, NSDV:0.008, ESDV:0.007" -- se parsea de forma
        # genérica como pares "CLAVE:valor" separados por comas, y de
        # ahí sólo se usan las claves que tienen una columna clara y
        # sin ambigüedad en POSTPLOT (ver el docstring del módulo).
        body = line.lstrip("-").strip()
        pares = {}
        for tok in body.split(","):
            if ":" not in tok:
                continue
            k, v = tok.split(":", 1)
            pares[k.strip().upper()] = v.strip()
        if "STATUS" in pares:
            point.status = pares["STATUS"]
        if "SATS" in pares:
            point.n_sats = _parse_int(pares["SATS"])
        if "PDOP" in pares:
            point.pdop = _parse_float(pares["PDOP"])
        if "HDOP" in pares:
            point.hdop = _parse_float(pares["HDOP"])
        if "VDOP" in pares:
            point.vdop = _parse_float(pares["VDOP"])
        return

    # Formato alterno "Avg/Min/Max" (sin "STATUS:", ver el docstring
    # del módulo) -- cada campo viene en su propia línea, así que se
    # revisa una por una; nunca se toca `point.status` aquí (este
    # formato no trae ese dato).
    m = _SURPAD_HDOP_RE.match(line)
    if m:
        point.hdop = _parse_float(m.group(1))
        return

    m = _SURPAD_VDOP_RE.match(line)
    if m:
        point.vdop = _parse_float(m.group(1))
        return

    m = _SURPAD_PDOP_RE.match(line)
    if m:
        point.pdop = _parse_float(m.group(1))
        return

    m = _SURPAD_NSATS_RE.match(line)
    if m:
        point.n_sats = _parse_int(m.group(1))
        return

    m = _VALID_READINGS_RE.match(line)
    if m:
        point.n_epochs = _parse_int(m.group(1))
        return

    m = _DT_RE.match(line)
    if m:
        point.date_text = m.group(1).strip()
        return

    m = _TM_RE.match(line)
    if m:
        point.time_text = m.group(1).strip()
        return

    # Cualquier otra línea de comentario (grilla local, equipo/antena,
    # estadísticas Nor/Eas/Elv/NRMS/ERMS min-max-avg, etc.) se ignora a
    # propósito.


def parse_rw5_text(text: str, path: str = "") -> ChcnavFile:
    cf = ChcnavFile(path=path)
    lines = text.splitlines()

    current_point: Optional[ChcnavPoint] = None
    n_sp_omitidos = 0
    n_bases = 0
    # Altura de antena/jalón vigente en el punto actual de la lectura del
    # archivo -- se actualiza con el campo 'HR' de cada registro 'LS' y
    # se le asigna a cada punto GPS que se parsee DESPUÉS, hasta que un
    # 'LS' posterior la cambie (ver `ChcnavPoint.ant_height` y la nota de
    # verificación en el docstring del módulo).
    current_ant_height: Optional[float] = None
    # Ocupación de base ('BP') vigente en el punto actual de la lectura
    # del archivo -- mismo patrón que `current_ant_height`, ver la nota
    # junto a `ChcnavPoint.base_baseline_m`/el docstring del módulo
    # sobre por qué es por orden de aparición y no por distancia.
    current_base: Optional["ChcnavPoint"] = None

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            current_point = None
            continue

        if line.startswith("--"):
            m = _LOCALIZATION_RE.match(line)
            if m:
                val = m.group(1).strip()
                cf.localization_file = None if val.lower() == "none" else val
            m = _GRID_ADJ_RE.match(line)
            if m:
                val = m.group(1).strip()
                cf.grid_adjustment = None if val.lower() == "none" else val
            if current_point is not None:
                _accumulate_quality_line(line, current_point)
            continue

        # Cualquier línea que no sea un comentario cierra el bloque de
        # calidad del punto GPS anterior (si había uno abierto): las
        # estadísticas de un punto SIEMPRE vienen inmediatamente
        # después de su propio registro GPS, nunca después de otro
        # registro intermedio.
        current_point = None

        parsed = _split_rw5_record(line)
        if parsed is None:
            # Línea de encabezado suelta sin estructura de comas (ej.
            # "User Defined:ORIGEN NACIONAL", "WGS84/32 CM -73.0N") --
            # puramente informativa, se ignora sin error.
            continue
        record_code, fields, suffix = parsed

        if record_code == "GPS":
            name = (fields.get("PN") or "").strip()
            lat = _parse_float(fields.get("LA"))
            lon = _parse_float(fields.get("LN"))
            height = _parse_float(fields.get("EL"))
            if not name or lat is None or lon is None or height is None:
                cf.warnings.append(
                    f"Línea {i + 1}: registro GPS incompleto (falta PN/LA/LN/EL), se omite."
                )
                continue
            baseline_m = None
            if current_base is not None:
                dist = _haversine_m(lat, lon, current_base.lat, current_base.lon)
                baseline_m = math.hypot(dist, height - current_base.height)
            point = ChcnavPoint(
                name=name, lat=lat, lon=lon, height=height,
                tipo=(suffix or "").strip(), line_no=i + 1,
                ant_height=current_ant_height,
                base_baseline_m=baseline_m,
                base_station_name=(current_base.name if current_base is not None else None),
            )
            cf.points.append(point)
            current_point = point
        elif record_code == "BP":
            lat = _parse_float(fields.get("LA"))
            lon = _parse_float(fields.get("LN"))
            height = _parse_float(fields.get("EL"))
            if lat is None or lon is None or height is None:
                cf.warnings.append(
                    f"Línea {i + 1}: registro BP (ocupación de base) sin LA/LN/EL completos, se omite."
                )
                continue
            n_bases += 1
            name = (fields.get("PN") or "").strip() or f"BASE{n_bases}"
            base_point = ChcnavPoint(
                name=name, lat=lat, lon=lon, height=height,
                tipo="BASE", line_no=i + 1, is_base=True,
            )
            cf.points.append(base_point)
            current_base = base_point
            # Un BP no trae, en el archivo de referencia, un bloque de
            # comentarios de calidad como el que sigue a un GPS (le sigue
            # un registro 'GS' con su posición en grilla local, que de
            # todas formas se ignora) -- no se deja `current_point`
            # abierto para él.
        elif record_code == "LS":
            hr = _parse_float(fields.get("HR"))
            if hr is not None:
                current_ant_height = hr
        elif record_code == "SP":
            n_sp_omitidos += 1
        elif record_code in _RECORD_CODES_IGNORADOS:
            pass
        # Cualquier otro código de registro no reconocido: se ignora
        # también, por la misma razón (nunca se adivina qué es).

    if n_sp_omitidos:
        cf.warnings.append(
            f"{n_sp_omitidos} punto(s) 'SP' omitido(s): sólo traen coordenadas de "
            "grilla local (N/E), sin latitud/longitud, así que no se pueden "
            "transformar de forma segura."
        )
    if cf.localization_file:
        cf.warnings.append(
            f"El archivo declara un archivo de localización ('{cf.localization_file}'): "
            "es posible que la latitud/longitud no sea WGS84 puro (calibración de sitio aplicada)."
        )
    if cf.grid_adjustment:
        cf.warnings.append(
            f"El archivo declara un ajuste de grilla ('{cf.grid_adjustment}'): "
            "es posible que la latitud/longitud no sea WGS84 puro."
        )

    dup = cf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        cf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplos})."
        )

    return cf


# Orden de codificaciones a probar en `parse_rw5_file` cuando no se pide
# una explícita -- ver la nota de verificación junto a esa función: el
# archivo real de CHCNav usado para construir este módulo era ASCII puro
# (subconjunto válido de UTF-8), pero un archivo real de SurPad
# (`LASUIZA.rw5`, aportado por el usuario) resultó traer texto de Status
# en español con tildes ("Autónomo") guardado en Windows-1252/Latin-1 de
# un solo byte (ej. 'ó' = 0xF3), no en UTF-8 -- "'utf-8' codec can't
# decode byte 0xf3..." fue el error real que QGIS mostró al intentar
# importarlo antes de este fix. 'cp1252' se prueba antes que 'latin-1'
# porque interpreta mejor algunas comillas/guiones "tipográficos" que un
# editor de Windows podría haber guardado; 'latin-1' nunca falla (mapea
# cualquier byte 1 a 1) y queda como último recurso para no bloquear la
# importación por un problema de codificación.
_ENCODINGS_RW5 = ("utf-8-sig", "cp1252", "latin-1")


def parse_rw5_file(path: str, encoding: Optional[str] = None) -> ChcnavFile:
    """Lee y parsea un .rw5 de CHCNav/LandStar/SurPad desde disco.

    Si `encoding` no se especifica, se prueban en orden las de
    `_ENCODINGS_RW5` -- 'utf-8-sig' primero (descarta un BOM si está
    presente, sin fallar si no lo está) y se cae a 'cp1252'/'latin-1'
    si el archivo no es UTF-8 válido (ver la nota junto a
    `_ENCODINGS_RW5` sobre por qué hace falta: un .rw5 real de SurPad
    con texto de Status en español tildado, guardado en Windows-1252).
    Pasar `encoding` fuerza una codificación específica y desactiva
    este fallback."""
    encodings = (encoding,) if encoding else _ENCODINGS_RW5
    text = None
    ultimo_error: Optional[UnicodeDecodeError] = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                text = f.read()
            break
        except UnicodeDecodeError as e:
            ultimo_error = e
            continue
    if text is None:
        raise ultimo_error
    if not looks_like_rw5(text):
        raise ValueError(
            "El archivo no parece un .rw5 de CHCNav/LandStar/SurPad (no se "
            "encontraron registros 'JB'/'GPS')."
        )
    return parse_rw5_text(text, path=path)
