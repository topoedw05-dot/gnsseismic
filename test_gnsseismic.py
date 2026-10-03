# -*- coding: utf-8 -*-
"""
Pruebas unitarias de la lógica pura del plugin (sin dependencias de
QGIS/PyQt): parser de .dc, esquema de base de datos y comparación CSV.

Ejecutar con:  python3 -m unittest test_gnsseismic.py -v
"""

import array
import csv
import math
import os
import sqlite3
import struct
import tempfile
import unittest

import db_schema
import csv_matcher
from dc_parser import (
    parse_dc_text, parse_line, receiver_arp_offset_m, receiver_arp_offset_known,
    resolve_receiver_arp_offset, receiver_arp_offset_known_for_file, _extract_e2nm,
    _parse_60nm_precision,
)
import preplot_generator
import export_writers
import geoid_utils
import ggf_reader
import hitarget_parser
import hitarget_raw_parser
import chcnav_parser
import stonex_parser
import i18n
import qld_reader


SAMPLE_DC = "\r\n".join([
    "00NMSC V10-70       102105-Jan-26 12:20 111111",
    "10NMTRABAJO1        121221",
    "13TSTime Date 02/05/2026 Time 05:30:55                          ",
    "66KI        10255092-37.096757440900-69.4656316462000.0000000000000051              11                                ",
    "66KI        10255093-37.096306921900-69.4656288894000.0000000000000051              11                                ",
    "66SO        21295190-37.053113691566-69.310221877116939.13734038639851              :30.017225441276400.03872155025601",
])

# Extracto real y sin modificar de un archivo .dc de Trimble subido por
# el usuario (3001YC.dc, sísmica Argentina): el punto '66SO' 14095304
# seguido de su registro 'C6NM' asociado. El usuario confirmó, con un
# reporte aparte de ese mismo punto, sus valores reales conocidos de
# antemano: Number of Satellites=22, PDOP=1.14, HDOP=0.57, VDOP=0.98 --
# usados para deducir por ingeniería inversa el formato de 'C6NM' (ver
# `_parse_c6nm_quality` en dc_parser.py) y verificados aquí para que
# una futura ronda no rompa esa decodificación sin darse cuenta.
SAMPLE_DC_SO_WITH_C6NM = "\r\n".join([
    "66SO        14095304-37.001445958719-69.411123662040998.59044245164857              :30.014824990219890.03368862345815",
    "C6NM2211.135778546333310.568085312843320.98349982500076                0007                                2403473010.0000000002403473016.0000000001",
])

# Extracto real y sin modificar de 3001YC.dc (líneas 13611-13613, el mismo
# punto 14095304 de arriba, esta vez con su registro '60NM' -- que hasta
# la v2.40.0 se trataba como un código auxiliar opaco (ver
# `KNOWN_AUX_CODES`) y desde esta ronda se decodifica por completo. El
# usuario confirmó, para este mismo punto, sus valores reales conocidos de
# antemano (h95=0.029, v95=0.066, cq=0.037) y además subió la base de
# datos POSTPLOT completa de este archivo (previsualizacion3.mdb, 208
# puntos) -- usada para verificar la fórmula contra el 100% de sus puntos
# no descartados, no sólo este (ver el docstring de
# `_parse_60nm_precision` en dc_parser.py para el detalle completo).
SAMPLE_DC_SO_WITH_60NM = "\r\n".join([
    "66SO        14095304-37.001445958719-69.411123662040998.59044245164857              :30.014824990219890.03368862345815",
    "C6NM2211.135778546333310.568085312843320.98349982500076                0007                                2403473010.0000000002403473016.0000000001",
    "60NM0.010618983767930.010344927199180.033688623458150.000009059654990.010926771909000.0100192809477436.20357894897461.00000000000000",
])

# Registro '60NM' real y sin modificar de un SEGUNDO archivo .dc de
# Trimble (ar180118.dsc, punto "PF10", receptor R6-2 -- distinto del de
# arriba): trae un campo NEGATIVO (el cuarto, un término cruzado de
# magnitud muy pequeña) en el que el signo "-" ocupa una posición de
# carácter que en un campo positivo sería un dígito más (ver el docstring
# de `_parse_60nm_precision`): sin ese ajuste de ancho, la lectura de los
# campos siguientes queda desalineada y la línea entera falla a decodificar.
# Se prueba directo contra `_parse_60nm_precision` (no contra
# `parse_dc_text`) porque lo único que importa para este caso es la
# decodificación del propio registro, no el mecanismo de promoción '67SO'
# de donde se extrajo. Valores reales conocidos de antemano
# (previsualisacion2.mdb, fila "PF10"): h95=0.025, v95=0.03 (0.029999999),
# cq=0.02, unit_variance=0.6 (0.60000002).
SAMPLE_60NM_LINE_NEGATIVE_FIELD = (
    "60NM0.010196711868050.007321746554230.01530697476119-0.00000511800820.010221925564110.007286504842343.041339635849000.60000002384186"
)

# Extracto real y sin modificar de 3001YC.dc (líneas 13611-13622): los
# tres puntos '66SO' consecutivos que siguen al de arriba (14095304),
# cada uno con su 'C6NM' -- usado para "Elapsed Time" (pedido explícito
# del usuario, ver `DCPoint.elapsed_seconds`): la diferencia entre el
# primer epoch de cada par de puntos consecutivos (2403473132-2403473010
# = 122; 2403473208-2403473132 = 76) es una duración real y verificable
# aunque esos números en sí no sean una hora de calendario (ver la nota
# completa junto a `_parse_c6nm_quality`).
SAMPLE_DC_TRES_SO_CONSECUTIVOS = "\r\n".join([
    "66SO        14095304-37.001445958719-69.411123662040998.59044245164857              :30.014824990219890.03368862345815",
    "C6NM2211.135778546333310.568085312843320.98349982500076                0007                                2403473010.0000000002403473016.0000000001",
    "66SO        14095305-37.000994689125-69.411119986812998.76167343463851              :30.022054424590570.08095169067383",
    "C6NM2311.112536668777470.551952779293060.96596378087997                0006                                2403473132.0000000002403473138.0000000001",
    "66SO        14095306-37.000542202587-69.4113646257991000.8726474717351              :30.021942398926240.06056489795446",
    "C6NM2311.116575121879580.552281737327580.97042506933212                0006                                2403473208.0000000002403473214.0000000001",
])

# Extracto real y sin modificar de 3001YC.dc: líneas 10-11 (el primer
# '57KI' del archivo, al principio mismo, justo antes del primer '66KI')
# y líneas 13610-13611 (un '57KI' posterior, justo antes de un '66SO' --
# ver el docstring de `_parse_57ki_antenna_height` en dc_parser.py para
# la verificación de por qué se interpreta como altura de antena
# vigente, incluyendo el ruido de serialización de punto flotante propio
# del receptor en ambos valores).
SAMPLE_DC_WITH_57KI = "\r\n".join([
    "57KI0.000000000000001",
    "66KI        10255092-37.096757440900-69.4656316462000.0000000000000051              11                                ",
    "66KI        10255093-37.096306921900-69.4656288894000.0000000000000051              11                                ",
    "57KI1.700000000000002",
    "66SO        14095304-37.001445958719-69.411123662040998.59044245164857              :30.014824990219890.03368862345815",
])


# Extracto real y sin modificar de un segundo archivo .dc de Trimble
# subido por el usuario (ar180118.dsc, "clásico", de antes de que
# existiera el RTX -- así lo confirmó el propio usuario al subirlo, para
# que se identificara la base RTK a corregir en el módulo "Importar datos
# de campo"). Trae la ocupación inicial de la base física ('66SI', línea
# 28 del archivo real) seguida de su primera reocupación/"Found" ('66FD',
# línea 30) -- ambas con el mismo nombre ("SA01") y la misma coordenada,
# byte a byte -- y, entre medio y después, varios registros auxiliares
# reales NO relacionados que antes de esta ronda no existían en
# `KNOWN_AUX_CODES`/`BASE_CODES`: 'E2SI' (descripción de antena/receptor,
# CON un triple de coordenadas en CEROS -- el caso que obliga a reconocer
# la base por código completo '66SI'/'66FD', nunca por sufijo 'SI'
# genérico, ver `dc_parser.BASE_CODES`), '13NM' (comentario de texto
# libre), '73KI' (repite el nombre de la base sin coordenadas) y 'E2NM'
# (descripción de receptor). Ver también `SAMPLE_DC_WITH_57KI` más arriba
# para el '57KI' intercalado (ya soportado desde la v2.22.0).
SAMPLE_DC_WITH_BASE = "\r\n".join([
    "66SI        SA01    -45.711423407377-68.149230633001703.69200932979650              11                                ",
    "57KI0.000000000000001",
    "66FD        SA01    -45.711423407377-68.149230633001703.69200932979650              11                                ",
    "E2SI                  000 Externa desconocida                     0.000000000000000.000000000000000.00000000000000",
    "13NMReceiver firmware version=0.000                             ",
    "57KI1.485000014305111",
    "73KI        SA01    ",
    "71KI11984389476.000000000410001                                                                ",
    "E2NMR6-2    49131686352530R6-2 Internal                           0.000000000000000.000000000000000.06490000000000",
])

# Registro real y sin modificar del mismo archivo (línea 39): un '67SO'
# aislado, SIN el '66KI' del mismo nombre en el mismo texto de prueba --
# usado sólo para confirmar que, cuando no hay ningún punto ya agregado
# con ese nombre para asociar, no se agrega como su propio punto (sus
# coordenadas son de cuadrícula LOCAL, no lat/lon/altura -- ver
# `SAMPLE_DC_KI_PROMOTED_TO_SO` más abajo para el caso normal, con su
# '66KI' correspondiente sí presente).
SAMPLE_DC_67SO = (
    "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557"
    "              430.008123480060950.01300537351604"
)

# Extracto real y sin modificar de ar180118.dsc: el punto "PF10", primero
# como '66KI' (línea 19, con su posición geográfica real) y más adelante
# como '67SO' + su 'C6NM' de calidad (líneas 39-40) -- confirmado contra
# el archivo real que EL MISMO NOMBRE aparece como '66KI' en 315 casos y,
# de ésos, 229 tienen ADEMÁS un '67SO' con calidad real más adelante (0
# discrepancias: el nombre de cada '67SO' siempre coincide con un '66KI'
# ya visto). El usuario confirmó, tras una primera ronda que descartaba
# el '67SO' como no relacionado, que el archivo SÍ trae datos de calidad
# reales de puntos de campo en 'SO' -- de ahí esta ronda de corrección.
SAMPLE_DC_KI_PROMOTED_TO_SO = "\r\n".join([
    "66KI        PF10    -45.784424760500-68.239471013000705.67700000000050              11                                ",
    "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557              430.008123480060950.01300537351604",
    "C6NM1621.213173627853390.642453730106351.0290983915329024.10656429435080007                                1984389502.6000000001984389508.6000000001",
])

# Extracto real de ar180118.dsc: el ÚNICO nombre que aparece dos veces
# como '67SO' en todo el archivo ("52102279", líneas 1556 y 1569 -- un
# reshoot/verificación, valores de calidad muy parecidos pero no
# idénticos), junto con su '66KI' (línea 779). Verifica el criterio de
# "primero que aparece" para decidir cuál de las dos ocupaciones se usa.
SAMPLE_DC_KI_PROMOTED_TWICE = "\r\n".join([
    "66KI        52102279-45.739946280200-68.1241256989000.0000000000000060              11                                ",
    "67SO        52102279896.9152194208002853.59361210978-2083.267293625560              430.008780174405390.01488727198267",
    "C6NM1521.379000425338750.700500190258031.1878415346145621.50168773113640011                                1984416643.0000000001984416653.0000000001",
    "67SO        52102279812.0997586015152867.84404973639-2130.771532413560              430.008340192940450.01396939988378",
    "C6NM1521.368680715560910.701470136642461.1752676963806222.50749650493000007                                1984417017.6000000001984417024.2000000001",
])


def _dc_point_line(code: str, name: str, lat: float, lon: float, height: float) -> str:
    """Arma una línea de registro de punto '.dc' sintética, sin depender
    de un archivo real, respetando el layout de ANCHO FIJO confirmado
    (8 caracteres en blanco + 8 de nombre + 3 campos de coordenada de 16
    caracteres cada uno, ver `_split_name_and_coords` en dc_parser.py) --
    usada sólo para probar el caso de MÚLTIPLES bases físicas distintas
    en un mismo archivo, todavía no visto en ningún archivo real (el
    único disponible, ar180118.dsc, sólo tiene una base, "SA01",
    reocupada 5 veces)."""

    def field16(v: float) -> str:
        s = f"{v:.12f}"
        return (s + "0" * 16)[:16] if len(s) < 16 else s[:16]

    return code + (" " * 8) + name.ljust(8)[:8] + field16(lat) + field16(lon) + field16(height)


# Escenario sintético con DOS bases físicas distintas (no visto todavía
# en ningún archivo real): "SB01" (12 puntos simulados con sólo 2 aquí,
# por brevedad) y, tras un '66FD' de una base DISTINTA, "SB02" (otros 2
# puntos) -- exactamente el escenario que describió el usuario ("levanté
# unos puntos con una base, después me pegué a otra base y seguí
# levantando"). "SB02" se puso deliberadamente MÁS CERCA de los puntos
# de "SB01" que la propia "SB01" (y viceversa), para que una prueba que
# comprobara la asociación por CERCANÍA en vez de por ORDEN DE APARICIÓN
# fallara de inmediato.
SAMPLE_DC_TWO_DISTINCT_BASES = "\r\n".join([
    _dc_point_line("66SI", "SB01", -45.700000000000, -68.100000000000, 700.000000000000),
    _dc_point_line("66KI", "P0001", -45.700010000000, -68.100010000000, 700.000000000000),
    _dc_point_line("66KI", "P0002", -45.700020000000, -68.100020000000, 700.000000000000),
    _dc_point_line("66FD", "SB02", -45.700015000000, -68.100015000000, 700.000000000000),
    _dc_point_line("66KI", "P0003", -45.700005000000, -68.100005000000, 700.000000000000),
    _dc_point_line("66KI", "P0004", -45.700025000000, -68.100025000000, 700.000000000000),
])


