# -*- coding: utf-8 -*-
"""
dc_parser.py
------------
Lector del formato de texto ".dc" (Data Collector) que exportan los
receptores GNSS/RTK usados en campañas topográficas y de posicionamiento
sísmico (ej. levantamiento de puntos receptores/fuente en prospección
sísmica).

El formato es de ANCHO DE CAMPO VARIABLE pero con una estructura de
registros muy regular: cada línea empieza con un código de 4 caracteres
(ej. "66KI", "66SO", "10NM", "13TS", "64TM"...). Los registros de punto
("66KI" y "66SO" en los archivos analizados, más "66SI"/"66FD" para una
ocupación de base RTK física -- ver `BASE_CODES` -- en archivos "clásicos"
de antes de que existiera el RTX) contienen, en este orden:

    <código 4><relleno de 8><nombre de punto, 8><latitud><longitud><altura>...

Las tres coordenadas siempre se representan como números decimales con
punto ("-37.096757440900"), en un campo de ANCHO FIJO (ver
`_NUM_FIELD_WIDTH`) que se ubica siempre a partir del carácter 16 del
cuerpo de la línea (8 sin usar + 8 de nombre, ver `_split_name_and_coords`
-- confirmado contra 3 archivos reales, 27563 registros de punto en
total). El nombre puede además compartirse entre DOS registros de un
mismo punto con prefijos numéricos distintos ("66"/"67"): un archivo
"clásico" (ar180118.dsc) trae, para 229 de sus 315 puntos, tanto un
'66KI' (posición geodésica, sin calidad) como un '67SO' -- mismo rol que
un '66SO' normal, sólo con otro prefijo -- cuyo 'C6NM' siguiente sí trae
calidad real; ese caso especial "asciende" el '66KI' ya agregado a
record_type='SO' en vez de agregar un punto nuevo (ver el caso especial
de '67SO' en `parse_dc_text`). Las TRES coordenadas propias del '67SO'
NO son geográficas -- son (ΔNorte, ΔEste, ΔAltura) de ese punto RESPECTO
A LA BASE RTK vigente, en un marco local topocéntrico centrado en la
base (verificado contra la base de datos POSTPLOT real que exporta
GPSeismic para este mismo archivo: `sqrt(ΔN²+ΔE²+ΔAltura²)` coincide, al
milímetro, con su columna "GPS Baseline" para los 229 puntos
verificados -- antes de esta ronda se creía, incorrectamente, que eran
una cuadrícula local sin uso posible; ver `DCPoint.base_baseline_m` y el
caso especial de '67SO' en `parse_dc_text`). El mismo archivo trae,
además, 4 apariciones de '67TP' -- mismo mecanismo de promoción que
'67SO' (mismo layout, mismo 'C6NM' de calidad que sigue) pero que señala
una ocupación DESCARTADA en campo: las 4 coinciden, nombre por nombre,
con los 4 únicos puntos que la base de datos POSTPLOT real marca con un
prefijo "D" (borrado) -- ver `DCPoint.deleted` y el caso especial de
'67SO'/'67TP' en `parse_dc_text`, que también cubre el patrón real de
"se descarta una ocupación y se vuelve a levantar el mismo punto" (un
'67TP' seguido más adelante por un '67SO' del mismo nombre, ej.
"51802277").

Otro registro por punto, aparte de los de posición: '13NM' trae un
comentario de operador -- con o sin un nombre de punto de 8 caracteres
pegado adelante (ver `DCPoint.comment` y el caso especial de '13NM' en
`parse_dc_text`) -- y, si su texto empieza con "Eliminado", marca el
punto como borrado en campo (`DCPoint.deleted`, verificado también
contra la base de datos POSTPLOT real: coincide texto por texto con el
comentario de sus 4 puntos "D"-prefijados).

Este módulo no depende de QGIS ni de PyQt: es lógica pura, para poder
probarlo de forma aislada y para poder reutilizarlo también fuera del
plugin (scripts de línea de comandos, etc).
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as _dt_date, datetime as _dt_datetime, timezone as _dt_timezone, timedelta as _dt_timedelta
from typing import List, Optional, Dict, Tuple

# `_haversine_m` ya está escrita y probada en hitarget_parser.py (usada
# ahí para asociar un punto con su base RTK más cercana, y reutilizada
# también por chcnav_parser.py) -- se reutiliza aquí en vez de
# duplicarla, con el mismo patrón de import dual que ya usan esos dos
# módulos (import relativo dentro del paquete del plugin, absoluto
# cuando se ejecuta suelto como en `test_gnsseismic.py`).
try:  # pragma: no cover - depende de si se importa como paquete o suelto
    from .hitarget_parser import _haversine_m
except ImportError:
    from hitarget_parser import _haversine_m

# Un número con signo opcional, parte entera y parte decimal obligatoria.
_FLOAT_RE = re.compile(r"-?\d+\.\d+")
_FLOAT_FULL_RE = re.compile(r"^\s*-?\d+\.\d+\s*$")

# Ancho fijo (en caracteres) de cada campo numérico (latitud/longitud/
# altura) observado en los archivos .dc analizados: el formato usa un
# ancho TOTAL constante por campo y hace flotar la cantidad de decimales
# para llenarlo siempre (p.ej. "-37.096757440900" y "0.00000000000000"
# ocupan ambos 16 caracteres). Como los campos van pegados sin
# separador, NO se pueden extraer con una expresión regular corrida
# sobre toda la línea (dos números consecutivos pueden "fusionarse" en
# un solo match); en cambio se localiza el bloque de 3 campos de ancho
# fijo consecutivos (lat, lon, altura) desplazando una ventana.
_NUM_FIELD_WIDTH = 16

# KI -> punto "cinemático" (RTK, levantamiento rápido; en los archivos
#       sísmicos observados corresponde a puntos receptor/estaca, sin
#       altura elipsoidal fiable -> se reporta 0.0, y sin ningún dato de
#       calidad asociado en este formato de .dc).
# SO -> punto de "estación"/fuente, levantado con más control de calidad
#       (trae, en la línea siguiente, un registro 'C6NM' con
#       satélites/PDOP/HDOP/VDOP/épocas/duración -- ver
#       `_parse_c6nm_quality`).
# BASE -> ocupación de una base RTK física (ver `BASE_CODES` más abajo) --
#       sólo presente en archivos "clásicos" de antes de que existiera el
#       RTX (confirmado por el propio usuario); un archivo RTX-corregido
#       no la trae porque no usa una base propia.

# Sufijos que SIEMPRE son puntos con coordenadas (lat, lon, altura).
COORD_SUFFIXES = ("KI", "SO")

# Códigos EXACTOS de 4 caracteres que representan la ocupación de una
# base RTK física en archivos Trimble '.dc' "clásicos" (de antes de que
# existiera el RTX -- así lo confirmó el usuario al subir el archivo real
# de referencia, ar180118.dsc). En ese archivo, '66SI' aparece UNA sola
# vez ("SI" = establecimiento inicial del sitio/base) y '66FD' aparece 4
# veces más ("FD" = "Found", el reconocimiento/reocupación de esa MISMA
# base al empezar cada una de las 4 sesiones de trabajo posteriores) --
# las 5 apariciones traen, byte a byte, el mismo nombre ("SA01") y las
# mismas coordenadas (lat -45.711423407377, lon -68.149230633001, altura
# 703.6920093297965 m WGS84), exactamente el mismo patrón ya verificado y
# manejado para la base física de CHCNav ('BP', v2.24.0) y de Hi-Target
# ('set_base').
#
# A diferencia de 'KI'/'SO' esto NO se generaliza por sufijo de 2 letras
# agregándolo a `COORD_SUFFIXES`: el mismo archivo real trae un registro
# NO relacionado ('E2SI', descripción de antena/receptor) que comparte el
# sufijo 'SI' pero cuyo cuerpo trae un triple de coordenadas en CEROS
# ("0.000000000000000.000000000000000.00000000000000") -- generalizar
# por sufijo lo haría pasar como un punto falso en (0, 0, 0). Por eso se
# reconoce por el código COMPLETO de 4 caracteres, nunca por sufijo.
BASE_CODES = ("66SI", "66FD")

# Códigos de registro auxiliares/de atributo (no son un punto en sí)
# cuyo sufijo de 2 letras coincide con COORD_SUFFIXES y que por eso,
# antes de la v2.10.0, disparaban una advertencia de "no se pudo
# interpretar" por cada uno -- identificados analizando un archivo .dc
# real (3001YC.dc, ~13800 puntos) que los trae en volumen: 'C6NM'/'60NM'
# (calidad/precisión, uno por cada punto 'SO'), 'A0SO'/'A5SO' (nombre del
# punto repetido + desplazamientos respecto al diseño, también uno por
# 'SO'), y los registros raros de una sola aparición al principio de cada
# ocupación/sesión de campo ('57KI' altura de antena vigente -- desde la
# v2.22.0 decodificado, ver `_parse_57ki_antenna_height` --, '50KI'/
# '56KI'/'82KI'/'71KI' de significado no confirmado). Se dejan de
# advertir porque son parte normal y esperada del formato, no un
# registro de punto mal formado.
#
# '73KI' se agregó en la ronda de soporte a base RTK física (ver
# `BASE_CODES`), identificado en un archivo real (ar180118.dsc): repite
# el nombre de la base ("SA01") sin coordenadas (4 apariciones, una por
# sesión, igual que '66FD'), de significado no confirmado más allá de
# eso. ('67SO', visto en el mismo archivo, NO es un registro auxiliar
# ignorable -- resultó ser un '66SO' real con otro prefijo numérico, y
# desde la ronda de soporte a sus datos de calidad se maneja aparte, con
# su propio caso especial en `parse_dc_text`, antes de llegar siquiera a
# este chequeo.)
KNOWN_AUX_CODES = {
    "C6NM", "60NM", "A0SO", "A5SO", "57KI", "50KI", "56KI", "82KI", "71KI",
    "73KI",
}

# El mismo tipo de registro auxiliar puede aparecer con un sufijo de 2
# letras DISTINTO según el sistema/datum de coordenadas que use ese
# trabajo dentro del archivo -- confirmado con un segundo archivo real
# del usuario (jg-28-08-26.dsc, Argentina/POSGAR07 Faja 2) que repite,
# con sufijo 'KI' en vez de 'TM', los mismos registros de parámetros de
# datum/proyección ya vistos con sufijo 'TM' en 3001YC.dc ('65TM'/'D5TM'/
# 'D8TM'/'64TM'/'49TM'/'81TM' -> aquí '65KI'/'D5KI'/'D8KI'/'64KI'/'49KI'/
# '81KI', mismo contenido: elipsoide, proyección, y un nombre de datum
# real como 'POSGAR07'/'Faja 2'/'Argentina'). Por eso además de
# `KNOWN_AUX_CODES` (códigos completos de 4 letras) se reconoce por
# PREFIJO de 2 letras cualquier familia de registro auxiliar ya
# confirmada, sin importar qué sufijo traiga esta vez -- evita tener que
# ir agregando un código completo nuevo por cada combinación de
# sufijo/datum que aparezca en futuros archivos reales.
KNOWN_AUX_PREFIXES = {"65", "D5", "D8", "64", "49", "81"}


def _read_sigfig_field(s: str, n_sig: int):
    """Lee, desde el principio de `s`, un número con signo opcional cuya
    cantidad TOTAL de dígitos significativos (parte entera + parte
    decimal, sin contar el punto ni el signo) es exactamente `n_sig`.

    Los campos numéricos de un '.dc' van pegados sin separador y NO
    tienen un ancho de caracteres fijo -- lo fijo es la cantidad de
    dígitos significativos (comprobado con datos reales: la altura de
    un '66SO' con 3 dígitos enteros como "998.59044245164857" mide 18
    caracteres, no los 16 de un '66KI' con altura "0.00000000000000",
    pero ambas tienen exactamente 15 dígitos significativos). Devuelve
    `(texto_del_numero, caracteres_consumidos)` o `None` si `s` no
    empieza con un número de esa forma.
    """
    i = 0
    if i < len(s) and s[i] == "-":
        i += 1
    dot_idx = s.find(".", i)
    if dot_idx == -1:
        return None
    int_part = s[i:dot_idx]
    if not int_part.isdigit():
        return None
    n_dec = n_sig - len(int_part)
    if n_dec < 0:
        return None
    dec_part = s[dot_idx + 1 : dot_idx + 1 + n_dec]
    if len(dec_part) < n_dec or not dec_part.isdigit():
        return None
    consumed = dot_idx + 1 + n_dec
    return s[:consumed], consumed


# ---------------------------------------------------------------------------
# "Hora de levant. (Local/GMT)" y "Hora serial (GPS)" -- calibración por
# semana de trabajo.
# ---------------------------------------------------------------------------
#
# Contexto (ver el docstring de `_parse_c6nm_quality` para la fórmula base):
# `Serial_Time_GPS = (t_inicio_sesion + occupation_seconds) - K`, con `K`
# una constante que NO es universal ni fija por archivo -- salta cada vez
# que el receptor se reinicia de verdad (en la práctica, en el fin de
# semana), pero se mantiene EXACTA dentro de una misma racha de días de
# trabajo. Confirmado con acceso a 66 archivos reales del usuario (21/ene
# al 7/feb/2026): el mismo K es válido para TODA una semana de trabajo, en
# archivos de recepetores y operadores distintos.
#
# Hallazgo nuevo de esta ronda (con los archivos de referencia reales
# `0502yc.dsc.mdb` y `ar210118.dsc.mdb` aportados por el usuario): una vez
# resuelto `Serial_Time_GPS` para un punto, "Survey Time (GMT)" sale de una
# constante UNIVERSAL (no depende de la semana ni del receptor):
#
#     Survey_Time_GMT (unix) = Serial_Time_GPS + 315964800
#
# Verificada EXACTA (segundo a segundo, 0 de margen) contra 4 puntos de
# referencia reales de 2 campañas totalmente independientes, con 8 años y 2
# modelos de receptor de diferencia:
#   - `3001YC.dc` (R12i, semana ISO 2026-05), punto "14095304": 207/207
#     puntos del POSTPLOT completo.
#   - `0502YC.dc` (R12i, semana ISO 2026-06), punto "15535147": 196/196
#     puntos del POSTPLOT completo -- semana de referencia NUEVA de esta
#     ronda, la que permitió confirmar que K salta en cada fin de semana
#     Y descubrir esta constante universal.
#   - `ar180118.dsc` (R6-2, semana ISO 2018-03), punto "PF10": 229/229
#     puntos del POSTPLOT completo.
#   - `ar210118.dsc` (R6-2, MISMA semana ISO 2018-03 que el anterior --
#     21/ene/2018 es domingo, último día de esa semana ISO -- estación
#     "CHK01SA"): verificado sin necesitar su archivo .dc/.dsc crudo
#     (que el usuario no tenía disponible), porque esta fórmula sólo
#     necesita el propio "Serial Time (GPS)" real del POSTPLOT, no
#     `t_inicio_sesion`.
# 632 puntos con POSTPLOT completo + 1 punto suelto, sin ninguna excepción
# real (la única fila que no coincide en cada archivo es la reocupación
# ambigua ya conocida, `DCPoint.ambiguous_reoccupation`, un caso especial
# documentado desde antes, no un fallo de esta fórmula).
_SERIAL_GPS_TO_GMT_UNIX_OFFSET = 315964800

# Offset fijo de "Hora de levant. (Local)" respecto de "Hora de levant.
# (GMT)", en horas. NO es el huso horario real del sitio de trabajo --
# confirmado en la investigación de la v2.43.0: un archivo real de
# Colombia (huso real UTC-5) y otro de Argentina (huso real UTC-3)
# mostraban, los DOS, exactamente el mismo desfase de 5 horas -- es una
# preferencia que el operador configuró una sola vez en QuikView ("Local
# Time Offset From GMT (HH.MM)", ver `quikview.chm`) y nunca volvió a
# tocar, incluso entre campañas de 2018 y 2026. Confirmada de nuevo, 4/4,
# contra los mismos 4 puntos de referencia de arriba. A diferencia de la
# constante de GMT de arriba (una propiedad del propio dato), ÉSTA es una
# preferencia de software del usuario -- si algún día la cambia en su
# QuikView, esta columna quedaría desactualizada sin forma de saberlo
# desde el .dc en sí (no hay nada que avise de ese cambio).
_LOCAL_TIME_OFFSET_HOURS = 5

# Tabla de calibración "K por semana de trabajo": clave (año ISO, semana
# ISO) de la fecha real del archivo (calculada sola de su propio '13TS',
# ver `DCFile.date_text` -- no hace falta que el usuario indique nada).
# Valor: el offset (segundos) a sumarle a `t_inicio_sesion +
# occupation_seconds` de cualquier punto 'SO' de esa semana para obtener
# su "Survey Time (GMT)" real, en timestamp Unix -- ver
# `_calibrar_horas_gps` para la fórmula completa.
#
# Semana sin entrada acá => los tres campos (`survey_time_gmt`/
# `survey_time_local`/`serial_time_gps`) quedan en `None`, igual que hasta
# ahora -- mismo criterio de "exacto o en blanco, nunca inventado" del
# resto del plugin. Cada vez que el usuario aporte un dato real de
# referencia (un POSTPLOT completo, o un solo punto con su "Serial Time
# (GPS)"/"Survey Time (GMT)" real) de una semana todavía sin calibrar, se
# agrega una entrada acá y esa semana queda resuelta para siempre -- sin
# tener que investigar de nuevo desde cero.
_GMT_WEEK_CALIBRATION = {
    # Semana ISO 2018-03 (15-21/ene/2018) -- `ar180118.dsc`, punto "PF10"
    # (Serial Time GPS real=1200312708, Survey Time GMT real=
    # "01/18/18 12:11:48"). El offset calibrado directo contra ESE único
    # punto (-468112000.6) dejaba 90 de 229 puntos del archivo desviados
    # por exactamente 1 segundo -- el redondeo de `_calibrar_horas_gps`
    # queda ambiguo cuando la parte fraccionaria del segundo (`t_inicio_
    # sesion`/`occupation_seconds` sólo traen 1 dígito decimal en este
    # archivo, receptor R6-2) cae justo cerca del borde ,4/,5 -- una
    # limitación de precisión del propio archivo, no del cálculo. Se
    # ajustó el offset a -468112000.4 probando, contra el POSTPLOT
    # COMPLETO real (no sólo PF10), todos los valores de offset posibles
    # dentro del margen de esa ambigüedad (paso de 0.1s) y quedándose con
    # el que maximiza coincidencias exactas: 228/229 puntos no descartados
    # (el único que no cuadra es la reocupación ambigua ya conocida,
    # `DCPoint.ambiguous_reoccupation`, no un fallo de esta calibración) --
    # y, por separado, contra un punto suelto de `ar210118.dsc` (misma
    # semana ISO, domingo 21/ene/2018, estación "CHK01SA") -- ver el
    # docstring de `_SERIAL_GPS_TO_GMT_UNIX_OFFSET`.
    (2018, 3): -468112000.4,
    # Semana ISO 2026-05 (26/ene-1/feb/2026) -- `3001YC.dc`, punto
    # "14095304" (Serial Time GPS real=1453807416, Survey Time GMT real=
    # "01/30/26 11:23:36"). Verificado exacto contra el POSTPLOT COMPLETO
    # de ese archivo (207/207 puntos no descartados).
    (2026, 5): -633700800.0,
    # Semana ISO 2026-06 (2-8/feb/2026) -- `0502YC.dc`, punto "15535147"
    # (Serial Time GPS real=1454329343, Survey Time GMT real=
    # "02/05/26 12:22:23"). Verificado exacto contra el POSTPLOT COMPLETO
    # de ese archivo (196/196 puntos con dato de calidad). Semana de
    # referencia aportada por el usuario en esta misma ronda, la que
    # confirmó al segundo exacto que K salta en cada fin de semana.
    (2026, 6): -634096000.0,
}


# ---------------------------------------------------------------------------
# Calibración AUTOMÁTICA de K, sin tabla manual -- a partir de las propias
# marcas '13TS' del archivo. Hallazgo de esta ronda, a pedido explícito del
# usuario, que insistió (con razón) en que tenía que haber una forma de
# resolver esto sin depender de que él aporte un dato de referencia cada
# vez ("el gpseismic que estoy usando... tiene 20 años... y lo resuelve
# bien... tiene que haber un algoritmo... investiga más a profundidad").
#
# `DCFile.date_text` sólo guarda el PRIMER '13TS' del archivo (fecha del
# job), pero en realidad el archivo trae MUCHOS más -- cada vez que el
# colector de campo vuelve a escribir su hora de sistema, típicamente
# justo antes de empezar un punto nuevo: la línea '13TS' queda seguida,
# dos líneas después (saltando el '66SO' del punto), por el 'C6NM' de
# calidad de ESE punto. Esa hora de sistema NO es la hora real exacta
# (ver más abajo por qué), pero viaja muy cerca de ella con un desfase
# CASI constante -- lo suficiente para, con VARIAS marcas del mismo
# archivo votando entre sí, deducir el mismo K exacto que hasta ahora
# sólo se conseguía con un dato de referencia real aportado a mano.
#
# Verificación (66 archivos reales + los 2 nuevos de esta ronda,
# `rg220826.dsc`/`rg230826.dsc`, antes sin calibrar): tomando, para cada
# marca '13TS' seguida así de un 'C6NM' (patrón "gap=2"), el candidato de
# K que resulta de asumir que esa hora de sistema, MENOS una constante
# `_TS_ANCHOR_DELTA_SECONDS`, es la hora local real de ESE punto (misma
# fórmula que `_calibrar_horas_gps`, sólo que despejando K en vez de
# aplicándolo) -- y votando por MAYORÍA entre todas las marcas del mismo
# archivo -- se reproduce, EXACTO, el K ya confirmado a mano por
# referencia real en los 2 archivos donde se tenía (`3001YC.dc`,
# `0502YC.dc`: mayoría exacta en 5/6 y 3/5 marcas respectivamente), y da
# un resultado consistente día a día para el resto del corpus real (ej.
# `DP050226.dc`, mismo día calendario que `0502YC.dc`: 5/5 marcas
# coinciden en un K a solo 1 segundo del ya confirmado). Con el corpus de
# agosto de 2026 (`rg140826.dsc` a `rg280826.dsc`, mismo receptor) se
# confirmó además algo importante: K NO cambia sólo de semana en semana --
# cambia cada vez que el receptor se reinicia de verdad, que puede ser
# cualquier noche (`rg220826.dsc` y `rg230826.dsc`, aunque caen en la
# MISMA semana ISO, dan K completamente distintos -- hubo un reinicio real
# entre esos dos días) o mantenerse igual varios días seguidos
# (`rg180826.dsc` a `rg220826.dsc`, 5 días, un solo K). Por eso esta
# calibración automática es POR ARCHIVO, no por semana ISO: cada archivo
# vota su propio K con sus propias marcas, sin asumir nada sobre archivos
# vecinos.
#
# ¿De dónde sale `_TS_ANCHOR_DELTA_SECONDS` (7183s, ~1h59m43s)? Se dedujo
# de los mismos archivos ya confirmados (`3001YC.dc`/`0502YC.dc`, R12i
# 2026) y se corroboró, sin cambiar de valor, contra `ar180118.dsc` (R6-2,
# 2018, 8 años y un receptor distinto) -- el desfase entre '13TS' y la
# hora real resultó CASI idéntico en los tres, lo que sugiere una
# constante del propio software (QuikView/GPSeismic), no del receptor ni
# del reloj de un colector en particular. No se pudo confirmar el porqué
# exacto (podría ser un supuesto de huso horario fijo, +/- algún ajuste de
# segundos intercalares GPS-UTC) -- no hizo falta: para esta calibración
# sólo importa que sea estable, y lo es (+/-1-4s de margen entre marcas
# del mismo archivo, jamás al punto de cambiar la mayoría en ninguno de
# los archivos con referencia real disponible).
#
# Umbral de confianza (mismo criterio de "exacto o en blanco, nunca
# inventado" del resto del plugin, aplicado ahora a un consenso interno en
# vez de a un dato externo): se necesitan al menos
# `_TS_ANCHOR_MIN_COUNT` marcas utilizables, el candidato más votado tiene
# que ganarle estrictamente a cualquier otro (nunca un empate), y tiene
# que representar al menos la mitad de las marcas. Si no se cumple
# (archivo con pocas marcas '13TS' en este patrón, o un archivo real donde
# el reinicio del receptor ocurrió A MITAD de las marcas disponibles,
# partiendo el voto) las tres columnas quedan en blanco -- igual que
# cuando no hay ninguna calibración disponible en absoluto.
_TS_ANCHOR_DELTA_SECONDS = 7183
_TS_ANCHOR_MIN_COUNT = 3


def _recolectar_anclas_13ts(lines: List[str]) -> List[Tuple["_dt_datetime", float]]:
    """Marcas ('13TS', `t_inicio_sesion + occupation_seconds` del punto
    asociado) útiles para `_derivar_offset_automatico` -- ver el docstring
    completo junto a `_TS_ANCHOR_DELTA_SECONDS`. Sólo cuenta un '13TS'
    cuando, dos líneas después (saltando exactamente una línea -- el '66SO'
    del punto), aparece un 'C6NM' interpretable: ese patrón exacto
    ("gap=2") es el único verificado como confiable contra los archivos
    reales disponibles -- un '13TS' más lejos de su 'C6NM' más cercano
    (ej. el primero del archivo, seguido de varios registros de
    configuración de la base antes del primer punto) da candidatos muy
    alejados de la realidad y se descarta directamente, sin intentar
    adivinar a qué punto correspondía."""
    anclas: List[Tuple["_dt_datetime", float]] = []
    n = len(lines)
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if not line.startswith("13TS"):
            continue
        fecha_hora = _extract_date_text(line)
        if not fecha_hora:
            continue
        dt = None
        for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
            try:
                dt = _dt_datetime.strptime(fecha_hora, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            continue
        j = i + 2
        if j >= n:
            continue
        siguiente = lines[j].rstrip("\r\n")
        if not siguiente.startswith("C6NM"):
            continue
        quality = _parse_c6nm_quality(siguiente)
        if (
            quality is None
            or quality["t_inicio_sesion"] is None
            or quality["occupation_seconds"] is None
        ):
            continue
        t2 = quality["t_inicio_sesion"] + quality["occupation_seconds"]
        anclas.append((dt, t2))
    return anclas


def _derivar_offset_automatico(anclas: List[Tuple["_dt_datetime", float]]):
    """Offset (mismas unidades/convención que `_GMT_WEEK_CALIBRATION`) que
    resulta de hacer votar por mayoría a `anclas` (ver
    `_recolectar_anclas_13ts`), o `None` si no hay suficiente consenso --
    ver el umbral de confianza documentado junto a `_TS_ANCHOR_DELTA_SECONDS`."""
    if len(anclas) < _TS_ANCHOR_MIN_COUNT:
        return None
    candidatos = []
    for dt, t2 in anclas:
        local_estimado = dt - _dt_timedelta(seconds=_TS_ANCHOR_DELTA_SECONDS)
        gmt_estimado = local_estimado + _dt_timedelta(hours=_LOCAL_TIME_OFFSET_HOURS)
        gmt_unix_estimado = (gmt_estimado - _dt_datetime(1970, 1, 1)).total_seconds()
        candidatos.append(round(gmt_unix_estimado - t2))
    conteo = Counter(candidatos).most_common()
    mejor, n_mejor = conteo[0]
    n_segundo = conteo[1][1] if len(conteo) > 1 else 0
    if n_mejor <= n_segundo:
        return None
    if n_mejor * 2 < len(candidatos):
        return None
    return float(mejor)


def _week_key_from_date_text(date_text):
    """(año ISO, semana ISO) de `DCFile.date_text` (sólo la FECHA del
    primer '13TS' del archivo -- ver la nota junto a ese campo), o `None`
    si no hay fecha o no se pudo interpretar. Se usa para buscar en
    `_GMT_WEEK_CALIBRATION` sin pedirle nada al usuario: la semana sale
    sola de la fecha que el propio archivo ya trae."""
    if not date_text:
        return None
    try:
        fecha_part = date_text.split(" ")[0]
        mes, dia, anio = (int(x) for x in fecha_part.split("/"))
        anio_iso, semana_iso, _dia_iso = _dt_date(anio, mes, dia).isocalendar()
        return (anio_iso, semana_iso)
    except (ValueError, IndexError):
        return None


def _calibrar_horas_gps(dc: "DCFile", lines: List[str]) -> None:
    """Completa `survey_time_gmt`/`survey_time_local`/`serial_time_gps` de
    cada punto 'SO'/'KI' de `dc` con `t_inicio_sesion`/`occupation_seconds`
    conocidos. Dos fuentes posibles para el offset, en este orden:

    1. La tabla manual `_GMT_WEEK_CALIBRATION`, indexada por la semana ISO
       del archivo (`_week_key_from_date_text(dc.date_text)`) -- semanas ya
       confirmadas con un dato de referencia real aportado por el usuario,
       con precisión verificada incluso al sub-segundo (ver esa tabla).
       Tiene prioridad porque es más precisa que la automática de abajo
       para los casos en que ya se confirmó a mano.
    2. Si la semana no está en la tabla manual, `_derivar_offset_automatico`
       sobre las marcas '13TS' del propio archivo (`_recolectar_anclas_13ts`)
       -- ver el docstring completo junto a `_TS_ANCHOR_DELTA_SECONDS` para
       el hallazgo y su verificación. Es POR ARCHIVO, no por semana: cada
       archivo se calibra solo, con sus propias marcas.

    Si ninguna de las dos fuentes da un offset confiable, los tres campos
    quedan en `None` (como ya estaban por defecto) -- mismo criterio de
    "exacto o en blanco, nunca inventado" en ambos casos. Se llama al final
    de `parse_dc_text`, después de calcular `elapsed_seconds`, porque no
    depende de él ni del orden de aparición.
    """
    week_key = _week_key_from_date_text(dc.date_text)
    offset = _GMT_WEEK_CALIBRATION.get(week_key) if week_key is not None else None
    if offset is None:
        anclas = _recolectar_anclas_13ts(lines)
        offset = _derivar_offset_automatico(anclas)
    if offset is None:
        return
    for p in dc.points:
        if p.is_base or p.t_inicio_sesion is None or p.occupation_seconds is None:
            continue
        t2 = p.t_inicio_sesion + p.occupation_seconds
        gmt_unix = round(t2 + offset)
        p.serial_time_gps = int(round(gmt_unix - _SERIAL_GPS_TO_GMT_UNIX_OFFSET))
        gmt_dt = _dt_datetime.fromtimestamp(gmt_unix, tz=_dt_timezone.utc)
        local_dt = gmt_dt - _dt_timedelta(hours=_LOCAL_TIME_OFFSET_HOURS)
        p.survey_time_gmt = gmt_dt.strftime("%Y-%m-%d %H:%M:%S")
        p.survey_time_local = local_dt.strftime("%Y-%m-%d %H:%M:%S")


# Ancho fijo (2 caracteres) del contador de satélites al principio de un
# registro 'C6NM', y cantidad de dígitos significativos de sus tres
# campos de precisión (PDOP/HDOP/VDOP) -- deducidos por ingeniería
# inversa contra un archivo .dc real del usuario (3001YC.dc) y un
# reporte de ese mismo punto (14095304) con sus valores reales conocidos
# de antemano: Number of Satellites=22, PDOP=1.14, HDOP=0.57, VDOP=0.98.
# Verificado además, para los 208 registros 'C6NM' de ese archivo (uno
# por cada punto 'SO'), que PDOP == sqrt(HDOP² + VDOP²) con un margen de
# +/-0.001 en 203 de 208 (las 5 restantes difieren menos del 2%, dentro
# de lo esperable por redondeo propio del receptor) -- confirma que los
# límites de campo son correctos y no una coincidencia de un solo punto.
_C6NM_SATS_WIDTH = 2
_C6NM_DOP_SIGFIGS = 15


def _parse_c6nm_quality(line: str):
    """Interpreta un registro 'C6NM' (sólo aparece, uno por uno, después
    de cada punto '66SO' -- nunca después de un '66KI', que en este
    formato de .dc no trae ningún dato de calidad). Devuelve un dict con
    `n_sats`/`pdop`/`hdop`/`vdop`/`n_epochs`/`occupation_seconds`, o
    `None` si la línea no matchea la forma esperada (para no reventar ni
    inventar datos ante un formato de receptor distinto).

    Después de satélites+PDOP+HDOP+VDOP, el registro trae un CUARTO campo
    numérico del mismo ancho fijo (15 dígitos significativos) que las 3
    DOP -- descubierto en esta ronda al reparar la lectura de "épocas"
    para ar180118.dsc, que sin saltar este campo quedaba SIEMPRE en
    `None` (confirmado: el archivo entero, 234 puntos, nunca lograba leer
    n_epochs antes de este fix). No se conoce su significado (valores
    observados entre ~19 y ~25, mucho más grandes que un DOP típico --
    podría ser un dato de calidad temporal, pero no hay forma de
    confirmarlo con lo disponible) y NO se usa para nada todavía -- se
    consume igual para no perder la alineación de los campos que siguen.

    Después de ese cuarto campo (cuando está presente -- ver más abajo),
    el registro trae un contador corto (épocas promediadas -- verificado
    que coincide EXACTO con la columna "GDOP" de la base de datos
    POSTPLOT real para 228 de 229 puntos verificables de ar180118.dsc, la
    única excepción siendo una reocupación ambigua donde la comparación
    tomó la ocupación equivocada de las dos, no un error de fórmula) y
    dos marcas de tiempo GPS (duración de la ocupación entre ambas, en
    segundos -- verificado exacto contra la columna "Occupation Time"
    real para los mismos 229 puntos). Sobre esas dos marcas: NO son una
    hora real absoluta -- confirmado en la ronda de "Elapsed Time"
    probando ambos epochs candidatos documentados por GPSeismic (GPS
    desde 1980-01-06, y Unix desde 1970-01-01) contra un punto real de
    3001YC.dc con fecha de archivo conocida (Julian_Date_Local=2026229,
    17/ago/2026): ambos interpretan el valor como una fecha absurda (año
    2056 y 2046 respectivamente), muy lejos de la fecha real del
    archivo -- confirma que es un contador interno del receptor
    (probablemente relativo al inicio de la sesión/job, no a un epoch de
    calendario conocido), no convertible a una hora real de calendario
    con lo confirmado hasta ahora (por eso Survey_Time_Local/GMT y
    Serial_Time_GPS siguen sin poder completarse para Trimble .dc). Sí
    es útil, en cambio, para "Elapsed Time" (tiempo transcurrido desde
    el punto anterior, tal como lo define GPSeismic -- ver
    `quikview.chm`, "Station to Station Time"): al ser un contador
    monótono DENTRO de la misma sesión, la DIFERENCIA entre el primer
    epoch de dos puntos 'SO' consecutivos sí es una duración real y
    verificable aunque no se sepa a qué hora de calendario corresponde
    cada uno por separado -- ver `t_inicio_sesion` más abajo, usado por
    `parse_dc_text` para calcular `DCPoint.elapsed_seconds` después de
    parsear todo el archivo.

    El cuarto campo NO está presente en todos los archivos: el caso de
    referencia original de este registro (3001YC.dc, punto 14095304, con
    valores confirmados por el usuario) sólo trae 3 campos DOP antes del
    contador de épocas. Por eso se intenta primero con 3 campos (el caso
    ya confirmado) y sólo se agrega el cuarto si, sin él, el contador de
    épocas de 4 dígitos no aparece donde debería -- en vez de asumir un
    layout fijo por adelantado.
    """
    if not line.startswith("C6NM") or len(line) < 7:
        return None
    body = line[4:]
    if not body[0:_C6NM_SATS_WIDTH].isdigit():
        return None
    try:
        n_sats = int(body[0:_C6NM_SATS_WIDTH])
    except ValueError:
        return None
    rest0 = body[_C6NM_SATS_WIDTH + 1 :]  # +1 salta un carácter constante ('1' en todo el archivo analizado, de significado desconocido)

    fields = []
    rest = rest0
    for _ in range(3):  # PDOP, HDOP, VDOP
        found = _read_sigfig_field(rest, _C6NM_DOP_SIGFIGS)
        if found is None:
            return None
        val, consumed = found
        fields.append(val)
        rest = rest[consumed:]
    try:
        pdop, hdop, vdop = (float(v) for v in fields)
    except ValueError:
        return None

    # Si el contador de épocas no aparece justo acá, se prueba de nuevo
    # consumiendo un cuarto campo del mismo ancho (15 dígitos
    # significativos, ver el docstring) antes de buscarlo -- formato
    # visto en ar180118.dsc (receptor Trimble R6-2).
    if not re.match(r"\s*\d{4}\s*", rest):
        found4 = _read_sigfig_field(rest, _C6NM_DOP_SIGFIGS)
        if found4 is not None:
            _val4, consumed4 = found4
            rest_con_4to_campo = rest[consumed4:]
            if re.match(r"\s*\d{4}\s*", rest_con_4to_campo):
                rest = rest_con_4to_campo

    m = re.match(r"\s*(\d{4})\s*", rest)
    n_epochs = None
    occupation_seconds = None
    t_inicio_sesion = None
    if m:
        try:
            n_epochs = int(m.group(1))
        except ValueError:
            n_epochs = None
        rest2 = rest[m.end():]
        t1 = _read_sigfig_field(rest2, 19) or _read_sigfig_field(rest2, 20)
        if t1:
            t1_val, c1 = t1
            rest3 = rest2[c1:]
            t2 = _read_sigfig_field(rest3, 19) or _read_sigfig_field(rest3, 20)
            if t2:
                t2_val, _c2 = t2
                try:
                    occupation_seconds = float(t2_val) - float(t1_val)
                    # `t1_val` (primer epoch de ESTE punto) se guarda además
                    # tal cual -- ver `t_inicio_sesion` más abajo y la nota
                    # completa junto a `DCPoint.t_inicio_sesion` -- para
                    # poder calcular "Elapsed Time" (tiempo transcurrido
                    # desde el punto anterior, pedido explícito del
                    # usuario) como una DIFERENCIA entre dos puntos
                    # consecutivos, sin necesitar resolver a qué fecha/hora
                    # real de calendario corresponde `t1_val` en sí mismo
                    # (ver más abajo por qué eso no se pudo confirmar).
                    t_inicio_sesion = float(t1_val)
                except ValueError:
                    occupation_seconds = None
                    t_inicio_sesion = None

    # Chequeo de cordura: valores fuera de un rango físicamente posible
    # probablemente significan que este receptor/firmware arma el
    # registro 'C6NM' distinto al analizado -- mejor no usar el dato
    # que usar uno mal interpretado.
    if not (0 <= n_sats <= 60):
        return None
    if not (0 < pdop < 50 and 0 < hdop < 50 and 0 < vdop < 50):
        return None

    return {
        "n_sats": n_sats,
        "pdop": pdop,
        "hdop": hdop,
        "vdop": vdop,
        "n_epochs": n_epochs,
        "occupation_seconds": occupation_seconds,
        "t_inicio_sesion": t_inicio_sesion,
    }


# Cantidad de campos y ancho (en dígitos significativos) del registro
# '60NM' -- ver `_parse_60nm_precision`. Confirmado que consume la línea
# COMPLETA sin caracteres sobrantes (8 campos de 15 dígitos significativos
# cada uno) para 207/208 puntos 'SO' de 3001YC.dc y 230/230 de
# ar180118.dsc (los únicos '66SO'/'67SO' sin un '60NM' asociado son
# ocupaciones descartadas en campo que tampoco llegan a calcularse en
# GPSeismic -- ver `DCPoint.deleted`).
_60NM_NUM_FIELDS = 8
_60NM_FIELD_SIGFIGS = 15


def _parse_60nm_precision(line: str):
    """Interpreta un registro '60NM' (aparece, uno por uno, INMEDIATAMENTE
    después del 'C6NM' de cada punto '66SO'/'67SO' -- nunca después de un
    '66KI', igual que 'C6NM'). Hasta la v2.40.0 este registro se trataba
    como un código auxiliar conocido pero opaco (ver `KNOWN_AUX_CODES`),
    documentando -- de forma incorrecta, según se confirmó en esta ronda
    -- que la Precisión Hor./Vert. 95% y el CQ que muestra GPSeismic no
    podían obtenerse del '.dc'. El usuario insistió en que su flujo real
    de trabajo con GPSeismic (sólo el '.dc', sin ningún archivo adicional,
    sin conexión a internet) sí muestra esos datos ("de alguna forma debe
    estar o calcular GPSeismic solo con el archivo .dc"), lo que llevó a
    decodificar '60NM' byte a byte por primera vez.

    El registro trae EXACTAMENTE 8 campos numéricos pegados sin separador,
    cada uno de 15 dígitos significativos (mismo mecanismo de
    `_read_sigfig_field` ya usado para las DOP de 'C6NM') -- con una
    excepción encontrada en esta ronda: cuando un campo es NEGATIVO, su
    ancho real es de 14 dígitos significativos, no 15 (el signo "-" ocupa
    la posición de carácter que en un campo positivo sería un dígito más
    -- confirmado reconstruyendo la alineación de los campos siguientes,
    que si no quedaban corridos y dejaban de empezar por "0." como todos
    los demás). En la práctica sólo el campo de índice 3 (ver más abajo)
    se observó negativo (135 de 230 puntos de ar180118.dsc) -- el resto
    son magnitudes que nunca cambian de signo (desviaciones estándar,
    tiempo, el factor de Varianza Unitaria).

    Identificación de cada campo -- deducida por correlación numérica
    contra la base de datos POSTPLOT real (referencia: `previsualizacion3.mdb`
    para 3001YC.dc, 208 puntos; `previsualisacion2.mdb` para ar180118.dsc,
    234 puntos, receptor distinto R6-2, fecha distinta) y CONFIRMADA con
    precisión de redondeo (error absoluto máximo observado: 0.0005, del
    orden del ruido de redondeo float32 ya visto en otros campos) en los
    436 puntos combinados de ambos archivos:

        campo[0] = sigma Norte  (desviación estándar, metros)
        campo[1] = sigma Este   (desviación estándar, metros)
        campo[2] = sigma Altura (desviación estándar, metros)
        campo[3] = término cruzado/covarianza Norte-Este (magnitud muy
                   pequeña, puede ser negativo -- no se usa todavía)
        campo[4] = término cruzado/covarianza Norte-Altura (no se usa)
        campo[5] = término cruzado/covarianza Este-Altura (no se usa)
        campo[6] = sin identificar (valores ~20-45, no se usa)
        campo[7] = Varianza Unitaria ("Unit Variance" de GPSeismic --
                   confirmado EXACTO, error absoluto máximo 0.0004, contra
                   la columna real "Unit Variance" en 436 de 436 puntos;
                   varía por trabajo -- 1.0 en 3001YC.dc, ~0.6 en
                   ar180118.dsc -- por lo que NO es un valor por defecto
                   fijo como se creía antes de decodificar este registro)

    A partir de sigma Norte/Este/Altura, las fórmulas que reproducen
    "Hor 95% Precision"/"Ver 95% Precision" de GPSeismic (ver
    `DCPoint.hor_precision_95`/`ver_precision_95`) son:

        Hor 95% = 1.96 * sqrt(sigma_norte² + sigma_este²)   (DRMS al 95%,
                  el enfoque estándar para el error radial horizontal de
                  una solución GNSS -- ver quikview.chm, "95% Precision
                  Values": estadísticas de posición por mínimos cuadrados)
        Ver 95% = 1.96 * sigma_altura

    Ambas fórmulas, junto con CQ = sqrt(Hor95² + Ver95²) / 1.96 (ya
    confirmada en la ronda anterior), se verificaron contra el 100% de los
    puntos no descartados de AMBOS archivos de referencia (207/207 de
    3001YC.dc, 229/229 de ar180118.dsc -- 436 en total) con el mismo
    margen de error de redondeo, no sólo contra 1-3 puntos sueltos.

    Devuelve un dict con `sigma_n`/`sigma_e`/`sigma_h`/`unit_variance`, o
    `None` si la línea no matchea la forma esperada (algún campo no se
    pudo leer, sobran caracteres al final, o algún valor queda fuera de un
    rango físicamente posible) -- mejor dejar el dato en blanco que usar
    uno mal interpretado.
    """
    if not line.startswith("60NM"):
        return None
    rest = line[4:]
    valores = []
    for _ in range(_60NM_NUM_FIELDS):
        es_negativo = rest.startswith("-")
        ancho = _60NM_FIELD_SIGFIGS - 1 if es_negativo else _60NM_FIELD_SIGFIGS
        found = _read_sigfig_field(rest, ancho)
        if found is None:
            return None
        val, consumed = found
        try:
            valores.append(float(val))
        except ValueError:
            return None
        rest = rest[consumed:]
    if rest.strip() != "":
        # Sobran caracteres: este receptor/firmware arma el registro
        # '60NM' con un layout distinto al analizado (o el campo negativo
        # de más arriba desalineó la lectura) -- mejor no usar nada de
        # esta línea que usar valores mal alineados.
        return None

    sigma_n, sigma_e, sigma_h = valores[0], valores[1], valores[2]
    unit_variance = valores[7]

    # Chequeo de cordura: una desviación estándar o una Varianza Unitaria
    # fuera de un rango físicamente posible para un levantamiento RTK/GPS
    # probablemente significa un layout distinto.
    if not (0.0 <= sigma_n < 10.0 and 0.0 <= sigma_e < 10.0 and 0.0 <= sigma_h < 10.0):
        return None
    if not (0.0 <= unit_variance < 100.0):
        return None

    return {
        "sigma_n": sigma_n,
        "sigma_e": sigma_e,
        "sigma_h": sigma_h,
        "unit_variance": unit_variance,
    }


def _leer_precision_60nm(lines: List[str], indice_c6nm: int):
    """Busca, en `lines[indice_c6nm + 1]`, el registro '60NM' que siempre
    viene INMEDIATAMENTE después del 'C6NM' ubicado en `indice_c6nm` (ver
    `_parse_60nm_precision`) y, si lo encuentra, calcula a partir de sus
    desviaciones estándar Norte/Este/Altura las 3 columnas reales de
    GPSeismic que se derivan de ellas: "Hor 95% Precision", "Ver 95%
    Precision" (fórmula DRMS al 95%, ver el docstring de
    `_parse_60nm_precision`) y "CQ" (ya confirmada en la ronda anterior:
    `sqrt(Hor95² + Ver95²) / 1.96`, matemáticamente equivalente a
    `sqrt(sigma_n² + sigma_e² + sigma_h²)`). Devuelve `None` si no hay un
    '60NM' válido en esa posición (KI, is_base, o una ocupación
    descartada en campo -- se prefiere blanco a inventar un valor)."""
    indice_60nm = indice_c6nm + 1
    if indice_60nm >= len(lines):
        return None
    linea_60nm = lines[indice_60nm].rstrip("\r\n")
    precision = _parse_60nm_precision(linea_60nm)
    if precision is None:
        return None
    sigma_n = precision["sigma_n"]
    sigma_e = precision["sigma_e"]
    sigma_h = precision["sigma_h"]
    hor95 = 1.96 * math.sqrt(sigma_n ** 2 + sigma_e ** 2)
    ver95 = 1.96 * sigma_h
    cq = math.sqrt(hor95 ** 2 + ver95 ** 2) / 1.96
    return {
        "hor_precision_95": hor95,
        "ver_precision_95": ver95,
        "cq": cq,
        "unit_variance": precision["unit_variance"],
    }


# Cantidad de dígitos significativos (parte entera + decimal) del valor
# numérico que trae un registro '57KI' -- deducida contra las 3
# apariciones reales en 3001YC.dc (líneas 10, 13610 y 13961) y la
# aparición en DP050226.dc (línea 10): en las 4, el campo así leído
# consume EXACTAMENTE el resto de la línea sin caracteres sobrantes
# (mismo criterio de ancho fijo ya usado en `_C6NM_DOP_SIGFIGS`), y los
# valores resultantes son físicamente plausibles como altura de antena/
# jalón (≈0.00 m en la primera aparición, al principio mismo del
# archivo; ≈1.70 m en las dos apariciones siguientes, cada una justo
# antes de que empiece una nueva ocupación/sesión de campo -- reconocida
# por los códigos vecinos '56KI'/'82KI'/'71KI'/'13TS' -- igual que un
# colector de datos pide confirmar la altura de antena al iniciar cada
# sesión). A diferencia de 'C6NM' (verificado con un valor de referencia
# YA CONOCIDO de antemano, ver `_C6NM_DOP_SIGFIGS`), aquí no se cuenta
# con un valor confirmado por el usuario -- ver la nota en `DCPoint.antenna_height`.
_KI_ANTENNA_HEIGHT_SIGFIGS = 16


def _parse_57ki_antenna_height(line: str) -> Optional[float]:
    """Interpreta un registro '57KI' (altura de antena/jalón vigente a
    partir de este punto del archivo, ver `KNOWN_AUX_CODES` y
    `DCPoint.antenna_height`). Devuelve el valor en metros, o `None` si
    la línea no matchea la forma esperada -- mejor no usar el dato que
    usar uno mal interpretado."""
    if not line.startswith("57KI"):
        return None
    body = line[4:]
    found = _read_sigfig_field(body, _KI_ANTENNA_HEIGHT_SIGFIGS)
    if found is None:
        return None
    val_text, consumed = found
    if consumed != len(body):
        # Sobran caracteres: este receptor/firmware arma el registro
        # '57KI' con un layout distinto al analizado.
        return None
    try:
        val = float(val_text)
    except ValueError:
        return None
    # Chequeo de cordura: una altura de antena/jalón fuera de este rango
    # físicamente posible probablemente significa un layout distinto.
    if not (0.0 <= val <= 10.0):
        return None
    # Redondeo: el valor crudo trae ruido de serialización de punto
    # flotante propio del receptor (ej. "0.000000000000001" en vez de
    # "0.0" exacto -- mismo fenómeno ya documentado para lat/lon/altura
    # de un punto, ver `_NUM_FIELD_WIDTH`) -- se redondea a 6 decimales
    # (sub-milimétrico, no pierde ninguna precisión real) para no
    # arrastrar ese ruido hasta la base de datos si el usuario no llega
    # a editar la celda en la previsualización.
    return round(val, 6)


@dataclass
class DCPoint:
    name: str
    lat: float
    lon: float
    height: float
    record_type: str  # 'KI', 'SO' o 'BASE' (ver `BASE_CODES`); un punto
    # parseado inicialmente como 'KI' puede "ascender" a 'SO' después, si
    # un '67SO' posterior en el archivo trae datos de calidad reales para
    # el mismo nombre (ver el caso especial de '67SO' en `parse_dc_text`)
    line_no: int
    raw: str
    # True si este punto es una ocupación de base RTK física ('66SI'/
    # '66FD', ver `BASE_CODES`) -- mismo campo, mismo significado, que ya
    # existe en `HiTargetPoint`/`ChcnavPoint`. Un 'KI'/'SO' normal nunca
    # lo tiene en True.
    is_base: bool = False
    # Datos de calidad, sólo disponibles para puntos 'SO' cuando el
    # archivo trae, en la línea siguiente, un registro 'C6NM' asociado
    # (ver `_parse_c6nm_quality` y la nota en `parse_dc_text`). Un
    # 'KI' de este formato de .dc NUNCA los trae -- quedan en None.
    n_sats: Optional[int] = None
    pdop: Optional[float] = None
    hdop: Optional[float] = None
    vdop: Optional[float] = None
    n_epochs: Optional[int] = None
    occupation_seconds: Optional[float] = None
    # Primer epoch de ESTE punto, tal cual lo trae 'C6NM' -- ver la nota
    # completa junto a `_parse_c6nm_quality` sobre por qué NO es una hora
    # real de calendario (es un contador interno del receptor, probable-
    # mente relativo al inicio de la sesión). Sólo se usa como paso
    # intermedio, dentro de `parse_dc_text`, para calcular
    # `elapsed_seconds` una vez que se conocen todos los puntos del
    # archivo en su orden real de aparición -- no se expone en la
    # previsualización ni se sube a la base de datos.
    t_inicio_sesion: Optional[float] = None
    # "Elapsed Time" de GPSeismic: tiempo transcurrido desde el primer
    # epoch del punto 'SO' anterior (en orden de aparición en el
    # archivo) hasta el primer epoch de ESTE punto -- pedido explícito
    # del usuario, calculado por `parse_dc_text` después de parsear todo
    # el archivo. `None` para un punto sin dato de calidad propio (KI,
    # is_base) o para el primer punto 'SO' del archivo (no hay uno
    # anterior con qué compararlo). Un valor negativo (el contador
    # "retrocedió", señal de un límite de sesión/job que no se puede
    # interpretar) tampoco se completa -- se prefiere blanco a un dato
    # sin sentido físico.
    elapsed_seconds: Optional[float] = None
    # Precisión Hor./Vert. 95% y CQ (columnas "Hor 95% Precision"/
    # "Ver 95% Precision"/"CQ" de POSTPLOT) -- desde esta ronda, calculadas
    # a partir del registro '60NM' que sigue al 'C6NM' de cada punto 'SO'
    # (ver `_parse_60nm_precision`, que documenta la verificación completa
    # contra 436 puntos reales de 2 archivos independientes). `None` para
    # un punto sin '60NM' asociado (KI, is_base, o una ocupación
    # descartada en campo sin datos de calidad -- ver `DCPoint.deleted`).
    hor_precision_95: Optional[float] = None
    ver_precision_95: Optional[float] = None
    cq: Optional[float] = None
    # Varianza Unitaria ("Unit Variance" de POSTPLOT) -- también viene del
    # '60NM' (ver `_parse_60nm_precision`); varía por trabajo (no es un
    # valor por defecto fijo, confirmado contra los 2 archivos de
    # referencia: 1.0 en 3001YC.dc, ~0.6 en ar180118.dsc).
    unit_variance: Optional[float] = None
    # "Hora de levant. (GMT/Local)" y "Hora serial (GPS)" -- ver el
    # docstring completo junto a `_GMT_WEEK_CALIBRATION` y
    # `_calibrar_horas_gps` (llamada al final de `parse_dc_text`) para la
    # fórmula y la verificación. `None` para los tres cuando la semana de
    # trabajo del archivo (según su propio '13TS') todavía no está
    # calibrada, cuando el punto no tiene `t_inicio_sesion`/
    # `occupation_seconds` (KI, is_base, sin 'C6NM'), o cuando el archivo
    # no trae ningún '13TS' -- mismo criterio de "exacto o en blanco" que
    # el resto de estos campos.
    survey_time_gmt: Optional[str] = None
    survey_time_local: Optional[str] = None
    serial_time_gps: Optional[int] = None
    # Altura de antena/jalón VIGENTE en el momento de levantar este punto
    # -- desde la v2.22.0, tomada del último registro '57KI' visto antes
    # de este punto en el archivo (ver `_parse_57ki_antenna_height` y la
    # nota en `parse_dc_text`; None si el archivo no trae ningún '57KI'
    # antes de este punto, o si su valor no se pudo interpretar). A
    # diferencia de los campos de calidad de arriba, esta interpretación
    # se basa en ingeniería inversa por patrón (ancho de campo exacto +
    # ubicación siempre justo antes de que empiece una ocupación/sesión
    # nueva + valores físicamente plausibles) y NO en un valor de
    # referencia conocido de antemano confirmado por el usuario -- por
    # eso en la previsualización de importación se trata como un valor
    # detectado automáticamente, editable y a revisar antes de subir.
    antenna_height: Optional[float] = None
    # Descriptor de GPSeismic (columna "Descriptor" de POSTPLOT, ej. "60",
    # "57") -- descubierto y verificado en esta ronda: son los 2
    # caracteres que vienen INMEDIATAMENTE después del bloque de 3
    # coordenadas (48 caracteres) de un registro '67SO'/'67TP', es decir
    # `line[4:][8+8+48 : 8+8+48+2]` sobre ESE registro (nunca sobre el
    # '66KI' original -- para 229 puntos verificados, el '66KI' inicial a
    # veces trae un descriptor DISTINTO, ej. PF10 trae "50" en su '66KI'
    # pero "57" en su '67SO', y "57" es el que coincide con la base de
    # datos POSTPLOT real) -- coincide EXACTO (234/234, incluyendo el
    # prefijo "D" que GPSeismic también le agrega cuando el punto queda
    # descartado) contra la base de datos POSTPLOT real de ar180118.dsc.
    # `None` si el punto nunca llegó a promoverse (KI puro, sin datos de
    # calidad -- se descarta de la previsualización de todos modos).
    descriptor: Optional[str] = None
    # Base RTK física VIGENTE al momento de levantar este punto (nombre +
    # distancia horizontal en metros), o `None` si ninguna ocupación de
    # base ('66SI'/'66FD', ver `BASE_CODES`) se vio todavía antes de este
    # punto en el archivo. A partir de la ronda de soporte a MÚLTIPLES
    # bases por archivo: se asigna por ORDEN DE APARICIÓN (la ocupación de
    # base más reciente vista antes que este punto, "vigente hasta que
    # otra la cambie"), exactamente el mismo mecanismo ya verificado para
    # `ChcnavPoint.base_station_name`/`base_baseline_m` con el registro
    # 'BP' de CHCNav (v2.24.0) -- ahí también los registros son
    # secuenciales y no hay ningún campo por punto que diga qué base usó,
    # así que se asume que la ocupación de base vigente al recorrer el
    # archivo en orden es la que realmente se usó, hasta que otra la
    # reemplace. Un punto is_base=True nunca tiene estos dos campos (la
    # base no está "asociada a sí misma"). Sin verificar todavía contra un
    # archivo real con más de una base física distinta (el único
    # disponible, ar180118.dsc, sólo tiene una, "SA01", reocupada 5
    # veces) -- ver la nota en `parse_dc_text`.
    base_station_name: Optional[str] = None
    base_baseline_m: Optional[float] = None
    # Comentario de operador asociado a este punto, tomado del texto
    # COMPLETO de un registro '13NM' posterior en el archivo, siempre
    # adjunto al punto no-base parseado más recientemente (`current_point`
    # en `parse_dc_text`) -- NUNCA por coincidencia de nombre (ver la nota
    # completa en el caso especial de '13NM' en `parse_dc_text`: se
    # descartó esa lectura inicial -- un nombre de 8 caracteres pegado al
    # texto -- al verificarla contra la base de datos POSTPLOT real, que
    # conserva el texto completo sin separar ningún nombre, incluso
    # cuando ese "nombre" es en realidad un typo del operador que señala
    # a un punto DISTINTO al vigente -- confirmado, además, por el
    # archivo de notas de operador ar180118.NOT, que documenta ese typo
    # como "Prior Point ID"). Si el mismo punto recibe más de un '13NM',
    # los textos se concatenan. `None` si no tiene ningún comentario.
    comment: Optional[str] = None
    # True si el comentario ('13NM', ver `comment` arriba) empieza con la
    # palabra "Eliminado" -- confirmado como el marcador real de "punto
    # borrado en campo" contra la base de datos POSTPLOT de referencia
    # (los puntos que ahí aparecen con el nombre prefijado por "D" tienen,
    # en su columna Comment, un texto que empieza exactamente así) y
    # contra 3001YC.dc/DP050226.dc (que traen la misma palabra en sus
    # propios '13NM').
    deleted: bool = False
    # True si este punto tuvo una segunda (o posterior) aparición como
    # '67SO' con el mismo nombre, ignorada porque la primera ya se había
    # asociado (ver el caso especial de '67SO' en `parse_dc_text` -- único
    # caso real visto hasta ahora: "52102279" en ar180118.dsc). La base de
    # datos POSTPLOT de referencia marca este mismo punto con un prefijo
    # "?" en su nombre, señal de una reocupación ambigua para el propio
    # GPSeismic.
    ambiguous_reoccupation: bool = False
    # True cuando `height` NO es una lectura geodésica propia de este
    # punto -- viene de la promoción '67SO'/'67TP' (ver el caso especial
    # en `parse_dc_text`), que actualiza calidad/descriptor/altura de
    # antena pero NUNCA la altura, porque sus propias 3 coordenadas son
    # un vector local (ΔNorte/ΔEste/ΔAltura) respecto a la base, no
    # lat/lon/altura -- así que `height` se queda con el valor crudo del
    # '66KI' original (típicamente 0.0, un simple marcador cinemático).
    # Descubierto a pedido explícito del usuario, que reportó que las
    # coordenadas planas/elevación/altura de antena de la previsualización
    # de `0502YC.dsc` no coincidían con su propia base de datos POSTPLOT
    # real de GPSeismic: para un punto SIN esta bandera (la inmensa
    # mayoría, cualquier archivo con receptores como el R12i que traen su
    # propia altura en el registro '66SO'), `height` SÍ es la altura
    # elipsoidal propia del punto (a nivel de la ANTENA, no del punto en
    # tierra) y hace falta restarle la altura de antena corregida (ver
    # `RECEIVER_ARP_OFFSET_M`) para reproducir la "WGS84 Height" real de
    # GPSeismic -- verificado EXACTO, sub-milimétrico, en 405 puntos
    # combinados de 2 archivos reales (`0502YC.dc`/`3001YC.dc`). Para un
    # punto CON esta bandera (el único caso real conocido hasta ahora:
    # los puntos promovidos por '67SO'/'67TP' de `ar180118.dsc`, receptor
    # R6-2), la altura real de GPSeismic sigue sin poder derivarse del
    # propio archivo -- por eso NO se le aplica ninguna corrección
    # (mismo comportamiento que antes de este hallazgo, no se inventa un
    # valor): queda como una investigación pendiente aparte.
    height_is_placeholder: bool = False

    def track_bin(self, line_digits: int = 4) -> "tuple[Optional[str], Optional[str]]":
        """Intento heurístico de separar el nombre del punto en
        Línea/Track (los primeros `line_digits` dígitos) y
        Estaca/Bin (el resto). Sólo funciona si el nombre es numérico.
        Se deja como ayuda opcional: cada empresa/levantamiento tiene su
        propia convención de nomenclatura, así que el usuario puede
        ajustar `line_digits` o ignorar el resultado.
        """
        n = self.name.strip()
        if not n.isdigit() or len(n) <= line_digits:
            return None, None
        return n[:line_digits], n[line_digits:]


@dataclass
class DCFile:
    path: str
    job_name: Optional[str] = None
    instrument: Optional[str] = None
    date_text: Optional[str] = None
    # Tipo y número de serie del receptor GNSS, tomados del registro
    # 'E2NM' (ver `_extraer_e2nm`) -- primero que aparece en el archivo,
    # mismo criterio de "primero que aparece" ya usado para `job_name`/
    # `instrument`/`date_text`. Distinto de `instrument`: ese campo viene
    # de '00NM' y en realidad es el modelo del COLECTOR/controlador de
    # campo (ej. "SC V10-70"), no del receptor GNSS en sí (verificado
    # contra la base de datos POSTPLOT de referencia: su "Receiver Type"
    # es "R6-2", que no aparece en ningún '00NM' del archivo, pero sí
    # coincide exactamente con el 'E2NM' de ese mismo archivo).
    receiver_type: Optional[str] = None
    receiver_sn: Optional[str] = None
    # Offset ARP↔L1 (metros) que el PROPIO receptor reporta en su
    # registro 'E2NM' (último campo de ancho `_NUM_FIELD_WIDTH`, ver
    # `_extract_e2nm`) -- descubierto a pedido explícito del usuario, que
    # preguntó cómo hace GPSeismic v2006 para corregir la altura de
    # antena "sin tener que recurrir a ver el offset según el modelo".
    # Confirmado EXACTO (o casi, con redondeo) contra los 3 modelos ya
    # verificados a mano en `RECEIVER_ARP_OFFSET_M`: R6-2 reporta
    # 0.06490 (tabla: 0.0649), R12i reporta 0.17932 (tabla: 0.1793),
    # R780-2 reporta 0.12488 (tabla: 0.125, esa sí sólo una aproximación
    # de un único archivo). Es decir: el firmware del receptor escribe
    # su propio offset de fábrica en cada archivo .dc/.dsc, y así es como
    # GPSeismic lo resuelve sin necesitar una tabla externa por modelo.
    # `None` si el archivo no tiene 'E2NM' o si ese campo no es un número
    # bien formado -- ver `resolve_receiver_arp_offset`, que usa este
    # valor con prioridad sobre `RECEIVER_ARP_OFFSET_M`.
    receiver_arp_offset_from_file: Optional[float] = None
    points: List[DCPoint] = field(default_factory=list)
    header_lines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def n_points(self) -> int:
        return len(self.points)

    def points_by_type(self, record_type: str) -> List[DCPoint]:
        return [p for p in self.points if p.record_type == record_type]

    def duplicated_names(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.points:
            counts[p.name] = counts.get(p.name, 0) + 1
        return {k: v for k, v in counts.items() if v > 1}

    def unique_base_names(self) -> List[str]:
        """Nombres distintos de ocupación de base RTK física (puntos con
        `is_base=True`, ver `BASE_CODES`) detectados en este archivo, en
        el orden en que aparecen, sin duplicados -- normalmente una sola
        entrada, aunque la misma base se haya reocupado ('66FD') varias
        veces a lo largo del trabajo.

        A diferencia de Hi-Target/CHCNav (que traen, por punto, una
        referencia explícita a qué base usó -- columnas "Base B"/"Base L"
        o el orden del registro 'BP'), Trimble '.dc' no tiene ningún campo
        así: no hay forma de saber, dentro del propio formato, qué base
        usó cada punto rover. Por eso la asociación real, punto por punto,
        se hace por ORDEN DE APARICIÓN en `parse_dc_text` (ver
        `DCPoint.base_station_name`) -- este método sólo sirve para
        listar los nombres distintos vistos (p.ej. para armar la tabla de
        "Corrección de base RTK"), no para decidir la asociación."""
        vistos: List[str] = []
        for p in self.points:
            if p.is_base and p.name not in vistos:
                vistos.append(p.name)
        return vistos


def _extract_job_name(line: str) -> Optional[str]:
    # '10NMDP050226        121221' -> 'DP050226'
    body = line[4:]
    m = re.match(r"\s*(\S+)", body)
    return m.group(1) if m else None


def _extract_instrument(line: str) -> Optional[str]:
    # '00NMSC V10-70       102105-Jan-26 12:20 111111' -> 'SC V10-70'
    body = line[4:]
    # el modelo suele terminar antes de una racha larga de espacios
    m = re.match(r"\s*(.+?)\s{2,}", body)
    if m:
        return m.group(1).strip()
    return body.strip() or None


def _extract_e2nm(line: str):
    """Interpreta un registro 'E2NM' (tipo y número de serie del receptor
    GNSS, y su offset ARP↔L1 de fábrica -- ver `DCFile.receiver_type`/
    `receiver_sn`/`receiver_arp_offset_from_file`). Formato de ANCHO FIJO
    confirmado contra 3 archivos reales de referencia, uno por cada
    modelo ya conocido (ar180118.dsc=R6-2, 0502YC.dc/3001YC.dc=R12i,
    ar22-08-26.dsc=R780-2): 'E2NM' + 8 caracteres de modelo de receptor
    (ej. "R6-2    ") + 8 caracteres de número de serie (ej. "49131686")
    + un bloque de 46 caracteres sin interpretar todavía (incluye el
    nombre de la antena, ej. "R6-2 Internal") + tres campos numéricos de
    ancho `_NUM_FIELD_WIDTH` (igual que el resto del formato), de los
    cuales los dos primeros son siempre 0.0 en los archivos vistos hasta
    ahora y el ÚLTIMO es el offset ARP↔L1 que el propio receptor reporta
    -- ver la nota completa en `DCFile.receiver_arp_offset_from_file`.
    Devuelve `(tipo, serie, offset_arp)`, con `offset_arp=None` si la
    línea es demasiado corta para tener ese último campo o si no es un
    número bien formado (nunca se adivina un valor)."""
    body = line[4:]
    if len(body) < 16:
        return None, None, None
    tipo = body[0:8].strip() or None
    serie = body[8:16].strip() or None
    offset_arp: Optional[float] = None
    if len(body) >= 16 + _NUM_FIELD_WIDTH:
        campo = body[-_NUM_FIELD_WIDTH:]
        if _FLOAT_FULL_RE.match(campo):
            try:
                offset_arp = float(campo)
            except ValueError:
                offset_arp = None
    return tipo, serie, offset_arp


def _extract_date_text(line: str) -> Optional[str]:
    # '13TSTime Date 02/05/2026 Time 05:30:55' -> '02/05/2026 05:30:55'
    m = re.search(r"Date\s+(\d{1,2}/\d{1,2}/\d{2,4}).*?Time\s+(\d{1,2}:\d{2}:\d{2})", line)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None


def _find_coord_block(body: str, w: int = _NUM_FIELD_WIDTH):
    """Busca, dentro de `body` (la línea sin el código de 4 caracteres),
    la primera posición en la que tres campos consecutivos de ancho `w`
    son todos numéricos (lat, lon, altura). Devuelve
    (pos_inicio, lat, lon, height) o None si no se encuentra.
    """
    limit = len(body) - 3 * w
    for pos in range(0, limit + 1):
        c1 = body[pos : pos + w]
        c2 = body[pos + w : pos + 2 * w]
        c3 = body[pos + 2 * w : pos + 3 * w]
        if _FLOAT_FULL_RE.match(c1) and _FLOAT_FULL_RE.match(c2) and _FLOAT_FULL_RE.match(c3):
            try:
                return pos, float(c1), float(c2), float(c3)
            except ValueError:
                continue
    return None


# Ancho fijo (en caracteres) de los dos campos que preceden siempre al
# bloque de coordenadas de un registro de punto: un primer campo de 8
# caracteres sin usar (siempre en blanco en los 3 archivos .dc reales
# analizados hasta ahora, ~27500 registros de punto en total) y, a
# continuación, el nombre del punto en un campo de otros 8 caracteres,
# alineado a la izquierda y rellenado con espacios (ej. "PF10    ") o, si
# el nombre ya ocupa las 8 posiciones (nombres numéricos de 8 dígitos, el
# caso más común), sin ningún espacio de separación antes del bloque de
# coordenadas que sigue inmediatamente después.
_NAME_FIELD_OFFSET = 8
_NAME_FIELD_WIDTH = 8


def _split_name_and_coords(body: str):
    """Separa `body` (la línea sin el código de 4 caracteres) en
    `(nombre, lat, lon, height)` usando el layout de ANCHO FIJO
    confirmado, campo por campo, contra 3 archivos .dc reales (27563
    registros de punto en total, cero discrepancias contra el método
    anterior): 8 caracteres sin usar + 8 de nombre + el bloque de
    coordenadas arrancando EXACTAMENTE ahí (no en cualquier posición más
    adelante -- a diferencia de `_find_coord_block` en modo de búsqueda
    libre). Devuelve `None` si `body` es demasiado corto, el nombre queda
    vacío, o no hay un bloque de coordenadas válido arrancando en esa
    posición.

    Se prefiere este layout de ancho fijo por sobre "el nombre es todo lo
    que hay antes de la primera coordenada válida en cualquier posición"
    (el método usado hasta la v2.28.0, que sigue disponible como red de
    seguridad en `parse_line`): ese método de búsqueda libre falla para
    un nombre puramente numérico que ocupa exactamente las 8 posiciones
    sin ningún espacio de separador antes del signo/dígito de la
    coordenada que sigue -- confirmado con un archivo real (ar180118.dsc,
    ronda de soporte a puntos '67SO' con datos de calidad reales) donde
    22 de sus 230 registros '67SO' con nombre de 8 dígitos quedaban con
    el nombre vacío por este motivo, y por lo tanto sin poder asociarse
    con su punto '66KI' correspondiente."""
    if len(body) < _NAME_FIELD_OFFSET + _NAME_FIELD_WIDTH:
        return None
    name = body[_NAME_FIELD_OFFSET : _NAME_FIELD_OFFSET + _NAME_FIELD_WIDTH].strip()
    if not name:
        return None
    rest = body[_NAME_FIELD_OFFSET + _NAME_FIELD_WIDTH :]
    found = _find_coord_block(rest)
    if found is None or found[0] != 0:
        return None
    _, lat, lon, height = found
    return name, lat, lon, height


# Posición fija (dentro de `line[4:]`, la línea sin el código de 4
# caracteres) de los 2 caracteres del Descriptor de GPSeismic dentro de
# un registro '67SO'/'67TP': justo después de los 8+8 caracteres de
# relleno+nombre y las 3 coordenadas de 16 caracteres cada una (48) --
# ver `DCPoint.descriptor`. Verificado exacto (234/234, incluyendo el
# prefijo "D" para puntos descartados) contra la base de datos POSTPLOT
# real de ar180118.dsc.
_DESCRIPTOR_OFFSET = _NAME_FIELD_OFFSET + _NAME_FIELD_WIDTH + 3 * _NUM_FIELD_WIDTH  # 8+8+48 = 64
_DESCRIPTOR_WIDTH = 2


def _extract_descriptor(line: str) -> Optional[str]:
    """Lee el Descriptor de GPSeismic (2 caracteres) de un registro
    '67SO'/'67TP' ya identificado como tal -- ver `_DESCRIPTOR_OFFSET`.
    Devuelve `None` si la línea es demasiado corta."""
    body = line[4:]
    if len(body) < _DESCRIPTOR_OFFSET + _DESCRIPTOR_WIDTH:
        return None
    desc = body[_DESCRIPTOR_OFFSET : _DESCRIPTOR_OFFSET + _DESCRIPTOR_WIDTH]
    return desc if desc.strip() else None


# Offset vertical fijo (metros) entre la altura de antena/jalón que trae
# un '57KI' (medida al punto de referencia del jalón/trípode) y la
# columna "HI" real de GPSeismic (que usa el punto de referencia de
# antena -- ARP -- del receptor GNSS) -- verificado EXACTO (234/234,
# milímetro a milímetro) contra la base de datos POSTPLOT real de
# ar180118.dsc para un receptor Trimble R6-2 (`DCFile.receiver_type`,
# tomado de 'E2NM'): "HI" = '57KI' vigente al momento de la promoción
# '67SO'/'67TP' (ver la nota en `parse_dc_text`) + 0.0649. Es un valor
# propio del MODELO de receptor (offset ARP↔L1 de fábrica), no del
# trabajo -- por eso se guarda por tipo de receptor y NO se aplica
# ningún offset (se usa la altura de jalón cruda, sin corregir) para un
# receptor no confirmado todavía en esta tabla, en vez de adivinar un
# valor -- ver `receiver_arp_offset_known` para distinguir ese caso del
# de un offset legítimamente nulo, y avisarle al usuario en vez de
# fallar en silencio (desde la v2.51.0, ver `gnsseismic_windows.py`).
# "R12i" agregado a pedido explícito del usuario (revisó
# `0502YC.dsc` contra su propia base de datos POSTPLOT real de GPSeismic
# y encontró que "HI" no coincidía): 0.1793, verificado EXACTO contra
# DOS archivos reales independientes de ese receptor (0502YC.dc, 198/198
# puntos; 3001YC.dc, 207/207 puntos -- 405 puntos combinados, la
# constante "HI_real - HI_cruda" da EXACTAMENTE 0.1793 en el 100% de
# ellos). Este mismo hallazgo también reveló y corrigió un bug más
# grande, ver `height_is_placeholder` en `DCPoint`.
# "R780-2" agregado en la v2.51.0, también a pedido explícito del
# usuario (`ar22-08-26.dsc`, "no me aparece la altura real de 1.875, me
# aparece es 1.75"): 0.125, a partir de ese único archivo real (251/251
# puntos, todos con la misma altura de antena cruda 1.75 m) comparado
# contra el valor que el usuario reportó como real -- a diferencia de
# R6-2/R12i, todavía NO se verificó contra una base de datos POSTPLOT
# completa de GPSeismic para este modelo, así que si un segundo archivo
# real de un R780-2 diera un HI distinto a 1.875 con esta misma
# corrección, habría que revisarlo.
RECEIVER_ARP_OFFSET_M = {
    "R6-2": 0.0649,
    "R12i": 0.1793,
    "R780-2": 0.125,
}


def receiver_arp_offset_m(receiver_type: Optional[str]) -> float:
    """Devuelve el offset ARP↔L1 conocido para `receiver_type` (ver
    `RECEIVER_ARP_OFFSET_M`), o 0.0 si el modelo no está en la tabla."""
    if not receiver_type:
        return 0.0
    return RECEIVER_ARP_OFFSET_M.get(receiver_type.strip(), 0.0)


def receiver_arp_offset_known(receiver_type: Optional[str]) -> bool:
    """True si `receiver_type` tiene un offset ARP↔L1 confirmado en
    `RECEIVER_ARP_OFFSET_M`. Permite distinguir "este modelo no corrige
    nada porque su offset es 0.0" (no existe ningún caso así todavía) de
    "este modelo todavía no está en la tabla, así que no se corrige
    nada" -- el segundo caso es el que se le avisa al usuario en la
    previsualización en vez de dejarlo pasar en silencio (ver
    `gnsseismic_windows.py`, `previsualizar_dc`)."""
    if not receiver_type:
        return False
    return receiver_type.strip() in RECEIVER_ARP_OFFSET_M


# Cota de sanidad para `receiver_arp_offset_from_file`: un offset ARP↔L1
# de fábrica real siempre es un valor chico (unos pocos centímetros a
# ~20cm en los 3 modelos verificados). Si algún archivo trajera, en esa
# misma posición, un número fuera de este rango -- por un registro
# 'E2NM' con un layout distinto al ya confirmado, por ejemplo --, se
# prefiere no usarlo y caer a la tabla en vez de aplicar una corrección
# disparatada.
_ARP_OFFSET_FROM_FILE_MAX_M = 1.0


def resolve_receiver_arp_offset(dc: "DCFile") -> float:
    """Devuelve el offset ARP↔L1 a aplicar para corregir la altura de
    antena de los puntos de `dc`. Desde la v2.52.0 se prioriza
    `dc.receiver_arp_offset_from_file` -- el valor que el propio
    receptor reporta en su registro 'E2NM' -- por sobre la tabla
    hardcodeada `RECEIVER_ARP_OFFSET_M`: es más preciso (esa tabla se
    armó a mano comparando contra GPSeismic, con algo de redondeo) y,
    sobre todo, funciona para CUALQUIER modelo Trimble aunque todavía no
    esté en la tabla -- este es, en definitiva, el mecanismo que permite
    a GPSeismic resolver la altura de antena real sin necesitar una
    tabla externa por modelo (investigado a pedido explícito del
    usuario). Si el archivo no trae ese campo, o el valor no pasa la
    cota de sanidad (`_ARP_OFFSET_FROM_FILE_MAX_M`), se cae a
    `receiver_arp_offset_m(dc.receiver_type)` como respaldo."""
    offset = dc.receiver_arp_offset_from_file
    if offset is not None and 0.0 <= offset < _ARP_OFFSET_FROM_FILE_MAX_M:
        return offset
    return receiver_arp_offset_m(dc.receiver_type)


def receiver_arp_offset_known_for_file(dc: "DCFile") -> bool:
    """True si hay un offset ARP↔L1 confiable para `dc` -- ya sea leído
    directamente del archivo (`dc.receiver_arp_offset_from_file`, dentro
    de la cota de sanidad) o confirmado de antemano en
    `RECEIVER_ARP_OFFSET_M`. Equivalente, para un `DCFile` completo, de
    lo que `receiver_arp_offset_known` resuelve a partir de sólo el tipo
    de receptor -- ver `resolve_receiver_arp_offset`."""
    offset = dc.receiver_arp_offset_from_file
    if offset is not None and 0.0 <= offset < _ARP_OFFSET_FROM_FILE_MAX_M:
        return True
    return receiver_arp_offset_known(dc.receiver_type)


def parse_line(line: str, line_no: int) -> Optional[DCPoint]:
    """Intenta interpretar una línea como un registro de punto.
    Devuelve None si la línea no es un registro de punto reconocido.
    """
    if len(line) < 5:
        return None
    code = line[:4]
    suffix = code[2:4]
    is_base = code in BASE_CODES
    if not is_base and suffix not in COORD_SUFFIXES:
        return None

    body = line[4:]
    resultado = _split_name_and_coords(body)
    if resultado is not None:
        name, lat, lon, height = resultado
    else:
        # Red de seguridad (nunca disparada contra los 3 archivos reales
        # analizados hasta ahora): si el layout de ancho fijo de arriba
        # no aplicara en algún archivo futuro, se cae al método anterior
        # a la v2.29.0 -- buscar el nombre como "todo lo que hay antes de
        # la primera coordenada válida", en cualquier posición.
        found = _find_coord_block(body)
        if found is None:
            return None
        pos, lat, lon, height = found
        name = body[:pos].strip()
        if not name:
            return None

    # Sanity check: coordenadas geográficas válidas. Si no lo parecen,
    # probablemente el registro no era realmente un punto (evita falsos
    # positivos en registros con formato parecido).
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    record_type = "BASE" if is_base else suffix  # 'BASE', 'KI' o 'SO'
    return DCPoint(
        name=name,
        lat=lat,
        lon=lon,
        height=height,
        record_type=record_type,
        line_no=line_no,
        raw=line,
        is_base=is_base,
    )


def parse_dc_text(text: str, path: str = "") -> DCFile:
    dc = DCFile(path=path)
    lines = text.splitlines()

    # Altura de antena/jalón vigente en el punto actual de la lectura del
    # archivo -- se actualiza cada vez que aparece un registro '57KI' y
    # se le asigna a cada punto ('66KI'/'66SO') que se parsee DESPUÉS,
    # hasta que un '57KI' posterior la cambie (ver `DCPoint.antenna_height`).
    current_antenna_height: Optional[float] = None

    # Índice punto ya agregado por nombre -- sólo para poder asociar un
    # '67SO' (ver más abajo) con el '66KI' del mismo nombre ya parseado
    # antes en el archivo. Nunca indexa una ocupación de base ('is_base'),
    # para no arriesgar una asociación accidental si alguna vez una base
    # compartiera nombre con un punto de campo.
    puntos_por_nombre: Dict[str, DCPoint] = {}

    # Ocupación de base RTK física VIGENTE mientras se recorre el archivo
    # en orden (ver `DCPoint.base_station_name`/`base_baseline_m`) --
    # `None` hasta que aparezca el primer '66SI'/'66FD', y actualizada
    # cada vez que aparece uno nuevo (mismo patrón que `current_ant_height`
    # más abajo, y que `current_base` en chcnav_parser.py para su registro
    # 'BP'). Todo punto no-base parseado DESPUÉS de esta línea del archivo
    # queda asociado a esta ocupación, hasta que otra la reemplace.
    current_base: Optional[DCPoint] = None

    # Último punto NO-base agregado (ya sea por `parse_line` o "ascendido"
    # por el caso especial de '67SO' más abajo) -- se usa para asociarle
    # un comentario '13NM' que viene sin nombre de punto propio, ver el
    # manejo de '13NM' más abajo y `DCPoint.comment`.
    current_point: Optional[DCPoint] = None

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        code = line[:4]

        if code == "10NM" and dc.job_name is None:
            dc.job_name = _extract_job_name(line)
            continue
        if code == "00NM" and dc.instrument is None:
            dc.instrument = _extract_instrument(line)
            continue
        if code == "13TS" and dc.date_text is None:
            dc.date_text = _extract_date_text(line)
            continue
        if code == "57KI":
            h = _parse_57ki_antenna_height(line)
            if h is not None:
                current_antenna_height = h
            continue
        if code == "E2NM" and dc.receiver_type is None and dc.receiver_sn is None:
            tipo, serie, offset_arp = _extract_e2nm(line)
            dc.receiver_type = tipo
            dc.receiver_sn = serie
            dc.receiver_arp_offset_from_file = offset_arp
            continue
        if code == "13NM":
            # Comentario de operador (ver `DCPoint.comment`), asociado
            # SIEMPRE al punto no-base parseado más recientemente
            # (`current_point`) -- NUNCA por coincidencia de nombre: se
            # había interpretado inicialmente que un '13NM' podía traer
            # un nombre de punto de 8 caracteres pegado al texto (ver
            # `body[:8]`) para asociarse EXPLÍCITAMENTE a ESE punto en vez
            # de al último parseado, pero la base de datos POSTPLOT real
            # de referencia desmiente esa lectura: para "13NM51802283xfaldo"
            # (línea 211 de ar180118.dsc) el Comment real es literalmente
            # "51802283xfaldo" -- el texto COMPLETO, SIN separar ningún
            # nombre -- adjunto al punto que estaba vigente en ese momento
            # del archivo ("51802283", que sí coincidía); y para
            # "13NM51802388xfaldo" (línea 911) el Comment real vuelve a
            # ser el texto completo "51802388xfaldo", pero esta vez
            # adjunto al punto REALMENTE vigente en ese momento,
            # "52102388" -- que NO coincide con el "51802388" del texto
            # (confirmado además por el archivo de notas de operador
            # ar180118.NOT, que documenta este caso como un "Prior Point
            # ID" -- un typo del operador al escribir el nombre, sin
            # ningún efecto sobre a qué punto se adjunta el comentario).
            texto = line[4:].strip()
            objetivo = current_point
            # Líneas de información de sesión/firmware, no un comentario
            # de un punto -- se descartan (confirmado con 3001YC.dc:
            # "13NMReceiver firmware version=6.400").
            if texto and not texto.lower().startswith("receiver firmware version"):
                if objetivo is not None:
                    if objetivo.comment:
                        objetivo.comment = f"{objetivo.comment} {texto}"
                    else:
                        objetivo.comment = texto
                    if texto.lower().startswith("eliminado"):
                        objetivo.deleted = True
            continue
        if code in ("67SO", "67TP"):
            # Descubierto con un archivo real (ar180118.dsc, "clásico",
            # de antes de que existiera el RTX): un '67SO' es, en los
            # hechos, el mismo tipo de registro que un '66SO' en otros
            # archivos -- trae, en la línea siguiente, el mismo 'C6NM' de
            # calidad (satélites/PDOP/HDOP/VDOP/épocas/duración) y, más
            # adelante, los mismos 'A0SO'/'A5SO' de desplazamiento
            # respecto al diseño -- sólo que usa OTRO prefijo numérico
            # ('67' en vez de '66', ver la nota de `KNOWN_AUX_PREFIXES`
            # sobre por qué el mismo tipo de registro puede aparecer con
            # un prefijo/sufijo distinto según el trabajo) y, sobre todo,
            # sus propias tres coordenadas NO son lat/lon/altura: son
            # (ΔNorte, ΔEste, ΔAltura) de ese punto respecto a la base RTK
            # vigente, en un marco local topocéntrico centrado en la base
            # (confirmado al milímetro contra la base de datos POSTPLOT de
            # referencia -- ver la nota completa al principio del módulo y
            # `DCPoint.base_baseline_m`; para el 100% de sus 230
            # apariciones reales, además, el nombre coincide exactamente
            # con el de un '66KI' ya visto antes en el mismo archivo).
            # Por eso NUNCA se agrega como un `DCPoint` propio: en cambio,
            # se busca el '66KI' ya agregado con el MISMO nombre y se le
            # copian los datos de calidad reales del 'C6NM' que sigue,
            # además de "ascenderlo" de record_type 'KI' a 'SO' -- ahora
            # sí tiene los mismos datos de campo reales que cualquier otro
            # punto 'SO' -- y de reemplazar su `base_baseline_m` (hasta
            # ahora la aproximación haversine calculada al parsear el
            # '66KI') por el valor preciso `sqrt(ΔN²+ΔE²+ΔAltura²)` que
            # traen las propias coordenadas de este registro.
            #
            # '67TP' (4 apariciones reales, todas en ar180118.dsc) es el
            # MISMO mecanismo de promoción, con el MISMO layout ('C6NM'/
            # 'A0TP'/'A5TP' en vez de 'A0SO'/'A5SO') -- pero señala una
            # ocupación DESCARTADA en campo: las 4 apariciones reales
            # coinciden, nombre por nombre, con los 4 únicos puntos que la
            # base de datos POSTPLOT de referencia marca con un prefijo
            # "D" (borrado) -- y las 4 vienen, en el propio archivo,
            # seguidas poco después de un '13NM' con texto "Eliminado ..."
            # (ver `DCPoint.deleted`). Por eso un '67TP' pone
            # `deleted = True` directamente (señal estructural, más
            # confiable que depender sólo del texto del comentario).
            #
            # Reocupaciones repetidas del MISMO nombre (ya "asociada" ->
            # 'objetivo.n_sats is not None'): dos casos reales distintos,
            # verificados por separado contra la base de datos POSTPLOT:
            #   (a) dos '67SO' sin ningún '67TP' de por medio (el único
            #       caso real, "52102279") -- GPSeismic lo expone como UNA
            #       sola fila con un prefijo "?" (reocupación ambigua): se
            #       conserva la calidad de la PRIMERA (criterio de
            #       "primero que aparece" ya usado en todo el módulo) y se
            #       marca `ambiguous_reoccupation = True` en la(s)
            #       siguiente(s), sin pisar sus datos.
            #   (b) un '67TP' (ocupación descartada) seguido más adelante
            #       por un '67SO' del MISMO nombre (las 4 apariciones
            #       reales de '67TP', ej. "51802277") -- GPSeismic trata
            #       la reocupación buena como el reemplazo real de la
            #       descartada: acá se sobreescriben calidad/baseline con
            #       los del nuevo evento y se "revive" el punto
            #       (deleted=False, se limpia el comentario "Eliminado"
            #       que le hubiera puesto el '13NM' intermedio) -- en vez
            #       de marcarlo ambiguo, ya que este patrón (descartar +
            #       volver a levantar) es el comportamiento esperado, no
            #       una ambigüedad genuina. (Arquitectura: el plugin sólo
            #       admite UN `DCPoint` por nombre -- a diferencia de
            #       GPSeismic, que sí expone ambas ocupaciones como filas
            #       separadas, D-prefijada + normal -- así que la fila
            #       descartada, una vez reemplazada, no queda accesible
            #       por separado; se prefiere mostrar el resultado bueno y
            #       final antes que la ocupación ya descartada en campo.)
            # `antenna_height`/`descriptor` SÍ se actualizan acá, al
            # momento de la promoción (no se dejan los que tenía el
            # '66KI' original) -- corregido en esta ronda: verificado
            # contra la base de datos POSTPLOT real que la altura de
            # antena vigente al momento del '66KI' inicial NO es la que
            # GPSeismic muestra como "HI" (para 229 puntos, "HI" siempre
            # coincide con el '57KI' vigente al momento de ESTA promoción
            # '67SO'/'67TP', más un offset fijo -- ver
            # `RECEIVER_ARP_OFFSET_M`, aplicado más adelante al armar la
            # previsualización), y lo mismo para el Descriptor (ver la
            # nota junto a `DCPoint.descriptor`).
            es_tp = code == "67TP"
            resultado = _split_name_and_coords(line[4:])
            if resultado is not None:
                nombre_prom, a, b, c = resultado
                objetivo = puntos_por_nombre.get(nombre_prom)
                if objetivo is not None:
                    ya_promovido = objetivo.n_sats is not None
                    reemplaza_descarte = ya_promovido and objetivo.deleted and not es_tp
                    if (not ya_promovido or reemplaza_descarte) and i + 1 < len(lines):
                        siguiente = lines[i + 1].rstrip("\r\n")
                        quality = _parse_c6nm_quality(siguiente)
                        if quality is not None:
                            objetivo.n_sats = quality["n_sats"]
                            objetivo.pdop = quality["pdop"]
                            objetivo.hdop = quality["hdop"]
                            objetivo.vdop = quality["vdop"]
                            objetivo.n_epochs = quality["n_epochs"]
                            objetivo.occupation_seconds = quality["occupation_seconds"]
                            objetivo.t_inicio_sesion = quality["t_inicio_sesion"]
                            precision = _leer_precision_60nm(lines, i + 1)
                            if precision is not None:
                                objetivo.hor_precision_95 = precision["hor_precision_95"]
                                objetivo.ver_precision_95 = precision["ver_precision_95"]
                                objetivo.cq = precision["cq"]
                                objetivo.unit_variance = precision["unit_variance"]
                            objetivo.record_type = "SO"
                            objetivo.base_baseline_m = math.sqrt(a * a + b * b + c * c)
                            objetivo.antenna_height = current_antenna_height
                            objetivo.descriptor = _extract_descriptor(line)
                            # `height` NO se toca acá -- ver
                            # `DCPoint.height_is_placeholder` para el por
                            # qué (las 3 coordenadas de este registro son
                            # un vector local, no lat/lon/altura).
                            objetivo.height_is_placeholder = True
                            if reemplaza_descarte:
                                objetivo.deleted = False
                                objetivo.comment = None
                            elif es_tp:
                                objetivo.deleted = True
                            current_point = objetivo
                    elif ya_promovido and not reemplaza_descarte:
                        objetivo.ambiguous_reoccupation = True
                        # Un comentario '13NM' que venga justo después de
                        # esta reocupación ignorada (caso real: "13NMxcano
                        # gas" justo después de la segunda ocurrencia de
                        # "52102279") sigue refiriéndose a ESTE punto, no
                        # al que se haya parseado antes -- se actualiza
                        # `current_point` igual que en la rama de arriba,
                        # aunque no se toquen sus datos de calidad.
                        current_point = objetivo
            continue

        point = parse_line(line, i + 1)
        if point is not None:
            point.antenna_height = current_antenna_height
            if point.is_base:
                # Nueva ocupación de base (o reocupación de la misma,
                # ver `BASE_CODES`) -- queda vigente para los puntos no-
                # base que se parseen después, hasta que otra la
                # reemplace (ver `current_base` más arriba).
                current_base = point
            else:
                if current_base is not None:
                    point.base_station_name = current_base.name
                    point.base_baseline_m = _haversine_m(
                        point.lat, point.lon, current_base.lat, current_base.lon
                    )
                if point.record_type == "SO" and i + 1 < len(lines):
                    siguiente = lines[i + 1].rstrip("\r\n")
                    quality = _parse_c6nm_quality(siguiente)
                    if quality is not None:
                        point.n_sats = quality["n_sats"]
                        point.pdop = quality["pdop"]
                        point.hdop = quality["hdop"]
                        point.vdop = quality["vdop"]
                        point.n_epochs = quality["n_epochs"]
                        point.occupation_seconds = quality["occupation_seconds"]
                        point.t_inicio_sesion = quality["t_inicio_sesion"]
                        precision = _leer_precision_60nm(lines, i + 1)
                        if precision is not None:
                            point.hor_precision_95 = precision["hor_precision_95"]
                            point.ver_precision_95 = precision["ver_precision_95"]
                            point.cq = precision["cq"]
                            point.unit_variance = precision["unit_variance"]
            dc.points.append(point)
            if not point.is_base:
                puntos_por_nombre.setdefault(point.name, point)
                current_point = point
        elif (
            code[2:4] in COORD_SUFFIXES
            and code not in KNOWN_AUX_CODES
            and code[0:2] not in KNOWN_AUX_PREFIXES
        ):
            # Parecía un registro de punto por su sufijo pero no se pudo
            # interpretar: se registra como advertencia en lugar de
            # fallar silenciosamente o interrumpir el proceso completo.
            # (Los códigos de KNOWN_AUX_CODES, y cualquier código cuyo
            # prefijo de 2 letras esté en KNOWN_AUX_PREFIXES, también
            # terminan en KI/SO pero son registros auxiliares conocidos,
            # no puntos mal formados -- no ameritan advertencia.)
            dc.warnings.append(f"Línea {i + 1}: no se pudo interpretar el registro '{code}'.")
        else:
            dc.header_lines.append(line)

    # Relleno para el caso de UNA sola base física en todo el archivo:
    # un punto no-base parseado ANTES de la primera ocupación de base
    # ('66SI'/'66FD') queda, durante el recorrido de arriba, sin
    # `base_station_name` (por diseño: la asociación es por orden de
    # aparición, ver `DCPoint.base_station_name`). Confirmado contra la
    # base de datos POSTPLOT real de referencia que esto es INCORRECTO
    # cuando sólo hay una base física en el archivo: el punto "PF10" de
    # ar180118.dsc aparece antes de la primera línea de base (línea 19,
    # base recién en la línea 28) y sin embargo GPSeismic lo asocia
    # igual a "SA01" -- la única base del archivo -- con su distancia
    # real (verificada al milímetro, ver `base_baseline_m` más arriba).
    # Por eso, sólo cuando el archivo tiene EXACTAMENTE una base física
    # distinta, se "rellena" cualquier punto que haya quedado sin
    # asociar con esa única base (calculando su distancia por haversine,
    # igual que para los puntos ya asociados durante el recorrido en
    # orden). Si el archivo tiene DOS O MÁS bases distintas no se hace
    # ningún relleno: no hay ningún archivo real de referencia con más
    # de una base física que confirme qué debería pasar con un punto
    # anterior a la primera, así que se prefiere dejarlo en `None`
    # (ambigüedad explícita) antes que adivinar.
    nombres_base = dc.unique_base_names()
    if len(nombres_base) == 1:
        bases_por_nombre = {p.name: p for p in dc.points if p.is_base}
        unica_base = bases_por_nombre.get(nombres_base[0])
        if unica_base is not None:
            for p in dc.points:
                if not p.is_base and p.base_station_name is None:
                    p.base_station_name = unica_base.name
                    # Si ya tiene un `base_baseline_m` preciso (puesto por
                    # el caso especial de '67SO', ver más arriba) NO se
                    # sobreescribe con la aproximación haversine -- sólo
                    # se calcula acá si todavía no tenía ninguno.
                    if p.base_baseline_m is None:
                        p.base_baseline_m = _haversine_m(
                            p.lat, p.lon, unica_base.lat, unica_base.lon
                        )

    dups = dc.duplicated_names()
    if dups:
        ejemplos = ", ".join(list(dups.keys())[:5])
        dc.warnings.append(
            f"{len(dups)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplos})."
        )

    # "Elapsed Time" (pedido explícito del usuario, ver la nota completa
    # junto a `DCPoint.elapsed_seconds` y `_parse_c6nm_quality`): tiempo
    # transcurrido desde el primer epoch del punto 'SO' anterior hasta el
    # de éste. Se ordena por `t_inicio_sesion` (el epoch real de cada
    # punto) en vez de por la posición de cada punto en `dc.points` --
    # necesario porque un punto "promovido" por un '67SO'/'67TP' (ver el
    # caso especial más arriba) queda en `dc.points` en la posición de su
    # aparición ORIGINAL como '66KI' (normalmente mucho antes en el
    # archivo), no en la posición donde de verdad se le tomó el epoch de
    # calidad -- recorrer la lista tal cual daría un "punto anterior"
    # equivocado para esos casos. Se recorre DESPUÉS de terminar de
    # parsear todo el archivo (no durante, arriba) por el mismo motivo:
    # una promoción puede actualizar `t_inicio_sesion` de un punto ya
    # agregado antes.
    con_epoch = sorted(
        (p for p in dc.points if not p.is_base and p.t_inicio_sesion is not None),
        key=lambda p: p.t_inicio_sesion,
    )
    anterior = None
    for p in con_epoch:
        if anterior is not None:
            delta = p.t_inicio_sesion - anterior
            if delta >= 0:
                p.elapsed_seconds = delta
        anterior = p.t_inicio_sesion

    # "Hora de levant. (Local/GMT)" y "Hora serial (GPS)" -- ver el
    # docstring completo junto a `_calibrar_horas_gps`/`_GMT_WEEK_CALIBRATION`.
    # Completa algo si la semana de trabajo de este archivo ya está
    # calibrada a mano, o si sus propias marcas '13TS' alcanzan para una
    # calibración automática confiable; deja los tres campos en blanco
    # (como ya estaban) en caso contrario.
    _calibrar_horas_gps(dc, lines)

    return dc


def parse_dc_file(path: str, encoding: str = "latin-1") -> DCFile:
    """Lee y parsea un archivo .dc desde disco.

    Se usa 'latin-1' por defecto porque estos archivos no suelen venir en
    UTF-8 y latin-1 nunca falla al decodificar (evita UnicodeDecodeError
    ante caracteres fuera de ASCII en nombres de trabajo, comentarios,
    etc.).
    """
    with open(path, "r", encoding=encoding, newline="") as f:
        text = f.read()
    return parse_dc_text(text, path=path)


def parse_dc_files(paths: List[str], encoding: str = "latin-1") -> List[DCFile]:
    return [parse_dc_file(p, encoding=encoding) for p in paths]