class TestDCParser(unittest.TestCase):
    def test_parse_ki_point(self):
        dc = parse_dc_text(SAMPLE_DC)
        self.assertEqual(dc.job_name, "TRABAJO1")
        self.assertEqual(dc.instrument, "SC V10-70")
        ki_points = dc.points_by_type("KI")
        self.assertEqual(len(ki_points), 2)
        p = ki_points[0]
        self.assertEqual(p.name, "10255092")
        self.assertAlmostEqual(p.lat, -37.0967574409, places=6)
        self.assertAlmostEqual(p.lon, -69.4656316462, places=6)
        self.assertEqual(p.height, 0.0)

    def test_parse_so_point_height_not_merged_with_lon(self):
        # Regresión: el registro SO tiene lon y altura pegados sin
        # separador; el parser no debe fusionarlos en un solo número.
        dc = parse_dc_text(SAMPLE_DC)
        so_points = dc.points_by_type("SO")
        self.assertEqual(len(so_points), 1)
        p = so_points[0]
        self.assertAlmostEqual(p.lon, -69.310221877116, places=6)
        self.assertAlmostEqual(p.height, 939.137340386398, places=3)

    def test_track_bin_split(self):
        dc = parse_dc_text(SAMPLE_DC)
        p = dc.points_by_type("KI")[0]
        track, bin_ = p.track_bin(4)
        self.assertEqual(track, "1025")
        self.assertEqual(bin_, "5092")

    def test_non_point_lines_ignored(self):
        self.assertIsNone(parse_line("64TM3-90.000000000000-69.000000000000", 1))

    def test_invalid_coordinates_rejected(self):
        # Latitud fuera de rango -> no debe interpretarse como punto.
        linea = "66KI        99999999950.000000000000-69.4656316462000.00000000000000"
        self.assertIsNone(parse_line(linea, 1))

    def test_ki_points_never_get_quality_data(self):
        # Un '66KI' de este formato de .dc nunca trae satélites/PDOP/etc
        # -- deben quedar en None, nunca inventados.
        dc = parse_dc_text(SAMPLE_DC)
        for p in dc.points_by_type("KI"):
            self.assertIsNone(p.n_sats)
            self.assertIsNone(p.pdop)

    def test_so_point_picks_up_quality_from_following_c6nm(self):
        # Caso real (punto 14095304 de 3001YC.dc), con valores de
        # referencia confirmados por el usuario en un reporte aparte.
        dc = parse_dc_text(SAMPLE_DC_SO_WITH_C6NM)
        so_points = dc.points_by_type("SO")
        self.assertEqual(len(so_points), 1)
        p = so_points[0]
        self.assertEqual(p.n_sats, 22)
        self.assertAlmostEqual(p.pdop, 1.14, places=2)
        self.assertAlmostEqual(p.hdop, 0.57, places=2)
        self.assertAlmostEqual(p.vdop, 0.98, places=2)
        self.assertEqual(p.n_epochs, 7)
        self.assertAlmostEqual(p.occupation_seconds, 6.0, places=3)

    def test_so_point_without_following_c6nm_has_no_quality_data(self):
        # Si el 'SO' no viene seguido de un 'C6NM' (otro formato de
        # receptor, o archivo recortado), no debe inventarse nada.
        dc = parse_dc_text(SAMPLE_DC)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.n_sats)
        self.assertIsNone(p.pdop)
        self.assertIsNone(p.occupation_seconds)

    def test_elapsed_seconds_first_point_of_file_is_none(self):
        # El primer punto con dato de calidad del archivo no tiene un
        # "punto anterior" con qué compararse -- debe quedar en None, no
        # en 0.0 (0 segundos sería un dato falso, no la ausencia de uno).
        dc = parse_dc_text(SAMPLE_DC_SO_WITH_C6NM)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.elapsed_seconds)

    def test_elapsed_seconds_between_consecutive_so_points(self):
        # Caso real (puntos 14095304/305/306 de 3001YC.dc, consecutivos
        # en el archivo): "Elapsed Time" pedido explícito del usuario,
        # verificado contra la diferencia real entre los dos primeros
        # epochs de cada par de puntos consecutivos.
        dc = parse_dc_text(SAMPLE_DC_TRES_SO_CONSECUTIVOS)
        so_points = dc.points_by_type("SO")
        self.assertEqual(len(so_points), 3)
        self.assertIsNone(so_points[0].elapsed_seconds)
        self.assertAlmostEqual(so_points[1].elapsed_seconds, 122.0, places=3)
        self.assertAlmostEqual(so_points[2].elapsed_seconds, 76.0, places=3)

    def test_survey_time_and_serial_time_gps_for_calibrated_week(self):
        # Punto real 14095304 de 3001YC.dc (mismo caso que
        # `SAMPLE_DC_SO_WITH_C6NM`), en un archivo cuyo '13TS' cae en la
        # semana ISO 2026-05 (26/ene-1/feb/2026, ya calibrada en
        # `dc_parser._GMT_WEEK_CALIBRATION`). Valores reales conocidos de
        # antemano (base de datos POSTPLOT completa de 3001YC.dc, fila
        # "14095304"): Serial Time (GPS)=1453807416, Survey Time (GMT)=
        # "01/30/26 11:23:36", Survey Time (Local)="01/30/26 06:23:36" --
        # ver el docstring completo de `_SERIAL_GPS_TO_GMT_UNIX_OFFSET` en
        # dc_parser.py para la verificación adicional contra el 100% de
        # los puntos de 3 archivos de referencia independientes.
        texto = "\r\n".join([
            "13TSTime Date 01/30/2026 Time 06:00:00                          ",
            SAMPLE_DC_SO_WITH_C6NM,
        ])
        dc = parse_dc_text(texto)
        p = dc.points_by_type("SO")[0]
        self.assertEqual(p.serial_time_gps, 1453807416)
        self.assertEqual(p.survey_time_gmt, "2026-01-30 11:23:36")
        self.assertEqual(p.survey_time_local, "2026-01-30 06:23:36")

    def test_survey_time_and_serial_time_gps_blank_for_uncalibrated_week(self):
        # Mismo punto/dato de calidad que arriba, pero con una fecha de
        # archivo ('13TS') que cae en una semana SIN calibrar todavía --
        # los tres campos deben quedar en None (blanco en la
        # previsualización), nunca un valor inventado o extrapolado de
        # otra semana.
        texto = "\r\n".join([
            "13TSTime Date 03/02/2026 Time 06:00:00                          ",
            SAMPLE_DC_SO_WITH_C6NM,
        ])
        dc = parse_dc_text(texto)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.serial_time_gps)
        self.assertIsNone(p.survey_time_gmt)
        self.assertIsNone(p.survey_time_local)

    def test_survey_time_and_serial_time_gps_blank_without_13ts(self):
        # Un archivo sin ningún '13TS' no tiene fecha (`DCFile.date_text`
        # en None) -- no hay semana que buscar en la tabla de calibración,
        # así que los tres campos deben quedar en None, igual que ya
        # ocurría antes de esta ronda.
        dc = parse_dc_text(SAMPLE_DC_SO_WITH_C6NM)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.serial_time_gps)
        self.assertIsNone(p.survey_time_gmt)
        self.assertIsNone(p.survey_time_local)

    def test_survey_time_gps_auto_calibrated_from_own_13ts_anchors(self):
        # Mecanismo AUTOMÁTICO (sin tabla manual, ver
        # `dc_parser._derivar_offset_automatico`/`_recolectar_anclas_13ts`):
        # a pedido explícito del usuario ("tiene que haber un algoritmo que
        # lo resuelva"), se descubrió que las propias marcas '13TS' del
        # archivo -- normalmente sólo usadas para la fecha -- traen
        # además una hora de sistema que, aunque no es la hora real exacta,
        # viaja a un desfase CASI constante de ella
        # (`_TS_ANCHOR_DELTA_SECONDS`, deducido y verificado contra 3
        # archivos reales independientes -- ver ese docstring). Con 3+
        # marcas '13TS' seguidas cada una de un 'C6NM' (patrón "gap=2") se
        # puede derivar el mismo K exacto sin ningún dato externo.
        #
        # Este test reutiliza el mismo punto real 14095304 de 3001YC.dc
        # (K real ya confirmado=949665600 para su semana real, ver
        # `test_survey_time_and_serial_time_gps_for_calibrated_week`) pero
        # con una fecha de archivo DISTINTA (semana ISO sin entrada en
        # `_GMT_WEEK_CALIBRATION`, para forzar el camino automático) y 3
        # marcas '13TS' idénticas, cada una a `_TS_ANCHOR_DELTA_SECONDS`
        # exactos de la hora local que le correspondería a ese punto con
        # ese mismo K -- para confirmar que el mecanismo, con consenso
        # perfecto (3/3), reconstruye exactamente la misma relación.
        bloque = "\r\n".join([
            SAMPLE_DC_SO_WITH_C6NM,
        ])
        ancla = "13TSTime Date 03/02/2026 Time 08:23:19                          "
        texto = "\r\n".join([ancla, bloque] * 3)
        dc = parse_dc_text(texto)
        so_points = dc.points_by_type("SO")
        self.assertEqual(len(so_points), 3)
        for p in so_points:
            self.assertEqual(p.serial_time_gps, 1456485816)
            self.assertEqual(p.survey_time_gmt, "2026-03-02 11:23:36")
            self.assertEqual(p.survey_time_local, "2026-03-02 06:23:36")

    def test_survey_time_gps_auto_calibration_needs_minimum_anchors(self):
        # Mismo caso que arriba pero con sólo 2 marcas '13TS' utilizables
        # (`dc_parser._TS_ANCHOR_MIN_COUNT` exige al menos 3) -- deben
        # quedar en blanco, nunca calibrar con menos consenso del mínimo
        # exigido.
        ancla = "13TSTime Date 03/02/2026 Time 08:23:19                          "
        texto = "\r\n".join([ancla, SAMPLE_DC_SO_WITH_C6NM] * 2)
        dc = parse_dc_text(texto)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.serial_time_gps)
        self.assertIsNone(p.survey_time_gmt)
        self.assertIsNone(p.survey_time_local)

    def test_survey_time_gps_auto_calibration_blank_on_tie(self):
        # 4 marcas '13TS', 2 votando por un candidato de K y 2 por otro
        # (una hora de diferencia entre ambos grupos) -- un empate nunca
        # debe resolverse a favor de ninguno de los dos: mismo criterio de
        # "exacto o en blanco, nunca inventado" aplicado ahora a un
        # consenso interno ambiguo.
        ancla_a = "13TSTime Date 03/02/2026 Time 08:23:19                          "
        ancla_b = "13TSTime Date 03/02/2026 Time 09:23:19                          "
        texto = "\r\n".join([
            ancla_a, SAMPLE_DC_SO_WITH_C6NM,
            ancla_a, SAMPLE_DC_SO_WITH_C6NM,
            ancla_b, SAMPLE_DC_SO_WITH_C6NM,
            ancla_b, SAMPLE_DC_SO_WITH_C6NM,
        ])
        dc = parse_dc_text(texto)
        for p in dc.points_by_type("SO"):
            self.assertIsNone(p.serial_time_gps)
            self.assertIsNone(p.survey_time_gmt)
            self.assertIsNone(p.survey_time_local)

    def test_survey_time_gps_manual_table_takes_priority_over_auto(self):
        # Si la semana del archivo YA está calibrada a mano en
        # `_GMT_WEEK_CALIBRATION` (más precisa, verificada contra un
        # POSTPLOT real completo), el mecanismo automático NUNCA debe
        # pisarla -- aunque el archivo traiga marcas '13TS' que, por sí
        # solas, sugerirían un K distinto (ej. un colector con la hora de
        # sistema mal puesta ese día en particular). Se arman 3 marcas
        # '13TS' deliberadamente "equivocadas" (una hora de diferencia de
        # lo que el mecanismo automático usaría) en un archivo de la semana
        # REAL ya calibrada (2026-05, `3001YC.dc`) y se confirma que el
        # resultado sigue siendo el valor manual exacto, no uno derivado de
        # esas marcas.
        ancla_equivocada = "13TSTime Date 01/30/2026 Time 20:00:00                          "
        texto = "\r\n".join([ancla_equivocada, SAMPLE_DC_SO_WITH_C6NM] * 3)
        dc = parse_dc_text(texto)
        for p in dc.points_by_type("SO"):
            self.assertEqual(p.serial_time_gps, 1453807416)
            self.assertEqual(p.survey_time_gmt, "2026-01-30 11:23:36")
            self.assertEqual(p.survey_time_local, "2026-01-30 06:23:36")

    def test_hor_ver_precision_cq_from_60nm(self):
        # Punto real 14095304 de 3001YC.dc, con valores reales confirmados
        # por el usuario de antemano (h95=0.029, v95=0.066, cq=0.037) --
        # ver el docstring completo de `_parse_60nm_precision` en
        # dc_parser.py para la verificación adicional contra los 436
        # puntos combinados de 2 archivos de referencia independientes.
        dc = parse_dc_text(SAMPLE_DC_SO_WITH_60NM)
        p = dc.points_by_type("SO")[0]
        self.assertAlmostEqual(p.hor_precision_95, 0.029, delta=0.001)
        self.assertAlmostEqual(p.ver_precision_95, 0.066, delta=0.001)
        self.assertAlmostEqual(p.cq, 0.037, delta=0.001)
        self.assertAlmostEqual(p.unit_variance, 1.0, delta=0.001)

    def test_hor_ver_precision_cq_none_without_60nm(self):
        # Un punto con 'C6NM' pero SIN un '60NM' a continuación (archivo
        # recortado, o un receptor/firmware que no lo trae) debe quedar en
        # None -- se prefiere blanco a inventar un valor.
        dc = parse_dc_text(SAMPLE_DC_SO_WITH_C6NM)
        p = dc.points_by_type("SO")[0]
        self.assertIsNone(p.hor_precision_95)
        self.assertIsNone(p.ver_precision_95)
        self.assertIsNone(p.cq)
        self.assertIsNone(p.unit_variance)

    def test_60nm_negative_field_uses_narrower_width(self):
        # Caso real (ar180118.dsc, punto "PF10", receptor R6-2 distinto):
        # el cuarto campo del '60NM' viene negativo, y su ancho real es de
        # 14 dígitos significativos, no 15 -- el signo ocupa la posición
        # de carácter que en un campo positivo sería un dígito más (ver el
        # docstring de `_parse_60nm_precision`). Sin este ajuste, la
        # decodificación entera de la línea falla (los campos siguientes
        # quedan desalineados). Valores reales confirmados
        # (previsualisacion2.mdb, fila "PF10"): h95=0.025, v95=0.03,
        # cq=0.02, unit_variance=0.6.
        precision = _parse_60nm_precision(SAMPLE_60NM_LINE_NEGATIVE_FIELD)
        self.assertIsNotNone(precision)
        hor95 = 1.96 * math.sqrt(precision["sigma_n"] ** 2 + precision["sigma_e"] ** 2)
        ver95 = 1.96 * precision["sigma_h"]
        cq = math.sqrt(hor95 ** 2 + ver95 ** 2) / 1.96
        self.assertAlmostEqual(hor95, 0.025, delta=0.001)
        self.assertAlmostEqual(ver95, 0.03, delta=0.001)
        self.assertAlmostEqual(cq, 0.02, delta=0.001)
        self.assertAlmostEqual(precision["unit_variance"], 0.6, delta=0.001)

    def test_57ki_antenna_height_applies_to_following_points_until_it_changes(self):
        # v2.22.0: un '57KI' no está asociado a un solo punto -- queda
        # vigente para todos los que sigan hasta que otro '57KI' lo
        # cambie (caso real: 2 puntos '66KI' comparten el primer '57KI'
        # del archivo, luego el siguiente '57KI' cambia el valor para el
        # '66SO' que viene después).
        dc = parse_dc_text(SAMPLE_DC_WITH_57KI)
        ki_points = dc.points_by_type("KI")
        self.assertEqual(len(ki_points), 2)
        for p in ki_points:
            self.assertAlmostEqual(p.antenna_height, 0.0, places=6)
        so_points = dc.points_by_type("SO")
        self.assertEqual(len(so_points), 1)
        self.assertAlmostEqual(so_points[0].antenna_height, 1.7, places=6)
        # El '57KI' en sí no debe generar ninguna advertencia ni
        # aparecer como punto.
        self.assertEqual(dc.warnings, [])

    def test_antenna_height_is_none_when_file_has_no_57ki(self):
        # Sin ningún '57KI' en el archivo (caso normal para la mayoría de
        # archivos .dc), la altura de antena debe quedar en None -- nunca
        # inventada.
        dc = parse_dc_text(SAMPLE_DC)
        for p in dc.points:
            self.assertIsNone(p.antenna_height)

    def test_57ki_rejects_line_with_unexpected_leftover_characters(self):
        # Si sobran caracteres después del campo numérico esperado, no es
        # el layout analizado -- mejor no usar el dato.
        from dc_parser import _parse_57ki_antenna_height
        self.assertIsNone(_parse_57ki_antenna_height("57KI0.000000000000001EXTRA"))

    def test_57ki_rejects_out_of_range_value(self):
        from dc_parser import _parse_57ki_antenna_height
        # "15.00000000000000" tiene los 16 dígitos significativos
        # esperados y no deja caracteres sobrantes, pero 15 m está fuera
        # del rango físicamente posible para una altura de antena/jalón.
        self.assertIsNone(_parse_57ki_antenna_height("57KI15.00000000000000"))

    def test_known_auxiliary_codes_do_not_generate_warnings(self):
        # Antes de la v2.10.0, 'C6NM'/'A0SO'/'A5SO'/etc disparaban una
        # advertencia de "no se pudo interpretar" por cada uno, aunque
        # son registros auxiliares normales, no puntos mal formados.
        texto = SAMPLE_DC_SO_WITH_C6NM + "\r\nA0SO        140953041\r\nA5SO0.03043926693499-0.0011159167625-996.71112245165\r\n60NM0.010618983767930.010344927199180.033688623458150.000009059654990.010926771909000.0100192809477436.20357894897461.00000000000000"
        dc = parse_dc_text(texto)
        self.assertEqual(dc.warnings, [])

    def test_unrecognized_ki_so_suffixed_code_still_warns(self):
        # Un código que TERMINA en KI/SO pero no es ninguno de los
        # auxiliares conocidos ni un punto interpretable sí debe seguir
        # generando advertencia -- no basta con "termina en KI/SO" para
        # silenciarlo sin más.
        dc = parse_dc_text("99SO texto que no es un punto valido")
        self.assertEqual(len(dc.warnings), 1)

    def test_known_aux_prefix_with_different_suffix_does_not_warn(self):
        # El mismo registro de parámetros de datum/proyección puede
        # aparecer con un sufijo de 2 letras distinto según el trabajo
        # dentro del archivo (visto con 'TM' en 3001YC.dc y con 'KI' en
        # un segundo archivo real del usuario, jg-28-08-26.dsc, con datum
        # Argentina/POSGAR07) -- debe reconocerse por PREFIJO, no sólo
        # por el código completo de 4 letras ya visto antes.
        texto = "\r\n".join([
            "65KI6378137.00000000298.257222101056",
            "D5KI                                340.0000000000001.000000000000000.000000000000000.00000000000000",
            "D8KI                                ",
            "64KI3-90.000000000000-69.000000000000                0.000000000000002500000.00000000                1.00000000000000                                ",
            "49KI26378137.00000000298.2572229328700.000000000000000.000000000000000.000000000000000.000000000000000.000000000000000.000000000000000.00000000000000",
            "81KI20.000000000000000.000000000000000.000000000000000.000000000000000.00000000000000geoar16                         ",
        ])
        dc = parse_dc_text(texto)
        self.assertEqual(dc.warnings, [])

    def test_base_occupation_detected_with_is_base_and_record_type(self):
        # Caso real (ar180118.dsc): '66SI' (establecimiento inicial) y
        # '66FD' (reocupación/"Found") de la MISMA base física "SA01",
        # con coordenada idéntica -- deben quedar como puntos con
        # record_type='BASE' e is_base=True, nunca como 'KI'/'SO'.
        dc = parse_dc_text(SAMPLE_DC_WITH_BASE)
        base_points = dc.points_by_type("BASE")
        self.assertEqual(len(base_points), 2)
        for p in base_points:
            self.assertTrue(p.is_base)
            self.assertEqual(p.name, "SA01")
            self.assertAlmostEqual(p.lat, -45.711423407377, places=6)
            self.assertAlmostEqual(p.lon, -68.149230633001, places=6)
            self.assertAlmostEqual(p.height, 703.692009329796, places=3)
        self.assertEqual(dc.points_by_type("KI"), [])
        self.assertEqual(dc.points_by_type("SO"), [])

    def test_unique_base_names_collapses_repeated_occupations(self):
        # La misma base reocupada varias veces ('66SI' + '66FD') debe
        # colapsar a una sola entrada -- es la que permite listar, para la
        # tabla de "Corrección de base RTK", las bases distintas del
        # archivo (ver `DCPoint.base_station_name` para la asociación
        # real punto por punto).
        dc = parse_dc_text(SAMPLE_DC_WITH_BASE)
        self.assertEqual(dc.unique_base_names(), ["SA01"])

    def test_ki_points_after_base_get_base_station_name_and_baseline(self):
        # Un punto 'KI'/'SO' que aparece DESPUÉS de una ocupación de base
        # en el archivo debe quedar asociado a ella (`base_station_name`
        # + `base_baseline_m` calculado por geometría) -- mismo mecanismo
        # ya verificado para 'BP' de CHCNav.
        texto = "\r\n".join([
            _dc_point_line("66KI", "P0000", -45.6, -68.0, 700.0),
            SAMPLE_DC_WITH_BASE.splitlines()[0],  # '66SI SA01 ...'
            _dc_point_line("66KI", "P0001", -45.711430000000, -68.149235000000, 703.7),
        ])
        dc = parse_dc_text(texto)
        by_name = {p.name: p for p in dc.points}
        self.assertEqual(by_name["P0001"].base_station_name, "SA01")
        self.assertIsNotNone(by_name["P0001"].base_baseline_m)
        self.assertGreater(by_name["P0001"].base_baseline_m, 0.0)
        # P0000 aparece ANTES de la única ocupación de base del archivo --
        # desde la corrección de esta ronda (verificada contra la base de
        # datos POSTPLOT real de referencia, caso real "PF10" en
        # ar180118.dsc) un punto así SÍ debe quedar asociado igual a esa
        # única base, con su distancia calculada por geometría -- ya no se
        # deja en None. Ver `test_multiple_distinct_bases_each_rover_point_gets_its_own`
        # para el caso de DOS O MÁS bases distintas, donde sí se sigue sin
        # inventar ninguna asociación para un punto anterior a la primera.
        self.assertEqual(by_name["P0000"].base_station_name, "SA01")
        self.assertIsNotNone(by_name["P0000"].base_baseline_m)
        self.assertGreater(by_name["P0000"].base_baseline_m, 0.0)

    def test_multiple_distinct_bases_each_rover_point_gets_its_own(self):
        # Escenario descrito por el usuario: un mismo archivo trae dos
        # bases físicas DISTINTAS (no la misma reocupada) -- p.ej. 2
        # puntos con "SB01", el topógrafo se pega a otra base, y sigue
        # con 2 puntos más bajo "SB02". Cada punto rover debe quedar
        # asociado a la base que realmente estaba vigente cuando se
        # levantó (por ORDEN de aparición en el archivo), nunca a la
        # geográficamente más cercana -- ver `SAMPLE_DC_TWO_DISTINCT_BASES`,
        # donde las coordenadas se eligieron a propósito para que "SB02"
        # quede más cerca de los puntos de "SB01" (y viceversa), de forma
        # que una asociación por distancia (en vez de por orden) haría
        # fallar esta prueba de inmediato.
        dc = parse_dc_text(SAMPLE_DC_TWO_DISTINCT_BASES)
        self.assertEqual(dc.unique_base_names(), ["SB01", "SB02"])
        by_name = {p.name: p for p in dc.points}
        self.assertEqual(by_name["P0001"].base_station_name, "SB01")
        self.assertEqual(by_name["P0002"].base_station_name, "SB01")
        self.assertEqual(by_name["P0003"].base_station_name, "SB02")
        self.assertEqual(by_name["P0004"].base_station_name, "SB02")
        for name in ("P0001", "P0002", "P0003", "P0004"):
            self.assertIsNotNone(by_name[name].base_baseline_m)
            self.assertGreater(by_name[name].base_baseline_m, 0.0)

    def test_base_related_auxiliary_records_do_not_warn_or_misparse(self):
        # 'E2SI' (con un triple de coordenadas en CEROS -- el riesgo de
        # colisión que obliga a reconocer la base por código completo, no
        # por sufijo 'SI'), '13NM', '73KI' y 'E2NM' no deben generar
        # ninguna advertencia ni producir un punto falso (en particular,
        # 'E2SI' NO debe aparecer como un punto en (0, 0, 0)). La única
        # advertencia esperada es la de "nombre repetido" -- SA01
        # aparece dos veces a propósito ('66SI' + '66FD', la misma base
        # reocupada), el mismo aviso informativo que ya generaría, por el
        # mismo motivo, una base de CHCNav/Hi-Target reocupada varias
        # veces (ver `duplicated_names`) -- no es un error a suprimir.
        dc = parse_dc_text(SAMPLE_DC_WITH_BASE)
        self.assertEqual(len(dc.warnings), 1)
        self.assertIn("SA01", dc.warnings[0])
        self.assertEqual(dc.n_points, 2)
        for p in dc.points:
            self.assertNotEqual((p.lat, p.lon, p.height), (0.0, 0.0, 0.0))

    def test_67so_without_matching_ki_generates_no_point_or_warning(self):
        # Un '67SO' aislado, sin el '66KI' del mismo nombre ya agregado
        # (no hay a quién asociarle la calidad), no debe agregarse como
        # su propio punto -- sus propias coordenadas son de cuadrícula
        # LOCAL, no lat/lon válidos (`parse_line` directo lo confirma) --
        # ni generar una advertencia de "no se pudo interpretar".
        self.assertIsNone(parse_line(SAMPLE_DC_67SO, 1))
        dc = parse_dc_text(SAMPLE_DC_67SO)
        self.assertEqual(dc.warnings, [])
        self.assertEqual(dc.n_points, 0)

    def test_67so_promotes_matching_ki_to_so_with_real_quality(self):
        # Caso real (ar180118.dsc, ronda de corrección tras verificación
        # del usuario): un '67SO' NO es un registro auxiliar ignorable --
        # es un '66SO' real con otro prefijo, y trae calidad real
        # (satélites/PDOP/HDOP/VDOP) para un punto YA visto como '66KI'.
        # El punto debe quedar con la posición geográfica del '66KI'
        # (nunca la cuadrícula local del '67SO'), "ascendido" a
        # record_type='SO', y con los valores de calidad reales del
        # 'C6NM' -- valores de referencia confirmados por PDOP² ≈ HDOP² +
        # VDOP² (1.213² ≈ 1.472 frente a 0.642² + 1.029² ≈ 1.471).
        dc = parse_dc_text(SAMPLE_DC_KI_PROMOTED_TO_SO)
        self.assertEqual(dc.n_points, 1)
        p = dc.points[0]
        self.assertEqual(p.name, "PF10")
        self.assertEqual(p.record_type, "SO")
        self.assertAlmostEqual(p.lat, -45.784424760500, places=6)
        self.assertAlmostEqual(p.lon, -68.239471013000, places=6)
        self.assertAlmostEqual(p.height, 705.677, places=3)
        self.assertEqual(p.n_sats, 16)
        self.assertAlmostEqual(p.pdop, 1.213173627853, places=3)
        self.assertAlmostEqual(p.hdop, 0.642453730106, places=3)
        self.assertAlmostEqual(p.vdop, 1.029098391532, places=3)
        self.assertEqual(dc.warnings, [])
        # GPS Baseline preciso: sqrt(ΔN²+ΔE²+ΔAltura²) de las propias
        # coordenadas del '67SO' -- verificado al milímetro contra la
        # columna "GPS Baseline" de la base de datos POSTPLOT real de
        # referencia para este mismo punto (10731.617 m).
        self.assertAlmostEqual(p.base_baseline_m, 10731.617, places=2)
        self.assertFalse(p.ambiguous_reoccupation)

    def test_67so_repeated_name_uses_first_occurrence_only(self):
        # Caso real (el único nombre que se repite como '67SO' en todo el
        # archivo, "52102279" -- un reshoot/verificación): sólo la
        # PRIMERA ocupación se usa para la calidad, la segunda se marca
        # con `ambiguous_reoccupation=True` en vez de ignorarse sin más --
        # la base de datos POSTPLOT real de referencia marca este mismo
        # punto con un prefijo "?" en su nombre, señal de que el propio
        # GPSeismic también lo trata como una reocupación ambigua. Mismo
        # criterio de "primero que aparece" ya usado para job_name/
        # instrument/date_text para decidir CUÁL de las dos se usa.
        dc = parse_dc_text(SAMPLE_DC_KI_PROMOTED_TWICE)
        self.assertEqual(dc.n_points, 1)
        p = dc.points[0]
        self.assertEqual(p.name, "52102279")
        self.assertEqual(p.record_type, "SO")
        self.assertEqual(p.n_sats, 15)
        self.assertAlmostEqual(p.pdop, 1.379000425339, places=3)
        self.assertEqual(dc.warnings, [])
        self.assertTrue(p.ambiguous_reoccupation)

    def test_67tp_marks_point_deleted(self):
        # '67TP' (4 apariciones reales en ar180118.dsc, nunca vista en
        # 3001YC.dc/DP050226.dc): mismo mecanismo de promoción que '67SO'
        # (mismo layout, mismo 'C6NM' de calidad que sigue) pero señala
        # una ocupación DESCARTADA en campo -- las 4 apariciones reales
        # coinciden, nombre por nombre, con los 4 únicos puntos "D"-
        # prefijados (borrados) de la base de datos POSTPLOT de
        # referencia. Caso sintético (sin una '67SO' posterior que la
        # reemplace, a diferencia del caso real -- ver
        # `test_67tp_followed_by_67so_revives_point_with_final_data` para
        # ese patrón) para verificar el marcado en sí, aislado.
        texto = "\r\n".join([
            _dc_point_line("66KI", "52102253", -45.747971721400, -68.135341323000, 0.0),
            "67TP        52102253-115.465613754703196.00460964534-2733.603063956860              480.010550483991920.01540310297623",
            "C6NM1221.586312194094260.874550004352481.3389003211217819.65878632151990006                                1984397396.0000000001984397406.0000000001",
        ])
        dc = parse_dc_text(texto)
        self.assertEqual(dc.n_points, 1)
        p = dc.points[0]
        self.assertEqual(p.record_type, "SO")
        self.assertTrue(p.deleted)
        self.assertIsNotNone(p.base_baseline_m)

    def test_67tp_followed_by_67so_revives_point_with_final_data(self):
        # Caso real, sin modificar (ar180118.dsc, líneas 53/157/158/162/
        # 169/170): el punto "51802277" se levanta como '66KI', se marca
        # descartado con un '67TP' (+ su 'C6NM' y el comentario '13NM'
        # "Eliminado" intermedio), y MÁS ADELANTE se vuelve a levantar
        # bien con un '67SO' del mismo nombre. GPSeismic expone esto como
        # DOS filas separadas en su base de datos POSTPLOT (una
        # "D51802277" descartada + una "51802277" buena) -- el plugin
        # sólo admite un `DCPoint` por nombre, así que se prioriza
        # mostrar el resultado BUENO y final: la calidad/baseline del
        # '67SO' final (verificados al milímetro/centésima contra la fila
        # "51802277" real de esa base de datos: PDOP=1.39, HDOP=0.77,
        # VDOP=1.16, GPS Baseline=5199.129, Number of Satellites=13), con
        # `deleted` vuelto a False y el comentario "Eliminado" limpiado
        # (la fila buena real no trae ningún comentario).
        texto = "\r\n".join([
            "66KI        51802277-45.749622651500-68.1117615400000.0000000000000060              11                                ",
            "67TP        518022771609.312149744484049.55081208609-2917.565799601460              480.009517922552780.01477087939114",
            "C6NM1221.602998495101930.867348849773411.3480764627456719.47828323433270006                                1984395408.0000000001984395418.0000000001",
            "13NMEliminado 10:51:51 AM 1/18/2018                             ",
            "67SO        518022771577.630346155034019.84629805293-2895.316662829460              430.009580235795780.01438348911574",
            "C6NM1321.393635749816890.772104859352111.1602046489715622.32864989261880006                                1984395843.0000000001984395853.0000000001",
        ])
        dc = parse_dc_text(texto)
        self.assertEqual(dc.n_points, 1)
        p = dc.points[0]
        self.assertEqual(p.name, "51802277")
        self.assertEqual(p.record_type, "SO")
        self.assertFalse(p.deleted)
        self.assertIsNone(p.comment)
        self.assertFalse(p.ambiguous_reoccupation)
        self.assertEqual(p.n_sats, 13)
        self.assertAlmostEqual(p.pdop, 1.39, places=2)
        self.assertAlmostEqual(p.hdop, 0.77, places=2)
        self.assertAlmostEqual(p.vdop, 1.16, places=2)
        self.assertAlmostEqual(p.base_baseline_m, 5199.129, places=2)
        self.assertEqual(dc.warnings, [])

    def test_67so_promotion_sets_descriptor_from_the_promotion_record(self):
        # Descubierto y verificado en esta ronda contra la base de datos
        # POSTPLOT real de ar180118.dsc (234/234 filas): el Descriptor de
        # GPSeismic (ej. "60") son los 2 caracteres justo después del
        # bloque de 3 coordenadas del registro '67SO'/'67TP' -- NUNCA del
        # '66KI' original, que puede traer un descriptor DISTINTO (caso
        # real: PF10 trae "50" en su '66KI' pero "57" en su '67SO', y la
        # base de datos real confirma "57"). Caso real, líneas 19/39-40.
        texto = "\r\n".join([
            "66KI        PF10    -45.784424760500-68.239471013000705.67700000000050              11                                ",
            "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557              430.008123480060950.01300537351604",
            "C6NM1621.213173627853390.642453730106351.0290983915329024.10656429435080007                                1984389502.6000000001984389508.6000000001",
        ])
        dc = parse_dc_text(texto)
        p = dc.points[0]
        self.assertEqual(p.descriptor, "57")

    def test_survey_time_and_serial_time_gps_for_older_calibrated_week(self):
        # Mismo punto real "PF10" de ar180118.dsc (receptor R6-2, campaña
        # de 2018 -- totalmente independiente de 3001YC.dc/2026, ver el
        # test de arriba) en su fecha real de archivo (semana ISO 2018-03,
        # 15-21/ene/2018). Valores reales conocidos de antemano (POSTPLOT
        # completo de ar180118.dsc, fila "PF10"): Serial Time (GPS)=
        # 1200312708, Survey Time (GMT)="01/18/18 12:11:48", Survey Time
        # (Local)="01/18/18 07:11:48". Confirma que la calibración
        # funciona igual para una semana/receptor/campaña totalmente
        # distinta de la del test anterior -- no es una coincidencia de un
        # solo archivo.
        texto = "\r\n".join([
            "13TSTime Date 01/18/2018 Time 06:00:00                          ",
            "66KI        PF10    -45.784424760500-68.239471013000705.67700000000050              11                                ",
            "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557              430.008123480060950.01300537351604",
            "C6NM1621.213173627853390.642453730106351.0290983915329024.10656429435080007                                1984389502.6000000001984389508.6000000001",
        ])
        dc = parse_dc_text(texto)
        p = dc.points_by_type("SO")[0]
        self.assertEqual(p.serial_time_gps, 1200312708)
        self.assertEqual(p.survey_time_gmt, "2018-01-18 12:11:48")
        self.assertEqual(p.survey_time_local, "2018-01-18 07:11:48")

    def test_c6nm_with_extra_field_parses_n_epochs_and_occupation_seconds(self):
        # El registro 'C6NM' de ar180118.dsc (receptor Trimble R6-2, ver
        # `DCFile.receiver_type`) trae un 4to campo del mismo ancho (15
        # dígitos significativos) entre VDOP y el contador de épocas, que
        # NO trae el caso de referencia original (3001YC.dc, ver
        # `test_so_point_picks_up_quality_from_following_c6nm`) -- sin
        # saltarlo, n_epochs/occupation_seconds quedaban SIEMPRE en None
        # para todo ar180118.dsc. Verificado contra la fila real "PF10"
        # de la base de datos POSTPLOT (GDOP=7 -- que resultó ser
        # exactamente la cantidad de épocas, ver el docstring de
        # `_parse_c6nm_quality` -- y Occupation Time=6).
        texto = "\r\n".join([
            "66KI        PF10    -45.784424760500-68.239471013000705.67700000000050              11                                ",
            "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557              430.008123480060950.01300537351604",
            "C6NM1621.213173627853390.642453730106351.0290983915329024.10656429435080007                                1984389502.6000000001984389508.6000000001",
        ])
        dc = parse_dc_text(texto)
        p = dc.points[0]
        self.assertEqual(p.n_epochs, 7)
        self.assertAlmostEqual(p.occupation_seconds, 6.0, places=1)

    def test_antenna_height_and_descriptor_read_at_promotion_not_at_ki(self):
        # Corrección de esta ronda: antes, `antenna_height`/`descriptor`
        # se leían al momento del '66KI' inicial y nunca se actualizaban.
        # Caso real (PF10): el '57KI' vigente en el '66KI' es "0.0", pero
        # el vigente al momento de su '67SO' es "0.99" -- y la columna
        # "HI" real de GPSeismic es 1.0549001 = 0.99 + 0.0649 (offset
        # ARP↔L1 del R6-2, ver `RECEIVER_ARP_OFFSET_M`).
        texto = "\r\n".join([
            "57KI0.000000000000001",
            "66KI        PF10    -45.784424760500-68.239471013000705.67700000000050              11                                ",
            "57KI0.990000000000002",
            "67SO        PF10    -8678.90305120402786.80873119971-5663.738668554557              430.008123480060950.01300537351604",
            "C6NM1621.213173627853390.642453730106351.0290983915329024.10656429435080007                                1984389502.6000000001984389508.6000000001",
        ])
        dc = parse_dc_text(texto)
        p = dc.points[0]
        self.assertAlmostEqual(p.antenna_height, 0.99, places=2)
        self.assertAlmostEqual(p.antenna_height + receiver_arp_offset_m("R6-2"), 1.0549001, places=3)

    def test_receiver_arp_offset_unknown_model_returns_zero(self):
        self.assertEqual(receiver_arp_offset_m(None), 0.0)
        self.assertEqual(receiver_arp_offset_m("Un Modelo Cualquiera"), 0.0)
        self.assertAlmostEqual(receiver_arp_offset_m("R6-2"), 0.0649, places=4)

    def test_receiver_arp_offset_r780_2(self):
        # Caso real (`ar22-08-26.dsc`, receptor "R780-2", 251 puntos
        # reales, todos con la misma altura de antena cruda 1.75 m):
        # el usuario reportó que la altura real (comparada contra
        # GPSeismic) es 1.875 m -- offset = 1.875 - 1.75 = 0.125.
        self.assertAlmostEqual(receiver_arp_offset_m("R780-2"), 0.125, places=4)
        self.assertAlmostEqual(1.75 + receiver_arp_offset_m("R780-2"), 1.875, places=4)

    def test_receiver_arp_offset_known(self):
        # Distingue "no está en la tabla todavía" (debe avisarse al
        # usuario, ver `log_receptor_sin_offset_arp` en
        # `gnsseismic_windows.py`) de un offset que sí está confirmado,
        # aunque ambos casos devuelvan un offset utilizable con
        # `receiver_arp_offset_m`.
        self.assertTrue(receiver_arp_offset_known("R6-2"))
        self.assertTrue(receiver_arp_offset_known("R12i"))
        self.assertTrue(receiver_arp_offset_known("R780-2"))
        self.assertFalse(receiver_arp_offset_known("R10-2"))
        self.assertFalse(receiver_arp_offset_known(None))
        self.assertFalse(receiver_arp_offset_known(""))

    def test_e2nm_extracts_receiver_type_and_serial(self):
        # Caso real (ar180118.dsc): 'E2NM' + 8 caracteres de modelo de
        # receptor + 8 de número de serie -- verificado contra la base de
        # datos POSTPLOT real de referencia, cuyas columnas "Receiver
        # Type"="R6-2" y "Receiver SN"="49131686" coinciden exactamente.
        dc = parse_dc_text(SAMPLE_DC_WITH_BASE)
        self.assertEqual(dc.receiver_type, "R6-2")
        self.assertEqual(dc.receiver_sn, "49131686")
        # Desde la v2.52.0: el mismo registro 'E2NM' también trae, como
        # último campo, el offset ARP↔L1 que el propio receptor reporta
        # -- ver `DCFile.receiver_arp_offset_from_file` y la
        # investigación completa en `_extract_e2nm`.
        self.assertAlmostEqual(dc.receiver_arp_offset_from_file, 0.0649, places=5)

    def test_extract_e2nm_arp_offset_matches_all_known_receivers(self):
        # Investigación a pedido explícito del usuario ("gpseismic v2006
        # lo hace sin tener que recurrir a ver el offset según el
        # modelo... investigalo"): se extrajo el registro 'E2NM' de 3
        # archivos reales e independientes, uno por cada modelo ya
        # confirmado a mano en `RECEIVER_ARP_OFFSET_M`, y en los 3 casos
        # el último campo de 16 caracteres del registro coincide (exacto,
        # o con el redondeo propio de la tabla hecha a mano) con el
        # offset ARP↔L1 ya verificado contra bases POSTPLOT reales de
        # GPSeismic. Esto confirma que el propio firmware del receptor
        # escribe su offset de fábrica en cada archivo .dc/.dsc -- así es
        # como GPSeismic lo resuelve sin necesitar una tabla externa por
        # modelo.
        casos = [
            # (línea E2NM real, modelo, serie, offset esperado, tabla)
            (
                "E2NMR6-2    49131686352530R6-2 Internal                           "
                "0.000000000000000.000000000000000.06490000000000",
                "R6-2", "49131686", 0.06490, 0.0649,
            ),
            (
                "E2NMR12i    64177278286101R12i Internal                           "
                "0.000000000000000.000000000000000.17932000000000",
                "R12i", "64177278", 0.17932, 0.1793,
            ),
            (
                "E2NMR780-2  65167949637580R780-2 Internal                         "
                "0.000000000000000.000000000000000.12488000000000",
                "R780-2", "65167949", 0.12488, 0.125,
            ),
        ]
        for linea, modelo, serie, offset_archivo, offset_tabla in casos:
            with self.subTest(modelo=modelo):
                tipo, sn, offset = _extract_e2nm(linea)
                self.assertEqual(tipo, modelo)
                self.assertEqual(sn, serie)
                self.assertAlmostEqual(offset, offset_archivo, places=5)
                # El valor leído del archivo es más preciso que (pero muy
                # cercano a) la tabla hecha a mano -- nunca debería diferir
                # en más de medio milímetro.
                self.assertAlmostEqual(offset, offset_tabla, places=3)

    def test_extract_e2nm_offset_none_if_line_too_short_or_malformed(self):
        self.assertEqual(_extract_e2nm("E2NMR6-2"), (None, None, None))
        tipo, serie, offset = _extract_e2nm("E2NMR6-2    49131686" + "x" * 94)
        self.assertEqual(tipo, "R6-2")
        self.assertEqual(serie, "49131686")
        self.assertIsNone(offset)

    def test_resolve_receiver_arp_offset_prefers_file_over_table(self):
        dc = parse_dc_text(SAMPLE_DC_WITH_BASE)
        # El archivo trae su propio offset (0.0649) -- coincide con la
        # tabla en este caso, pero `resolve_receiver_arp_offset` debe
        # usar el del archivo, no el de la tabla.
        self.assertAlmostEqual(resolve_receiver_arp_offset(dc), 0.0649, places=5)
        self.assertTrue(receiver_arp_offset_known_for_file(dc))

    def test_resolve_receiver_arp_offset_falls_back_to_table(self):
        # Un archivo con 'E2NM' pero sin el campo de offset (línea corta,
        # formato inesperado) debe caer a la tabla hardcodeada.
        dc = parse_dc_text("\r\n".join([
            "00NMSC V10-70       102105-Jan-26 12:20 111111",
            "E2NMR6-2    49131686",
        ]))
        self.assertIsNone(dc.receiver_arp_offset_from_file)
        self.assertAlmostEqual(resolve_receiver_arp_offset(dc), 0.0649, places=4)
        self.assertTrue(receiver_arp_offset_known_for_file(dc))

    def test_resolve_receiver_arp_offset_unknown_receiver_no_offset(self):
        # Receptor que ni trae el campo del archivo ni está en la tabla:
        # no se inventa ninguna corrección (0.0), y se marca "no
        # conocido" para que la UI avise (ver `log_receptor_sin_offset_arp`).
        dc = parse_dc_text("\r\n".join([
            "00NMSC V10-70       102105-Jan-26 12:20 111111",
            "E2NMR10-2   99999999",
        ]))
        self.assertEqual(resolve_receiver_arp_offset(dc), 0.0)
        self.assertFalse(receiver_arp_offset_known_for_file(dc))

    def test_13nm_comment_is_the_full_text_attached_to_current_point(self):
        # Caso real, sin modificar (ar180118.dsc, línea 211, punto
        # "51802283"): la interpretación inicial ("13NM" + un nombre de
        # punto de 8 caracteres pegado al texto, separado del resto como
        # comentario) se descartó al verificarla contra la base de datos
        # POSTPLOT real de referencia -- su Comment para este punto es
        # literalmente "51802283xfaldo" (el texto COMPLETO, sin separar
        # ningún nombre), adjunto al punto vigente en ese momento del
        # archivo (que en este caso, por coincidencia, también se llama
        # "51802283"). Ver `test_13nm_comment_with_mismatched_name_still_attaches_to_current_point`
        # para el caso, igual de real, donde el "nombre" del texto NO
        # coincide con el punto vigente -- confirma que nunca hay
        # coincidencia de nombre real, sólo casualidad.
        texto = "\r\n".join([
            _dc_point_line("66KI", "51802283", -45.747770674600, -68.109173145500, 0.0),
            _dc_point_line("66KI", "OTRO0001", -45.71, -68.11, 701.0),
            "13NM51802283xfaldo                                              ",
        ])
        dc = parse_dc_text(texto)
        by_name = {p.name: p for p in dc.points}
        # El texto se adjunta COMPLETO (con el "51802283" incluido) al
        # último punto parseado ("OTRO0001"), no al punto homónimo.
        self.assertIsNone(by_name["51802283"].comment)
        self.assertEqual(by_name["OTRO0001"].comment, "51802283xfaldo")

    def test_13nm_comment_with_mismatched_name_still_attaches_to_current_point(self):
        # Caso real, sin modificar (ar180118.dsc, línea 911): el texto
        # "13NM51802388xfaldo" trae un "nombre" ("51802388") que NO
        # coincide con ningún punto real del archivo -- la base de datos
        # POSTPLOT de referencia confirma que el Comment completo
        # "51802388xfaldo" quedó adjunto al punto que realmente estaba
        # vigente en ese momento, "52102388" (un typo del operador,
        # documentado además como "Prior Point ID" en el archivo de
        # notas de operador ar180118.NOT) -- nunca se intenta "corregir"
        # ni separar el nombre.
        texto = "\r\n".join([
            _dc_point_line("66KI", "P0001", -45.7, -68.1, 700.0),
            _dc_point_line("66KI", "52102388", -45.71, -68.11, 701.0),
            "13NM51802388xfaldo                                              ",
        ])
        dc = parse_dc_text(texto)
        by_name = {p.name: p for p in dc.points}
        self.assertIsNone(by_name["P0001"].comment)
        self.assertEqual(by_name["52102388"].comment, "51802388xfaldo")

    def test_13nm_comment_falls_back_to_most_recent_point(self):
        # Caso real, sin modificar (ar180118.dsc, línea 1345): un '13NM'
        # sin ningún nombre reconocible se asocia al punto no-base
        # parseado más recientemente (no al primero).
        texto = "\r\n".join([
            _dc_point_line("66KI", "P0001", -45.7, -68.1, 700.0),
            _dc_point_line("66KI", "P0002", -45.71, -68.11, 701.0),
            "13NMxfaldo                                                      ",
        ])
        dc = parse_dc_text(texto)
        by_name = {p.name: p for p in dc.points}
        self.assertIsNone(by_name["P0001"].comment)
        self.assertEqual(by_name["P0002"].comment, "xfaldo")

    def test_13nm_firmware_version_line_is_skipped(self):
        # Caso real, sin modificar (ar180118.dsc, línea 37): una línea de
        # información de sesión/firmware no es un comentario de punto --
        # no debe asociarse a ningún punto ni generar advertencia.
        texto = "\r\n".join([
            _dc_point_line("66KI", "P0001", -45.7, -68.1, 700.0),
            "13NMReceiver firmware version=4.110                             ",
        ])
        dc = parse_dc_text(texto)
        self.assertIsNone(dc.points[0].comment)
        self.assertEqual(dc.warnings, [])

    def test_13nm_eliminado_marks_point_as_deleted(self):
        # Caso real, sin modificar (ar180118.dsc, línea 162, justo
        # después de las líneas '67TP'/'C6NM'/'60NM'/'A0TP'/'A5TP' del
        # punto "51802277" -- omitidas aquí por brevedad ya que ninguna
        # de ellas mueve `current_point`) -- confirmado como el marcador
        # real de "punto borrado en campo" contra la base de datos
        # POSTPLOT de referencia: el punto "51802277" aparece ahí como
        # "D51802277" con Comment="Eliminado 10:51:51 AM 1/18/2018",
        # coincidiendo texto por texto.
        texto = "\r\n".join([
            _dc_point_line("66KI", "51802277", -45.749622651500, -68.111761540000, 0.0),
            "13NMEliminado 10:51:51 AM 1/18/2018                             ",
        ])
        dc = parse_dc_text(texto)
        p = dc.points[0]
        self.assertTrue(p.deleted)
        self.assertEqual(p.comment, "Eliminado 10:51:51 AM 1/18/2018")

    def test_13nm_non_eliminado_comment_does_not_mark_deleted(self):
        texto = "\r\n".join([
            _dc_point_line("66KI", "P0001", -45.7, -68.1, 700.0),
            "13NMx casa                                                      ",
        ])
        dc = parse_dc_text(texto)
        p = dc.points[0]
        self.assertFalse(p.deleted)
        self.assertEqual(p.comment, "x casa")


class TestDBSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self):
        os.remove(self.path)

    def test_create_schema_tables_exist(self):
        conn = db_schema.create_project_db(self.path, overwrite=True)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tablas = {r[0] for r in cur.fetchall()}
        for esperado in ("POSTPLOT", "PREPLOT", "TableDescriptions", "COMPARACION"):
            self.assertIn(esperado, tablas)

    def test_insert_and_count(self):
        conn = db_schema.create_project_db(self.path, overwrite=True)
        filas = [{"Station_Text": "A1", "WGS84_Latitude": 1.0, "WGS84_Longitude": 2.0}]
        n = db_schema.insert_rows(conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS, filas)
        self.assertEqual(n, 1)
        self.assertEqual(db_schema.table_row_count(conn, "POSTPLOT"), 1)

    def test_open_existing_adds_missing_tables_without_dropping_data(self):
        conn = db_schema.create_project_db(self.path, overwrite=True)
        db_schema.insert_rows(conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS, [{"Station_Text": "A1"}])
        conn.close()
        # Simula una BD "vieja" sin la tabla COMPARACION.
        conn2 = sqlite3.connect(self.path)
        conn2.execute("DROP TABLE COMPARACION")
        conn2.commit()
        conn2.close()

        conn3 = db_schema.create_project_db(self.path, overwrite=False)
        self.assertEqual(db_schema.table_row_count(conn3, "POSTPLOT"), 1)  # los datos siguen ahí
        cur = conn3.execute("SELECT name FROM sqlite_master WHERE type='table'")
        self.assertIn("COMPARACION", {r[0] for r in cur.fetchall()})

    def test_project_settings_roundtrip(self):
        conn = db_schema.create_project_db(self.path, overwrite=True)
        self.assertIsNone(db_schema.get_project_setting(conn, "geoid_model_file"))
        db_schema.set_project_setting(conn, "geoid_model_file", "/ruta/geoide.tif")
        self.assertEqual(db_schema.get_project_setting(conn, "geoid_model_file"), "/ruta/geoide.tif")
        # Sobrescribe (ON CONFLICT ... DO UPDATE), no duplica la fila.
        db_schema.set_project_setting(conn, "geoid_model_file", "/otra/ruta.tif")
        self.assertEqual(db_schema.get_project_setting(conn, "geoid_model_file"), "/otra/ruta.tif")
        cur = conn.execute("SELECT COUNT(*) FROM ProjectSettings WHERE Setting_Key = 'geoid_model_file'")
        self.assertEqual(cur.fetchone()[0], 1)
        # Borrado lógico (valor vacío) -> get_project_setting cae al default.
        db_schema.set_project_setting(conn, "geoid_model_file", "")
        self.assertEqual(db_schema.get_project_setting(conn, "geoid_model_file", default="x"), "x")


class TestDeletableQuery(unittest.TestCase):
    """Borrado controlado desde el panel de consultas (v2.14.0): sólo un
    SELECT simple de una sola tabla borrable (sin JOIN/UNION/GROUP BY/CTE)
    habilita el borrado, y el DELETE real debe borrar EXACTAMENTE lo
    mismo que devolvería ese SELECT."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        self.conn = db_schema.create_project_db(self.path, overwrite=True)
        db_schema.insert_rows(
            self.conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS,
            [
                {"Station_Text": "A1", "Descriptor": "KI"},
                {"Station_Text": "A2", "Descriptor": "SO"},
                {"Station_Text": "A3", "Descriptor": "KI"},
            ],
        )

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_simple_select_star_is_deletable(self):
        tabla, where = db_schema.deletable_table_and_where("SELECT * FROM POSTPLOT")
        self.assertEqual(tabla, "POSTPLOT")
        self.assertIsNone(where)

    def test_select_with_where_extracts_condition(self):
        tabla, where = db_schema.deletable_table_and_where(
            "SELECT * FROM POSTPLOT WHERE Descriptor = 'KI'"
        )
        self.assertEqual(tabla, "POSTPLOT")
        self.assertEqual(where, "Descriptor = 'KI'")

    def test_lowercase_table_name_is_normalized(self):
        tabla, _ = db_schema.deletable_table_and_where("select * from postplot")
        self.assertEqual(tabla, "POSTPLOT")

    def test_join_is_not_deletable(self):
        tabla, where = db_schema.deletable_table_and_where(
            "SELECT p.* FROM POSTPLOT p JOIN PREPLOT q ON p.Station_Text = q.Station_Text"
        )
        self.assertIsNone(tabla)
        self.assertIsNone(where)

    def test_group_by_is_not_deletable(self):
        tabla, _ = db_schema.deletable_table_and_where(
            "SELECT Descriptor, COUNT(*) FROM POSTPLOT GROUP BY Descriptor"
        )
        self.assertIsNone(tabla)

    def test_cte_is_not_deletable(self):
        tabla, _ = db_schema.deletable_table_and_where(
            "WITH x AS (SELECT * FROM POSTPLOT) SELECT * FROM x"
        )
        self.assertIsNone(tabla)

    def test_unknown_table_is_not_deletable(self):
        tabla, _ = db_schema.deletable_table_and_where("SELECT * FROM TableDescriptions")
        self.assertIsNone(tabla)

    def test_non_select_is_not_deletable(self):
        tabla, _ = db_schema.deletable_table_and_where("DELETE FROM POSTPLOT")
        self.assertIsNone(tabla)

    def test_count_and_delete_matching_rows(self):
        n = db_schema.count_matching_rows(self.conn, "POSTPLOT", "Descriptor = 'KI'")
        self.assertEqual(n, 2)
        borrados = db_schema.delete_matching_rows(self.conn, "POSTPLOT", "Descriptor = 'KI'")
        self.assertEqual(borrados, 2)
        self.assertEqual(db_schema.table_row_count(self.conn, "POSTPLOT"), 1)
        restante = self.conn.execute("SELECT Station_Text FROM POSTPLOT").fetchone()[0]
        self.assertEqual(restante, "A2")

    def test_delete_matching_rows_without_where_deletes_all(self):
        borrados = db_schema.delete_matching_rows(self.conn, "POSTPLOT", None)
        self.assertEqual(borrados, 3)
        self.assertEqual(db_schema.table_row_count(self.conn, "POSTPLOT"), 0)

    def test_delete_matching_rows_rejects_non_deletable_table(self):
        with self.assertRaises(ValueError):
            db_schema.delete_matching_rows(self.conn, "TableDescriptions", None)

    def test_delete_rows_by_id(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID FROM POSTPLOT ORDER BY ID").fetchall()]
        borrados = db_schema.delete_rows_by_id(self.conn, "POSTPLOT", [ids[0], ids[2]])
        self.assertEqual(borrados, 2)
        restante = self.conn.execute("SELECT Station_Text FROM POSTPLOT").fetchone()[0]
        self.assertEqual(restante, "A2")

    def test_delete_rows_by_id_ignores_none_and_empty(self):
        self.assertEqual(db_schema.delete_rows_by_id(self.conn, "POSTPLOT", [None, None]), 0)
        self.assertEqual(db_schema.delete_rows_by_id(self.conn, "POSTPLOT", []), 0)
        self.assertEqual(db_schema.table_row_count(self.conn, "POSTPLOT"), 3)


class TestUpdateRowById(unittest.TestCase):
    """Edición en línea desde el panel de consultas (v2.21.0): un UPDATE
    por fila cambiada, sólo sobre columnas reales de la tabla."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        self.conn = db_schema.create_project_db(self.path, overwrite=True)
        db_schema.insert_rows(
            self.conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS,
            [
                {"Station_Text": "A1", "Descriptor": "KI"},
                {"Station_Text": "A2", "Descriptor": "SO"},
            ],
        )

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_table_column_names_matches_schema(self):
        cols = db_schema.table_column_names(self.conn, "POSTPLOT")
        self.assertIn("ID", cols)
        self.assertIn("Station_Text", cols)
        self.assertIn("Descriptor", cols)

    def test_update_row_by_id_changes_only_that_row(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID FROM POSTPLOT ORDER BY ID").fetchall()]
        db_schema.update_row_by_id(self.conn, "POSTPLOT", ids[0], {"Descriptor": "51"})
        fila = self.conn.execute("SELECT Descriptor FROM POSTPLOT WHERE ID = ?", (ids[0],)).fetchone()
        self.assertEqual(fila[0], "51")
        otra = self.conn.execute("SELECT Descriptor FROM POSTPLOT WHERE ID = ?", (ids[1],)).fetchone()
        self.assertEqual(otra[0], "SO")

    def test_update_row_by_id_multiple_columns(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID FROM POSTPLOT ORDER BY ID").fetchall()]
        db_schema.update_row_by_id(self.conn, "POSTPLOT", ids[0], {"Station_Text": "A1-editado", "Track": 5})
        fila = self.conn.execute("SELECT Station_Text, Track FROM POSTPLOT WHERE ID = ?", (ids[0],)).fetchone()
        self.assertEqual(fila[0], "A1-editado")
        self.assertEqual(fila[1], 5)

    def test_update_row_by_id_rejects_unknown_column(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID FROM POSTPLOT ORDER BY ID").fetchall()]
        with self.assertRaises(ValueError):
            db_schema.update_row_by_id(self.conn, "POSTPLOT", ids[0], {"NoExiste": "x"})
        # No debe haber cambiado nada a pesar del intento rechazado.
        fila = self.conn.execute("SELECT Descriptor FROM POSTPLOT WHERE ID = ?", (ids[0],)).fetchone()
        self.assertEqual(fila[0], "KI")

    def test_update_row_by_id_rejects_non_editable_table(self):
        with self.assertRaises(ValueError):
            db_schema.update_row_by_id(self.conn, "TableDescriptions", 1, {"x": "y"})

    def test_update_row_by_id_noop_on_empty_changes(self):
        ids = [r[0] for r in self.conn.execute("SELECT ID FROM POSTPLOT ORDER BY ID").fetchall()]
        db_schema.update_row_by_id(self.conn, "POSTPLOT", ids[0], {})  # no debe lanzar ni tocar nada
        fila = self.conn.execute("SELECT Descriptor FROM POSTPLOT WHERE ID = ?", (ids[0],)).fetchone()
        self.assertEqual(fila[0], "KI")


class TestSearchReplace(unittest.TestCase):
    """"Buscar / Buscar y reemplazar" del panel de "Base de Datos"
    (v2.53.0, pedido explícito del usuario: poder buscar y reemplazar
    por CUALQUIER columna de POSTPLOT/PREPLOT/COMPARACION sin escribir
    SQL a mano) -- `db_schema.count_replace_matches`/`replace_in_column`."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = self.tmp.name
        self.conn = db_schema.create_project_db(self.path, overwrite=True)
        db_schema.insert_rows(
            self.conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS,
            [
                {"Station_Text": "A1", "Descriptor": "KI", "Comment": "ojo revisar despues"},
                {"Station_Text": "A2", "Descriptor": "SO", "Comment": "sin novedad"},
                {"Station_Text": "A3", "Descriptor": "KI", "Comment": "ojo, base reocupada"},
            ],
        )

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_count_replace_matches_exact(self):
        n = db_schema.count_replace_matches(self.conn, "POSTPLOT", "Descriptor", "KI", exact=True)
        self.assertEqual(n, 2)

    def test_count_replace_matches_contains(self):
        n = db_schema.count_replace_matches(self.conn, "POSTPLOT", "Comment", "ojo", exact=False)
        self.assertEqual(n, 2)
        # "contiene" no matchea si el texto no está en la celda.
        self.assertEqual(
            db_schema.count_replace_matches(self.conn, "POSTPLOT", "Comment", "zzz", exact=False), 0,
        )

    def test_replace_exact_changes_whole_cell_only_on_full_match(self):
        n = db_schema.replace_in_column(self.conn, "POSTPLOT", "Descriptor", "KI", "61", exact=True)
        self.assertEqual(n, 2)
        valores = {r[0] for r in self.conn.execute("SELECT Descriptor FROM POSTPLOT ORDER BY ID").fetchall()}
        self.assertEqual(valores, {"61", "SO"})

    def test_replace_exact_does_not_touch_partial_match(self):
        # "ojo" no es el valor COMPLETO de ninguna celda de Comment, así
        # que un reemplazo exacto no debe tocar nada.
        n = db_schema.replace_in_column(self.conn, "POSTPLOT", "Comment", "ojo", "listo", exact=True)
        self.assertEqual(n, 0)
        comentarios = [r[0] for r in self.conn.execute("SELECT Comment FROM POSTPLOT ORDER BY ID").fetchall()]
        self.assertEqual(comentarios, ["ojo revisar despues", "sin novedad", "ojo, base reocupada"])

    def test_replace_contains_preserves_rest_of_cell_text(self):
        n = db_schema.replace_in_column(self.conn, "POSTPLOT", "Comment", "ojo", "listo", exact=False)
        self.assertEqual(n, 2)
        comentarios = [r[0] for r in self.conn.execute("SELECT Comment FROM POSTPLOT ORDER BY ID").fetchall()]
        self.assertEqual(comentarios, ["listo revisar despues", "sin novedad", "listo, base reocupada"])

    def test_replace_in_column_rejects_id_column(self):
        with self.assertRaises(ValueError):
            db_schema.replace_in_column(self.conn, "POSTPLOT", "ID", "1", "2", exact=True)

    def test_replace_in_column_rejects_unknown_column(self):
        with self.assertRaises(ValueError):
            db_schema.replace_in_column(self.conn, "POSTPLOT", "NoExiste", "a", "b", exact=True)

    def test_replace_in_column_rejects_non_editable_table(self):
        with self.assertRaises(ValueError):
            db_schema.replace_in_column(self.conn, "TableDescriptions", "Descriptor", "a", "b", exact=True)

    def test_count_replace_matches_rejects_non_editable_table(self):
        with self.assertRaises(ValueError):
            db_schema.count_replace_matches(self.conn, "TableDescriptions", "x", "a", exact=True)


class TestCSVMatcher(unittest.TestCase):
    def setUp(self):
        self.tmp_csv = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
        writer = csv.writer(self.tmp_csv)
        writer.writerow(["Nombre", "Este", "Norte", "Cota"])
        writer.writerow(["P1", "1000.00", "2000.00", "100.0"])
        writer.writerow(["P2-x", "1010.00", "2010.00", "101.0"])
        self.tmp_csv.close()

    def tearDown(self):
        os.remove(self.tmp_csv.name)

    def test_read_csv_points(self):
        pts = csv_matcher.read_csv_points(self.tmp_csv.name, "Nombre", "Este", "Norte", "Cota")
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0]["name"], "P1")
        self.assertEqual(pts[0]["x"], 1000.0)

    def test_match_exact_and_tolerance(self):
        diseno = csv_matcher.read_csv_points(self.tmp_csv.name, "Nombre", "Este", "Norte", "Cota")
        levantado = [
            {"name": "P1", "x": 1000.05, "y": 2000.00, "z": 100.0},
            {"name": "P2X", "x": 1010.00, "y": 2010.00, "z": 101.0},
            {"name": "P3", "x": 5000.0, "y": 5000.0, "z": 0.0},
        ]
        res = csv_matcher.match_by_name(levantado, diseno, tolerancia_m=0.10, permitir_aproximado=True)
        self.assertEqual(res.n_matched, 2)
        self.assertEqual(len(res.solo_en_levantado), 1)
        self.assertEqual(len(res.solo_en_diseno), 0)
        p1 = next(m for m in res.matched if m["name_diseno"] == "P1")
        self.assertTrue(p1["dentro_tolerancia"])
        self.assertAlmostEqual(p1["distancia_2d"], 0.05, places=3)
        p2 = next(m for m in res.matched if m["name_diseno"] == "P2-x")
        self.assertEqual(p2["tipo_match"], "aproximado")

    def test_geographic_to_local_xy_short_distance(self):
        lat0, lon0 = -37.05, -69.31
        x, y = csv_matcher.geographic_to_local_xy(lat0, lon0 + 0.001, lat0, lon0)
        # ~0.001 grados de longitud a esa latitud son unos 89 m
        self.assertAlmostEqual(x, 88.9, delta=2.0)
        self.assertAlmostEqual(y, 0.0, delta=0.01)


class TestPreplotGenerator(unittest.TestCase):
    def test_grid_basic_geometry(self):
        pts = preplot_generator.generate_grid_preplot(
            0, 0, azimuth_deg=0, line_spacing=100, station_spacing=50,
            n_lines=2, n_stations=3, first_line_number=1000, first_station_number=1,
        )
        self.assertEqual(len(pts), 6)
        # azimut 0: las estaciones avanzan hacia el norte (Y crece)
        self.assertAlmostEqual(pts[0].x, 0.0)
        self.assertAlmostEqual(pts[0].y, 0.0)
        self.assertAlmostEqual(pts[2].y, 100.0)
        # las lineas se separan hacia el este (X crece) a azimut+90
        self.assertAlmostEqual(pts[3].x, 100.0)
        self.assertEqual(pts[0].name, "10000001")
        self.assertEqual(pts[3].track, 1001)

    def test_grid_rejects_invalid_params(self):
        with self.assertRaises(ValueError):
            preplot_generator.generate_grid_preplot(0, 0, 0, 100, 50, 0, 3)
        with self.assertRaises(ValueError):
            preplot_generator.generate_grid_preplot(0, 0, 0, -1, 50, 2, 3)

    def test_line_two_points_includes_end(self):
        pts = preplot_generator.generate_line_preplot_two_points(
            0, 0, 0, 225, station_spacing=50, line_number=500,
        )
        self.assertEqual(pts[-1].x, 0)
        self.assertEqual(pts[-1].y, 225)
        # 5 estaciones regulares (0,50,100,150,200) + el punto final 225
        self.assertEqual(len(pts), 6)

    def test_line_azimuth(self):
        pts = preplot_generator.generate_line_preplot_azimuth(
            0, 0, azimuth_deg=90, length=180, station_spacing=50, line_number=7,
            first_station_number=100, station_increment=2,
        )
        self.assertEqual(len(pts), 4)
        self.assertAlmostEqual(pts[1].x, 50.0)
        self.assertAlmostEqual(pts[1].y, 0.0)
        self.assertEqual(pts[1].bin, 102)


class TestExportWritersSPS(unittest.TestCase):
    def test_record_width_always_80(self):
        rec = export_writers.format_sps_record("S", 1025, 5092, easting=2404388.2, northing=530617.6, elevation=1911.1)
        self.assertEqual(len(rec), 80)

    def test_field_alignment(self):
        rec = export_writers.format_sps_record(
            "R", line_name=1025, point_number=5092, point_index=1, point_code="G",
            static_ms=12, depth_m=3.5, datum_m=100, uphole_ms=5, water_depth_m=0.0,
            easting=2404388.2, northing=530617.6, elevation=1911.1,
            day_of_year=125, time_hhmmss="143055",
        )
        self.assertEqual(rec[0], "R")
        self.assertEqual(rec[1:17].strip(), "1025.00")
        self.assertEqual(rec[17:25].strip(), "5092.00")
        self.assertEqual(rec[25], "1")
        self.assertEqual(rec[26:28].strip(), "G")
        self.assertEqual(rec[46:55].strip(), "2404388.2")
        self.assertEqual(rec[55:65].strip(), "530617.6")
        self.assertEqual(rec[65:71].strip(), "1911.1")
        self.assertEqual(rec[71:74], "125")
        self.assertEqual(rec[74:80], "143055")

    def test_invalid_tipo_raises(self):
        with self.assertRaises(ValueError):
            export_writers.format_sps_record("X", 1, 1)

    def test_write_sps_file(self):
        rows = [
            {"Track": 1025, "Bin": 5092, "X": 2404388.2, "Y": 530617.6, "Z": 1911.1},
            {"Track": 1025, "Bin": 5093, "X": 2404398.2, "Y": 530617.6, "Z": 1910.5},
            {"Track": None, "Bin": 5094, "X": 1, "Y": 1},  # fila inválida, se omite
        ]
        tmp = tempfile.NamedTemporaryFile(suffix=".S01", delete=False)
        tmp.close()
        try:
            n = export_writers.write_sps(rows, tmp.name, tipo="S", line_col="Track", point_col="Bin", x_col="X", y_col="Y", elev_col="Z")
            self.assertEqual(n, 2)
            with open(tmp.name, "r") as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                self.assertEqual(len(line), 80)
        finally:
            os.remove(tmp.name)

    def test_parse_record_round_trip_with_format(self):
        rec = export_writers.format_sps_record(
            "S", line_name=1025, point_number=5092, point_index=1, point_code="G",
            easting=2404388.2, northing=530617.6, elevation=1911.1,
        )
        parsed = export_writers.parse_sps_record(rec)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["tipo"], "S")
        self.assertAlmostEqual(parsed["line_name"], 1025.0)
        self.assertAlmostEqual(parsed["point_number"], 5092.0)
        self.assertEqual(parsed["point_code"], "G")
        self.assertAlmostEqual(parsed["easting"], 2404388.2)
        self.assertAlmostEqual(parsed["northing"], 530617.6)
        self.assertAlmostEqual(parsed["elevation"], 1911.1)

    def test_parse_record_rejects_non_point_lines(self):
        self.assertIsNone(export_writers.parse_sps_record(""))
        self.assertIsNone(export_writers.parse_sps_record("H This is a header comment line"))
        self.assertIsNone(export_writers.parse_sps_record("X" + " " * 79))  # tipo no reconocido
        self.assertIsNone(export_writers.parse_sps_record("S corto"))  # muy corta para tener Este/Norte

    def test_parse_file_reads_source_and_receiver_records(self):
        rec_s = export_writers.format_sps_record("S", 1025, 5092, easting=100.0, northing=200.0, elevation=10.0)
        rec_r = export_writers.format_sps_record("R", 1025, 5093, easting=110.0, northing=210.0, elevation=11.0)
        tmp = tempfile.NamedTemporaryFile(suffix=".sps", delete=False, mode="w")
        try:
            tmp.write("H comentario de encabezado, se debe ignorar\n")
            tmp.write(rec_s + "\n")
            tmp.write(rec_r + "\n")
            tmp.write("\n")  # línea en blanco, se debe ignorar
            tmp.close()
            registros = export_writers.parse_sps_file(tmp.name)
            self.assertEqual(len(registros), 2)
            self.assertEqual(registros[0]["tipo"], "S")
            self.assertEqual(registros[1]["tipo"], "R")
            self.assertAlmostEqual(registros[1]["easting"], 110.0)
        finally:
            os.remove(tmp.name)


class TestExportWritersCSV(unittest.TestCase):
    """Exportación a "Excel (.csv)" del panel de consultas (v2.21.0):
    vuelca columnas/filas tal cual, sin pasar por el mapeo Nombre/X/Y."""

    def test_write_csv_file(self):
        columns = ["ID", "Station_Text", "Descriptor"]
        rows = [
            {"ID": 1, "Station_Text": "A1", "Descriptor": "KI"},
            {"ID": 2, "Station_Text": "Ñandú", "Descriptor": None},
        ]
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        try:
            n = export_writers.write_csv(columns, rows, tmp.name)
            self.assertEqual(n, 2)
            with open(tmp.name, "r", encoding="utf-8-sig", newline="") as f:
                lineas = f.read().splitlines()
            self.assertEqual(len(lineas), 3)  # encabezado + 2 filas
            self.assertEqual(lineas[0], "ID,Station_Text,Descriptor")
            self.assertIn("Ñandú", lineas[2])
            self.assertTrue(lineas[2].endswith(","))  # Descriptor None -> celda vacía
        finally:
            os.remove(tmp.name)

    def test_write_csv_empty_rows(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.close()
        try:
            n = export_writers.write_csv(["A", "B"], [], tmp.name)
            self.assertEqual(n, 0)
            with open(tmp.name, "r", encoding="utf-8-sig") as f:
                self.assertEqual(f.read().strip(), "A,B")
        finally:
            os.remove(tmp.name)


class TestPreplotGeneratorFormatPointName(unittest.TestCase):
    def test_format_point_name_matches_generated_convention(self):
        # Mismo caso que preplot_generator.generate_grid_preplot usa
        # internamente (línea 1000 + estación 1 -> "10000001"), para que
        # un punto importado de un SPS externo quede nombrado igual que
        # si se hubiera generado dentro del plugin.
        self.assertEqual(preplot_generator.format_point_name(1000, 1), "10000001")
        self.assertEqual(preplot_generator.format_point_name(1025, 5092, line_digits=4, station_digits=4), "10255092")

    def test_format_point_name_non_integer_not_truncated(self):
        # Igual que _format_number: un número no entero no se trunca,
        # aunque el resultado quede más largo que `digits`.
        self.assertEqual(preplot_generator.format_point_name(1025.5, 1), "1025.50001")


class TestGeoidUtils(unittest.TestCase):
    def test_orthometric_height_basic(self):
        # H = h - N
        self.assertAlmostEqual(geoid_utils.orthometric_height(1911.1, 25.3), 1885.8, places=6)

    def test_orthometric_height_missing_values(self):
        self.assertIsNone(geoid_utils.orthometric_height(None, 25.3))
        self.assertIsNone(geoid_utils.orthometric_height(1911.1, None))
        self.assertIsNone(geoid_utils.orthometric_height(None, None))

    def test_orthometric_height_zero_ellipsoidal(self):
        # Caso real de los registros KI del .dc (altura elipsoidal 0.0):
        # el resultado sigue siendo matemáticamente correcto (-N), aunque
        # no sea muy útil sin una altura elipsoidal real.
        self.assertAlmostEqual(geoid_utils.orthometric_height(0.0, 25.3), -25.3, places=6)


def _build_synthetic_ggf(nrows=3, ncols=3, ymin=0.0, xmin=10.0, step=1.0,
                          values_north_first=None, name=b"Test Grid",
                          header_size=110, signature=ggf_reader.SIGNATURE):
    """Arma en memoria los bytes de un .ggf sintético pequeño (mismo
    encabezado que un TNL GRID FILE real, pero con una grilla mínima),
    para poder probar el parser sin depender de un archivo real de
    varios MB. `values_north_first` es la lista fila-mayor con la fila 0
    = norte (ymax) -- así es como el formato real guarda los datos de
    verdad (ver corrección documentada en `ggf_reader.py`); el parser ya
    NO invierte el arreglo, así que estos bytes se escriben tal cual."""
    if values_north_first is None:
        # 3x3 por defecto: fila 0 (norte, lat=ymax) = [7,8,9]; fila 1 = [4,5,6];
        # fila 2 (sur, lat=ymin) = [1,2,3]
        values_north_first = [7.0, 8.0, 9.0, 4.0, 5.0, 6.0, 1.0, 2.0, 3.0]

    ymax = ymin + (nrows - 1) * step
    xmax = xmin + (ncols - 1) * step

    header = bytearray(header_size)
    struct.pack_into("<h", header, 0, 1)  # versión, no usada
    header[2:2 + len(signature)] = signature
    header[2 + len(signature):2 + len(signature) + 1] = b"\x00"
    name_field = name[:32].ljust(32, b"\x00")
    header[0x10:0x10 + 32] = name_field
    struct.pack_into("<d", header, 0x30, ymin)
    struct.pack_into("<d", header, 0x38, ymax)
    struct.pack_into("<d", header, 0x40, xmin)
    struct.pack_into("<d", header, 0x48, xmax)
    struct.pack_into("<d", header, 0x50, step)
    struct.pack_into("<d", header, 0x58, step)
    struct.pack_into("<i", header, 0x60, nrows)
    struct.pack_into("<i", header, 0x64, ncols)

    data = array.array("f", values_north_first)
    return bytes(header) + data.tobytes()


class TestGgfReader(unittest.TestCase):
    def test_parses_header_fields(self):
        raw = _build_synthetic_ggf()
        grid = ggf_reader.parse_ggf_bytes(raw)
        self.assertEqual(grid.name, "Test Grid")
        self.assertEqual((grid.nrows, grid.ncols), (3, 3))
        self.assertAlmostEqual(grid.xmin, 10.0)
        self.assertAlmostEqual(grid.xmax, 12.0)
        self.assertAlmostEqual(grid.ymin, 0.0)
        self.assertAlmostEqual(grid.ymax, 2.0)

    def test_sample_at_exact_node(self):
        raw = _build_synthetic_ggf()
        grid = ggf_reader.parse_ggf_bytes(raw)
        # (lon=10, lat=2) es la esquina noroeste -> fila 0 del archivo (norte), col 0 -> valor 7.0
        self.assertAlmostEqual(grid.sample(10.0, 2.0), 7.0, places=5)
        # (lon=10, lat=0) es la esquina suroeste -> última fila del archivo (sur), col 0 -> valor 1.0
        self.assertAlmostEqual(grid.sample(10.0, 0.0), 1.0, places=5)

    def test_sample_bilinear_interpolation(self):
        raw = _build_synthetic_ggf()
        grid = ggf_reader.parse_ggf_bytes(raw)
        # Punto a medio camino entre los 4 nodos {1,2,4,5} (esquina suroeste) -> promedio = 3.0
        self.assertAlmostEqual(grid.sample(10.5, 0.5), 3.0, places=5)

    def test_sample_out_of_bounds_returns_none(self):
        raw = _build_synthetic_ggf()
        grid = ggf_reader.parse_ggf_bytes(raw)
        self.assertIsNone(grid.sample(-74.0, 4.7))  # Bogotá, muy lejos de la grilla de prueba
        self.assertIsNone(grid.sample(11.0, 5.0))   # dentro del rango de longitud, fuera del de latitud

    def test_sample_normalizes_longitude_convention(self):
        raw = _build_synthetic_ggf()
        grid = ggf_reader.parse_ggf_bytes(raw)
        # 370 grados este equivale a 10 grados (misma esquina que test_sample_at_exact_node)
        self.assertAlmostEqual(grid.sample(370.0, 2.0), 7.0, places=5)

    def test_sample_treats_extreme_values_as_nodata(self):
        valores = [7.0, 8.0, 1e20, 4.0, 5.0, 6.0, 1.0, 2.0, 3.0]  # fila norte, col este (NE) corrupta
        raw = _build_synthetic_ggf(values_north_first=valores)
        grid = ggf_reader.parse_ggf_bytes(raw)
        # (11.5, 1.5) cae junto a la esquina noreste (fila norte, columna
        # este), que es justo la celda corrupta -> None
        self.assertIsNone(grid.sample(11.5, 1.5))
        # (10.5, 0.5), en la esquina opuesta, no toca esa celda -> sigue
        # dando un resultado normal
        self.assertIsNotNone(grid.sample(10.5, 0.5))

    def test_rejects_wrong_signature(self):
        raw = _build_synthetic_ggf(signature=b"NOT A GGF FILE")
        with self.assertRaises(ggf_reader.GgfFormatError):
            ggf_reader.parse_ggf_bytes(raw)

    def test_rejects_size_mismatch(self):
        raw = bytearray(_build_synthetic_ggf())
        raw = raw[:-37]  # truncado: ya no alcanza para nrows*ncols*4 datos completos
        with self.assertRaises(ggf_reader.GgfFormatError):
            ggf_reader.parse_ggf_bytes(bytes(raw))

    def test_rejects_too_small_file(self):
        with self.assertRaises(ggf_reader.GgfFormatError):
            ggf_reader.parse_ggf_bytes(b"TNL GRID FILE\x00")

    def test_real_argentina_file_if_available(self):
        # Prueba de regresión del bug de orientación de filas corregido
        # después de la v2.49.0 (ver nota en el docstring de
        # `ggf_reader.py`): si el archivo real está presente, valida (1)
        # el punto exacto que reportó el usuario, contra GPSeismic/el IGN
        # de Argentina, y (2) tres ciudades con ondulación conocida, con
        # límites lo bastante ajustados como para que el bug de filas
        # invertidas (que daba, por ejemplo, N=42 en Ushuaia y N=12 en
        # Salta -- al revés de la realidad) sí hiciera fallar esta prueba.
        candidatos = [
            os.path.join(os.path.dirname(__file__), "GEOIDE-Ar16.ggf"),
        ]
        real_path = next((p for p in candidatos if os.path.exists(p)), None)
        if real_path is None:
            self.skipTest("Archivo real GEOIDE-Ar16.ggf no disponible en este entorno.")
        grid = ggf_reader.read_ggf(real_path)

        # Punto real de `0502YC.dsc` (recnum 15535147, lat -37.07°): con
        # WGS84 Height=944.95697 m, GPSeismic/el IGN dan una elevación
        # ortométrica de 920.948 m -> ondulación esperada = 24.009 m.
        n_reportado = grid.sample(-69.391263438257, -37.07224729408)
        self.assertIsNotNone(n_reportado)
        self.assertAlmostEqual(n_reportado, 24.009, delta=0.1)

        # Buenos Aires: valor de referencia ampliamente publicado ~16-17 m.
        n_ba = grid.sample(-58.3816, -34.6037)
        self.assertIsNotNone(n_ba)
        self.assertTrue(14 < n_ba < 19)

        # Ushuaia (extremo sur): debe ser MENOR que Buenos Aires y Salta
        # (la ondulación decrece hacia la Patagonia austral).
        n_ushuaia = grid.sample(-68.3029, -54.8019)
        self.assertIsNotNone(n_ushuaia)
        self.assertTrue(5 < n_ushuaia < 20)
        self.assertLess(n_ushuaia, n_ba)

        # Salta (norte, cerca del alto geoidal andino/boliviano): debe
        # ser claramente MAYOR que Buenos Aires y Ushuaia.
        n_salta = grid.sample(-65.4117, -24.7859)
        self.assertIsNotNone(n_salta)
        self.assertTrue(25 < n_salta < 45)
        self.assertGreater(n_salta, n_ba)
        self.assertGreater(n_salta, n_ushuaia)


HITARGET_HEADER = (
    "id,Nombre,N,E,Z,B,L,H,AntH,σN,σE,σZ,N Promedios,Estado,"
    "InicioTiempo Loc,FinTiempo Loc,InicioUTC,FinUTC,Desc,Edad,Sats,"
    "Sats en común,PDOP,Elevación(°),Nombre VRS,Base B,Base L,"
    "H Base(Centro Fase),Estación,Incl. Ang.,Incl. Azi"
)


_HITARGET_COLUMNS = HITARGET_HEADER.split(",")


def _hitarget_row(id_, nombre, b, l, h, ant_h="1.83586", estado="RTK Fijo", desc="", **extra):
    """Arma una fila de CSV de Hi-Target con las 31 columnas del
    encabezado real (en el orden exacto de `HITARGET_HEADER`), dejando
    en blanco las que no se pasen explícitamente. `extra` acepta
    cualquier otra columna por su nombre exacto del encabezado (p.ej.
    `**{"Sats": "29", "PDOP": "1.43554", "Base B": "...", ...}`)."""
    valores = {c: "" for c in _HITARGET_COLUMNS}
    valores.update({
        "id": id_, "Nombre": nombre, "N": "0", "E": "0", "Z": "0",
        "B": b, "L": l, "H": h, "AntH": ant_h, "Estado": estado, "Desc": desc,
    })
    valores.update(extra)
    return ",".join(valores[c] for c in _HITARGET_COLUMNS)


# Bytes copiados literalmente (sin modificar un solo byte) del archivo
# real "GPS.raw" que subió el usuario -- ver el docstring de
# TestHiTargetRawParser para el detalle de qué representa cada uno.
_RAW_HEADER = b'GPS\x00\x0b\x00\x00\x00\x00-\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff'

_RAW_REC_RMV_BASE = b'RMV\x00?\xfa\xf5\xc2\x8f\\(\xf6\x01?\xb6\x01\xaf\xd1N\x7f\x07\xbf\xf4\xb8`;\xd2\x1eO@\xa5\xdd\xfc\x1b\xdaQ\x1a\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\t\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9e\x02\xbf\xf8\xa0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Hi-Target:V60-2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Base\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00set_base\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00A@\n,\xc1\xf6\xf6\x86AR\x91\x0f\xa6Z\x1b\xe3@\xa5\xda\x89\xd3E\x85\x95\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9e\x02\xbf\xe9\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00'

_RAW_REC_HSD_GPS01 = b'HSD\x00?\xfc\xcc\xcc\xcc\xcc\xcc\xcd\x02?\xb4\xa0H9!\xf5\xa7\xbf\xf4\xc3Z\xe1\xfaz\xce@\x97x\x94\xafO\r\x85\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\t\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9f\x89\xea\xfa\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Hi-Target:V60-2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00GPS01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00set_base\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00A?\x8f\x15\x8c\\X)AR\x80^\xdd06\x8b@\x97q<\xc3\xa5\xffN\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9f\x89\xea\xea\xf0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00'

_RAW_REC_HSD_PT1 = b'HSD\x08@\x00\x00\x00\x00\x00\x00\x00\x00?\xb4\x9f\xcd[\x94\xeb;\xbf\xf4\xc3`\xb6\xa1\xe6\xbe@\x97RO}\xe7\xd0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x05\x0f@\x00\x00\x00?\xb7\xbf\xac\x1a\x1d\x08:\x88\x11\xbe:m\xc4\xf8;>\xaf\xf6?\xb4\xa0H9!>\xd0\xbf\xf4\xc3Z\xe1\xfa\xe8\x04@\x97x\x94\xa8\xf4\xb0\x00\x00\x00\x01\x9f\x89\xf1k\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Hi-Target:V30 Plus\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x001\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00L cc\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbfv\xe0Zi_\x81\x91?r\x96Iu\x9d\x99F\xbf\xf0\x00\x00\x00\x00\x00\x00A?\x8e\xe7=s\x89\x1eAR\x80V\x027\xa9B@\x97I\xf0\\\xbaP\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9f\x89\xf1[`\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00'

_RAW_REC_HSD_PT43 = b"HSD\x08@\x06ffffff\x00?\xb4\x80\xf1\xa8d\x942\xbf\xf4\xa3o\xe5\xe3\xa5\x9e@\x97^C\x0f\x17\x13L\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xf4\n?\x80\x00\x00?\xf9aA\x1b\x1e\x07G\x19\xebrIV\xbe\x88B\xe8c\xec?\xb4\xa0H9!>\xd0\xbf\xf4\xc3Z\xe1\xfa\xe8\x04@\x97x\x94\xa8\xf4\xb0\x00\x00\x00\x01\x9f\x8bL\rH\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Hi-Target:V30 Plus\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0043\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00BM HOSPITAL\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00?_t|P\xe3R'?\x82:\xc8\x0b\xf8\x1b@\xbf\xf0\x00\x00\x00\x00\x00\x00A?\x82\xf3]\r\xcf\xf7AR\xb0\xb7\xb7j\x96u@\x97R\xb0\xba\xb6`\x19\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x9f\x8bD{\xc8\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbf\xf0\x00\x00\x00\x00\x00\x00"


class TestHiTargetParser(unittest.TestCase):
    def _write_csv(self, rows, header=HITARGET_HEADER):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="",
        )
        tmp.write(header + "\n")
        for r in rows:
            tmp.write(r + "\n")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        return tmp.name

    def test_parse_dms_positive_and_negative(self):
        self.assertAlmostEqual(hitarget_parser.parse_dms(" 04°36′58.90211″"), 4.616361697222222, places=9)
        self.assertAlmostEqual(hitarget_parser.parse_dms(" -74°21′08.62095″"), -74.35239470833332, places=9)
        self.assertAlmostEqual(hitarget_parser.parse_dms(" 00°00′00.00000″"), 0.0, places=9)

    def test_parse_dms_invalid_returns_none(self):
        self.assertIsNone(hitarget_parser.parse_dms("not a dms value"))
        self.assertIsNone(hitarget_parser.parse_dms(None))
        self.assertIsNone(hitarget_parser.parse_dms(""))

    def test_looks_like_hitarget_csv(self):
        self.assertTrue(hitarget_parser.looks_like_hitarget_csv(HITARGET_HEADER.split(",")))
        self.assertFalse(hitarget_parser.looks_like_hitarget_csv(["Nombre", "X", "Y"]))
        self.assertFalse(hitarget_parser.looks_like_hitarget_csv([]))

    def test_parse_full_file_round_trip(self):
        rows = [
            _hitarget_row("1", "GPS01", "04°36′58.90211″", "-74°21′08.62095″",
                          "1500.30934", ant_h="1.83586", estado="RTK Fijo", desc="set_base"),
            _hitarget_row("2", "1", "04°36′34.19556″", "-74°21′18.28800″",
                          "1490.48473", ant_h="2.0929", estado="RTK Fix", desc="L cc"),
            _hitarget_row("3", "2", "04°36′33.61556″", "-74°21′15.50753″",
                          "1492.37434", ant_h="2.0929", estado="RTK Flotante", desc=""),
        ]
        path = self._write_csv(rows)
        hf = hitarget_parser.parse_hitarget_csv(path)
        self.assertEqual(hf.n_points, 3)
        self.assertEqual(hf.warnings, [])

        base = hf.points[0]
        self.assertEqual(base.name, "GPS01")
        self.assertTrue(base.is_base)
        self.assertAlmostEqual(base.lat, 4.616361697222222, places=9)
        self.assertAlmostEqual(base.lon, -74.35239470833332, places=9)
        self.assertEqual(base.height, 1500.30934)
        self.assertEqual(base.ant_height, 1.83586)
        self.assertEqual(base.desc, "set_base")

        rover = hf.points[1]
        self.assertFalse(rover.is_base)
        self.assertEqual(rover.name, "1")
        self.assertEqual(rover.estado, "RTK Fix")
        self.assertEqual(rover.desc, "L cc")

    def test_qc_columns_and_base_station_matching(self):
        # Base real (fila is_base) + un punto que reporta esa misma
        # coordenada en sus columnas "Base B"/"Base L" -- debe
        # encontrarla por proximidad y calcular una línea base > 0.
        base_row = _hitarget_row(
            "1", "GPS01", "04°36′58.90211″", "-74°21′08.62095″", "1500.30934",
            ant_h="1.83586", estado="RTK Fijo", desc="set_base",
        )
        rover_row = _hitarget_row(
            "2", "1", "04°36′34.19556″", "-74°21′18.28800″", "1490.48473",
            ant_h="2.0929", estado="RTK Fix", desc="L cc",
            **{
                "Sats": "29", "Sats en común": "26", "PDOP": "1.43554",
                "N Promedios": "5", "InicioTiempo Loc": "08:44.0",
                "FinTiempo Loc": "08:48.0", "InicioUTC": "08:44.0", "FinUTC": "08:48.0",
                "Base B": "04°36′58.90211″", "Base L": "-74°21′08.62095″",
                "H Base(Centro Fase)": "1502.14518", "Estación": "0",
            },
        )
        path = self._write_csv([base_row, rover_row])
        hf = hitarget_parser.parse_hitarget_csv(path)
        self.assertEqual(hf.n_points, 2)

        base = hf.points[0]
        self.assertIsNone(base.base_lat)  # la propia base no reporta una base de referencia
        self.assertIsNone(base.base_station_name)

        rover = hf.points[1]
        self.assertEqual(rover.n_sats, 29)
        self.assertAlmostEqual(rover.pdop, 1.43554, places=5)
        self.assertEqual(rover.n_epochs, 5.0)
        self.assertAlmostEqual(rover.occupation_seconds, 4.0, places=3)
        self.assertEqual(rover.base_station_name, "GPS01")
        self.assertIsNotNone(rover.base_baseline_m)
        self.assertGreater(rover.base_baseline_m, 0.0)
        self.assertLess(rover.base_baseline_m, 5000.0)  # línea base RTK típica, no miles de km

    def test_zero_base_coordinates_treated_as_no_base(self):
        # "00°00'00.00000\"" en Base B/Base L (como en la fila is_base
        # real, o un receptor sin corrección RTK/base) no debe
        # interpretarse como una base real en (0,0).
        row = _hitarget_row(
            "1", "SOLO", "04°36′34.19556″", "-74°21′18.28800″", "1490.48473",
            **{"Base B": "00°00′00.00000″", "Base L": "00°00′00.00000″"},
        )
        path = self._write_csv([row])
        hf = hitarget_parser.parse_hitarget_csv(path)
        p = hf.points[0]
        self.assertIsNone(p.base_lat)
        self.assertIsNone(p.base_lon)
        self.assertIsNone(p.base_baseline_m)
        self.assertIsNone(p.base_station_name)

    def test_occupation_seconds_none_when_times_missing_or_invalid(self):
        row = _hitarget_row(
            "1", "SOLO", "04°36′34.19556″", "-74°21′18.28800″", "1490.48473",
        )
        path = self._write_csv([row])
        hf = hitarget_parser.parse_hitarget_csv(path)
        self.assertIsNone(hf.points[0].occupation_seconds)

    def test_duplicated_names_warning(self):
        rows = [
            _hitarget_row("1", "P1", "04°36′58.90211″", "-74°21′08.62095″", "1500.0"),
            _hitarget_row("2", "P1", "04°36′34.19556″", "-74°21′18.28800″", "1490.0"),
        ]
        path = self._write_csv(rows)
        hf = hitarget_parser.parse_hitarget_csv(path)
        self.assertEqual(hf.n_points, 2)
        self.assertEqual(hf.duplicated_names(), {"P1": 2})
        self.assertTrue(any("P1" in w for w in hf.warnings))

    def test_invalid_dms_row_skipped_with_warning(self):
        rows = [
            _hitarget_row("1", "OK1", "04°36′58.90211″", "-74°21′08.62095″", "1500.0"),
            _hitarget_row("2", "MALO", "no-es-dms", "-74°21′18.28800″", "1490.0"),
        ]
        path = self._write_csv(rows)
        hf = hitarget_parser.parse_hitarget_csv(path)
        self.assertEqual(hf.n_points, 1)
        self.assertEqual(hf.points[0].name, "OK1")
        self.assertTrue(any("MALO" in w for w in hf.warnings))

    def test_missing_required_column_raises(self):
        path = self._write_csv(
            [f"1,P1,0,0,0,04°36′58.90211″,-74°21′08.62095″,1500.0,1.8"],
            header="id,Nombre,N,E,Z,B,L,H,AntH",
        )
        with self.assertRaises(ValueError):
            hitarget_parser.parse_hitarget_csv(path)

    def test_real_sample_file_if_available(self):
        # Si el archivo de muestra real que subió el usuario está
        # presente en este entorno, lo usamos como prueba adicional de
        # extremo a extremo (no falla si no está: es sólo un bonus).
        candidatos = [
            p for p in [
                "/root/.claude/uploads/30a52047-bb27-555f-85a3-157bcdb0557a/f52014f2-La_Yerbabuena_csv_072810.csv",
            ] if os.path.exists(p)
        ]
        if not candidatos:
            self.skipTest("Archivo de muestra real de Hi-Target no disponible en este entorno.")
        hf = hitarget_parser.parse_hitarget_csv(candidatos[0])
        self.assertEqual(hf.n_points, 45)
        self.assertEqual(hf.warnings, [])
        self.assertEqual(sum(1 for p in hf.points if p.is_base), 2)


class TestHiTargetRawParser(unittest.TestCase):
    """Los bytes usados en `_RAW_HEADER`/`_RAW_REC_*` son copias
    literales (extraídas con `open(path, "rb").read()`, sin modificar un
    solo byte) del archivo real que subió el usuario ("GPS.raw", subido
    como .txt porque el entorno no aceptaba .raw): el encabezado
    completo de 86 bytes y cuatro de sus registros de 398 bytes, elegidos
    para cubrir un registro "RMV" (debe ignorarse), uno "HSD" de una
    ocupación de base ("GPS01"/set_base), uno "HSD" de un punto normal
    ("1"/"L cc") y uno "HSD" con un comentario de campo en vez del código
    de calidad habitual ("43"/"BM HOSPITAL"). Los valores esperados de
    latitud/longitud/altura se sacaron del CSV real de la MISMA sesión
    ("La_Yerbabuena_csv_072810.csv", confirmado por el usuario) -- ver el
    docstring de `hitarget_raw_parser.py` para el detalle completo de
    esa verificación cruzada."""

    def _write_raw(self, records):
        tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        tmp.write(_RAW_HEADER)
        for r in records:
            tmp.write(r)
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        return tmp.name

    def test_looks_like_hitarget_raw(self):
        data = _RAW_HEADER + _RAW_REC_HSD_GPS01
        self.assertTrue(hitarget_raw_parser.looks_like_hitarget_raw(data))
        self.assertFalse(hitarget_raw_parser.looks_like_hitarget_raw(data[:-1]))
        self.assertFalse(hitarget_raw_parser.looks_like_hitarget_raw(b"not a raw file"))
        self.assertFalse(hitarget_raw_parser.looks_like_hitarget_raw(b""))

    def test_rmv_record_is_skipped(self):
        path = self._write_raw([_RAW_REC_RMV_BASE])
        hf = hitarget_raw_parser.parse_hitarget_raw(path)
        self.assertEqual(hf.n_points, 0)

    def test_hsd_base_occupation(self):
        path = self._write_raw([_RAW_REC_RMV_BASE, _RAW_REC_HSD_GPS01])
        hf = hitarget_raw_parser.parse_hitarget_raw(path)
        self.assertEqual(hf.n_points, 1)  # el RMV se ignora
        p = hf.points[0]
        self.assertEqual(p.name, "GPS01")
        self.assertEqual(p.desc, "set_base")
        self.assertTrue(p.is_base)
        self.assertAlmostEqual(p.lat, hitarget_parser.parse_dms(" 04°36′58.90211″"), places=6)
        self.assertAlmostEqual(p.lon, hitarget_parser.parse_dms(" -74°21′08.62095″"), places=6)
        self.assertAlmostEqual(p.height, 1500.30934, places=3)
        self.assertIsNone(p.ant_height)  # ver docstring: el .raw no la trae

    def test_hsd_rover_point_with_baseline_to_nearest_base(self):
        path = self._write_raw([_RAW_REC_HSD_GPS01, _RAW_REC_HSD_PT1])
        hf = hitarget_raw_parser.parse_hitarget_raw(path)
        self.assertEqual(hf.n_points, 2)
        p = next(pt for pt in hf.points if pt.name == "1")
        self.assertEqual(p.desc, "L cc")
        self.assertFalse(p.is_base)
        self.assertAlmostEqual(p.lat, hitarget_parser.parse_dms(" 04°36′57.39156″"), places=6)
        self.assertAlmostEqual(p.lon, hitarget_parser.parse_dms(" -74°21′09.76790″"), places=6)
        self.assertAlmostEqual(p.height, 1490.48473, places=3)
        # Emparejado con la ocupación de base GPS01 del mismo archivo
        # (única base presente en este mini-archivo de prueba).
        self.assertEqual(p.base_station_name, "GPS01")
        self.assertIsNotNone(p.base_baseline_m)
        self.assertLess(p.base_baseline_m, 200.0)  # levantamiento pequeño, no unos km

    def test_hsd_point_with_field_comment_instead_of_quality_code(self):
        path = self._write_raw([_RAW_REC_HSD_GPS01, _RAW_REC_HSD_PT43])
        hf = hitarget_raw_parser.parse_hitarget_raw(path)
        p = next(pt for pt in hf.points if pt.name == "43")
        self.assertEqual(p.desc, "BM HOSPITAL")
        self.assertFalse(p.is_base)
        self.assertAlmostEqual(p.lat, hitarget_parser.parse_dms(" 04°35′20.26996″"), places=6)
        self.assertAlmostEqual(p.lon, hitarget_parser.parse_dms(" -73°54′21.31105″"), places=6)
        self.assertAlmostEqual(p.height, 1492.67259, places=3)

    def test_not_a_raw_file_raises(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        tmp.write(b"esto no es un .raw de Hi-Target")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        with self.assertRaises(ValueError):
            hitarget_raw_parser.parse_hitarget_raw(tmp.name)

    def test_real_sample_file_if_available(self):
        # Igual que en TestHiTargetParser: si el archivo de muestra real
        # está presente en este entorno, se usa como prueba adicional de
        # extremo a extremo (no falla si no está).
        candidatos = [
            p for p in [
                "/root/.claude/uploads/30a52047-bb27-555f-85a3-157bcdb0557a/114446c4-GPS.raw.txt",
            ] if os.path.exists(p)
        ]
        if not candidatos:
            self.skipTest("Archivo de muestra real .raw de Hi-Target no disponible en este entorno.")
        hf = hitarget_raw_parser.parse_hitarget_raw(candidatos[0])
        # 43 puntos de rover + 2 ocupaciones de base (GPS01/GPS01_1) --
        # los registros "RMV" duplicados (Base/BASE/"1"/"2") NO cuentan,
        # exactamente los mismos 45 puntos únicos que trae el CSV real de
        # esta misma sesión (ver TestHiTargetParser.test_real_sample_file_if_available).
        self.assertEqual(hf.n_points, 45)
        self.assertEqual(sum(1 for p in hf.points if p.is_base), 2)
        self.assertTrue(all(p.ant_height is None for p in hf.points))
        nombres = {p.name for p in hf.points}
        self.assertIn("31 (25cm oriente)", nombres)
        self.assertIn("BM HOSPITAL", {p.desc for p in hf.points})


class TestChcnavParser(unittest.TestCase):
    """Todas las líneas usadas en estas pruebas son copias literales del
    archivo real aportado por el usuario (`02082025JV.rw5`, CHCNav
    LandStar), salvo donde se indica lo contrario (advertencias que ese
    archivo en particular no dispara, ej. localización/duplicados,
    construidas con snippets mínimos que reutilizan valores reales de
    coordenadas para no inventar el formato, sólo el escenario)."""

    def test_looks_like_rw5(self):
        texto_real = "\r\n".join([
            "JB,NM02082025JV,DT08-02-2025,TM08:50:18",
            "MO,AD0,UN1.0,SF1.00000000,EC0,EO0.0,AU0",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
        ])
        self.assertTrue(chcnav_parser.looks_like_rw5(texto_real))
        self.assertFalse(chcnav_parser.looks_like_rw5(SAMPLE_DC))
        self.assertFalse(chcnav_parser.looks_like_rw5(HITARGET_HEADER + "\n"))
        self.assertFalse(chcnav_parser.looks_like_rw5(""))

    def test_split_rw5_record_suffix_as_own_token(self):
        # Línea real 80: sufijo como su propio token separado por coma.
        record_code, fields, suffix = chcnav_parser._split_rw5_record(
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD"
        )
        self.assertEqual(record_code, "GPS")
        self.assertEqual(fields["PN"], "200")
        self.assertAlmostEqual(float(fields["LA"]), 10.162030337814702, places=9)
        self.assertAlmostEqual(float(fields["LN"]), -75.32709828115034, places=9)
        self.assertAlmostEqual(float(fields["EL"]), 13.575629611192722, places=9)
        self.assertEqual(suffix, "LD")

    def test_split_rw5_record_suffix_appended_without_comma(self):
        # Línea real 22 (registro GS de una base): el sufijo "--BASE"
        # viene pegado sin coma al valor del campo EL anterior.
        record_code, fields, suffix = chcnav_parser._split_rw5_record(
            "GS,PN,N2681835.390205027,E4745132.846943585,EL15.567857143469155--BASE"
        )
        self.assertEqual(record_code, "GS")
        self.assertEqual(fields["PN"], "")
        self.assertAlmostEqual(float(fields["EL"]), 15.567857143469155, places=9)
        self.assertEqual(suffix, "BASE")

    def test_split_rw5_record_trailing_empty_suffix_token_ignored(self):
        # Línea real 79: BP de la ocupación del rover, termina en ",--"
        # (token de sufijo vacío) -- no debe convertirse en un sufijo
        # con texto "".
        record_code, fields, suffix = chcnav_parser._split_rw5_record(
            "BP,,LA10.161984196709469,LN-75.32701699006014,EL15.239372084848583,"
            "AG0.0,PA0.0,ATAPC,SRROVER,--"
        )
        self.assertEqual(record_code, "BP")
        self.assertIsNone(suffix)
        self.assertEqual(fields["AT"], "APC")
        self.assertEqual(fields["SR"], "ROVER")

    def test_split_rw5_record_returns_none_for_plain_header_line(self):
        # Líneas reales del encabezado sin estructura de comas.
        self.assertIsNone(chcnav_parser._split_rw5_record("User Defined:ORIGEN NACIONAL"))
        self.assertIsNone(chcnav_parser._split_rw5_record("WGS84/32 CM -73.0N"))

    def test_gps_point_with_full_quality_block(self):
        # Líneas reales 80-101 completas (punto PN200, con el bloque de
        # calidad completo: Valid Readings, estadísticas de grilla local
        # ignoradas, la línea STATUS y DT/TM finales).
        texto = "\r\n".join([
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
            "--GS,PN200,N 2681840.8278161627,E 4745123.686076916,EL13.575632946765422,--LD",
            "--Valid Readings: 5 of 5",
            "--Fixed Readings: 5 of 5",
            "--Nor Min: 2681840.8257 MAX: 2681840.8324",
            "--Eas Min: 4745123.6844 MAX: 4745123.6878",
            "--Elv Min: 13.5632 MAX: 13.5840",
            "--Nor Avg: 2681840.8278 SD: 0.0024",
            "--Eas Avg: 4745123.6861 SD: 0.0014",
            "--Elv Avg: 13.5756 SD: 0.0078",
            "--NRMS Avg: 0.0079 SD: 0.0002 MIN: 0.0076 MAX: 0.0081",
            "--ERMS Avg: 0.0074 SD: 0.0002 MIN: 0.0072 MAX: 0.0077",
            "--HSDV Avg: 0.0108 SD: 0.0002 MIN: 0.0104 MAX: 0.0111",
            "--VSDV Avg: 0.0219 SD: 0.0005 MIN: 0.0210 MAX: 0.0225",
            "--HDOP Avg: 0.7051 MIN: 0.7051 MAX: 0.7051",
            "--VDOP Avg: 1.4075 MIN: 1.4074 MAX: 1.4075",
            "--PDOP Avg: 1.5742 MIN: 1.5741 MAX: 1.5743",
            "--AGE Avg: 1.0000 MIN: 1.0000 MAX: 1.0000",
            "--Number of Satellites Avg: 14 MIN: 14 MAX: 14",
            "--HSDV:0.011, VSDV:0.022, STATUS:FIXED, SATS:25, AGE:1.0, PDOP:1.574, "
            "HDOP:0.705, VDOP:1.407, TDOP:1.465, GDOP:2.150, NSDV:0.008, ESDV:0.007",
            "--DT08-02-2025",
            "--TM09:30:53",
            "GPS,PN201,LA10.16124299349628,LN-75.32749458393123,EL12.013189334705835,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 2)
        p = cf.points[0]
        self.assertEqual(p.name, "200")
        self.assertAlmostEqual(p.lat, 10.162030337814702, places=9)
        self.assertAlmostEqual(p.lon, -75.32709828115034, places=9)
        self.assertAlmostEqual(p.height, 13.575629611192722, places=9)
        self.assertEqual(p.tipo, "LD")
        self.assertEqual(p.status, "FIXED")
        self.assertEqual(p.n_sats, 25)
        self.assertAlmostEqual(p.pdop, 1.574, places=3)
        self.assertAlmostEqual(p.hdop, 0.705, places=3)
        self.assertAlmostEqual(p.vdop, 1.407, places=3)
        self.assertEqual(p.n_epochs, 5)
        self.assertEqual(p.date_text, "08-02-2025")
        self.assertEqual(p.time_text, "09:30:53")
        self.assertEqual(cf.warnings, [])

    def test_gps_point_without_quality_block_leaves_fields_none(self):
        # Líneas reales 997-999: PN241 sólo trae el comentario "--GS"
        # (grilla local, ignorado) y ningún otro dato de calidad --
        # debe importarse igual, con los campos de calidad en None (no
        # es un error: 14 de los 55 puntos del archivo real son así).
        texto = "\r\n".join([
            "GPS,PN241,LA10.177239662332967,LN-75.34544663952626,EL60.126460726914026,--LD",
            "--GS,PN241,N 2683537.5721762213,E 4743125.1850750875,EL60.12646407095194,--LD",
            "GPS,PN242,LA10.178208897164538,LN-75.34446917659483,EL64.61830715029285,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 2)
        p = cf.points[0]
        self.assertEqual(p.name, "241")
        self.assertIsNone(p.status)
        self.assertIsNone(p.n_sats)
        self.assertIsNone(p.pdop)
        self.assertIsNone(p.hdop)
        self.assertIsNone(p.vdop)
        self.assertIsNone(p.n_epochs)
        self.assertIsNone(p.date_text)
        self.assertIsNone(p.time_text)

    def test_gps_point_with_surpad_avg_min_max_quality_block(self):
        # Líneas reales 16-36 de un archivo .rw5 de SurPad (`LASUIZA.rw5`,
        # aportado por el usuario): bloque de calidad SIN ninguna línea
        # "STATUS:" -- cada campo viene en su propia línea "Avg/Min/Max".
        # Debe reconocerse HDOP/VDOP/PDOP/Number of Satellites (del valor
        # "Avg" de cada uno) y "Valid Readings" para n_epochs, igual que
        # con el formato de CHCNav -- pero `status` debe quedar en None
        # (este formato no trae ningún dato de fijo/flotante).
        texto = "\r\n".join([
            "GPS,PN1,LA4.53297279,LN-74.18444174,EL2766.946500,--TN",
            "--GS,PN1,N 2098656.1966,E 4854543.5510,EL2765.1216,--TN",
            "--GT,PN1,SW2434,ST315561000,EW2434,ET315565000",
            "--DT09-02-2026",
            "--TM10:39:24",
            "--Valid Readings: 2 of 2",
            "--Fixed Readings: 2 of 2",
            "--Nor Min: 2098656.1958  Max: 2098656.1974",
            "--Eas Min: 4854543.5480  Max: 4854543.5540",
            "--Elv Min: 2765.1131  Max: 2765.1301",
            "--Nor Avg: 2098656.1966  SD: 0.0008",
            "--Eas Avg: 4854543.5510  SD: 0.0030",
            "--Elv Avg: 2765.1216  SD: 0.0085",
            "--NRMS Avg: 0.0110 SD: 0.0000 Min: 0.0110 Max: 0.0110",
            "--ERMS Avg: 0.0165 SD: 0.0005 Min: 0.0160 Max: 0.0170",
            "--HSDV Avg: 0.0198 SD: 0.0004 Min: 0.0194 Max: 0.0202",
            "--VSDV Avg: 0.0285 SD: 0.0005 Min: 0.0280 Max: 0.0290",
            "--HDOP Avg: 0.6000 Min: 0.6000 Max: 0.6000",
            "--VDOP Avg: 1.0000 Min: 1.0000 Max: 1.0000",
            "--PDOP Avg: 1.2000 Min: 1.2000 Max: 1.2000",
            "--AGE Avg: 1.0000 Min: 1.0000 Max: 1.0000",
            "--Number of Satellites Avg: 11 Min: 11 Max: 12",
            "GPS,PN2,LA4.53297803,LN-74.18443588,EL2767.109500,--TN",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="LASUIZA.rw5")
        self.assertEqual(cf.n_points, 2)
        p = cf.points[0]
        self.assertEqual(p.name, "1")
        self.assertIsNone(p.status)
        self.assertEqual(p.n_sats, 11)
        self.assertAlmostEqual(p.pdop, 1.2, places=4)
        self.assertAlmostEqual(p.hdop, 0.6, places=4)
        self.assertAlmostEqual(p.vdop, 1.0, places=4)
        self.assertEqual(p.n_epochs, 2)
        self.assertEqual(p.date_text, "09-02-2026")
        self.assertEqual(p.time_text, "10:39:24")

    def test_ls_hr_sets_antenna_height_for_following_gps_points(self):
        # v2.22.0: líneas reales 77-80 ('LS,HR2.1194' justo antes del BP
        # del rover y del primer GPS, PN200) más el siguiente GPS (línea
        # 102, PN201) sin ningún 'LS' de por medio -- ambos deben
        # heredar la misma altura de antena 2.1194 (ver la nota de
        # verificación matemática, HR = altura ingresada + offset SHMP
        # de la antena, en el docstring del módulo).
        texto = "\r\n".join([
            "--Entered Rover HR:2.0,H Vertical",
            "LS,HR2.1194",
            "BP,,LA10.161984196709469,LN-75.32701699006014,EL15.239372084848583,"
            "AG0.0,PA0.0,ATAPC,SRROVER,--",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
            "GPS,PN201,LA10.16124299349628,LN-75.32749458393123,EL12.013189334705835,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        # Desde que 'BP' pasó a capturarse como un punto is_base (para la
        # corrección de base RTK), este texto tiene 3 puntos: la base y
        # los 2 GPS -- el 'ant_height' sólo aplica a los GPS.
        self.assertEqual(cf.n_points, 3)
        gps_points = [p for p in cf.points if not p.is_base]
        self.assertEqual(len(gps_points), 2)
        for p in gps_points:
            self.assertAlmostEqual(p.ant_height, 2.1194, places=4)

    def test_ant_height_is_none_before_any_ls_record(self):
        # Un GPS sin ningún 'LS' previo en el archivo (o en el texto
        # analizado) debe quedar en None -- nunca inventado.
        texto = "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD"
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertIsNone(cf.points[0].ant_height)

    def test_ls_without_valid_hr_keeps_previous_antenna_height(self):
        # Un 'LS' con un campo 'HR' vacío o no numérico no debe borrar la
        # altura de antena ya detectada -- mejor conservar el último
        # valor válido que perderlo.
        texto = "\r\n".join([
            "LS,HR2.1194",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
            "LS,HR",
            "GPS,PN201,LA10.16124299349628,LN-75.32749458393123,EL12.013189334705835,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertAlmostEqual(cf.points[0].ant_height, 2.1194, places=4)
        self.assertAlmostEqual(cf.points[1].ant_height, 2.1194, places=4)

    def test_chkam_chkpm_suffixes_preserved_verbatim(self):
        # Líneas reales 1021-1024: par de puntos de chequeo (CHKAM/CHKPM)
        # -- el sufijo se guarda tal cual, sin traducir su significado.
        texto = "\r\n".join([
            "GPS,PN253,LA10.162453124542493,LN-75.32688946889526,EL13.650418561464129,--CHKAM",
            "--GS,PN253,N 2681887.426703714,E 4745146.903457276,EL13.65042189528644,--CHKAM",
            "GPS,PN254,LA10.162453222857446,LN-75.326889404453,EL13.641672971699187,--CHKPM",
            "--GS,PN254,N 2681887.4375273525,E 4745146.910596957,EL13.641676307855546,--CHKPM",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual([p.tipo for p in cf.points], ["CHKAM", "CHKPM"])

    def test_sp_record_skipped_with_warning(self):
        # Líneas reales 388-389 (puntos guardados sólo con grilla local).
        texto = "\r\n".join([
            "SP,1000,N2680704.2602,E4745287.4215,EL2.828,--LD",
            "SP,1001,N2680716.3037,E4745295.0241,EL2.8324,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 0)
        self.assertTrue(any("2 punto(s) 'SP' omitido" in w for w in cf.warnings))

    def test_gs_base_grid_record_skipped_silently(self):
        # Línea real 22 ("--GS" con la grilla local de la base, sufijo
        # "--BASE") -- se sigue excluyendo sin ninguna advertencia
        # (siempre se ignoró, ver el docstring del módulo); la base
        # misma (registro 'BP', línea 21) SÍ se captura desde que existe
        # la corrección de base RTK -- ver
        # `test_bp_record_captured_as_base_point`.
        texto = "\r\n".join([
            "BP,PN,LA10.161981772358489,LN-75.32701433161537,EL15.567853809032213",
            "GS,PN,N2681835.390205027,E4745132.846943585,EL15.567857143469155--BASE",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 1)
        self.assertTrue(cf.points[0].is_base)
        self.assertEqual(cf.warnings, [])

    def test_bp_record_captured_as_base_point(self):
        # Línea real 21: un 'BP' sin PN propio (sólo el código "PN"
        # suelto, sin valor) -- debe capturarse con is_base=True, un
        # nombre sintético "BASE1" (por ser el primero del archivo), y
        # sus LA/LN/EL tal cual (mismo formato de campos que un 'GPS').
        texto = "BP,PN,LA10.161981772358489,LN-75.32701433161537,EL15.567853809032213"
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 1)
        p = cf.points[0]
        self.assertTrue(p.is_base)
        self.assertEqual(p.name, "BASE1")
        self.assertAlmostEqual(p.lat, 10.161981772358489, places=9)
        self.assertAlmostEqual(p.lon, -75.32701433161537, places=9)
        self.assertAlmostEqual(p.height, 15.567853809032213, places=9)
        self.assertEqual(p.tipo, "BASE")

    def test_bp_record_with_extra_fields_still_parses(self):
        # Línea real 79: el 4to 'BP' del archivo de referencia, con
        # campos extra AG/PA/AT/SR que no se usan -- no debe fallar ni
        # ser ignorado por ellos.
        texto = (
            "BP,,LA10.161984196709469,LN-75.32701699006014,EL15.239372084848583,"
            "AG0.0,PA0.0,ATAPC,SRROVER,--"
        )
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 1)
        self.assertTrue(cf.points[0].is_base)
        self.assertEqual(cf.points[0].name, "BASE1")

    def test_gps_points_after_bp_get_base_baseline_and_name(self):
        # Un punto GPS que aparece DESPUÉS de un 'BP' en el archivo debe
        # asociarse a esa base (vigente hasta que otro 'BP' la cambie,
        # igual que 'ant_height'/'LS') -- uno ANTES de cualquier 'BP'
        # debe quedar sin base (None), no inventarse una.
        texto = "\r\n".join([
            "GPS,PN199,LA10.16,LN-75.32,EL13.0,--LD",
            "BP,PN,LA10.161984196709469,LN-75.32701699006014,EL15.239372084848583",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        by_name = {p.name: p for p in cf.points}
        self.assertIsNone(by_name["199"].base_baseline_m)
        self.assertIsNone(by_name["199"].base_station_name)
        self.assertEqual(by_name["200"].base_station_name, "BASE1")
        self.assertIsNotNone(by_name["200"].base_baseline_m)
        self.assertGreater(by_name["200"].base_baseline_m, 0.0)

    def test_multiple_bp_occupations_last_one_wins_by_order_not_distance(self):
        # Reproduce el caso real del archivo de referencia: varias
        # ocupaciones de base casi idénticas entre sí (aquí separadas a
        # propósito por más de lo real para que el resultado no dependa
        # de redondeos) -- el punto GPS debe asociarse con la ÚLTIMA
        # ocupación vista antes que él (BASE2), NUNCA con la más cercana
        # por distancia (que sería BASE1, deliberadamente puesta más
        # cerca del GPS que BASE2 para que la prueba falle si el código
        # volviera a usar distancia en vez de orden).
        texto = "\r\n".join([
            "BP,PN,LA10.1600000,LN-75.3200000,EL15.0",  # BASE1: muy cerca del GPS
            "BP,PN,LA10.2000000,LN-75.4000000,EL15.0",  # BASE2: lejos del GPS, pero la última vigente
            "GPS,PN200,LA10.1600010,LN-75.3200010,EL13.0,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        gps = next(p for p in cf.points if p.name == "200")
        self.assertEqual(gps.base_station_name, "BASE2")

    def test_localization_file_and_grid_adjustment_none_no_warning(self):
        # Líneas reales 6-8 del encabezado: ambos declarados "None".
        texto = "\r\n".join([
            "--Localization File:None",
            "--Geoid Separation:None",
            "--Grid Adjustment:None",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertIsNone(cf.localization_file)
        self.assertIsNone(cf.grid_adjustment)
        self.assertEqual(cf.warnings, [])

    def test_warns_when_localization_file_declared(self):
        # El archivo real no dispara esta rama (ver la prueba anterior);
        # se prueba con un nombre de calibración de ejemplo, manteniendo
        # las coordenadas del punto reales.
        texto = "\r\n".join([
            "--Localization File:CARTAGENA_CAL.cal",
            "--Grid Adjustment:None",
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.localization_file, "CARTAGENA_CAL.cal")
        self.assertTrue(any("CARTAGENA_CAL.cal" in w for w in cf.warnings))

    def test_duplicated_names_warning(self):
        # Dos registros GPS reales (PN200 y PN201) pero con el segundo
        # renombrado a "200" para forzar el duplicado.
        texto = "\r\n".join([
            "GPS,PN200,LA10.162030337814702,LN-75.32709828115034,EL13.575629611192722,--LD",
            "GPS,PN200,LA10.16124299349628,LN-75.32749458393123,EL12.013189334705835,--LD",
        ])
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 2)
        self.assertTrue(any("repetido" in w for w in cf.warnings))

    def test_gps_record_missing_fields_warns_and_is_skipped(self):
        texto = "GPS,PN200,LA10.162030337814702,--LD"  # sin LN ni EL
        cf = chcnav_parser.parse_rw5_text(texto, path="x.rw5")
        self.assertEqual(cf.n_points, 0)
        self.assertTrue(any("incompleto" in w for w in cf.warnings))

    def test_parse_rw5_file_rejects_non_rw5_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".rw5", delete=False) as f:
            f.write(SAMPLE_DC)
            path = f.name
        self.addCleanup(os.remove, path)
        with self.assertRaises(ValueError):
            chcnav_parser.parse_rw5_file(path)

    def test_parse_rw5_file_falls_back_to_cp1252_when_not_utf8(self):
        # Caso real reportado por el usuario: QGIS mostró "'utf-8' codec
        # can't decode byte 0xf3..." al importar un .rw5 real de SurPad
        # (`LASUIZA.rw5`) -- ese archivo trae el Status en español con
        # tilde ("Autónomo") guardado en Windows-1252/Latin-1 de un solo
        # byte (ó = 0xF3), no en UTF-8. `parse_rw5_file` debe leerlo
        # igual, sin que el usuario tenga que convertir el archivo a
        # mano, probando 'cp1252' cuando 'utf-8-sig' falla.
        texto = "\r\n".join([
            "JB,NMLASUIZA,DT09-02-2026,TM10:15:18",
            "MO,AD0,UN1,SF1.000000,EC0,EO0.0,AU0",
            "GPS,PN1,LA4.53297279,LN-74.18444174,EL2766.946500,--TN",
            "--HSDV:1.5248, VSDV:2.3230, STATUS:Autónomo, SATS:9, AGE:1.0, "
            "PDOP:2.1, HDOP:1.1, VDOP:1.8",
        ])
        with tempfile.NamedTemporaryFile(suffix=".rw5", delete=False) as f:
            f.write(texto.encode("cp1252"))
            path = f.name
        self.addCleanup(os.remove, path)
        cf = chcnav_parser.parse_rw5_file(path)
        self.assertEqual(cf.n_points, 1)
        self.assertEqual(cf.points[0].status, "Autónomo")
        self.assertEqual(cf.points[0].n_sats, 9)

    def test_real_sample_file_if_available(self):
        # Archivo real completo aportado por el usuario (55 puntos GPS,
        # 3 SP, 4 BP, cerca de Cartagena, Colombia) -- ver el docstring
        # de chcnav_parser.py para la verificación matemática contra
        # pyproj que confirmó la convención de LA/LN de este formato.
        candidatos = [
            p for p in [
                "/root/.claude/uploads/30a52047-bb27-555f-85a3-157bcdb0557a/743238bf-02082025JV.rw5",
            ] if os.path.exists(p)
        ]
        if not candidatos:
            self.skipTest("Archivo de muestra real de CHCNav no disponible en este entorno.")
        cf = chcnav_parser.parse_rw5_file(candidatos[0])
        # Desde que 'BP' se captura como punto is_base (corrección de
        # base RTK), el total pasa de 55 (sólo GPS) a 59 (55 GPS + 4 BP).
        self.assertEqual(cf.n_points, 59)
        self.assertIsNone(cf.localization_file)
        self.assertIsNone(cf.grid_adjustment)
        self.assertTrue(any("3 punto(s) 'SP' omitido" in w for w in cf.warnings))
        gps_points = [p for p in cf.points if not p.is_base]
        base_points = [p for p in cf.points if p.is_base]
        self.assertEqual(len(gps_points), 55)
        self.assertEqual(len(base_points), 4)
        self.assertEqual([p.name for p in base_points], ["BASE1", "BASE2", "BASE3", "BASE4"])
        self.assertEqual(len({p.name for p in gps_points}), 55)
        con_calidad = [p for p in gps_points if p.status is not None]
        self.assertEqual(len(con_calidad), 41)
        self.assertTrue(all(p.status == "FIXED" for p in con_calidad))
        # v2.22.0: los 55 puntos GPS comparten la única altura de antena
        # ('LS,HR2.1194') vigente desde la línea 78 hasta el final del
        # archivo (no vuelve a aparecer ningún otro 'LS').
        self.assertTrue(all(p.ant_height is not None for p in gps_points))
        self.assertTrue(all(abs(p.ant_height - 2.1194) < 1e-6 for p in gps_points))
        # Los 4 'BP' preceden al primer 'GPS' del archivo (línea 80):
        # BASE1/2/3 son reconfiguraciones/pruebas previas al inicio real
        # del levantamiento, así que sólo BASE4 (la última, línea 79)
        # queda vigente para los 55 puntos GPS -- ver el docstring del
        # módulo sobre por qué es por orden y no por distancia (las 4
        # posiciones difieren entre sí por menos de 1 m).
        self.assertTrue(all(p.base_station_name == "BASE4" for p in gps_points))
        self.assertTrue(all(p.base_baseline_m is not None and p.base_baseline_m > 0 for p in gps_points))
        self.assertTrue(all(p.base_baseline_m is None for p in base_points))


class TestI18n(unittest.TestCase):
    def test_all_keys_have_both_languages_non_empty(self):
        faltantes = []
        for key, entry in i18n.TR.items():
            for lang in ("es", "en"):
                if not entry.get(lang):
                    faltantes.append((key, lang))
        self.assertEqual(faltantes, [], f"Claves de traducción incompletas: {faltantes}")

    def test_t_formats_placeholders(self):
        texto = i18n.t("es", "msg_project_created_body", path="/tmp/x.sqlite", crs="EPSG:9377")
        self.assertIn("/tmp/x.sqlite", texto)
        self.assertIn("EPSG:9377", texto)
        texto_en = i18n.t("en", "msg_project_created_body", path="/tmp/x.sqlite", crs="EPSG:9377")
        self.assertIn("/tmp/x.sqlite", texto_en)
        self.assertNotEqual(texto, texto_en)

    def test_t_falls_back_to_key_when_missing(self):
        self.assertEqual(i18n.t("es", "clave_inexistente_xyz"), "clave_inexistente_xyz")

    def test_t_falls_back_to_default_lang_when_lang_missing(self):
        # Un idioma no soportado no debe reventar: cae a DEFAULT_LANG.
        texto = i18n.t("fr", "btn_close")
        self.assertEqual(texto, i18n.TR["btn_close"][i18n.DEFAULT_LANG])


# Extracto real y sin modificar de un archivo .qld (RP_QC_19-08-26_final.qld,
# sísmica Argentina, receptores en Patagonia): el encabezado completo más
# los primeros 2 puntos ('14011001'/'14011002'), byte por byte. El layout
# de este formato binario (sin documentación pública) se dedujo por
# ingeniería inversa contra este mismo archivo y se verificó
# matemáticamente: transformando la latitud/longitud de cada uno de sus
# 12191 puntos a Gauss-Krüger Faja 2 Argentina (WGS84), el resultado
# coincide con el Este/Norte que el propio archivo trae para ese punto
# con una diferencia menor a 1 mm -- ver qld_reader.py.
SAMPLE_QLD_BYTES = bytes.fromhex(
    "514c4439000000000000f03f417267656e74696e655f436f6f7264696e617465"
    "5f53797374656d73000000000000000000000000000000000000000000000000"
    "0000000000000000000000005a6f6e6520494900000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000005747533834000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000004d45544552530000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000031343031313030310000000000000000000000c0"
    "266943413333337385e555410000000000000000ffb87b4e9b3e43c059bd56a0"
    "921f51c035310000000000000000000000000000000000000000000000000000"
    "0000000031343031313030320000000000000000333333f32a69434100000020"
    "83e555410000000000000000a434c1099e3e43c0aa50110a911f51c035310000"
    "00000000000000000000000000000000000000000000000000000000"
)


class TestQldReader(unittest.TestCase):
    def test_looks_like_qld_checks_magic_bytes(self):
        with tempfile.NamedTemporaryFile(suffix=".qld", delete=False) as f:
            f.write(SAMPLE_QLD_BYTES)
            path = f.name
        try:
            self.assertTrue(qld_reader.looks_like_qld(path))
        finally:
            os.unlink(path)
        self.assertFalse(qld_reader.looks_like_qld(__file__))

    def test_parses_header_fields(self):
        qf = qld_reader.parse_qld_bytes(SAMPLE_QLD_BYTES)
        self.assertEqual(qf.coord_system_name, "Argentine_Coordinate_Systems")
        self.assertEqual(qf.zone_name, "Zone II")
        self.assertEqual(qf.datum, "WGS84")
        self.assertEqual(qf.units, "METERS")

    def test_parses_points_with_real_verified_values(self):
        # Valores EXACTOS del archivo real, ya verificados por separado
        # contra una transformación de coordenadas independiente (ver el
        # docstring de qld_reader.py) -- no inventados.
        qf = qld_reader.parse_qld_bytes(SAMPLE_QLD_BYTES)
        self.assertEqual(qf.n_points, 2)
        p0 = qf.points[0]
        self.assertEqual(p0.name, "14011001")
        self.assertEqual(p0.line_no, 0)
        self.assertAlmostEqual(p0.este, 2544205.5, places=1)
        self.assertAlmostEqual(p0.norte, 5740053.8, places=1)
        self.assertEqual(p0.z, 0.0)
        self.assertAlmostEqual(p0.lat, -38.489114580546804, places=9)
        self.assertAlmostEqual(p0.lon, -68.49332436056774, places=9)
        p1 = qf.points[1]
        self.assertEqual(p1.name, "14011002")
        self.assertEqual(p1.line_no, 1)

    def test_no_warnings_for_well_formed_sample(self):
        qf = qld_reader.parse_qld_bytes(SAMPLE_QLD_BYTES)
        self.assertEqual(qf.warnings, [])

    def test_warns_on_non_wgs84_datum(self):
        # Cambia el campo de datum (bytes 140:204) por otro texto, sin
        # tocar nada más -- debe advertir en vez de asumir en silencio
        # que las coordenadas siguen siendo WGS84.
        data = bytearray(SAMPLE_QLD_BYTES)
        datum_field = b"POSGAR94" + b"\x00" * (64 - len(b"POSGAR94"))
        data[140:204] = datum_field
        qf = qld_reader.parse_qld_bytes(bytes(data))
        self.assertTrue(any("POSGAR94" in w for w in qf.warnings))

    def test_rejects_file_without_magic_signature(self):
        with self.assertRaises(ValueError):
            qld_reader.parse_qld_bytes(b"NOTQLD" + b"\x00" * 300)

    def test_truncated_trailing_bytes_generate_warning(self):
        # Encabezado completo + un registro completo + 10 bytes sueltos
        # que no alcanzan para otro registro de 88 bytes.
        header_and_one_record = SAMPLE_QLD_BYTES[: 268 + 88]
        data = header_and_one_record + b"\x00" * 10
        qf = qld_reader.parse_qld_bytes(data)
        self.assertEqual(qf.n_points, 1)
        self.assertTrue(any("sobrantes" in w for w in qf.warnings))

    def test_duplicated_point_names_generate_warning(self):
        # Dos registros con el mismo nombre (se copia el segundo
        # registro real pero se le pone el nombre del primero).
        rec0 = SAMPLE_QLD_BYTES[268:268 + 88]
        rec1 = bytearray(SAMPLE_QLD_BYTES[268 + 88:268 + 176])
        rec1[0:16] = rec0[0:16]
        data = SAMPLE_QLD_BYTES[:268] + rec0 + bytes(rec1)
        qf = qld_reader.parse_qld_bytes(data)
        self.assertEqual(qf.n_points, 2)
        self.assertTrue(any("repetido" in w for w in qf.warnings))

    def test_real_sample_file_if_available(self):
        # El archivo real completo (12191 puntos) no vive en el
        # repositorio -- esta prueba sólo corre si está disponible en el
        # entorno (igual patrón que los demás "archivo real" de este
        # proyecto).
        candidatos = [
            os.path.join(os.path.dirname(__file__), "RP_QC_19-08-26_final.qld"),
            "/mnt/user-data/uploads/RP_QC_19-08-26_final.qld",
        ]
        path = next((p for p in candidatos if os.path.exists(p)), None)
        if path is None:
            self.skipTest("Archivo real RP_QC_19-08-26_final.qld no disponible en este entorno.")
        qf = qld_reader.parse_qld_file(path)
        self.assertEqual(qf.n_points, 12191)
        self.assertEqual(qf.warnings, [])
        nombres = {p.name for p in qf.points}
        self.assertEqual(len(nombres), 12191)


# Esquema mínimo pero fiel al real (mismos nombres/tipos de columna que
# `CARGILL.PD`, el archivo real de Stonex subido por el usuario --
# verificado leyendo su `sqlite_master` directamente) para poder armar
# bases de datos de prueba sintéticas sin depender del archivo real.
_STONEX_SCHEMA_SQL = """
CREATE TABLE Point ( ID INTEGER PRIMARY KEY, NAME CHAR, CODE CHAR, Latitude DOUBLE, Longitude DOUBLE, Altitude DOUBLE, North DOUBLE, East DOUBLE, Height DOUBLE, CoordinateType INTEGER, PointType INTEGER, DeleteSign INTEGER, GPSID CHAR, StartTime CHAR, EndTime CHAR);
CREATE TABLE GPSCoordinate (ID CHAR NOT NULL, Satellite_Locked INT, Satellite_Tracked INT, PDOP DOUBLE, HDOP DOUBLE, VDOP DOUBLE, Pos_State CHAR, LocalDate DATETIME, LocalTime DATETIME, UTCDate DATETIME, UTCTime DATETIME, DistancetoBase DOUBLE, InstrumentID CHAR, Antenna_AntennaHeight DOUBLE, Base_ID CHAR, Base_Latitude DOUBLE, Base_Longitude DOUBLE, Base_Altitude DOUBLE, Undulation DOUBLE);
CREATE TABLE CoordinateSystemDetail ([Title] CHAR,[Value] CHAR);
CREATE TABLE Antenna (ID CHAR NOT NULL, Type CHAR, H DOUBLE, R DOUBLE, HL1 DOUBLE, HL2 DOUBLE);
CREATE TABLE android_metadata (locale CHAR);
"""


class TestStonexParser(unittest.TestCase):
    """Las columnas usadas acá (`_STONEX_SCHEMA_SQL` arriba) son las
    mismas, con el mismo nombre y tipo, que trae `CARGILL.PD` (archivo
    real de Stonex subido por el usuario, 46 puntos válidos + 2
    marcados como eliminados) -- ver el docstring de `stonex_parser.py`
    para el detalle completo de la verificación contra ese archivo real
    (incluida la identidad `Point.Altitude` == `WGS84Altitude` -
    `Antenna_AntennaHeight`, confirmada en los 48 puntos del archivo)."""

    def _make_db(self, points, coord_system_name="MAGNA-SIRGAS / CTM12 - Origen Nacional"):
        tmp = tempfile.NamedTemporaryFile(suffix=".PD", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.executescript(_STONEX_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO Antenna (ID, Type, H, R, HL1, HL2) VALUES (?,?,?,?,?,?)",
            ("S8503119000077", "Stonex S850A", 0.049, 0.07, 0.0168, 0.0157),
        )
        conn.execute(
            "INSERT INTO CoordinateSystemDetail (Title, Value) VALUES (?,?)",
            ("CoordSystemName", coord_system_name),
        )
        for i, p in enumerate(points, start=1):
            gpsid = f"gps{i}"
            conn.execute(
                "INSERT INTO Point (ID, NAME, CODE, Latitude, Longitude, Altitude, "
                "DeleteSign, GPSID, StartTime, EndTime) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (i, p["name"], p.get("code", "LD"), p["lat"], p["lon"], p["height"],
                 p.get("delete_sign", 0), gpsid, p.get("start_time"), p.get("end_time")),
            )
            if not p.get("no_gps_row"):
                conn.execute(
                    "INSERT INTO GPSCoordinate (ID, Satellite_Locked, PDOP, HDOP, VDOP, "
                    "Pos_State, LocalDate, LocalTime, UTCDate, UTCTime, DistancetoBase, "
                    "InstrumentID, Antenna_AntennaHeight, Base_ID, Base_Latitude, "
                    "Base_Longitude, Base_Altitude, Undulation) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (gpsid, p.get("n_sats", 10), p.get("pdop", 1.0), p.get("hdop", 0.5),
                     p.get("vdop", 0.9), p.get("pos_state", "FIXED"),
                     p.get("local_date"), p.get("local_time"),
                     p.get("utc_date"), p.get("utc_time"),
                     p.get("gps_baseline_m", 20.0), "S8503119000077",
                     p.get("ant_height", 2.0), p.get("gps_base_station", "RTCM-Ref 0"),
                     p.get("base_lat", 10.161980782242969), p.get("base_lon", -75.32701219768245),
                     p.get("base_height", 12.343), 0.0),
                )
        conn.commit()
        conn.close()
        self.addCleanup(os.remove, tmp.name)
        return tmp.name

    def test_looks_like_stonex_db_true_for_matching_schema(self):
        path = self._make_db([{"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0}])
        self.assertTrue(stonex_parser.looks_like_stonex_db(path))

    def test_looks_like_stonex_db_false_for_non_sqlite_file(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".PD", delete=False)
        tmp.write(b"esto no es una base de datos SQLite")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        self.assertFalse(stonex_parser.looks_like_stonex_db(tmp.name))

    def test_looks_like_stonex_db_false_for_unrelated_sqlite_schema(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.execute("CREATE TABLE Foo (ID INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        self.addCleanup(os.remove, tmp.name)
        self.assertFalse(stonex_parser.looks_like_stonex_db(tmp.name))

    def test_parses_basic_point_with_quality_fields(self):
        path = self._make_db([{
            "name": "1", "code": "LD", "lat": 10.162185617637231, "lon": -75.32702635991954,
            "height": 11.01139852309674, "n_sats": 10, "pdop": 1.12, "hdop": 0.62, "vdop": 1.0,
            "pos_state": "FIXED", "ant_height": 2.0658, "gps_baseline_m": 22.7487,
            "gps_base_station": "RTCM-Ref 0",
            "start_time": "2025-08-02 09:29:48", "end_time": "2025-08-02 09:29:52",
            "local_date": "2025-08-02", "local_time": "09:29:52",
            "utc_date": "2025-08-02", "utc_time": "14:29:52",
        }])
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.n_points, 1)
        self.assertEqual(sf.warnings, [])
        p = sf.points[0]
        self.assertEqual(p.name, "1")
        self.assertEqual(p.code, "LD")
        self.assertAlmostEqual(p.lat, 10.162185617637231)
        self.assertAlmostEqual(p.height, 11.01139852309674)
        self.assertEqual(p.n_sats, 10)
        self.assertEqual(p.pos_state, "FIXED")
        self.assertAlmostEqual(p.ant_height, 2.0658)
        self.assertAlmostEqual(p.gps_baseline_m, 22.7487)
        self.assertEqual(p.gps_base_station, "RTCM-Ref 0")
        self.assertEqual(p.receiver_type, "Stonex S850A")
        self.assertEqual(p.receiver_sn, "S8503119000077")
        self.assertEqual(p.occupation_seconds, 4.0)
        self.assertEqual(p.survey_time_local, "2025-08-02 09:29:52")
        self.assertEqual(p.survey_time_gmt, "2025-08-02 14:29:52")
        self.assertFalse(p.is_base)

    def test_deleted_points_are_excluded_with_warning(self):
        path = self._make_db([
            {"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0},
            {"name": "13", "lat": 10.1, "lon": -75.1, "height": 11.0, "delete_sign": 1},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.n_points, 1)
        self.assertEqual(sf.points[0].name, "1")
        self.assertTrue(any("eliminados" in w for w in sf.warnings))

    def test_point_without_gps_row_is_excluded(self):
        path = self._make_db([
            {"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0},
            {"name": "2", "lat": 10.1, "lon": -75.1, "height": 11.0, "no_gps_row": True},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.n_points, 1)
        self.assertTrue(any("medición GNSS real" in w for w in sf.warnings))

    def test_duplicated_names_are_warned(self):
        path = self._make_db([
            {"name": "P1", "lat": 10.0, "lon": -75.0, "height": 10.0},
            {"name": "p1", "lat": 10.1, "lon": -75.1, "height": 11.0},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.n_points, 2)
        self.assertEqual(sf.duplicated_names(), ["P1"])
        self.assertTrue(any("repetidos" in w for w in sf.warnings))

    def test_base_lat_lon_height_are_parsed(self):
        path = self._make_db([{
            "name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0,
            "gps_base_station": "RTCM-Ref 0",
            "base_lat": 10.161980782242969, "base_lon": -75.32701219768245, "base_height": 12.343,
        }])
        sf = stonex_parser.parse_stonex_db(path)
        p = sf.points[0]
        self.assertAlmostEqual(p.base_lat, 10.161980782242969)
        self.assertAlmostEqual(p.base_lon, -75.32701219768245)
        self.assertAlmostEqual(p.base_height, 12.343)

    def test_unique_bases_collapses_repeated_references(self):
        # Los 46 puntos válidos del archivo real comparten la MISMA
        # referencia ("RTCM-Ref 0") -- unique_bases() debe devolver una
        # sola entrada, no una por punto.
        path = self._make_db([
            {"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0, "gps_base_station": "RTCM-Ref 0"},
            {"name": "2", "lat": 10.1, "lon": -75.1, "height": 11.0, "gps_base_station": "RTCM-Ref 0"},
            {"name": "3", "lat": 10.2, "lon": -75.2, "height": 12.0, "gps_base_station": "RTCM-Ref 0"},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        bases = sf.unique_bases()
        self.assertEqual(len(bases), 1)
        nombre, lat, lon, altura = bases[0]
        self.assertEqual(nombre, "RTCM-Ref 0")
        self.assertAlmostEqual(lat, 10.161980782242969)
        self.assertAlmostEqual(lon, -75.32701219768245)
        self.assertAlmostEqual(altura, 12.343)

    def test_unique_bases_distinguishes_different_references(self):
        path = self._make_db([
            {"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0,
             "gps_base_station": "RTCM-Ref 0", "base_lat": 10.1, "base_lon": -75.1, "base_height": 12.0},
            {"name": "2", "lat": 10.1, "lon": -75.1, "height": 11.0,
             "gps_base_station": "BASE-LOCAL", "base_lat": 10.2, "base_lon": -75.2, "base_height": 13.0},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        bases = sf.unique_bases()
        self.assertEqual(len(bases), 2)
        nombres = [b[0] for b in bases]
        self.assertEqual(nombres, ["RTCM-Ref 0", "BASE-LOCAL"])

    def test_unique_bases_skips_points_without_known_base(self):
        path = self._make_db([
            {"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0, "gps_base_station": ""},
        ])
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.unique_bases(), [])

    def test_coord_system_name_is_captured(self):
        path = self._make_db(
            [{"name": "1", "lat": 10.0, "lon": -75.0, "height": 10.0}],
            coord_system_name="MAGNA-SIRGAS / CTM12 - Origen Nacional",
        )
        sf = stonex_parser.parse_stonex_db(path)
        self.assertEqual(sf.coord_system_name, "MAGNA-SIRGAS / CTM12 - Origen Nacional")

    def test_real_sample_file_if_available(self):
        # El archivo real completo (48 puntos, 2 marcados como
        # eliminados) no vive en el repositorio -- esta prueba sólo
        # corre si está disponible en este entorno (mismo patrón que los
        # demás "archivo real" de este proyecto).
        candidatos = [
            p for p in [
                "/root/.claude/uploads/30a52047-bb27-555f-85a3-157bcdb0557a/c5ac1f6b-CARGILL.PD",
            ] if os.path.exists(p)
        ]
        if not candidatos:
            self.skipTest("Archivo de muestra real de Stonex no disponible en este entorno.")
        self.assertTrue(stonex_parser.looks_like_stonex_db(candidatos[0]))
        sf = stonex_parser.parse_stonex_db(candidatos[0])
        self.assertEqual(sf.n_points, 46)
        self.assertEqual(sf.coord_system_name, "MAGNA-SIRGAS / CTM12 - Origen Nacional")
        self.assertTrue(any("eliminados" in w for w in sf.warnings))
        # Todos los puntos reales traen satélites/PDOP y un Pos_State
        # real, sin excepción.
        self.assertTrue(all(p.n_sats is not None for p in sf.points))
        self.assertTrue(all(p.pos_state for p in sf.points))
        estados = {p.pos_state for p in sf.points}
        self.assertEqual(estados, {"FIXED", "FLOAT", "DIF3D"})
        # Point.Altitude ya tiene la altura de antena restada -- ver
        # docstring del módulo.
        self.assertAlmostEqual(sf.points[0].height, 10.5551980789572)
        # Los 46 puntos válidos comparten la misma referencia RTCM/NTRIP
        # -- confirmado leyendo el archivo real directo con sqlite3
        # (ronda 2.27.0, a partir del CSV que el usuario aportó junto
        # con esta base para poder corregirla).
        bases = sf.unique_bases()
        self.assertEqual(len(bases), 1)
        nombre, lat, lon, altura = bases[0]
        self.assertEqual(nombre, "RTCM-Ref 0")
        self.assertAlmostEqual(lat, 10.161980782242969)
        self.assertAlmostEqual(lon, -75.32701219768245)
        self.assertAlmostEqual(altura, 12.343)


if __name__ == "__main__":
    unittest.main()
