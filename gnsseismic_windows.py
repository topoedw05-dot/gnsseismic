# -*- coding: utf-8 -*-
"""
gnsseismic_windows.py
----------------------
Controlador principal del plugin (`GNSSeismicController`) y sus cinco
ventanas de sección (bilingüe ES/EN; el idioma se controla desde un
combo en el toolbar del plugin, ver `gnsseismic.py`). Cada sección era
una pestaña de un único diálogo hasta la v1.3.0 ("Gestor DC Topografía");
desde la v2.0.0 ("GNSSeismic") cada una es su propia ventana no modal,
abierta con un ícono del toolbar, para poder tener varias abiertas al
mismo tiempo:

  Proyecto        -> crear/abrir la base de datos SQLite del proyecto
                     (esquema POSTPLOT/PREPLOT/TableDescriptions/COMPARACION),
                     elegir el CRS de trabajo y, opcionalmente, cargar el
                     modelo de geoide del proyecto.
  Preplot         -> generar puntos de diseño sísmico: grilla 3D
  Sísmico            (origen + azimut + espaciamientos) o línea 2D
                     (entre dos puntos, o desde un punto + azimut +
                     longitud), y subirlos a la tabla PREPLOT.
  Importar        -> (antes "Importar .dc"; renombrada porque desde la
  datos de campo     v2.8.0 soporta más de una marca -- ver
                     "note_datos_campo") cargar uno o varios archivos
                     .dc de Trimble y/o CSV de Hi-Target (usando sus
                     coordenadas geográficas B/L/H), aplicarles
                     (opcionalmente) el geoide del proyecto, importarlos
                     a POSTPLOT y visualizarlos como capa de puntos.
  Comparar        -> comparar los puntos levantados contra puntos de
                     diseño, cuya fuente puede ser un CSV cargado por
                     el usuario O la tabla PREPLOT ya guardada en esta
                     misma base de datos; ver diferencias, crear capa
                     de comparación y subir el resultado a la BD.
  Base de Datos   -> ejecutar consultas SELECT sobre la base del
                     proyecto y exportar el resultado a Shapefile,
                     GeoPackage o SPS (SEG/Shell, .S01/.R01).

`GNSSeismicController` NO es una ventana en sí (hereda de QWidget pero
nunca se muestra): existe sólo para tener un `self` estable que sirva de
padre a los QFileDialog/QMessageBox de cada sección y para guardar todo
el estado compartido entre secciones (conexión a la base, geoide
cargado, idioma activo, etc.), exactamente igual que cuando todo esto
vivía en un único QDialog con pestañas. Cada sección sigue siendo un
método `_build_tab_*()` que arma y devuelve un QWidget (el nombre
"_build_tab_*" quedó igual por costumbre, aunque ya no arma una pestaña
sino el contenido de su propia ventana `_SectionWindow`).

Mecanismo de idioma: todas las cadenas visibles viven en `i18n.py`
(clave -> {"es":..., "en":...}). Los widgets "estáticos" (títulos,
etiquetas, botones) se registran con `self._reg(...)` al construirse;
`retranslate_ui()` recorre ese registro para volver a aplicar el texto
cuando cambia el idioma (`set_language()`, llamado desde el combo de
idioma del toolbar). Los widgets con contenido dinámico (resúmenes de
resultados, bitácoras) se generan en el idioma vigente en el momento de
la acción, pero no se retraducen retroactivamente si el usuario cambia
de idioma después (salvo `lbl_conteos` y `lbl_preplot_resumen`, que sí
se re-renderizan -- ver `_render_counts_label`/`_render_preplot_label`).
"""

import os
import csv
import functools
import inspect
import json
import math
import re
import sqlite3
import traceback
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QMetaType, QSettings, QTimer
from qgis.PyQt.QtGui import QColor, QBrush
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QWidget,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QPlainTextEdit, QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QGroupBox, QRadioButton, QButtonGroup, QAbstractItemView,
    QHeaderView, QStackedWidget, QInputDialog, QScrollArea, QFrame, QMenu, QSizePolicy, QToolButton, QStyle,
)

# QAction vive en QtWidgets en PyQt5 (QGIS 3) pero se movió a QtGui en
# PyQt6 (QGIS 4) -- se usa para las entradas del menú desplegable
# "Archivos de campo" (ver `_build_tab_importar`).
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsField, QgsFeature, QgsGeometry,
    QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorFileWriter, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsMarkerSymbol, QgsLineSymbol, QgsSingleSymbolRenderer, QgsWkbTypes, QgsApplication,
)

try:
    from qgis.gui import QgsProjectionSelectionWidget
except ImportError:  # por si acaso en builds muy antiguos
    QgsProjectionSelectionWidget = None

try:
    # Usada por "Factor de escala del proyecto" (Proyecto) para tomar la
    # coordenada de referencia con un clic en el canvas de QGIS -- ver
    # `_iniciar_click_mapa_factor_escala`.
    from qgis.gui import QgsMapToolEmitPoint
except ImportError:  # por si acaso en builds muy antiguos
    QgsMapToolEmitPoint = None

from . import db_schema
from .dc_parser import (
    parse_dc_file,
    receiver_arp_offset_m,
    receiver_arp_offset_known,
    resolve_receiver_arp_offset,
    receiver_arp_offset_known_for_file,
)
from . import hitarget_parser
from . import hitarget_raw_parser
from . import chcnav_parser
from . import surpad_parser
from . import sourcelink_parser
from . import inova_parser
from . import punto_nombre
from . import shared_project
from .tabla_fija import TablaColumnasFijas
from .ui_widgets import AcordeonSeccion, EtiquetaElidida, ListaCompacta, PestanasAltoActual, ToggleSwitch
from . import stonex_parser
from . import csv_matcher
from . import preplot_generator
from . import export_writers
from . import geoid_utils
from . import ggf_reader
from . import qld_reader
from . import i18n


def _escritura(silencioso=False):
    """Decorador para los métodos que ESCRIBEN en la base del proyecto:
    en un proyecto compartido abierto en SOLO LECTURA no se ejecutan (con
    `silencioso=True` salen sin avisar; para guardados automáticos) y, en
    uno donde esta ventana es el EDITOR, programan una publicación a la
    carpeta compartida al terminar. Fuera del modo compartido no hacen
    nada distinto. Descarta los argumentos que `clicked` etc. pasan de más
    (PyQt los entrega según la firma visible del método)."""
    def deco(fn):
        params = list(inspect.signature(fn).parameters.values())[1:]
        acepta_var = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
        max_pos = len([
            p for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ])

        @functools.wraps(fn)
        def envoltura(self, *args, **kwargs):
            if not acepta_var:
                args = args[:max_pos]
            sh = getattr(self, "_shared", None)
            if sh is not None and sh.mode == shared_project.MODE_VIEWER:
                if not silencioso:
                    QMessageBox.information(self, self.t("shared_ro_title"), self.t("shared_ro_blocked_body"))
                return None
            resultado = fn(self, *args, **kwargs)
            sh = getattr(self, "_shared", None)
            if sh is not None and sh.mode == shared_project.MODE_EDITOR:
                QTimer.singleShot(1500, self._publicar_si_cambio)
            return resultado
        return envoltura
    return deco


def _valor_enum(clase, nombre, subespacio=None):
    """Devuelve el valor de un enum de Qt soportando tanto la forma
    "escopada" que exige PyQt6/Qt6 (`clase.subespacio.nombre`, p.ej.
    `Qt.WidgetAttribute.WA_DeleteOnClose`) como la forma plana de PyQt5
    (`clase.nombre`, p.ej. `Qt.WA_DeleteOnClose`), usando `getattr()`
    en vez de escribir ninguna de las dos formas como un acceso
    literal `Clase.Miembro` en el código fuente -- el verificador
    "Qt6 Check" de plugins.qgis.org marca ese patrón apenas lo
    encuentra escrito así, aunque la forma plana sólo se use de
    respaldo bajo PyQt5 y nunca se ejecute bajo Qt6 (no bloquea la
    publicación -- es meramente informativo, confirmado oficialmente
    por la documentación de QGIS -- pero de todos modos conviene no
    dejar esa señal en rojo en la página pública del plugin; mismo
    patrón ya usado y confirmado funcionando en el plugin hermano
    recalculo_rtk)."""
    if subespacio is not None:
        sub = getattr(clase, subespacio, None)
        if sub is not None:
            valor = getattr(sub, nombre, None)
            if valor is not None:
                return valor
    return getattr(clase, nombre)


# Compatibilidad Qt5 (QGIS 3, PyQt5) / Qt6 (QGIS 4, PyQt6): ver
# `_valor_enum()` arriba.
FIELD_STRING = _valor_enum(QMetaType, "QString", "Type")
FIELD_DOUBLE = _valor_enum(QMetaType, "Double", "Type")
FIELD_INT = _valor_enum(QMetaType, "Int", "Type")

WA_DELETE_ON_CLOSE = _valor_enum(Qt, "WA_DeleteOnClose", "WidgetAttribute")

# Flags de ventana que le agregan a un QDialog los botones de
# minimizar/maximizar de la barra de título (por defecto un QDialog en
# Windows sólo trae el botón de cerrar) -- ver `_SectionWindow`.
WINDOW_MINIMIZE_HINT = _valor_enum(Qt, "WindowMinimizeButtonHint", "WindowType")
WINDOW_MAXIMIZE_HINT = _valor_enum(Qt, "WindowMaximizeButtonHint", "WindowType")
WINDOW_SYSTEM_MENU_HINT = _valor_enum(Qt, "WindowSystemMenuHint", "WindowType")

# QSizePolicy.Ignored -- usado para que un QGridLayout reparta el
# espacio horizontal en una proporción fija entre "Consulta SQL" y
# "Buscar / Buscar y reemplazar" en "Base de Datos" (ver
# `_build_tab_bd`), ignorando el ancho "preferido" de cada uno (que de
# otro modo le daría más espacio al lado con más botones en fila, aunque
# ambos tuvieran el mismo "stretch").
SIZE_POLICY_IGNORED = _valor_enum(QSizePolicy, "Ignored", "Policy")

# Flags/estados de QTableWidgetItem, usados por la tabla de
# previsualización de "Importar datos de campo" (casilla "Incluir" y
# celdas editables de Nombre/Altura de antena/Comentario).
ITEM_IS_EDITABLE = _valor_enum(Qt, "ItemIsEditable", "ItemFlag")
ITEM_IS_USER_CHECKABLE = _valor_enum(Qt, "ItemIsUserCheckable", "ItemFlag")
ITEM_IS_ENABLED = _valor_enum(Qt, "ItemIsEnabled", "ItemFlag")
ITEM_IS_SELECTABLE = _valor_enum(Qt, "ItemIsSelectable", "ItemFlag")
CHECK_STATE_CHECKED = _valor_enum(Qt, "Checked", "CheckState")
CHECK_STATE_UNCHECKED = _valor_enum(Qt, "Unchecked", "CheckState")

# Botones estándar de QMessageBox, usados por la confirmación de
# sobrescritura al crear un proyecto (ver `crear_proyecto`).
MSG_YES = _valor_enum(QMessageBox, "Yes", "StandardButton")
MSG_NO = _valor_enum(QMessageBox, "No", "StandardButton")
MSG_CANCEL = _valor_enum(QMessageBox, "Cancel", "StandardButton")

# "Rol" de un botón agregado a mano a un QMessageBox (usado por
# "Guardar consulta..." en la sección Base de Datos, que ofrece
# "Sobrescribir"/"Guardar como nueva" además del Cancelar estándar).
MSG_ROLE_ACTION = _valor_enum(QMessageBox, "ActionRole", "ButtonRole")
MSG_ROLE_REJECT = _valor_enum(QMessageBox, "RejectRole", "ButtonRole")

# Estilo del botón "Subir"/"Subir/Retirar" de "Importar datos de campo":
# verde mientras no se ha subido nada en este proyecto (acción segura de
# avance), rojo cuando ya hay una subida que se puede retirar (ver
# `_actualizar_boton_subir`).
# Botón "Subir" = acción principal (CTA) de "Importar datos de campo"
# (rediseño v2.63.0): ancho completo (lo da el layout), esquinas
# ligeramente redondeadas y color llamativo con buen contraste (blanco
# sobre #2e7d32 / #c62828, ratio > 5:1).
ESTILO_BTN_SUBIR_VERDE = (
    "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; font-size: 14px;"
    " border: none; border-radius: 6px; padding: 10px 16px; }"
    "QPushButton:hover { background-color: #388e3c; }"
    "QPushButton:pressed { background-color: #1b5e20; }"
    "QPushButton:disabled { background-color: #9e9e9e; color: #eeeeee; }"
)
ESTILO_BTN_SUBIR_ROJO = (
    "QPushButton { background-color: #c62828; color: white; font-weight: bold; font-size: 14px;"
    " border: none; border-radius: 6px; padding: 10px 16px; }"
    "QPushButton:hover { background-color: #d32f2f; }"
    "QPushButton:pressed { background-color: #8e0000; }"
    "QPushButton:disabled { background-color: #9e9e9e; color: #eeeeee; }"
)

# Rediseño v2.63.0 de "Importar datos de campo": aspecto de tarjeta (borde
# fino redondeado con colores de la PALETA del tema, así sirve en claro y
# en oscuro), botones iconográficos, barra de acciones compacta y rótulos
# tenues.
ESTILO_TARJETAS = (
    "QGroupBox#card { border: 1px solid palette(mid); border-radius: 8px; margin-top: 12px; padding-top: 10px; }"
    "QGroupBox#card::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 5px; }"
)
ESTILO_BTN_ICONO = (
    "QPushButton { font-size: 16px; font-weight: bold; padding: 2px 8px; border: 1px solid palette(mid);"
    " border-radius: 5px; }"
    "QPushButton:hover { background: palette(midlight); }"
    "QPushButton::menu-indicator { subcontrol-position: right center; subcontrol-origin: padding; right: 4px; }"
)
ESTILO_BTN_BARRA = (
    "QToolButton { padding: 3px 9px; border: 1px solid palette(mid); border-radius: 4px; }"
    "QToolButton:hover { background: palette(midlight); }"
)
ESTILO_BTN_ENLACE = (
    "QPushButton { border: none; text-align: left; padding: 2px 0px; color: palette(link); }"
    "QPushButton:hover { text-decoration: underline; }"
)
ESTILO_ROTULO_TENUE = "color: gray;"
ESTILO_SUBTITULO = "font-weight: bold;"
# Botón de acción principal "Aplicar configuración" (pestaña Proyecto).
ESTILO_BTN_PRIMARIO = (
    "QPushButton { background-color: #1565c0; color: white; font-weight: bold; border: none;"
    " border-radius: 6px; padding: 7px 18px; }"
    "QPushButton:hover { background-color: #1976d2; }"
    "QPushButton:pressed { background-color: #0d47a1; }"
    "QPushButton:disabled { background-color: #9e9e9e; color: #eeeeee; }"
)


def _estilo_badge(color_hex):
    """Estilo de un "badge" (píldora de color) de la pestaña Proyecto:
    borde y fondo translúcido del color dado, texto del color del tema
    (legible en claro y en oscuro)."""
    c = color_hex.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return (
        f"QLabel {{ border: 1px solid {color_hex}; border-radius: 10px; padding: 2px 10px;"
        f" background-color: rgba({r}, {g}, {b}, 45); font-weight: bold; }}"
    )

# Forma del marco de un QFrame/QScrollArea (usado para que el
# contenido de cada `_SectionWindow` vaya dentro de un scroll area sin
# borde visible).
FRAME_SHAPE_NONE = _valor_enum(QFrame, "NoFrame", "Shape")

# Colores de fondo para la tabla de previsualización de "Importar datos de campo"
# (además de COLOR_DENTRO/COLOR_FUERA, definidos más abajo).
COLOR_YA_SUBIDO = QColor(225, 225, 225)

# Fondo de una celda de `tbl_query` con un cambio de edición todavía sin
# guardar (ver `_on_query_cell_changed`/`guardar_cambios_consulta`, v2.21.0).
COLOR_QUERY_EDITADO = QColor(255, 243, 205)

COLOR_KI = "#1f78b4"
COLOR_SO = "#e31a1c"
COLOR_DENTRO = QColor(200, 255, 200)
COLOR_FUERA = QColor(255, 200, 200)
# Tabla de "Comparar": tintes más suaves + texto oscuro fijo (legibles en tema oscuro).
COLOR_CMP_DENTRO = QColor(214, 240, 214)
COLOR_CMP_FUERA = QColor(250, 214, 214)
COLOR_CMP_TEXTO = QColor(33, 33, 33)
COMPARAR_COL_DIST = 5  # "Dist. 2D"
COMPARAR_COL_TOL = 6   # "¿Tolerancia?"
# Fondo de la celda "Nombre" de un punto marcado `ambiguous_reoccupation`
# (reocupación ambigua, prefijo "?" -- ver `DCPoint.ambiguous_reoccupation`)
# o todavía `deleted` en su estado final (prefijo "D") -- pedido del
# usuario: resaltarlos igual que ya se resaltan los puntos fuera de
# tolerancia (`COLOR_FUERA`), para que no pasen desapercibidos en la
# previsualización aunque de todos modos se muestren (no se descartan).
COLOR_AMBIGUO = QColor(255, 235, 160)

# Fondo del ENCABEZADO VERTICAL (número de fila) de `tbl_import_preview`
# para las filas que cumplen el filtro/consulta SQL de la previsualización
# (ver `_resaltar_filas_filtro_preview`, pedido explícito del usuario:
# "querys para mirar situaciones"). A propósito NO se usa el fondo de las
# celdas -- ahí ya viven COLOR_AMBIGUO/COLOR_YA_SUBIDO (celda Nombre) y
# COLOR_DENTRO/COLOR_FUERA (celda Estado); resaltar el encabezado de fila
# en vez de una celda evita pisar cualquiera de esos colores.
COLOR_FILTRO_PREVIEW = QColor(180, 210, 255)

# Fondo de TODA la fila (todas sus columnas, a propósito por encima de
# cualquier otro color de celda de esa fila -- Nombre/Estado/etc.) de un
# punto cuyo nombre ya existe en POSTPLOT (ver
# `verificar_duplicados_bd`/`_resaltar_filas_duplicadas_bd`, pedido
# explícito del usuario). Rojo más saturado que COLOR_FUERA (fuera de
# tolerancia) para no confundir ambas señales: un duplicado real contra
# la base ya guardada es un aviso más serio.
COLOR_DUPLICADO_BD = QColor(255, 120, 120)

# Colores/etiquetas de la capa de puntos creada al subir "Importar datos de
# campo" (`_crear_capa_puntos_dc`/`_aplicar_estilo_por_tipo`): KI/SO son los
# dos tipos de registro de punto de campo de un .dc de Trimble (BASE, su
# ocupación de base física cuando el archivo trae una, se agregó en la ronda
# de soporte a base RTK física -- ver `dc_parser.BASE_CODES` -- reutilizando
# la misma clave BASE ya usada más abajo para Hi-Target/CHCNav); FIX/FLOAT/
# CALC/BASE/OTRO son los tipos derivados del estado de una fila de Hi-Target
# -- ver `_hitarget_tipo_code`; LD/CT/CHKAM/CHKPM son los códigos de sufijo tal
# cual los trae un .rw5 de CHCNav (ver `chcnav_parser.py` -- no se traduce
# su significado exacto, sólo se preservan y colorean); CHK es el código
# de punto de chequeo tal cual lo trae la base de Stonex (ver
# `stonex_parser.py`/`_stonex_tipo_code`). Futuras marcas pueden agregar
# más entradas aquí; ver la nota junto a `_build_tab_importar` sobre cómo
# agregar una marca nueva de punta a punta.
#
# IMPORTANTE (ronda 2.26.0): las etiquetas de leyenda de LD/CT/CHKAM/
# CHKPM ya NO llevan el nombre de la marca por delante (antes decían
# "CHCNav: LD", etc.) -- se quitó ese prefijo porque, al agregar Stonex,
# su archivo real trajo el MISMO código "LD" que ya usaba CHCNav (ambos
# son códigos cortos de campo que bien podrían significar lo mismo
# ["Levantamiento de Detalle"] en cualquier marca, o no -- el plugin
# nunca lo confirma, sólo preserva el texto), así que un punto Stonex
# con código "LD" heredaría el mismo color Y la misma clave de i18n que
# un "LD" de CHCNav; dejar la etiqueta con el nombre de marca fijo
# habría mostrado "CHCNav: LD" para un punto que en realidad viene de
# Stonex. Cualquier código nuevo que otra marca reutilice en el futuro
# queda cubierto por la misma razón -- por eso la leyenda de estos
# códigos es siempre el código tal cual, sin nombre de marca.
#
# IMPORTANTE (ronda siguiente a la v2.62.6): el mismo criterio de arriba
# se le había quedado sin aplicar a "BASE" -- su etiqueta decía
# "Hi-Target: Base" a pesar de que, a diferencia de FIX/FLOAT/CALC (esos
# sí exclusivos de Hi-Target, derivados de su "Estado"), el tipo "BASE"
# lo produce CUALQUIER marca con ocupación de base RTK: Hi-Target, DC,
# CHCNav/SurPad (registro 'BP' o sufijo "--BASE") y Stonex. El usuario lo
# reportó al ver "Hi-Target: Base" en la previsualización de un archivo
# de CHCNav/SurPad (sin ningún dato de Hi-Target de por medio) -- se
# corrigió la clave `legend_base` en i18n.py para que diga sólo "Base",
# sin nombre de marca, igual que LD/CT/CHKAM/CHKPM.
COLOR_POR_TIPO = {
    "KI": COLOR_KI,
    "SO": COLOR_SO,
    "FIX": "#33a02c",
    "FLOAT": "#ff7f00",
    "CALC": "#6a3d9a",
    "BASE": "#b15928",
    "LD": "#1f78b4",
    "CT": "#33a02c",
    "CHKAM": "#ff7f00",
    "CHKPM": "#6a3d9a",
    "CHK": "#e31a1c",
    "OTRO": "#999999",
}
LEGEND_KEY_POR_TIPO = {
    "KI": "legend_ki",
    "SO": "legend_so",
    "FIX": "legend_fix",
    "FLOAT": "legend_float",
    "CALC": "legend_calc",
    "BASE": "legend_base",
    "LD": "legend_ld",
    "CT": "legend_ct",
    "CHKAM": "legend_chkam",
    "CHKPM": "legend_chkpm",
    "CHK": "legend_chk",
    "OTRO": "legend_other",
}


def _transform_xy(x, y, src_crs: QgsCoordinateReferenceSystem, dst_crs: QgsCoordinateReferenceSystem, project: QgsProject):
    if src_crs == dst_crs:
        return x, y
    tr = QgsCoordinateTransform(src_crs, dst_crs, project)
    pt = tr.transform(QgsPointXY(x, y))
    return pt.x(), pt.y()


def _factor_escala_convergencia(lon_wgs84: float, lat_wgs84: float, working_crs: QgsCoordinateReferenceSystem):
    """Factor de escala (point scale factor) y convergencia meridiana
    (grid convergence) de la proyección `working_crs` en el punto
    (lon_wgs84, lat_wgs84), para rellenar las columnas "Factor de
    escala"/"Convergencia" de la previsualización de "Importar datos de
    campo" (v2.58.0 -- antes siempre quedaban en "-", ver el comentario
    que había junto al llamador).

    Investigación v2.58.0 (pedido explícito del usuario, que sospechaba
    que GPSeismic calcula sus coordenadas planas APLICANDO el factor de
    escala): se extrajeron con `mdb-export` dos .mdb reales del usuario
    que sí traen "Local Easting"/"Local Northing"/"Scale Factor"/
    "Convergence" pobladas (la mayoría de los .mdb de prueba sólo traen
    lat/lon WGS84 -- esas dos columnas recién se completan después de
    asignarle al proyecto, en GPSeismic, un "Local System" vía su
    utilidad de Geodetic Settings). Comparando esos valores reales
    contra cálculos independientes (pyproj) se confirmó:

    1) Las coordenadas planas de GPSeismic ("Local Easting"/"Local
       Northing") coinciden EXACTO con una proyección Gauss-Krüger
       estándar (Transversa de Mercator, k0=1) de la lat/lon WGS84, sin
       aplicar ningún factor de escala a la distancia ni a la
       coordenada -- la hipótesis del usuario no se confirma para este
       módulo. El factor de escala SÍ se aplica así (ground-to-grid)
       dentro de GPSeismic, pero en otro módulo (QuikCon, el que
       procesa poligonales con estación total/teodolito, no el que
       procesa puntos GNSS como esta pantalla -- ver `Disc0059.htm` del
       manual de QuikCon).
    2) "Scale Factor" y "Convergence" son, en cambio, exactamente el
       factor de escala puntual y la convergencia de meridiano
       ESTÁNDAR de esa misma proyección en ese punto -- valores
       puramente informativos (típicamente usados después, a mano o en
       QuikCon, para pasar de distancia de terreno a distancia de
       grilla), no algo que ya esté aplicado en "Local Easting"/"Local
       Northing". Por eso si se pueden calcular con pyproj sin tocar
       para nada el cálculo de Este/Norte que ya hace este plugin.
    3) Las "pequeñas diferencias" que el usuario notó en Este/Norte
       entre este plugin y GPSeismic no son por el factor de escala --
       son porque el .mdb de GPSeismic tiene registrado "Local Datum:
       WGS84" para ese proyecto, es decir GPSeismic NO aplicó ninguna
       transformación de datum (tomó la lat/lon WGS84 tal cual). Si el
       CRS de trabajo elegido en este plugin es, en cambio, un CRS
       argentino amarrado a un datum distinto de WGS84 "crudo" (p.ej.
       EPSG:5344, POSGAR 2007/Argentina 2 -- el propio ejemplo que ya
       usa el comentario de `_working_crs()` más arriba), QGIS sí hace
       una transformación de datum real (aunque chica) antes de
       proyectar, y ahí aparece la diferencia -- del orden de ~0.22 m
       Este / ~0.66 m Norte en el punto de prueba usado, consistente
       con la deriva acumulada entre POSGAR 2007 (época fija 2006) y
       WGS84 (realización actual) por el movimiento de la placa
       sudamericana. Con EPSG:22172/22182 (POSGAR 98/94, datums
       prácticamente coincidentes con WGS84) la diferencia es
       prácticamente nula. Esto es una decisión de qué CRS de trabajo
       elegir, no un error de cálculo de este plugin ni de GPSeismic.

    Usa `pyproj` (ya incluido en el entorno de Python de QGIS) a partir
    del WKT del CRS de trabajo. Si `working_crs` es geográfico (sin
    proyección, p.ej. EPSG:4326) o si algo falla (pyproj no disponible,
    CRS sin parámetros de proyección reconocidos por PROJ, etc.),
    devuelve (None, None) y el llamador debe mostrar "-" como antes de
    la v2.58.0 -- nunca debe romper la previsualización."""
    if working_crs is None or not working_crs.isValid() or working_crs.isGeographic():
        return None, None
    try:
        import pyproj
        crs_pp = pyproj.CRS.from_wkt(working_crs.toWkt())
        factors = pyproj.Proj(crs_pp).get_factors(lon_wgs84, lat_wgs84)
        return factors.meridional_scale, factors.meridian_convergence
    except Exception:
        return None, None


_RADIO_TERRESTRE_MEDIO_M = 6371000.0


def _factor_elevacion(altura_m: float, radio_m: float = _RADIO_TERRESTRE_MEDIO_M) -> float:
    """Factor de elevación (ground-to-grid) estándar de topografía:
    `R / (R + altura)`, con R el radio terrestre medio (6.371.000 m,
    misma aproximación de nivel esférico simple que usan la mayoría de
    las calculadoras comerciales de "combined scale factor" -- no hace
    falta el radio de curvatura exacto del elipsoide en ese punto para
    el nivel de precisión que necesita este cálculo). `altura_m` es la
    altura media del área de trabajo sobre el elipsoide (o la
    ortométrica -- la diferencia entre ambas, del orden de la
    ondulación del geoide, pesa muy poco frente al propio radio
    terrestre). Pedido explícito del usuario (v2.59.0) como base para un
    futuro módulo de Estación Total: a diferencia de un punto GNSS/RTK
    -- que no necesita esto, ver `_factor_escala_convergencia` -- una
    Estación Total mide una distancia real de terreno, que hay que
    multiplicar por el factor COMBINADO (éste × el de la proyección) "
    para obtener la distancia de grilla antes de calcular Este/Norte."""
    return radio_m / (radio_m + altura_m)


def _factor_combinado_proyecto(lon_wgs84: float, lat_wgs84: float, altura_m: float, working_crs: QgsCoordinateReferenceSystem):
    """Factor de escala combinado (terreno -> grilla) de un punto de
    referencia del proyecto -- junta `_factor_escala_convergencia`
    (factor de la proyección + convergencia) con `_factor_elevacion`
    (por la altura). Usado por el grupo "Factor de escala del proyecto"
    de la pestaña Proyecto (`guardar_factor_escala_proyecto`), no por
    ningún cálculo de coordenadas existente -- ver el docstring de
    `_factor_escala_convergencia` sobre por qué Este/Norte NO aplica
    esto. Devuelve (factor_proyeccion, convergencia, factor_elevacion,
    factor_combinado) o (None, None, None, None) si el CRS de trabajo es
    geográfico o pyproj no pudo calcular el factor de proyección."""
    factor_proyeccion, convergencia = _factor_escala_convergencia(lon_wgs84, lat_wgs84, working_crs)
    if factor_proyeccion is None:
        return None, None, None, None
    factor_elev = _factor_elevacion(altura_m)
    return factor_proyeccion, convergencia, factor_elev, factor_proyeccion * factor_elev


def _transform_extent(extent, src_crs: QgsCoordinateReferenceSystem, dst_crs: QgsCoordinateReferenceSystem, project: QgsProject):
    """Igual que `_transform_xy` pero para un `QgsRectangle` completo --
    usada por `GNSSeismicController._zoom_canvas_a_capa` para llevar la
    extensión de una capa (en su propio CRS) al CRS real del canvas de
    QGIS antes de centrar la vista en ella (ver esa función para el por
    qué)."""
    if src_crs == dst_crs or extent.isEmpty():
        return extent
    tr = QgsCoordinateTransform(src_crs, dst_crs, project)
    try:
        return tr.transformBoundingBox(extent)
    except Exception:
        # Si la transformación falla (p.ej. un CRS sin parámetros de
        # conversión conocidos hacia el otro), mejor centrar con la
        # extensión sin transformar que no centrar nada.
        return extent


def _format_dms(decimal_degrees: float) -> str:
    """Formatea un ángulo en grados decimales a grados/minutos/segundos
    con 5 decimales en los segundos (pedido del usuario en la v2.25.0
    para la columna de coordenadas geográficas de la previsualización de
    "Importar datos de campo"), con el MISMO estilo de símbolos °′″ y
    signo antepuesto (no N/S/E/W) que ya usa este proyecto para LEER una
    coordenada Hi-Target (ver `hitarget_parser._DMS_RE`/`parse_dms`, cuyo
    propio docstring trae ejemplos reales como " -74°21′08.62095″" --
    con 5 decimales igual que se pide acá). Sólo para MOSTRAR: nunca se
    vuelve a parsear con `parse_dms`."""
    sign = "-" if decimal_degrees < 0 else ""
    valor = abs(decimal_degrees)
    deg = int(valor)
    rem = (valor - deg) * 60.0
    minutos = int(rem)
    segundos = round((rem - minutos) * 60.0, 5)
    if segundos >= 60.0:
        segundos -= 60.0
        minutos += 1
    if minutos >= 60:
        minutos -= 60
        deg += 1
    return f"{sign}{deg}°{minutos:02d}′{segundos:08.5f}″"


def _track_bin_heuristic(name: str, line_digits: int):
    """Misma heurística que `DCPoint.track_bin` (separar los primeros
    `line_digits` dígitos del nombre como Línea/Track y el resto como
    Estaca/Bin, sólo si el nombre es puramente numérico), pero como
    función libre para poder aplicarla también a puntos que no vienen de
    un .dc (por ahora, Hi-Target)."""
    n = (name or "").strip()
    if line_digits <= 0 or not n.isdigit() or len(n) <= line_digits:
        return None, None
    return n[:line_digits], n[line_digits:]


def _normalize_track_key(value):
    """Normaliza un valor de Track (puede venir como int de la tabla
    PREPLOT, o como texto recortado del nombre del punto, ej. "0052"
    contra 52) para poder cruzarlos como clave de diccionario sin que
    el tipo o los ceros a la izquierda hagan fallar el match. `None`
    si no hay valor utilizable."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return str(int(float(s)))
    except (TypeError, ValueError):
        return s


def _fit_line_azimuth_deg(points_xy_ordered):
    """Ajusta el rumbo (azimut, grados 0-360 desde el norte) de una
    línea sísmica de preplot a partir de sus puntos (x=Este, y=Norte),
    ya ordenados de inicio a fin de línea (por Bin/Station_Value).

    Confirmado contra el manual oficial de GPSeismic (utilidad
    "Recalculate Offsets (crooked line)" de GPSQL.chm): el "Inline
    Azimuth" real de GPSeismic no sale del punto de campo, sino de un
    archivo CRK generado por QuikLoad con el azimut de cada tramo de la
    línea de PREPLOT -- es decir, un parámetro del DISEÑO de la malla,
    no algo calculable desde un solo punto GPS. Este plugin no tiene
    (todavía) un cargador de archivos CRK, así que en su lugar se
    calcula el mismo dato directamente desde la geometría de la propia
    tabla PREPLOT del proyecto (que ya tenemos cargada para el match
    contra PREPLOT), ajustando la MEJOR RECTA (mínimos cuadrados/PCA,
    no sólo el segmento extremo a extremo, para tolerar puntos con
    algo de ruido) a través de todos los puntos de esa línea/Track.

    Devuelve `None` si hay menos de 2 puntos o si todos coinciden
    (no se puede determinar una dirección).
    """
    n = len(points_xy_ordered)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points_xy_ordered) / n
    mean_y = sum(p[1] for p in points_xy_ordered) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in points_xy_ordered)
    syy = sum((p[1] - mean_y) ** 2 for p in points_xy_ordered)
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points_xy_ordered)
    if sxx == 0 and syy == 0:
        return None
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    u_e, u_n = math.cos(theta), math.sin(theta)
    dx_total = points_xy_ordered[-1][0] - points_xy_ordered[0][0]
    dy_total = points_xy_ordered[-1][1] - points_xy_ordered[0][1]
    if u_e * dx_total + u_n * dy_total < 0:
        u_e, u_n = -u_e, -u_n
    return math.degrees(math.atan2(u_e, u_n)) % 360


# -- Levantamiento 2D/3D y azimutes de línea fuente/receptora (pedido
# explícito del usuario: "en el modulo crear proyecto... hay que saber si el
# proyecto sera un 3d o un 2d, y si es un 3d, que pregunte los azimutes de
# las lineas fuentes y de la lineas receptoras"). Revisado contra el manual
# oficial de GPSeismic (projman/Creating.htm, sección "Entering Azimuths"/
# "Azimuth Mode" del propio "Project Manager"): un proyecto 3D define DOS
# azimutes fijos (línea fuente y línea receptora) y un "modo" para decidir
# cuál de los dos aplica a cada punto -- GPSeismic ofrece Default/Track
# Range/Odd-Even/Descriptor. Se implementa aquí el modo por Descriptor
# (código real de punto sísmico, ver `fila["descriptor"]` en
# `previsualizar_dc` -- NO `fila["tipo"]`, que en este plugin es la
# calidad/tipo de solución GNSS, KI/SO/FIX/FLOAT/etc., algo distinto): es el
# único de los cuatro que no depende de una numeración de Track consistente
# entre proyectos, y coincide con la convención real observada en las 89
# consultas guardadas reales del usuario (Query_DB.qrylt): todo Descriptor
# receptor empieza con "5" (51, 52, 5111) y todo Descriptor fuente/VP con
# "6" (60, 62, 63, 64, 65, 6111) -- mientras que los rangos de Track varían
# sin ningún patrón fijo de un proyecto a otro en esas mismas consultas.
_SURVEY_CODIGOS_FUENTE_DEFECTO = "60,62,63,64,65"
_SURVEY_CODIGOS_RECEPTORA_DEFECTO = "51,52"


def _parse_lista_codigos_descriptor(texto: str) -> set:
    """Convierte "60, 62 ,63" (como lo escribe el usuario en el campo de
    códigos de línea fuente/receptora) en {"60", "62", "63"} (mayúsculas,
    sin espacios). Cadena vacía o None -> set() vacío."""
    if not texto:
        return set()
    return {c.strip().upper() for c in texto.split(",") if c.strip()}


def _clasificar_linea_por_descriptor(descriptor, codigos_fuente: set, codigos_receptora: set):
    """Clasifica un punto como "fuente" o "receptora" según su Descriptor
    real (`fila["descriptor"]`) contra las dos listas de códigos
    configuradas para el proyecto 3D. También prueba sin el prefijo "D" de
    punto descartado (ver la nota junto a `descriptor_defecto` en
    `previsualizar_dc`: un punto descartado trae Descriptor "D60", no "60")
    para que un punto marcado como descartado siga clasificando igual que
    el resto de su línea. Devuelve None si no clasifica en ninguna de las
    dos listas (Descriptor vacío, código no configurado, etc.)."""
    if not descriptor:
        return None
    d = str(descriptor).strip().upper()
    if not d:
        return None
    candidatos = [d]
    if d[0] == "D" and len(d) > 1:
        candidatos.append(d[1:])
    for cand in candidatos:
        if cand in codigos_fuente:
            return "fuente"
        if cand in codigos_receptora:
            return "receptora"
    return None


# -- Importar/exportar consultas guardadas (sección "Base de Datos", pedido
# explícito del usuario: "que no tenga que armar los querys cada vez que
# arme un proyecto nuevo" + poder llevarlas a otra máquina) -----------------
#
# Formato .qrylt: el archivo de consultas guardadas nativo de GPSeismic
# (confirmado con un archivo real del usuario, "Query_DB.qrylt", 199
# casillas numeradas). Es texto plano con fin de línea CRLF, sin encabezado,
# con dos líneas por casilla numerada (más líneas "NNX..."/"NNC|..." de
# metadata de formato/color que GPSeismic usa para su propia grilla y que
# este plugin ignora, no le sirven para nada):
#   NND <descripción, o "(undefined)" si el usuario nunca la puso>
#   NNQ <SQL, o vacío si esa casilla nunca se usó>
# El SQL ya viene en una sintaxis (`[Tabla].`Columna``, "Like", "Between...
# And") que SQLite entiende tal cual sin ninguna conversión (SQLite acepta
# tanto corchetes como comillas invertidas para nombres, como extensión de
# compatibilidad) -- confirmado probándolo contra una base de prueba antes
# de confiar en esto. Lo único que puede fallar al EJECUTAR una consulta
# importada es que se refiera a una tabla que este plugin no tiene (ej.
# "VIBROS", propia de otros módulos de GPSeismic que este plugin no
# replica) -- error normal de "no existe la tabla/columna", igual que
# cualquier otra consulta inválida escrita a mano.
_QRYLT_LINE_RE = re.compile(r"^(\d+)([A-Za-z])(.*)$")


def _parse_qrylt_text(text: str):
    """Parsea el CONTENIDO ya decodificado de un archivo .qrylt de
    GPSeismic. Devuelve una lista de {"name": ..., "sql": ...} en el mismo
    orden de casilla (1, 2, 3...), salteando las casillas sin SQL (nunca
    usadas) -- ver la nota de formato más arriba. Una casilla sin
    descripción propia ("(undefined)", o en blanco) se nombra "GPSeismic
    <n>" para que siga siendo identificable en el combo en vez de perderse
    con un nombre vacío."""
    desc_por_numero = {}
    sql_por_numero = {}
    for linea in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _QRYLT_LINE_RE.match(linea)
        if not m:
            continue
        numero, letra, resto = int(m.group(1)), m.group(2).upper(), m.group(3)
        if letra == "D":
            desc_por_numero[numero] = resto.strip()
        elif letra == "Q":
            sql_por_numero[numero] = resto.strip()
        # Las líneas "X"/"C" (formato de grilla/color propio de GPSeismic)
        # se ignoran a propósito -- ver la nota de formato más arriba.

    resultado = []
    for numero in sorted(sql_por_numero):
        sql = sql_por_numero[numero]
        if not sql:
            continue
        desc = desc_por_numero.get(numero, "").strip()
        if not desc or desc == "(undefined)":
            desc = f"GPSeismic {numero}"
        resultado.append({"name": desc, "sql": sql})
    return resultado


def _leer_archivo_qrylt(path: str):
    """Lee un archivo .qrylt de disco probando primero UTF-8 y, si falla,
    Windows-1252 (codificación habitual de GPSeismic/Access en Windows en
    español) -- nunca se asume una sola codificación de entrada porque el
    archivo puede venir de cualquier versión de Windows del usuario."""
    with open(path, "rb") as f:
        contenido = f.read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = contenido.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = contenido.decode("latin-1", errors="replace")
    return _parse_qrylt_text(texto)


def _parse_custom_queries_json(data):
    """Parsea el contenido ya deserializado (`json.loads`) de un archivo
    exportado por este mismo plugin (`exportar_consultas_guardadas`) --
    acepta tanto el formato propio (`{"gnsseismic_custom_queries": 1,
    "queries": [...]}`) como una lista simple de {"name", "sql"} por si el
    usuario arma el archivo a mano. Devuelve una lista de {"name", "sql"},
    salteando cualquier entrada sin nombre o sin SQL."""
    if isinstance(data, dict):
        items = data.get("queries", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    resultado = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("name") or "").strip()
        sql = str(item.get("sql") or "").strip()
        if nombre and sql:
            resultado.append({"name": nombre, "sql": sql})
    return resultado


def _fusionar_consultas_importadas(existentes, nuevas, nombres_reservados):
    """Combina `nuevas` (recién leídas de un archivo) con `existentes` (ya
    guardadas en QSettings), sin pisar NUNCA una consulta que el usuario ya
    tenía guardada con ese nombre -- ni entre sí (dos "nuevas" con el mismo
    nombre, algo que sí pasa en archivos .qrylt reales, ej. dos casillas
    llamadas "25-CHK NUEVO") ni contra un preset de fábrica
    (`nombres_reservados`, ver `_PRESET_KEY_LABELS`): en cualquier
    colisión, la consulta IMPORTADA es la que se renombra agregando " (2)",
    " (3)", etc. hasta encontrar un nombre libre, nunca la que ya existía.

    Devuelve (lista_final, n_agregadas, n_renombradas)."""
    resultado = list(existentes)
    nombres_usados = {q["name"] for q in existentes} | set(nombres_reservados)
    n_agregadas = 0
    n_renombradas = 0
    for nueva in nuevas:
        nombre = nueva["name"]
        if nombre in nombres_usados:
            n_renombradas += 1
            base = nombre
            i = 2
            while f"{base} ({i})" in nombres_usados:
                i += 1
            nombre = f"{base} ({i})"
        nombres_usados.add(nombre)
        resultado.append({"name": nombre, "sql": nueva["sql"]})
        n_agregadas += 1
    return resultado, n_agregadas, n_renombradas


def _hitarget_tipo_code(p) -> str:
    """Clasifica un `HiTargetPoint` en uno de los tipos usados para la
    columna Descriptor de POSTPLOT y la simbología de la capa creada al
    importar, a partir de su columna Estado (texto libre del receptor,
    ej. 'RTK Fijo'/'RTK Fix'/'RTK Flotante'/'Cálculo') y de si es una
    ocupación de base (`is_base`)."""
    if p.is_base:
        return "BASE"
    estado = (p.estado or "").strip().lower()
    if "fij" in estado or "fix" in estado:
        return "FIX"
    if "flot" in estado or "float" in estado:
        return "FLOAT"
    if "calc" in estado or "cálc" in estado:
        return "CALC"
    return "OTRO"


def _hitarget_calidad_key(p) -> str:
    """Clave de i18n para la columna "Calidad" de la previsualización
    (agregada en la v2.25.0), derivada de la misma columna Estado que ya
    usa `_hitarget_tipo_code` -- pero, a diferencia de esa función, ésta
    SIEMPRE lee el Estado tal cual (incluso para una ocupación de base:
    no hay razón para no mostrar la calidad de su propia solución sólo
    porque además sea una base), y nunca agrega la categoría BASE."""
    estado = (p.estado or "").strip().lower()
    if "fij" in estado or "fix" in estado:
        return "calidad_fijo"
    if "flot" in estado or "float" in estado:
        return "calidad_flotante"
    if "calc" in estado or "cálc" in estado:
        return "calidad_calculo"
    if not estado:
        return "calidad_nd"
    return "calidad_otro"


def _survey_mode_key_valor(status_texto) -> "tuple[str, str]":
    """Survey Mode (texto/valor) de GPSeismic a partir de un texto de
    estado/calidad de la solución (Estado de Hi-Target, Status de
    CHCNav).

    Valores confirmados contra la documentación oficial de GPSeismic
    (tabla de importación GNSS estándar, "gnss_table.htm" del manual
    GPSeismic.chm, instalado en el equipo del usuario): el campo
    Survey_Mode_Value es un entero con un catálogo fijo -- 0=Desconocido,
    1=Autónomo, 2=GPS código, 3=Phase (RTK fijo), 4=RTK Float, 5=GPS/
    Glonass código, 6=Solución de área amplia, 7=Trimble RTX, 8=Leica
    XRTK.

    Este plugin distingue tres de esos ocho, los únicos que puede
    detectar de forma confiable a partir del texto libre de Estado/
    Status que traen Hi-Target y CHCNav (misma detección por subcadena
    que ya usa `_hitarget_calidad_key` para la columna "Calidad", para
    quedar consistentes entre ambas columnas): "fix"/"fijo"/"fixed" ->
    Phase/3; "flot"/"float" -> RTK Float/4 (agregado en esta ronda: es
    un valor real y distinto del catálogo oficial, no debe confundirse
    con Autónomo); cualquier otro caso (incluye "cálculo"/"calc", sin
    dato suficiente para separarlo de una posición autónoma corriente,
    y cualquier texto vacío u otro) -> Autónomo/1, el valor por defecto
    que ya se usaba antes de esta ronda. Devuelve (clave_i18n, valor) --
    la clave se traduce con `self.t(...)` en el llamador, igual que ya
    hace `_hitarget_calidad_key`."""
    texto = (status_texto or "").strip().lower()
    if "fij" in texto or "fix" in texto:
        return "survey_mode_phase", "3"
    if "flot" in texto or "float" in texto:
        return "survey_mode_float", "4"
    return "survey_mode_autonomo", "1"


def _inova_modo_key_valor(calidad) -> "tuple[str, str]":
    """Survey Mode de un VP de Inova a partir de sus tipos de fix GNSS
    ("RTK Fix", "RTK Fix, DGPS Fix"...; un VP junta las lecturas de varios
    vibros). Se toma el PEOR de los tipos presentes: sólo "RTK Fix" ->
    Phase/3, algún "Float" -> RTK Float/4, cualquier otro (p.ej. "DGPS
    Fix", que es diferencial de código, no RTK) -> Autónomo/1 -- por eso no
    sirve `_survey_mode_key_valor` tal cual, que trata todo "fix" como
    Phase."""
    tokens = [t.strip().lower() for t in (calidad or "").split(",") if t.strip()]
    if not tokens:
        return "survey_mode_autonomo", "1"
    peor = "survey_mode_phase"
    for t in tokens:
        if "float" in t or "flot" in t:
            nivel = "survey_mode_float"
        elif "rtk" in t and ("fix" in t or "fij" in t):
            nivel = "survey_mode_phase"
        else:
            nivel = "survey_mode_autonomo"
        if nivel == "survey_mode_autonomo" or (nivel == "survey_mode_float" and peor == "survey_mode_phase"):
            peor = nivel
    return peor, {"survey_mode_phase": "3", "survey_mode_float": "4", "survey_mode_autonomo": "1"}[peor]


# Texto fijo en INGLÉS para el valor por defecto de Survey_Mode_Text --
# a diferencia de casi cualquier otro texto de la previsualización (que
# sí sigue el idioma de la interfaz vía `self.t()`), éste es un
# catálogo real y externo de GPSeismic (ver la nota de
# `_survey_mode_key_valor` arriba) cuya convención SIEMPRE es en
# inglés, confirmado 234/234 puntos contra la base de datos POSTPLOT de
# referencia del usuario ("Phase", nunca "Fase", sin importar en qué
# idioma esté el plugin). Usar `self.t(...)` para este valor por
# defecto era un error real: quedaba "congelado" en el idioma de la UI
# vigente al momento de importar el archivo, y ni siquiera se
# retraducía si el usuario cambiaba de idioma después (a diferencia de
# los encabezados de columna, que sí se retraducen) -- lo reportó el
# propio usuario viendo "Fase" en la columna "Survey Mode (text)" con
# el plugin ya en inglés.
SURVEY_MODE_TEXTO_EN = {
    key: i18n.TR[key]["en"]
    for key in ("survey_mode_phase", "survey_mode_autonomo", "survey_mode_float")
}


def _chcnav_tipo_code(p) -> str:
    """Código de tipo para un `ChcnavPoint`: el sufijo de clasificación
    tal cual lo trae el archivo (ej. 'LD'/'CT'/'CHKAM'/'CHKPM' -- ver
    `chcnav_parser.py`, nunca se traduce/adivina su significado exacto),
    o 'OTRO' si el punto no trae ninguno (raro, pero ocurre en el
    archivo real de referencia usado para construir este parser)."""
    return (p.tipo or "").strip() or "OTRO"


def _stonex_tipo_code(p) -> str:
    """Código de tipo para un `stonex_parser.StonexPoint`: el campo CODE
    tal cual lo trae la base de Stonex, en MAYÚSCULAS (a diferencia de
    `_chcnav_tipo_code`, aquí sí se normaliza el caso -- en el archivo
    real de referencia el mismo código de chequeo aparece una vez como
    'chk' y otra como 'CHK', inconsistencia propia de cómo el usuario lo
    escribió en el equipo, no una diferencia real de significado entre
    dos códigos distintos), o 'OTRO' si el punto no trae ninguno."""
    return (p.code or "").strip().upper() or "OTRO"


def _stonex_calidad_texto(translate, pos_state: str) -> str:
    """Texto de la columna "Calidad" para un punto de Stonex, a partir
    de `GPSCoordinate.Pos_State` (texto real del receptor). El archivo
    real de referencia trae tres valores: 'FIXED', 'FLOAT' y 'DIF3D'
    (posicionamiento diferencial, sin RTK) -- a pedido explícito del
    usuario (pregunta de aclaración de la ronda 2.26.0), 'FIXED'/'FLOAT'
    SÍ se traducen (son inambiguos, mismo criterio que ya usa
    `_hitarget_calidad_key` para el texto Estado de Hi-Target), pero
    'DIF3D' se deja TAL CUAL, sin traducir -- el usuario decidió no
    forzarlo dentro de "Autónomo" ni de "Otro" para no perder la
    distinción real que hace el propio receptor."""
    if pos_state == "FIXED":
        return translate("calidad_fijo")
    if pos_state == "FLOAT":
        return translate("calidad_flotante")
    return pos_state if pos_state else translate("calidad_nd")


# Subcarpetas que se crean dentro de la carpeta de un proyecto nuevo
# (ver `crear_proyecto`): "database" aloja la base SQLite del proyecto,
# nombrada `<nombre_de_proyecto_sanitizado>.sqlite` (desde la v2.16.0;
# antes siempre `database.sqlite` sin importar el nombre elegido -- un
# proyecto creado con una versión anterior sigue abriendo igual, porque
# `abrir_proyecto()`/"Mis proyectos..." nunca asumen un nombre de archivo
# fijo, sólo guardan la ruta completa); "maps", "preplot" y "posplot"
# quedan vacías, a disposición del usuario para organizar sus propios
# archivos de ese proyecto (capas, entregables, exportaciones) fuera de
# la base de datos.
PROJECT_SUBFOLDERS = ("database", "maps", "preplot", "posplot")

# Clave bajo la que se guarda, en QSettings (perfil de QGIS del usuario,
# no en ningún proyecto en particular), la lista de proyectos conocidos
# para el selector "Mis proyectos..." -- ver `_load_known_projects` /
# `_register_known_project`. Los proyectos pueden vivir en carpetas
# completamente distintas (normal cuando se trabaja en varios a la vez),
# así que se registran por su ruta completa, no por nombre.
_SETTINGS_KEY_KNOWN_PROJECTS = "gnsseismic/known_projects"
_SETTINGS_KEY_LAST_PARENT_DIR = "gnsseismic/last_project_parent_dir"

# Claves bajo las que "Guardar consulta..." (sección Base de Datos)
# persiste en QSettings -- igual que "Mis proyectos", en el perfil de
# QGIS del usuario, no en ningún proyecto en particular, porque las
# consultas de ejemplo se refieren siempre al mismo esquema (POSTPLOT/
# PREPLOT/COMPARACION) sin importar en qué proyecto se usen:
#   - `_SETTINGS_KEY_QUERY_OVERRIDES`: dict {clave_de_preset: sql} con el
#     SQL que el usuario haya guardado encima de una consulta de ejemplo
#     de fábrica (ver `_PRESET_SQL`), reemplazando su SQL original sin
#     crear una entrada nueva en el combo.
#   - `_SETTINGS_KEY_CUSTOM_QUERIES`: lista de {"name": ..., "sql": ...}
#     con las consultas guardadas por el usuario con un nombre propio,
#     agregadas al final del combo de consultas de ejemplo.
_SETTINGS_KEY_QUERY_OVERRIDES = "gnsseismic/query_preset_overrides"
_SETTINGS_KEY_CUSTOM_QUERIES = "gnsseismic/custom_queries"

# Filtros propios guardados por el usuario en la sección "Consultar /
# filtrar antes de subir" de "Importar datos de campo" (ver
# `_PREVIEW_FILTER_PRESET_ORDER` más abajo) -- mismo mecanismo que
# `_SETTINGS_KEY_CUSTOM_QUERIES` pero en una clave propia, ya que son
# condiciones WHERE sueltas (no consultas completas) contra una tabla
# distinta (`PREVIEW`, en memoria).
_SETTINGS_KEY_PREVIEW_FILTER_CUSTOM = "gnsseismic/preview_filter_custom"

_MAX_KNOWN_PROJECTS = 50

_INVALID_FOLDER_CHARS_RE = re.compile(r'[\\/:*?"<>|]')


def _sanitizar_nombre_carpeta(nombre: str) -> str:
    """Convierte el nombre de proyecto elegido por el usuario en un
    nombre de carpeta válido (quita caracteres prohibidos en Windows,
    que es donde corre este plugin en la práctica)."""
    limpio = _INVALID_FOLDER_CHARS_RE.sub("_", nombre).strip().strip(".")
    return limpio or "proyecto"


def _parse_optional_float(text):
    """Convierte texto de una celda editable (altura de antena) a float,
    o None si está vacío o no es un número (tolera coma decimal)."""
    if text is None:
        return None
    text = str(text).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# Columnas de la tabla de previsualización de "Importar datos de campo"
# (`_build_tab_importar`/`previsualizar_dc`/`_llenar_tabla_preview`): se
# muestran los puntos recién parseados del/de los .dc ANTES de subirlos a
# POSTPLOT, ya comparados contra PREPLOT (si el proyecto tiene), para que
# el usuario decida qué subir y pueda corregir nombre/altura de
# antena/comentario primero.
#
# Reorganizada por completo en la ronda de la base de datos
# "previsualisacion.mdb" (una exportación POSTPLOT real de GPSeismic para
# ar180118.dsc, subida por el usuario como plantilla): a pedido explícito
# del usuario ("que quede organizada como esta mbd adjunta"), las
# primeras 58 columnas (índices 1 a 58, después de "Incluir") reproducen
# EXACTAMENTE el orden y los encabezados de esa base de datos real
# (`POSTPLOT`, 58 columnas -- ver `_import_preview_headers` para el
# nombre completo de cada una). El usuario, al preguntársele si prefería
# sólo las columnas con datos reales o las 58 completas, eligió
# explícitamente "Mismas 58 columnas, aunque queden vacías" -- así que
# varias quedan siempre en "-"/vacías quando el formato de origen no trae
# ese dato (nunca inventado): Scale Factor/Convergence (requieren
# geometría de proyección no implementada), los 7 campos "Offset ..."
# y Azimut de línea (comparación contra un diseño/azimut de referencia
# que no se rastrea por punto), Precisión Hor/Ver 95%/CQ (requerirían
# asumir una constante UERE no confirmada), Julian Date/Serial Time
# (GPS)/Elapsed Time/Populate Time (decodificación de tiempo GPS no
# verificada), GDOP/Unit Variance/Init Block/Station Deltas/Consecutive
# Intervals/Consecutive Azimuths/Reserved (sin ningún dato equivalente en
# ninguno de los 4 formatos soportados). El resto SÍ trae datos reales,
# la mayoría ya calculados en el backend desde rondas anteriores y sólo
# faltaba mostrarlos aquí (Track/Bin, satélites/PDOP/HDOP/VDOP, GPS
# Baseline/Base Station, tiempo de ocupación, nombre de trabajo/receptor/
# serie) -- ver `_llenar_tabla_preview` para el detalle de cada columna.
# "Local Latitude/Longitude" se muestran iguales a "WGS84 Latitude/
# Longitude" (mismo supuesto, documentado, de que el datum local del
# proyecto es WGS84 -- ver `col_local_datum`). Después de las 58
# columnas de GPSeismic se conservan, como columnas EXTRA propias del
# plugin (no parte del layout de GPSeismic), las que ya existían antes de
# esta ronda para comparar contra PREPLOT y decidir qué subir: Tipo
# (KI/SO/BASE) y la comparación con PREPLOT -- con el archivo de origen,
# como siempre, en la última columna de todas.
#
# Desde esta ronda, a pedido explícito del usuario: se quitó la columna
# "Calidad" de esta tabla (seguía calculándose internamente --
# `fila.get("calidad")` -- para la capa de puntos del mapa, el filtro SQL
# de la previsualización y la exportación a CSV/Shapefile/GeoPackage,
# ninguno de los cuales se tocó; sólo se dejó de MOSTRAR en esta tabla),
# y Elevación ortométrica se movió de columna EXTRA al final (donde no
# tenía relación visual con la altura de la que se deriva) a quedar
# INMEDIATAMENTE después de "Alt. WGS84 (m)" -- más lógico para comparar
# ambas alturas de un vistazo, aunque GPSeismic no tenga esa columna ahí
# en su propio layout de 58.
PREVIEW_COL_INCLUDE = 0
PREVIEW_COL_NOMBRE = 1                      # Station (text)
PREVIEW_COL_STATION_VALUE = 2               # Station (value)
PREVIEW_COL_TRACK = 3
PREVIEW_COL_BIN = 4
PREVIEW_COL_DESCRIPTOR = 5                  # editable, en blanco por defecto (ver la nota de arriba)
PREVIEW_COL_LAT_WGS84 = 6
PREVIEW_COL_LON_WGS84 = 7
PREVIEW_COL_LAT_LOCAL = 8
PREVIEW_COL_LON_LOCAL = 9
PREVIEW_COL_ESTE = 10                       # Local Easting
PREVIEW_COL_NORTE = 11                      # Local Northing
PREVIEW_COL_ALTURA = 12                     # WGS84 Height
PREVIEW_COL_ORTOMETRICA = 13                # columna EXTRA (no es de GPSeismic) -- a propósito, justo al lado de Alt. WGS84 (ver la nota de arriba)
PREVIEW_COL_SCALE_FACTOR = 14
PREVIEW_COL_CONVERGENCE = 15
PREVIEW_COL_SURVEY_MODE_TEXT = 16           # editable
PREVIEW_COL_SURVEY_MODE_VALUE = 17          # editable
PREVIEW_COL_HI = 18
PREVIEW_COL_OFFSET_NORTH = 19
PREVIEW_COL_OFFSET_EAST = 20
PREVIEW_COL_OFFSET_RANGE = 21
PREVIEW_COL_OFFSET_BEARING = 22
PREVIEW_COL_OFFSET_INLINE = 23
PREVIEW_COL_OFFSET_CROSSLINE = 24
PREVIEW_COL_OFFSET_HEIGHT = 25
PREVIEW_COL_INLINE_AZIMUTH = 26
PREVIEW_COL_HOR_PRECISION = 27
PREVIEW_COL_VER_PRECISION = 28
PREVIEW_COL_CQ = 29
PREVIEW_COL_N_SATS = 30
PREVIEW_COL_PDOP = 31
PREVIEW_COL_HDOP = 32
PREVIEW_COL_VDOP = 33
PREVIEW_COL_JULIAN_DATE = 34
PREVIEW_COL_SURVEY_TIME_LOCAL = 35
PREVIEW_COL_SURVEY_TIME_GMT = 36
PREVIEW_COL_SERIAL_TIME_GPS = 37
PREVIEW_COL_ELAPSED_TIME = 38
PREVIEW_COL_POPULATE_TIME = 39
PREVIEW_COL_LOCAL_DATUM = 40
PREVIEW_COL_LOCAL_SYSTEM = 41
PREVIEW_COL_DISTANCE_UNITS = 42
PREVIEW_COL_DISTANCE_FACTOR = 43
PREVIEW_COL_COMENTARIO = 44                 # Comment, editable
PREVIEW_COL_DOWNLOAD_FILE = 45
PREVIEW_COL_JOB_NAME = 46                   # Collector Job Name
PREVIEW_COL_RECEIVER_TYPE = 47
PREVIEW_COL_RECEIVER_SN = 48
PREVIEW_COL_GDOP = 49
PREVIEW_COL_UNIT_VARIANCE = 50
PREVIEW_COL_GPS_BASELINE = 51
PREVIEW_COL_GPS_BASE_STATION = 52
PREVIEW_COL_OCCUPATION_TIME = 53
PREVIEW_COL_INIT_BLOCK = 54
PREVIEW_COL_STATION_DELTAS = 55
PREVIEW_COL_CONSECUTIVE_INTERVALS = 56
PREVIEW_COL_CONSECUTIVE_AZIMUTHS = 57
PREVIEW_COL_RECNUM = 58
PREVIEW_COL_RESERVED = 59
# -- fin de las 58 columnas de GPSeismic -- a partir de acá, columnas
# EXTRA propias del plugin, que GPSeismic no tiene: Tipo (KI/SO/BASE) y
# la comparación con PREPLOT -- con el archivo de origen, como siempre,
# al final de todo. ("Calidad" se quitó de esta tabla y "Ortométrica" se
# movió junto a "Alt. WGS84 (m)" -- ver la nota de arriba.)
PREVIEW_COL_TIPO = 60
PREVIEW_COL_PREPLOT = 61
PREVIEW_COL_DELTA_E = 62
PREVIEW_COL_DELTA_N = 63
PREVIEW_COL_DIST2D = 64
PREVIEW_COL_ESTADO = 65
PREVIEW_COL_ARCHIVO = 66
PREVIEW_COL_SURVEYOR = 67  # columna extra (v2.62.11): Surveyor que se subirá (Unit ID en SourceLink, o el escrito junto al archivo)
PREVIEW_N_COLS = 68

# Columnas de la tabla de previsualización de "Importar preplot externo"
# (`_build_tab_preplot`, grupo agregado en la v2.6.0): puntos leídos de
# un archivo SPS (Omni 3D / mesa de Sercel) o de un CSV genérico, ANTES
# de subirlos a PREPLOT, para poder revisar/corregir el nombre y decidir
# qué incluir -- en particular los que ya existen en PREPLOT con el
# mismo nombre, marcados como posibles duplicados.
EXT_PREVIEW_COL_INCLUDE = 0
EXT_PREVIEW_COL_ORIGEN = 1
EXT_PREVIEW_COL_NOMBRE = 2
EXT_PREVIEW_COL_TRACK = 3
EXT_PREVIEW_COL_BIN = 4
EXT_PREVIEW_COL_ESTE = 5
EXT_PREVIEW_COL_NORTE = 6
EXT_PREVIEW_COL_COTA = 7
EXT_PREVIEW_COL_ESTADO = 8
EXT_PREVIEW_N_COLS = 9

# Columnas de la tabla de "Corrección de base RTK (opcional)"
# (`_build_tab_importar`/`_actualizar_seccion_correccion_base`), agregada
# junto con esta funcionalidad: una fila por cada ocupación de base
# ('is_base'=True) detectada entre los archivos cargados de Hi-Target
# (CSV/.raw) o CHCNav (.rw5).
#
# Trimble .dc quedó fuera de esta funcionalidad hasta esta ronda: su
# registro 'SO' nunca se confirmó como ocupación de base (sigue sin
# estarlo -- 'SO' es un punto de estación/fuente normal, ver el docstring
# más arriba). Lo que sí se confirmó, con un archivo real más antiguo
# ("clásico", de antes de que existiera el RTX -- lo confirmó el propio
# usuario al subirlo) son dos registros DISTINTOS y hasta entonces no
# vistos, '66SI'/'66FD' (ver `dc_parser.BASE_CODES`): la primera
# aparición ('SI', una sola vez) y las reocupaciones/"Found" siguientes
# ('FD', una por sesión) de la MISMA base física, siempre con nombre y
# coordenada idénticos -- igual patrón que 'BP' de CHCNav o 'set_base' de
# Hi-Target. A diferencia de esas dos marcas, Trimble .dc no tiene ningún
# campo que diga qué base usó cada punto rover -- desde la ronda de
# soporte a MÚLTIPLES bases por archivo, la asociación se hace por ORDEN
# DE APARICIÓN dentro de `dc_parser.parse_dc_text` (a cada punto no-base
# se le asigna la ocupación de base más reciente vista antes que él,
# "vigente hasta que otra la reemplace" -- ver
# `DCPoint.base_station_name`/`base_baseline_m`), exactamente el mismo
# mecanismo ya verificado para el 'BP' de CHCNav (v2.24.0). Así, un
# archivo con una sola base física (reocupada varias veces) asocia todos
# sus puntos no-base a ella, y uno con dos o más bases físicas distintas
# (ej. 12 puntos con "BASE1" y luego, tras un '66FD' nuevo, 25 puntos con
# "BASE2") asocia cada punto con la que realmente estaba vigente cuando
# se levantó -- sin verificar todavía contra un archivo real con más de
# una base distinta (el único disponible, ar180118.dsc, sólo tiene una).
#
# Stonex (ronda 2.26.0) no tenía en su único archivo real disponible
# ninguna ocupación de base física propia (sólo una referencia de red
# RTCM/NTRIP para todos sus puntos) -- pero desde la v2.27.0 SÍ participa:
# a pedido del usuario (que aportó un CSV propio de su app confirmando
# la coordenada de esa referencia), se arma una fila 'is_base'=True
# SINTÉTICA por cada referencia distinta que traiga el archivo
# (`StonexFile.unique_bases()`, a partir de
# `GPSCoordinate.Base_Latitude/Base_Longitude/Base_Altitude`, el mismo
# dato que cada punto rover ya trae repetido) en vez de a partir de un
# punto realmente ocupado -- ver la nota junto al loop STONEX en
# `previsualizar_dc()` y el docstring de stonex_parser.py.
# El pedido original del usuario: cuando el levantamiento RTK se hizo
# con una base propia (no con RTX de Trimble ni HAS de Galileo, que ya
# entregan coordenadas corregidas), la posición de esa base suele venir
# de una lectura autónoma/libre (sin corregir) -- si después se
# post-procesa una sesión estática sobre ese mismo punto y se obtiene su
# coordenada verdadera, todos los puntos RTK levantados con esa base se
# pueden corregir con una simple traslación (Δlat/Δlon/Δaltura =
# corregida - libre), aplicada por igual a todos. Ver
# `GNSSeismicController._aplicar_correcciones_base_a_filas` para cómo se
# aplica (de forma idempotente, siempre a partir de la coordenada tal
# cual quedó parseada del archivo) y `_on_aplicar_correccion_base` para
# el flujo de la interfaz.
# Desde la v2.25.0 también se muestran las coordenadas planas (Este/
# Norte, `_transform_xy` al CRS de trabajo del proyecto) tanto de la
# base libre como de la corregida -- pedido explícito del usuario junto
# con las columnas planas de la previsualización principal. La de la
# base libre se calcula siempre (a partir de lat/lon tal cual se
# parseó); la de la corregida sólo cuando la corrección ya está
# APLICADA (`self._base_corrections`), igual que ya hacían las columnas
# geográficas corregidas -- ver `_actualizar_seccion_correccion_base`.
CORR_BASE_COL_ARCHIVO = 0
CORR_BASE_COL_NOMBRE = 1
CORR_BASE_COL_LAT_LIBRE = 2
CORR_BASE_COL_LON_LIBRE = 3
CORR_BASE_COL_ALT_LIBRE = 4
CORR_BASE_COL_ESTE_LIBRE = 5
CORR_BASE_COL_NORTE_LIBRE = 6
CORR_BASE_COL_LAT_CORR = 7
CORR_BASE_COL_LON_CORR = 8
CORR_BASE_COL_ALT_CORR = 9
CORR_BASE_COL_ESTE_CORR = 10
CORR_BASE_COL_NORTE_CORR = 11
CORR_BASE_COL_CARGAR = 12
CORR_BASE_COL_ESTADO = 13
CORR_BASE_N_COLS = 14

# Umbral (metros, horizontal) a partir del cual "Aplicar correcciones"
# pide confirmación antes de aplicar un desplazamiento tan grande -- una
# corrección de base real (autónoma/libre vs. estática post-procesada)
# normalmente es de centímetros a pocos metros; un salto de decenas de
# metros suele indicar un error de digitación (coordenada equivocada,
# signo de longitud invertido, etc.) más que una corrección real.
CORR_BASE_SHIFT_WARN_M = 50.0


class _SectionWindow(QDialog):
    """Ventana no modal para una sección del plugin (Proyecto, Preplot
    Sísmico, Importar datos de campo, Comparar o Base de Datos). Se puede mover,
    redimensionar y cerrar de forma independiente, y quedar abierta junto
    con las demás ventanas del plugin al mismo tiempo -- a diferencia de
    una pestaña, aquí no hay que elegir cuál ver."""

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setModal(False)
        # Por defecto un QDialog en Windows sólo trae el botón de cerrar
        # en la barra de título -- pedido del usuario (v2.20.0): agregar
        # también minimizar y maximizar/restaurar a las cinco ventanas de
        # sección (comparten esta misma clase, así que alcanza con
        # tocarla acá una sola vez). `WindowSystemMenuHint` va junto con
        # los otros dos porque en algunas plataformas hace falta para que
        # el botón de minimizar/maximizar funcione de verdad, no sólo se
        # vea (documentado así por Qt); no quita el botón de cerrar, que
        # ya viene con las flags por defecto de un QDialog.
        self.setWindowFlags(
            self.windowFlags() | WINDOW_MINIMIZE_HINT | WINDOW_MAXIMIZE_HINT | WINDOW_SYSTEM_MENU_HINT
        )
        # Cerrar la ventana (la X) no debe destruir sus widgets: así el
        # estado de esa sección (última consulta ejecutada, último
        # resultado de comparación, etc.) se conserva si el usuario la
        # vuelve a abrir con el ícono del toolbar.
        self.setAttribute(WA_DELETE_ON_CLOSE, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        # El contenido va dentro de un QScrollArea (en vez de agregarse
        # directo al layout) para que el tamaño MÍNIMO de la ventana lo
        # imponga el scroll area (chico) y no la suma de las alturas
        # mínimas de todos sus widgets internos -- si no, una sección con
        # mucho contenido (p.ej. Preplot Sísmico desde que se le agregó
        # "Importar preplot externo" en la v2.6.0) fuerza la ventana a
        # abrir más alta que la pantalla aunque `_ajustar_tamano_ventana`
        # la achique después, porque Qt no la deja bajar de ese mínimo.
        # Con el scroll area, si hace falta, se ve con una barra de
        # desplazamiento en vez de tapar la pantalla.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(FRAME_SHAPE_NONE)
        scroll.setWidget(content)
        layout.addWidget(scroll)


class GNSSeismicController(QWidget):
    """No es una ventana visible: existe sólo para guardar el estado
    compartido entre las cinco secciones del plugin y para servir de
    padre estable a los QFileDialog/QMessageBox de cada una. Las
    ventanas propiamente dichas son las `_SectionWindow` que arma
    `_build_windows()`, una por sección."""

    # NOTA (v2.17.0): el usuario pidió agregar también "POSTPLOT por Swath"
    # y "PREPLOT por Swath", pero "Swath" no existe como columna ni como
    # concepto en ninguna parte del esquema actual (`db_schema.py`) ni del
    # resto del código -- se revisó a fondo antes de escribir estos
    # presets. Siguiendo la regla del proyecto de nunca adivinar un campo
    # o formato no documentado, se dejaron pendientes hasta que el usuario
    # aclare a qué se refiere (¿columna nueva a crear? ¿se calcula a
    # partir de rangos de `Track`? ¿es otro nombre de campo que ya usa en
    # su flujo de trabajo?). Los otros tres presets pedidos sí son
    # inequívocos porque `Track`, `Station_Value` y `Julian_Date_Local`
    # ya son columnas reales de POSTPLOT.
    _PRESET_ORDER = [
        "custom",
        "postplot_all",
        "preplot_all",
        "postplot_by_type",
        "postplot_by_track",
        "postplot_by_station_value",
        "postplot_by_julian_date_local",
        "comparacion_fuera_tol",
    ]
    _PRESET_SQL = {
        "custom": None,
        "postplot_all": "SELECT * FROM POSTPLOT",
        "preplot_all": "SELECT * FROM PREPLOT",
        "postplot_by_type": "SELECT * FROM POSTPLOT WHERE Descriptor = 'KI'",
        "postplot_by_track": "SELECT * FROM POSTPLOT WHERE Track = 1",
        "postplot_by_station_value": "SELECT * FROM POSTPLOT WHERE Station_Value = 100",
        "postplot_by_julian_date_local": "SELECT * FROM POSTPLOT WHERE Julian_Date_Local = 1",
        "comparacion_fuera_tol": "SELECT * FROM COMPARACION WHERE Dentro_Tolerancia = 0",
    }
    _PRESET_KEY_LABELS = {
        "custom": "preset_custom",
        "postplot_all": "preset_postplot_all",
        "preplot_all": "preset_preplot_all",
        "postplot_by_type": "preset_postplot_by_type",
        "postplot_by_track": "preset_postplot_by_track",
        "postplot_by_station_value": "preset_postplot_by_station_value",
        "postplot_by_julian_date_local": "preset_postplot_by_julian_date_local",
        "comparacion_fuera_tol": "preset_comparacion_fuera_tol",
    }

    # -- Formatos del combo "Formato de exportación:" de "Base de Datos"
    # (v2.21.0): antes eran 3 botones separados (Shapefile/GeoPackage/SPS);
    # ahora es una única lista desplegable + un botón "Exportar...", con
    # Excel (.csv) agregado como cuarto formato -- ver `exportar_query`/
    # `_exportar_csv`.
    _EXPORT_FORMAT_ORDER = ["shapefile", "gpkg", "sps", "csv"]
    _EXPORT_FORMAT_LABELS = {
        "shapefile": "export_format_shapefile",
        "gpkg": "export_format_gpkg",
        "sps": "export_format_sps",
        "csv": "export_format_csv",
    }

    # Exportación de la previsualización de "Importar datos de campo"
    # (`_fill_export_preview_format_combo`/`_exportar_preview_actual`):
    # mismas etiquetas (`_EXPORT_FORMAT_LABELS`) pero SIN "sps" -- a
    # propósito, ya que el formato SPS de exportación de "Base de Datos"
    # depende de un mapeo de columnas (línea/punto/código) que no aplica
    # a esta previsualización todavía sin subir; se dejó fuera de esta
    # ronda en vez de duplicar ese mapeo.
    _PREVIEW_EXPORT_FORMAT_ORDER = ["shapefile", "gpkg", "csv"]

    # -- Filtros predeterminados y asistente de la sección "Consultar /
    # filtrar antes de subir" de "Importar datos de campo" (pedido
    # explícito del usuario: mismo mecanismo de presets + guardado que
    # "Base de Datos" -- ver `_PRESET_ORDER`/`_PRESET_SQL` arriba y
    # `_load_custom_queries`/`guardar_consulta_actual` más abajo -- pero
    # en una versión más chica: sin overrides de los presets de fábrica
    # y sin renombrar/importar/exportar, que el pedido no mencionó. El
    # SQL corre contra la tabla `PREVIEW` en memoria que arma
    # `_construir_conexion_preview_sqlite()` a partir de
    # `self._import_preview`, con su columna calculada `estado`
    # ("sin_match" / "dentro_tolerancia" / "fuera_tolerancia" / "subido").
    _PREVIEW_FILTER_PRESET_ORDER = [
        "custom",
        "sin_preplot",
        "fuera_tolerancia",
        "dentro_tolerancia",
        "ya_subidos",
        "no_incluidos",
    ]
    _PREVIEW_FILTER_PRESET_SQL = {
        "custom": None,
        "sin_preplot": "estado = 'sin_match'",
        "fuera_tolerancia": "estado = 'fuera_tolerancia'",
        "dentro_tolerancia": "estado = 'dentro_tolerancia'",
        "ya_subidos": "subido = 1",
        "no_incluidos": "incluir = 0",
    }
    _PREVIEW_FILTER_PRESET_LABELS = {
        "custom": "preset_preview_filter_custom",
        "sin_preplot": "preset_preview_filter_sin_preplot",
        "fuera_tolerancia": "preset_preview_filter_fuera_tolerancia",
        "dentro_tolerancia": "preset_preview_filter_dentro_tolerancia",
        "ya_subidos": "preset_preview_filter_ya_subidos",
        "no_incluidos": "preset_preview_filter_no_incluidos",
    }

    # Columnas ofrecidas por el asistente de filtro (sin escribir SQL a
    # mano): (nombre de columna en la tabla `PREVIEW` en memoria, clave
    # i18n de su etiqueta, "text"/"num" para saber cómo armar la
    # condición -- comillas simples sólo para texto). Reusa las mismas
    # claves i18n que los encabezados de `tbl_import_preview` donde
    # existen, para no duplicar traducciones.
    _PREVIEW_FILTER_COLUMNS = [
        ("nombre", "col_point_name", "text"),
        ("descriptor", "col_descriptor", "text"),
        ("track", "col_track", "num"),
        ("bin", "col_bin", "num"),
        ("lat", "col_lat", "num"),
        ("lon", "col_lon", "num"),
        ("este", "col_easting", "num"),
        ("norte", "col_northing", "num"),
        ("altura", "col_height_wgs84", "num"),
        ("hi", "col_antenna_height", "num"),
        ("comentario", "col_comment", "text"),
        ("tipo", "col_type", "text"),
        ("calidad", "col_calidad", "text"),
        ("survey_mode_text", "col_survey_mode_text", "text"),
        ("archivo", "col_file", "text"),
        ("estado", "col_status", "text"),
        ("surveyor", "col_surveyor", "text"),
        ("incluir", "col_include", "num"),
        ("subido", "lbl_filtro_wizard_col_subido", "num"),
    ]
    _PREVIEW_FILTER_OPERATORS = [
        ("=", "op_eq"),
        ("!=", "op_neq"),
        (">", "op_gt"),
        ("<", "op_lt"),
        (">=", "op_gte"),
        ("<=", "op_lte"),
        ("contiene", "op_contains"),
        ("no_contiene", "op_not_contains"),
        ("vacio", "op_is_empty"),
        ("no_vacio", "op_is_not_empty"),
    ]

    # -- Marcas soportadas por la solapa desplegable "Archivos de campo"
    # de "Importar datos de campo" (ver `_build_tab_importar`), como
    # (clave i18n del ítem del menú, nombre del método "agregar_xxx" que
    # dispara). Para agregar una marca nueva (Stonex, South, etc.) hace
    # falta, de punta a punta:
    #   1. Escribir su parser en un módulo nuevo sin dependencias de
    #      QGIS/PyQt (ver dc_parser.py/hitarget_parser.py/
    #      chcnav_parser.py como plantilla): looks_like_xxx(text),
    #      parse_xxx_file(path) -> XxxFile, con XxxFile.path/.points/
    #      .warnings/.n_points y un dataclass de punto con al menos
    #      name/lat/lon/height y un código de tipo/clasificación propio.
    #   2. Agregar self.xxx_files = [] en __init__ (junto a dc_files/
    #      hitarget_files/chcnav_files).
    #   3. Escribir agregar_xxx(self) siguiendo agregar_hitarget()/
    #      agregar_chcnav() como plantilla, y agregar su origen ("XXX")
    #      al if/elif de quitar_dc().
    #   4. Agregar una entrada aquí: (i18n key nueva del ítem del menú,
    #      "agregar_xxx") y sus i18n keys (ítem del menú, título de
    #      diálogo, filtro de archivos, resumen de log) en i18n.py.
    #   5. Extender previsualizar_dc() (guard "not self.xxx_files" +
    #      nuevo loop por-origen que arme una fila de `self._import_preview`)
    #      y subir_dc_preview() (agregar xxx_by_path junto a dc_by_path/
    #      hitarget_by_path/chcnav_by_path) con el nuevo origen "XXX".
    #   6. Si la marca usa un código de tipo/clasificación propio,
    #      agregar sus entradas a COLOR_POR_TIPO/LEGEND_KEY_POR_TIPO (y,
    #      si hace falta, una función `_xxx_tipo_code()` como
    #      `_hitarget_tipo_code`/`_chcnav_tipo_code`).
    _CAMPO_BRANDS = (
        ("menu_add_dc", "agregar_dc"),
        ("menu_add_hitarget", "agregar_hitarget"),
        ("menu_add_chcnav", "agregar_chcnav"),
        ("menu_add_stonex", "agregar_stonex"),
        ("menu_add_surpad", "agregar_surpad"),
        ("menu_add_sourcelink", "agregar_sourcelink"),
        ("menu_add_inova", "agregar_inova"),
    )

    def __init__(self, iface, project: QgsProject, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.project = project

        self.lang = i18n.DEFAULT_LANG
        self._i18n_widgets = []  # [(widget, key, kind, kwargs), ...] para retranslate_ui()

        self.db_path = None
        self.conn = None
        self.dc_files = []  # list[DCFile]
        self.hitarget_files = []  # list[hitarget_parser.HiTargetFile]
        self.chcnav_files = []  # list[chcnav_parser.ChcnavFile]
        self.stonex_files = []  # list[stonex_parser.StonexFile]
        # SurPad exporta un .rw5 de la misma familia de formato que
        # LandStar/CHCNav (mismos códigos de registro JB/MO/BP/LS/GPS),
        # así que se reutiliza el mismo `chcnav_parser.py` tal cual --
        # ver `agregar_surpad()` -- y por eso esta lista guarda también
        # objetos `chcnav_parser.ChcnavFile`, no un tipo propio.
        self.sourcelink_files = []  # list[sourcelink_parser.SourceLinkFile] (CSV de SourceLink con las posiciones de los vibros)
        # Modo compartido opcional (ver `shared_project.py`): None si el
        # proyecto abierto no es compartido; si lo es, la `SharedSession`
        # (editor con copia local + publicación, o lector de solo lectura).
        self._shared = None
        self._banners_solo_lectura = []  # QLabel rojos que avisan "SOLO LECTURA" en las pestañas que escriben
        self._shared_timer = QTimer(self)
        self._shared_timer.setInterval(60 * 1000)
        self._shared_timer.timeout.connect(self._on_shared_tick)
        app_qt = QApplication.instance()
        if app_qt is not None:
            # Al cerrar QGIS: publica los cambios pendientes y libera el bloqueo.
            app_qt.aboutToQuit.connect(self._al_cerrar_qgis)
        self.inova_files = []  # list[inova_parser.InovaFile] (.xls de Inova: COG de cada VP, ver agregar_inova)
        self.surpad_files = []  # list[chcnav_parser.ChcnavFile] (parseados con chcnav_parser, ver agregar_surpad)
        self._campo_file_refs = []  # [(origen, path), ...] alineado con self.lst_dc, origen: "DC"|"HITARGET"|"CHCNAV"|"STONEX"|"SURPAD"|"SOURCELINK"|"INOVA"
        # Topógrafo (Surveyor) escrito junto a cada archivo de campo cargado:
        # {(origen, path): texto}. Se llena desde el QLineEdit de cada fila
        # de `lst_dc` (ver `_agregar_item_campo`) y se usa al subir a
        # POSTPLOT para llenar la columna Surveyor de los puntos de ESE archivo.
        self._surveyor_por_archivo = {}
        # Subidas a POSTPLOT hechas desde "Importar datos de campo" que
        # todavía se pueden retirar, la más reciente al final: cada lote es
        # {"ids": [ID de POSTPLOT insertados], "keys": [(origen, path,
        # line_no) de las filas de la previsualización], "layer_id": id de
        # la capa de QGIS creada, o None}. Vacía = botón verde "Subir";
        # con algún lote = botón rojo "Subir/Retirar" (ver
        # `_actualizar_boton_subir`). Se vacía al cambiar de proyecto: los
        # ID sólo valen para la base de datos donde se insertaron.
        self._lotes_subidos = []
        self.design_points = []  # list[dict] con las coordenadas ya transformadas del "diseño" (CSV o PREPLOT)
        self._origen_diseno_label = ""  # texto para la columna Origen_Diseno al subir COMPARACION
        self.match_result = None
        self.preplot_generated_points = []  # list[PreplotPoint], último preplot generado
        self._preplot_track_azimuths = {}  # {track normalizado: azimut grados}, ver `_calcular_preplot_track_azimuths`

        # -- Levantamiento 2D/3D del proyecto (ver `_cargar_config_survey_guardada`/
        # `_resolver_azimut_linea`): guardado por proyecto igual que el CRS/geoide.
        self._survey_type = "2D"  # "2D" o "3D"
        self._survey_azimut_fuente = None  # grados 0-360, sólo si _survey_type == "3D"
        self._survey_azimut_receptora = None  # grados 0-360, sólo si _survey_type == "3D"
        self._survey_codigos_fuente = set()  # códigos Descriptor que clasifican como línea fuente
        self._survey_codigos_receptora = set()  # ídem, línea receptora
        self._preplot_ext_preview = []  # list[dict], puntos de preplot externo (SPS/CSV/.qld/capa QGIS) aún no subidos a PREPLOT
        self._preplot_gen_layer = None  # capa de memoria temporal del preplot generado a mano (ver generar_preplot)
        self._provisional_preplot_ext_layer = None  # capa de memoria temporal con self._preplot_ext_preview (ver _actualizar_capa_provisional_preplot_ext)
        self.query_columns = []  # columnas de la última consulta ejecutada en la pestaña 5
        self.query_rows = []  # filas (dict) de la última consulta ejecutada en la pestaña 5
        self._query_delete_table = None  # tabla borrable de la consulta actual (ver db_schema.deletable_table_and_where), o None si no aplica
        self._query_delete_where = None  # WHERE de la consulta actual, para armar el DELETE del botón "Borrar resultados"
        self._query_table_editable = False  # si `tbl_query` admite edición en línea (misma condición que el borrado + columnas validadas, ver ejecutar_consulta)
        self._query_pending_edits = {}  # {fila_en_query_rows: {columna: valor_nuevo}}, cambios de edición aún no guardados en la base (ver guardar_cambios_consulta)
        self._provisional_query_layer = None  # capa de memoria temporal con self.query_rows (ver _actualizar_capa_provisional_query)
        self._query_layer_row_ids = {}  # {fid_de_la_capa: ID_real_en_la_tabla}, sólo cuando la consulta actual es borrable
        self._last_counts = None  # (n_post, n_pre, n_comp) para poder re-renderizar al cambiar idioma
        self._last_preplot_summary = None  # (n, modo_key) para poder re-renderizar al cambiar idioma

        self._import_preview = []  # list[dict], puntos parseados del .dc aún no subidos (ver previsualizar_dc())
        self._import_geoid_applied = False
        self._import_geoid_file_name = None
        self._last_import_preview_summary = None  # (n, matched, within, had_preplot) para re-renderizar al cambiar idioma
        self._preview_filtro_ids = None  # set de índices de `_import_preview` que cumplen la consulta actual, o None si no hay filtro activo (ver `_ejecutar_filtro_preview`)

        # -- Corrección de base RTK libre -> corregida (opcional, ver la
        # nota junto a `CORR_BASE_COL_ARCHIVO`): `_base_corrections` es la
        # única fuente de verdad de qué corrección aplicar, guardada por
        # (origen, archivo_path, nombre_ORIGINAL de la base -- nunca el
        # nombre editado en la tabla de previsualización, para que
        # renombrar un punto no rompa la asociación) -> {"lat", "lon",
        # "altura_wgs84" (o None si no se corrigió la altura)}. Se aplica
        # de nuevo, desde cero, cada vez que se llama `previsualizar_dc()`
        # (ver `_aplicar_correcciones_base_a_filas`), así que sobrevive a
        # agregar otro archivo o volver a previsualizar sin necesidad de
        # guardar el valor ya corregido dentro de `_import_preview`.
        # `_base_correction_rows` es la lista paralela (alineada por fila)
        # con los metadatos de cada fila de `tbl_correccion_base` --
        # mismo patrón que `_import_preview`/`tbl_import_preview`.
        self._base_corrections = {}
        self._base_correction_rows = []
        self._provisional_preview_layer = None  # capa de memoria temporal creada por previsualizar_dc() (ver _actualizar_capa_provisional_preview)
        self._filtro_preview_layer = None  # capa de memoria temporal con el SUBCONJUNTO filtrado (ver _mostrar_filtro_preview_en_mapa) -- separada de _provisional_preview_layer para no chocar entre sí
        self._provisional_preplot_match_layer = None  # capa de memoria temporal con el punto de PREPLOT de cada match (ver _actualizar_capas_desplazamiento_preview)
        self._provisional_desplazamiento_layer = None  # capa de memoria temporal con la línea preplot->levantado de cada match (ver _actualizar_capas_desplazamiento_preview)

        self.geoid_path = None
        self.geoid_layer = None  # QgsRasterLayer del geoide asignado al proyecto, o None
        self.geoid_ggf = None  # ggf_reader.GgfGrid si el geoide es un .ggf de Trimble, o None

        self._factor_escala_calculado = None  # (factor_proyeccion, convergencia, factor_elevacion, factor_combinado) del último "Calcular", o None -- ver guardar_factor_escala_proyecto
        self._factor_escala_map_tool = None  # QgsMapToolEmitPoint activo mientras se espera el clic de "Usar clic en el mapa...", o None
        self._factor_escala_prev_map_tool = None  # herramienta del canvas antes de activar la de arriba, para restaurarla después del clic

        self.crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        self._windows = {}  # clave de sección -> (_SectionWindow, clave_i18n_del_título)
        self._build_windows()

    # ------------------------------------------------------------------
    # Traducción / idioma
    # ------------------------------------------------------------------
    def t(self, key, **kwargs):
        return i18n.t(self.lang, key, **kwargs)

    def _reg(self, widget, key, kind="text", **kwargs):
        """Registra un widget "estático" (título/etiqueta/botón/tooltip/
        placeholder) para que `retranslate_ui()` lo pueda volver a
        traducir, y le aplica la traducción actual de una vez."""
        self._i18n_widgets.append((widget, key, kind, kwargs))
        self._apply_i18n(widget, key, kind, kwargs)
        return widget

    def _apply_i18n(self, widget, key, kind, kwargs):
        text = i18n.t(self.lang, key, **kwargs)
        if kind == "text":
            widget.setText(text)
        elif kind == "title":
            widget.setTitle(text)
        elif kind == "placeholder":
            widget.setPlaceholderText(text)
        elif kind == "tooltip":
            widget.setToolTip(text)

    def _form_row(self, form: QFormLayout, key, field_widget):
        label = self._reg(QLabel(), key)
        form.addRow(label, field_widget)
        return label

    def _agregar_boton_ayuda(self, v: QVBoxLayout, help_keys, titulo_key):
        """Agrega, arriba a la derecha del contenido de una pestaña, un
        botón "?" que muestra en un diálogo aparte los textos
        explicativos que antes ocupaban espacio fijo en la propia
        pestaña (ver `_mostrar_ayuda`).

        No se puede poner este botón pegado a los de minimizar/
        maximizar/cerrar de la ventana: esos son nativos de Windows,
        activados con flags de Qt sobre la barra de título del sistema
        (ver `_SectionWindow.__init__`), no botones propios del plugin
        -- Qt no tiene forma de agregar un botón de más ahí sin
        reemplazar toda la barra de título nativa por una hecha a mano
        (cambio mucho más grande y con más riesgo de romper arrastrar/
        mover/maximizar/aparecer en la barra de tareas). Puesto arriba
        a la derecha del contenido se logra el mismo objetivo: liberar
        el espacio fijo que ocupaban esos textos, reorganizando el
        resto de los controles hacia arriba."""
        fila = QHBoxLayout()
        fila.addStretch(1)
        btn_ayuda = self._crear_boton_ayuda(help_keys, titulo_key)
        fila.addWidget(btn_ayuda)
        v.insertLayout(0, fila)
        return btn_ayuda

    def _crear_boton_ayuda(self, help_keys, titulo_key):
        """El botón "?" en sí (sin colocarlo): lo usan `_agregar_boton_ayuda`
        y la esquina de la barra de pestañas de Preplot Sísmico."""
        btn_ayuda = QPushButton("?")
        btn_ayuda.setFixedSize(24, 24)
        self._reg(btn_ayuda, "btn_help_tooltip", kind="tooltip")
        btn_ayuda.clicked.connect(lambda: self._mostrar_ayuda(titulo_key, help_keys))
        return btn_ayuda

    def _mostrar_ayuda(self, titulo_key, help_keys):
        """Diálogo de ayuda genérico (ver `_agregar_boton_ayuda`):
        concatena la traducción ACTUAL (se relee cada vez que se abre,
        así que respeta un cambio de idioma posterior) de cada clave de
        `help_keys`, separadas por una línea en blanco, en una ventana
        aparte de sólo lectura y con scroll."""
        dlg = QDialog(self)
        dlg.setWindowTitle(self.t(titulo_key))
        lay = QVBoxLayout(dlg)
        texto = QPlainTextEdit()
        texto.setReadOnly(True)
        texto.setPlainText("\n\n".join(self.t(k) for k in help_keys))
        texto.setMinimumSize(480, 360)
        lay.addWidget(texto)
        btn_cerrar = QPushButton(self.t("btn_close"))
        btn_cerrar.clicked.connect(dlg.accept)
        lay.addWidget(btn_cerrar, alignment=_valor_enum(Qt, "AlignRight", "AlignmentFlag"))
        # PyQt5 expone QDialog.exec_() (y, desde 5.11, también exec()); en
        # PyQt6 sólo existe exec(). Se usa el que esté disponible.
        (dlg.exec if hasattr(dlg, "exec") else dlg.exec_)()

    def set_language(self, lang):
        """Llamado desde el combo de idioma del toolbar
        (`gnsseismic.py`), no desde un widget propio del controlador."""
        if not lang or lang == self.lang:
            return
        self.lang = lang
        self.retranslate_ui()

    def retranslate_ui(self):
        self._retranslate_window_titles()
        for widget, key, kind, kwargs in self._i18n_widgets:
            self._apply_i18n(widget, key, kind, kwargs)

        self._fill_descriptor_combo(self.cb_grilla_descriptor)
        self._fill_descriptor_combo(self.cb_linea_descriptor)
        self._fill_query_preset_combo(keep_selection=True)
        if hasattr(self, "cb_cmp_query_a"):
            self._fill_cmp_query_combos(keep_selection=True)
            self._actualizar_resumen_cmp_sql()
        self._fill_export_format_combo(keep_selection=True)
        self._actualizar_visibilidad_opciones_sps()
        self._render_query_resumen()
        self._fill_export_preview_format_combo(keep_selection=True)
        self._fill_bulk_campo_combo(keep_selection=True)
        self._fill_preview_filter_preset_combo(keep_selection=True)
        self._fill_filtro_wizard_combos(keep_selection=True)

        self.tbl_resultado.setHorizontalHeaderLabels(self._comparar_headers())
        if self.match_result is not None:
            self._llenar_tabla_resultado(self.match_result)

        self._retranslate_tabla_preview()

        if hasattr(self, "btn_subir_dc"):
            self._actualizar_boton_subir()

        if hasattr(self, "btn_toggle_log_importar"):
            self._actualizar_texto_boton_log_importar()

        self._actualizar_resumen_acordeones()
        if hasattr(self, "btn_sql_dev"):
            self._actualizar_texto_boton_sql_dev()
            self._actualizar_lbl_filtro_actual()

        if hasattr(self, "btn_toggle_config_proyecto"):
            self._actualizar_texto_boton_config_proyecto()

        self._actualizar_ui_compartido()

        if hasattr(self, "lbl_filtro_preview_resumen") and self._preview_filtro_ids is not None:
            self.lbl_filtro_preview_resumen.setText(
                self.t("lbl_preview_filter_summary", n=len(self._preview_filtro_ids), total=len(self._import_preview))
            )

        if hasattr(self, "tbl_correccion_base"):
            borrador = self._leer_borrador_correccion_base_desde_tabla()
            self.tbl_correccion_base.setHorizontalHeaderLabels(self._correccion_base_headers())
            self._actualizar_seccion_correccion_base(borrador)

        self.tbl_preplot_ext_preview.setHorizontalHeaderLabels(self._ext_preview_headers())
        if self._preplot_ext_preview:
            self._sync_preplot_ext_desde_tabla()
            self._llenar_tabla_preplot_ext()
        self._render_preplot_ext_resumen()
        self._retraducir_pestanas_preplot()
        self.tbl_preplot_gen_preview.setHorizontalHeaderLabels(self._gen_preview_headers())
        self._llenar_tabla_preplot_gen()
        self._actualizar_texto_boton_log_preplot()

        self._render_counts_label()
        self._render_preplot_label()
        self._toggle_fuente_diseno()
        self._actualizar_chk_geoid_importar()

    def _retranslate_window_titles(self):
        for win, title_key in self._windows.values():
            win.setWindowTitle(self.t(title_key))

    # ------------------------------------------------------------------
    # Construcción de la interfaz: una ventana no modal por sección
    # ------------------------------------------------------------------
    def _build_windows(self):
        secciones = [
            ("proyecto", self._build_tab_proyecto, "tab1_title"),
            ("preplot", self._build_tab_preplot, "tab2_title"),
            ("importar", self._build_tab_importar, "tab3_title"),
            ("comparar", self._build_tab_comparar, "tab4_title"),
            ("bd", self._build_tab_bd, "tab5_title"),
        ]
        parent_window = self.iface.mainWindow() if self.iface is not None else None
        for key, builder, title_key in secciones:
            content = builder()
            win = _SectionWindow(content, parent=parent_window)
            win.setWindowTitle(self.t(title_key))
            self._ajustar_tamano_ventana(win, content)
            self._windows[key] = (win, title_key)

    _ANCHO_MAX_RECUADRO = 520  # px: tope del ancho que se le exige a cada recuadro de una fila de 2

    def _ajustar_tamano_ventana(self, win, content):
        """Dimensiona la ventana de una sección a lo que su propio
        contenido necesita, en vez de un tamaño fijo grande igual para
        las cinco -- antes todas abrían a 950x720 sin importar cuánto
        contenido tuvieran, lo que en pantallas más chicas tapaba casi
        toda la pantalla.

        Se usa `content.sizeHint()` (el widget de la sección, ANTES de
        meterlo en el QScrollArea de `_SectionWindow`) en vez de
        `win.adjustSize()`: el sizeHint de un QScrollArea vacío de
        contexto es un tamaño genérico chico que no refleja el
        contenido real, así que dimensionar por ahí dejaba las cinco
        ventanas con la misma altura chica sin importar cuánto
        contenido tuvieran (el problema opuesto al de antes). Con el
        sizeHint del contenido, cada ventana vuelve a abrir según lo que
        necesita; si aun así quedara más grande que el 90% de la
        pantalla disponible (una sección con mucho contenido, como
        Preplot Sísmico desde que se le agregó "Importar preplot
        externo" en la v2.6.0), se recorta a ese 90% y el sobrante queda
        accesible con la barra de desplazamiento del QScrollArea en vez
        de tapar la pantalla. Sigue siendo una ventana redimensionable a
        mano."""
        deseado = content.sizeHint().expandedTo(content.minimumSizeHint())
        ancho = deseado.width() + 24  # margen para el borde/barra del scroll area
        alto = deseado.height() + 24
        # Causa del "primer arranque desordenado" (importar datos de campo):
        # los recuadros que se acomodan de a 2 por fila usan
        # `QSizePolicy.Ignored` (para repartir 50/50), y un widget Ignored
        # NO aporta su ancho al `sizeHint` del contenido; el sizeHint
        # quedaba entonces mucho más angosto que lo que necesitan dos
        # recuadros lado a lado y la ventana abría con botones y etiquetas
        # recortados ("gregar", "impia", "Co"...). Se calcula el ancho
        # que de verdad necesitan (el recuadro Ignored más ancho, tope
        # `_ANCHO_MAX_RECUADRO`, x2 + márgenes) y se usa como ancho de
        # apertura y como ancho MÍNIMO del contenido: si el usuario achica
        # la ventana, aparece la barra de desplazamiento horizontal del
        # QScrollArea en vez de aplastar los botones.
        ancho_recuadro = 0
        for g in content.findChildren(QGroupBox):
            if g.sizePolicy().horizontalPolicy() == SIZE_POLICY_IGNORED:
                ancho_recuadro = max(ancho_recuadro, min(g.sizeHint().width(), self._ANCHO_MAX_RECUADRO))
        if ancho_recuadro:
            ancho_min = 2 * ancho_recuadro + 80
            content.setMinimumWidth(ancho_min)
            ancho = max(ancho, ancho_min + 24)
        try:
            screen = win.screen() if hasattr(win, "screen") else None
            if screen is None:
                screen = QApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else None
        except Exception:
            area = None
        if area is not None and area.width() > 0 and area.height() > 0:
            ancho = min(ancho, int(area.width() * 0.9))
            alto = min(alto, int(area.height() * 0.9))
        win.resize(max(ancho, 1), max(alto, 1))

    def show_window(self, key):
        """Abre (o trae al frente, si ya estaba abierta) la ventana de la
        sección `key` ("proyecto"/"preplot"/"importar"/"comparar"/"bd").
        Llamado desde el ícono correspondiente del toolbar."""
        entry = self._windows.get(key)
        if entry is None:
            return
        win, _title_key = entry
        win.show()
        win.raise_()
        win.activateWindow()

    def close_all_windows(self):
        """Cierra las cinco ventanas de sección (llamado al descargar el
        plugin, `GNSSeismicPlugin.unload()`)."""
        # Un proyecto compartido abierto publica lo pendiente y libera su
        # bloqueo al descargar/recargar el plugin.
        self._cerrar_sesion_compartida(cerrar_conexion=True)
        for win, _title_key in self._windows.values():
            win.close()

    # -- Sección: Proyecto -------------------------------------------------
    def _build_tab_proyecto(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)

        # -- Barra superior (rediseño v2.64.0): gestión del proyecto en una
        # fila compacta. Izquierda: botones de texto corto con glifo
        # (Nuevo / Abrir / Mis proyectos / Actualizar). Derecha: "badges" de
        # colores con el balance del proyecto (POSTPLOT / PREPLOT /
        # COMPARACION) y el botón de ayuda "?". Debajo, en texto chico, la
        # ruta de la base SQLite resumida (completa en el tooltip).
        fila_barra = QHBoxLayout()
        fila_barra.setSpacing(4)
        for key_texto, key_tip, handler in (
            ("tb_proj_new", "btn_new_project", self.crear_proyecto),
            ("tb_proj_open", "btn_open_project", self.abrir_proyecto),
            ("tb_proj_switch", "btn_switch_project", self.abrir_selector_proyectos),
            ("tb_proj_refresh", "btn_refresh_counts", self.actualizar_conteos),
        ):
            tb = QToolButton()
            tb.setStyleSheet(ESTILO_BTN_BARRA)
            self._reg(tb, key_texto)
            self._reg(tb, key_tip, kind="tooltip")
            tb.clicked.connect(lambda _checked=False, h=handler: h())
            fila_barra.addWidget(tb)
        fila_barra.addStretch(1)
        self.badge_postplot = QLabel()
        self.badge_preplot = QLabel()
        self.badge_comparacion = QLabel()
        for badge, color, tip in (
            (self.badge_postplot, "#2e7d32", "tip_badge_post"),
            (self.badge_preplot, "#1565c0", "tip_badge_pre"),
            (self.badge_comparacion, "#ef6c00", "tip_badge_comp"),
        ):
            badge.setStyleSheet(_estilo_badge(color))
            self._reg(badge, tip, kind="tooltip")
            fila_barra.addWidget(badge)
        btn_ayuda = QPushButton("?")
        btn_ayuda.setFixedSize(24, 24)
        self._reg(btn_ayuda, "btn_help_tooltip", kind="tooltip")
        btn_ayuda.clicked.connect(
            lambda: self._mostrar_ayuda("tab1_title", ["crs_saved_note", "note_factor_escala", "geoid_info", "note_survey_3d"])
        )
        fila_barra.addWidget(btn_ayuda)
        v.addLayout(fila_barra)

        self.lbl_db_path = EtiquetaElidida()
        self.lbl_db_path.setStyleSheet(ESTILO_ROTULO_TENUE + " font-size: 11px;")
        self._reg(self.lbl_db_path, "db_path_placeholder", kind="placeholder")
        v.addWidget(self.lbl_db_path)

        # Línea de error de los conteos (normalmente oculta).
        self.lbl_conteos = QLabel("")
        self.lbl_conteos.setWordWrap(True)
        self.lbl_conteos.setStyleSheet("color: #c62828;")
        self.lbl_conteos.setVisible(False)
        v.addWidget(self.lbl_conteos)
        self._render_counts_label()

        # -- Proyecto compartido (OPCIONAL): varias oficinas ven/editan el
        # mismo proyecto a través de una carpeta sincronizada o de red --
        # ver `shared_project.py`. Un solo editor a la vez; los demás en
        # solo lectura. Ahora es un interruptor (On/Off) con un ícono (i)
        # cuyo tooltip trae la explicación que antes ocupaba un bloque de
        # texto fijo; los botones de acción sólo aparecen según el rol.
        grp_shared = self._reg(QGroupBox(), "grp_shared", kind="title")
        grp_shared.setObjectName("card")
        v_shared = QVBoxLayout(grp_shared)
        fila_toggle = QHBoxLayout()
        self.chk_shared_enable = self._reg(ToggleSwitch(), "chk_shared_enable")
        self.chk_shared_enable.clicked.connect(self._on_toggle_compartir)
        fila_toggle.addWidget(self.chk_shared_enable)
        fila_toggle.addWidget(self._crear_icono_info("shared_info_tip"))
        fila_toggle.addStretch(1)
        self.btn_shared_publish = self._reg(QPushButton(), "btn_shared_publish")
        self.btn_shared_publish.clicked.connect(self.publicar_ahora)
        self.btn_shared_release = self._reg(QPushButton(), "btn_shared_release")
        self.btn_shared_release.clicked.connect(self.dejar_de_editar)
        self.btn_shared_takeover = self._reg(QPushButton(), "btn_shared_takeover")
        self.btn_shared_takeover.clicked.connect(self.tomar_control)
        self.btn_shared_refresh = self._reg(QPushButton(), "btn_shared_refresh")
        self.btn_shared_refresh.clicked.connect(self.actualizar_lector)
        for b in (self.btn_shared_publish, self.btn_shared_release,
                  self.btn_shared_takeover, self.btn_shared_refresh):
            fila_toggle.addWidget(b)
        v_shared.addLayout(fila_toggle)
        self.lbl_shared_estado = QLabel()
        self.lbl_shared_estado.setWordWrap(True)
        v_shared.addWidget(self.lbl_shared_estado)
        v.addWidget(grp_shared)
        self._actualizar_ui_compartido()

        # Pedido explícito del usuario (con una captura de la pestaña
        # "Proyecto"): dejar siempre visible sólo la parte de arriba y,
        # debajo, un botón que despliega/oculta todo lo demás (CRS, factor
        # de escala, tipo de levantamiento, geoide) -- ese bloque sólo
        # hace falta ver al configurar un proyecto nuevo o corregir uno
        # existente. Mismo mecanismo que el "Registro" de "Importar datos
        # de campo": un botón con forma de interruptor (`setCheckable`)
        # muestra/oculta un contenedor. Oculto por defecto;
        # `crear_proyecto()` lo despliega solo al terminar de crear un
        # proyecto nuevo, que es justo cuando hace falta revisarlo.
        self.btn_toggle_config_proyecto = QPushButton()
        self.btn_toggle_config_proyecto.setCheckable(True)
        self.btn_toggle_config_proyecto.setChecked(False)
        v.addWidget(self.btn_toggle_config_proyecto)

        self.config_proyecto_widget = QWidget()
        v_config_proyecto = QVBoxLayout(self.config_proyecto_widget)
        v_config_proyecto.setContentsMargins(0, 0, 0, 0)
        self.config_proyecto_widget.setVisible(False)
        self.btn_toggle_config_proyecto.toggled.connect(self.config_proyecto_widget.setVisible)
        self.btn_toggle_config_proyecto.toggled.connect(lambda _checked: self._actualizar_texto_boton_config_proyecto())
        self._actualizar_texto_boton_config_proyecto()
        v.addWidget(self.config_proyecto_widget)

        # -- Dos columnas simétricas e independientes ---------------------
        # Izquierda: Configuración Geográfica (CRS + Geoide).
        # Derecha: Factor de Escala + Tipo de Levantamiento.
        grp_geo = self._reg(QGroupBox(), "grp_config_geografica", kind="title")
        grp_geo.setObjectName("card")
        v_geo = QVBoxLayout(grp_geo)

        lbl_crs = self._reg(QLabel(), "lbl_crs_title")
        lbl_crs.setStyleSheet(ESTILO_SUBTITULO)
        self._reg(lbl_crs, "grp_crs", kind="tooltip")
        v_geo.addWidget(lbl_crs)
        if QgsProjectionSelectionWidget is not None:
            self.crs_widget = QgsProjectionSelectionWidget()
            self.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:9377"))  # MAGNA-SIRGAS / Origen-Nacional (Colombia)
            v_geo.addWidget(self.crs_widget)
            # El CRS se guarda con el proyecto (ProjectSettings) y se
            # recupera solo al abrir/crear/cambiar de proyecto -- ver
            # `_guardar_crs_actual`/`_cargar_crs_guardado`. A propósito NO
            # se guarda con cada cambio del selector (`crsChanged`): este
            # widget es único y compartido por todas las secciones, así
            # que guardar en cada cambio, tocándolo para PREPARAR un
            # proyecto nuevo (crear uno para Argentina mientras el de
            # Colombia sigue abierto), pisaría sin darse cuenta el CRS ya
            # guardado del proyecto abierto -- se probó en vivo y pasaba
            # exactamente eso. Se guarda con el botón general "Aplicar
            # configuración" del fondo (y automáticamente en "Nuevo
            # proyecto...", que usa el CRS elegido en ese momento).
        else:
            self.crs_widget = None
            v_geo.addWidget(self._reg(QLabel(), "crs_widget_unavailable"))

        v_geo.addSpacing(10)
        lbl_geoide = self._reg(QLabel(), "grp_geoid")
        lbl_geoide.setStyleSheet(ESTILO_SUBTITULO)
        v_geo.addWidget(lbl_geoide)
        # Campo de texto de sólo lectura con acciones DENTRO del campo:
        # carpeta (explorar el archivo del geoide: .grd, .gtx, .ggf...) y,
        # sólo si hay uno asignado, una "x" para quitarlo.
        self.lbl_geoid_path = QLineEdit()
        self.lbl_geoid_path.setReadOnly(True)
        self._reg(self.lbl_geoid_path, "geoid_path_placeholder", kind="placeholder")
        trailing = _valor_enum(QLineEdit, "TrailingPosition", "ActionPosition")
        estilo_app = QApplication.style()
        act_explorar = QAction(self.lbl_geoid_path)
        act_explorar.setIcon(estilo_app.standardIcon(_valor_enum(QStyle, "SP_DirOpenIcon", "StandardPixmap")))
        self._reg(act_explorar, "btn_load_geoid", kind="tooltip")
        act_explorar.triggered.connect(lambda _c=False: self.cargar_geoide())
        self.lbl_geoid_path.addAction(act_explorar, trailing)
        self._act_geoide_quitar = QAction(self.lbl_geoid_path)
        self._act_geoide_quitar.setIcon(estilo_app.standardIcon(_valor_enum(QStyle, "SP_TitleBarCloseButton", "StandardPixmap")))
        self._reg(self._act_geoide_quitar, "btn_clear_geoid", kind="tooltip")
        self._act_geoide_quitar.triggered.connect(lambda _c=False: self.quitar_geoide())
        self.lbl_geoid_path.addAction(self._act_geoide_quitar, trailing)
        self._act_geoide_quitar.setVisible(False)
        self.lbl_geoid_path.textChanged.connect(lambda t: self._act_geoide_quitar.setVisible(bool(t)))
        v_geo.addWidget(self.lbl_geoid_path)
        v_geo.addStretch(1)

        grp_fs = self._reg(QGroupBox(), "grp_config_factor_survey", kind="title")
        grp_fs.setObjectName("card")
        v_fs = QVBoxLayout(grp_fs)

        lbl_factor = self._reg(QLabel(), "lbl_factor_title")
        lbl_factor.setStyleSheet(ESTILO_SUBTITULO)
        self._reg(lbl_factor, "grp_factor_escala", kind="tooltip")
        v_fs.addWidget(lbl_factor)

        # Latitud / Longitud / Altura: tres campos pequeños en UNA fila.
        grid_factor = QGridLayout()
        grid_factor.setHorizontalSpacing(6)
        grid_factor.setVerticalSpacing(1)
        for col in range(3):
            grid_factor.setColumnStretch(col, 1)
        for col, key in enumerate(("fe_cap_lat", "fe_cap_lon", "fe_cap_alt")):
            cap = self._reg(QLabel(), key)
            cap.setStyleSheet(ESTILO_ROTULO_TENUE)
            grid_factor.addWidget(cap, 0, col)
        self.spin_factor_escala_lat = QDoubleSpinBox()
        self.spin_factor_escala_lat.setDecimals(8)
        self.spin_factor_escala_lat.setRange(-90.0, 90.0)
        grid_factor.addWidget(self.spin_factor_escala_lat, 1, 0)
        self.spin_factor_escala_lon = QDoubleSpinBox()
        self.spin_factor_escala_lon.setDecimals(8)
        self.spin_factor_escala_lon.setRange(-180.0, 180.0)
        grid_factor.addWidget(self.spin_factor_escala_lon, 1, 1)
        self.spin_factor_escala_altura = QDoubleSpinBox()
        self.spin_factor_escala_altura.setDecimals(2)
        self.spin_factor_escala_altura.setRange(-1000.0, 9000.0)
        self.spin_factor_escala_altura.setSuffix(" m")
        self._reg(self.spin_factor_escala_altura, "tip_factor_escala_altura", kind="tooltip")
        grid_factor.addWidget(self.spin_factor_escala_altura, 1, 2)
        v_fs.addLayout(grid_factor)

        # Barra de acciones compacta justo debajo de los números.
        fila_factor = QHBoxLayout()
        fila_factor.setSpacing(4)
        for key_texto, key_tip, handler in (
            ("tb_fe_map", "btn_click_mapa_factor_escala", self._iniciar_click_mapa_factor_escala),
            ("tb_fe_calc", "btn_calcular_factor_escala", self._calcular_factor_escala_proyecto),
            ("tb_fe_save", "btn_save_factor_escala", self.guardar_factor_escala_proyecto),
        ):
            tb = QToolButton()
            tb.setStyleSheet(ESTILO_BTN_BARRA)
            self._reg(tb, key_texto)
            self._reg(tb, key_tip, kind="tooltip")
            tb.clicked.connect(lambda _checked=False, h=handler: h())
            fila_factor.addWidget(tb)
        fila_factor.addStretch(1)
        v_fs.addLayout(fila_factor)

        self.lbl_factor_escala_status = QLabel("")
        self.lbl_factor_escala_status.setWordWrap(True)
        v_fs.addWidget(self.lbl_factor_escala_status)
        self.lbl_factor_escala_resultado = QLabel(self.t("status_factor_escala_sin_calcular"))
        self.lbl_factor_escala_resultado.setWordWrap(True)
        v_fs.addWidget(self.lbl_factor_escala_resultado)

        linea = QFrame()
        linea.setFrameShape(_valor_enum(QFrame, "HLine", "Shape"))
        linea.setFrameShadow(_valor_enum(QFrame, "Sunken", "Shadow"))
        v_fs.addWidget(linea)

        # Tipo de levantamiento (2D/3D) al final de la columna. Si es 3D se
        # muestran además los azimutes y códigos Descriptor de línea
        # fuente/receptora (`_actualizar_visibilidad_campos_survey_3d`).
        lbl_survey = self._reg(QLabel(), "grp_survey_type")
        lbl_survey.setStyleSheet(ESTILO_SUBTITULO)
        v_fs.addWidget(lbl_survey)
        form_survey = QFormLayout()
        self.cb_survey_type = QComboBox()
        self.cb_survey_type.addItem(self.t("opt_survey_2d"), "2D")
        self.cb_survey_type.addItem(self.t("opt_survey_3d"), "3D")
        self.cb_survey_type.currentIndexChanged.connect(self._actualizar_visibilidad_campos_survey_3d)
        self._lbl_survey_type = self._form_row(form_survey, "lbl_survey_type", self.cb_survey_type)

        self.spin_survey_az_fuente = QDoubleSpinBox()
        self.spin_survey_az_fuente.setRange(0.0, 360.0)
        self.spin_survey_az_fuente.setDecimals(3)
        self.spin_survey_az_fuente.setSuffix(" °")
        self._lbl_survey_az_fuente = self._form_row(form_survey, "lbl_survey_az_fuente", self.spin_survey_az_fuente)

        self.spin_survey_az_receptora = QDoubleSpinBox()
        self.spin_survey_az_receptora.setRange(0.0, 360.0)
        self.spin_survey_az_receptora.setDecimals(3)
        self.spin_survey_az_receptora.setSuffix(" °")
        self._lbl_survey_az_receptora = self._form_row(form_survey, "lbl_survey_az_receptora", self.spin_survey_az_receptora)

        self.txt_survey_cod_fuente = QLineEdit()
        self.txt_survey_cod_fuente.setText(_SURVEY_CODIGOS_FUENTE_DEFECTO)
        self._reg(self.txt_survey_cod_fuente, "tip_survey_cod_placeholder", kind="placeholder")
        self._lbl_survey_cod_fuente = self._form_row(form_survey, "lbl_survey_cod_fuente", self.txt_survey_cod_fuente)

        self.txt_survey_cod_receptora = QLineEdit()
        self.txt_survey_cod_receptora.setText(_SURVEY_CODIGOS_RECEPTORA_DEFECTO)
        self._reg(self.txt_survey_cod_receptora, "tip_survey_cod_placeholder", kind="placeholder")
        self._lbl_survey_cod_receptora = self._form_row(form_survey, "lbl_survey_cod_receptora", self.txt_survey_cod_receptora)
        v_fs.addLayout(form_survey)
        v_fs.addStretch(1)
        self._actualizar_visibilidad_campos_survey_3d()

        for g in (grp_geo, grp_fs):
            g.setSizePolicy(SIZE_POLICY_IGNORED, g.sizePolicy().verticalPolicy())
        grid_config = QGridLayout()
        grid_config.setColumnStretch(0, 1)
        grid_config.setColumnStretch(1, 1)
        grid_config.setHorizontalSpacing(10)
        grid_config.addWidget(grp_geo, 0, 0)
        grid_config.addWidget(grp_fs, 0, 1)
        v_config_proyecto.addLayout(grid_config)

        # Botón general "Aplicar configuración" al fondo: guarda con ESTE
        # proyecto el CRS y el tipo de levantamiento elegidos (reemplaza a
        # los botones "Guardar CRS..." y "Guardar configuración de
        # levantamiento"). El geoide se guarda al elegirlo y el factor de
        # escala con su propio botón "Guardar factor".
        fila_aplicar = QHBoxLayout()
        fila_aplicar.addStretch(1)
        self.btn_aplicar_config = self._reg(QPushButton(), "btn_aplicar_config")
        self._reg(self.btn_aplicar_config, "tip_btn_aplicar_config", kind="tooltip")
        self.btn_aplicar_config.setStyleSheet(ESTILO_BTN_PRIMARIO)
        self.btn_aplicar_config.setMinimumWidth(180)
        self.btn_aplicar_config.clicked.connect(self.aplicar_configuracion_proyecto)
        fila_aplicar.addWidget(self.btn_aplicar_config)
        v_config_proyecto.addLayout(fila_aplicar)

        w.setStyleSheet(ESTILO_TARJETAS)
        v.addStretch()
        return w

    @staticmethod
    def _tooltip_html(texto, ancho=360):
        """Tooltip con ajuste de línea (Qt sólo ajusta los de texto rico)."""
        return f"<table width='{ancho}'><tr><td>{texto}</td></tr></table>"

    def _crear_icono_info(self, tip_key):
        """Ícono (i) redondo cuyo tooltip (clave `tip_key`, ya en HTML)
        reemplaza a un bloque de texto explicativo de espacio fijo."""
        lbl = QLabel("i")
        lbl.setFixedSize(18, 18)
        lbl.setAlignment(_valor_enum(Qt, "AlignCenter", "AlignmentFlag"))
        lbl.setStyleSheet(
            "QLabel { border: 1px solid palette(mid); border-radius: 9px; font-weight: bold; font-style: italic; }"
        )
        lbl.setCursor(_valor_enum(Qt, "WhatsThisCursor", "CursorShape"))
        self._reg(lbl, tip_key, kind="tooltip")
        return lbl

    def _on_toggle_compartir(self, marcado):
        """Interruptor "Habilitar proyecto compartido en la nube"."""
        if marcado:
            self.compartir_proyecto_actual()
        else:
            self.dejar_de_compartir()
        # Si el usuario canceló el diálogo (o el modo no cambió), el
        # interruptor vuelve a reflejar el estado real.
        self._actualizar_ui_compartido()

    @_escritura()
    def aplicar_configuracion_proyecto(self):
        """Botón general "Aplicar configuración": valida el tipo de
        levantamiento (si es 3D, azimutes y códigos completos) y, sólo si
        todo está bien, guarda con ESTE proyecto el CRS de trabajo y el
        tipo de levantamiento elegidos."""
        if not self._require_project():
            return
        ok, msg = self._guardar_config_survey_actual()
        if not ok:
            QMessageBox.warning(self, self.t("err_title"), msg)
            return
        self._guardar_crs_actual()
        crs = self.crs_widget.crs() if self.crs_widget is not None else self.crs_wgs84
        QMessageBox.information(
            self, self.t("ok_title"),
            self.t("msg_config_applied", crs=crs.authid() or crs.description(), tipo=self.cb_survey_type.currentData()),
        )

    def _actualizar_texto_boton_config_proyecto(self):
        key = "btn_config_proyecto_hide" if self.btn_toggle_config_proyecto.isChecked() else "btn_config_proyecto_show"
        self.btn_toggle_config_proyecto.setText(self.t(key))

    def _working_crs(self) -> QgsCoordinateReferenceSystem:
        if self.crs_widget is not None:
            crs = self.crs_widget.crs()
            if crs.isValid():
                return crs
        return self.crs_wgs84

    def _zoom_canvas_a_capa(self, layer):
        """Centra el canvas de QGIS en la extensión de `layer` (usado por
        todas las capas provisionales/de resultado que crea el plugin --
        Preplot Sísmico, Importar datos de campo, Comparar, Base de
        Datos). `QgsMapCanvas.setExtent()` interpreta el `QgsRectangle`
        que recibe en el CRS ACTUAL del canvas, no en el de la capa --
        pasarle `layer.extent()` sin transformar (como se hacía antes de
        la v2.18.0) deja el canvas centrándose en coordenadas sin
        sentido cuando el canvas está en un CRS distinto al de la capa.
        Esto pasa fácil en este plugin porque nunca se cambia el CRS del
        PROYECTO de QGIS en sí (`QgsProject.instance().crs()`, el que usa
        el canvas) -- sólo el "CRS de trabajo" que elige el usuario en el
        selector del plugin (`_working_crs()`), usado para crear estas
        capas. Si el proyecto de QGIS se quedó en su CRS por defecto
        (frecuentemente EPSG:4326) mientras el usuario trabaja en un CRS
        proyectado (EPSG:9377, EPSG:5344, etc.), la extensión de la capa
        viene en metros y el canvas la interpreta como si fueran grados
        -- la capa se ve igual de bien dibujada en el lugar correcto
        (QGIS la reproyecta sola al dibujarla), pero la vista no se
        mueve ahí. Bug real reportado por el usuario en la sección Base
        de Datos, corregido en la v2.18.0 acá y en los otros cinco
        lugares del archivo que centraban la vista de la misma forma."""
        canvas = self.iface.mapCanvas()
        extent = _transform_extent(
            layer.extent(), layer.crs(), canvas.mapSettings().destinationCrs(), self.project
        )
        canvas.setExtent(extent)
        canvas.refresh()

    def _activar_conteo_features(self, layer):
        """Activa "Mostrar cantidad de entidades" (show feature count) en
        el panel de capas de QGIS para `layer`, recién agregada al
        proyecto -- así el usuario ve de inmediato, junto al nombre de la
        capa, cuántos puntos trajo la consulta sin tener que abrir la
        tabla de atributos. Pedido explícito del usuario para la capa de
        resultados de "Base de Datos" (v2.19.0). `layer` debe haberse
        agregado ya al proyecto (`self.project.addMapLayer(layer)`) --
        si todavía no tiene un nodo en el árbol de capas, no hace nada."""
        nodo = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if nodo is not None:
            nodo.setCustomProperty("showFeatureCount", True)

    # -- CRS de trabajo guardado por proyecto ---------------------------------
    # El selector de CRS es un único widget compartido por todas las
    # secciones (`_working_crs()`), así que si no se guardara/recuperara
    # por proyecto, cambiar de un proyecto a otro (p.ej. "Mis
    # proyectos...") dejaría seleccionado el CRS del proyecto anterior --
    # justamente el escenario de riesgo que motivó esto: trabajar con un
    # proyecto en Colombia y otro en Argentina y subir datos sin darse
    # cuenta de que quedó el CRS que no correspondía.
    @_escritura(silencioso=True)
    def _guardar_crs_actual(self):
        if self.conn is None or self.crs_widget is None:
            return
        crs = self.crs_widget.crs()
        if crs.isValid():
            db_schema.set_project_setting(self.conn, "working_crs_authid", crs.authid() or crs.toWkt())

    def _cargar_crs_guardado(self):
        """Al abrir/crear/cambiar de proyecto, recupera el CRS de trabajo
        guardado con ESE proyecto (tabla ProjectSettings). Si el proyecto
        no tiene uno guardado todavía (base de una versión anterior del
        plugin, o abierta desde fuera del flujo normal), se avisa y se
        mantiene el que esté seleccionado en ese momento -- no se fuerza
        un valor por defecto que podría ser el de otro país/proyecto --
        y se guarda de una vez para que la próxima apertura ya lo
        recuerde."""
        if self.crs_widget is None:
            return
        saved = db_schema.get_project_setting(self.conn, "working_crs_authid") if self.conn is not None else None
        if saved:
            crs = QgsCoordinateReferenceSystem(saved)
            if crs.isValid():
                self.crs_widget.blockSignals(True)
                self.crs_widget.setCrs(crs)
                self.crs_widget.blockSignals(False)
                return
        crs_actual = self.crs_widget.crs()
        QMessageBox.warning(
            self, self.t("warn_crs_not_saved_title"),
            self.t("warn_crs_not_saved_body", crs=crs_actual.authid() or crs_actual.description()),
        )
        self._guardar_crs_actual()

    # -- Factor de escala del proyecto (terreno <-> grilla), guardado por
    # proyecto igual que el CRS de arriba -- base para un futuro módulo de
    # Estación Total (ver `note_factor_escala` y el docstring de
    # `_factor_combinado_proyecto`). Pedido explícito del usuario, que
    # preguntó cómo se calcularía ese factor y si tendría que
    # proporcionarlo al crear el proyecto "así como lo hace GPSeismic", y
    # si se podría hacer clic en el mapa de QGIS para tomar la coordenada.
    def _iniciar_click_mapa_factor_escala(self):
        """Botón "Usar clic en el mapa...": activa una herramienta de un
        solo clic sobre el canvas de QGIS -- el próximo clic del usuario
        en el mapa (en cualquier CRS que tenga el canvas en ese momento)
        se toma como el punto de referencia, se convierte a lat/lon WGS84
        y llena los campos de arriba. Restaura la herramienta que
        estuviera activa en el canvas antes de este botón (pan, zoom,
        etc.) apenas se registra el clic, para no dejar el mapa "trabado"
        en modo selección de punto."""
        if QgsMapToolEmitPoint is None:
            QMessageBox.warning(self, self.t("err_title"), self.t("crs_widget_unavailable"))
            return
        canvas = self.iface.mapCanvas()
        self._factor_escala_prev_map_tool = canvas.mapTool()
        self._factor_escala_map_tool = QgsMapToolEmitPoint(canvas)
        self._factor_escala_map_tool.canvasClicked.connect(self._on_click_mapa_factor_escala)
        canvas.setMapTool(self._factor_escala_map_tool)
        self.lbl_factor_escala_status.setText(self.t("status_factor_escala_esperando_click"))

    def _on_click_mapa_factor_escala(self, point, _button):
        """Callback de `QgsMapToolEmitPoint.canvasClicked` -- `point` viene
        en el CRS ACTUAL DEL CANVAS (`QgsProject.instance().crs()`), que no
        es necesariamente el CRS de trabajo del plugin (`_working_crs()`,
        ver la nota de `_zoom_canvas_a_capa` sobre esta misma distinción);
        se convierte siempre a lat/lon WGS84 con `_transform_xy`, antes de
        llenar los spinbox, porque es lo que espera
        `_factor_combinado_proyecto`."""
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        lon, lat = _transform_xy(point.x(), point.y(), canvas_crs, self.crs_wgs84, self.project)
        self.spin_factor_escala_lat.setValue(lat)
        self.spin_factor_escala_lon.setValue(lon)
        self.lbl_factor_escala_status.setText(self.t("status_factor_escala_tomado", lat=lat, lon=lon))
        # Un solo clic: se restaura de inmediato la herramienta que tenía
        # el canvas antes (pan/zoom/etc.) para no dejarlo trabado en modo
        # "elegir punto" después de este único uso.
        if self._factor_escala_prev_map_tool is not None:
            canvas.setMapTool(self._factor_escala_prev_map_tool)
        self._factor_escala_map_tool = None
        self._factor_escala_prev_map_tool = None

    def _calcular_factor_escala_proyecto(self):
        """Botón "Calcular": corre `_factor_combinado_proyecto` con la
        lat/lon/altura actualmente en los campos (tomados del mapa o
        escritos a mano) y el CRS de trabajo de arriba, y muestra el
        resultado -- sin guardar nada todavía (eso es
        `guardar_factor_escala_proyecto`, aparte y explícito, mismo
        criterio que ya usa el CRS/la config de levantamiento)."""
        lat = self.spin_factor_escala_lat.value()
        lon = self.spin_factor_escala_lon.value()
        altura = self.spin_factor_escala_altura.value()
        working_crs = self._working_crs()
        if working_crs.isGeographic():
            QMessageBox.warning(
                self, self.t("warn_factor_escala_crs_geografico_title"),
                self.t("warn_factor_escala_crs_geografico_body"),
            )
            return
        factor_proyeccion, convergencia, factor_elevacion, factor_combinado = _factor_combinado_proyecto(
            lon, lat, altura, working_crs
        )
        if factor_proyeccion is None:
            QMessageBox.warning(
                self, self.t("warn_factor_escala_crs_geografico_title"),
                self.t("warn_factor_escala_crs_geografico_body"),
            )
            return
        self._factor_escala_calculado = (factor_proyeccion, convergencia, factor_elevacion, factor_combinado)
        self.lbl_factor_escala_resultado.setText(
            self.t(
                "lbl_factor_escala_resultado",
                factor_proyeccion=factor_proyeccion, convergencia=convergencia,
                factor_elevacion=factor_elevacion, factor_combinado=factor_combinado,
            )
        )

    @_escritura()
    def guardar_factor_escala_proyecto(self):
        """Botón "Guardar factor de este proyecto": persiste (tabla
        ProjectSettings, igual que el CRS/la config de levantamiento) el
        punto de referencia (lat/lon/altura) y el factor combinado ya
        calculado con "Calcular" -- pide calcular primero si todavía no
        se hizo, en vez de guardar algo a medias o desactualizado."""
        if not self._require_project():
            return
        if self._factor_escala_calculado is None:
            QMessageBox.warning(
                self, self.t("warn_factor_escala_no_calculado_title"),
                self.t("warn_factor_escala_no_calculado_body"),
            )
            return
        lat = self.spin_factor_escala_lat.value()
        lon = self.spin_factor_escala_lon.value()
        altura = self.spin_factor_escala_altura.value()
        factor_proyeccion, convergencia, factor_elevacion, factor_combinado = self._factor_escala_calculado
        db_schema.set_project_setting(self.conn, "factor_escala_lat", repr(lat))
        db_schema.set_project_setting(self.conn, "factor_escala_lon", repr(lon))
        db_schema.set_project_setting(self.conn, "factor_escala_altura_m", repr(altura))
        db_schema.set_project_setting(self.conn, "factor_escala_proyeccion", repr(factor_proyeccion))
        db_schema.set_project_setting(self.conn, "factor_escala_convergencia", repr(convergencia))
        db_schema.set_project_setting(self.conn, "factor_escala_elevacion", repr(factor_elevacion))
        db_schema.set_project_setting(self.conn, "factor_escala_combinado", repr(factor_combinado))
        QMessageBox.information(
            self, self.t("ok_title"),
            self.t("msg_factor_escala_saved", factor=factor_combinado, lat=lat, lon=lon, altura=altura),
        )

    def _cargar_factor_escala_guardado(self):
        """Al abrir/crear/cambiar de proyecto, recupera el punto de
        referencia y el factor combinado guardados con ESE proyecto, si
        los hay -- a diferencia del CRS, no avisa si no hay nada guardado
        (es un dato opcional y nuevo, todavía sin usar en ningún cálculo
        del plugin; la mayoría de los proyectos existentes no lo van a
        tener hasta que el usuario lo calcule y guarde una vez)."""
        self._factor_escala_calculado = None
        if not hasattr(self, "spin_factor_escala_lat"):
            return
        self.lbl_factor_escala_resultado.setText(self.t("status_factor_escala_sin_calcular"))
        self.lbl_factor_escala_status.setText("")
        if self.conn is None:
            return
        try:
            lat = float(db_schema.get_project_setting(self.conn, "factor_escala_lat", "0") or "0")
            lon = float(db_schema.get_project_setting(self.conn, "factor_escala_lon", "0") or "0")
            altura = float(db_schema.get_project_setting(self.conn, "factor_escala_altura_m", "0") or "0")
        except (TypeError, ValueError):
            return
        self.spin_factor_escala_lat.setValue(lat)
        self.spin_factor_escala_lon.setValue(lon)
        self.spin_factor_escala_altura.setValue(altura)
        factor_combinado_txt = db_schema.get_project_setting(self.conn, "factor_escala_combinado")
        if not factor_combinado_txt:
            return
        try:
            factor_proyeccion = float(db_schema.get_project_setting(self.conn, "factor_escala_proyeccion", "0") or "0")
            convergencia = float(db_schema.get_project_setting(self.conn, "factor_escala_convergencia", "0") or "0")
            factor_elevacion = float(db_schema.get_project_setting(self.conn, "factor_escala_elevacion", "0") or "0")
            factor_combinado = float(factor_combinado_txt)
        except (TypeError, ValueError):
            return
        self._factor_escala_calculado = (factor_proyeccion, convergencia, factor_elevacion, factor_combinado)
        self.lbl_factor_escala_resultado.setText(
            self.t(
                "lbl_factor_escala_resultado",
                factor_proyeccion=factor_proyeccion, convergencia=convergencia,
                factor_elevacion=factor_elevacion, factor_combinado=factor_combinado,
            )
        )

    # -- Levantamiento 2D/3D y azimutes de línea fuente/receptora, guardados
    # por proyecto (mismo mecanismo y mismo motivo que el CRS de arriba: un
    # único selector compartido por todas las secciones). Ver la nota junto
    # a `_clasificar_linea_por_descriptor` sobre por qué se eligió
    # clasificar por Descriptor en vez de por rango de Track u Odd/Even.
    def _actualizar_visibilidad_campos_survey_3d(self, *_args):
        """Muestra/oculta los campos de azimutes y códigos Descriptor de
        línea fuente/receptora según el combo 2D/3D -- para un proyecto 2D
        no hace falta preguntarlos (se sigue usando, sin cambios, el rumbo
        ajustado por Track de PREPLOT, ver `_resolver_azimut_linea`)."""
        if not hasattr(self, "cb_survey_type"):
            return
        es_3d = self.cb_survey_type.currentData() == "3D"
        for widget in (
            self.spin_survey_az_fuente, self._lbl_survey_az_fuente,
            self.spin_survey_az_receptora, self._lbl_survey_az_receptora,
            self.txt_survey_cod_fuente, self._lbl_survey_cod_fuente,
            self.txt_survey_cod_receptora, self._lbl_survey_cod_receptora,
        ):
            widget.setVisible(es_3d)

    @_escritura(silencioso=True)
    def _guardar_config_survey_actual(self):
        """Valida y persiste (ProjectSettings) los widgets de la pestaña
        Proyecto. Devuelve (True, "") si se guardó, o (False, mensaje) si
        la configuración 3D está incompleta -- en ese caso no se guarda
        nada a medias, ni se pisa lo que ya hubiera guardado el proyecto."""
        if self.conn is None or not hasattr(self, "cb_survey_type"):
            return False, ""
        es_3d = self.cb_survey_type.currentData() == "3D"
        if es_3d:
            cod_fuente = _parse_lista_codigos_descriptor(self.txt_survey_cod_fuente.text())
            cod_receptora = _parse_lista_codigos_descriptor(self.txt_survey_cod_receptora.text())
            if not cod_fuente or not cod_receptora:
                return False, self.t("err_survey_codes_required")
            if cod_fuente & cod_receptora:
                return False, self.t("err_survey_codes_overlap")
            az_fuente = self.spin_survey_az_fuente.value()
            az_receptora = self.spin_survey_az_receptora.value()
            db_schema.set_project_setting(self.conn, "survey_type", "3D")
            db_schema.set_project_setting(self.conn, "azimuth_linea_fuente", repr(az_fuente))
            db_schema.set_project_setting(self.conn, "azimuth_linea_receptora", repr(az_receptora))
            db_schema.set_project_setting(self.conn, "descriptores_linea_fuente", ",".join(sorted(cod_fuente)))
            db_schema.set_project_setting(self.conn, "descriptores_linea_receptora", ",".join(sorted(cod_receptora)))
            self._survey_type = "3D"
            self._survey_azimut_fuente = az_fuente
            self._survey_azimut_receptora = az_receptora
            self._survey_codigos_fuente = cod_fuente
            self._survey_codigos_receptora = cod_receptora
        else:
            db_schema.set_project_setting(self.conn, "survey_type", "2D")
            self._survey_type = "2D"
            self._survey_azimut_fuente = None
            self._survey_azimut_receptora = None
            self._survey_codigos_fuente = set()
            self._survey_codigos_receptora = set()
        return True, ""

    def _cargar_config_survey_guardada(self):
        """Al abrir/crear un proyecto, recupera el tipo de levantamiento
        guardado con ESE proyecto (2D por defecto si nunca se guardó --
        proyectos creados con una versión anterior del plugin -- sin
        forzar ningún diálogo) y, si es 3D, los azimutes/códigos, y
        refleja todo en los widgets de la pestaña Proyecto."""
        if self.conn is None:
            return
        tipo = db_schema.get_project_setting(self.conn, "survey_type", "2D") or "2D"
        az_fuente_txt = db_schema.get_project_setting(self.conn, "azimuth_linea_fuente", "")
        az_receptora_txt = db_schema.get_project_setting(self.conn, "azimuth_linea_receptora", "")
        cod_fuente_txt = db_schema.get_project_setting(self.conn, "descriptores_linea_fuente", "")
        cod_receptora_txt = db_schema.get_project_setting(self.conn, "descriptores_linea_receptora", "")

        self._survey_type = "3D" if tipo == "3D" else "2D"
        try:
            self._survey_azimut_fuente = float(az_fuente_txt) if az_fuente_txt not in (None, "") else None
        except (TypeError, ValueError):
            self._survey_azimut_fuente = None
        try:
            self._survey_azimut_receptora = float(az_receptora_txt) if az_receptora_txt not in (None, "") else None
        except (TypeError, ValueError):
            self._survey_azimut_receptora = None
        self._survey_codigos_fuente = _parse_lista_codigos_descriptor(cod_fuente_txt)
        self._survey_codigos_receptora = _parse_lista_codigos_descriptor(cod_receptora_txt)

        if hasattr(self, "cb_survey_type"):
            idx = self.cb_survey_type.findData(self._survey_type)
            self.cb_survey_type.blockSignals(True)
            self.cb_survey_type.setCurrentIndex(idx if idx >= 0 else 0)
            self.cb_survey_type.blockSignals(False)
            self.spin_survey_az_fuente.setValue(self._survey_azimut_fuente or 0.0)
            self.spin_survey_az_receptora.setValue(self._survey_azimut_receptora or 0.0)
            self.txt_survey_cod_fuente.setText(
                ",".join(sorted(self._survey_codigos_fuente)) or _SURVEY_CODIGOS_FUENTE_DEFECTO
            )
            self.txt_survey_cod_receptora.setText(
                ",".join(sorted(self._survey_codigos_receptora)) or _SURVEY_CODIGOS_RECEPTORA_DEFECTO
            )
            self._actualizar_visibilidad_campos_survey_3d()

    def _preguntar_tipo_levantamiento_nuevo_proyecto(self):
        """Al crear un proyecto nuevo (ver `crear_proyecto`), pregunta de
        una vez si el proyecto es 2D o 3D y, si es 3D, los dos azimutes de
        línea (fuente/receptora) -- ver la nota junto a
        `_clasificar_linea_por_descriptor` sobre el manual de GPSeismic que
        motivó esto. Se muestra como un diálogo aparte (no sólo el grupo de
        la pestaña) porque el pedido explícito del usuario fue que el
        plugin "pregunte" en ese momento del flujo. Si el usuario cancela,
        el proyecto queda igual en 2D (ya es el valor por defecto, no se
        pierde nada) y puede configurarlo después desde la pestaña, con el
        botón "Guardar configuración de levantamiento"."""
        dlg = QDialog(self)
        dlg.setWindowTitle(self.t("dlg_survey_type_title"))
        v = QVBoxLayout(dlg)
        # El texto de introducción es largo: con ajuste de línea y un ancho
        # acotado el diálogo cabe en pantalla (sin esto se estiraba a una
        # sola línea de más de 2000 px).
        lbl_intro = QLabel(self.t("dlg_survey_type_intro"))
        lbl_intro.setWordWrap(True)
        v.addWidget(lbl_intro)
        dlg.setMinimumWidth(520)
        dlg.setMaximumWidth(760)

        form = QFormLayout()
        cb_tipo = QComboBox()
        cb_tipo.addItem(self.t("opt_survey_2d"), "2D")
        cb_tipo.addItem(self.t("opt_survey_3d"), "3D")
        form.addRow(self.t("lbl_survey_type"), cb_tipo)

        spin_fuente = QDoubleSpinBox()
        spin_fuente.setRange(0.0, 360.0)
        spin_fuente.setDecimals(3)
        spin_fuente.setSuffix(" °")
        lbl_fuente = QLabel(self.t("lbl_survey_az_fuente"))
        form.addRow(lbl_fuente, spin_fuente)

        spin_receptora = QDoubleSpinBox()
        spin_receptora.setRange(0.0, 360.0)
        spin_receptora.setDecimals(3)
        spin_receptora.setSuffix(" °")
        lbl_receptora = QLabel(self.t("lbl_survey_az_receptora"))
        form.addRow(lbl_receptora, spin_receptora)

        txt_cod_fuente = QLineEdit(_SURVEY_CODIGOS_FUENTE_DEFECTO)
        txt_cod_fuente.setToolTip(self.t("tip_survey_cod_placeholder"))
        lbl_cod_fuente = QLabel(self.t("lbl_survey_cod_fuente"))
        form.addRow(lbl_cod_fuente, txt_cod_fuente)

        txt_cod_receptora = QLineEdit(_SURVEY_CODIGOS_RECEPTORA_DEFECTO)
        txt_cod_receptora.setToolTip(self.t("tip_survey_cod_placeholder"))
        lbl_cod_receptora = QLabel(self.t("lbl_survey_cod_receptora"))
        form.addRow(lbl_cod_receptora, txt_cod_receptora)

        v.addLayout(form)

        def _actualizar_visibilidad(*_args):
            es_3d = cb_tipo.currentData() == "3D"
            for w in (spin_fuente, lbl_fuente, spin_receptora, lbl_receptora,
                      txt_cod_fuente, lbl_cod_fuente, txt_cod_receptora, lbl_cod_receptora):
                w.setVisible(es_3d)

        cb_tipo.currentIndexChanged.connect(_actualizar_visibilidad)
        _actualizar_visibilidad()

        def _confirmar():
            es_3d = cb_tipo.currentData() == "3D"
            if es_3d:
                cod_fuente = _parse_lista_codigos_descriptor(txt_cod_fuente.text())
                cod_receptora = _parse_lista_codigos_descriptor(txt_cod_receptora.text())
                if not cod_fuente or not cod_receptora or (cod_fuente & cod_receptora):
                    QMessageBox.warning(
                        dlg, self.t("err_title"),
                        self.t("err_survey_codes_overlap") if (cod_fuente & cod_receptora)
                        else self.t("err_survey_codes_required"),
                    )
                    return
                db_schema.set_project_setting(self.conn, "survey_type", "3D")
                db_schema.set_project_setting(self.conn, "azimuth_linea_fuente", repr(spin_fuente.value()))
                db_schema.set_project_setting(self.conn, "azimuth_linea_receptora", repr(spin_receptora.value()))
                db_schema.set_project_setting(self.conn, "descriptores_linea_fuente", ",".join(sorted(cod_fuente)))
                db_schema.set_project_setting(self.conn, "descriptores_linea_receptora", ",".join(sorted(cod_receptora)))
            else:
                db_schema.set_project_setting(self.conn, "survey_type", "2D")
            dlg.accept()

        fila_botones = QHBoxLayout()
        btn_ok = self._reg(QPushButton(), "btn_accept")
        btn_cancelar = self._reg(QPushButton(), "btn_cancel")
        btn_ok.clicked.connect(_confirmar)
        btn_cancelar.clicked.connect(dlg.reject)
        fila_botones.addStretch()
        fila_botones.addWidget(btn_ok)
        fila_botones.addWidget(btn_cancelar)
        v.addLayout(fila_botones)

        (dlg.exec if hasattr(dlg, "exec") else dlg.exec_)()
        self._cargar_config_survey_guardada()

    def _resolver_azimut_linea(self, fila: dict):
        """Azimut de línea sísmica (grados 0-360, mismo sistema/CRS que usa
        `_fit_line_azimuth_deg`) a aplicar a `fila` para descomponer su
        offset posplot-preplot en Inline/Crossline. Prioridad:

        1) Si el proyecto es 3D y el Descriptor real del punto
           (`fila["descriptor"]`, ver `previsualizar_dc` -- NO
           `fila["tipo"]`) clasifica como línea fuente o receptora contra
           los códigos configurados, se usa el azimut FIJO de esa línea
           (`self._survey_azimut_fuente`/`_survey_azimut_receptora`).
        2) Si no (proyecto 2D, sin azimutes 3D configurados, o el punto no
           clasificó), se usa -- sin cambios respecto a versiones
           anteriores -- el rumbo ajustado por Track de la propia geometría
           de PREPLOT (`self._preplot_track_azimuths`).

        Devuelve (azimut_o_None, origen) donde origen es
        "fuente"/"receptora"/"preplot"/None."""
        if self._survey_type == "3D":
            clasif = _clasificar_linea_por_descriptor(
                fila.get("descriptor"), self._survey_codigos_fuente, self._survey_codigos_receptora,
            )
            if clasif == "fuente" and self._survey_azimut_fuente is not None:
                return self._survey_azimut_fuente, "fuente"
            if clasif == "receptora" and self._survey_azimut_receptora is not None:
                return self._survey_azimut_receptora, "receptora"
        track_key = _normalize_track_key(fila.get("track"))
        az = self._preplot_track_azimuths.get(track_key) if track_key is not None else None
        return (az, "preplot") if az is not None else (None, None)

    def _render_counts_label(self):
        """Actualiza los tres "badges" de la barra superior de la pestaña
        Proyecto (POSTPLOT / PREPLOT / COMPARACION)."""
        if not hasattr(self, "badge_postplot"):
            return
        if self._last_counts is None:
            n_post = n_pre = n_comp = "-"
        else:
            n_post, n_pre, n_comp = self._last_counts
        self.badge_postplot.setText(self.t("badge_post", n=n_post))
        self.badge_preplot.setText(self.t("badge_pre", n=n_pre))
        self.badge_comparacion.setText(self.t("badge_comp", n=n_comp))
        self.lbl_conteos.setVisible(False)

    def _render_preplot_label(self):
        """Re-renderiza el resumen de la pestaña 2 (Preplot Sísmico) en el
        idioma vigente. Como `lbl_preplot_resumen` no es un widget
        "estático" (su texto depende de si ya se generó un preplot o no),
        se guarda el estado en `_last_preplot_summary` para poder volver
        a traducirlo cuando el usuario cambia de idioma sin haber
        generado nada todavía -- este era justamente el caso que se
        quedaba en español ("Sin puntos generados todavía.")."""
        if not hasattr(self, "lbl_preplot_resumen"):
            return
        if self._last_preplot_summary is None:
            texto = f"<span style='color:#f9a825'>&#9888;</span>&nbsp;{self.t('pp_estado_vacio')}"
            hay_puntos = False
        else:
            n, modo_key = self._last_preplot_summary
            texto = f"<span style='color:#2e9d4a'>&#9679;</span>&nbsp;{self.t('pp_estado_listo', n=n, modo=self.t(modo_key))}"
            hay_puntos = True
        self.lbl_preplot_resumen.setText(texto)
        # "Limpiar" y "Guardar" sólo tienen sentido con puntos generados.
        for nombre in ("tb_pp_limpiar", "tb_pp_guardar"):
            btn = getattr(self, nombre, None)
            if btn is not None:
                btn.setEnabled(hay_puntos)

    def crear_proyecto(self):
        """Crea un proyecto nuevo como una CARPETA (con el nombre que
        elija el usuario) que contiene cuatro subcarpetas:
        "database" (con "<nombre_de_proyecto>.sqlite", la base de datos
        real del proyecto -- el nombre del archivo es el mismo nombre de
        proyecto que el usuario eligió, sanitizado igual que el de la
        carpeta), "maps", "preplot" y "posplot" (vacías, para que el
        usuario organice ahí sus propios archivos de ese proyecto).

        Antes de pedir carpeta/nombre, valida que el geoide que esté
        cargado en ESE momento (típicamente el que quedó de un proyecto
        anterior que sigue abierto) tenga cobertura en la zona de uso del
        CRS actualmente elegido -- si no, no deja crear el proyecto hasta
        que se corrija el CRS o el geoide (ver `_geoide_cubre_zona_crs`).
        Sin geoide cargado no hay nada que validar y se sigue de largo."""
        crs_elegido = self.crs_widget.crs() if self.crs_widget is not None else self.crs_wgs84
        if not self._geoide_cubre_zona_crs(crs_elegido):
            area = crs_elegido.bounds()
            geoid_nombre = os.path.basename(self.geoid_path) if self.geoid_path else "?"
            QMessageBox.critical(
                self, self.t("err_geoid_crs_mismatch_title"),
                self.t(
                    "err_geoid_crs_mismatch_body",
                    geoid=geoid_nombre, crs=crs_elegido.authid() or crs_elegido.description(),
                    xmin=round(area.xMinimum(), 2), ymin=round(area.yMinimum(), 2),
                    xmax=round(area.xMaximum(), 2), ymax=round(area.yMaximum(), 2),
                ),
            )
            return

        settings = QSettings()
        ultima_carpeta = settings.value(_SETTINGS_KEY_LAST_PARENT_DIR, "")
        carpeta_padre = QFileDialog.getExistingDirectory(
            self, self.t("dlg_new_project_folder_title"), ultima_carpeta or ""
        )
        if not carpeta_padre:
            return

        nombre, ok = QInputDialog.getText(
            self, self.t("dlg_new_project_name_title"), self.t("dlg_new_project_name_label")
        )
        if not ok:
            return
        nombre = nombre.strip()
        if not nombre:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_project_name_invalid"))
            return

        nombre_sanitizado = _sanitizar_nombre_carpeta(nombre)
        carpeta_proyecto = os.path.join(carpeta_padre, nombre_sanitizado)
        db_path = os.path.join(carpeta_proyecto, "database", f"{nombre_sanitizado}.sqlite")

        if os.path.exists(db_path):
            resp = QMessageBox.question(
                self, self.t("confirm_overwrite_title"),
                self.t("confirm_project_overwrite_body", path=db_path),
            )
            if resp not in (MSG_YES,):
                return

        try:
            os.makedirs(carpeta_proyecto, exist_ok=True)
            for sub in PROJECT_SUBFOLDERS:
                os.makedirs(os.path.join(carpeta_proyecto, sub), exist_ok=True)

            conn = db_schema.create_project_db(db_path, overwrite=True)
            for tabla in ("POSTPLOT", "PREPLOT"):
                db_schema.register_table_description(
                    conn, tabla, creation_purpose="Proyecto creado con GNSSeismic (QGIS)"
                )
            # Si había un proyecto compartido abierto, se cierra su sesión
            # (el editor publica y libera el bloqueo) antes de pasar al nuevo.
            self._cerrar_sesion_compartida(cerrar_conexion=True)
            self.conn = conn
            self._resetear_lotes_subidos()
            self.db_path = db_path
            self.lbl_db_path.setText(db_path)
            self._actualizar_ui_compartido()
            self.geoid_layer = None
            self.geoid_ggf = None
            self.geoid_path = None
            self.lbl_geoid_path.clear()
            self._actualizar_chk_geoid_importar()
            self.actualizar_conteos()
            # Un proyecto nuevo no tiene (todavía) un factor de escala
            # guardado -- se limpia la vista para no arrastrar el cálculo
            # del proyecto que pudiera haber estado abierto antes.
            self._cargar_factor_escala_guardado()
            # Guarda el CRS que esté seleccionado en ese momento como el CRS
            # de ESTE proyecto (ver `_guardar_crs_actual`/`_cargar_crs_guardado`),
            # para que no se pierda ni se confunda con el de otro proyecto la
            # próxima vez que se cambie de uno a otro.
            self._guardar_crs_actual()

            # Pedido explícito del usuario: después de elegir la carpeta,
            # preguntar si el proyecto es 2D o 3D (y, si 3D, los azimutes de
            # línea fuente/receptora) -- ver `_preguntar_tipo_levantamiento_nuevo_proyecto`.
            # Como el proyecto ya quedó creado en 2D por defecto, cancelar
            # este diálogo no deja nada a medias.
            self._preguntar_tipo_levantamiento_nuevo_proyecto()

            # Pedido explícito del usuario: el recuadro de configuración
            # (CRS/factor de escala/tipo de levantamiento/geoide) queda
            # oculto por defecto -- ver `btn_toggle_config_proyecto` en
            # `_build_tab_proyecto` -- pero un proyecto recién creado es
            # justo el momento en que hace falta revisarlo/completarlo,
            # así que se despliega solo acá.
            self.btn_toggle_config_proyecto.setChecked(True)

            settings.setValue(_SETTINGS_KEY_LAST_PARENT_DIR, carpeta_padre)
            self._register_known_project(nombre, carpeta_proyecto, db_path)

            crs_creado = self.crs_widget.crs() if self.crs_widget is not None else self.crs_wgs84
            QMessageBox.information(
                self, self.t("msg_project_created_title"),
                self.t(
                    "msg_project_created_body", path=carpeta_proyecto,
                    crs=crs_creado.authid() or crs_creado.description(),
                ),
            )
            # Opcional: ¿el proyecto será compartido (carpeta sincronizada)?
            if QMessageBox.question(
                self, self.t("shared_new_title"), self.t("shared_new_body", path=carpeta_proyecto),
            ) in (MSG_YES,):
                self.compartir_proyecto_actual(silencioso=True)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_project_create", error=e, trace=traceback.format_exc()))

    def abrir_proyecto(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("dlg_open_project_title"), "", self.t("filter_sqlite_open"))
        if not path:
            return
        self._abrir_proyecto_desde_ruta(path)

    def _abrir_proyecto_desde_ruta(self, path: str) -> bool:
        """Lógica común para abrir una base de datos de proyecto ya
        existente, sea a través del diálogo de archivo de
        `abrir_proyecto()` o al elegir un proyecto en el selector
        "Mis proyectos..." (`abrir_selector_proyectos()`). Además de
        abrir la conexión, registra el proyecto en la lista de
        conocidos. Devuelve True si se pudo abrir."""
        if not os.path.exists(path):
            QMessageBox.warning(self, self.t("warn_project_missing_title"), self.t("warn_project_missing_body", path=path))
            self._quitar_proyecto_conocido(path)
            return False
        try:
            # No se sobrescribe: sólo se asegura de que existan todas las
            # tablas esperadas (por si la base es de una versión anterior
            # del plugin, o la plantilla original sin la tabla COMPARACION
            # o ProjectSettings).
            # Si hay una sesión compartida abierta del MISMO proyecto, se
            # cierra primero (publica y libera el bloqueo) para que la
            # nueva apertura no se vea a sí misma como "otro editor".
            vieja_sesion, vieja_conn = self._shared, self.conn
            if vieja_sesion is not None and os.path.normcase(os.path.abspath(vieja_sesion.db_path)) == os.path.normcase(os.path.abspath(path)):
                self._cerrar_sesion_compartida(cerrar_conexion=True)
                vieja_sesion = None
            nueva_sesion = None
            if shared_project.is_shared(path):
                conn, nueva_sesion = self._preparar_conexion_compartida(path)
                if conn is None:
                    return False  # el usuario canceló
            else:
                conn = db_schema.create_project_db(path, overwrite=False)
            # La nueva base ya está lista: recién ahora se cierra la sesión
            # compartida anterior (si era de otro proyecto).
            if vieja_sesion is not None:
                self._cerrar_sesion_compartida(cerrar_conexion=True)
            elif vieja_conn is not None and self._shared is None and vieja_conn is not conn:
                pass  # proyecto anterior no compartido: se deja abierto como siempre
            self.conn = conn
            self._shared = nueva_sesion
            if nueva_sesion is not None:
                self._shared_timer.start()
            self._resetear_lotes_subidos()
            self.db_path = path
            self.lbl_db_path.setText(path)
            self._cargar_estado_proyecto()
            self._actualizar_ui_compartido()
            carpeta_raiz = self._detectar_raiz_proyecto(path)
            nombre = os.path.basename(carpeta_raiz) or os.path.splitext(os.path.basename(path))[0]
            self._register_known_project(nombre, carpeta_raiz, path)
            return True
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_project_open", error=e))
            return False

    # -- Proyecto compartido (OPCIONAL) --------------------------------------
    # Ver `shared_project.py` para las reglas: un solo editor (copia local +
    # publicación atómica a la carpeta sincronizada), el resto en solo
    # lectura sobre una copia local de la última versión publicada.

    def _shared_local_root(self) -> str:
        try:
            base = QgsApplication.qgisSettingsDirPath()
        except Exception:  # sin QGIS completo: carpeta del usuario
            base = os.path.expanduser("~")
        return os.path.join(base, "gnsseismic_shared")

    def _crear_banner_solo_lectura(self):
        lbl = QLabel()
        lbl.setWordWrap(True)
        lbl.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; padding: 4px;")
        lbl.setVisible(False)
        self._banners_solo_lectura.append(lbl)
        return lbl

    def _texto_estado_compartido(self) -> str:
        sh = self._shared
        if sh is None:
            if self.conn is None or not self.db_path:
                return self.t("shared_status_no_project")
            return self.t("shared_status_not_shared")
        if sh.mode == shared_project.MODE_EDITOR:
            texto = self.t("shared_status_editor", fecha=sh.last_publish_text or "-")
        else:
            lock = sh.lock_seen
            if lock is None:
                editor = self.t("shared_viewer_nobody")
            else:
                minutos = int(lock.age_seconds() // 60) if lock.age_seconds() != float("inf") else -1
                editor = self.t(
                    "shared_viewer_editing", quien=lock.who(),
                    desde=shared_project.iso_to_local_text(lock.since),
                    min=minutos if minutos >= 0 else "?",
                    caida=(self.t("shared_viewer_stale") if lock.is_stale() else ""),
                )
            texto = self.t("shared_status_viewer", editor=editor, fecha=sh.last_publish_text or "-")
            if sh.remote_newer:
                texto += " " + self.t("shared_viewer_newer")
        if sh.last_error:
            texto += " " + self.t("shared_last_error", error=sh.last_error)
        return texto

    def _actualizar_ui_compartido(self):
        if not hasattr(self, "lbl_shared_estado"):
            return
        sh = self._shared
        editor = sh is not None and sh.mode == shared_project.MODE_EDITOR
        lector = sh is not None and sh.mode == shared_project.MODE_VIEWER
        # Interruptor "Habilitar proyecto compartido": refleja el estado
        # real; sólo se puede mover con un proyecto abierto y, si ya es
        # compartido, sólo siendo el editor (el lector no puede desactivarlo).
        self.chk_shared_enable.blockSignals(True)
        self.chk_shared_enable.setChecked(sh is not None)
        self.chk_shared_enable.blockSignals(False)
        self.chk_shared_enable.setEnabled(editor or (sh is None and self.conn is not None and bool(self.db_path)))
        for b in (self.btn_shared_publish, self.btn_shared_release):
            b.setVisible(editor)
        for b in (self.btn_shared_takeover, self.btn_shared_refresh):
            b.setVisible(lector)
        # El texto de estado sólo se muestra cuando el proyecto ES
        # compartido (la explicación general va en el tooltip del ícono (i)).
        self.lbl_shared_estado.setVisible(sh is not None)
        self.lbl_shared_estado.setText(self._texto_estado_compartido() if sh is not None else "")
        for lbl in self._banners_solo_lectura:
            lbl.setVisible(lector)
            if lector:
                lbl.setText(self.t("shared_banner_readonly"))

    def _guardar_estado_sesion_compartida_en_log(self, clave, **kw):
        if hasattr(self, "log_importar"):
            self.log_importar.appendPlainText(self.t(clave, **kw))

    def _abrir_como_editor(self, path, force=False):
        """Toma el bloqueo, deja una copia local de la versión publicada
        (o recupera la copia local de una sesión anterior con cambios sin
        publicar) y abre la conexión sobre ella. (conn, sesión) o
        (None, None)."""
        raiz = self._shared_local_root()
        local = shared_project.editor_copy_path(raiz, path)
        sid = shared_project.new_session_id()
        ok, otro = shared_project.acquire_lock(path, sid, force=force)
        if not ok:
            QMessageBox.warning(self, self.t("shared_open_title"), self.t("shared_lock_race_body", quien=otro.who() if otro else "?"))
            return None, None
        recuperar = False
        sig = shared_project.published_signature(path)
        if os.path.exists(local) and sig is not None:
            try:
                if os.stat(local).st_mtime_ns > sig[0] + 2_000_000_000:
                    resp = QMessageBox.question(self, self.t("shared_recover_title"), self.t("shared_recover_body"))
                    recuperar = resp in (MSG_YES,)
            except OSError:
                recuperar = False
        try:
            if not recuperar:
                shared_project.snapshot_published(path, local)
            conn = db_schema.create_project_db(local, overwrite=False)
        except Exception:
            shared_project.release_lock(path, sid)
            raise
        ses = shared_project.SharedSession(
            db_path=path, mode=shared_project.MODE_EDITOR, session_id=sid, local_path=local,
            baseline_changes=(-1 if recuperar else conn.total_changes), signature=sig,
            last_publish_text=shared_project.published_mtime_text(path),
        )
        return conn, ses

    def _abrir_como_lector(self, path):
        """Copia local de la última versión publicada, abierta en solo
        lectura (`query_only`: aunque algún camino de código intentara
        escribir, SQLite lo rechaza)."""
        raiz = self._shared_local_root()
        view = shared_project.viewer_copy_path(raiz, path)
        shared_project.snapshot_published(path, view)
        conn = db_schema.create_project_db(view, overwrite=False)
        conn.execute("PRAGMA query_only = ON")
        ses = shared_project.SharedSession(
            db_path=path, mode=shared_project.MODE_VIEWER, session_id="", local_path=view,
            signature=shared_project.published_signature(path),
            lock_seen=shared_project.read_lock(path),
            last_publish_text=shared_project.published_mtime_text(path),
        )
        return conn, ses

    def _preparar_conexion_compartida(self, path):
        """Decide el modo al abrir un proyecto compartido: libre -> editor;
        con editor activo -> pregunta (solo lectura / tomar el control /
        cancelar). Devuelve (conn, sesión) o (None, None) si se cancela."""
        lock = shared_project.read_lock(path)
        if lock is None:
            return self._abrir_como_editor(path)
        minutos = int(lock.age_seconds() // 60) if lock.age_seconds() != float("inf") else -1
        box = QMessageBox(self)
        box.setWindowTitle(self.t("shared_open_title"))
        box.setText(self.t(
            "shared_open_body", quien=lock.who(),
            desde=shared_project.iso_to_local_text(lock.since),
            min=minutos if minutos >= 0 else "?",
            caida=(self.t("shared_viewer_stale") if lock.is_stale() else ""),
        ))
        b_ro = box.addButton(self.t("btn_shared_open_ro"), MSG_ROLE_ACTION)
        b_take = box.addButton(self.t("btn_shared_open_takeover"), MSG_ROLE_ACTION)
        box.addButton(self.t("btn_cancel"), MSG_ROLE_REJECT)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_ro:
            return self._abrir_como_lector(path)
        if clicked is b_take:
            return self._abrir_como_editor(path, force=True)
        return None, None

    def _publicar_sesion(self, manual=False) -> bool:
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_EDITOR or self.conn is None:
            return False
        try:
            scratch = os.path.join(shared_project.work_dir(self._shared_local_root(), sh.db_path), "scratch")
            shared_project.publish(self.conn, sh.db_path, scratch)
            sh.baseline_changes = self.conn.total_changes
            sh.signature = shared_project.published_signature(sh.db_path)
            sh.last_publish_text = shared_project.published_mtime_text(sh.db_path)
            sh.last_error = ""
            ok = True
        except Exception as e:  # Drive sin conexión, carpeta inaccesible, disco lleno...
            sh.last_error = str(e)
            ok = False
            if manual:
                QMessageBox.warning(self, self.t("shared_publish_error_title"), self.t("shared_publish_error_body", error=e))
        self._actualizar_ui_compartido()
        return ok

    def _publicar_si_cambio(self):
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_EDITOR or self.conn is None:
            return
        if self.conn.total_changes != sh.baseline_changes:
            self._publicar_sesion(manual=False)

    def publicar_ahora(self):
        if self._shared is not None and self._shared.mode == shared_project.MODE_EDITOR:
            if self._publicar_sesion(manual=True):
                QMessageBox.information(self, self.t("shared_publish_ok_title"), self.t("shared_publish_ok_body", fecha=self._shared.last_publish_text))

    def _on_shared_tick(self):
        sh = self._shared
        if sh is None:
            self._shared_timer.stop()
            return
        try:
            if sh.mode == shared_project.MODE_EDITOR:
                if not shared_project.renew_lock(sh.db_path, sh.session_id):
                    self._perdio_control()
                    return
                self._publicar_si_cambio()
            else:
                sig = shared_project.published_signature(sh.db_path)
                sh.remote_newer = sig is not None and sig != sh.signature
                sh.lock_seen = shared_project.read_lock(sh.db_path)
        except Exception as e:  # el latido nunca debe interrumpir el trabajo
            sh.last_error = str(e)
        self._actualizar_ui_compartido()

    def _al_cerrar_qgis(self):
        try:
            self._cerrar_sesion_compartida()
        except RuntimeError:
            return  # widgets ya destruidos al salir: lo importante (publicar/liberar) ya se hizo

    def _cerrar_sesion_compartida(self, cerrar_conexion=False):
        """Termina la sesión compartida: el editor publica lo pendiente (si
        no se puede, NO libera el bloqueo para no dejar a otro editar sobre
        una versión vieja) y libera el bloqueo. Seguro de llamar siempre
        (también al cerrar QGIS)."""
        sh = self._shared
        if sh is None:
            return
        self._shared_timer.stop()
        publicado = True
        if sh.mode == shared_project.MODE_EDITOR:
            if self.conn is not None and (self.conn.total_changes != sh.baseline_changes):
                publicado = self._publicar_sesion(manual=False)
            if publicado:
                shared_project.release_lock(sh.db_path, sh.session_id)
        self._shared = None
        if cerrar_conexion and self.conn is not None:
            try:
                self.conn.close()
            except Exception as e:  # ya cerrada
                sh.last_error = str(e)
        self._actualizar_ui_compartido()

    def _cambiar_a_lector(self):
        """Pasa la ventana actual del modo editor al de solo lectura sobre
        la última versión publicada (tras `dejar_de_editar` o al perder el
        control)."""
        sh = self._shared
        if sh is None:
            return
        path = sh.db_path
        self._shared_timer.stop()
        try:
            self.conn.close()
        except Exception as e:
            sh.last_error = str(e)
        conn, ses = self._abrir_como_lector(path)
        self.conn, self._shared = conn, ses
        self._resetear_lotes_subidos()
        self._cargar_estado_proyecto()
        self._shared_timer.start()
        self._actualizar_ui_compartido()

    def dejar_de_editar(self):
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_EDITOR:
            return
        if self.conn.total_changes != sh.baseline_changes and not self._publicar_sesion(manual=True):
            return  # no se pudo publicar: se sigue editando, no se libera
        shared_project.release_lock(sh.db_path, sh.session_id)
        self._cambiar_a_lector()

    def tomar_control(self):
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_VIEWER:
            return
        lock = shared_project.read_lock(sh.db_path)
        if lock is not None:
            resp = QMessageBox.question(
                self, self.t("shared_takeover_title"),
                self.t("shared_takeover_body", quien=lock.who(), caida=(self.t("shared_viewer_stale") if lock.is_stale() else "")),
            )
            if resp not in (MSG_YES,):
                return
        self._shared_timer.stop()
        path = sh.db_path
        try:
            self.conn.close()
        except Exception as e:
            sh.last_error = str(e)
        try:
            conn, ses = self._abrir_como_editor(path, force=True)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_project_open", error=e))
            conn, ses = None, None
        if conn is None:  # no se pudo: se vuelve a la vista de solo lectura
            conn, ses = self._abrir_como_lector(path)
        self.conn, self._shared = conn, ses
        self._resetear_lotes_subidos()
        self._cargar_estado_proyecto()
        self._shared_timer.start()
        self._actualizar_ui_compartido()

    def actualizar_lector(self):
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_VIEWER:
            return
        path = sh.db_path
        self._shared_timer.stop()
        try:
            self.conn.close()
        except Exception as e:
            sh.last_error = str(e)
        try:
            conn, ses = self._abrir_como_lector(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_project_open", error=e))
            conn = sqlite3.connect(sh.local_path)
            conn.execute("PRAGMA query_only = ON")
            ses = sh
        self.conn, self._shared = conn, ses
        self._cargar_estado_proyecto()
        self._shared_timer.start()
        self._actualizar_ui_compartido()

    def _perdio_control(self):
        """Otra persona tomó el control mientras esta ventana editaba: lo
        publicado por la otra persona manda; los cambios locales sin
        publicar se guardan como respaldo y la ventana pasa a solo
        lectura."""
        sh = self._shared
        if sh is None:
            return
        respaldo = ""
        try:
            if self.conn.total_changes != sh.baseline_changes:
                self.conn.commit()
                carpeta = shared_project.work_dir(self._shared_local_root(), sh.db_path)
                respaldo = os.path.join(carpeta, "respaldo_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".sqlite")
                shared_project.copy_atomic(sh.local_path, respaldo)
        except Exception as e:
            sh.last_error = str(e)
        self._cambiar_a_lector()
        QMessageBox.warning(
            self, self.t("shared_lost_title"),
            self.t("shared_lost_body") + (("\n\n" + self.t("shared_lost_backup", path=respaldo)) if respaldo else ""),
        )

    def compartir_proyecto_actual(self, silencioso=False):
        """Marca el proyecto abierto como compartido: crea el marcador, toma
        el bloqueo y pasa a trabajar sobre una copia local con publicación
        a la carpeta del proyecto (que debería estar dentro de una carpeta
        sincronizada, p.ej. Google Drive para escritorio)."""
        if not self._require_project():
            return
        if self._shared is not None:
            return
        if not silencioso:
            resp = QMessageBox.question(
                self, self.t("shared_enable_title"), self.t("shared_enable_body", path=self.db_path),
            )
            if resp not in (MSG_YES,):
                return
        path = self.db_path
        try:
            self.conn.commit()
            self.conn.close()
            shared_project.enable_shared(path)
            conn, ses = self._abrir_como_editor(path)
            if conn is None:
                raise RuntimeError(self.t("shared_lock_race_body", quien="?"))
        except Exception as e:
            # se vuelve a abrir el proyecto como estaba (sin compartir)
            shared_project.disable_shared(path)
            self.conn = db_schema.create_project_db(path, overwrite=False)
            QMessageBox.critical(self, self.t("err_title"), self.t("err_project_open", error=e))
            return
        self.conn, self._shared = conn, ses
        self._shared_timer.start()
        self._publicar_sesion(manual=False)  # deja publicada la versión actual
        self._actualizar_ui_compartido()
        self.actualizar_conteos()

    def dejar_de_compartir(self):
        sh = self._shared
        if sh is None or sh.mode != shared_project.MODE_EDITOR:
            return
        resp = QMessageBox.question(self, self.t("shared_disable_title"), self.t("shared_disable_body"))
        if resp not in (MSG_YES,):
            return
        if not self._publicar_sesion(manual=True):
            return
        path = sh.db_path
        self._shared_timer.stop()
        shared_project.release_lock(path, sh.session_id)
        shared_project.disable_shared(path)
        try:
            self.conn.close()
        except Exception as e:
            sh.last_error = str(e)
        self._shared = None
        self.conn = db_schema.create_project_db(path, overwrite=False)
        self._resetear_lotes_subidos()
        self._actualizar_ui_compartido()
        self.actualizar_conteos()

    def _cargar_estado_proyecto(self):
        """Recarga desde la base abierta lo que se muestra del proyecto
        (geoide, CRS, factor de escala, tipo de levantamiento, conteos)."""
        self._cargar_geoide_guardado()
        self._cargar_crs_guardado()
        self._cargar_factor_escala_guardado()
        self._cargar_config_survey_guardada()
        self.actualizar_conteos()

    def _detectar_raiz_proyecto(self, db_path: str) -> str:
        """Infiere la carpeta "raíz" del proyecto a partir de la ruta de
        su base de datos, para mostrarla en el selector "Mis
        proyectos...". Si la base vive en una subcarpeta "database" (la
        convención de los proyectos creados desde `crear_proyecto`), la
        raíz es la carpeta que la contiene; si no (una base suelta de una
        versión anterior del plugin, o abierta fuera de esa convención),
        la raíz es simplemente la carpeta que contiene el archivo
        .sqlite."""
        carpeta = os.path.dirname(db_path)
        if os.path.basename(carpeta).lower() == "database":
            return os.path.dirname(carpeta)
        return carpeta

    # -- Selector de proyectos ("Mis proyectos...") ---------------------------
    # Los proyectos se registran por su ruta completa en QSettings (no en
    # ningún proyecto de QGIS en particular), así que la lista persiste
    # entre sesiones y funciona igual sin importar en qué carpeta viva
    # cada uno -- normal cuando se trabaja con varios proyectos a la vez
    # en rutas distintas.
    def _load_known_projects(self):
        settings = QSettings()
        raw = settings.value(_SETTINGS_KEY_KNOWN_PROJECTS, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [p for p in data if isinstance(p, dict) and p.get("db_path")]

    def _save_known_projects(self, proyectos):
        settings = QSettings()
        settings.setValue(_SETTINGS_KEY_KNOWN_PROJECTS, json.dumps(proyectos))

    def _register_known_project(self, nombre: str, carpeta_raiz: str, db_path: str):
        proyectos = self._load_known_projects()
        db_path_norm = os.path.normcase(os.path.abspath(db_path))
        proyectos = [p for p in proyectos if os.path.normcase(os.path.abspath(p.get("db_path", ""))) != db_path_norm]
        proyectos.insert(0, {
            "name": nombre,
            "root_dir": carpeta_raiz,
            "db_path": db_path,
            "last_opened": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._save_known_projects(proyectos[:_MAX_KNOWN_PROJECTS])

    def _quitar_proyecto_conocido(self, db_path: str):
        proyectos = self._load_known_projects()
        db_path_norm = os.path.normcase(os.path.abspath(db_path))
        proyectos = [p for p in proyectos if os.path.normcase(os.path.abspath(p.get("db_path", ""))) != db_path_norm]
        self._save_known_projects(proyectos)

    def abrir_selector_proyectos(self):
        """Ventana "Mis proyectos...": lista todos los proyectos ya
        creados/abiertos con este plugin (sin importar en qué carpeta o
        unidad estén) para cambiar de uno a otro con un clic, sin tener
        que ir a buscarlos con el diálogo de archivos cada vez."""
        dlg = QDialog(self.iface.mainWindow() if self.iface is not None else None)
        dlg.setWindowTitle(self.t("dlg_switch_project_title"))
        dlg.resize(720, 380)
        layout = QVBoxLayout(dlg)

        tabla = QTableWidget()
        tabla.setColumnCount(4)
        tabla.setHorizontalHeaderLabels([
            self.t("col_project_name"), self.t("col_project_crs"),
            self.t("col_project_path"), self.t("col_project_last_opened"),
        ])
        tabla.setEditTriggers(_valor_enum(QAbstractItemView, "NoEditTriggers", "EditTrigger"))
        tabla.setSelectionBehavior(_valor_enum(QAbstractItemView, "SelectRows", "SelectionBehavior"))
        tabla.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(tabla)

        lbl_vacio = QLabel(self.t("info_no_known_projects"))
        lbl_vacio.setWordWrap(True)
        layout.addWidget(lbl_vacio)

        def _refrescar():
            proyectos = self._load_known_projects()
            tabla.setRowCount(len(proyectos))
            for row, p in enumerate(proyectos):
                db_path = p.get("db_path", "")
                # Se lee directo del archivo (no de un valor guardado en el
                # registro) para que la columna siempre muestre el CRS real
                # y actual de cada proyecto, incluso si se corrigió con
                # "Guardar CRS de este proyecto" sin pasar por este selector.
                if not os.path.exists(db_path):
                    crs_texto = self.t("col_project_crs_unavailable")
                else:
                    crs_guardado = db_schema.get_project_setting_from_file(db_path, "working_crs_authid")
                    crs_texto = crs_guardado if crs_guardado else self.t("col_project_crs_not_saved")
                tabla.setItem(row, 0, QTableWidgetItem(p.get("name", "")))
                tabla.setItem(row, 1, QTableWidgetItem(crs_texto))
                tabla.setItem(row, 2, QTableWidgetItem(db_path))
                tabla.setItem(row, 3, QTableWidgetItem(p.get("last_opened", "")))
            tabla.resizeColumnsToContents()
            lbl_vacio.setVisible(len(proyectos) == 0)
            tabla.setVisible(len(proyectos) > 0)
            return proyectos

        def _fila_seleccionada():
            filas = tabla.selectionModel().selectedRows() if tabla.selectionModel() else []
            return filas[0].row() if filas else -1

        def _abrir_seleccionado():
            row = _fila_seleccionada()
            if row < 0:
                QMessageBox.information(self, self.t("info_select_project_title"), self.t("info_select_project_body"))
                return
            db_path = tabla.item(row, 2).text()
            if self._abrir_proyecto_desde_ruta(db_path):
                dlg.accept()
            else:
                _refrescar()

        def _quitar_seleccionado():
            row = _fila_seleccionada()
            if row < 0:
                QMessageBox.information(self, self.t("info_select_project_title"), self.t("info_select_project_body"))
                return
            nombre = tabla.item(row, 0).text()
            db_path = tabla.item(row, 2).text()
            resp = QMessageBox.question(
                self, self.t("confirm_title"), self.t("confirm_remove_project_body", name=nombre)
            )
            if resp in (MSG_YES,):
                self._quitar_proyecto_conocido(db_path)
                _refrescar()

        def _agregar_existente():
            path, _ = QFileDialog.getOpenFileName(dlg, self.t("dlg_open_project_title"), "", self.t("filter_sqlite_open"))
            if not path:
                return
            if self._abrir_proyecto_desde_ruta(path):
                dlg.accept()
            else:
                _refrescar()

        tabla.doubleClicked.connect(lambda _idx: _abrir_seleccionado())

        fila_botones = QHBoxLayout()
        btn_abrir = QPushButton(self.t("btn_open_selected_project"))
        btn_abrir.clicked.connect(_abrir_seleccionado)
        btn_quitar = QPushButton(self.t("btn_remove_project_from_list"))
        btn_quitar.clicked.connect(_quitar_seleccionado)
        btn_agregar = QPushButton(self.t("btn_add_existing_project"))
        btn_agregar.clicked.connect(_agregar_existente)
        btn_cerrar = QPushButton(self.t("btn_close"))
        btn_cerrar.clicked.connect(dlg.reject)
        fila_botones.addWidget(btn_abrir)
        fila_botones.addWidget(btn_quitar)
        fila_botones.addWidget(btn_agregar)
        fila_botones.addStretch()
        fila_botones.addWidget(btn_cerrar)
        layout.addLayout(fila_botones)

        _refrescar()
        # PyQt5 expone QDialog.exec_() (y, desde 5.11, también exec()); en
        # PyQt6 sólo existe exec(). Se usa el que esté disponible.
        (dlg.exec if hasattr(dlg, "exec") else dlg.exec_)()

    def actualizar_conteos(self):
        if self.conn is None:
            self._last_counts = None
            self._render_counts_label()
            return
        try:
            n_post = db_schema.table_row_count(self.conn, "POSTPLOT")
            n_pre = db_schema.table_row_count(self.conn, "PREPLOT")
            n_comp = db_schema.table_row_count(self.conn, "COMPARACION")
            self._last_counts = (n_post, n_pre, n_comp)
            self._render_counts_label()
        except Exception as e:
            self._last_counts = None
            self._render_counts_label()
            self.lbl_conteos.setText(self.t("lbl_counts_error", error=e))
            self.lbl_conteos.setVisible(True)
        # Repuebla el combo de columnas de "Buscar / Buscar y reemplazar"
        # (ver `_poblar_columnas_buscar_reemplazar`) cada vez que cambia
        # el proyecto abierto -- antes de la primera vez que se abre o
        # crea un proyecto, ese combo queda vacío (no hay esquema todavía
        # que leer).
        self._poblar_columnas_buscar_reemplazar()

    def _require_project(self) -> bool:
        if self.conn is None:
            QMessageBox.warning(self, self.t("no_project_title"), self.t("no_project_body"))
            return False
        return True

    # -- Geoide del proyecto --------------------------------------------------
    def _abrir_geoide_desde_ruta(self, path):
        """Intenta cargar `path` como modelo de geoide del proyecto.
        Deja el resultado en `self.geoid_layer` (para cualquier formato
        que GDAL/QGIS entienda directamente: GeoTIFF, GTX, ASCII Grid,
        Surfer GRD binario -- este último es el formato del QGeoiCol2004
        de IGAC, que QGIS abre solo) o en `self.geoid_ggf` (para el
        formato binario propietario .ggf "TNL GRID FILE" de Trimble, que
        GDAL no reconoce y que este plugin lee con su propio parser puro,
        `ggf_reader.py`). Lanza una excepción si no se pudo cargar de
        ninguna de las dos formas."""
        self.geoid_layer = None
        self.geoid_ggf = None
        ext = os.path.splitext(path)[1].lower()
        if ext == ".ggf":
            self.geoid_ggf = ggf_reader.read_ggf(path)
            return
        layer = QgsRasterLayer(path, "geoide")
        if not layer.isValid():
            raise ValueError(self.t("err_geoid_invalid"))
        if not layer.crs().isValid():
            # Formatos como Surfer GRD no traen CRS embebido; estos
            # modelos de geoide siempre están en coordenadas geográficas
            # WGS84 (grados), así que se asume EPSG:4326 en vez de dejar
            # el CRS sin definir.
            layer.setCrs(self.crs_wgs84)
        self.geoid_layer = layer

    @_escritura()
    def cargar_geoide(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("dlg_load_geoid_title"), "", self.t("filter_raster"))
        if not path:
            return
        try:
            self._abrir_geoide_desde_ruta(path)
            self.geoid_path = path
            self.lbl_geoid_path.setText(path)
            if self.conn is not None:
                db_schema.set_project_setting(self.conn, "geoid_model_file", path)
            self._actualizar_chk_geoid_importar()
            QMessageBox.information(self, self.t("ok_title"), self.t("msg_geoid_loaded", path=path))
        except Exception as e:
            self.geoid_layer = None
            self.geoid_ggf = None
            QMessageBox.critical(self, self.t("err_title"), self.t("err_geoid_load", error=e))

    @_escritura()
    def quitar_geoide(self):
        self.geoid_layer = None
        self.geoid_ggf = None
        self.geoid_path = None
        self.lbl_geoid_path.clear()
        if self.conn is not None:
            db_schema.set_project_setting(self.conn, "geoid_model_file", "")
        self._actualizar_chk_geoid_importar()

    def _cargar_geoide_guardado(self):
        """Al abrir un proyecto existente, recupera el geoide que se le
        haya asignado en una sesión anterior (tabla ProjectSettings)."""
        self.geoid_layer = None
        self.geoid_ggf = None
        self.geoid_path = None
        self.lbl_geoid_path.clear()
        if self.conn is None:
            self._actualizar_chk_geoid_importar()
            return
        saved_path = db_schema.get_project_setting(self.conn, "geoid_model_file")
        if not saved_path:
            self._actualizar_chk_geoid_importar()
            return
        self.geoid_path = saved_path
        self.lbl_geoid_path.setText(saved_path)
        if os.path.exists(saved_path):
            try:
                self._abrir_geoide_desde_ruta(saved_path)
            except Exception:
                self.geoid_layer = None
                self.geoid_ggf = None
        self._actualizar_chk_geoid_importar()

    def _actualizar_chk_geoid_importar(self):
        if not hasattr(self, "chk_aplicar_geoid"):
            return
        disponible = self.geoid_layer is not None or self.geoid_ggf is not None
        self.chk_aplicar_geoid.setEnabled(disponible)
        if disponible:
            self.chk_aplicar_geoid.setChecked(True)
            self.chk_aplicar_geoid.setToolTip(self.t("tip_apply_geoid"))
        else:
            self.chk_aplicar_geoid.setChecked(False)
            self.chk_aplicar_geoid.setToolTip(self.t("tip_apply_geoid_disabled"))

    def _sample_geoid_undulation(self, lon, lat):
        """Muestrea el geoide asignado al proyecto en (lon, lat) [WGS84]
        y devuelve la ondulación N (metros), o None si no hay geoide
        cargado o el punto cae fuera de su cobertura. Soporta tanto un
        ráster QGIS (`self.geoid_layer`) como una grilla .ggf leída con
        `ggf_reader` (`self.geoid_ggf`)."""
        if self.geoid_ggf is not None:
            try:
                return self.geoid_ggf.sample(lon, lat)
            except Exception:
                return None
        if self.geoid_layer is None:
            return None
        try:
            pt = QgsPointXY(lon, lat)
            raster_crs = self.geoid_layer.crs()
            if raster_crs.isValid() and raster_crs != self.crs_wgs84:
                pt = QgsCoordinateTransform(self.crs_wgs84, raster_crs, self.project).transform(pt)
            valor, ok = self.geoid_layer.dataProvider().sample(pt, 1)
            if not ok:
                return None
            return valor
        except Exception:
            return None

    def _geoide_cubre_zona_crs(self, crs: QgsCoordinateReferenceSystem) -> bool:
        """Comprueba si el geoide actualmente cargado (`self.geoid_layer`
        o `self.geoid_ggf`) tiene cobertura en algún punto de la zona de
        uso de `crs` (`crs.bounds()`, siempre en WGS84 grados,
        independientemente del CRS que sea). Se muestrea el centro y las
        cuatro esquinas de esa zona con `_sample_geoid_undulation` -- el
        mismo muestreo real que usa "Importar datos de campo" -- en vez de comparar
        cajas delimitadoras a mano, para no tener que lidiar por
        separado con la convención de longitud (0-360 este vs.
        -180..180) que puede traer un .ggf. Sin geoide cargado no hay
        nada que validar y devuelve True (no bloquea)."""
        if self.geoid_layer is None and self.geoid_ggf is None:
            return True
        area = crs.bounds()
        if area is None or area.isEmpty():
            return True  # CRS sin área de uso conocida -- no se puede validar, no se bloquea
        xmin, ymin, xmax, ymax = area.xMinimum(), area.yMinimum(), area.xMaximum(), area.yMaximum()
        xmid, ymid = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        puntos = ((xmid, ymid), (xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax))
        return any(self._sample_geoid_undulation(lon, lat) is not None for lon, lat in puntos)

    # -- Sección: Preplot Sísmico ------------------------------------------
    # -- Sección: Preplot Sísmico (rediseño v2.65.0) -----------------------
    # Estructura: pestañas arriba (Generar manual / Importar SPS-QLD /
    # Importar capa de QGIS) -- sólo se ve el contenido de la elegida --
    # y, debajo, una tabla de datos que ocupa todo el alto sobrante
    # (`stack_preplot_inferior`: en la pestaña 1 muestra los puntos
    # generados; en las pestañas 2 y 3 la previsualización de lo importado,
    # con el botón verde "Subir seleccionados a PREPLOT" fijo abajo a la
    # derecha).
    _MAX_FILAS_TABLA_PREPLOT_GEN = 2000  # filas que se dibujan en la tabla de puntos generados (todos se guardan)

    def _build_tab_preplot(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(6)
        v.addWidget(self._crear_banner_solo_lectura())

        self.tabs_preplot = PestanasAltoActual()
        # Que las pestañas NO se estiren a lo alto: sólo lo que necesite la
        # pestaña activa; todo el alto sobrante es para la tabla de abajo.
        self.tabs_preplot.setSizePolicy(
            _valor_enum(QSizePolicy, "Preferred", "Policy"), _valor_enum(QSizePolicy, "Maximum", "Policy")
        )
        self.tabs_preplot.addTab(self._build_preplot_pestana_generar(), "")
        self.tabs_preplot.addTab(self._build_preplot_pestana_archivo(), "")
        self.tabs_preplot.addTab(self._build_preplot_pestana_capa(), "")
        # El "?" de ayuda va en la esquina de la barra de pestañas (así no
        # gasta una fila propia).
        self.tabs_preplot.setCornerWidget(
            self._crear_boton_ayuda(["preplot_intro", "note_preplot_external"], "tab2_title"),
            _valor_enum(Qt, "TopRightCorner", "Corner"),
        )
        v.addWidget(self.tabs_preplot)

        v.addWidget(self._build_preplot_inferior(), 1)

        w.setStyleSheet(ESTILO_TARJETAS)

        self._retraducir_pestanas_preplot()
        self.tabs_preplot.currentChanged.connect(self._on_pestana_preplot_cambiada)
        self._on_pestana_preplot_cambiada(0)
        self._actualizar_modo_preplot()
        self._render_preplot_label()
        self._render_preplot_ext_resumen()
        return w

    # -- helpers de maquetación ------------------------------------------
    def _tarjeta_card(self, title_key):
        grp = self._reg(QGroupBox(), title_key, kind="title")
        grp.setObjectName("card")
        v = QVBoxLayout(grp)
        v.setSpacing(6)
        return grp, v

    @staticmethod
    def _bloque_filas(columnas=3):
        """Cuadrícula de `columnas` columnas de igual ancho para filas de
        campos numéricos compactos."""
        cont = QWidget()
        g = QGridLayout(cont)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(6)
        for c in range(columnas):
            g.setColumnStretch(c, 1)
        return cont, g

    def _celda_campo(self, grid, fila, col, key, widget, span=1):
        """Un campo con su rótulo ARRIBA (tenue), en la celda (fila, col)."""
        cont = QWidget()
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lbl = self._reg(QLabel(), key)
        lbl.setStyleSheet(ESTILO_ROTULO_TENUE)
        lay.addWidget(lbl)
        lay.addWidget(widget)
        grid.addWidget(cont, fila, col, 1, span)
        return cont

    @staticmethod
    def _spin_entero(minimo, maximo, valor):
        sp = QSpinBox()
        sp.setRange(minimo, maximo)
        sp.setValue(valor)
        return sp

    @staticmethod
    def _spin_decimal(minimo, maximo, valor=None):
        sp = QDoubleSpinBox()
        sp.setRange(minimo, maximo)
        sp.setDecimals(3)
        if valor is not None:
            sp.setValue(valor)
        return sp

    @staticmethod
    def _combo_campo():
        """Combo que no obliga a ensanchar la ventana según el nombre de
        campo más largo de la capa."""
        cb = QComboBox()
        cb.setSizeAdjustPolicy(_valor_enum(QComboBox, "AdjustToMinimumContentsLengthWithIcon", "SizeAdjustPolicy"))
        cb.setMinimumContentsLength(10)
        return cb

    def _boton_barra(self, key, tip_key, slot):
        b = QToolButton()
        b.setToolButtonStyle(_valor_enum(Qt, "ToolButtonTextOnly", "ToolButtonStyle"))
        b.setStyleSheet(ESTILO_BTN_BARRA)
        self._reg(b, key)
        self._reg(b, tip_key, kind="tooltip")
        b.clicked.connect(slot)
        return b

    # -- Pestaña 1: Generar preplot manual ---------------------------------
    def _build_preplot_pestana_generar(self):
        pag = QWidget()
        v = QVBoxLayout(pag)
        v.setSpacing(6)
        self._pp_widgets_grilla = []  # contenedores visibles sólo en modo "Grilla 3D"
        self._pp_widgets_linea = []   # ... sólo en modo "Línea 2D"

        # ---- Grupo A: geometría base ----
        grp_a, v_a = self._tarjeta_card("pp_card_a")
        fila_tipo = QHBoxLayout()
        fila_tipo.addWidget(self._reg(QLabel(), "pp_lbl_tipo"))
        self.rb_preplot_grilla = self._reg(QRadioButton(), "rb_grid")
        self.rb_preplot_linea = self._reg(QRadioButton(), "rb_line")
        self.rb_preplot_grilla.setChecked(True)
        grupo_modo = QButtonGroup(self)
        grupo_modo.addButton(self.rb_preplot_grilla)
        grupo_modo.addButton(self.rb_preplot_linea)
        fila_tipo.addWidget(self.rb_preplot_grilla)
        fila_tipo.addWidget(self.rb_preplot_linea)
        fila_tipo.addStretch(1)
        v_a.addLayout(fila_tipo)

        # Modo grilla, grupo A: Este | Norte | Azimut
        self.sp_grilla_origen_x = self._coord_spinbox()
        self.sp_grilla_origen_y = self._coord_spinbox()
        self.sp_grilla_azimut = self._spin_decimal(0.0, 359.999)
        self._reg(self.sp_grilla_azimut, "tip_grid_azimuth", kind="tooltip")
        a_grilla, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_origen_x", self.sp_grilla_origen_x)
        self._celda_campo(g, 0, 1, "pp_origen_y", self.sp_grilla_origen_y)
        self._celda_campo(g, 0, 2, "pp_azimut", self.sp_grilla_azimut)
        v_a.addWidget(a_grilla)
        self._pp_widgets_grilla.append(a_grilla)

        # Modo línea, grupo A: cómo definir la línea + sus coordenadas
        a_linea = QWidget()
        v_al = QVBoxLayout(a_linea)
        v_al.setContentsMargins(0, 0, 0, 0)
        v_al.setSpacing(6)
        fila_def = QHBoxLayout()
        fila_def.addWidget(self._reg(QLabel(), "pp_lbl_def_linea"))
        self.rb_linea_dos_puntos = self._reg(QRadioButton(), "rb_line_two_points")
        self.rb_linea_azimut = self._reg(QRadioButton(), "rb_line_azimuth")
        self.rb_linea_dos_puntos.setChecked(True)
        grupo_sub = QButtonGroup(self)
        grupo_sub.addButton(self.rb_linea_dos_puntos)
        grupo_sub.addButton(self.rb_linea_azimut)
        fila_def.addWidget(self.rb_linea_dos_puntos)
        fila_def.addWidget(self.rb_linea_azimut)
        fila_def.addStretch(1)
        v_al.addLayout(fila_def)

        self.stack_linea = QStackedWidget()
        pag_dos, g2 = self._bloque_filas()
        self.sp_linea_ini_x = self._coord_spinbox()
        self.sp_linea_ini_y = self._coord_spinbox()
        self.sp_linea_fin_x = self._coord_spinbox()
        self.sp_linea_fin_y = self._coord_spinbox()
        self._celda_campo(g2, 0, 0, "pp_ini_x", self.sp_linea_ini_x)
        self._celda_campo(g2, 0, 1, "pp_ini_y", self.sp_linea_ini_y)
        self._celda_campo(g2, 1, 0, "pp_fin_x", self.sp_linea_fin_x)
        self._celda_campo(g2, 1, 1, "pp_fin_y", self.sp_linea_fin_y)
        self.stack_linea.addWidget(pag_dos)
        pag_az, g3 = self._bloque_filas()
        self.sp_linea_az_x = self._coord_spinbox()
        self.sp_linea_az_y = self._coord_spinbox()
        self.sp_linea_azimut = self._spin_decimal(0.0, 359.999)
        self.sp_linea_longitud = self._spin_decimal(0.001, 100000000.0, 1000.0)
        self._celda_campo(g3, 0, 0, "pp_ini_x", self.sp_linea_az_x)
        self._celda_campo(g3, 0, 1, "pp_ini_y", self.sp_linea_az_y)
        self._celda_campo(g3, 0, 2, "pp_azimut", self.sp_linea_azimut)
        self._celda_campo(g3, 1, 0, "pp_longitud", self.sp_linea_longitud)
        self.stack_linea.addWidget(pag_az)
        v_al.addWidget(self.stack_linea)
        v_a.addWidget(a_linea)
        self._pp_widgets_linea.append(a_linea)
        self.rb_linea_dos_puntos.toggled.connect(lambda on: on and self.stack_linea.setCurrentIndex(0))
        self.rb_linea_azimut.toggled.connect(lambda on: on and self.stack_linea.setCurrentIndex(1))
        v.addWidget(grp_a)

        # ---- Grupo B: espaciados y líneas ----
        grp_b, v_b = self._tarjeta_card("pp_card_b")
        self.sp_grilla_esp_lineas = self._spin_decimal(0.001, 1000000.0, 300.0)
        self.sp_grilla_esp_estaciones = self._spin_decimal(0.001, 1000000.0, 50.0)
        self.sp_grilla_n_lineas = self._spin_entero(1, 100000, 5)
        self.sp_grilla_n_estaciones = self._spin_entero(1, 1000000, 20)
        b_grilla, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_dist_lineas", self.sp_grilla_esp_lineas)
        self._celda_campo(g, 0, 1, "pp_dist_estaciones", self.sp_grilla_esp_estaciones)
        self._celda_campo(g, 1, 0, "pp_n_lineas", self.sp_grilla_n_lineas)
        self._celda_campo(g, 1, 1, "pp_n_estaciones", self.sp_grilla_n_estaciones)
        v_b.addWidget(b_grilla)
        self._pp_widgets_grilla.append(b_grilla)

        self.sp_linea_espaciamiento = self._spin_decimal(0.001, 1000000.0, 50.0)
        self.sp_linea_numero = self._spin_entero(-999999, 999999, 1000)
        self.chk_linea_incluir_final = self._reg(QCheckBox(), "chk_include_end")
        self.chk_linea_incluir_final.setChecked(True)
        b_linea, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_dist_estaciones", self.sp_linea_espaciamiento)
        self._celda_campo(g, 0, 1, "pp_num_linea", self.sp_linea_numero)
        g.addWidget(self.chk_linea_incluir_final, 1, 0, 1, 3)
        v_b.addWidget(b_linea)
        self._pp_widgets_linea.append(b_linea)
        v.addWidget(grp_b)

        # ---- Grupo C: indexación y nomenclatura ----
        grp_c, v_c = self._tarjeta_card("pp_card_c")
        self.sp_grilla_primera_linea = self._spin_entero(-999999, 999999, 1000)
        self.sp_grilla_incr_linea = self._spin_entero(-99999, 99999, 1)
        self.sp_grilla_digitos_linea = self._spin_entero(1, 10, 4)
        self.sp_grilla_primera_estacion = self._spin_entero(-999999, 999999, 1)
        self.sp_grilla_incr_estacion = self._spin_entero(-99999, 99999, 1)
        self.sp_grilla_digitos_estacion = self._spin_entero(1, 10, 4)
        self.cb_grilla_descriptor = QComboBox()
        self._fill_descriptor_combo(self.cb_grilla_descriptor)
        c_grilla, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_primer_linea", self.sp_grilla_primera_linea)
        self._celda_campo(g, 0, 1, "pp_incr_linea", self.sp_grilla_incr_linea)
        self._celda_campo(g, 0, 2, "pp_dig_linea", self.sp_grilla_digitos_linea)
        self._celda_campo(g, 1, 0, "pp_primer_estacion", self.sp_grilla_primera_estacion)
        self._celda_campo(g, 1, 1, "pp_incr_estacion", self.sp_grilla_incr_estacion)
        self._celda_campo(g, 1, 2, "pp_dig_estacion", self.sp_grilla_digitos_estacion)
        self._celda_campo(g, 2, 0, "pp_descriptor", self.cb_grilla_descriptor)
        v_c.addWidget(c_grilla)
        self._pp_widgets_grilla.append(c_grilla)

        self.sp_linea_primera_estacion = self._spin_entero(-999999, 999999, 1)
        self.sp_linea_incr_estacion = self._spin_entero(-99999, 99999, 1)
        self.sp_linea_digitos_estacion = self._spin_entero(1, 10, 4)
        self.sp_linea_digitos_linea = self._spin_entero(1, 10, 4)
        self.cb_linea_descriptor = QComboBox()
        self._fill_descriptor_combo(self.cb_linea_descriptor)
        c_linea, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_primer_estacion", self.sp_linea_primera_estacion)
        self._celda_campo(g, 0, 1, "pp_incr_estacion", self.sp_linea_incr_estacion)
        self._celda_campo(g, 0, 2, "pp_dig_estacion", self.sp_linea_digitos_estacion)
        self._celda_campo(g, 1, 0, "pp_dig_linea", self.sp_linea_digitos_linea)
        self._celda_campo(g, 1, 1, "pp_descriptor", self.cb_linea_descriptor)
        v_c.addWidget(c_linea)
        self._pp_widgets_linea.append(c_linea)
        v.addWidget(grp_c)

        # ---- Barra de acciones fija + estado ----
        barra = QHBoxLayout()
        self.tb_pp_generar = self._boton_barra("pp_tb_generar", "pp_tip_generar", self.generar_preplot)
        self.tb_pp_limpiar = self._boton_barra("pp_tb_limpiar", "pp_tip_limpiar", self.limpiar_preplot_generado)
        self.tb_pp_guardar = self._boton_barra("pp_tb_guardar", "pp_tip_guardar", self.guardar_preplot_en_bd)
        barra.addWidget(self.tb_pp_generar)
        barra.addWidget(self.tb_pp_limpiar)
        barra.addWidget(self.tb_pp_guardar)
        barra.addStretch(1)
        v.addLayout(barra)
        # Mensaje de estado sutil, justo debajo de la barra (los tres
        # botones ya ocupan casi todo el ancho de la ventana).
        self.lbl_preplot_resumen = QLabel()
        self.lbl_preplot_resumen.setTextFormat(_valor_enum(Qt, "RichText", "TextFormat"))
        self.lbl_preplot_resumen.setWordWrap(True)
        self.lbl_preplot_resumen.setSizePolicy(SIZE_POLICY_IGNORED, _valor_enum(QSizePolicy, "Preferred", "Policy"))
        v.addWidget(self.lbl_preplot_resumen)
        v.addStretch(1)

        self.rb_preplot_grilla.toggled.connect(self._actualizar_modo_preplot)
        self.rb_linea_dos_puntos.toggled.connect(self._actualizar_modo_preplot)
        return pag

    def _actualizar_modo_preplot(self, *_args):
        """Muestra los bloques de campos del modo elegido (Grilla 3D /
        Línea 2D) y oculta los del otro; la casilla "incluir el punto
        final" sólo aplica a la línea entre dos puntos."""
        grilla = self.rb_preplot_grilla.isChecked()
        for wdg in self._pp_widgets_grilla:
            wdg.setVisible(grilla)
        for wdg in self._pp_widgets_linea:
            wdg.setVisible(not grilla)
        self.chk_linea_incluir_final.setVisible(self.rb_linea_dos_puntos.isChecked())

    # -- Pestaña 2: Importar archivo externo (SPS / QLD) -------------------
    def _build_preplot_pestana_archivo(self):
        pag = QWidget()
        v = QVBoxLayout(pag)
        v.setSpacing(6)
        grp, v_g = self._tarjeta_card("pp_card_archivo")

        self.spn_ext_digitos_linea = self._spin_entero(1, 10, 4)
        self.spn_ext_digitos_estacion = self._spin_entero(1, 10, 4)
        self._reg(self.spn_ext_digitos_linea, "pp_tip_digitos_ext", kind="tooltip")
        self._reg(self.spn_ext_digitos_estacion, "pp_tip_digitos_ext", kind="tooltip")
        cont, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_lbl_dig_linea_ext", self.spn_ext_digitos_linea)
        self._celda_campo(g, 0, 1, "pp_lbl_dig_estacion_ext", self.spn_ext_digitos_estacion)
        v_g.addWidget(cont)

        fila_btn = QHBoxLayout()
        btn_sps = self._reg(QPushButton(), "btn_import_sps")
        btn_sps.clicked.connect(self.importar_preplot_sps)
        btn_qld = self._reg(QPushButton(), "btn_import_qld")
        btn_qld.clicked.connect(self.importar_preplot_qld)
        for b in (btn_sps, btn_qld):
            b.setMinimumHeight(30)
            fila_btn.addWidget(b, 1)
        v_g.addLayout(fila_btn)
        v.addWidget(grp)
        v.addStretch(1)
        return pag

    # -- Pestaña 3: Importar capa de QGIS -----------------------------------
    def _build_preplot_pestana_capa(self):
        pag = QWidget()
        v = QVBoxLayout(pag)
        v.setSpacing(6)
        grp, v_g = self._tarjeta_card("pp_card_capa")

        v_g.addWidget(self._reg(QLabel(), "lbl_ext_layer"))
        fila_capa = QHBoxLayout()
        self.cb_ext_capa = self._combo_campo()
        self.cb_ext_capa.setMinimumContentsLength(20)
        btn_refrescar = QToolButton()
        btn_refrescar.setText("⟳")
        btn_refrescar.setStyleSheet(ESTILO_BTN_BARRA)
        self._reg(btn_refrescar, "pp_tip_refrescar_capas", kind="tooltip")
        btn_refrescar.clicked.connect(self._refrescar_capas_preplot_ext)
        fila_capa.addWidget(self.cb_ext_capa, 1)
        fila_capa.addWidget(btn_refrescar)
        v_g.addLayout(fila_capa)

        self.cb_ext_col_nombre = self._combo_campo()
        self.cb_ext_col_track = self._combo_campo()
        self.cb_ext_col_bin = self._combo_campo()
        self.cb_ext_col_z = self._combo_campo()
        self.cb_ext_col_descriptor = self._combo_campo()
        cont, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "pp_campo_nombre", self.cb_ext_col_nombre)
        self._celda_campo(g, 0, 1, "pp_campo_linea", self.cb_ext_col_track)
        self._celda_campo(g, 0, 2, "pp_campo_estacion", self.cb_ext_col_bin)
        self._celda_campo(g, 1, 0, "pp_campo_cota", self.cb_ext_col_z)
        self._celda_campo(g, 1, 1, "pp_campo_descriptor", self.cb_ext_col_descriptor)
        v_g.addWidget(cont)

        self.cb_ext_capa.currentIndexChanged.connect(self._on_ext_capa_changed)
        self._refrescar_capas_preplot_ext()

        btn_importar = self._reg(QPushButton(), "btn_import_capa_qgis")
        btn_importar.setMinimumHeight(30)
        btn_importar.clicked.connect(self.importar_preplot_capa_qgis)
        v_g.addWidget(btn_importar)
        v.addWidget(grp)
        v.addStretch(1)
        return pag

    # -- Zona inferior: tabla de datos + cierre ------------------------------
    def _build_preplot_inferior(self):
        self.stack_preplot_inferior = QStackedWidget()

        # Página 0 (pestaña 1): puntos generados.
        pg0 = QWidget()
        v0 = QVBoxLayout(pg0)
        v0.setContentsMargins(0, 0, 0, 0)
        v0.setSpacing(4)
        self.tbl_preplot_gen_preview = QTableWidget(0, 6)
        self.tbl_preplot_gen_preview.setHorizontalHeaderLabels(self._gen_preview_headers())
        self.tbl_preplot_gen_preview.horizontalHeader().setStretchLastSection(True)
        self.tbl_preplot_gen_preview.setMinimumHeight(200)
        self.tbl_preplot_gen_preview.verticalHeader().setDefaultSectionSize(24)
        v0.addWidget(self.tbl_preplot_gen_preview, 1)
        self.lbl_preplot_gen_nota = QLabel("")
        self.lbl_preplot_gen_nota.setStyleSheet(ESTILO_ROTULO_TENUE)
        v0.addWidget(self.lbl_preplot_gen_nota)
        self.stack_preplot_inferior.addWidget(pg0)

        # Página 1 (pestañas 2 y 3): previsualización de lo importado.
        pg1 = QWidget()
        v1 = QVBoxLayout(pg1)
        v1.setContentsMargins(0, 0, 0, 0)
        v1.setSpacing(4)
        self.tbl_preplot_ext_preview = QTableWidget(0, EXT_PREVIEW_N_COLS)
        self.tbl_preplot_ext_preview.setHorizontalHeaderLabels(self._ext_preview_headers())
        self.tbl_preplot_ext_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl_preplot_ext_preview.setMinimumHeight(200)
        self.tbl_preplot_ext_preview.verticalHeader().setDefaultSectionSize(24)
        v1.addWidget(self.tbl_preplot_ext_preview, 1)

        fila_resumen = QHBoxLayout()
        self.lbl_preplot_ext_resumen = QLabel("")
        self.lbl_preplot_ext_resumen.setStyleSheet(ESTILO_ROTULO_TENUE)
        fila_resumen.addWidget(self.lbl_preplot_ext_resumen, 1)
        btn_limpiar_ext = self._reg(QPushButton(), "btn_clear_preview")
        btn_limpiar_ext.setStyleSheet(ESTILO_BTN_ENLACE)
        btn_limpiar_ext.clicked.connect(self.limpiar_preplot_ext_preview)
        fila_resumen.addWidget(btn_limpiar_ext)
        self.btn_toggle_log_preplot = QPushButton()
        self.btn_toggle_log_preplot.setCheckable(True)
        self.btn_toggle_log_preplot.setStyleSheet(ESTILO_BTN_ENLACE)
        fila_resumen.addWidget(self.btn_toggle_log_preplot)
        v1.addLayout(fila_resumen)

        # El registro queda oculto por defecto, pero `self.log_preplot`
        # sigue recibiendo texto (y se abre solo si hay un aviso).
        self.log_preplot = QPlainTextEdit()
        self.log_preplot.setReadOnly(True)
        self.log_preplot.setMaximumHeight(90)
        self.log_preplot.setVisible(False)
        self.btn_toggle_log_preplot.toggled.connect(self.log_preplot.setVisible)
        self.btn_toggle_log_preplot.toggled.connect(lambda _c: self._actualizar_texto_boton_log_preplot())
        self._actualizar_texto_boton_log_preplot()
        v1.addWidget(self.log_preplot)

        # Cierre: "Processor" a la izquierda y el botón verde a la derecha.
        fila_cierre = QHBoxLayout()
        lbl_proc = self._reg(QLabel(), "pp_lbl_processor")
        self._reg(lbl_proc, "lbl_processor", kind="tooltip")
        fila_cierre.addWidget(lbl_proc)
        self.txt_preplot_ext_processor = QLineEdit()
        self.txt_preplot_ext_processor.setMinimumWidth(190)
        self.txt_preplot_ext_processor.setMaximumWidth(280)
        self._reg(self.txt_preplot_ext_processor, "pp_ph_processor", kind="placeholder")
        self._reg(self.txt_preplot_ext_processor, "lbl_processor", kind="tooltip")
        fila_cierre.addWidget(self.txt_preplot_ext_processor, 1)
        fila_cierre.addStretch(1)
        self.btn_subir_preplot_ext = self._reg(QPushButton(), "btn_upload_preplot_external")
        self.btn_subir_preplot_ext.setStyleSheet(ESTILO_BTN_SUBIR_VERDE)
        self.btn_subir_preplot_ext.setMinimumHeight(40)
        self.btn_subir_preplot_ext.setMinimumWidth(300)
        self.btn_subir_preplot_ext.setCursor(_valor_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.btn_subir_preplot_ext.setEnabled(False)
        self.btn_subir_preplot_ext.clicked.connect(self.subir_preplot_externo)
        fila_cierre.addWidget(self.btn_subir_preplot_ext)
        v1.addLayout(fila_cierre)
        self.stack_preplot_inferior.addWidget(pg1)
        return self.stack_preplot_inferior

    def _on_pestana_preplot_cambiada(self, idx):
        """Pestaña 1 -> tabla de puntos generados; pestañas 2 y 3 ->
        previsualización de lo importado. Las páginas que no están a la
        vista pasan a política vertical `Ignored`, para que ni las
        pestañas ni la zona inferior reserven la altura de la página más
        alta (QStackedLayout respeta `Ignored` al calcular su tamaño)."""
        pref = _valor_enum(QSizePolicy, "Preferred", "Policy")
        for i in range(self.tabs_preplot.count()):
            self.tabs_preplot.widget(i).setSizePolicy(pref, pref if i == idx else SIZE_POLICY_IGNORED)
        destino = 0 if idx == 0 else 1
        for i in range(self.stack_preplot_inferior.count()):
            self.stack_preplot_inferior.widget(i).setSizePolicy(pref, pref if i == destino else SIZE_POLICY_IGNORED)
        self.stack_preplot_inferior.setCurrentIndex(destino)
        self.tabs_preplot.updateGeometry()

    def _retraducir_pestanas_preplot(self):
        for i, key in enumerate(("pp_tab_generar", "pp_tab_archivo", "pp_tab_capa")):
            self.tabs_preplot.setTabText(i, self.t(key))
        # Que los títulos de las 3 pestañas quepan siempre completos (sin
        # flechas de desplazamiento): ancho mínimo = el de la barra de
        # pestañas + el botón "?" de la esquina.
        barra = self.tabs_preplot.tabBar()
        barra.setUsesScrollButtons(False)
        self.tabs_preplot.setMinimumWidth(barra.sizeHint().width() + 40)

    def _actualizar_texto_boton_log_preplot(self):
        key = "btn_log_hide" if self.btn_toggle_log_preplot.isChecked() else "btn_log_show"
        self.btn_toggle_log_preplot.setText(self.t(key))

    def _gen_preview_headers(self):
        return [
            self.t("col_point_name"), self.t("col_track"), self.t("col_bin"),
            self.t("col_easting"), self.t("col_northing"), self.t("col_descriptor"),
        ]

    def _llenar_tabla_preplot_gen(self):
        """Dibuja en la tabla de la pestaña 1 los puntos generados (sólo
        lectura). Se dibujan como máximo `_MAX_FILAS_TABLA_PREPLOT_GEN`
        filas para que una grilla enorme no congele la ventana; la capa
        temporal y el guardado en PREPLOT siempre usan TODOS los puntos."""
        puntos = getattr(self, "preplot_generated_points", None) or []
        mostrados = puntos[: self._MAX_FILAS_TABLA_PREPLOT_GEN]
        tbl = self.tbl_preplot_gen_preview
        tbl.setUpdatesEnabled(False)
        try:
            tbl.setRowCount(len(mostrados))
            for row, p in enumerate(mostrados):
                textos = (p.name, p.track, p.bin, f"{p.x:.3f}", f"{p.y:.3f}", p.descriptor)
                for col, texto in enumerate(textos):
                    item = QTableWidgetItem(str(texto))
                    item.setFlags(item.flags() & ~ITEM_IS_EDITABLE)
                    tbl.setItem(row, col, item)
        finally:
            tbl.setUpdatesEnabled(True)
        if len(puntos) > len(mostrados):
            self.lbl_preplot_gen_nota.setText(self.t("pp_gen_truncado", shown=len(mostrados), n=len(puntos)))
        else:
            self.lbl_preplot_gen_nota.setText("")

    def _quitar_capa_preplot_generado(self):
        capa = getattr(self, "_preplot_gen_layer", None)
        if capa is None:
            return
        try:
            if QgsProject.instance().mapLayer(capa.id()) is not None:
                self.project.removeMapLayer(capa.id())
        except RuntimeError:
            # El objeto Qt/QGIS ya fue eliminado (p.ej. el usuario quitó
            # la capa a mano) -- nada que limpiar.
            pass
        self._preplot_gen_layer = None

    def limpiar_preplot_generado(self):
        """"Limpiar previsualización" de la pestaña 1: quita la capa
        temporal del mapa y vacía los puntos generados/la tabla. No toca
        lo que ya se haya guardado en PREPLOT."""
        self._quitar_capa_preplot_generado()
        self.preplot_generated_points = None
        self._last_preplot_summary = None
        self._llenar_tabla_preplot_gen()
        self._render_preplot_label()

    @staticmethod
    def _coord_spinbox(default=0.0):
        sp = QDoubleSpinBox()
        sp.setRange(-100000000.0, 100000000.0)
        sp.setDecimals(3)
        sp.setValue(default)
        return sp

    def _fill_descriptor_combo(self, combo: QComboBox):
        """(Re)llena un combo de Descriptor conservando el valor de
        datos seleccionado ("RECEPTOR"/"FUENTE"/"") aunque cambie el
        idioma de la etiqueta visible."""
        current_data = combo.currentData() if combo.count() else "RECEPTOR"
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.t("descriptor_receiver"), "RECEPTOR")
        combo.addItem(self.t("descriptor_source"), "FUENTE")
        combo.addItem(self.t("descriptor_none"), "")
        idx = combo.findData(current_data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def generar_preplot(self):
        try:
            if self.rb_preplot_grilla.isChecked():
                puntos = preplot_generator.generate_grid_preplot(
                    origin_x=self.sp_grilla_origen_x.value(),
                    origin_y=self.sp_grilla_origen_y.value(),
                    azimuth_deg=self.sp_grilla_azimut.value(),
                    line_spacing=self.sp_grilla_esp_lineas.value(),
                    station_spacing=self.sp_grilla_esp_estaciones.value(),
                    n_lines=self.sp_grilla_n_lineas.value(),
                    n_stations=self.sp_grilla_n_estaciones.value(),
                    first_line_number=self.sp_grilla_primera_linea.value(),
                    line_increment=self.sp_grilla_incr_linea.value(),
                    first_station_number=self.sp_grilla_primera_estacion.value(),
                    station_increment=self.sp_grilla_incr_estacion.value(),
                    line_digits=self.sp_grilla_digitos_linea.value(),
                    station_digits=self.sp_grilla_digitos_estacion.value(),
                    descriptor=self.cb_grilla_descriptor.currentData() or "",
                )
                modo_key = "preplot_mode_grid"
            else:
                descriptor = self.cb_linea_descriptor.currentData() or ""
                if self.rb_linea_dos_puntos.isChecked():
                    puntos = preplot_generator.generate_line_preplot_two_points(
                        start_x=self.sp_linea_ini_x.value(), start_y=self.sp_linea_ini_y.value(),
                        end_x=self.sp_linea_fin_x.value(), end_y=self.sp_linea_fin_y.value(),
                        station_spacing=self.sp_linea_espaciamiento.value(),
                        line_number=self.sp_linea_numero.value(),
                        first_station_number=self.sp_linea_primera_estacion.value(),
                        station_increment=self.sp_linea_incr_estacion.value(),
                        line_digits=self.sp_linea_digitos_linea.value(),
                        station_digits=self.sp_linea_digitos_estacion.value(),
                        include_end=self.chk_linea_incluir_final.isChecked(),
                        descriptor=descriptor,
                    )
                else:
                    puntos = preplot_generator.generate_line_preplot_azimuth(
                        start_x=self.sp_linea_az_x.value(), start_y=self.sp_linea_az_y.value(),
                        azimuth_deg=self.sp_linea_azimut.value(), length=self.sp_linea_longitud.value(),
                        station_spacing=self.sp_linea_espaciamiento.value(),
                        line_number=self.sp_linea_numero.value(),
                        first_station_number=self.sp_linea_primera_estacion.value(),
                        station_increment=self.sp_linea_incr_estacion.value(),
                        line_digits=self.sp_linea_digitos_linea.value(),
                        station_digits=self.sp_linea_digitos_estacion.value(),
                        descriptor=descriptor,
                    )
                modo_key = "preplot_mode_line"
        except ValueError as e:
            QMessageBox.warning(self, self.t("warn_invalid_params_title"), str(e))
            return

        modo_texto = self.t(modo_key)
        self.preplot_generated_points = puntos
        self._last_preplot_summary = (len(puntos), modo_key)
        self._render_preplot_label()
        self._llenar_tabla_preplot_gen()
        self.log_preplot.appendPlainText(self.t("log_preplot_generated", n=len(puntos), modo=modo_texto))

        # La capa temporal anterior se reemplaza (no se acumulan).
        self._quitar_capa_preplot_generado()
        dest_crs = self._working_crs()
        layer = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", "Preplot generado", "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("linea", FIELD_INT),
            QgsField("estacion", FIELD_INT),
            QgsField("descriptor", FIELD_STRING),
        ])
        layer.updateFields()
        feats = []
        for p in puntos:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)))
            f.setAttributes([p.name, p.track, p.bin, p.descriptor])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        self._preplot_gen_layer = layer
        self._zoom_canvas_a_capa(layer)

    @_escritura()
    def guardar_preplot_en_bd(self):
        if not self._require_project():
            return
        puntos = getattr(self, "preplot_generated_points", None)
        if not puntos:
            QMessageBox.information(self, self.t("info_nothing_to_save_title"), self.t("info_nothing_to_save_body"))
            return

        dest_crs = self._working_crs()
        filas = []
        for p in puntos:
            if dest_crs != self.crs_wgs84:
                lon, lat = _transform_xy(p.x, p.y, dest_crs, self.crs_wgs84, self.project)
            else:
                lon, lat = p.x, p.y
            filas.append({
                "Station_Text": p.name,
                "Track": p.track,
                "Bin": p.bin,
                "Descriptor": p.descriptor,
                "Local_Easting": p.x,
                "Local_Northing": p.y,
                "WGS84_Longitude": lon,
                "WGS84_Latitude": lat,
                "Local_System": dest_crs.authid(),
                "Populate_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Processor": "GNSSeismic (QGIS) - preplot generado",
            })
        try:
            n = db_schema.insert_rows(self.conn, "PREPLOT", db_schema.PREPLOT_COLUMNS, filas)
            self.actualizar_conteos()
            self.log_preplot.appendPlainText(self.t("log_preplot_saved", n=n))
            QMessageBox.information(self, self.t("ok_title"), self.t("msg_preplot_saved_body", n=n))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_preplot_save", error=e, trace=traceback.format_exc()))

    # -- Preplot externo (SPS de Omni 3D/mesa de Sercel, o capa de QGIS) --
    def _ext_preview_headers(self):
        return [
            self.t("col_include"), self.t("col_source"), self.t("col_point_name"),
            self.t("col_track"), self.t("col_bin"), self.t("col_easting"),
            self.t("col_northing"), self.t("col_elevation"), self.t("col_status"),
        ]

    def _set_ext_preview_readonly_cell(self, row, col, text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~ITEM_IS_EDITABLE)
        self.tbl_preplot_ext_preview.setItem(row, col, item)

    def _nombres_preplot_existentes(self):
        """Nombres (Station_Text, en mayúsculas) que ya están en PREPLOT
        de este proyecto -- para marcar como posible duplicado un punto
        del preplot externo que traiga el mismo nombre."""
        if self.conn is None:
            return set()
        cur = self.conn.execute("SELECT Station_Text FROM PREPLOT WHERE Station_Text IS NOT NULL")
        return {str(row[0]).strip().upper() for row in cur.fetchall() if row[0] is not None}

    def _capa_preplot_ext_seleccionada(self):
        layer_id = self.cb_ext_capa.currentData()
        if not layer_id:
            return None
        return self.project.mapLayer(layer_id)

    def _refrescar_capas_preplot_ext(self):
        """(Re)llena el combo de capas con las capas vectoriales de
        puntos ya cargadas en el proyecto de QGIS -- shapefile,
        GeoPackage, o un CSV delimitado por comas ya agregado como capa
        de puntos (p.ej. con "Agregar capa de texto delimitado"). Se
        puede volver a llamar con el botón "Actualizar lista" si se
        agrega una capa después de abrir esta ventana."""
        capa_actual = self.cb_ext_capa.currentData() if self.cb_ext_capa.count() else None
        self.cb_ext_capa.blockSignals(True)
        self.cb_ext_capa.clear()
        self.cb_ext_capa.addItem(self.t("opt_select_layer"), None)
        for layer in self.project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if layer.geometryType() != _valor_enum(QgsWkbTypes, "PointGeometry", "GeometryType"):
                continue
            self.cb_ext_capa.addItem(layer.name(), layer.id())
        if capa_actual is not None:
            idx = self.cb_ext_capa.findData(capa_actual)
            if idx >= 0:
                self.cb_ext_capa.setCurrentIndex(idx)
        self.cb_ext_capa.blockSignals(False)
        self._on_ext_capa_changed()

    def _on_ext_capa_changed(self, _idx=None):
        """Al elegir (o refrescar) la capa de arriba, vuelve a llenar
        los combos de campos (Nombre/Track/Bin/Cota/Descriptor) con los
        campos de esa capa, preseleccionando por nombre igual que en
        "Comparar"."""
        layer = self._capa_preplot_ext_seleccionada()
        nombres = [f.name() for f in layer.fields()] if layer is not None else []

        self.cb_ext_col_nombre.clear()
        self.cb_ext_col_nombre.addItems(nombres)
        self._preseleccionar_columna(self.cb_ext_col_nombre, ["nombre", "name", "punto", "codigo", "código", "id", "station"])

        for cb, candidatos in (
            (self.cb_ext_col_track, ["track", "linea", "línea", "line"]),
            (self.cb_ext_col_bin, ["bin", "estacion", "estación", "station"]),
            (self.cb_ext_col_z, ["cota", "z", "altura", "elev", "height"]),
            (self.cb_ext_col_descriptor, ["descriptor", "descripcion", "descripción", "tipo"]),
        ):
            cb.clear()
            cb.addItem(self.t("none_option"))
            cb.addItems(nombres)
            self._preseleccionar_columna(cb, candidatos)

    def _combo_ext_field_opcional(self, combo: QComboBox):
        texto = combo.currentText().strip()
        if not texto or texto == self.t("none_option"):
            return None
        return texto

    def importar_preplot_sps(self):
        """Lee un archivo SPS (fuentes .S01, receptores .R01, o un .sps
        genérico con ambos) -- el formato que exportan Omni 3D y la mesa
        de Sercel -- y agrega sus puntos a la previsualización de abajo.
        Las coordenadas del SPS se asumen ya en el CRS de trabajo del
        proyecto (igual que el preplot generado por el propio plugin);
        no se aplica ninguna transformación aquí."""
        if not self._require_project():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t("dlg_import_sps_title"), "", self.t("filter_sps"))
        if not path:
            return
        try:
            registros = export_writers.parse_sps_file(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_sps_read", error=e))
            return
        if not registros:
            QMessageBox.warning(self, self.t("warn_sps_empty_title"), self.t("warn_sps_empty_body"))
            return

        line_digits = self.spn_ext_digitos_linea.value()
        station_digits = self.spn_ext_digitos_estacion.value()
        origen = os.path.basename(path)
        nuevas = []
        for r in registros:
            nombre = preplot_generator.format_point_name(r["line_name"], r["point_number"], line_digits, station_digits)
            track = int(r["line_name"]) if float(r["line_name"]).is_integer() else r["line_name"]
            bin_ = int(r["point_number"]) if float(r["point_number"]).is_integer() else r["point_number"]
            descriptor = "FUENTE" if r["tipo"] == "S" else ("RECEPTOR" if r["tipo"] == "R" else "")
            nuevas.append({
                "origen": origen, "nombre": nombre, "track": track, "bin": bin_,
                "x": r["easting"], "y": r["northing"], "z": r.get("elevation"),
                "descriptor": descriptor,
            })
        self._agregar_preplot_ext_preview(nuevas)

    def importar_preplot_qld(self):
        """Lee un archivo .qld ("QLD9"), formato binario propietario de
        diseño/QC de puntos sísmicos (reconstruido por ingeniería inversa
        contra un archivo real del usuario -- ver `qld_reader.py`), y
        agrega sus puntos a la previsualización de abajo. Igual que con
        Hi-Target, se usan siempre la latitud/longitud (WGS84) que trae
        cada punto -- nunca su Este/Norte en la grilla local del
        archivo -- porque esas sí se pueden transformar al CRS de
        trabajo del proyecto sin tener que adivinar a qué EPSG
        corresponde el nombre de zona/datum que declara el propio
        archivo; track/bin se separan del nombre del punto con la misma
        heurística que Hi-Target."""
        if not self._require_project():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t("dlg_import_qld_title"), "", self.t("filter_qld"))
        if not path:
            return
        try:
            qf = qld_reader.parse_qld_file(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_qld_read", error=e))
            return
        if qf.n_points == 0:
            QMessageBox.warning(self, self.t("warn_qld_empty_title"), self.t("warn_qld_empty_body"))
            return
        for w in qf.warnings:
            self.log_preplot.appendPlainText(self.t("log_qld_datum_warning", warning=w))
        if qf.warnings:
            # El registro está oculto por defecto: con un aviso de datum se
            # abre solo para que no pase inadvertido.
            self.btn_toggle_log_preplot.setChecked(True)

        line_digits = self.spn_ext_digitos_linea.value()
        dest_crs = self._working_crs()
        origen = os.path.basename(path)
        nuevas = []
        for p in qf.points:
            x, y = _transform_xy(p.lon, p.lat, self.crs_wgs84, dest_crs, self.project)
            track, bin_ = _track_bin_heuristic(p.name, line_digits)
            nuevas.append({
                "origen": origen, "nombre": p.name, "track": track, "bin": bin_,
                "x": x, "y": y, "z": p.z, "descriptor": "",
            })
        self._agregar_preplot_ext_preview(nuevas)

    def importar_preplot_capa_qgis(self):
        """Lee los puntos de la capa de QGIS elegida arriba (shapefile,
        GeoPackage, o un CSV delimitado por comas ya agregado como capa
        de puntos), tomando nombre/track/bin/cota/descriptor de los
        campos elegidos, transforma sus coordenadas del CRS propio de
        la capa al CRS de trabajo del proyecto, y agrega sus puntos a
        la previsualización de abajo."""
        if not self._require_project():
            return
        layer = self._capa_preplot_ext_seleccionada()
        if layer is None:
            QMessageBox.information(self, self.t("info_select_layer_title"), self.t("info_select_layer_body"))
            return
        if layer.geometryType() != _valor_enum(QgsWkbTypes, "PointGeometry", "GeometryType"):
            QMessageBox.warning(self, self.t("warn_layer_no_points_title"), self.t("warn_layer_no_points_body"))
            return

        name_field = self.cb_ext_col_nombre.currentText().strip()
        if not name_field:
            QMessageBox.warning(self, self.t("warn_missing_name_field_title"), self.t("warn_missing_name_field_body"))
            return
        track_field = self._combo_ext_field_opcional(self.cb_ext_col_track)
        bin_field = self._combo_ext_field_opcional(self.cb_ext_col_bin)
        z_field = self._combo_ext_field_opcional(self.cb_ext_col_z)
        descriptor_field = self._combo_ext_field_opcional(self.cb_ext_col_descriptor)

        src_crs = layer.crs()
        dest_crs = self._working_crs()
        origen = layer.name()
        nuevas = []
        try:
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                wkb_type = geom.wkbType()
                punto = geom.constGet()
                if QgsWkbTypes.isMultiType(wkb_type):
                    if punto.numGeometries() == 0:
                        continue
                    punto = punto.geometryN(0)
                x, y = punto.x(), punto.y()
                z = punto.z() if QgsWkbTypes.hasZ(wkb_type) else None
                if z is not None and z != z:  # NaN -> sin Z real
                    z = None
                if src_crs != dest_crs:
                    x, y = _transform_xy(x, y, src_crs, dest_crs, self.project)

                nombre = feat[name_field]
                nombre = str(nombre).strip() if nombre is not None else ""
                if not nombre:
                    continue
                track = feat[track_field] if track_field else None
                bin_ = feat[bin_field] if bin_field else None
                if z_field:
                    z_attr = feat[z_field]
                    if z_attr is not None:
                        z = z_attr
                if descriptor_field:
                    desc_val = feat[descriptor_field]
                    descriptor = str(desc_val).strip() if desc_val is not None else ""
                else:
                    descriptor = ""

                nuevas.append({
                    "origen": origen, "nombre": nombre, "track": track, "bin": bin_,
                    "x": x, "y": y, "z": z, "descriptor": descriptor,
                })
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_layer_import", error=e))
            return

        if not nuevas:
            QMessageBox.warning(self, self.t("warn_layer_no_points_title"), self.t("warn_layer_no_points_body"))
            return
        self._agregar_preplot_ext_preview(nuevas)

    def _agregar_preplot_ext_preview(self, nuevas):
        """Agrega `nuevas` (de un SPS o un CSV recién leído) a la
        previsualización acumulada -- se puede cargar primero un SPS y
        después un CSV (o varios SPS) antes de subir todo junto con un
        solo `Processor`. Marca como duplicado cualquier punto cuyo
        nombre ya exista en PREPLOT o se repita dentro de lo ya
        acumulado en la previsualización; por seguridad, los duplicados
        arrancan sin la casilla "Incluir" marcada (el usuario decide si
        de todas formas quiere subirlos)."""
        existentes = self._nombres_preplot_existentes()
        vistos = {f["nombre"].strip().upper() for f in self._preplot_ext_preview}
        for fila in nuevas:
            clave = fila["nombre"].strip().upper()
            duplicado = clave in existentes or clave in vistos
            fila["duplicado"] = duplicado
            fila["incluir"] = not duplicado
            vistos.add(clave)
        self._preplot_ext_preview.extend(nuevas)
        self._llenar_tabla_preplot_ext()
        self._actualizar_capa_provisional_preplot_ext()

    def _llenar_tabla_preplot_ext(self):
        tbl = self.tbl_preplot_ext_preview
        tbl.setRowCount(len(self._preplot_ext_preview))
        for row, fila in enumerate(self._preplot_ext_preview):
            chk_item = QTableWidgetItem()
            flags = (chk_item.flags() | ITEM_IS_USER_CHECKABLE | ITEM_IS_SELECTABLE | ITEM_IS_ENABLED)
            flags &= ~ITEM_IS_EDITABLE
            chk_item.setFlags(flags)
            chk_item.setCheckState(CHECK_STATE_CHECKED if fila.get("incluir") else CHECK_STATE_UNCHECKED)
            tbl.setItem(row, EXT_PREVIEW_COL_INCLUDE, chk_item)

            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_ORIGEN, fila.get("origen", ""))

            item_nombre = QTableWidgetItem(fila["nombre"])
            tbl.setItem(row, EXT_PREVIEW_COL_NOMBRE, item_nombre)

            track = fila.get("track")
            bin_ = fila.get("bin")
            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_TRACK, track if track is not None else "-")
            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_BIN, bin_ if bin_ is not None else "-")
            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_ESTE, f"{fila['x']:.3f}")
            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_NORTE, f"{fila['y']:.3f}")
            z = fila.get("z")
            self._set_ext_preview_readonly_cell(row, EXT_PREVIEW_COL_COTA, f"{z:.3f}" if z is not None else "-")

            duplicado = fila.get("duplicado")
            estado_texto = self.t("status_duplicate_preplot") if duplicado else self.t("status_new_point")
            item_estado = QTableWidgetItem(estado_texto)
            item_estado.setFlags(item_estado.flags() & ~ITEM_IS_EDITABLE)
            if duplicado:
                item_estado.setBackground(COLOR_FUERA)
            tbl.setItem(row, EXT_PREVIEW_COL_ESTADO, item_estado)

        self._render_preplot_ext_resumen()

    def _render_preplot_ext_resumen(self):
        n = len(self._preplot_ext_preview)
        n_dup = sum(1 for f in self._preplot_ext_preview if f.get("duplicado"))
        self.lbl_preplot_ext_resumen.setText(self.t("lbl_preplot_ext_summary", n=n, dup=n_dup))
        if hasattr(self, "btn_subir_preplot_ext"):
            self.btn_subir_preplot_ext.setEnabled(n > 0)

    def _sync_preplot_ext_desde_tabla(self):
        tbl = self.tbl_preplot_ext_preview
        n = min(tbl.rowCount(), len(self._preplot_ext_preview))
        for row in range(n):
            fila = self._preplot_ext_preview[row]
            item_nombre = tbl.item(row, EXT_PREVIEW_COL_NOMBRE)
            if item_nombre is not None:
                nuevo = item_nombre.text().strip()
                if nuevo:
                    fila["nombre"] = nuevo
            item_inc = tbl.item(row, EXT_PREVIEW_COL_INCLUDE)
            if item_inc is not None:
                fila["incluir"] = item_inc.checkState() == CHECK_STATE_CHECKED

    def limpiar_preplot_ext_preview(self):
        self._preplot_ext_preview = []
        self._llenar_tabla_preplot_ext()
        self._actualizar_capa_provisional_preplot_ext()

    @_escritura()
    def subir_preplot_externo(self):
        if not self._require_project():
            return
        if not self._preplot_ext_preview:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        self._sync_preplot_ext_desde_tabla()
        seleccionados = [f for f in self._preplot_ext_preview if f.get("incluir")]
        if not seleccionados:
            QMessageBox.information(self, self.t("info_nothing_to_upload_title"), self.t("info_nothing_to_upload_body"))
            return

        processor = self.txt_preplot_ext_processor.text().strip() or None
        dest_crs = self._working_crs()
        filas = []
        for f in seleccionados:
            if dest_crs != self.crs_wgs84:
                lon, lat = _transform_xy(f["x"], f["y"], dest_crs, self.crs_wgs84, self.project)
            else:
                lon, lat = f["x"], f["y"]
            filas.append({
                "Station_Text": f["nombre"],
                "Track": f.get("track"),
                "Bin": f.get("bin"),
                "Descriptor": f.get("descriptor", ""),
                "Local_Easting": f["x"],
                "Local_Northing": f["y"],
                "WGS84_Longitude": lon,
                "WGS84_Latitude": lat,
                "WGS84_Height": f.get("z"),
                "Local_System": dest_crs.authid(),
                "Populate_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Processor": processor,
            })
        try:
            n = db_schema.insert_rows(self.conn, "PREPLOT", db_schema.PREPLOT_COLUMNS, filas)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_preplot_save", error=e, trace=traceback.format_exc()))
            return

        subidos = {f["nombre"].strip().upper() for f in seleccionados}
        self._preplot_ext_preview = [f for f in self._preplot_ext_preview if f["nombre"].strip().upper() not in subidos]
        self._llenar_tabla_preplot_ext()
        self._actualizar_capa_provisional_preplot_ext()
        self.actualizar_conteos()
        self.log_preplot.appendPlainText(self.t("log_preplot_ext_saved", n=n))
        QMessageBox.information(self, self.t("ok_title"), self.t("msg_preplot_saved_body", n=n))

    # -- Sección: Importar datos de campo (antes "Importar .dc"; desde la
    # v2.8.0 soporta Trimble .dc e Hi-Target CSV, desde la v2.15.0 también
    # CHCNav .rw5 -- ver "note_datos_campo") -- el botón de agregar
    # archivo es, desde la v2.15.0, una única solapa desplegable
    # "Archivos de campo" (`_CAMPO_BRANDS`) en vez de un botón por marca:
    # para agregar una marca nueva (Stonex, South, etc.) ver la nota
    # junto a `_CAMPO_BRANDS`.
    def _build_tab_importar(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self._crear_banner_solo_lectura())
        self._agregar_boton_ayuda(
            v,
            [
                "note_datos_campo", "note_correccion_base", "note_manual_fields_import",
                "note_preview_query", "note_check_db_duplicates", "note_desplazamiento_preview",
                "note_importar_botones",
            ],
            "tab3_title",
        )

        # Rediseño de la interfaz (v2.63.0, pedido explícito del usuario):
        #   Columna izquierda: "1. Archivo de Origen" + acordeones PREPLOT /
        #           Editar en bloque (cerrados, con un resumen de su estado)
        #           + Corrección de base (sólo si hay base).
        #   Columna derecha: "2. Filtrado Avanzado" + "3. Formato y
        #           Finalización" (CTA "Subir").
        #   Abajo:  la tabla de previsualización, que se queda con todo el
        #           alto que liberan los bloques colapsados.
        # Las tarjetas usan `QSizePolicy.Ignored` + `QGridLayout` con el
        # mismo `setColumnStretch` (reparto 50/50 real, mismo mecanismo que
        # "Base de Datos"); `_ajustar_tamano_ventana` calcula el ancho de
        # apertura a partir de ellas.

        # -- Tarjeta 1: Archivo de Origen -------------------------------
        grp_origen = self._reg(QGroupBox(), "grp_origen_card", kind="title")
        grp_origen.setObjectName("card")
        v_origen = QVBoxLayout(grp_origen)

        # Encabezado: rótulo a la izquierda y, en la esquina superior
        # derecha de la tarjeta, el grupo de botones iconográficos
        # Agregar (+, con el menú de marcas) / Quitar (-).
        fila_archivos = QHBoxLayout()
        fila_archivos.addWidget(self._reg(QLabel(), "grp_archivos_campo"))
        fila_archivos.addStretch(1)
        btn_add_campo = QPushButton("+")
        btn_add_campo.setStyleSheet(ESTILO_BTN_ICONO)
        btn_add_campo.setMinimumWidth(50)
        self._reg(btn_add_campo, "tip_btn_add_campo", kind="tooltip")
        menu_campo = QMenu(btn_add_campo)
        for menu_key, metodo_nombre in self._CAMPO_BRANDS:
            accion = self._reg(QAction(menu_campo), menu_key)
            accion.triggered.connect(getattr(self, metodo_nombre))
            menu_campo.addAction(accion)
        btn_add_campo.setMenu(menu_campo)
        btn_quitar = QPushButton("−")
        btn_quitar.setStyleSheet(ESTILO_BTN_ICONO)
        btn_quitar.setMinimumWidth(34)
        self._reg(btn_quitar, "tip_btn_remove_dc", kind="tooltip")
        btn_quitar.clicked.connect(self.quitar_dc)
        fila_archivos.addWidget(btn_add_campo)
        fila_archivos.addWidget(btn_quitar)
        v_origen.addLayout(fila_archivos)

        self.lst_dc = ListaCompacta()
        self.lst_dc.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lst_dc.setMinimumHeight(70)
        # Con "stretch": si la fila queda más alta que esta tarjeta por
        # culpa de su pareja, el espacio de sobra lo absorbe la lista.
        v_origen.addWidget(self.lst_dc, 1)

        form = QFormLayout()
        self.spn_digitos_linea = QDoubleSpinBox()
        self.spn_digitos_linea.setDecimals(0)
        self.spn_digitos_linea.setRange(0, 10)
        self.spn_digitos_linea.setValue(4)
        self._reg(self.spn_digitos_linea, "tip_track_digits", kind="tooltip")
        self._form_row(form, "lbl_track_digits", self.spn_digitos_linea)
        # Processor: un único valor para toda la importación (el Surveyor,
        # en cambio, va por archivo -- ver `_agregar_item_campo`). Ambos
        # llenan, al subir, las columnas del mismo nombre de POSTPLOT.
        self.txt_import_processor = QLineEdit()
        self._reg(self.txt_import_processor, "tip_processor_import", kind="tooltip")
        self._form_row(form, "lbl_processor_import", self.txt_import_processor)
        v_origen.addLayout(form)

        self.chk_aplicar_geoid = self._reg(QCheckBox(), "chk_apply_geoid")
        self.chk_aplicar_geoid.setEnabled(False)
        self.chk_aplicar_geoid.setToolTip(self.t("tip_apply_geoid_disabled"))
        v_origen.addWidget(self.chk_aplicar_geoid)

        # "Previsualizar": botón secundario y discreto, debajo de los
        # parámetros técnicos (alineado a la derecha, sin ocupar todo el ancho).
        fila_prev = QHBoxLayout()
        fila_prev.addStretch(1)
        btn_previsualizar = self._reg(QPushButton(), "btn_import_dc")
        self._reg(btn_previsualizar, "tip_btn_import_dc", kind="tooltip")
        btn_previsualizar.setMinimumWidth(120)
        btn_previsualizar.clicked.connect(self.previsualizar_dc)
        fila_prev.addWidget(btn_previsualizar)
        v_origen.addLayout(fila_prev)

        # -- Acordeón: Comparación con PREPLOT (en memoria, ANTES de subir
        #    nada a POSTPLOT). Cerrado por defecto; la cabecera resume el
        #    estado (tolerancia, emparejamiento aproximado, activo o no).
        self.acc_preplot = AcordeonSeccion()
        cont_comp = QWidget()
        v_comp = QVBoxLayout(cont_comp)
        v_comp.setContentsMargins(0, 0, 0, 0)
        fila_comp = QHBoxLayout()
        fila_comp.addWidget(self._reg(QLabel(), "lbl_tolerance"))
        self.spn_tolerancia_import = QDoubleSpinBox()
        self.spn_tolerancia_import.setDecimals(3)
        self.spn_tolerancia_import.setRange(0.001, 1000.0)
        self.spn_tolerancia_import.setSingleStep(0.01)
        self.spn_tolerancia_import.setValue(5.0)  # v2.62.18: 5 m por defecto
        fila_comp.addWidget(self.spn_tolerancia_import)
        v_comp.addLayout(fila_comp)
        self.chk_aproximado_import = self._reg(QCheckBox(), "chk_approx_match")
        self.chk_aproximado_import.setChecked(False)  # v2.62.18: sin aproximado por defecto
        self._reg(self.chk_aproximado_import, "tip_approx_match", kind="tooltip")
        v_comp.addWidget(self.chk_aproximado_import)
        btn_refrescar_comp = self._reg(QPushButton(), "btn_refresh_compare_import")
        self._reg(btn_refrescar_comp, "tip_btn_refresh_compare_import", kind="tooltip")
        btn_refrescar_comp.clicked.connect(self.actualizar_comparacion_preview)
        v_comp.addWidget(btn_refrescar_comp)
        self.acc_preplot.set_contenido(cont_comp)
        # El resumen "N puntos / emparejados / dentro de tolerancia" se
        # muestra siempre (fuera del acordeón), debajo de los bloques.
        self.lbl_preview_resumen = QLabel("")
        self.lbl_preview_resumen.setWordWrap(True)

        # -- Corrección de base RTK libre -> corregida (opcional, ver la
        # nota junto a `CORR_BASE_COL_ARCHIVO`): sólo se muestra cuando
        # `_actualizar_seccion_correccion_base` (llamada al final de
        # `previsualizar_dc()`) detecta al menos una ocupación de base
        # ('is_base') entre los puntos de Hi-Target/CHCNav/DC (Trimble
        # .dc, desde la ronda de soporte a base RTK física -- ver
        # `dc_parser.BASE_CODES`) ya parseados, o al menos una referencia
        # distinta en Stonex (ver `StonexFile.unique_bases`) -- si el
        # levantamiento se hizo con RTX de Trimble o HAS de Galileo (sin
        # base propia), o el archivo simplemente no trae ninguna, la
        # sección queda oculta.
        self.grp_correccion_base = self._reg(QGroupBox(), "grp_correccion_base_title", kind="title")
        self.grp_correccion_base.setObjectName("card")
        self.grp_correccion_base.setVisible(False)
        v_corr = QVBoxLayout(self.grp_correccion_base)
        self.tbl_correccion_base = QTableWidget(0, CORR_BASE_N_COLS)
        self.tbl_correccion_base.setHorizontalHeaderLabels(self._correccion_base_headers())
        self.tbl_correccion_base.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl_correccion_base.setMinimumHeight(110)
        v_corr.addWidget(self.tbl_correccion_base, 1)
        btn_aplicar_correccion = self._reg(QPushButton(), "btn_aplicar_correccion_base")
        self._reg(btn_aplicar_correccion, "tip_btn_aplicar_correccion_base", kind="tooltip")
        btn_aplicar_correccion.clicked.connect(self._on_aplicar_correcciones_base)
        v_corr.addWidget(btn_aplicar_correccion)

        # -- Acordeón: Editar en bloque -- generalizado en v2.60.0 para
        # servir tanto a la Altura de antena (HI) como al Descriptor de
        # toda la columna (`aplicar_valor_bulk`). El combo `cb_bulk_campo`
        # decide qué widget de valor mostrar y qué columna/clave de
        # `self._import_preview` escribir. Cerrado por defecto, con el
        # campo y el valor elegidos en la cabecera.
        self.acc_bulk = AcordeonSeccion()
        cont_bulk = QWidget()
        v_bulk = QVBoxLayout(cont_bulk)
        v_bulk.setContentsMargins(0, 0, 0, 0)
        fila_bulk = QHBoxLayout()
        fila_bulk.addWidget(self._reg(QLabel(), "lbl_bulk_apply"))
        self.cb_bulk_campo = QComboBox()
        self._fill_bulk_campo_combo()
        self.cb_bulk_campo.currentIndexChanged.connect(self._actualizar_widget_valor_bulk)
        fila_bulk.addWidget(self.cb_bulk_campo)

        self.spn_hi_bulk = QDoubleSpinBox()
        self.spn_hi_bulk.setDecimals(3)
        self.spn_hi_bulk.setRange(0.0, 50.0)
        self.spn_hi_bulk.setSingleStep(0.01)
        fila_bulk.addWidget(self.spn_hi_bulk)

        self.txt_descriptor_bulk = QLineEdit()
        self._reg(self.txt_descriptor_bulk, "ph_bulk_descriptor", kind="placeholder")
        self.txt_descriptor_bulk.setVisible(False)
        fila_bulk.addWidget(self.txt_descriptor_bulk)
        v_bulk.addLayout(fila_bulk)

        btn_bulk_apply = self._reg(QPushButton(), "btn_hi_bulk_apply")
        self._reg(btn_bulk_apply, "tip_btn_hi_bulk_apply", kind="tooltip")
        btn_bulk_apply.clicked.connect(self.aplicar_valor_bulk)
        v_bulk.addWidget(btn_bulk_apply)
        self.acc_bulk.set_contenido(cont_bulk)

        # Los resúmenes de las cabeceras se actualizan solos.
        self.spn_tolerancia_import.valueChanged.connect(lambda _v: self._actualizar_resumen_acordeones())
        self.chk_aproximado_import.toggled.connect(lambda _c: self._actualizar_resumen_acordeones())
        self.cb_bulk_campo.currentIndexChanged.connect(lambda _i: self._actualizar_resumen_acordeones())
        self.spn_hi_bulk.valueChanged.connect(lambda _v: self._actualizar_resumen_acordeones())
        self.txt_descriptor_bulk.textChanged.connect(lambda _t: self._actualizar_resumen_acordeones())
        self._actualizar_resumen_acordeones()

        # -- Tarjeta 2: Filtrado Avanzado -------------------------------
        # Consultar la previsualización antes de subir nada (pedido
        # explícito del usuario, con las mismas herramientas -- consulta,
        # capa de mapa temporal -- de "Base de Datos", pero acá NUNCA se
        # reordenan las filas de `tbl_import_preview`: el resto de este
        # módulo asume que la fila N de la tabla es siempre
        # `self._import_preview[N]`. La consulta se resuelve con SQL de
        # verdad en una tabla SQLite en memoria -- ver
        # `_construir_conexion_preview_sqlite`.
        grp_filtrado = self._reg(QGroupBox(), "grp_filtrado_card", kind="title")
        grp_filtrado.setObjectName("card")
        v_qp = QVBoxLayout(grp_filtrado)

        # Arriba: filtro predeterminado + guardar. Elegir un preset sólo
        # LLENA la condición; el usuario sigue apretando "Filtrar".
        fila_preset = QHBoxLayout()
        fila_preset.addWidget(self._reg(QLabel(), "lbl_preview_filter_preset"))
        self.cb_preview_filter_preset = QComboBox()
        self._fill_preview_filter_preset_combo()
        self.cb_preview_filter_preset.currentIndexChanged.connect(self._aplicar_preset_filtro_preview)
        fila_preset.addWidget(self.cb_preview_filter_preset, 1)
        btn_guardar_filtro = self._reg(QPushButton(), "btn_save_preview_filter")
        self._reg(btn_guardar_filtro, "tip_btn_save_preview_filter", kind="tooltip")
        btn_guardar_filtro.clicked.connect(self.guardar_filtro_preview_actual)
        fila_preset.addWidget(btn_guardar_filtro)
        v_qp.addLayout(fila_preset)

        # Asistente visual (sin escribir SQL), en UNA sola fila de
        # entradas: Columna | Condición | Valor | Unir con | (+). Agrega
        # la condición a la consulta -- ver `_agregar_condicion_filtro_preview`
        # y `_construir_condicion_wizard`.
        grid_wizard = QGridLayout()
        grid_wizard.setHorizontalSpacing(6)
        grid_wizard.setVerticalSpacing(1)
        grid_wizard.setColumnStretch(0, 3)
        grid_wizard.setColumnStretch(1, 3)
        grid_wizard.setColumnStretch(2, 3)
        for col, key in enumerate(("lbl_filtro_wizard_columna", "lbl_filtro_wizard_operador", "ph_filtro_wizard_valor_lbl", "lbl_filtro_wizard_conector")):
            lbl = self._reg(QLabel(), key)
            lbl.setStyleSheet(ESTILO_ROTULO_TENUE)
            grid_wizard.addWidget(lbl, 0, col)
        self.cb_filtro_wizard_columna = QComboBox()
        grid_wizard.addWidget(self.cb_filtro_wizard_columna, 1, 0)
        self.cb_filtro_wizard_operador = QComboBox()
        grid_wizard.addWidget(self.cb_filtro_wizard_operador, 1, 1)
        self.txt_filtro_wizard_valor = QLineEdit()
        self._reg(self.txt_filtro_wizard_valor, "ph_filtro_wizard_valor", kind="placeholder")
        grid_wizard.addWidget(self.txt_filtro_wizard_valor, 1, 2)
        self.cb_filtro_wizard_conector = QComboBox()
        grid_wizard.addWidget(self.cb_filtro_wizard_conector, 1, 3)
        btn_agregar_condicion = QPushButton("+")
        btn_agregar_condicion.setStyleSheet(ESTILO_BTN_ICONO)
        btn_agregar_condicion.setFixedWidth(34)
        self._reg(btn_agregar_condicion, "tip_btn_agregar_condicion_filtro", kind="tooltip")
        btn_agregar_condicion.clicked.connect(self._agregar_condicion_filtro_preview)
        grid_wizard.addWidget(btn_agregar_condicion, 1, 4)
        self._fill_filtro_wizard_combos()
        v_qp.addLayout(grid_wizard)

        # Condición actual en lenguaje llano + "Modo Desarrollador (SQL)":
        # el cuadro de texto con la condición SQL cruda queda OCULTO por
        # defecto detrás de un botón desplegable para no abrumar.
        self.lbl_filtro_actual = QLabel("")
        self.lbl_filtro_actual.setWordWrap(True)
        self.lbl_filtro_actual.setStyleSheet(ESTILO_ROTULO_TENUE)
        v_qp.addWidget(self.lbl_filtro_actual)

        self.btn_sql_dev = QPushButton()
        self.btn_sql_dev.setCheckable(True)
        self.btn_sql_dev.setChecked(False)
        self.btn_sql_dev.setFlat(True)
        self.btn_sql_dev.setStyleSheet(ESTILO_BTN_ENLACE)
        self._reg(self.btn_sql_dev, "tip_btn_sql_dev", kind="tooltip")
        self.txt_filtro_preview = QLineEdit()
        self._reg(self.txt_filtro_preview, "tip_preview_filter_placeholder", kind="placeholder")
        self.txt_filtro_preview.setVisible(False)
        self.btn_sql_dev.toggled.connect(self.txt_filtro_preview.setVisible)
        self.btn_sql_dev.toggled.connect(lambda _c: self._actualizar_texto_boton_sql_dev())
        self.txt_filtro_preview.textChanged.connect(lambda _t: self._actualizar_lbl_filtro_actual())
        self._actualizar_texto_boton_sql_dev()
        self._actualizar_lbl_filtro_actual()
        v_qp.addWidget(self.btn_sql_dev)
        v_qp.addWidget(self.txt_filtro_preview)

        # Barra de acciones compacta: Filtrar / Limpiar / Mapa / Marcar /
        # Desmarcar, con ícono (glifo) + texto corto.
        fila_acciones = QHBoxLayout()
        fila_acciones.setSpacing(4)
        for key_texto, key_tip, handler in (
            ("tb_filter", "tip_btn_apply_preview_filter", self._ejecutar_filtro_preview),
            ("tb_clear", "tip_btn_clear_preview_filter", self._quitar_filtro_preview),
            ("tb_map", "tip_btn_show_filtered_on_map", self._mostrar_filtro_preview_en_mapa),
            ("tb_mark", "tip_btn_mark_include_filtered", lambda: self._marcar_incluir_filtrados(True)),
            ("tb_unmark", "tip_btn_unmark_include_filtered", lambda: self._marcar_incluir_filtrados(False)),
        ):
            tb = QToolButton()
            tb.setStyleSheet(ESTILO_BTN_BARRA)
            self._reg(tb, key_texto)
            self._reg(tb, key_tip, kind="tooltip")
            tb.clicked.connect(lambda _checked=False, h=handler: h())
            fila_acciones.addWidget(tb)
        fila_acciones.addStretch(1)
        v_qp.addLayout(fila_acciones)

        self.lbl_filtro_preview_resumen = QLabel("")
        self.lbl_filtro_preview_resumen.setWordWrap(True)
        v_qp.addWidget(self.lbl_filtro_preview_resumen)
        v_qp.addStretch(1)

        # -- Tarjeta 3: Formato y Finalización --------------------------
        grp_finalizar = self._reg(QGroupBox(), "grp_finalizar_card", kind="title")
        grp_finalizar.setObjectName("card")
        v_fin = QVBoxLayout(grp_finalizar)

        # Arriba: formato de exportación + botón Exportar, en una fila.
        fila_export_preview = QHBoxLayout()
        fila_export_preview.addWidget(self._reg(QLabel(), "lbl_export_format"))
        self.cb_export_preview_formato = QComboBox()
        self._fill_export_preview_format_combo()
        fila_export_preview.addWidget(self.cb_export_preview_formato, 1)
        btn_exportar_preview = self._reg(QPushButton(), "btn_export_preview")
        self._reg(btn_exportar_preview, "tip_btn_export_preview", kind="tooltip")
        btn_exportar_preview.clicked.connect(self._exportar_preview_actual)
        fila_export_preview.addWidget(btn_exportar_preview)
        v_fin.addLayout(fila_export_preview)

        # Interruptor moderno (Toggle Switch) en vez de casilla.
        self.chk_crear_capa_import = self._reg(ToggleSwitch(), "chk_create_layer")
        self.chk_crear_capa_import.setChecked(True)
        v_fin.addWidget(self.chk_crear_capa_import)

        # Acciones secundarias: verificar duplicados y registro. El
        # "Registro" queda oculto por defecto (`self.log_importar` sigue
        # recibiendo texto -- `appendPlainText` -- esté visible o no, así
        # que nada de lo que escribe el flujo de importación se pierde).
        fila_secundaria = QHBoxLayout()
        btn_verificar_duplicados = self._reg(QPushButton(), "btn_check_db_duplicates")
        self._reg(btn_verificar_duplicados, "tip_btn_check_db_duplicates", kind="tooltip")
        btn_verificar_duplicados.clicked.connect(self.verificar_duplicados_bd)
        fila_secundaria.addWidget(btn_verificar_duplicados)
        self.btn_toggle_log_importar = QPushButton()
        self.btn_toggle_log_importar.setCheckable(True)
        self.btn_toggle_log_importar.setChecked(False)
        fila_secundaria.addWidget(self.btn_toggle_log_importar)
        v_fin.addLayout(fila_secundaria)

        self.log_importar = QPlainTextEdit()
        self.log_importar.setReadOnly(True)
        self.log_importar.setVisible(False)
        self.log_importar.setMinimumHeight(90)
        self.btn_toggle_log_importar.toggled.connect(self.log_importar.setVisible)
        self.btn_toggle_log_importar.toggled.connect(lambda _checked: self._actualizar_texto_boton_log_importar())
        self._actualizar_texto_boton_log_importar()
        v_fin.addWidget(self.log_importar)

        v_fin.addStretch(1)

        # "Subir": acción principal (CTA) de la pantalla, de ancho
        # completo. Texto/color/tooltip los maneja `_actualizar_boton_subir`
        # (verde "Subir" -> rojo "Subir/Retirar" tras una subida), por eso
        # no se registra con `_reg`: `retranslate_ui` lo vuelve a aplicar.
        self.btn_subir_dc = QPushButton()
        self.btn_subir_dc.setMinimumHeight(40)
        self.btn_subir_dc.setCursor(_valor_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.btn_subir_dc.clicked.connect(self._on_click_subir)
        v_fin.addWidget(self.btn_subir_dc)
        self._actualizar_boton_subir()

        # -- Armado -----------------------------------------------------
        for g in (grp_origen, grp_filtrado, grp_finalizar, self.grp_correccion_base):
            g.setSizePolicy(SIZE_POLICY_IGNORED, g.sizePolicy().verticalPolicy())
        for a in (self.acc_preplot, self.acc_bulk):
            a.setSizePolicy(SIZE_POLICY_IGNORED, a.sizePolicy().verticalPolicy())

        # Dos columnas de igual ancho. Izquierda: "1. Archivo de Origen"
        # (la lista de archivos absorbe el alto sobrante) + acordeones
        # PREPLOT / Editar en bloque + resumen + Corrección de base (si
        # hay base). Derecha: "2. Filtrado Avanzado" (absorbe el alto
        # sobrante) + "3. Formato y Finalización" con el CTA "Subir"
        # abajo, pegado a la tabla. Así las dos columnas quedan parejas
        # sin huecos vacíos.
        col_izq = QVBoxLayout()
        col_izq.setSpacing(6)
        col_izq.addWidget(grp_origen, 1)
        col_izq.addWidget(self.acc_preplot)
        col_izq.addWidget(self.acc_bulk)
        col_izq.addWidget(self.lbl_preview_resumen)
        col_izq.addWidget(self.grp_correccion_base)
        col_der = QVBoxLayout()
        col_der.setSpacing(6)
        col_der.addWidget(grp_filtrado, 1)
        col_der.addWidget(grp_finalizar)
        grid_tarjetas = QGridLayout()
        grid_tarjetas.setColumnStretch(0, 1)
        grid_tarjetas.setColumnStretch(1, 1)
        grid_tarjetas.setHorizontalSpacing(10)
        grid_tarjetas.addLayout(col_izq, 0, 0)
        grid_tarjetas.addLayout(col_der, 0, 1)
        v.addLayout(grid_tarjetas)

        # Aspecto de "tarjeta" (borde fino redondeado, con los colores de
        # la paleta del tema para que sirva en claro y en oscuro).
        w.setStyleSheet(ESTILO_TARJETAS)

        # -- Previsualización: ocupa todo el ancho y, con los bloques de
        # arriba colapsados, todo el alto que quede libre (stretch 1).
        # Las columnas "Incluir" y "Nombre" quedan FIJAS a la izquierda al
        # desplazarse en horizontal (pedido explícito del usuario, ver
        # `tabla_fija.py`) y "Comentario" se muestra justo al lado de
        # "Descriptor" -- sólo cambia el ORDEN VISUAL (`moveSection`): los
        # índices lógicos `PREVIEW_COL_*` no cambian, así que ninguna otra
        # parte del código (edición, exportación, consultas) se ve afectada.
        self.tbl_import_preview = TablaColumnasFijas(
            0, PREVIEW_N_COLS, fijas=(PREVIEW_COL_INCLUDE, PREVIEW_COL_NOMBRE),
        )
        self.tbl_import_preview.setMinimumHeight(340)
        self.tbl_import_preview.setHorizontalHeaderLabels(self._import_preview_headers())
        self.tbl_import_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        _hdr_preview = self.tbl_import_preview.horizontalHeader()
        _hdr_preview.moveSection(
            _hdr_preview.visualIndex(PREVIEW_COL_COMENTARIO),
            _hdr_preview.visualIndex(PREVIEW_COL_DESCRIPTOR) + 1,
        )
        # Recalcula "Alt. WGS84 (m)"/"Elevación ortométrica" en vivo al
        # editar la celda "Altura de antena" -- ver
        # `_on_preview_item_changed`, pedido explícito del usuario.
        self.tbl_import_preview.itemChanged.connect(self._on_preview_item_changed)
        v.addWidget(self.tbl_import_preview, 1)

        return w

    # -- Rediseño v2.63.0: textos dinámicos de acordeones / botones ------
    def _actualizar_resumen_acordeones(self):
        """Refresca los títulos + resumen de estado de los acordeones
        PREPLOT y Editar en bloque (cerrados, esa línea es lo único que
        se ve de ellos)."""
        if hasattr(self, "acc_preplot") and hasattr(self, "chk_aproximado_import"):
            tol = self.spn_tolerancia_import.value()
            aprox = self.t("acc_yes") if self.chk_aproximado_import.isChecked() else self.t("acc_no")
            resumen_prev = self._last_import_preview_summary
            if resumen_prev is None:
                estado = self.t("acc_state_waiting")
            elif resumen_prev[3]:
                estado = self.t("acc_state_active")
            else:
                estado = self.t("acc_state_no_preplot")
            texto = self.t("acc_preplot_summary", tol=f"{tol:.3f}", aprox=aprox, estado=estado)
            self.acc_preplot.set_textos(self.t("acc_preplot_title"), texto)
        if hasattr(self, "acc_bulk") and hasattr(self, "txt_descriptor_bulk"):
            if self.cb_bulk_campo.currentData() == "descriptor":
                valor = self.txt_descriptor_bulk.text().strip() or self.t("acc_empty")
                campo = self.t("opt_bulk_field_descriptor")
            else:
                valor = f"{self.spn_hi_bulk.value():.3f} m"
                campo = self.t("opt_bulk_field_hi")
            self.acc_bulk.set_textos(self.t("acc_bulk_title"), f"{campo} = {valor}")

    def _actualizar_texto_boton_sql_dev(self):
        key = "btn_sql_dev_hide" if self.btn_sql_dev.isChecked() else "btn_sql_dev_show"
        self.btn_sql_dev.setText(self.t(key))

    def _actualizar_lbl_filtro_actual(self):
        if not hasattr(self, "lbl_filtro_actual"):
            return
        condicion = self.txt_filtro_preview.text().strip()
        self.lbl_filtro_actual.setText(self.t("lbl_filtro_actual", c=condicion or self.t("acc_none")))
        self.lbl_filtro_actual.setToolTip(condicion)

    def _actualizar_texto_boton_log_importar(self):
        key = "btn_log_hide" if self.btn_toggle_log_importar.isChecked() else "btn_log_show"
        self.btn_toggle_log_importar.setText(self.t(key))

    def agregar_dc(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_dc_title"), "", self.t("filter_dc"))
        if not paths:
            return
        for p in paths:
            try:
                dc = parse_dc_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.dc_files.append(dc)
            self._campo_file_refs.append(("DC", dc.path))
            # Desde la ronda de soporte a base RTK física: si el archivo
            # trae una única base física distinta ('66SI'/'66FD', ver
            # `dc_parser.BASE_CODES`), se informa su nombre aquí mismo
            # -- es la confirmación más directa de que la sección
            # "Corrección de base RTK" va a quedar disponible para este
            # archivo al previsualizar.
            base_names = dc.unique_base_names()
            resumen = self.t(
                "log_dc_summary", name=os.path.basename(p), n=dc.n_points,
                ki=len(dc.points_by_type("KI")), so=len(dc.points_by_type("SO")),
            )
            if len(base_names) == 1:
                resumen += " " + self.t("log_dc_base_detectada", base=base_names[0])
            elif len(base_names) > 1:
                resumen += " " + self.t("log_dc_bases_multiples", n=len(base_names))
            self._agregar_item_campo(resumen)
            if dc.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(dc.warnings)))

    def agregar_hitarget(self):
        # Desde la v2.23.0 también acepta el .raw binario propio de
        # Hi-Target (el log interno del receptor/controlador), además
        # del CSV que ya soportaba desde la v2.8.0 -- ver el docstring
        # de `hitarget_raw_parser.py` para el formato deducido y su
        # verificación. Se distingue por extensión: ambos formatos
        # producen el mismo `HiTargetFile`/`HiTargetPoint`, así que el
        # resto de esta ventana (previsualización, comparación, subida)
        # no necesita saber de cuál vino cada archivo.
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_hitarget_title"), "", self.t("filter_hitarget_csv"))
        if not paths:
            return
        for p in paths:
            try:
                if p.lower().endswith(".raw"):
                    hf = hitarget_raw_parser.parse_hitarget_raw(p)
                else:
                    hf = hitarget_parser.parse_hitarget_csv(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.hitarget_files.append(hf)
            self._campo_file_refs.append(("HITARGET", hf.path))
            n_base = sum(1 for pt in hf.points if pt.is_base)
            resumen = self.t(
                "log_hitarget_summary", name=os.path.basename(p), n=hf.n_points, base=n_base,
            )
            self._agregar_item_campo(resumen)
            if hf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(hf.warnings)))
            # Aviso explícito en el log (no sólo en la nota estática de
            # arriba de la tabla, que se pasa fácil por alto): un .raw de
            # Hi-Target nunca trae la altura de antena -- ver el
            # docstring de `hitarget_raw_parser.py`. Se avisa aquí mismo,
            # al momento de cargar el archivo, para que quede claro que
            # no es un error del plugin sino una limitación real del
            # formato -- toca completarla a mano o con "Aplicar a todos".
            if p.lower().endswith(".raw"):
                self.log_importar.appendPlainText(self.t("log_hitarget_raw_no_ant_height"))

    def agregar_chcnav(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_chcnav_title"), "", self.t("filter_chcnav_rw5"))
        if not paths:
            return
        for p in paths:
            try:
                cf = chcnav_parser.parse_rw5_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.chcnav_files.append(cf)
            self._campo_file_refs.append(("CHCNAV", cf.path))
            n_con_calidad = sum(1 for pt in cf.points if pt.status is not None)
            n_base = sum(1 for pt in cf.points if pt.is_base)
            resumen = self.t(
                "log_chcnav_summary", name=os.path.basename(p), n=cf.n_points,
                con_calidad=n_con_calidad, base=n_base,
            )
            self._agregar_item_campo(resumen)
            if cf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(cf.warnings)))

    def agregar_surpad(self):
        # SurPad (app de campo usada con equipos de varias marcas, no
        # un fabricante propio de receptor) exporta dos formatos que
        # `surpad_parser.parse_surpad_file` distingue por contenido:
        #  * .rw5 -- misma familia que LandStar/CHCNav, pero con LA/LN en
        #    DD.MMSSssss (NO decimales, ver chcnav_parser.py: dialecto
        #    "surpad", corregido en la v2.62.8 tras verificarlo contra la
        #    grilla del propio archivo);
        #  * .raw -- grados decimales completos, la fuente más fiable.
        # Ambos devuelven `chcnav_parser.ChcnavFile`/`ChcnavPoint`, así que
        # se guardan en `self.surpad_files` (ítem "SurPad" propio en la
        # lista) y el resto del código (preview, subida a POSTPLOT, tipo-
        # code, modo de levantamiento, corrección de base) los trata igual
        # que a CHCNav por duck-typing.
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_surpad_title"), "", self.t("filter_surpad_rw5"))
        if not paths:
            return
        for p in paths:
            try:
                cf = surpad_parser.parse_surpad_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.surpad_files.append(cf)
            self._campo_file_refs.append(("SURPAD", cf.path))
            n_con_calidad = sum(1 for pt in cf.points if pt.status is not None)
            n_base = sum(1 for pt in cf.points if pt.is_base)
            resumen = self.t(
                "log_surpad_summary", name=os.path.basename(p), n=cf.n_points,
                con_calidad=n_con_calidad, base=n_base,
            )
            self._agregar_item_campo(resumen)
            if cf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(cf.warnings)))
                # En SurPad el detalle importa (puntos con posible
                # inclinación, bases renombradas): se muestra cada aviso.
                for aviso in cf.warnings:
                    self.log_importar.appendPlainText(f"    - {aviso}")

    def agregar_sourcelink(self):
        # CSV de SourceLink (control de vibradores sísmicos): una fila por
        # disparo con la posición GNSS del vibro. A diferencia del resto de
        # formatos, trae el número de vibrador por fila ("Unit ID"), que se
        # sube como `Surveyor` de cada punto -- por eso el campo "Surveyor"
        # junto al archivo queda desactivado (ver `_agregar_item_campo`).
        # Ver el análisis completo del formato en `sourcelink_parser.py`.
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_sourcelink_title"), "", self.t("filter_sourcelink_csv"))
        if not paths:
            return
        for p in paths:
            try:
                sf = sourcelink_parser.parse_sourcelink_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.sourcelink_files.append(sf)
            self._campo_file_refs.append(("SOURCELINK", sf.path))
            resumen = self.t(
                "log_sourcelink_summary", name=os.path.basename(p), n=sf.n_points,
                unidades=len(sf.units), anulados=sf.n_void,
            )
            self._agregar_item_campo(resumen)
            if sf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(sf.warnings)))
                for aviso in sf.warnings:
                    self.log_importar.appendPlainText(f"    - {aviso}")

    def agregar_inova(self):
        # Libro Excel (.xls) de Inova (vibradores sísmicos): una fila COG
        # (centro de grupo de los vibros) por VP. Es el algoritmo de la
        # macro `ExtraerCOG_GPSeismic` del usuario, hecho en Python -- ver
        # `inova_parser.py`. Como SourceLink, trae el/los vibro(s) de cada
        # punto y se suben como `Surveyor` (el campo junto al archivo no
        # aplica). La altura de antena se resta con la columna HI.
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_inova_title"), "", self.t("filter_inova_xls"))
        if not paths:
            return
        for p in paths:
            try:
                inf = inova_parser.parse_inova_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.inova_files.append(inf)
            self._campo_file_refs.append(("INOVA", inf.path))
            resumen = self.t(
                "log_inova_summary", name=os.path.basename(p), n=inf.n_points,
                unidades=len(inf.units), fail=inf.n_fail,
            )
            self._agregar_item_campo(resumen)
            if inf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(inf.warnings)))
                for aviso in inf.warnings:
                    self.log_importar.appendPlainText(f"    - {aviso}")

    def agregar_stonex(self):
        # El archivo de Stonex es una base de datos SQLite. Hasta la
        # v2.27.0 se aceptaba cualquier extensión y se confirmaba el
        # formato sólo por su contenido (el archivo real de referencia
        # había llegado con la extensión cambiada). Desde la v2.28.0, a
        # pedido explícito del usuario, sólo se reconocen archivos con
        # extensión ".PD": el filtro del diálogo ya limita la selección
        # a *.pd, y se repite el chequeo acá por si el sistema operativo
        # deja escribir un nombre de archivo a mano sin pasar por ese
        # filtro. El chequeo de contenido
        # (`stonex_parser.looks_like_stonex_db`) se mantiene además,
        # como segunda validación (protege contra un archivo .PD que no
        # sea realmente de Stonex).
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dlg_add_stonex_title"), "", self.t("filter_stonex_db"))
        if not paths:
            return
        for p in paths:
            if not p.lower().endswith(".pd"):
                QMessageBox.warning(self, self.t("warn_read_file_title"), self.t("err_stonex_wrong_extension", name=os.path.basename(p)))
                continue
            if not stonex_parser.looks_like_stonex_db(p):
                QMessageBox.warning(self, self.t("warn_read_file_title"), self.t("err_stonex_not_recognized", name=os.path.basename(p)))
                continue
            try:
                sf = stonex_parser.parse_stonex_file(p)
            except Exception as e:
                QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(p)}:\n{e}")
                continue
            self.stonex_files.append(sf)
            self._campo_file_refs.append(("STONEX", sf.path))
            resumen = self.t(
                "log_stonex_summary", name=os.path.basename(p), n=sf.n_points,
            )
            self._agregar_item_campo(resumen)
            if sf.warnings:
                self.log_importar.appendPlainText(self.t("log_dc_warnings", name=os.path.basename(p), n=len(sf.warnings)))

    def _surveyor_de_fila(self, fila):
        """Surveyor que se subirá para una fila de la previsualización: el
        propio de la fila (Unit ID del vibro, SourceLink) o, si no trae, el
        escrito junto a su archivo."""
        return (fila.get("surveyor") or self._surveyor_por_archivo.get((fila.get("origen"), fila.get("archivo_path")), "")).strip()

    def _refrescar_columna_surveyor(self):
        """Actualiza la columna Surveyor de la previsualización (p.ej. al
        escribir el Surveyor de un archivo) sin reconstruir la tabla."""
        tbl = getattr(self, "tbl_import_preview", None)
        if tbl is None or tbl.columnCount() <= PREVIEW_COL_SURVEYOR:
            return
        for row, fila in enumerate(self._import_preview):
            if row < tbl.rowCount():
                self._set_preview_readonly_cell(row, PREVIEW_COL_SURVEYOR, self._surveyor_de_fila(fila) or "-")

    def _agregar_item_campo(self, resumen):
        """Agrega a `lst_dc` la fila de un archivo de campo recién cargado
        (el último de `self._campo_file_refs`): el resumen del archivo a la
        izquierda y, a su derecha, un campo de texto "Surveyor" propio de
        ese archivo -- si se cargan varios archivos de topógrafos distintos,
        al subir a POSTPLOT cada punto queda con el topógrafo de SU archivo.
        La fila sigue siendo un `QListWidgetItem` normal (selección y
        "Quitar" funcionan igual que antes)."""
        clave = self._campo_file_refs[-1] if self._campo_file_refs else None
        item = QListWidgetItem()
        self.lst_dc.addItem(item)
        fila = QWidget()
        h = QHBoxLayout(fila)
        h.setContentsMargins(6, 2, 6, 2)
        lbl = QLabel(resumen)
        lbl.setToolTip(resumen)
        # Ignored: el resumen (largo) se recorta en vez de empujar el campo
        # Surveyor fuera de la vista; el texto completo queda en el tooltip.
        lbl.setSizePolicy(SIZE_POLICY_IGNORED, lbl.sizePolicy().verticalPolicy())
        h.addWidget(lbl, 1)
        h.addWidget(QLabel("Surveyor:"))
        edt = QLineEdit()
        edt.setPlaceholderText("Surveyor")
        edt.setMinimumWidth(130)
        edt.setMaximumWidth(220)
        edt.setToolTip(self.t("tip_surveyor_archivo"))
        if clave is not None and clave[0] in ("SOURCELINK", "INOVA"):
            # SourceLink (Unit ID) e Inova (vibros del VP) traen el/los
            # vibrador(es) en cada fila y se suben como Surveyor de cada
            # punto: el campo no aplica.
            edt.setEnabled(False)
            edt.setPlaceholderText(self.t("ph_surveyor_unit_id"))
            edt.setToolTip(self.t("tip_surveyor_sourcelink" if clave[0] == "SOURCELINK" else "tip_surveyor_inova"))
        elif clave is not None:
            edt.setText(self._surveyor_por_archivo.get(clave, ""))
            edt.textChanged.connect(
                lambda texto, k=clave: self._surveyor_por_archivo.__setitem__(k, texto.strip())
            )
            edt.textChanged.connect(lambda _t: self._refrescar_columna_surveyor())
        h.addWidget(edt)
        item.setSizeHint(fila.sizeHint())
        self.lst_dc.setItemWidget(item, fila)

    def quitar_dc(self):
        removidos = []  # [(origen, path), ...] realmente quitados en esta llamada
        for item in sorted(self.lst_dc.selectedItems(), key=self.lst_dc.row, reverse=True):
            row = self.lst_dc.row(item)
            self.lst_dc.takeItem(row)
            if row >= len(self._campo_file_refs):
                continue
            origen, path = self._campo_file_refs.pop(row)
            if (origen, path) not in self._campo_file_refs:
                self._surveyor_por_archivo.pop((origen, path), None)
            if origen == "DC":
                self.dc_files = [f for f in self.dc_files if f.path != path]
            elif origen == "HITARGET":
                self.hitarget_files = [f for f in self.hitarget_files if f.path != path]
            elif origen == "CHCNAV":
                self.chcnav_files = [f for f in self.chcnav_files if f.path != path]
            elif origen == "STONEX":
                self.stonex_files = [f for f in self.stonex_files if f.path != path]
            elif origen == "SURPAD":
                self.surpad_files = [f for f in self.surpad_files if f.path != path]
            elif origen == "SOURCELINK":
                self.sourcelink_files = [f for f in self.sourcelink_files if f.path != path]
            elif origen == "INOVA":
                self.inova_files = [f for f in self.inova_files if f.path != path]
            removidos.append((origen, path))

        if not removidos:
            return

        # A pedido explícito del usuario (ronda 2.28.0): quitar uno o
        # varios archivos de campo ya cargados también borra la
        # previsualización, la capa provisional del mapa y la sección
        # "Corrección de base RTK" -- antes de este cambio, quitar un
        # archivo dejaba esos tres elementos mostrando datos del archivo
        # ya quitado (incluida su fila de base RTK, si tenía) hasta que
        # el usuario volviera a presionar "Previsualizar" a mano. Primero
        # se descarta cualquier corrección de base ya guardada
        # (`self._base_corrections`) para una base de un archivo que se
        # acaba de quitar -- si el mismo archivo se vuelve a agregar más
        # adelante, hay que volver a escribir/cargar su corrección --, y
        # después se limpia todo, sin volver a parsear nada (el usuario
        # decide cuándo previsualizar de nuevo lo que sigue cargado).
        for origen, path in removidos:
            for clave in [k for k in self._base_corrections if k[0] == origen and k[1] == path]:
                del self._base_corrections[clave]
        self._limpiar_previsualizacion_campo()

    def _limpiar_previsualizacion_campo(self):
        """Limpia por completo la previsualización de "Importar datos de
        campo" -- `self._import_preview`, `tbl_import_preview`, la capa
        provisional del mapa (`_actualizar_capa_provisional_preview`) y
        la sección "Corrección de base RTK"
        (`_actualizar_seccion_correccion_base`) -- sin volver a parsear
        ni previsualizar nada. Usada desde `quitar_dc()` (ronda 2.28.0):
        después de quitar uno o más archivos, el usuario tiene que
        volver a presionar "Previsualizar" para ver de nuevo lo que
        sigue cargado, en vez de dejar en pantalla datos de un archivo
        que ya no está."""
        self._import_preview = []
        self._preview_filtro_ids = None
        if hasattr(self, "tbl_import_preview"):
            self.tbl_import_preview.setRowCount(0)
        if hasattr(self, "lbl_filtro_preview_resumen"):
            self.lbl_filtro_preview_resumen.setText("")
        self._actualizar_capa_provisional_preview()
        self._actualizar_capas_desplazamiento_preview()
        self._actualizar_seccion_correccion_base()

    # -- Previsualización / edición / comparación antes de subir a BD ----
    def previsualizar_dc(self, mostrar_aviso: bool = True):
        """Parsea `self.dc_files`, `self.hitarget_files` y
        `self.chcnav_files` (sin escribir nada todavía en POSTPLOT),
        descarta los puntos que no tengan un levantamiento GNSS real de
        campo (sin satélites/PDOP -- ver más
        abajo), y llena `tbl_import_preview` para que el usuario pueda
        revisar, corregir nombre/altura de antena/comentario, comparar
        contra PREPLOT, y decidir con la casilla "Incluir" qué subir.
        También crea/actualiza una capa provisional en el plano de QGIS
        con esos mismos puntos (ver `_actualizar_capa_provisional_preview`).

        `mostrar_aviso` (agregado en la v2.25.0): si hay al menos un
        punto en la previsualización resultante, muestra un QMessageBox
        informando a qué CRS de trabajo se proyectaron los puntos (para
        las nuevas columnas de coordenadas planas) y si se les aplicó el
        geoide del proyecto (para la elevación ortométrica) -- pedido
        explícito del usuario. Se pasa `False` desde la re-previsualización
        interna que dispara `_on_aplicar_correcciones_base` (aplicar una
        corrección de base) para no repetir el mismo aviso dos veces
        seguidas por una acción que el usuario no reconocería como "subir
        un archivo de campo nuevo"."""
        if not self._require_project():
            return
        if not self.dc_files and not self.hitarget_files and not self.chcnav_files and not self.stonex_files and not self.surpad_files and not self.sourcelink_files and not self.inova_files:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return

        # Conserva ediciones (nombre corregido, HI, comentario, incluir,
        # ya-subido) de puntos que sigan estando si se vuelve a
        # previsualizar (p.ej. tras agregar un archivo .dc adicional),
        # en vez de perderlas. La identidad de un punto para este cruce
        # es (origen, ruta del archivo, número de línea dentro de él) --
        # NUNCA su posición (dc_idx/point_idx) en `self.dc_files`/
        # `self.hitarget_files`, que cambia si se quita o agrega un
        # archivo y volvería a emparejar por accidente un punto nuevo
        # con el estado ("ya subido", ediciones) de un punto viejo no
        # relacionado que ocupara antes esa misma posición.
        self._sync_preview_edits_desde_tabla()
        ediciones_previas = {
            (f["origen"], f["archivo_path"], f["line_no"]): f
            for f in self._import_preview
        }
        # Guarda lo que el usuario haya escrito en la tabla de corrección
        # de base (coordenada corregida todavía no aplicada con el botón
        # "Aplicar correcciones") para no perderlo si esta previsualización
        # se dispara por otra razón (p.ej. agregar otro archivo) -- ver
        # `_actualizar_seccion_correccion_base`.
        correccion_borrador = self._leer_borrador_correccion_base_desde_tabla()

        line_digits = int(self.spn_digitos_linea.value())
        aplicar_geoide = self.chk_aplicar_geoid.isChecked() and (self.geoid_layer is not None or self.geoid_ggf is not None)
        geoid_file_name = os.path.basename(self.geoid_path) if (aplicar_geoide and self.geoid_path) else None

        filas = []
        for dc_idx, dc in enumerate(self.dc_files):
            # Desde la ronda de soporte a base RTK física en Trimble .dc
            # (ver `dc_parser.BASE_CODES`): Trimble .dc no trae, a
            # diferencia de Hi-Target/CHCNav, ningún campo que asocie
            # explícitamente un punto rover con el nombre de la base que
            # usó -- así que, desde la ronda de soporte a MÚLTIPLES bases
            # por archivo, `dc_parser.parse_dc_text` asocia cada punto por
            # ORDEN DE APARICIÓN (la ocupación de base más reciente vista
            # antes que él en el archivo, "vigente hasta que otra la
            # cambie" -- ver `DCPoint.base_station_name`/`base_baseline_m`),
            # exactamente el mismo mecanismo ya verificado para el 'BP' de
            # CHCNav (v2.24.0). El resultado ya viene calculado en cada
            # punto -- este loop sólo lo copia a la fila, igual que ya
            # hacen los loops de HITARGET/CHCNAV más abajo.
            #
            # Una misma base física reocupada ('66FD') puede aparecer
            # varias veces en el archivo con nombre y coordenada
            # IDÉNTICOS (ver `dc_parser.BASE_CODES`) -- se muestra sólo
            # UNA fila por nombre distinto (la primera ocupación en orden
            # del archivo, normalmente el '66SI'), igual que ya hace
            # Stonex con `unique_bases()` para sus referencias repetidas.
            # Sin este filtro, la tabla de "Corrección de base RTK"
            # mostraría una fila duplicada por cada reocupación -- además
            # de ser confuso, `_on_aplicar_correcciones_base` identifica
            # cada fila por (origen, archivo, nombre_original), así que
            # varias filas con la misma clave se pisarían entre sí al
            # aplicar (la última fila sin corrección escrita borraría la
            # que sí se acababa de aplicar en una fila anterior). Esto
            # sigue siendo válido con más de una base física distinta: si
            # "BASE1" se reocupa 3 veces y luego "BASE2" otras 2, este
            # filtro deja pasar sólo la primera ocupación de cada nombre
            # (2 filas en la tabla de corrección: "BASE1" y "BASE2").
            dc_bases_ya_agregadas = set()
            # Offset ARP↔L1 a aplicar para este archivo (ver
            # `dc_parser.resolve_receiver_arp_offset`). Desde la v2.52.0
            # se toma, con prioridad, del propio registro 'E2NM' del
            # archivo (`dc.receiver_arp_offset_from_file`) -- el receptor
            # reporta su propio offset de fábrica, así que esto funciona
            # para CUALQUIER modelo Trimble, no sólo los ya confirmados a
            # mano en `dc_parser.RECEIVER_ARP_OFFSET_M` -- y sólo cae a
            # esa tabla como respaldo si el archivo no trae ese campo.
            arp_offset = resolve_receiver_arp_offset(dc)
            # Desde la v2.51.0: avisar en el Registro, una vez por
            # archivo, cuando NO hay ningún offset confiable para este
            # receptor -- ni en el propio archivo ni en la tabla -- a
            # pedido explícito del usuario tras reportar `ar22-08-26.dsc`
            # (receptor "R780-2", todavía no confirmado en ese momento).
            # Antes este caso quedaba en silencio (la "Altura de
            # antena"/elevación mostraba el valor crudo, sin corregir,
            # sin ninguna señal visible de que faltaba un offset) y el
            # usuario sólo lo notó comparando contra GPSeismic. Con la
            # lectura directa del archivo (v2.52.0) este aviso ya debería
            # ser poco frecuente -- sólo archivos sin registro 'E2NM', o
            # con un formato de 'E2NM' inesperado. Sólo avisa si el
            # archivo de verdad trae algún punto con altura de antena (si
            # no trae ninguna, no hay nada que corregir y el aviso sería
            # ruido).
            if (
                dc.receiver_type
                and not receiver_arp_offset_known_for_file(dc)
                and any(p.antenna_height is not None for p in dc.points)
            ):
                self.log_importar.appendPlainText(self.t(
                    "log_receptor_sin_offset_arp",
                    archivo=os.path.basename(dc.path), receptor=dc.receiver_type.strip(),
                ))
            # Julian Date (Local) de GPSeismic: año + día del año (3
            # dígitos) de la fecha del archivo (`DCFile.date_text`, del
            # primer '13TS' -- sólo trae fecha, no se usa la hora, que no
            # se pudo verificar como confiable, ver la nota junto a
            # `PREVIEW_COL_JULIAN_DATE`). Verificado exacto contra la
            # base de datos POSTPLOT real (234/234 filas: "2018018" para
            # ar180118.dsc, del "01/18/2018" de su primer '13TS'). `None`
            # si el archivo no trae ningún '13TS'.
            julian_date_local = None
            if dc.date_text:
                try:
                    fecha_part = dc.date_text.split(" ")[0]
                    mes, dia, anio = (int(x) for x in fecha_part.split("/"))
                    dia_del_anio = datetime(anio, mes, dia).timetuple().tm_yday
                    julian_date_local = f"{anio}{dia_del_anio:03d}"
                except (ValueError, IndexError):
                    julian_date_local = None
            for point_idx, p in enumerate(dc.points):
                if p.is_base:
                    if p.name in dc_bases_ya_agregadas:
                        continue
                    dc_bases_ya_agregadas.add(p.name)
                track, bin_ = p.track_bin(line_digits) if line_digits > 0 else (None, None)
                # Altura WGS84 real del PUNTO EN TIERRA (lo que GPSeismic
                # muestra como "WGS84 Height"/lo que sube a esa columna de
                # POSTPLOT) -- a diferencia de `p.height`, que es la altura
                # elipsoidal cruda a nivel de la ANTENA. Hace falta
                # restarle la altura de antena ya corregida (jalón + offset
                # ARP del modelo de receptor, ver `RECEIVER_ARP_OFFSET_M`)
                # -- descubierto a pedido explícito del usuario, que
                # reportó que las coordenadas/elevación/altura de antena de
                # la previsualización de `0502YC.dsc` no coincidían con su
                # propia base de datos POSTPLOT real; verificado EXACTO,
                # sub-milimétrico, contra 405 puntos combinados de 2
                # archivos reales de referencia (`0502YC.dc`/`3001YC.dc`).
                # Nunca se aplica cuando `height_is_placeholder` es True
                # (ver esa nota en `dc_parser.DCPoint`): ahí `p.height` no
                # es una lectura real, así que restarle algo la empeoraría
                # -- se deja tal cual (mismo comportamiento que antes de
                # este hallazgo, todavía sin resolver para esos casos).
                altura_wgs84 = p.height
                # Altura cruda a nivel de antena, guardada aparte en la
                # fila (`altura_antena_cruda`) sólo cuando la resta de
                # arriba SÍ aplica -- es lo que permite recalcular
                # "Alt. WGS84 (m)"/"Elevación ortométrica" en vivo cuando
                # el usuario edita la celda "Altura de antena" después de
                # previsualizar (pedido explícito del usuario: "cuando
                # cambio... la altura de la antena, recalcula las
                # elevaciones?" -- antes NO se recalculaba, ver
                # `_on_preview_item_changed`/`_recalcular_altura_wgs84_fila`).
                # `None` para un punto con `height_is_placeholder` (no hay
                # nada que recalcular ahí, mismo criterio de no tocar ese
                # caso ya documentado arriba).
                altura_antena_cruda = None
                if not p.height_is_placeholder and p.antenna_height is not None:
                    altura_wgs84 = p.height - (p.antenna_height + arp_offset)
                    altura_antena_cruda = p.height
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(altura_wgs84, geoid_h)
                previa = ediciones_previas.get(("DC", dc.path, p.line_no))
                # Prefijo por defecto del nombre mostrado -- réplica de la
                # convención real de GPSeismic, confirmada contra la base
                # de datos POSTPLOT de referencia: "D" para un punto
                # descartado en campo (`DCPoint.deleted`, ver la nota
                # completa en dc_parser.py) y "?" para una reocupación
                # ambigua (`DCPoint.ambiguous_reoccupation`) -- editable,
                # el usuario puede quitarlo si corresponde. `previa`
                # respeta cualquier corrección ya hecha por el usuario, el
                # prefijo sólo se aplica la PRIMERA vez que se ve el punto.
                nombre_defecto = p.name
                # Descriptor de GPSeismic (ver `DCPoint.descriptor`):
                # GPSeismic le agrega el mismo prefijo "D" que al Nombre
                # cuando el punto queda descartado (verificado contra la
                # base de datos POSTPLOT real: "D51802277" trae
                # Descriptor "D60", no "60") -- nunca al reocupación
                # ambigua ("?52102279" trae Descriptor "60" sin prefijo).
                descriptor_defecto = p.descriptor or ""
                if p.deleted:
                    nombre_defecto = "D" + nombre_defecto
                    if descriptor_defecto:
                        descriptor_defecto = "D" + descriptor_defecto
                elif p.ambiguous_reoccupation:
                    nombre_defecto = "?" + nombre_defecto
                filas.append({
                    "origen": "DC", "dc_idx": dc_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(dc.path), "archivo_path": dc.path,
                    "job_name": dc.job_name, "instrument": dc.instrument,
                    "tipo": p.record_type,
                    # Trimble .dc no trae ningún dato de calidad de la
                    # solución (fix/float/autónomo) en ningún registro
                    # conocido de este formato -- se muestra "Autónomo"
                    # fijo para todos sus puntos (decisión del usuario,
                    # no un dato confirmado del archivo, ver la nota
                    # junto a la clave de i18n "calidad_autonomo").
                    "calidad": self.t("calidad_autonomo"),
                    "modo_texto": (
                        "RTK Cinematico (KI)" if p.record_type == "KI"
                        else "RTK Estatico/Fuente (SO)" if p.record_type == "SO"
                        else "RTK Base fisica (.dc)"
                    ),
                    "nombre": (previa["nombre"] if previa else nombre_defecto),
                    # `nombre_original` (sin editar por el usuario, SIN el
                    # prefijo "D"/"?" de arriba) es la identidad usada por
                    # la corrección de base RTK -- ver la nota junto a
                    # `CORR_BASE_COL_ARCHIVO`. Desde esta ronda, Trimble
                    # .dc SÍ participa de esa funcionalidad cuando trae una
                    # ocupación de base física ('66SI'/'66FD', ver
                    # `dc_parser.BASE_CODES`).
                    "nombre_original": p.name,
                    "is_base": p.is_base,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": altura_wgs84,
                    "altura_antena_cruda": altura_antena_cruda,
                    "track": track, "bin": bin_,
                    "geoid_h": geoid_h, "local_h": local_h,
                    # HI real de GPSeismic: '57KI' vigente al momento de
                    # la promoción '67SO'/'67TP' de este punto (ver
                    # `DCPoint.antenna_height`, corregido en esta ronda
                    # para leerse en ese momento y no en el '66KI'
                    # original) más el offset ARP↔L1 propio del modelo de
                    # receptor (`arp_offset`, arriba) -- verificado exacto
                    # (234/234, al milímetro) contra la base de datos
                    # POSTPLOT real. Sigue siendo editable por si el
                    # usuario necesita corregirlo.
                    "hi": (
                        previa.get("hi") if previa
                        else (p.antenna_height + arp_offset if p.antenna_height is not None else None)
                    ),
                    # Desde esta ronda: si el archivo trae un comentario
                    # de operador ('13NM') para este punto, se usa como
                    # valor inicial editable (ver `DCPoint.comment` en
                    # dc_parser.py, verificado texto por texto contra la
                    # base de datos POSTPLOT de referencia para sus 229
                    # puntos no descartados).
                    "comentario": (previa.get("comentario") if previa else (p.comment or "")),
                    # Igual que Hi-Target/CHCNav: una ocupación de base no
                    # se incluye por defecto al subir a POSTPLOT -- no es
                    # un punto receptor/fuente de campo. Desde esta ronda,
                    # un punto descartado en campo ('13NM' "Eliminado" o
                    # '67TP' sin una reocupación buena posterior, ver
                    # `DCPoint.deleted`) tampoco se incluye por defecto --
                    # el usuario puede volver a marcarlo si de verdad
                    # quiere subirlo.
                    "incluir": (
                        previa.get("incluir", not p.is_base and not p.deleted) if previa
                        else (not p.is_base and not p.deleted)
                    ),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    # Desde la v2.10.0: un punto '66SO' de este formato
                    # de .dc SÍ trae satélites/PDOP/HDOP/VDOP/épocas/
                    # duración de ocupación, en el registro 'C6NM' que
                    # dc_parser.py asocia automáticamente (ver
                    # `DCPoint.n_sats`/etc, deducidos por ingeniería
                    # inversa contra un archivo real y un valor de
                    # referencia confirmado por el usuario). Un '66KI'
                    # de este formato NUNCA los trae -- quedan en None,
                    # no es un error.
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": p.n_epochs, "occupation_seconds": p.occupation_seconds,
                    # "Elapsed Time" de GPSeismic (tiempo transcurrido
                    # desde el punto 'SO' anterior, ver la nota completa
                    # junto a `DCPoint.elapsed_seconds`) -- pedido
                    # explícito del usuario. Sólo Trimble .dc lo trae:
                    # ningún otro formato soportado tiene un contador de
                    # sesión equivalente que se pueda diferenciar entre
                    # puntos consecutivos.
                    "elapsed_seconds": p.elapsed_seconds,
                    # Precisión Hor./Vert. 95% y CQ: desde esta ronda SÍ
                    # se completan para Trimble .dc (pedido explícito del
                    # usuario: "lo necesitamos por control de calidad de
                    # la presicion del punto tomado en campo") -- ver
                    # `DCPoint.hor_precision_95`/`ver_precision_95`/`cq` y
                    # el docstring completo de `_parse_60nm_precision` en
                    # dc_parser.py, que documenta la verificación contra
                    # 436 puntos reales de 2 archivos independientes.
                    "hor_precision_95": p.hor_precision_95,
                    "ver_precision_95": p.ver_precision_95,
                    "cq": p.cq,
                    # Ya calculados por `dc_parser.parse_dc_text` (ver la
                    # nota más arriba) -- `None` para un punto is_base
                    # (nunca asociado a sí mismo) o para uno sin ninguna
                    # ocupación de base vista antes de él en el archivo.
                    "gps_baseline_m": p.base_baseline_m,
                    "gps_base_station": p.base_station_name,
                    # Nuevas columnas de esta ronda (ver la nota junto a
                    # `PREVIEW_COL_INCLUDE`): tipo y número de serie del
                    # receptor GNSS, tomados de 'E2NM' (ver
                    # `DCFile.receiver_type`/`receiver_sn` en
                    # dc_parser.py) -- distinto de `instrument` (el modelo
                    # del COLECTOR, de '00NM', no del receptor GNSS).
                    "receiver_type": dc.receiver_type, "receiver_sn": dc.receiver_sn,
                    "deleted": p.deleted, "ambiguous_reoccupation": p.ambiguous_reoccupation,
                    # Descriptor de GPSeismic: ver `descriptor_defecto`
                    # arriba (`DCPoint.descriptor`, verificado exacto
                    # 234/234 contra la base de datos POSTPLOT real).
                    # Modo de levantamiento (texto/valor): el 100% de los
                    # 234 puntos de esa misma base de datos traen Survey
                    # Mode "Phase"/3 para un punto 'KI'/'SO' real (no
                    # is_base) -- se usa como valor inicial editable.
                    "descriptor": (previa.get("descriptor") if previa else descriptor_defecto),
                    "julian_date_local": julian_date_local,
                    # "Hora de levant. (Local/GMT)" y "Hora serial (GPS)":
                    # desde esta ronda, Trimble .dc SÍ completa estos tres
                    # campos -- pero sólo cuando la semana de trabajo real
                    # del archivo (calculada del propio '13TS', ver
                    # `DCFile.date_text`) ya está calibrada en
                    # `dc_parser._GMT_WEEK_CALIBRATION` (ver el docstring
                    # completo ahí: K -la constante de "Serial Time (GPS)"-
                    # no es universal, salta en cada reinicio real del
                    # receptor, típicamente en el fin de semana). `None`
                    # (columna en blanco, como hasta ahora) para cualquier
                    # semana todavía sin calibrar -- mismo criterio de
                    # "exacto o en blanco, nunca inventado" del resto del
                    # plugin.
                    "serial_time_gps": p.serial_time_gps,
                    "survey_time_gmt": p.survey_time_gmt,
                    "survey_time_local": p.survey_time_local,
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa
                        else (SURVEY_MODE_TEXTO_EN["survey_mode_phase"] if not p.is_base else "")
                    ),
                    "survey_mode_value": (
                        previa.get("survey_mode_value") if previa
                        else ("3" if not p.is_base else "")
                    ),
                })

        for ht_idx, hf in enumerate(self.hitarget_files):
            for point_idx, p in enumerate(hf.points):
                track, bin_ = _track_bin_heuristic(p.name, line_digits)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(p.height, geoid_h)
                previa = ediciones_previas.get(("HITARGET", hf.path, p.line_no))
                filas.append({
                    "origen": "HITARGET", "dc_idx": ht_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(hf.path), "archivo_path": hf.path,
                    "job_name": None, "instrument": "Hi-Target",
                    "tipo": _hitarget_tipo_code(p),
                    # A diferencia de "tipo" (que agrega la categoría
                    # BASE para el Descriptor de POSTPLOT), "calidad"
                    # siempre traduce la columna Estado tal cual la trae
                    # el CSV -- ver `_hitarget_calidad_key`. El .raw (sin
                    # columna Estado -- ver hitarget_raw_parser.py)
                    # siempre cae en "calidad_nd".
                    "calidad": self.t(_hitarget_calidad_key(p)),
                    "modo_texto": f"RTK Hi-Target ({p.estado})" if p.estado else "RTK Hi-Target",
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    "is_base": p.is_base,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": p.height,
                    "track": track, "bin": bin_,
                    "geoid_h": geoid_h, "local_h": local_h,
                    "hi": (previa.get("hi") if previa else p.ant_height),
                    "comentario": (previa.get("comentario") if previa else (p.desc or "")),
                    "incluir": (previa.get("incluir", not p.is_base) if previa else (not p.is_base)),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    # Datos de calidad/base que el CSV de Hi-Target SÍ
                    # trae con columnas propias (a diferencia de un
                    # .dc). `gps_baseline_m`/`gps_base_station` los
                    # calcula `hitarget_parser` a partir de las columnas
                    # "Base B"/"Base L" (distancia a la base y, si
                    # coincide con una fila de ocupación de base del
                    # mismo archivo, su nombre).
                    # Hi-Target no trae HDOP/VDOP por separado en el CSV
                    # (sólo el PDOP combinado) -- se dejan en None.
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": None, "vdop": None,
                    "n_epochs": p.n_epochs,
                    "occupation_seconds": p.occupation_seconds,
                    "gps_baseline_m": p.base_baseline_m,
                    "gps_base_station": p.base_station_name,
                    # Descriptor de GPSeismic: sin dato equivalente
                    # confirmado en un CSV de Hi-Target -- queda en
                    # blanco y editable (ver la nota junto a
                    # `PREVIEW_COL_DESCRIPTOR`). Modo de levantamiento
                    # (texto/valor): pedido del usuario -- Phase/3 si el
                    # Estado de este punto dice "fix"/"fijo"/"fixed",
                    # Autónomo/1 en caso contrario (ver
                    # `_survey_mode_key_valor`).
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa
                        else SURVEY_MODE_TEXTO_EN[_survey_mode_key_valor(p.estado)[0]]
                    ),
                    "survey_mode_value": (
                        previa.get("survey_mode_value") if previa
                        else _survey_mode_key_valor(p.estado)[1]
                    ),
                })

        for cn_idx, cf in enumerate(self.chcnav_files):
            for point_idx, p in enumerate(cf.points):
                track, bin_ = _track_bin_heuristic(p.name, line_digits)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(p.height, geoid_h)
                previa = ediciones_previas.get(("CHCNAV", cf.path, p.line_no))
                filas.append({
                    "origen": "CHCNAV", "dc_idx": cn_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(cf.path), "archivo_path": cf.path,
                    "job_name": None, "instrument": "CHCNav",
                    "tipo": _chcnav_tipo_code(p),
                    # A pedido del usuario: se muestra el STATUS del
                    # .rw5 tal cual (ej. "FIXED"), SIN traducirlo a
                    # Fijo/Flotante/Autónomo -- el archivo real de
                    # referencia usado para construir este plugin sólo
                    # confirma ese valor, nunca uno de float/autónomo
                    # con el que verificar una traducción (ver
                    # `chcnav_parser.ChcnavPoint.status`).
                    "calidad": (p.status if p.status else self.t("calidad_nd")),
                    "modo_texto": (f"RTK CHCNav ({p.status})" if p.status else "RTK CHCNav"),
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    "is_base": p.is_base,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": p.height,
                    "track": track, "bin": bin_,
                    "geoid_h": geoid_h, "local_h": local_h,
                    # Desde la v2.22.0: si el archivo trae un registro
                    # 'LS' (campo 'HR') antes de este punto, se usa como
                    # altura de antena -- ver `ChcnavPoint.ant_height` y
                    # la nota de verificación matemática en el docstring
                    # de chcnav_parser.py (confirmado, no una
                    # interpretación por patrón como en el caso del .dc).
                    # Igual sigue siendo editable aquí.
                    "hi": (previa.get("hi") if previa else p.ant_height),
                    "comentario": (previa.get("comentario") if previa else ""),
                    # Desde que 'BP' se captura como punto is_base
                    # (corrección de base RTK), una ocupación de base NO
                    # se incluye por defecto al subir a POSTPLOT -- mismo
                    # criterio que ya usa Hi-Target para sus puntos
                    # 'set_base'.
                    "incluir": (previa.get("incluir", not p.is_base) if previa else (not p.is_base)),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    # El .rw5 de CHCNav SÍ trae satélites/PDOP/HDOP/VDOP/
                    # épocas para la mayoría de los puntos GPS (ver
                    # `chcnav_parser.py`), pero NO para todos: 14 de los
                    # 55 puntos del archivo real de referencia no traen
                    # el bloque de estadísticas de calidad (quedan en
                    # None -- no es un error, ver la nota más abajo
                    # sobre por qué esto NO los descarta de la
                    # previsualización, a diferencia de un '66KI' de
                    # .dc). El .rw5 no trae duración de ocupación por
                    # punto -- queda en None para cualquier punto de este
                    # origen. `gps_baseline_m`/`gps_base_station` SÍ se
                    # calculan desde que existe la corrección de base RTK
                    # (registro 'BP', ver chcnav_parser.py): distancia y
                    # nombre de la ocupación de base VIGENTE (por orden
                    # de aparición en el archivo, no por distancia) al
                    # momento de este punto -- None si el archivo no trae
                    # ningún 'BP' antes de él.
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": p.n_epochs, "occupation_seconds": None,
                    "gps_baseline_m": p.base_baseline_m, "gps_base_station": p.base_station_name,
                    # Fecha/hora del punto tal cual las trae el .rw5
                    # ("--DT.../--TM..."), sin interpretar su formato --
                    # sólo texto informativo para Survey_Time_Local.
                    "survey_time_local": (
                        f"{p.date_text} {p.time_text}" if (p.date_text and p.time_text)
                        else (p.date_text or p.time_text)
                    ),
                    # Descriptor de GPSeismic: sin dato equivalente
                    # confirmado en un .rw5 de CHCNav -- queda en blanco y
                    # editable (ver la nota junto a
                    # `PREVIEW_COL_DESCRIPTOR`). Modo de levantamiento
                    # (texto/valor): pedido del usuario, a partir del
                    # STATUS real del .rw5 (ver `_survey_mode_key_valor`).
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa
                        else SURVEY_MODE_TEXTO_EN[_survey_mode_key_valor(p.status)[0]]
                    ),
                    "survey_mode_value": (
                        previa.get("survey_mode_value") if previa
                        else _survey_mode_key_valor(p.status)[1]
                    ),
                })

        # SurPad reutiliza chcnav_parser.py tal cual (ver agregar_surpad),
        # así que este loop es una copia casi exacta del de arriba para
        # CHCNAV -- sólo cambia "origen"/"dc_idx" (clave propia en
        # `ediciones_previas` para no mezclar ediciones con un archivo
        # CHCNav real que tenga el mismo nombre) e "instrument"/
        # "modo_texto" para que el usuario vea "SurPad" en vez de
        # "CHCNav" en la previsualización.
        for sp_idx, cf in enumerate(self.surpad_files):
            for point_idx, p in enumerate(cf.points):
                track, bin_ = _track_bin_heuristic(p.name, line_digits)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(p.height, geoid_h)
                previa = ediciones_previas.get(("SURPAD", cf.path, p.line_no))
                filas.append({
                    "origen": "SURPAD", "dc_idx": sp_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(cf.path), "archivo_path": cf.path,
                    "job_name": None, "instrument": "SurPad",
                    # Sólo el .raw de SurPad trae modelo/serie del receptor
                    # (comentario "--Gnss Device"); en un .rw5 quedan en None.
                    "receiver_type": getattr(p, "receiver_type", None),
                    "receiver_sn": getattr(p, "receiver_sn", None),
                    "tipo": _chcnav_tipo_code(p),
                    # Mismo criterio que CHCNAV arriba: se muestra el
                    # STATUS tal cual (ej. "FIJO"), sin traducirlo --
                    # queda en "N/D" para los puntos con el bloque
                    # alterno "Avg/Min/Max" (ver chcnav_parser.py), que
                    # no trae ese dato.
                    "calidad": (p.status if p.status else self.t("calidad_nd")),
                    "modo_texto": (f"RTK SurPad ({p.status})" if p.status else "RTK SurPad"),
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    "is_base": p.is_base,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": p.height,
                    "track": track, "bin": bin_,
                    "geoid_h": geoid_h, "local_h": local_h,
                    "hi": (previa.get("hi") if previa else p.ant_height),
                    "comentario": (previa.get("comentario") if previa else ""),
                    "incluir": (previa.get("incluir", not p.is_base) if previa else (not p.is_base)),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": p.n_epochs, "occupation_seconds": None,
                    "gps_baseline_m": p.base_baseline_m, "gps_base_station": p.base_station_name,
                    "survey_time_local": (
                        f"{p.date_text} {p.time_text}" if (p.date_text and p.time_text)
                        else (p.date_text or p.time_text)
                    ),
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa
                        else SURVEY_MODE_TEXTO_EN[_survey_mode_key_valor(p.status)[0]]
                    ),
                    "survey_mode_value": (
                        previa.get("survey_mode_value") if previa
                        else _survey_mode_key_valor(p.status)[1]
                    ),
                })

        # SourceLink (CSV de posiciones de vibros, ver `sourcelink_parser.py`):
        # cada fila es un disparo de un vibrador. Track/Bin salen de las
        # columnas Line/Station del archivo (no de la heurística de dígitos),
        # el Surveyor es el Unit ID (número del vibro) de CADA punto, y el
        # comentario por defecto es el "Comment" del operador.
        for sl_idx, sf in enumerate(self.sourcelink_files):
            for point_idx, p in enumerate(sf.points):
                previa = ediciones_previas.get(("SOURCELINK", sf.path, p.line_no))
                # Altura de antena (HI) editable, por defecto 0 (decisión del
                # usuario: en campo a veces no se configura la altura de la
                # antena del vibro, ~2.73 m, y se decide después si se
                # corrige). `p.height` es la altura elipsoidal a nivel de
                # antena tal como viene en el CSV; la altura final es
                # `p.height - HI` (y la ortométrica se recalcula con ella),
                # igual que Trimble .dc -- ver `_recalcular_altura_wgs84_fila`.
                hi_sl = previa.get("hi") if previa else 0.0
                altura_sl = p.height - (hi_sl or 0.0)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(altura_sl, geoid_h)
                modo_key, modo_valor = _survey_mode_key_valor(p.quality)
                filas.append({
                    "origen": "SOURCELINK", "dc_idx": sl_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(sf.path), "archivo_path": sf.path,
                    "job_name": None, "instrument": "SourceLink",
                    "receiver_type": None, "receiver_sn": None,
                    "tipo": p.tipo,
                    "calidad": (p.quality if p.quality else self.t("calidad_nd")),
                    "modo_texto": (f"SourceLink ({p.quality})" if p.quality else "SourceLink"),
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    "is_base": False,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": altura_sl,
                    "altura_antena_cruda": p.height, "hi_vacio_es_cero": True,
                    "track": p.track, "bin": p.bin,
                    "surveyor": p.surveyor,
                    "geoid_h": geoid_h, "local_h": local_h,
                    "hi": hi_sl,
                    "comentario": (previa.get("comentario") if previa else p.comment),
                    "incluir": (previa.get("incluir", True) if previa else True),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": None, "occupation_seconds": None,
                    "gps_baseline_m": None, "gps_base_station": None,
                    "julian_date_local": p.julian_date_local,
                    "survey_time_local": p.survey_time_local,
                    "survey_time_gmt": p.survey_time_gmt,
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa else SURVEY_MODE_TEXTO_EN[modo_key]
                    ),
                    "survey_mode_value": (previa.get("survey_mode_value") if previa else modo_valor),
                })

        # Inova (.xls, ver `inova_parser.py`): un punto por VP (fila COG).
        # Igual que SourceLink el Surveyor es el/los vibro(s) del punto
        # ("7 y 8") y Track/Bin salen de SLine/Flag. La altura del archivo
        # es la elevación a nivel de ANTENA: se guarda cruda en
        # `altura_antena_cruda` y `altura_wgs84 = cruda - HI` con HI = la
        # altura de antena del grupo (la del archivo o 2.73 m, como la
        # macro del usuario), editable -- misma mecánica que Trimble .dc
        # (`_recalcular_altura_wgs84_fila`); HI en blanco = 0.
        for in_idx, inf in enumerate(self.inova_files):
            for point_idx, p in enumerate(inf.points):
                previa = ediciones_previas.get(("INOVA", inf.path, p.line_no))
                hi_in = previa.get("hi") if previa else p.antenna_height
                altura_in = p.height - (hi_in or 0.0)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(altura_in, geoid_h)
                modo_key, modo_valor = _inova_modo_key_valor(p.quality)
                filas.append({
                    "origen": "INOVA", "dc_idx": in_idx, "point_idx": point_idx, "line_no": p.line_no,
                    "archivo": os.path.basename(inf.path), "archivo_path": inf.path,
                    "job_name": None, "instrument": inf.instrument,
                    "receiver_type": None, "receiver_sn": None,
                    "tipo": p.tipo,
                    "calidad": (p.quality if p.quality else self.t("calidad_nd")),
                    "modo_texto": (f"Inova ({p.quality})" if p.quality else "Inova"),
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    "is_base": False,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": altura_in,
                    "altura_antena_cruda": p.height, "hi_vacio_es_cero": True,
                    "track": p.track, "bin": p.bin,
                    "surveyor": p.surveyor,
                    "geoid_h": geoid_h, "local_h": local_h,
                    "hi": hi_in,
                    "comentario": (
                        previa.get("comentario") if previa
                        else (f"Inova: {p.status}" if p.status and p.status.lower() != "pass" else "")
                    ),
                    "incluir": (previa.get("incluir", True) if previa else True),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": p.n_readings, "occupation_seconds": None,
                    "gps_baseline_m": None, "gps_base_station": p.base_station,
                    "julian_date_local": p.julian_date,
                    "survey_time_local": p.survey_time_local,
                    "survey_time_gmt": p.survey_time_gmt,
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (
                        previa.get("survey_mode_text") if previa else SURVEY_MODE_TEXTO_EN[modo_key]
                    ),
                    "survey_mode_value": (previa.get("survey_mode_value") if previa else modo_valor),
                })

        for st_idx, sf in enumerate(self.stonex_files):
            for point_idx, p in enumerate(sf.points):
                track, bin_ = _track_bin_heuristic(p.name, line_digits)
                geoid_h = None
                local_h = None
                if aplicar_geoide:
                    geoid_h = self._sample_geoid_undulation(p.lon, p.lat)
                    if geoid_h is not None:
                        local_h = geoid_utils.orthometric_height(p.height, geoid_h)
                previa = ediciones_previas.get(("STONEX", sf.path, p.row_id))
                filas.append({
                    "origen": "STONEX", "dc_idx": st_idx, "point_idx": point_idx, "line_no": p.row_id,
                    "archivo": os.path.basename(sf.path), "archivo_path": sf.path,
                    "job_name": None, "instrument": (p.receiver_type or "Stonex"),
                    "tipo": _stonex_tipo_code(p),
                    # A pedido del usuario (ronda 2.26.0, ver
                    # `_stonex_calidad_texto`): FIXED/FLOAT se traducen a
                    # Fijo/Flotante, DIF3D (posicionamiento diferencial,
                    # sin RTK) se deja tal cual, sin traducir.
                    "calidad": _stonex_calidad_texto(self.t, p.pos_state),
                    "modo_texto": (f"RTK Stonex ({p.pos_state})" if p.pos_state else "RTK Stonex"),
                    "nombre": (previa["nombre"] if previa else p.name),
                    "nombre_original": p.name,
                    # No se pudo verificar cómo se ve una ocupación de
                    # base LOCAL en este formato (ver docstring de
                    # stonex_parser.py) -- el archivo real de referencia
                    # sólo usó una referencia de red (RTCM/NTRIP), nunca
                    # una base física propia. `is_base` queda siempre en
                    # False para este origen por ahora.
                    "is_base": False,
                    "lat": p.lat, "lon": p.lon, "altura_wgs84": p.height,
                    "track": track, "bin": bin_,
                    "geoid_h": geoid_h, "local_h": local_h,
                    # La base de Stonex trae la altura de antena YA
                    # efectiva (con el offset de fase de la antena
                    # sumado -- ver `Antenna.H`/`R`/`HL1`/`HL2` en el
                    # docstring de stonex_parser.py), así que se usa tal
                    # cual como valor inicial editable, igual que el
                    # AntH de un CSV de Hi-Target.
                    "hi": (previa.get("hi") if previa else p.ant_height),
                    # Este formato no trae ningún campo de comentario/
                    # descripción libre por punto (a diferencia del Desc
                    # de Hi-Target) -- queda vacío y editable, igual que
                    # un punto de Trimble .dc o CHCNav.
                    "comentario": (previa.get("comentario") if previa else ""),
                    "incluir": (previa.get("incluir", True) if previa else True),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    # A diferencia de los otros tres formatos, la base de
                    # Stonex SÍ trae satélites/PDOP/HDOP/VDOP reales para
                    # el 100% de sus puntos (siempre vienen de una
                    # solución GNSS ya calculada por el receptor) y la
                    # distancia a la base/referencia YA calculada por el
                    # propio equipo (`DistancetoBase`), sin necesidad de
                    # recalcularla por geometría como hizo falta para
                    # Hi-Target. No trae un conteo de épocas promediadas
                    # comparable al de los otros formatos (`Sub_Total`
                    # siempre fue 1 en el archivo real de referencia) --
                    # queda en None.
                    "n_sats": p.n_sats, "pdop": p.pdop, "hdop": p.hdop, "vdop": p.vdop,
                    "n_epochs": None, "occupation_seconds": p.occupation_seconds,
                    "gps_baseline_m": p.gps_baseline_m, "gps_base_station": p.gps_base_station,
                    # Única marca, hasta ahora, con fecha/hora real y
                    # absoluta (local Y UTC) por punto -- las otras sólo
                    # traen, cuando traen algo, un reloj de sesión sin
                    # fecha (Hi-Target) o texto sin interpretar
                    # (CHCNav). Ver "Survey_Time_GMT" en
                    # `subir_dc_preview`.
                    "survey_time_local": p.survey_time_local,
                    "survey_time_gmt": p.survey_time_gmt,
                    "receiver_sn": p.receiver_sn,
                    "receiver_type": p.receiver_type,
                    # Descriptor/Modo de levantamiento de GPSeismic: sin
                    # dato equivalente confirmado en Stonex -- quedan en
                    # blanco y editables (ver la nota junto a
                    # `PREVIEW_COL_DESCRIPTOR`).
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (previa.get("survey_mode_text") if previa else ""),
                    "survey_mode_value": (previa.get("survey_mode_value") if previa else ""),
                })

            # Filas SINTÉTICAS de base/referencia (ronda 2.27.0): a
            # diferencia de Hi-Target/CHCNav, en Stonex NINGÚN punto del
            # archivo ES la base -- cada punto rover sólo trae repetida
            # la coordenada de la referencia que usó
            # (`GPSCoordinate.Base_Latitude`/`Base_Longitude`/
            # `Base_Altitude`, ver stonex_parser.py). Para poder
            # ofrecer la misma sección "Corrección de base RTK" que ya
            # existe para las otras dos marcas, se arma una fila
            # `is_base=True` por cada referencia distinta que devuelva
            # `sf.unique_bases()` -- su "coordenada libre" es
            # directamente la que trae el archivo (no una medición
            # propia, porque no la hay), y su nombre (`Base_ID`, p.ej.
            # "RTCM-Ref 0") es la misma clave que ya usa
            # `gps_base_station` en los puntos rover, así que
            # `_aplicar_correcciones_base_a_filas` los asocia sin
            # ningún cambio adicional. `line_no` usa un entero NEGATIVO
            # (nunca colisiona con un `Point.ID` real, siempre positivo)
            # para poder conservar ediciones (aunque en la práctica sólo
            # aplica a "incluir", ya que esta fila no tiene HI/comentario
            # propios) igual que cualquier otra fila.
            for base_idx, (base_name, base_lat, base_lon, base_height) in enumerate(sf.unique_bases()):
                line_no = -(base_idx + 1)
                previa = ediciones_previas.get(("STONEX", sf.path, line_no))
                filas.append({
                    "origen": "STONEX", "dc_idx": st_idx, "point_idx": -1, "line_no": line_no,
                    "archivo": os.path.basename(sf.path), "archivo_path": sf.path,
                    "job_name": None, "instrument": "Stonex",
                    "tipo": "BASE",
                    "calidad": self.t("calidad_nd"),
                    "modo_texto": "RTK Stonex (referencia)",
                    "nombre": (previa["nombre"] if previa else base_name),
                    "nombre_original": base_name,
                    "is_base": True,
                    "lat": base_lat, "lon": base_lon,
                    "altura_wgs84": (base_height if base_height is not None else 0.0),
                    "track": None, "bin": None,
                    "geoid_h": None, "local_h": None,
                    "hi": (previa.get("hi") if previa else None),
                    "comentario": (previa.get("comentario") if previa else ""),
                    # Nunca incluida por defecto al subir -- no es una
                    # medición propia (sin satélites/PDOP/HI reales),
                    # sólo la referencia que usaron los puntos rover.
                    # Mismo criterio que ya usan las ocupaciones de base
                    # de Hi-Target/CHCNav.
                    "incluir": (previa.get("incluir", False) if previa else False),
                    "subido": (previa.get("subido", False) if previa else False),
                    "match": None,
                    "n_sats": None, "pdop": None, "hdop": None, "vdop": None,
                    "n_epochs": None, "occupation_seconds": None,
                    "gps_baseline_m": None, "gps_base_station": None,
                    "survey_time_local": None, "survey_time_gmt": None, "receiver_sn": None,
                    "receiver_type": None,
                    "descriptor": (previa.get("descriptor") if previa else ""),
                    "survey_mode_text": (previa.get("survey_mode_text") if previa else ""),
                    "survey_mode_value": (previa.get("survey_mode_value") if previa else ""),
                })

        # Corrección de base RTK libre -> corregida (opcional, ver la
        # nota junto a `CORR_BASE_COL_ARCHIVO`): se aplica ANTES del
        # filtro de abajo (no cambia qué se descarta, sólo lat/lon/altura
        # de los puntos ya construidos) y antes de armar la tabla de esta
        # sección, para que ambas reflejen siempre la coordenada ya
        # corregida si el usuario guardó una.
        self._aplicar_correcciones_base_a_filas(filas, aplicar_geoide)

        # Pedido del usuario: la previsualización sólo debe mostrar puntos
        # con un levantamiento GNSS real de campo -- identificables porque
        # traen satélites/PDOP, un dato que sólo se puede tomar en campo
        # (a diferencia de la altura, que en algún formato podría venir
        # de un diseño). Un punto sin ninguno de los dos (típicamente un
        # '66KI' de un .dc en este formato, que nunca trae estos datos --
        # ver la v2.10.0) se descarta de la previsualización, no sólo se
        # oculta: nunca llega a subirse porque nunca llega a
        # `self._import_preview`. Los puntos de origen CHCNAV e HITARGET
        # son la excepción: en un .rw5, un registro GPS es SIEMPRE un
        # levantamiento real de campo (a diferencia de un '66KI' de .dc),
        # aunque 14 de los 55 puntos del archivo real de referencia no
        # traigan el bloque de estadísticas de calidad que trae la
        # mayoría; e igual para Hi-Target -- tanto un CSV (que sí suele
        # traer Sats/PDOP) como un .raw (que, desde la v2.23.0, nunca los
        # trae -- ver hitarget_raw_parser.py) son siempre un punto medido
        # en campo, nunca un punto de diseño, así que no hace falta (ni
        # corresponde) exigirles satélites/PDOP para no descartarlos.
        # STONEX se agrega a la misma excepción (aunque en la práctica
        # nunca haría falta: la base de Stonex siempre trae
        # satélites/PDOP reales para el 100% de sus puntos, ver
        # stonex_parser.py) -- por consistencia con el resto de marcas
        # que ya son siempre-campo-real, no por necesidad estricta.
        #
        # Una fila DC con 'is_base'=True (desde la ronda de soporte a base
        # RTK física, ver `dc_parser.BASE_CODES`) también se exceptúa,
        # aunque su origen siga siendo "DC": una ocupación de base física
        # ('66SI'/'66FD') es tan real-de-campo como cualquier 'SO', sólo
        # que este formato de .dc nunca le asocia un registro 'C6NM' de
        # calidad (ese registro sólo sigue a un 'SO') -- exigirle
        # satélites/PDOP la descartaría siempre, dejando la sección
        # "Corrección de base RTK" sin ninguna fila que mostrar incluso
        # cuando la base sí se detectó correctamente (ver
        # `DCFile.unique_base_names`).
        total_parseados = len(filas)
        filas = [
            f for f in filas
            if f.get("origen") in ("CHCNAV", "HITARGET", "STONEX", "SURPAD", "SOURCELINK", "INOVA")
            or f.get("is_base")
            or f.get("n_sats") is not None
            or f.get("pdop") is not None
        ]
        n_descartados = total_parseados - len(filas)

        self._import_preview = filas
        # El filtro/consulta guarda ÍNDICES dentro de `self._import_preview`
        # (ver `_construir_conexion_preview_sqlite`) -- como esta lista se
        # acaba de reconstruir de cero, cualquier filtro activo quedaría
        # apuntando a filas que ya no son las mismas, así que se limpia acá
        # en vez de arrastrarlo por error.
        self._preview_filtro_ids = None
        if hasattr(self, "txt_filtro_preview"):
            self.txt_filtro_preview.clear()
        if hasattr(self, "lbl_filtro_preview_resumen"):
            self.lbl_filtro_preview_resumen.setText("")
        self._import_geoid_applied = aplicar_geoide
        self._import_geoid_file_name = geoid_file_name
        self._ejecutar_comparacion_preview()
        self._llenar_tabla_preview()
        if n_descartados:
            self.log_importar.appendPlainText(self.t(
                "log_preview_discarded_no_field_data", n=n_descartados, total=total_parseados,
            ))
        self._actualizar_capa_provisional_preview()
        self._actualizar_capas_desplazamiento_preview()
        self._actualizar_seccion_correccion_base(correccion_borrador)

        if mostrar_aviso and self._import_preview:
            dest_crs = self._working_crs()
            crs_texto = dest_crs.authid() or dest_crs.description()
            if aplicar_geoide:
                cuerpo = self.t(
                    "dlg_aviso_transform_body_con_geoid",
                    n=len(self._import_preview), crs=crs_texto,
                    geoid=(geoid_file_name or "?"),
                )
            else:
                cuerpo = self.t(
                    "dlg_aviso_transform_body_sin_geoid",
                    n=len(self._import_preview), crs=crs_texto,
                )
            QMessageBox.information(self, self.t("dlg_aviso_transform_title"), cuerpo)

    def _aplicar_correcciones_base_a_filas(self, filas, aplicar_geoide):
        """Aplica sobre `filas` (recién armada por `previsualizar_dc()` a
        partir de los archivos parseados, ANTES del filtro que descarta
        puntos sin datos de campo reales) las traslaciones guardadas en
        `self._base_corrections`. Cada corrección es una traslación
        simple (mismo Δlat/Δlon/Δaltura para todos los puntos de esa
        ocupación): Δ = coordenada corregida (post-proceso estático) -
        coordenada libre (tal cual quedó parseada del archivo, NUNCA una
        ya corregida en una vuelta anterior -- por eso se recalcula la
        libre aquí mismo, desde `filas`, en vez de guardarla). Esto hace
        que aplicar, cambiar la coordenada corregida y volver a aplicar
        sea idempotente: nunca acumula el desplazamiento, y sobrevive a
        agregar otro archivo o volver a previsualizar sin que
        `_import_preview` tenga que conservar el valor ya corregido.

        La asociación punto-base es la que ya calcula cada parser
        (`base_baseline_m`/`base_station_name`, copiados a `gps_
        baseline_m`/`gps_base_station` de la fila -- ver hitarget_parser.py/
        hitarget_raw_parser.py/chcnav_parser.py/dc_parser.py, este último
        desde la ronda de soporte a múltiples bases por archivo, por orden
        de aparición): un punto sin base conocida (`gps_base_station`
        None -- p.ej. un archivo sin ninguna ocupación de base, o un punto
        de DC anterior a la primera ocupación de base del archivo) nunca
        se corrige, sin advertencia (nada que corregir)."""
        if not self._base_corrections:
            return
        # OJO: guarda una COPIA de lat/lon/altura (no el dict `f` en sí,
        # que se sigue mutando más abajo en este mismo bucle) -- una base
        # ('is_base') puede aparecer ANTES que sus puntos en `filas` (es
        # el caso real de CHCNav: los registros 'BP' preceden a todos los
        # 'GPS' del archivo), así que si `bases_libres` guardara una
        # referencia viva, para cuando se procese el primer punto
        # no-base la base ya estaría corregida y el delta saldría 0.
        bases_libres = {
            (f["origen"], f["archivo_path"], f["nombre_original"]): {
                "lat": f["lat"], "lon": f["lon"], "altura_wgs84": f["altura_wgs84"],
            }
            for f in filas if f.get("is_base")
        }
        for f in filas:
            if f.get("is_base"):
                clave = (f["origen"], f["archivo_path"], f["nombre_original"])
                corr = self._base_corrections.get(clave)
                if corr is None:
                    continue
                f["lat"] = corr["lat"]
                f["lon"] = corr["lon"]
                if corr.get("altura_wgs84") is not None:
                    f["altura_wgs84"] = corr["altura_wgs84"]
                f["base_corregida"] = True
            else:
                base_name = f.get("gps_base_station")
                if not base_name:
                    continue
                clave = (f["origen"], f["archivo_path"], base_name)
                corr = self._base_corrections.get(clave)
                if corr is None:
                    continue
                base_libre = bases_libres.get(clave)
                if base_libre is None:
                    # La corrección quedó guardada para una base que ya
                    # no está entre los archivos cargados (se quitó el
                    # archivo) -- no hay con qué calcular el delta.
                    continue
                d_lat = corr["lat"] - base_libre["lat"]
                d_lon = corr["lon"] - base_libre["lon"]
                d_alt = (
                    (corr["altura_wgs84"] - base_libre["altura_wgs84"])
                    if corr.get("altura_wgs84") is not None else 0.0
                )
                f["lat"] = f["lat"] + d_lat
                f["lon"] = f["lon"] + d_lon
                f["altura_wgs84"] = f["altura_wgs84"] + d_alt
                f["base_corregida"] = True
            if aplicar_geoide:
                geoid_h = self._sample_geoid_undulation(f["lon"], f["lat"])
                f["geoid_h"] = geoid_h
                f["local_h"] = (
                    geoid_utils.orthometric_height(f["altura_wgs84"], geoid_h)
                    if geoid_h is not None else None
                )

    def _leer_borrador_correccion_base_desde_tabla(self):
        """Lee de `tbl_correccion_base` la coordenada corregida que el
        usuario haya escrito pero todavía NO aplicado con "Aplicar
        correcciones" (ver `_on_aplicar_correcciones_base`), para poder
        conservarla si `previsualizar_dc()` se vuelve a llamar antes de
        que el usuario alcance a aplicarla (p.ej. agrega otro archivo).
        Devuelve {(origen, archivo_path, nombre_original): (texto_lat,
        texto_lon, texto_alt)}; un valor ya aplicado (guardado en
        `self._base_corrections`) no hace falta conservarlo aparte,
        porque `_aplicar_correcciones_base_a_filas` ya lo vuelve a
        aplicar solo en cada previsualización."""
        borrador = {}
        if not hasattr(self, "tbl_correccion_base"):
            return borrador
        tbl = self.tbl_correccion_base
        n = min(tbl.rowCount(), len(self._base_correction_rows))
        for row in range(n):
            meta = self._base_correction_rows[row]
            clave = (meta["origen"], meta["archivo_path"], meta["nombre_original"])
            item_lat = tbl.item(row, CORR_BASE_COL_LAT_CORR)
            item_lon = tbl.item(row, CORR_BASE_COL_LON_CORR)
            item_alt = tbl.item(row, CORR_BASE_COL_ALT_CORR)
            borrador[clave] = (
                item_lat.text() if item_lat else "",
                item_lon.text() if item_lon else "",
                item_alt.text() if item_alt else "",
            )
        return borrador

    def _actualizar_seccion_correccion_base(self, borrador=None):
        """Reconstruye `tbl_correccion_base` a partir de las filas
        `is_base` de `self._import_preview` (una por cada ocupación de
        base detectada entre los archivos de Hi-Target/CHCNav cargados,
        o -- desde la v2.27.0 -- una por cada referencia/base distinta
        que traigan los archivos de Stonex, sintetizada por
        `sf.unique_bases()` ya que ningún punto de ese formato ES la
        base en sí, ver la nota junto al loop STONEX en
        `previsualizar_dc()`) y muestra u oculta la sección completa
        según haya o no alguna. `borrador`, si se da (ver
        `_leer_borrador_correccion_base_desde_
        tabla`), repone lo que el usuario haya escrito y aún no aplicado;
        una corrección YA aplicada (en `self._base_corrections`) se
        repone directamente desde ahí, con prioridad sobre el borrador."""
        if not hasattr(self, "grp_correccion_base"):
            return
        borrador = borrador or {}
        bases = [f for f in self._import_preview if f.get("is_base")]
        self.grp_correccion_base.setVisible(bool(bases))
        tbl = self.tbl_correccion_base
        tbl.setRowCount(len(bases))
        self._base_correction_rows = []
        dest_crs = self._working_crs()
        for row, f in enumerate(bases):
            clave = (f["origen"], f["archivo_path"], f["nombre_original"])
            self._base_correction_rows.append({
                "origen": f["origen"], "archivo_path": f["archivo_path"],
                "nombre_original": f["nombre_original"],
            })
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_ARCHIVO, f["archivo"])
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_NOMBRE, f["nombre"])
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_LAT_LIBRE, f"{f['lat']:.7f}")
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_LON_LIBRE, f"{f['lon']:.7f}")
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_ALT_LIBRE, f"{f['altura_wgs84']:.3f}")

            # Coordenadas planas de la base libre (siempre disponibles,
            # se calculan a partir de lat/lon tal cual quedó parseada) --
            # pedido explícito del usuario junto con las de la
            # previsualización principal, reutilizando el mismo
            # `_transform_xy`.
            este_libre, norte_libre = _transform_xy(f["lon"], f["lat"], self.crs_wgs84, dest_crs, self.project)
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_ESTE_LIBRE, f"{este_libre:.3f}")
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_NORTE_LIBRE, f"{norte_libre:.3f}")

            aplicada = self._base_corrections.get(clave)
            texto_lat = texto_lon = texto_alt = ""
            texto_este_corr = texto_norte_corr = ""
            if aplicada is not None:
                texto_lat = f"{aplicada['lat']:.7f}"
                texto_lon = f"{aplicada['lon']:.7f}"
                texto_alt = "" if aplicada.get("altura_wgs84") is None else f"{aplicada['altura_wgs84']:.3f}"
                # Coordenada plana de la corregida: sólo cuando la
                # corrección ya está APLICADA (no mientras el usuario
                # sólo escribió un borrador todavía sin aplicar), igual
                # criterio que ya usa el "Estado" de esta misma fila.
                este_corr, norte_corr = _transform_xy(
                    aplicada["lon"], aplicada["lat"], self.crs_wgs84, dest_crs, self.project,
                )
                texto_este_corr = f"{este_corr:.3f}"
                texto_norte_corr = f"{norte_corr:.3f}"
            elif clave in borrador:
                texto_lat, texto_lon, texto_alt = borrador[clave]
            tbl.setItem(row, CORR_BASE_COL_LAT_CORR, QTableWidgetItem(texto_lat))
            tbl.setItem(row, CORR_BASE_COL_LON_CORR, QTableWidgetItem(texto_lon))
            tbl.setItem(row, CORR_BASE_COL_ALT_CORR, QTableWidgetItem(texto_alt))
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_ESTE_CORR, texto_este_corr)
            self._set_correccion_base_readonly_cell(row, CORR_BASE_COL_NORTE_CORR, texto_norte_corr)

            btn_cargar = QPushButton(self.t("btn_cargar_correccion_base"))
            btn_cargar.clicked.connect(lambda _checked=False, r=row: self._on_cargar_correccion_base(r))
            tbl.setCellWidget(row, CORR_BASE_COL_CARGAR, btn_cargar)

            estado_texto = self.t("status_correccion_aplicada") if aplicada is not None else self.t("status_correccion_pendiente")
            item_estado = QTableWidgetItem(estado_texto)
            item_estado.setFlags(item_estado.flags() & ~ITEM_IS_EDITABLE)
            if aplicada is not None:
                item_estado.setBackground(COLOR_DENTRO)
            tbl.setItem(row, CORR_BASE_COL_ESTADO, item_estado)

        tbl.resizeColumnsToContents()

    def _set_correccion_base_readonly_cell(self, row, col, text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~ITEM_IS_EDITABLE)
        self.tbl_correccion_base.setItem(row, col, item)

    def _leer_coordenada_corregida_csv(self, path: str, nombre_base: str):
        """Lee un archivo simple (formato propio de esta funcionalidad,
        no de ningún equipo GNSS) con la coordenada YA corregida de una
        base -- CSV con o sin encabezado, columnas "Lat,Lon[,Altura]" o
        "Nombre,Lat,Lon[,Altura]" (coma o punto decimal, cualquiera de
        los dos). Si trae varias filas de datos, busca la que tenga un
        nombre igual (sin distinguir mayúsculas/espacios) a `nombre_base`;
        si sólo trae una, la usa sin importar el nombre. Devuelve (lat,
        lon, altura_o_None); lanza ValueError con un mensaje traducible
        si no puede interpretar nada útil."""
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            filas_csv = [row for row in csv.reader(fh) if any(c.strip() for c in row)]
        if not filas_csv:
            raise ValueError(self.t("err_correccion_archivo_vacio"))

        def _num(texto):
            texto = (texto or "").strip().replace(",", ".")
            if not texto:
                return None
            return float(texto)

        candidatas = []  # (nombre_o_None, lat, lon, altura_o_None)
        for row in filas_csv:
            celdas = [c.strip() for c in row]
            if len(celdas) < 2:
                continue
            try:
                # ¿La primera celda es un número? -> "Lat,Lon[,Altura]".
                lat = _num(celdas[0])
                if lat is None:
                    raise ValueError
                lon = _num(celdas[1]) if len(celdas) > 1 else None
                nombre = None
                alt = _num(celdas[2]) if len(celdas) > 2 else None
            except ValueError:
                # Primera celda no numérica -> encabezado, o
                # "Nombre,Lat,Lon[,Altura]".
                if len(celdas) < 3:
                    continue
                try:
                    lat = _num(celdas[1])
                    lon = _num(celdas[2])
                except ValueError:
                    continue
                if lat is None:
                    continue
                nombre = celdas[0]
                alt = _num(celdas[3]) if len(celdas) > 3 else None
            if lat is None or lon is None:
                continue
            candidatas.append((nombre, lat, lon, alt))

        if not candidatas:
            raise ValueError(self.t("err_correccion_archivo_sin_datos"))
        if len(candidatas) == 1:
            _, lat, lon, alt = candidatas[0]
            return lat, lon, alt
        objetivo = (nombre_base or "").strip().lower()
        for nombre, lat, lon, alt in candidatas:
            if nombre and nombre.strip().lower() == objetivo:
                return lat, lon, alt
        raise ValueError(self.t("err_correccion_archivo_sin_match", nombre=nombre_base))

    def _on_cargar_correccion_base(self, row: int):
        if row >= len(self._base_correction_rows):
            return
        meta = self._base_correction_rows[row]
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("dlg_cargar_correccion_title"), "", self.t("filter_correccion_csv"),
        )
        if not path:
            return
        try:
            lat, lon, alt = self._leer_coordenada_corregida_csv(path, meta["nombre_original"])
        except Exception as e:
            QMessageBox.warning(self, self.t("warn_read_file_title"), f"{os.path.basename(path)}:\n{e}")
            return
        tbl = self.tbl_correccion_base
        tbl.setItem(row, CORR_BASE_COL_LAT_CORR, QTableWidgetItem(f"{lat:.7f}"))
        tbl.setItem(row, CORR_BASE_COL_LON_CORR, QTableWidgetItem(f"{lon:.7f}"))
        tbl.setItem(row, CORR_BASE_COL_ALT_CORR, QTableWidgetItem("" if alt is None else f"{alt:.3f}"))

    def _on_aplicar_correcciones_base(self):
        """Lee las coordenadas corregidas escritas en `tbl_correccion_base`
        (manual o cargadas desde archivo, da igual -- ambas terminan
        como texto en las mismas celdas) y actualiza
        `self._base_corrections`: una fila con Lat y Lon corregidas
        completas queda guardada (o reemplaza la anterior); una fila
        vacía en ambas quita cualquier corrección previa para esa base
        (vuelve a la coordenada libre). Después vuelve a previsualizar
        para que el desplazamiento se aplique de una vez a todos los
        puntos de esa base (ver `_aplicar_correcciones_base_a_filas`)."""
        if not hasattr(self, "tbl_correccion_base"):
            return
        tbl = self.tbl_correccion_base
        saltos_grandes = []  # [(nombre, distancia_m), ...] para confirmar si hace falta
        cambios = []  # [(clave, corr_o_None)]
        for row, meta in enumerate(self._base_correction_rows):
            item_lat = tbl.item(row, CORR_BASE_COL_LAT_CORR)
            item_lon = tbl.item(row, CORR_BASE_COL_LON_CORR)
            item_alt = tbl.item(row, CORR_BASE_COL_ALT_CORR)
            texto_lat = (item_lat.text().strip() if item_lat else "")
            texto_lon = (item_lon.text().strip() if item_lon else "")
            texto_alt = (item_alt.text().strip() if item_alt else "")
            clave = (meta["origen"], meta["archivo_path"], meta["nombre_original"])
            if not texto_lat and not texto_lon:
                cambios.append((clave, None))
                continue
            if not texto_lat or not texto_lon:
                QMessageBox.warning(
                    self, self.t("warn_correccion_incompleta_title"),
                    self.t("warn_correccion_incompleta_body", archivo=self._base_correction_row_label(row)),
                )
                return
            try:
                lat = float(texto_lat.replace(",", "."))
                lon = float(texto_lon.replace(",", "."))
                alt = float(texto_alt.replace(",", ".")) if texto_alt else None
            except ValueError:
                QMessageBox.warning(
                    self, self.t("warn_correccion_invalida_title"),
                    self.t("warn_correccion_invalida_body", archivo=self._base_correction_row_label(row)),
                )
                return
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                QMessageBox.warning(
                    self, self.t("warn_correccion_invalida_title"),
                    self.t("warn_correccion_invalida_body", archivo=self._base_correction_row_label(row)),
                )
                return
            # Distancia respecto a la coordenada libre mostrada en la
            # misma fila, para el aviso de salto sospechosamente grande.
            item_lat_libre = tbl.item(row, CORR_BASE_COL_LAT_LIBRE)
            item_lon_libre = tbl.item(row, CORR_BASE_COL_LON_LIBRE)
            try:
                lat_libre = float(item_lat_libre.text()) if item_lat_libre else None
                lon_libre = float(item_lon_libre.text()) if item_lon_libre else None
            except ValueError:
                lat_libre = lon_libre = None
            if lat_libre is not None and lon_libre is not None:
                # Reutiliza `_haversine_m` de hitarget_parser.py (ya
                # escrita y probada) en vez de duplicarla aquí.
                dist = hitarget_parser._haversine_m(lat, lon, lat_libre, lon_libre)
                if dist > CORR_BASE_SHIFT_WARN_M:
                    saltos_grandes.append((self._base_correction_row_label(row), dist))
            cambios.append((clave, {"lat": lat, "lon": lon, "altura_wgs84": alt}))

        if not cambios:
            return
        if saltos_grandes:
            detalle = "\n".join(f"- {nombre}: {dist:.1f} m" for nombre, dist in saltos_grandes)
            resp = QMessageBox.question(
                self, self.t("warn_correccion_salto_grande_title"),
                self.t(
                    "warn_correccion_salto_grande_body", detalle=detalle,
                    umbral=f"{CORR_BASE_SHIFT_WARN_M:.0f} m",
                ),
            )
            if resp not in (MSG_YES,):
                return

        n_aplicadas = 0
        n_quitadas = 0
        for clave, corr in cambios:
            if corr is None:
                if self._base_corrections.pop(clave, None) is not None:
                    n_quitadas += 1
            else:
                self._base_corrections[clave] = corr
                n_aplicadas += 1

        # `mostrar_aviso=False`: esto es una re-previsualización interna
        # (aplicar/quitar una corrección de base), no la primera vez que
        # se previsualizan archivos de campo nuevos -- el aviso de
        # transformación/geoide ya se mostró entonces (ver
        # `previsualizar_dc`).
        self.previsualizar_dc(mostrar_aviso=False)
        if n_aplicadas:
            self.log_importar.appendPlainText(self.t("log_correccion_base_aplicada", n=n_aplicadas))
        if n_quitadas:
            self.log_importar.appendPlainText(self.t("log_correccion_base_quitada", n=n_quitadas))

    def _base_correction_row_label(self, row: int) -> str:
        if row >= len(self._base_correction_rows):
            return ""
        meta = self._base_correction_rows[row]
        return f"{os.path.basename(meta['archivo_path'])} / {meta['nombre_original']}"

    def _sync_preview_edits_desde_tabla(self):
        """Copia a `self._import_preview` lo que el usuario haya editado
        en la tabla (Nombre/HI/Comentario/Incluir/Descriptor/Modo de
        levantamiento) antes de recalcular o volver a comparar, para no
        perderlo."""
        if not hasattr(self, "tbl_import_preview"):
            return
        tbl = self.tbl_import_preview
        n = min(tbl.rowCount(), len(self._import_preview))
        for row in range(n):
            fila = self._import_preview[row]
            item_nombre = tbl.item(row, PREVIEW_COL_NOMBRE)
            if item_nombre is not None:
                nuevo = item_nombre.text().strip()
                if nuevo:
                    fila["nombre"] = nuevo
            item_hi = tbl.item(row, PREVIEW_COL_HI)
            if item_hi is not None:
                fila["hi"] = _parse_optional_float(item_hi.text())
            item_com = tbl.item(row, PREVIEW_COL_COMENTARIO)
            if item_com is not None:
                fila["comentario"] = item_com.text()
            item_inc = tbl.item(row, PREVIEW_COL_INCLUDE)
            if item_inc is not None and not fila.get("subido"):
                fila["incluir"] = item_inc.checkState() == CHECK_STATE_CHECKED
            # Descriptor y Modo de levantamiento (texto/valor): nuevas
            # celdas editables de esta ronda (ver la nota junto a
            # `PREVIEW_COL_DESCRIPTOR`) -- sólo texto libre, igual que
            # Comentario, sin ningún cálculo ni validación.
            item_desc = tbl.item(row, PREVIEW_COL_DESCRIPTOR)
            if item_desc is not None:
                fila["descriptor"] = item_desc.text()
            item_modo_texto = tbl.item(row, PREVIEW_COL_SURVEY_MODE_TEXT)
            if item_modo_texto is not None:
                fila["survey_mode_text"] = item_modo_texto.text()
            item_modo_valor = tbl.item(row, PREVIEW_COL_SURVEY_MODE_VALUE)
            if item_modo_valor is not None:
                fila["survey_mode_value"] = item_modo_valor.text()

    def _on_preview_item_changed(self, item):
        """Conectado a `itemChanged` de `tbl_import_preview`: recalcula en
        vivo "Alt. WGS84 (m)"/"Elevación ortométrica" cuando el usuario
        edita la celda "Altura de antena" (HI) -- pedido explícito del
        usuario ("cuando cambio en la previsualizacion la altura de la
        antena, recalcula las elevaciones?"): antes NO se recalculaba, la
        elevación se quedaba con el valor calculado al previsualizar,
        desactualizada respecto a cualquier corrección posterior de HI.
        Ignora cualquier otro cambio de celda -- sólo importa la columna
        HI acá (los demás campos editables, como Nombre/Comentario/
        Descriptor, se siguen sincronizando de forma perezosa por
        `_sync_preview_edits_desde_tabla`, sin necesidad de reaccionar en
        vivo). Se conecta una sola vez (ver `_setup_import_preview_tab` o
        donde se crea `tbl_import_preview`); `_llenar_tabla_preview`
        bloquea señales mientras reconstruye la tabla entera para no
        disparar esto miles de veces (una por celda HI) en cada
        previsualización."""
        if item.column() == PREVIEW_COL_NOMBRE:
            self._actualizar_derivados_nombre_fila(item.row())
            return
        if item.column() != PREVIEW_COL_HI:
            return
        self._recalcular_altura_wgs84_fila(item.row())

    def _actualizar_derivados_nombre_fila(self, row):
        """Al editar la celda "Nombre" de la previsualización, actualiza en
        vivo "Estación (valor)", "Línea" y "Estaca" (pedido explícito del
        usuario) con la misma regla que usa GPSeismic y que ya aplicaba
        `_llenar_tabla_preview` (ver `punto_nombre.derivados_de_nombre`),
        y guarda esos valores en la fila para que lo que se SUBE a POSTPLOT
        (Track/Bin/Station_Value) sea lo que se ve en la tabla. Un nombre
        vacío se rechaza: se restaura el anterior."""
        if row >= len(self._import_preview):
            return
        fila = self._import_preview[row]
        tbl = self.tbl_import_preview
        item = tbl.item(row, PREVIEW_COL_NOMBRE)
        if item is None:
            return
        nuevo = item.text().strip()
        tbl.blockSignals(True)
        try:
            if not nuevo:
                item.setText(fila["nombre"])
                return
            fila["nombre"] = nuevo
            line_digits = int(self.spn_digitos_linea.value()) if hasattr(self, "spn_digitos_linea") else 0
            station_value, track, bin_ = punto_nombre.derivados_de_nombre(nuevo, line_digits)
            fila["track"] = track
            fila["bin"] = bin_
            self._set_preview_readonly_cell(row, PREVIEW_COL_STATION_VALUE, station_value)
            self._set_preview_readonly_cell(row, PREVIEW_COL_TRACK, track)
            self._set_preview_readonly_cell(row, PREVIEW_COL_BIN, bin_)
        finally:
            tbl.blockSignals(False)

    def _recalcular_altura_wgs84_fila(self, row):
        """Recalcula "Alt. WGS84 (m)"/"Elevación ortométrica" de la fila
        `row` a partir de la altura de antena ACTUAL de la celda HI (ya
        editada por el usuario) -- ver `_on_preview_item_changed`/
        `aplicar_valor_bulk`. Sólo aplica cuando la fila trae
        `altura_antena_cruda` (Trimble .dc, punto con lectura geodésica
        propia -- ver `DCPoint.height_is_placeholder`); para cualquier
        otra fila (HITARGET/CHCNAV/STONEX, o un .dc con altura no
        recalculable) no hay nada que hacer -- su "Alt. WGS84 (m)" nunca
        dependió de HI, ni antes de este hallazgo ni ahora."""
        if row >= len(self._import_preview):
            return
        fila = self._import_preview[row]
        altura_antena_cruda = fila.get("altura_antena_cruda")
        if altura_antena_cruda is None:
            return
        tbl = self.tbl_import_preview
        item_hi = tbl.item(row, PREVIEW_COL_HI)
        nuevo_hi = _parse_optional_float(item_hi.text()) if item_hi is not None else None
        fila["hi"] = nuevo_hi
        if nuevo_hi is None and fila.get("hi_vacio_es_cero"):
            # SourceLink: HI en blanco equivale a 0 (sin corrección), la
            # altura vuelve al valor crudo del archivo.
            nuevo_hi = 0.0
        if nuevo_hi is None:
            # HI en blanco: no hay con qué corregir -- se deja "Alt. WGS84"
            # como estaba (no se inventa un offset de cero), mismo
            # criterio de "exacto o en blanco" del resto del plugin.
            return
        fila["altura_wgs84"] = altura_antena_cruda - nuevo_hi
        if fila.get("geoid_h") is not None:
            fila["local_h"] = geoid_utils.orthometric_height(fila["altura_wgs84"], fila["geoid_h"])
        tbl.blockSignals(True)
        try:
            self._set_preview_readonly_cell(row, PREVIEW_COL_ALTURA, f"{fila['altura_wgs84']:.3f}")
            local_h = fila.get("local_h")
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_ORTOMETRICA, f"{local_h:.3f}" if local_h is not None else "-",
            )
        finally:
            tbl.blockSignals(False)

    def actualizar_comparacion_preview(self):
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        # Aquí sí la tabla ya refleja `self._import_preview` (se llenó en
        # la previsualización o en una comparación anterior), así que
        # hay que respetar lo que el usuario haya editado antes de
        # volver a emparejar por nombre.
        self._sync_preview_edits_desde_tabla()
        self._ejecutar_comparacion_preview()
        for row in range(min(self.tbl_import_preview.rowCount(), len(self._import_preview))):
            self._render_preview_match_cells(row, self._import_preview[row])
        self._render_import_preview_summary()
        self._actualizar_capas_desplazamiento_preview()

    def _ejecutar_comparacion_preview(self):
        """Empareja `self._import_preview` (puntos del .dc aún no
        subidos) contra la tabla PREPLOT del proyecto -- a diferencia de
        la sección "Comparar" (que compara contra POSTPLOT ya subido),
        aquí se compara en memoria, antes de escribir nada en la base de
        datos, para decidir qué subir.

        OJO: a propósito NO sincroniza ediciones desde `tbl_import_preview`
        -- quien la llame debe hacerlo antes si corresponde (ver
        `actualizar_comparacion_preview`). Cuando la llama
        `previsualizar_dc()` justo después de reconstruir
        `self._import_preview` desde cero, la tabla todavía muestra la
        previsualización ANTERIOR (no se ha vuelto a llenar todavía), así
        que sincronizar aquí pisaría los nombres recién parseados con el
        contenido viejo que todavía está en pantalla."""
        for fila in self._import_preview:
            fila["match"] = None
        self._preplot_track_azimuths = {}

        if not self._import_preview:
            self._last_import_preview_summary = None
            return

        diseno = self._fetch_levantado_xy("PREPLOT", self._working_crs()) if self.conn is not None else []
        if not diseno:
            self._last_import_preview_summary = (len(self._import_preview), 0, 0, False)
            return

        dest_crs = self._working_crs()
        line_digits = int(self.spn_digitos_linea.value()) if hasattr(self, "spn_digitos_linea") else 0
        self._preplot_track_azimuths = self._calcular_preplot_track_azimuths(dest_crs, line_digits)
        levantado = []
        for fila in self._import_preview:
            x, y = _transform_xy(fila["lon"], fila["lat"], self.crs_wgs84, dest_crs, self.project)
            levantado.append({"name": fila["nombre"], "x": x, "y": y, "z": fila["altura_wgs84"]})

        tolerancia = self.spn_tolerancia_import.value()
        aproximado = self.chk_aproximado_import.isChecked()
        result = csv_matcher.match_by_name(levantado, diseno, tolerancia_m=tolerancia, permitir_aproximado=aproximado)

        match_por_nombre = {}
        for m in result.matched:
            match_por_nombre.setdefault(m["name_levantado"], m)
        for fila in self._import_preview:
            fila["match"] = match_por_nombre.get(fila["nombre"])

        self._last_import_preview_summary = (len(self._import_preview), result.n_matched, result.n_dentro_tolerancia, True)

    def _import_preview_headers(self):
        # Reorganizada para reproducir el layout de 58 columnas de la
        # base de datos POSTPLOT real de GPSeismic -- ver la nota junto a
        # `PREVIEW_COL_INCLUDE`. Las primeras 58 (después de "Incluir")
        # siguen EXACTAMENTE ese orden -- salvo Elevación ortométrica,
        # movida a propósito justo al lado de Alt. WGS84 (ver la nota
        # completa junto a `PREVIEW_COL_INCLUDE`) -- ; el resto son
        # columnas extra propias del plugin para comparar contra PREPLOT
        # ("Calidad" se quitó de esta tabla, ver la misma nota).
        return [
            self.t("col_include"), self.t("col_point_name"),
            self.t("col_station_value"), self.t("col_track"), self.t("col_bin"),
            self.t("col_descriptor"),
            self.t("col_lat_wgs84"), self.t("col_lon_wgs84"),
            self.t("col_lat_local"), self.t("col_lon_local"),
            self.t("col_easting"), self.t("col_northing"),
            self.t("col_height_wgs84"),
            self.t("col_ortometrica"),
            self.t("col_scale_factor"), self.t("col_convergence"),
            self.t("col_survey_mode_text"), self.t("col_survey_mode_value"),
            self.t("col_antenna_height"),
            self.t("col_offset_north"), self.t("col_offset_east"),
            self.t("col_offset_range"), self.t("col_offset_bearing"),
            self.t("col_offset_inline"), self.t("col_offset_crossline"),
            self.t("col_offset_height"),
            self.t("col_inline_azimuth"),
            self.t("col_hor_precision"), self.t("col_ver_precision"), self.t("col_cq"),
            self.t("col_n_sats"), self.t("col_pdop"), self.t("col_hdop"), self.t("col_vdop"),
            self.t("col_julian_date"),
            self.t("col_survey_time_local"), self.t("col_survey_time_gmt"),
            self.t("col_serial_time_gps"), self.t("col_elapsed_time"), self.t("col_populate_time"),
            self.t("col_local_datum"), self.t("col_local_system"),
            self.t("col_distance_units"), self.t("col_distance_factor"),
            self.t("col_comment"),
            self.t("col_download_file"), self.t("col_job_name"),
            self.t("col_receiver_type"), self.t("col_receiver_sn"),
            self.t("col_gdop"), self.t("col_unit_variance"),
            self.t("col_gps_baseline"), self.t("col_gps_base_station"),
            self.t("col_occupation_time"),
            self.t("col_init_block"), self.t("col_station_deltas"),
            self.t("col_consecutive_intervals"), self.t("col_consecutive_azimuths"),
            self.t("col_recnum"), self.t("col_reserved"),
            # -- fin de las 58 columnas de GPSeismic -- columnas extra
            # propias del plugin, ya existentes antes de esta ronda:
            self.t("col_type"),
            self.t("col_preplot_match"), self.t("col_delta_x"), self.t("col_delta_y"),
            self.t("col_dist_2d"), self.t("col_status"), self.t("col_file"),
            self.t("col_surveyor"),
        ]

    def _correccion_base_headers(self):
        return [
            self.t("col_file"), self.t("col_base_name"),
            self.t("col_lat_libre"), self.t("col_lon_libre"), self.t("col_alt_libre"),
            self.t("col_este_libre"), self.t("col_norte_libre"),
            self.t("col_lat_corregida"), self.t("col_lon_corregida"), self.t("col_alt_corregida"),
            self.t("col_este_corregida"), self.t("col_norte_corregida"),
            self.t("col_cargar"), self.t("col_status"),
        ]

    def _set_preview_readonly_cell(self, row, col, text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~ITEM_IS_EDITABLE)
        self.tbl_import_preview.setItem(row, col, item)

    def _render_preview_match_cells(self, row, fila):
        if fila.get("subido"):
            self._set_preview_readonly_cell(row, PREVIEW_COL_PREPLOT, "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_E, "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_N, "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_DIST2D, "-")
            estado_texto = self.t("status_already_uploaded")
            color = COLOR_YA_SUBIDO
        else:
            m = fila.get("match")
            if m is None:
                self._set_preview_readonly_cell(row, PREVIEW_COL_PREPLOT, "-")
                self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_E, "-")
                self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_N, "-")
                self._set_preview_readonly_cell(row, PREVIEW_COL_DIST2D, "-")
                estado_texto = self.t("status_no_preplot_match")
                color = None
            else:
                self._set_preview_readonly_cell(row, PREVIEW_COL_PREPLOT, m["name_diseno"])
                self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_E, f"{m['delta_x']:.3f}")
                self._set_preview_readonly_cell(row, PREVIEW_COL_DELTA_N, f"{m['delta_y']:.3f}")
                self._set_preview_readonly_cell(row, PREVIEW_COL_DIST2D, f"{m['distancia_2d']:.3f}")
                dentro = m["dentro_tolerancia"]
                estado_texto = self.t("status_within_tolerance") if dentro else self.t("status_outside_tolerance")
                color = COLOR_DENTRO if dentro else COLOR_FUERA

        item_estado = QTableWidgetItem(estado_texto)
        item_estado.setFlags(item_estado.flags() & ~ITEM_IS_EDITABLE)
        if color is not None:
            item_estado.setBackground(color)
        self.tbl_import_preview.setItem(row, PREVIEW_COL_ESTADO, item_estado)

    def _set_preview_editable_cell(self, row, col, text, ya_subido):
        """Como `_set_preview_readonly_cell`, pero deja la celda editable
        cuando el punto todavía no se subió a POSTPLOT (`ya_subido`) --
        ayuda para no repetir el mismo `if ya_subido: ... else: ...` en
        cada una de las celdas editables de la previsualización (Nombre/
        HI/Comentario/Descriptor/Modo de levantamiento)."""
        if ya_subido:
            self._set_preview_readonly_cell(row, col, text)
        else:
            self.tbl_import_preview.setItem(row, col, QTableWidgetItem(text))

    def _llenar_tabla_preview(self):
        tbl = self.tbl_import_preview
        # Señales bloqueadas mientras se reconstruye la tabla entera: sin
        # esto, cada celda HI insertada dispararía
        # `_on_preview_item_changed` (una recalculación por punto, miles
        # de veces por archivo) durante la propia construcción -- en vano,
        # porque `fila["altura_wgs84"]` ya viene calculada correctamente
        # desde `previsualizar_dc()`. Se reactivan al final del método.
        tbl.blockSignals(True)
        tbl.setRowCount(len(self._import_preview))
        line_digits = int(self.spn_digitos_linea.value()) if hasattr(self, "spn_digitos_linea") else 0
        for row, fila in enumerate(self._import_preview):
            chk_item = QTableWidgetItem()
            ya_subido = fila.get("subido", False)
            flags = (chk_item.flags() | ITEM_IS_USER_CHECKABLE | ITEM_IS_SELECTABLE)
            flags &= ~ITEM_IS_EDITABLE
            if ya_subido:
                flags &= ~ITEM_IS_ENABLED
            else:
                flags |= ITEM_IS_ENABLED
            chk_item.setFlags(flags)
            chk_item.setCheckState(
                CHECK_STATE_CHECKED if (fila.get("incluir", True) and not ya_subido) else CHECK_STATE_UNCHECKED
            )
            tbl.setItem(row, PREVIEW_COL_INCLUDE, chk_item)

            self._set_preview_editable_cell(row, PREVIEW_COL_NOMBRE, fila["nombre"], ya_subido)
            if fila.get("ambiguous_reoccupation") or fila.get("deleted"):
                item_nombre = self.tbl_import_preview.item(row, PREVIEW_COL_NOMBRE)
                if item_nombre is not None:
                    item_nombre.setBackground(COLOR_AMBIGUO)

            # Station (value)/Track/Bin de GPSeismic: se recalculan acá,
            # a partir del NOMBRE ACTUAL (con cualquier prefijo "D"/"?"
            # que tenga -- ver la nota junto a `PREVIEW_COL_INCLUDE`), en
            # vez de usar directamente `fila["track"]`/`fila["bin"]` (que
            # se calcularon una sola vez, al parsear, a partir del nombre
            # ORIGINAL sin prefijo): así se reproduce exactamente el
            # comportamiento real de GPSeismic, confirmado contra la base
            # de datos POSTPLOT de referencia -- un nombre con prefijo
            # ("D51802277") no es puramente numérico, así que su Station
            # (value)/Track/Bin quedan en 0/0/0 en esa base de datos real
            # (fila 4), mientras que un nombre puramente numérico sí los
            # calcula con normalidad.
            station_value, track_calc, bin_calc = punto_nombre.derivados_de_nombre(fila["nombre"], line_digits)
            self._set_preview_readonly_cell(row, PREVIEW_COL_STATION_VALUE, station_value)
            self._set_preview_readonly_cell(row, PREVIEW_COL_TRACK, track_calc)
            self._set_preview_readonly_cell(row, PREVIEW_COL_BIN, bin_calc)

            self._set_preview_editable_cell(row, PREVIEW_COL_DESCRIPTOR, fila.get("descriptor") or "", ya_subido)

            # WGS84/Local Latitude-Longitude: GPSeismic muestra ambos
            # pares (columnas 6-9 de POSTPLOT) -- acá se asume, igual que
            # ya hace el resto del plugin al subir a POSTPLOT (ver
            # "Local_Height"/db_schema.py), que el datum local del
            # proyecto es WGS84, así que "Local" repite el mismo valor
            # que "WGS84" -- no una conversión de datum real (ninguno de
            # los 4 formatos soportados trae los parámetros de un datum
            # local distinto por punto). Con 12 decimales (antes 8), a
            # pedido explícito del usuario, para mostrar la precisión
            # completa que trae el archivo de origen -- confirmado contra
            # un '66KI'/'67SO' real de Trimble .dc: el campo de ancho fijo
            # de coordenadas (`_NUM_FIELD_WIDTH` en `dc_parser.py`) trae
            # exactamente 12 dígitos decimales (ej. "-37.096757440900"),
            # que con 8 decimales se venían truncando sin necesidad.
            self._set_preview_readonly_cell(row, PREVIEW_COL_LAT_WGS84, f"{fila['lat']:.12f}")
            self._set_preview_readonly_cell(row, PREVIEW_COL_LON_WGS84, f"{fila['lon']:.12f}")
            self._set_preview_readonly_cell(row, PREVIEW_COL_LAT_LOCAL, f"{fila['lat']:.12f}")
            self._set_preview_readonly_cell(row, PREVIEW_COL_LON_LOCAL, f"{fila['lon']:.12f}")

            # Coordenadas planas (Este/Norte) en el CRS de trabajo del
            # proyecto -- proyección automática pedida por el usuario en
            # la v2.25.0, reutilizando `_transform_xy` (el mismo mecanismo
            # que ya usa `_ejecutar_comparacion_preview` para comparar
            # contra PREPLOT, nunca antes usado para mostrar la
            # coordenada propia del punto en esta tabla).
            este, norte = _transform_xy(fila["lon"], fila["lat"], self.crs_wgs84, self._working_crs(), self.project)
            self._set_preview_readonly_cell(row, PREVIEW_COL_ESTE, f"{este:.3f}")
            self._set_preview_readonly_cell(row, PREVIEW_COL_NORTE, f"{norte:.3f}")

            self._set_preview_readonly_cell(row, PREVIEW_COL_ALTURA, f"{fila['altura_wgs84']:.3f}")

            # Scale Factor/Convergence: factor de escala puntual y
            # convergencia de meridiano de la proyección de trabajo en
            # este punto -- calculados desde la v2.58.0 (ver el
            # docstring de `_factor_escala_convergencia` para la
            # investigación completa que llevó a implementar esto, y
            # por qué NO afecta el cálculo de Este/Norte de arriba).
            # Quedan en "-" sólo si el CRS de trabajo es geográfico (sin
            # proyección) o si pyproj no pudo calcularlos por algún
            # motivo -- igual que siempre antes de la v2.58.0.
            factor_escala, convergencia = _factor_escala_convergencia(
                fila["lon"], fila["lat"], self._working_crs()
            )
            sf_text = "-" if factor_escala is None else f"{factor_escala:.8f}"
            conv_text = "-" if convergencia is None else f"{convergencia:.6f}"
            self._set_preview_readonly_cell(row, PREVIEW_COL_SCALE_FACTOR, sf_text)
            self._set_preview_readonly_cell(row, PREVIEW_COL_CONVERGENCE, conv_text)

            self._set_preview_editable_cell(
                row, PREVIEW_COL_SURVEY_MODE_TEXT, fila.get("survey_mode_text") or "", ya_subido,
            )
            self._set_preview_editable_cell(
                row, PREVIEW_COL_SURVEY_MODE_VALUE, fila.get("survey_mode_value") or "", ya_subido,
            )

            hi_text = "" if fila.get("hi") is None else f"{fila['hi']:.3f}"
            self._set_preview_editable_cell(row, PREVIEW_COL_HI, hi_text, ya_subido)

            # Offset North/East/Range/Bearing/Height: comparación real
            # posplot-vs-preplot, tomada del mismo `match` que ya calcula
            # `_ejecutar_comparacion_preview()` (ver `_render_preview_
            # match_cells` más abajo) -- North=delta_y, East=delta_x,
            # Height=delta_z (posplot menos preplot, mismo signo que ya
            # usa el resto del plugin, ver `csv_matcher._build_match`),
            # Range=distancia_2d, y Bearing=azimut (0-360, desde el norte)
            # del vector preplot->posplot. Sólo disponibles cuando hay un
            # PREPLOT cargado Y este punto matcheó contra uno -- si no,
            # "-", igual que ya hace la sección de comparación con
            # PREPLOT para esos mismos casos.
            #
            # Offset Inline/Crossline e Inline Azimuth de GPSeismic NO son
            # lo mismo que el Bearing de arriba: son la descomposición de
            # ese offset a lo largo/a través del rumbo de la línea sísmica
            # del proyecto. Confirmado contra el manual oficial de
            # GPSeismic (utilidad "Recalculate Offsets (crooked line)" de
            # GPSQL.chm, dentro de la propia instalación del programa):
            # ese rumbo sale de un archivo CRK generado por QuikLoad a
            # partir de la geometría de la línea de PREPLOT -- NO del
            # punto de campo individual (coincide con haber encontrado
            # "Inline Azimuth" como una constante, 0.70490003, en las 234
            # filas de la base de datos POSTPLOT real: esa línea era
            # recta). Como este plugin ya tiene esa misma geometría
            # (tabla PREPLOT del proyecto), se calcula aquí el rumbo de
            # cada línea/Track ajustando la mejor recta por sus puntos
            # (ver `_calcular_preplot_track_azimuths`/
            # `_fit_line_azimuth_deg`) en vez de depender de un archivo
            # CRK externo que este plugin todavía no puede cargar.
            # Desde la introducción del levantamiento 2D/3D del proyecto
            # (ver `_resolver_azimut_linea`), el azimut aplicado puede venir
            # del azimut FIJO de línea fuente/receptora configurado para un
            # proyecto 3D (clasificado por Descriptor) en vez de siempre
            # del ajuste por Track de PREPLOT -- misma fórmula de abajo sin
            # cambios, sólo cambia de dónde sale `inline_az`.
            m = fila.get("match")
            inline_az, _origen_az = self._resolver_azimut_linea(fila)
            if m is not None:
                offset_norte = m["delta_y"]
                offset_este = m["delta_x"]
                offset_altura = m.get("delta_z")
                bearing = math.degrees(math.atan2(offset_este, offset_norte)) % 360
                self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_NORTH, f"{offset_norte:.3f}")
                self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_EAST, f"{offset_este:.3f}")
                self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_RANGE, f"{m['distancia_2d']:.3f}")
                self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_BEARING, f"{bearing:.3f}")
                self._set_preview_readonly_cell(
                    row, PREVIEW_COL_OFFSET_HEIGHT, f"{offset_altura:.3f}" if offset_altura is not None else "-",
                )
                if inline_az is not None:
                    az_rad = math.radians(inline_az)
                    u_e, u_n = math.sin(az_rad), math.cos(az_rad)
                    inline = offset_este * u_e + offset_norte * u_n
                    crossline = offset_este * u_n - offset_norte * u_e
                    self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_INLINE, f"{inline:.3f}")
                    self._set_preview_readonly_cell(row, PREVIEW_COL_OFFSET_CROSSLINE, f"{crossline:.3f}")
                    self._set_preview_readonly_cell(row, PREVIEW_COL_INLINE_AZIMUTH, f"{inline_az:.3f}")
                else:
                    # No se pudo determinar el rumbo de esta línea (por
                    # ejemplo, la línea de PREPLOT sólo tiene un punto, o
                    # no hay PREPLOT cargado para este Track) -- "-" antes
                    # que inventar un rumbo.
                    for col in (PREVIEW_COL_OFFSET_INLINE, PREVIEW_COL_OFFSET_CROSSLINE, PREVIEW_COL_INLINE_AZIMUTH):
                        self._set_preview_readonly_cell(row, col, "-")
            else:
                for col in (
                    PREVIEW_COL_OFFSET_NORTH, PREVIEW_COL_OFFSET_EAST, PREVIEW_COL_OFFSET_RANGE,
                    PREVIEW_COL_OFFSET_BEARING, PREVIEW_COL_OFFSET_HEIGHT,
                    PREVIEW_COL_OFFSET_INLINE, PREVIEW_COL_OFFSET_CROSSLINE, PREVIEW_COL_INLINE_AZIMUTH,
                ):
                    self._set_preview_readonly_cell(row, col, "-")

            # Precisión Hor/Ver 95% y CQ: re-revisado de nuevo a pedido
            # explícito del usuario ("lo necesitamos por control de
            # calidad de la presicion del punto tomado en campo"), que
            # además corrigió una conclusión equivocada de la ronda
            # anterior: el 'C6NM' en efecto no trae estos datos, pero SÍ
            # los trae el '60NM' que lo sigue inmediatamente -- hasta esta
            # ronda tratado como un código auxiliar opaco (ver
            # `KNOWN_AUX_CODES` en dc_parser.py), ahora decodificado por
            # completo. Ver el docstring de `_parse_60nm_precision` en
            # dc_parser.py para la fórmula (DRMS al 95% a partir de las
            # desviaciones estándar Norte/Este/Altura que trae ese
            # registro) y su verificación completa contra 436 puntos
            # reales de 2 archivos independientes (error absoluto máximo
            # ±0.0005, del orden del ruido de redondeo float32 ya visto en
            # otros campos). `None` sólo para un punto sin '60NM' asociado
            # (KI, is_base, o una ocupación descartada en campo).
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_HOR_PRECISION,
                f"{fila['hor_precision_95']:.3f}" if fila.get("hor_precision_95") is not None else "-",
            )
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_VER_PRECISION,
                f"{fila['ver_precision_95']:.3f}" if fila.get("ver_precision_95") is not None else "-",
            )
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_CQ,
                f"{fila['cq']:.3f}" if fila.get("cq") is not None else "-",
            )

            self._set_preview_readonly_cell(row, PREVIEW_COL_N_SATS, fila.get("n_sats") if fila.get("n_sats") is not None else "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_PDOP, f"{fila['pdop']:.2f}" if fila.get("pdop") is not None else "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_HDOP, f"{fila['hdop']:.2f}" if fila.get("hdop") is not None else "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_VDOP, f"{fila['vdop']:.2f}" if fila.get("vdop") is not None else "-")

            # Julian Date (Local) = año + día del año (3 dígitos) de la
            # fecha del archivo (`fila["julian_date_local"]`, armado más
            # abajo a partir de `DCFile.date_text` -- el primer '13TS' del
            # archivo -- para DC; ver la nota junto a esa clave). Populate
            # Time es simplemente el momento ACTUAL (se calcula cuando se
            # genera esta previsualización, igual que hace
            # `subir_dc_preview()` al subir de verdad).
            jd = fila.get("julian_date_local")
            self._set_preview_readonly_cell(row, PREVIEW_COL_JULIAN_DATE, jd if jd else "-")
            # Serial Time (GPS): desde esta ronda, Trimble .dc SÍ completa
            # este dato -- pero sólo para la semana de trabajo real del
            # archivo (según su propio '13TS') si ya está calibrada en
            # `dc_parser._GMT_WEEK_CALIBRATION` (ver el docstring completo
            # ahí y en `dc_parser._calibrar_horas_gps`: la constante K de
            # este dato no es universal, salta en cada reinicio real del
            # receptor). `fila.get("serial_time_gps")` ya viene en `None`
            # para cualquier semana sin calibrar -- se muestra "-" en ese
            # caso, igual que antes de esta ronda.
            serial_gps = fila.get("serial_time_gps")
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_SERIAL_TIME_GPS, f"{serial_gps:.0f}" if serial_gps is not None else "-",
            )
            # Elapsed Time: desde esta ronda SÍ se completa para Trimble
            # .dc (pedido explícito del usuario) -- aunque el contador de
            # sesión de 'C6NM' no se pueda convertir a una hora real (ver
            # arriba), la DIFERENCIA entre el primer epoch de dos puntos
            # 'SO' consecutivos sigue siendo una duración real y
            # verificable (ver `DCPoint.elapsed_seconds`, calculado por
            # `dc_parser.parse_dc_text`). Se muestra en segundos, en
            # segundos enteros -- consistente con el tipo INT de la
            # columna `Elapsed_Time` en POSTPLOT.
            elapsed = fila.get("elapsed_seconds")
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_ELAPSED_TIME, f"{elapsed:.0f}" if elapsed is not None else "-",
            )
            self._set_preview_readonly_cell(row, PREVIEW_COL_POPULATE_TIME, datetime.now().strftime("%m/%d/%y %H:%M:%S"))

            # Survey Time (Local/GMT): sólo Stonex trae fecha/hora real y
            # absoluta por punto (ver `p.survey_time_local`/`_gmt` en
            # previsualizar_dc); CHCNav trae un texto de sesión sin
            # interpretar como Survey Time (Local) únicamente. El resto
            # queda en "-".
            self._set_preview_readonly_cell(row, PREVIEW_COL_SURVEY_TIME_LOCAL, fila.get("survey_time_local") or "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_SURVEY_TIME_GMT, fila.get("survey_time_gmt") or "-")

            self._set_preview_readonly_cell(row, PREVIEW_COL_LOCAL_DATUM, self.t("col_local_datum_wgs84"))
            self._set_preview_readonly_cell(row, PREVIEW_COL_LOCAL_SYSTEM, self._working_crs().description() or "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_DISTANCE_UNITS, self.t("col_distance_units_meter"))
            self._set_preview_readonly_cell(row, PREVIEW_COL_DISTANCE_FACTOR, "1")

            self._set_preview_editable_cell(row, PREVIEW_COL_COMENTARIO, fila.get("comentario") or "", ya_subido)

            self._set_preview_readonly_cell(row, PREVIEW_COL_DOWNLOAD_FILE, fila["archivo"])
            self._set_preview_readonly_cell(row, PREVIEW_COL_JOB_NAME, fila.get("job_name") or "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_RECEIVER_TYPE, fila.get("receiver_type") or "-")
            self._set_preview_readonly_cell(row, PREVIEW_COL_RECEIVER_SN, fila.get("receiver_sn") or "-")

            # GDOP: descubierto en esta ronda, al reparar la lectura de
            # "épocas promediadas" del 'C6NM' (ver el docstring de
            # `_parse_c6nm_quality` en dc_parser.py) -- coincide EXACTO
            # con esa cantidad de épocas, no con ninguna fórmula
            # geométrica de dilución de precisión (se probó la fórmula
            # sqrt(PDOP²+TDOP²) que se suele usar para GDOP, pero no hay
            # ningún campo de TDOP en este formato de .dc, y la cantidad
            # de épocas coincide exacta -- 228 de 229 puntos verificables
            # de ar180118.dsc, la única excepción una reocupación ambigua
            # que ya se explica en otra parte -- así que se usa ese valor
            # tal cual). Unit Variance/Init Block/Station Deltas/
            # Consecutive Intervals/Consecutive Azimuths/Reserved: sin
            # ningún dato equivalente confirmado en ninguno de los 4
            # formatos soportados -- "-".
            n_epochs = fila.get("n_epochs")
            self._set_preview_readonly_cell(row, PREVIEW_COL_GDOP, n_epochs if n_epochs is not None else "-")
            for col in (
                PREVIEW_COL_UNIT_VARIANCE, PREVIEW_COL_INIT_BLOCK,
                PREVIEW_COL_STATION_DELTAS, PREVIEW_COL_CONSECUTIVE_INTERVALS,
                PREVIEW_COL_CONSECUTIVE_AZIMUTHS, PREVIEW_COL_RESERVED,
            ):
                self._set_preview_readonly_cell(row, col, "-")

            gps_baseline = fila.get("gps_baseline_m")
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_GPS_BASELINE, f"{gps_baseline:.3f}" if gps_baseline is not None else "-",
            )
            self._set_preview_readonly_cell(row, PREVIEW_COL_GPS_BASE_STATION, fila.get("gps_base_station") or "-")
            occ = fila.get("occupation_seconds")
            self._set_preview_readonly_cell(row, PREVIEW_COL_OCCUPATION_TIME, f"{occ:.0f}" if occ is not None else "-")

            self._set_preview_readonly_cell(row, PREVIEW_COL_RECNUM, row + 1)

            # Elevación ortométrica: columna EXTRA (no es de GPSeismic),
            # movida a propósito junto a "Alt. WGS84 (m)" -- ver la nota
            # completa junto a `PREVIEW_COL_INCLUDE`.
            local_h = fila.get("local_h")
            self._set_preview_readonly_cell(
                row, PREVIEW_COL_ORTOMETRICA, f"{local_h:.3f}" if local_h is not None else "-",
            )

            # -- fin de las 58 columnas de GPSeismic -- columnas extra
            # propias del plugin, ya existentes antes de esta ronda. Nota:
            # "Calidad" (`fila.get("calidad")`) se quitó de esta tabla a
            # pedido explícito del usuario -- sigue calculándose y
            # usándose para la capa de puntos del mapa, el filtro SQL de
            # la previsualización y la exportación a CSV/Shapefile/
            # GeoPackage (ver `_render_preview_match_cells` más abajo y
            # las notas junto a `PREVIEW_COL_INCLUDE`).
            self._set_preview_readonly_cell(row, PREVIEW_COL_TIPO, fila["tipo"])
            self._set_preview_readonly_cell(row, PREVIEW_COL_ARCHIVO, fila["archivo"])
            self._set_preview_readonly_cell(row, PREVIEW_COL_SURVEYOR, self._surveyor_de_fila(fila) or "-")

            self._render_preview_match_cells(row, fila)

        tbl.blockSignals(False)
        tbl.resizeColumnsToContents()
        # Reaplica el resaltado del filtro/consulta actual (si hay uno):
        # esta función siempre reconstruye la tabla entera desde cero, así
        # que cualquier resaltado puesto antes en el encabezado vertical se
        # habría perdido si no se repite acá (ver `_resaltar_filas_filtro_preview`).
        self._resaltar_filas_filtro_preview()
        self._resaltar_filas_duplicadas_bd()
        self._render_import_preview_summary()

    def _retranslate_tabla_preview(self):
        if not hasattr(self, "tbl_import_preview"):
            return
        self.tbl_import_preview.setHorizontalHeaderLabels(self._import_preview_headers())
        for row in range(min(self.tbl_import_preview.rowCount(), len(self._import_preview))):
            self._render_preview_match_cells(row, self._import_preview[row])
        self._render_import_preview_summary()

    def _render_import_preview_summary(self):
        if not hasattr(self, "lbl_preview_resumen"):
            return
        # La cabecera del acordeón PREPLOT muestra si la comparación está
        # activa (hay PREPLOT) -- se refresca junto con el resumen.
        self._actualizar_resumen_acordeones()
        if self._last_import_preview_summary is None:
            self.lbl_preview_resumen.setText("")
            return
        n, matched, within, had_preplot = self._last_import_preview_summary
        if had_preplot:
            self.lbl_preview_resumen.setText(self.t("lbl_preview_summary", n=n, matched=matched, within=within))
        else:
            self.lbl_preview_resumen.setText(self.t("lbl_preview_summary_no_preplot", n=n))

    # -- Consulta/filtro SQL de la previsualización (`grp_preview_query`,
    # ver la nota junto a su construcción en `_build_tab_importar`) --------

    def _construir_conexion_preview_sqlite(self):
        """Arma una base SQLite EN MEMORIA (nunca se guarda en disco, se
        descarta al terminar de usarla) con una tabla PREVIEW a partir de
        `self._import_preview`, para poder filtrar la previsualización con
        SQL de verdad -- pedido explícito del usuario, con las mismas
        herramientas (consulta SQL) que ya tiene "Base de Datos", pero
        SEPARADA de `self.conn` (la base de datos real del proyecto):
        nunca se escribe nada acá, y esta tabla desaparece apenas se
        cierra la conexión.

        La columna "id" guarda el ÍNDICE ORIGINAL dentro de
        `self._import_preview` (0-based) -- es la única forma en que el
        resto de esta funcionalidad (resaltar filas, marcar Incluir,
        mostrar en el mapa, exportar) puede volver de "qué filas cumplen
        la consulta" a "qué elementos de la lista son esos" SIN tocar
        jamás el orden de `tbl_import_preview` (por diseño: esa tabla
        nunca se reordena, ver la nota junto a `grp_preview_query`)."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE PREVIEW ("
            "id INTEGER PRIMARY KEY, nombre TEXT, track INTEGER, bin INTEGER, "
            "descriptor TEXT, lat REAL, lon REAL, este REAL, norte REAL, "
            "altura REAL, hi REAL, comentario TEXT, tipo TEXT, calidad TEXT, "
            "survey_mode_text TEXT, survey_mode_value TEXT, "
            "incluir INTEGER, subido INTEGER, archivo TEXT, estado TEXT, surveyor TEXT"
            ")"
        )
        dest_crs = self._working_crs()
        filas_sql = []
        for idx, fila in enumerate(self._import_preview):
            try:
                este, norte = _transform_xy(fila["lon"], fila["lat"], self.crs_wgs84, dest_crs, self.project)
            except Exception:
                este, norte = None, None
            if fila.get("subido"):
                estado = "subido"
            else:
                m = fila.get("match")
                if m is None:
                    estado = "sin_match"
                elif m.get("dentro_tolerancia"):
                    estado = "dentro_tolerancia"
                else:
                    estado = "fuera_tolerancia"
            filas_sql.append((
                idx, fila.get("nombre"), fila.get("track"), fila.get("bin"),
                fila.get("descriptor") or "", fila.get("lat"), fila.get("lon"),
                este, norte, fila.get("altura_wgs84"),
                fila.get("hi"), fila.get("comentario") or "", fila.get("tipo") or "",
                fila.get("calidad") or "", fila.get("survey_mode_text") or "",
                fila.get("survey_mode_value") or "",
                1 if fila.get("incluir", True) else 0,
                1 if fila.get("subido") else 0,
                fila.get("archivo") or "", estado,
                self._surveyor_de_fila(fila),
            ))
        conn.executemany(
            "INSERT INTO PREVIEW (id, nombre, track, bin, descriptor, lat, lon, este, norte, "
            "altura, hi, comentario, tipo, calidad, survey_mode_text, survey_mode_value, "
            "incluir, subido, archivo, estado, surveyor) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            filas_sql,
        )
        conn.commit()
        return conn

    # -- Filtros predeterminados + asistente de la sección "Consultar /
    # filtrar antes de subir" (v2.60.0, pedido explícito del usuario:
    # mismo mecanismo de "Base de Datos" -- ver `_PREVIEW_FILTER_PRESET_ORDER`
    # más arriba). Elegir un preset o agregar una condición con el
    # asistente sólo llena `self.txt_filtro_preview`; sigue haciendo
    # falta apretar "Filtrar" para aplicarlo, igual que si se hubiera
    # escrito el SQL a mano.

    def _load_custom_preview_filters(self):
        settings = QSettings()
        raw = settings.value(_SETTINGS_KEY_PREVIEW_FILTER_CUSTOM, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [q for q in data if isinstance(q, dict) and q.get("name") and "sql" in q]

    def _save_custom_preview_filters(self, filtros):
        settings = QSettings()
        settings.setValue(_SETTINGS_KEY_PREVIEW_FILTER_CUSTOM, json.dumps(filtros))

    def _fill_preview_filter_preset_combo(self, keep_selection=False):
        current_data = self.cb_preview_filter_preset.currentData() if (keep_selection and self.cb_preview_filter_preset.count()) else "custom"
        self.cb_preview_filter_preset.blockSignals(True)
        self.cb_preview_filter_preset.clear()
        for key in self._PREVIEW_FILTER_PRESET_ORDER:
            self.cb_preview_filter_preset.addItem(self.t(self._PREVIEW_FILTER_PRESET_LABELS[key]), key)
        for q in self._load_custom_preview_filters():
            self.cb_preview_filter_preset.addItem(q["name"], f"custom_filter:{q['name']}")
        idx = self.cb_preview_filter_preset.findData(current_data)
        self.cb_preview_filter_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_preview_filter_preset.blockSignals(False)

    def _fill_filtro_wizard_combos(self, keep_selection=False):
        col_actual = self.cb_filtro_wizard_columna.currentData() if (keep_selection and self.cb_filtro_wizard_columna.count()) else None
        self.cb_filtro_wizard_columna.blockSignals(True)
        self.cb_filtro_wizard_columna.clear()
        for key, label_key, _tipo in self._PREVIEW_FILTER_COLUMNS:
            self.cb_filtro_wizard_columna.addItem(self.t(label_key), key)
        idx_col = self.cb_filtro_wizard_columna.findData(col_actual)
        self.cb_filtro_wizard_columna.setCurrentIndex(idx_col if idx_col >= 0 else 0)
        self.cb_filtro_wizard_columna.blockSignals(False)

        op_actual = self.cb_filtro_wizard_operador.currentData() if (keep_selection and self.cb_filtro_wizard_operador.count()) else None
        self.cb_filtro_wizard_operador.blockSignals(True)
        self.cb_filtro_wizard_operador.clear()
        for key, label_key in self._PREVIEW_FILTER_OPERATORS:
            self.cb_filtro_wizard_operador.addItem(self.t(label_key), key)
        idx_op = self.cb_filtro_wizard_operador.findData(op_actual)
        self.cb_filtro_wizard_operador.setCurrentIndex(idx_op if idx_op >= 0 else 0)
        self.cb_filtro_wizard_operador.blockSignals(False)

        con_actual = self.cb_filtro_wizard_conector.currentData() if (keep_selection and self.cb_filtro_wizard_conector.count()) else None
        self.cb_filtro_wizard_conector.blockSignals(True)
        self.cb_filtro_wizard_conector.clear()
        self.cb_filtro_wizard_conector.addItem(self.t("opt_filtro_wizard_and"), "AND")
        self.cb_filtro_wizard_conector.addItem(self.t("opt_filtro_wizard_or"), "OR")
        idx_con = self.cb_filtro_wizard_conector.findData(con_actual)
        self.cb_filtro_wizard_conector.setCurrentIndex(idx_con if idx_con >= 0 else 0)
        self.cb_filtro_wizard_conector.blockSignals(False)

    def _aplicar_preset_filtro_preview(self, index):
        key = self.cb_preview_filter_preset.itemData(index)
        if not key:
            return
        if isinstance(key, str) and key.startswith("custom_filter:"):
            nombre = key[len("custom_filter:"):]
            for q in self._load_custom_preview_filters():
                if q["name"] == nombre:
                    self.txt_filtro_preview.setText(q["sql"])
                    break
            return
        sql = self._PREVIEW_FILTER_PRESET_SQL.get(key)
        if sql:
            self.txt_filtro_preview.setText(sql)

    def _construir_condicion_wizard(self):
        """Arma un fragmento de SQL a partir de lo elegido en el
        asistente (columna + condición + valor), sin que el usuario
        tenga que escribir SQL. Devuelve `None` si falta un valor donde
        hace falta uno, o si el valor no es numérico para una columna
        numérica -- en ambos casos `_agregar_condicion_filtro_preview`
        avisa con un mensaje en vez de agregar una condición rota."""
        col_key = self.cb_filtro_wizard_columna.currentData()
        op_key = self.cb_filtro_wizard_operador.currentData()
        columnas_por_clave = {k: t for k, _lbl, t in self._PREVIEW_FILTER_COLUMNS}
        tipo = columnas_por_clave.get(col_key, "text")
        valor = self.txt_filtro_wizard_valor.text().strip()

        if op_key == "vacio":
            if tipo == "text":
                return f"({col_key} IS NULL OR {col_key} = '')"
            return f"{col_key} IS NULL"
        if op_key == "no_vacio":
            if tipo == "text":
                return f"({col_key} IS NOT NULL AND {col_key} != '')"
            return f"{col_key} IS NOT NULL"

        if not valor:
            return None

        if op_key in ("contiene", "no_contiene"):
            valor_escapado = valor.replace("'", "''")
            condicion_like = f"{col_key} LIKE '%{valor_escapado}%'"
            return condicion_like if op_key == "contiene" else f"NOT {condicion_like}"

        simbolos = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}
        simbolo = simbolos.get(op_key)
        if simbolo is None:
            return None

        if tipo == "num":
            try:
                float(valor)
            except ValueError:
                return None
            return f"{col_key} {simbolo} {valor}"

        valor_escapado = valor.replace("'", "''")
        return f"{col_key} {simbolo} '{valor_escapado}'"

    def _agregar_condicion_filtro_preview(self):
        condicion_nueva = self._construir_condicion_wizard()
        if condicion_nueva is None:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_filtro_wizard_valor_invalido"))
            return
        actual = self.txt_filtro_preview.text().strip()
        if not actual:
            self.txt_filtro_preview.setText(condicion_nueva)
        else:
            conector = self.cb_filtro_wizard_conector.currentData()
            self.txt_filtro_preview.setText(f"({actual}) {conector} ({condicion_nueva})")
        self.txt_filtro_wizard_valor.clear()
        idx_custom = self.cb_preview_filter_preset.findData("custom")
        if idx_custom >= 0:
            self.cb_preview_filter_preset.blockSignals(True)
            self.cb_preview_filter_preset.setCurrentIndex(idx_custom)
            self.cb_preview_filter_preset.blockSignals(False)

    def guardar_filtro_preview_actual(self):
        """Botón "Guardar filtro...": mismo comportamiento que
        `guardar_consulta_actual` de "Base de Datos" pero para la
        condición de filtro de esta sección -- si el combo tiene
        seleccionado un filtro propio ya guardado, ofrece sobrescribirlo
        o guardar aparte con un nombre nuevo; si no (preset de fábrica o
        "Personalizado"), sólo tiene sentido guardarlo como nuevo."""
        condicion_actual = self.txt_filtro_preview.text().strip()
        if not condicion_actual:
            QMessageBox.information(self, self.t("info_empty_filter_title"), self.t("info_empty_filter_body"))
            return

        key = self.cb_preview_filter_preset.currentData()
        es_filtro_guardado = isinstance(key, str) and key.startswith("custom_filter:")

        if not es_filtro_guardado:
            self._guardar_filtro_preview_como_nuevo(condicion_actual)
            return

        nombre_actual = key[len("custom_filter:"):]
        box = QMessageBox(self)
        box.setWindowTitle(self.t("dlg_save_filter_title"))
        box.setText(self.t("dlg_save_filter_overwrite_body", nombre=nombre_actual))
        btn_overwrite = box.addButton(self.t("btn_save_filter_overwrite", nombre=nombre_actual), MSG_ROLE_ACTION)
        btn_new = box.addButton(self.t("btn_save_filter_as_new"), MSG_ROLE_ACTION)
        box.addButton(MSG_CANCEL)
        box.setDefaultButton(btn_overwrite)
        box.exec()
        clicked = box.clickedButton()

        if clicked is btn_overwrite:
            filtros = self._load_custom_preview_filters()
            for q in filtros:
                if q["name"] == nombre_actual:
                    q["sql"] = condicion_actual
                    break
            self._save_custom_preview_filters(filtros)
            QMessageBox.information(
                self, self.t("dlg_save_filter_title"),
                self.t("info_filter_saved_body", nombre=nombre_actual),
            )
        elif clicked is btn_new:
            self._guardar_filtro_preview_como_nuevo(condicion_actual)
        # Si se cancela, no se toca nada.

    def _guardar_filtro_preview_como_nuevo(self, condicion):
        nombre, ok = QInputDialog.getText(
            self, self.t("dlg_save_filter_title"), self.t("dlg_save_filter_name_label")
        )
        if not ok:
            return
        nombre = nombre.strip()
        if not nombre:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_filter_name_invalid"))
            return
        if nombre in [self.t(self._PREVIEW_FILTER_PRESET_LABELS[k]) for k in self._PREVIEW_FILTER_PRESET_ORDER]:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_filter_name_reserved"))
            return

        filtros = self._load_custom_preview_filters()
        ya_existe = any(q["name"] == nombre for q in filtros)
        if ya_existe:
            resp = QMessageBox.question(
                self, self.t("confirm_overwrite_title"),
                self.t("confirm_filter_overwrite_body", nombre=nombre),
            )
            if resp not in (MSG_YES,):
                return
            for q in filtros:
                if q["name"] == nombre:
                    q["sql"] = condicion
                    break
        else:
            filtros.append({"name": nombre, "sql": condicion})

        self._save_custom_preview_filters(filtros)
        self._fill_preview_filter_preset_combo(keep_selection=False)
        idx = self.cb_preview_filter_preset.findData(f"custom_filter:{nombre}")
        if idx >= 0:
            self.cb_preview_filter_preset.blockSignals(True)
            self.cb_preview_filter_preset.setCurrentIndex(idx)
            self.cb_preview_filter_preset.blockSignals(False)
        QMessageBox.information(
            self, self.t("dlg_save_filter_title"),
            self.t("info_filter_saved_body", nombre=nombre),
        )

    def _ejecutar_filtro_preview(self):
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        condicion = self.txt_filtro_preview.text().strip()
        if not condicion:
            self._quitar_filtro_preview()
            return
        # Sincroniza ediciones sin guardar de la tabla antes de armar la
        # tabla SQLite en memoria -- si no, una consulta sobre "comentario"
        # o "hi", por ejemplo, ignoraría lo que el usuario acaba de
        # escribir y todavía no se movió a `self._import_preview`.
        self._sync_preview_edits_desde_tabla()
        conn = self._construir_conexion_preview_sqlite()
        try:
            # `PREVIEW` es una tabla SQLite efímera en memoria armada por el propio plugin a partir de la previsualización (nunca se guarda en disco); `condicion` es el filtro que el propio usuario escribe para FILTRAR sus propios datos ya cargados, sin frontera de confianza de por medio
            cur = conn.execute(f"SELECT id FROM PREVIEW WHERE {condicion}")  # nosec B608
            ids = {row[0] for row in cur.fetchall()}
        except sqlite3.Error as e:
            QMessageBox.warning(self, self.t("warn_invalid_query_title"), self.t("warn_invalid_query_body", error=e))
            return
        finally:
            conn.close()
        self._preview_filtro_ids = ids
        self._resaltar_filas_filtro_preview()
        self.lbl_filtro_preview_resumen.setText(
            self.t("lbl_preview_filter_summary", n=len(ids), total=len(self._import_preview))
        )

    def _quitar_filtro_preview(self):
        self._preview_filtro_ids = None
        self.txt_filtro_preview.clear()
        self._resaltar_filas_filtro_preview()
        self.lbl_filtro_preview_resumen.setText("")

    def _resaltar_filas_filtro_preview(self):
        """Resalta (o limpia el resaltado de) las filas que cumplen el
        filtro actual usando el ENCABEZADO VERTICAL de cada fila (el
        número a la izquierda), nunca el fondo de las celdas -- así no se
        pisa COLOR_AMBIGUO/COLOR_YA_SUBIDO (celda Nombre) ni COLOR_DENTRO/
        COLOR_FUERA (celda Estado, ver `_render_preview_match_cells`).
        Se llama tanto al aplicar/quitar el filtro como al final de
        `_llenar_tabla_preview()` (que reconstruye la tabla entera y
        perdería cualquier resaltado puesto antes)."""
        if not hasattr(self, "tbl_import_preview"):
            return
        tbl = self.tbl_import_preview
        ids = self._preview_filtro_ids
        for row in range(tbl.rowCount()):
            header_item = tbl.verticalHeaderItem(row)
            if header_item is None:
                header_item = QTableWidgetItem(str(row + 1))
                tbl.setVerticalHeaderItem(row, header_item)
            resaltar = ids is not None and row in ids
            header_item.setBackground(COLOR_FILTRO_PREVIEW if resaltar else QBrush())
            font = header_item.font()
            font.setBold(resaltar)
            header_item.setFont(font)

    # -- Verificar duplicados contra POSTPLOT (pedido explícito del usuario:
    # antes de subir, avisar si un punto de la previsualización ya existe en
    # la base de datos por su nombre) -------------------------------------

    def _nombres_postplot_existentes(self, nombres) -> set:
        """Devuelve, en mayúsculas, el subconjunto de `nombres` (Station_
        Text) que ya existen en la tabla POSTPLOT del proyecto abierto.
        Comparación insensible a mayúsculas/minúsculas, igual que la
        columna real (`Station_Text TEXT COLLATE NOCASE`, ver
        `db_schema.py`). Corre en tandas de a lo sumo 500 nombres por
        consulta para no superar el límite de parámetros por sentencia de
        SQLite en una tabla con muchos puntos."""
        if self.conn is None:
            return set()
        nombres_unicos = sorted({str(n).strip() for n in nombres if n and str(n).strip()})
        if not nombres_unicos:
            return set()
        encontrados = set()
        cur = self.conn.cursor()
        TANDA = 500
        for i in range(0, len(nombres_unicos), TANDA):
            tanda = nombres_unicos[i:i + TANDA]
            placeholders = ", ".join("?" for _ in tanda)
            cur.execute(
                # tabla fija ("POSTPLOT"), `tanda` siempre va bindeada como parámetros
                f"SELECT DISTINCT Station_Text FROM POSTPLOT WHERE Station_Text IN ({placeholders})", tanda,  # nosec B608
            )
            encontrados.update(str(r[0]).strip().upper() for r in cur.fetchall() if r[0] is not None)
        return encontrados

    def verificar_duplicados_bd(self):
        """Botón "Verificar duplicados en la base de datos": compara cada
        punto de la previsualización (que todavía no se subió en esta
        misma sesión, ver `fila["subido"]`) contra los Station_Text que ya
        existen en POSTPLOT, por nombre. Los que ya existen se marcan
        (`fila["duplicado_bd"] = True`), se desmarca su casilla "Incluir"
        (para que no se suban de nuevo sin querer al presionar "Subir a
        POSTPLOT") y se resaltan en rojo -- fila completa, no sólo una
        celda, ver `_resaltar_filas_duplicadas_bd` -- para que sean
        imposibles de pasar por alto. La casilla "Incluir" queda editable
        (no bloqueada como con un punto ya subido EN ESTA sesión): es una
        advertencia, no un candado -- si el usuario de verdad quiere
        volver a subir un punto con ese nombre (por ejemplo, una
        reocupación intencional), puede volver a marcarla a mano."""
        if not self._require_project():
            return
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_upload_title"), self.t("info_nothing_to_upload_body"))
            return

        self._sync_preview_edits_desde_tabla()

        for f in self._import_preview:
            f["duplicado_bd"] = False

        candidatos = [f for f in self._import_preview if not f.get("subido") and (f.get("nombre") or "").strip()]
        existentes = self._nombres_postplot_existentes(f["nombre"] for f in candidatos)

        n_marcados = 0
        for f in candidatos:
            if f["nombre"].strip().upper() in existentes:
                f["duplicado_bd"] = True
                f["incluir"] = False
                n_marcados += 1

        self._llenar_tabla_preview()

        if n_marcados:
            QMessageBox.warning(
                self, self.t("warn_duplicates_found_title"),
                self.t("warn_duplicates_found_body", n=n_marcados),
            )
        else:
            QMessageBox.information(self, self.t("info_no_duplicates_title"), self.t("info_no_duplicates_body"))

    def _resaltar_filas_duplicadas_bd(self):
        """Pinta de rojo TODAS las columnas (no sólo Nombre/Estado como el
        resto de los resaltados de esta tabla) de cada fila marcada por
        `verificar_duplicados_bd` como ya existente en POSTPLOT -- a
        propósito por encima de cualquier otro color de celda que ya
        tuviera esa fila (tolerancia/ambiguo/ya subido): un duplicado real
        contra la base ya guardada es la señal más importante de las tres.
        Se llama al final de `_llenar_tabla_preview()`, que reconstruye la
        tabla entera y perdería cualquier resaltado puesto antes."""
        if not hasattr(self, "tbl_import_preview"):
            return
        tbl = self.tbl_import_preview
        for row, fila in enumerate(self._import_preview):
            if not fila.get("duplicado_bd"):
                continue
            for col in range(tbl.columnCount()):
                item = tbl.item(row, col)
                if item is not None:
                    item.setBackground(COLOR_DUPLICADO_BD)

    def _filas_preview_filtradas(self):
        """Devuelve la lista de filas de `self._import_preview` que hay
        que usar para "marcar Incluir"/"mostrar en el mapa"/"exportar":
        el subconjunto filtrado si hay un filtro activo, o todas si no."""
        if self._preview_filtro_ids is None:
            return list(self._import_preview)
        return [f for i, f in enumerate(self._import_preview) if i in self._preview_filtro_ids]

    def _marcar_incluir_filtrados(self, valor: bool):
        if not self._import_preview:
            return
        self._sync_preview_edits_desde_tabla()
        filas = self._filas_preview_filtradas()
        if not filas:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        n_cambiadas = 0
        for fila in filas:
            if fila.get("subido"):
                continue
            fila["incluir"] = valor
            n_cambiadas += 1
        self._llenar_tabla_preview()
        self.log_importar.appendPlainText(
            self.t("log_preview_filter_marked_on" if valor else "log_preview_filter_marked_off", n=n_cambiadas)
        )

    def _mostrar_filtro_preview_en_mapa(self):
        """Crea/reemplaza una capa de memoria PROVISIONAL SEPARADA de la
        que ya crea `_actualizar_capa_provisional_preview()` (que siempre
        muestra TODOS los puntos de la previsualización) -- ésta muestra
        sólo el subconjunto que cumple el filtro/consulta actual (o todos,
        si no hay ningún filtro aplicado), con más atributos inspeccionables
        (nombre, tipo, calidad, comentario, incluir, estado), modelada en
        `_crear_capa_puntos_dc`."""
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        self._sync_preview_edits_desde_tabla()
        filas = self._filas_preview_filtradas()
        if not filas:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return

        capa_vieja = self._filtro_preview_layer
        if capa_vieja is not None:
            try:
                if QgsProject.instance().mapLayer(capa_vieja.id()) is not None:
                    self.project.removeMapLayer(capa_vieja.id())
            except RuntimeError:
                pass
            self._filtro_preview_layer = None

        layer = QgsVectorLayer("Point?crs=EPSG:4326", self.t("layer_preview_filtro"), "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("tipo", FIELD_STRING),
            QgsField("calidad", FIELD_STRING),
            QgsField("comentario", FIELD_STRING),
            QgsField("incluir", FIELD_STRING),
            QgsField("estado", FIELD_STRING),
            QgsField("altura", FIELD_DOUBLE),
        ])
        layer.updateFields()

        feats = []
        tipos_presentes = set()
        for fila in filas:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(fila["lon"], fila["lat"])))
            estado = self.t("status_already_uploaded") if fila.get("subido") else (
                self.t("status_within_tolerance") if fila.get("match") and fila["match"].get("dentro_tolerancia")
                else self.t("status_outside_tolerance") if fila.get("match")
                else self.t("status_no_preplot_match")
            )
            f.setAttributes([
                fila["nombre"], fila["tipo"], fila.get("calidad") or "",
                fila.get("comentario") or "", "1" if fila.get("incluir", True) else "0",
                estado, fila["altura_wgs84"],
            ])
            feats.append(f)
            tipos_presentes.add(fila["tipo"])
        prov.addFeatures(feats)
        layer.updateExtents()

        orden = sorted(tipos_presentes, key=lambda t: list(COLOR_POR_TIPO).index(t) if t in COLOR_POR_TIPO else 999)
        self._aplicar_estilo_por_tipo(layer, orden)
        self.project.addMapLayer(layer)
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)
        self._filtro_preview_layer = layer

    def _fill_export_preview_format_combo(self, keep_selection=False):
        """Repuebla `cb_export_preview_formato` -- mismo patrón que
        `_fill_export_format_combo` de "Base de Datos", pero con
        `_PREVIEW_EXPORT_FORMAT_ORDER` (sin SPS, ver su nota)."""
        if not hasattr(self, "cb_export_preview_formato"):
            return
        current_data = self.cb_export_preview_formato.currentData() if (keep_selection and self.cb_export_preview_formato.count()) else "shapefile"
        self.cb_export_preview_formato.blockSignals(True)
        self.cb_export_preview_formato.clear()
        for key in self._PREVIEW_EXPORT_FORMAT_ORDER:
            self.cb_export_preview_formato.addItem(self.t(self._EXPORT_FORMAT_LABELS[key]), key)
        idx = self.cb_export_preview_formato.findData(current_data)
        self.cb_export_preview_formato.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_export_preview_formato.blockSignals(False)

    def _exportar_preview_actual(self):
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        self._sync_preview_edits_desde_tabla()
        filas = self._filas_preview_filtradas()
        if not filas:
            QMessageBox.information(self, self.t("info_nothing_to_import_title"), self.t("info_nothing_to_import_body"))
            return
        formato = self.cb_export_preview_formato.currentData()
        if not formato:
            return
        if formato == "csv":
            self._exportar_preview_csv(filas)
        else:
            self._exportar_preview_ogr(filas, formato)

    def _exportar_preview_csv(self, filas):
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("dlg_export_to", driver=self.t("export_format_csv")), "", "CSV (*.csv)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        columnas = [
            "nombre", "track", "bin", "descriptor", "lat", "lon", "altura",
            "hi", "comentario", "tipo", "calidad", "survey_mode_text",
            "survey_mode_value", "incluir", "subido", "archivo",
        ]
        filas_out = [
            {
                "nombre": f.get("nombre"), "track": f.get("track"), "bin": f.get("bin"),
                "descriptor": f.get("descriptor") or "", "lat": f.get("lat"), "lon": f.get("lon"),
                "altura": f.get("altura_wgs84"), "hi": f.get("hi"), "comentario": f.get("comentario") or "",
                "tipo": f.get("tipo"), "calidad": f.get("calidad") or "",
                "survey_mode_text": f.get("survey_mode_text") or "", "survey_mode_value": f.get("survey_mode_value") or "",
                "incluir": f.get("incluir", True), "subido": f.get("subido", False), "archivo": f.get("archivo"),
            }
            for f in filas
        ]
        try:
            n = export_writers.write_csv(columnas, filas_out, path)
            QMessageBox.information(self, self.t("msg_export_ok_title"), self.t("msg_export_csv_body", n=n, path=path))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_export_title"), self.t("err_export_body", error=e, trace=traceback.format_exc()))

    def _exportar_preview_ogr(self, filas, formato):
        extensiones = {"shapefile": ("ESRI Shapefile", "Shapefile (*.shp)", ".shp"), "gpkg": ("GPKG", "GeoPackage (*.gpkg)", ".gpkg")}
        driver, filtro, ext = extensiones[formato]
        path, _ = QFileDialog.getSaveFileName(self, self.t("dlg_export_to", driver=driver), "", filtro)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "exportacion", "memory")
        prov = layer.dataProvider()
        columnas_extra = ["nombre", "track", "bin", "descriptor", "tipo", "calidad", "comentario", "hi"]
        prov.addAttributes([QgsField(c, FIELD_STRING) for c in columnas_extra])
        layer.updateFields()

        feats = []
        for f in filas:
            feat = QgsFeature(layer.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(f["lon"], f["lat"])))
            feat.setAttributes(["" if f.get(c) is None else str(f.get(c)) for c in columnas_extra])
            feats.append(feat)
        prov.addFeatures(feats)
        layer.updateExtents()

        try:
            opciones = QgsVectorFileWriter.SaveVectorOptions()
            opciones.driverName = driver
            opciones.fileEncoding = "UTF-8"
            resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path, self.project.transformContext(), opciones
            )
            codigo = resultado[0] if isinstance(resultado, (tuple, list)) else resultado
            if codigo != _valor_enum(QgsVectorFileWriter, "NoError", "WriterError"):
                mensaje = resultado[1] if isinstance(resultado, (tuple, list)) and len(resultado) > 1 else str(resultado)
                raise RuntimeError(mensaje)
            QMessageBox.information(self, self.t("msg_export_ok_title"), self.t("msg_export_points_body", n=len(feats), path=path))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_export_title"), self.t("err_export_body", error=e, trace=traceback.format_exc()))

    def _fill_bulk_campo_combo(self, keep_selection=False):
        current_data = self.cb_bulk_campo.currentData() if (keep_selection and self.cb_bulk_campo.count()) else "hi"
        self.cb_bulk_campo.blockSignals(True)
        self.cb_bulk_campo.clear()
        self.cb_bulk_campo.addItem(self.t("opt_bulk_field_hi"), "hi")
        self.cb_bulk_campo.addItem(self.t("opt_bulk_field_descriptor"), "descriptor")
        idx = self.cb_bulk_campo.findData(current_data)
        self.cb_bulk_campo.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_bulk_campo.blockSignals(False)
        if hasattr(self, "spn_hi_bulk"):
            self._actualizar_widget_valor_bulk()

    def _actualizar_widget_valor_bulk(self, *_args):
        """Conectado a `cb_bulk_campo.currentIndexChanged`: muestra el
        spinbox de Altura de antena o el campo de texto de Descriptor
        según el campo elegido en el combo -- ver `aplicar_valor_bulk`."""
        es_descriptor = self.cb_bulk_campo.currentData() == "descriptor"
        self.spn_hi_bulk.setVisible(not es_descriptor)
        self.txt_descriptor_bulk.setVisible(es_descriptor)

    def aplicar_valor_bulk(self):
        """Botón "Aplicar a todos" junto al combo "Aplicar a todos los
        puntos incluidos": generalización (v2.60.0, pedido explícito del
        usuario) de la vieja `aplicar_hi_a_todos` para que el mismo botón
        sirva también para pisar el Descriptor de toda la columna, no
        sólo la Altura de antena. Nunca toca filas ya subidas
        (`fila.get("subido")`), igual que antes."""
        campo = self.cb_bulk_campo.currentData()
        if campo == "descriptor":
            valor_texto = self.txt_descriptor_bulk.text()
            columna_tabla = PREVIEW_COL_DESCRIPTOR
            clave_fila = "descriptor"
            valor_fila = valor_texto
        else:
            valor_fila = self.spn_hi_bulk.value()
            valor_texto = f"{valor_fila:.3f}"
            columna_tabla = PREVIEW_COL_HI
            clave_fila = "hi"
        for row in range(self.tbl_import_preview.rowCount()):
            if row < len(self._import_preview) and self._import_preview[row].get("subido"):
                continue
            item = self.tbl_import_preview.item(row, columna_tabla)
            if item is not None:
                item.setText(valor_texto)
            if row < len(self._import_preview):
                self._import_preview[row][clave_fila] = valor_fila

    # -- Botón Subir / Subir-Retirar (verde -> rojo) y retiro de la última
    # subida (pedido explícito del usuario: poder deshacer una subida hecha
    # por error, incluso ignorando las advertencias de duplicados) --------

    def _actualizar_boton_subir(self):
        """Verde y "Subir" mientras no haya ninguna subida retirable;
        rojo y "Subir/Retirar" cuando `self._lotes_subidos` tiene al menos
        una."""
        btn = getattr(self, "btn_subir_dc", None)
        if btn is None:
            return
        if self._lotes_subidos:
            btn.setText(self.t("btn_upload_retire_dc"))
            btn.setToolTip(self.t("tip_btn_upload_retire_dc"))
            btn.setStyleSheet(ESTILO_BTN_SUBIR_ROJO)
        else:
            btn.setText(self.t("btn_upload_dc"))
            btn.setToolTip(self.t("tip_btn_upload_dc"))
            btn.setStyleSheet(ESTILO_BTN_SUBIR_VERDE)

    def _resetear_lotes_subidos(self):
        self._lotes_subidos = []
        self._actualizar_boton_subir()

    def _on_click_subir(self):
        """Sin subidas retirables: sube directamente. Con alguna (botón
        "Subir/Retirar"): pregunta si se quiere subir lo pendiente, retirar
        la última subida o cancelar."""
        if not self._lotes_subidos:
            self.subir_dc_preview()
            return
        lote = self._lotes_subidos[-1]
        box = QMessageBox(self)
        box.setWindowTitle(self.t("dlg_upload_retire_title"))
        box.setText(self.t("dlg_upload_retire_body", n=len(lote["ids"])))
        btn_subir = box.addButton(self.t("btn_dialog_upload_pending"), MSG_ROLE_ACTION)
        btn_retirar = box.addButton(self.t("btn_dialog_retire_last", n=len(lote["ids"])), MSG_ROLE_ACTION)
        box.addButton(MSG_CANCEL)
        box.setDefaultButton(btn_subir)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_retirar:
            self._retirar_ultima_subida()
        elif clicked is btn_subir:
            self.subir_dc_preview()

    @_escritura()
    def _retirar_ultima_subida(self):
        """Borra de POSTPLOT los puntos (por ID exacto) de la subida más
        reciente, devuelve sus filas de la previsualización a "no subido"
        con "Incluir" marcado, quita la capa de QGIS que se creó con esa
        subida y actualiza los conteos y el botón."""
        if not self._lotes_subidos:
            return
        if not self._require_project():
            return
        lote = self._lotes_subidos[-1]
        n = len(lote["ids"])
        resp = QMessageBox.question(
            self, self.t("confirm_retire_upload_title"),
            self.t("confirm_retire_upload_body", n=n),
        )
        if resp not in (MSG_YES,):
            return
        try:
            borradas = db_schema.delete_rows_by_id_chunked(self.conn, "POSTPLOT", lote["ids"])
        except Exception as e:
            QMessageBox.warning(self, self.t("warn_retire_upload_title"), self.t("warn_retire_upload_error", error=e))
            return
        self._lotes_subidos.pop()

        claves = set(lote["keys"])
        for fila in self._import_preview:
            if (fila.get("origen"), fila.get("archivo_path"), fila.get("line_no")) in claves:
                fila["subido"] = False
                fila["incluir"] = True
        layer_id = lote.get("layer_id")
        if layer_id:
            try:
                if self.project.mapLayer(layer_id) is not None:
                    self.project.removeMapLayer(layer_id)
            except Exception:  # nosec B110 - la capa pudo haberla borrado el usuario a mano
                pass

        self.actualizar_conteos()
        self.log_importar.appendPlainText(self.t("log_retire_upload_ok", n=borradas))
        self._actualizar_boton_subir()
        if self._import_preview:
            self._llenar_tabla_preview()
        QMessageBox.information(
            self, self.t("info_retire_upload_title"), self.t("info_retire_upload_body", n=borradas),
        )

    @_escritura()
    def subir_dc_preview(self):
        """Sube a POSTPLOT sólo los puntos de `self._import_preview` con
        la casilla "Incluir" marcada, usando el nombre/altura de
        antena/comentario que el usuario haya editado en la tabla (ver
        `_sync_preview_edits_desde_tabla`)."""
        if not self._require_project():
            return
        if not self._import_preview:
            QMessageBox.information(self, self.t("info_nothing_to_upload_title"), self.t("info_nothing_to_upload_body"))
            return

        self._sync_preview_edits_desde_tabla()

        incluidas = [f for f in self._import_preview if f.get("incluir", True) and not f.get("subido")]
        if not incluidas:
            QMessageBox.information(self, self.t("info_nothing_to_upload_title"), self.t("info_nothing_to_upload_body"))
            return

        # Advertencia (pedido explícito del usuario): si alguno de los
        # puntos a subir ya existe en POSTPLOT (mismo Station_Text, sin
        # distinguir mayúsculas), se pide confirmación antes de insertar.
        # Es una advertencia, no un candado -- una reocupación intencional
        # es legítima -- y lo que se suba por error se puede retirar con
        # "Subir/Retirar" (`_retirar_ultima_subida`).
        existentes = self._nombres_postplot_existentes(f["nombre"] for f in incluidas)
        duplicados = [f for f in incluidas if (f.get("nombre") or "").strip().upper() in existentes]
        if duplicados:
            ejemplos = ", ".join(sorted({str(f["nombre"]).strip() for f in duplicados})[:8])
            resp = QMessageBox.question(
                self, self.t("warn_upload_duplicates_title"),
                self.t("warn_upload_duplicates_body", n=len(duplicados), ejemplos=ejemplos),
                MSG_YES | MSG_NO, MSG_NO,
            )
            if resp != MSG_YES:
                return

        por_archivo = {}
        for f in incluidas:
            por_archivo.setdefault((f["origen"], f["archivo_path"]), []).append(f)

        dc_by_path = {dc.path: dc for dc in self.dc_files}
        hitarget_by_path = {hf.path: hf for hf in self.hitarget_files}
        chcnav_by_path = {cf.path: cf for cf in self.chcnav_files}
        stonex_by_path = {sf.path: sf for sf in self.stonex_files}
        surpad_by_path = {sf.path: sf for sf in self.surpad_files}
        sourcelink_by_path = {sf.path: sf for sf in self.sourcelink_files}
        inova_by_path = {sf.path: sf for sf in self.inova_files}
        _archivo_by_origen = {
            "DC": dc_by_path, "HITARGET": hitarget_by_path,
            "CHCNAV": chcnav_by_path, "STONEX": stonex_by_path,
            "SURPAD": surpad_by_path, "SOURCELINK": sourcelink_by_path, "INOVA": inova_by_path,
        }

        total_insertadas = 0
        puntos_para_capa = []  # (nombre, lat, lon, altura, tipo)
        lote = {"ids": [], "keys": [], "layer_id": None}

        for (origen, archivo_path), filas in por_archivo.items():
            archivo_obj = _archivo_by_origen.get(origen, {}).get(archivo_path)
            # Processor (global) y Surveyor (propio del archivo) de la
            # pestaña -- None si se dejan vacíos, para no guardar "".
            processor_txt = self.txt_import_processor.text().strip() or None
            surveyor_txt = self._surveyor_por_archivo.get((origen, archivo_path), "").strip() or None
            rows = []
            for f in filas:
                # Offset North/East/Range/Bearing/Height e Inline/Crossline/
                # Inline Azimuth: hasta esta versión se calculaban SÓLO para
                # mostrarlos en la tabla de previsualización
                # (`_llenar_tabla_preview`) y se descartaban al subir --
                # POSTPLOT tiene estas columnas (igual que la plantilla
                # ADC3D.sqlite real) pero quedaban siempre NULL. Ahora se
                # recalculan aquí, con la misma fórmula, para que sí queden
                # guardadas en la base (pedido explícito del usuario: "...en
                # el manejo de la base de datos"). Sólo disponibles cuando
                # hay un PREPLOT cargado Y el punto matcheó contra uno (`m`),
                # igual que en la previsualización.
                m = f.get("match")
                offset_north = offset_east = offset_range = offset_bearing = offset_height = None
                offset_inline = offset_crossline = inline_azimuth = None
                if m is not None:
                    offset_north = m["delta_y"]
                    offset_east = m["delta_x"]
                    offset_range = m["distancia_2d"]
                    offset_bearing = math.degrees(math.atan2(offset_east, offset_north)) % 360
                    offset_height = m.get("delta_z")
                    az, _origen_az = self._resolver_azimut_linea(f)
                    if az is not None:
                        az_rad = math.radians(az)
                        u_e, u_n = math.sin(az_rad), math.cos(az_rad)
                        offset_inline = offset_east * u_e + offset_north * u_n
                        offset_crossline = offset_east * u_n - offset_north * u_e
                        inline_azimuth = az
                rows.append({
                    "Station_Text": f["nombre"],
                    "Station_Value": punto_nombre.station_value_numerico(f["nombre"]),
                    "Track": int(f["track"]) if f["track"] else None,
                    "Bin": int(f["bin"]) if f["bin"] else None,
                    # Corregido en v2.60.0: hasta esta versión acá se
                    # guardaba `f["tipo"]` (la clasificación de solución
                    # GNSS -- KI/SO de Trimble, Fijo/Flotante de
                    # Hi-Target, etc.) en la columna Descriptor real de
                    # POSTPLOT, descartando el código Descriptor de
                    # verdad (`fila["descriptor"]`, editable en la
                    # columna "Descriptor" de la previsualización desde
                    # la v2.32.0, y el mismo campo que ya usa
                    # `_resolver_azimut_linea`/v2.36.0 para decidir línea
                    # fuente/receptora -- 60/62/.../51/52) para Trimble
                    # .dc, que sí lo trae. Ahora se guarda el código real
                    # cuando el formato lo trajo o el usuario lo escribió
                    # a mano/con "Aplicar a todos", y sólo se usa `tipo`
                    # como respaldo para Hi-Target/CHCNav/Stonex/bases,
                    # que nunca traen un código Descriptor propio y
                    # quedarían en blanco si no.
                    "Descriptor": f.get("descriptor") or f["tipo"],
                    "WGS84_Latitude": f["lat"],
                    "WGS84_Longitude": f["lon"],
                    "WGS84_Height": f["altura_wgs84"],
                    "Geoid_Height": f["geoid_h"],
                    "Local_Height": f["local_h"],
                    "Geoid_Model_File": self._import_geoid_file_name if f["geoid_h"] is not None else None,
                    "HI": f.get("hi"),
                    "Offset_North": offset_north,
                    "Offset_East": offset_east,
                    "Offset_Range": offset_range,
                    "Offset_Bearing": offset_bearing,
                    "Offset_Height": offset_height,
                    "Offset_Inline": offset_inline,
                    "Offset_Crossline": offset_crossline,
                    "Inline_Azimuth": inline_azimuth,
                    # Sólo Trimble .dc trae un dato real para esto (ver la
                    # nota completa junto a `DCPoint.hor_precision_95` y el
                    # docstring de `_parse_60nm_precision` en
                    # dc_parser.py) -- `.get()` deja NULL para el resto de
                    # los orígenes, igual que "Elapsed_Time" más abajo.
                    "Hor_Precision_95": f.get("hor_precision_95"),
                    "Ver_Precision_95": f.get("ver_precision_95"),
                    "CQ": f.get("cq"),
                    "Comment": (f.get("comentario") or None),
                    "Survey_Mode_Text": f.get("modo_texto"),
                    # Sólo Trimble .dc trae un dato real para esto (ver la
                    # nota completa junto a `DCPoint.elapsed_seconds`) --
                    # `.get()` deja NULL para el resto de los orígenes.
                    "Elapsed_Time": f.get("elapsed_seconds"),
                    # CHCNAV trae este dato tal cual de las líneas
                    # "--DT.../--TM..." del .rw5 (sin interpretar su
                    # formato); STONEX trae fecha/hora real y absoluta
                    # (local Y UTC, ver `Survey_Time_GMT` más abajo) de
                    # `GPSCoordinate.LocalDate/LocalTime`. Desde esta
                    # ronda, Trimble .dc TAMBIÉN puede traer un valor real
                    # acá -- ver `dc_parser._calibrar_horas_gps` -- pero
                    # sólo para una semana de trabajo ya calibrada; `.get()`
                    # deja NULL para Hi-Target (sin este dato en absoluto) y
                    # para DC de una semana todavía sin calibrar.
                    "Survey_Time_Local": f.get("survey_time_local"),
                    # STONEX trae hora UTC real y absoluta por punto
                    # (`GPSCoordinate.UTCDate/UTCTime`); Trimble .dc, desde
                    # esta ronda, también -- mismo criterio que
                    # "Survey_Time_Local" de arriba. `.get()` deja NULL
                    # para Hi-Target y para DC sin semana calibrada.
                    "Survey_Time_GMT": f.get("survey_time_gmt"),
                    # Nuevo en esta ronda: Trimble .dc trae un valor real
                    # para "Serial Time (GPS)" cuando su semana de trabajo
                    # ya está calibrada (ver `dc_parser._GMT_WEEK_
                    # CALIBRATION`/`_calibrar_horas_gps`, verificado exacto
                    # contra 631 de 632 puntos combinados de 3 archivos
                    # reales -- la única excepción es una reocupación
                    # ambigua ya conocida). Ningún otro origen soportado
                    # trae este dato -- `.get()` deja NULL para ellos y
                    # para DC de una semana sin calibrar.
                    "Serial_Time_GPS": f.get("serial_time_gps"),
                    # Julian Date (Local): ya se calculaba y se mostraba
                    # bien en la previsualización desde hace varias rondas
                    # (`f["julian_date_local"]`, ver la nota junto a esa
                    # clave en `previsualizar_dc()`) pero, hallado recién
                    # ahora al revisar este mismo bloque, nunca se
                    # guardaba de verdad al subir a POSTPLOT -- quedaba
                    # siempre NULL en la base de datos pese a mostrarse
                    # bien en pantalla. Corregido de paso en esta ronda,
                    # mismo patrón que el resto de las columnas de acá.
                    "Julian_Date_Local": (
                        int(f.get("julian_date_local")) if f.get("julian_date_local") else None
                    ),
                    "Populate_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Collector_Job_Name": f["job_name"],
                    # Desde esta ronda: para un origen que trae el tipo de
                    # RECEPTOR GNSS real (DC vía 'E2NM', ver
                    # `DCFile.receiver_type` en dc_parser.py; Stonex vía
                    # `Antenna`/`Receiver`), se usa ese valor -- más
                    # preciso que `f["instrument"]`, que para DC en
                    # realidad es el modelo del COLECTOR/controlador de
                    # campo (de '00NM'), no del receptor. Para
                    # Hi-Target/CHCNav (sin este dato) se sigue usando
                    # `f["instrument"]` tal cual, igual que antes.
                    "Receiver_Type": (f.get("receiver_type") or f["instrument"]),
                    # Sólo STONEX trae un número de serie/IMEI real del
                    # equipo (`GPSCoordinate.InstrumentID`, vía
                    # `Antenna.ID`) -- ningún otro origen lo trae,
                    # `.get()` deja NULL para ellos.
                    "Receiver_SN": f.get("receiver_sn"),
                    "Download_File": os.path.basename(f["archivo_path"]),
                    # Desde la v2.10.0, un punto 'SO' de .dc también
                    # trae satélites/PDOP/HDOP/VDOP/épocas/duración (ver
                    # la nota junto a "n_sats" en `previsualizar_dc`); un
                    # 'KI' de .dc y la base RTK de cualquier origen
                    # siguen sin este dato -- quedan en None.
                    "Number_of_Satellites": f.get("n_sats"),
                    "PDOP": f.get("pdop"),
                    "HDOP": f.get("hdop"),
                    "VDOP": f.get("vdop"),
                    "Number_Of_Epochs": f.get("n_epochs"),
                    "Occupation_Time": f.get("occupation_seconds"),
                    "GPS_Baseline": f.get("gps_baseline_m"),
                    "GPS_Base_Station": f.get("gps_base_station"),
                    "Processor": processor_txt,
                    # SourceLink trae el vibrador (Unit ID) por punto y tiene
                    # prioridad; el resto usa el Surveyor escrito junto al
                    # archivo.
                    "Surveyor": (f.get("surveyor") or surveyor_txt),
                })
                puntos_para_capa.append((f["nombre"], f["lat"], f["lon"], f["altura_wgs84"], f["tipo"]))

            try:
                ids_insertados = db_schema.insert_rows_with_ids(
                    self.conn, "POSTPLOT", db_schema.POSTPLOT_COLUMNS, rows,
                )
                n = len(ids_insertados)
                lote["ids"].extend(ids_insertados)
                lote["keys"].extend((f["origen"], f["archivo_path"], f["line_no"]) for f in filas)
                total_insertadas += n
                nombre_archivo = os.path.basename(archivo_path)
                job = archivo_obj.job_name if origen == "DC" and archivo_obj is not None else None
                instr = filas[0]["instrument"]
                self.log_importar.appendPlainText(self.t(
                    "log_import_ok", name=nombre_archivo, n=n, job=(job or "-"), instr=(instr or "-"),
                ))
                for f in filas:
                    f["subido"] = True
                    f["incluir"] = False
                if archivo_obj is not None:
                    for warn in archivo_obj.warnings:
                        self.log_importar.appendPlainText(self.t("log_import_warning", warn=warn))
            except Exception as e:
                nombre_archivo = os.path.basename(archivo_path)
                self.log_importar.appendPlainText(self.t("log_import_error", name=nombre_archivo, error=e))

        self.actualizar_conteos()

        if self.chk_crear_capa_import.isChecked() and puntos_para_capa:
            capa = self._crear_capa_puntos_dc(puntos_para_capa)
            if capa is not None:
                lote["layer_id"] = capa.id()

        if lote["ids"]:
            self._lotes_subidos.append(lote)
            self._actualizar_boton_subir()

        QMessageBox.information(
            self, self.t("msg_import_done_title"),
            self.t("msg_import_done_body", n=total_insertadas)
            + ("\n\n" + self.t("msg_import_done_retire_hint") if lote["ids"] else ""),
        )

        self._llenar_tabla_preview()

    def _crear_capa_puntos_dc(self, puntos):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", self.t("layer_dc_points"), "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("tipo", FIELD_STRING),
            QgsField("altura", FIELD_DOUBLE),
        ])
        layer.updateFields()

        feats = []
        for nombre, lat, lon, altura, tipo in puntos:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            f.setAttributes([nombre, tipo, altura])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()

        tipos_presentes = sorted({tipo for _, _, _, _, tipo in puntos}, key=lambda t: list(COLOR_POR_TIPO).index(t) if t in COLOR_POR_TIPO else 999)
        self._aplicar_estilo_por_tipo(layer, tipos_presentes)
        self.project.addMapLayer(layer)
        # Sin esto, `iface.mapCanvas().layers()` puede quedar sin
        # sincronizar con el árbol de capas del proyecto hasta el
        # siguiente ciclo del loop de eventos de Qt -- procesar los
        # eventos pendientes aquí mismo evita el bug reportado de "el
        # punto no aparece en el plano" al importar.
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)
        return layer

    def _aplicar_estilo_por_tipo(self, layer, tipos_presentes):
        """Simboliza por categorías la capa creada al subir "Importar
        datos de campo", con un color/etiqueta por cada tipo realmente
        presente entre los puntos subidos (KI/SO de un .dc de Trimble;
        FIX/FLOAT/CALC/BASE/OTRO derivados del estado de un punto de
        Hi-Target -- ver `_hitarget_tipo_code`; futuras marcas pueden
        agregar más entradas a `COLOR_POR_TIPO`/`LEGEND_KEY_POR_TIPO`)."""
        categorias = []
        for valor in tipos_presentes:
            color = COLOR_POR_TIPO.get(valor, COLOR_POR_TIPO["OTRO"])
            etiqueta_key = LEGEND_KEY_POR_TIPO.get(valor, "legend_other")
            symbol = QgsMarkerSymbol.createSimple({"name": "circle", "size": "2.4", "color": color})
            categorias.append(QgsRendererCategory(valor, symbol, self.t(etiqueta_key)))
        renderer = QgsCategorizedSymbolRenderer("tipo", categorias)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _actualizar_capa_provisional_preview(self):
        """Crea/actualiza una capa de memoria PROVISIONAL con los puntos
        que quedaron en `self._import_preview` (ya filtrados por
        `previsualizar_dc()` a sólo los que tienen datos de campo reales)
        para que el usuario pueda ver de inmediato su ubicación
        geográfica en el plano de QGIS, sin necesidad de subirlos antes a
        POSTPLOT. A diferencia de la capa "Puntos levantados" que crea
        `_crear_capa_puntos_dc()` al subir, ésta se reemplaza por
        completo cada vez que se vuelve a previsualizar (nunca se
        acumulan capas provisionales viejas). Si toda la previsualización
        viene de un único archivo cargado, la capa se nombra con ese
        archivo en vez de un título genérico (ver `layer_preview_
        provisional_archivo` en i18n.py)."""
        capa_vieja = self._provisional_preview_layer
        if capa_vieja is not None:
            try:
                if QgsProject.instance().mapLayer(capa_vieja.id()) is not None:
                    self.project.removeMapLayer(capa_vieja.id())
            except RuntimeError:
                # El objeto Qt/QGIS ya fue eliminado (p.ej. el usuario
                # quitó la capa a mano) -- nada que limpiar.
                pass
            self._provisional_preview_layer = None

        if not self._import_preview:
            return

        # Pedido explícito del usuario: si TODA la previsualización viene
        # de un único archivo cargado, la capa temporal se nombra con ese
        # archivo (ej. "LASUIZA.rw5 (vista previa, sin subir)") en vez del
        # título genérico de siempre -- antes, aunque sólo hubiera un
        # archivo cargado, el título no decía cuál era. Con más de un
        # archivo cargado a la vez no hay un único nombre que mostrar, así
        # que se mantiene el título genérico.
        archivos_presentes = sorted({
            fila["archivo"] for fila in self._import_preview if fila.get("archivo")
        })
        if len(archivos_presentes) == 1:
            nombre_capa = self.t("layer_preview_provisional_archivo", archivo=archivos_presentes[0])
        else:
            nombre_capa = self.t("layer_preview_provisional")

        layer = QgsVectorLayer("Point?crs=EPSG:4326", nombre_capa, "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("tipo", FIELD_STRING),
            QgsField("altura", FIELD_DOUBLE),
        ])
        layer.updateFields()

        feats = []
        tipos_presentes = set()
        for fila in self._import_preview:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(fila["lon"], fila["lat"])))
            f.setAttributes([fila["nombre"], fila["tipo"], fila["altura_wgs84"]])
            feats.append(f)
            tipos_presentes.add(fila["tipo"])
        prov.addFeatures(feats)
        layer.updateExtents()

        orden = sorted(tipos_presentes, key=lambda t: list(COLOR_POR_TIPO).index(t) if t in COLOR_POR_TIPO else 999)
        self._aplicar_estilo_por_tipo(layer, orden)
        self.project.addMapLayer(layer)
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)
        self._provisional_preview_layer = layer

    def _actualizar_capas_desplazamiento_preview(self):
        """Crea/actualiza dos capas de memoria PROVISIONALES a partir de
        los puntos de `self._import_preview` que matchearon contra
        PREPLOT por nombre (`fila["match"]`, armado por
        `_ejecutar_comparacion_preview()`): una con el punto de PREPLOT
        de cada match, y otra con una LÍNEA entre ese punto de PREPLOT y
        el punto levantado en campo (POSTPLOT, todavía sin subir) --
        pedido explícito del usuario, para ver gráficamente en el mapa el
        desplazamiento real de cada punto respecto a su diseño, sin subir
        ni exportar nada todavía.

        Las coordenadas de ambos extremos (`x_diseno`/`y_diseno` y
        `x_levantado`/`y_levantado`) ya vienen en el CRS de trabajo
        (`_working_crs()`) dentro de `fila["match"]` -- mismo campo que ya
        usa `_render_preview_match_cells`/`crear_capa_comparacion`, así
        que no hace falta ninguna transformación de coordenadas acá.

        Igual que `_actualizar_capa_provisional_preview()`, ambas capas
        se reemplazan por completo cada vez que se llama (nunca se
        acumulan capas viejas) -- se llama tanto al previsualizar como al
        volver a comparar (`actualizar_comparacion_preview`)."""
        for attr in ("_provisional_preplot_match_layer", "_provisional_desplazamiento_layer"):
            capa_vieja = getattr(self, attr)
            if capa_vieja is not None:
                try:
                    if QgsProject.instance().mapLayer(capa_vieja.id()) is not None:
                        self.project.removeMapLayer(capa_vieja.id())
                except RuntimeError:
                    # El objeto Qt/QGIS ya fue eliminado (p.ej. el usuario
                    # quitó la capa a mano) -- nada que limpiar.
                    pass
                setattr(self, attr, None)

        matches = [fila["match"] for fila in self._import_preview if fila.get("match") is not None]
        if not matches:
            return

        dest_crs = self._working_crs()

        layer_preplot = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", self.t("layer_preplot_match_preview"), "memory")
        prov_p = layer_preplot.dataProvider()
        prov_p.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("dist_2d", FIELD_DOUBLE),
            QgsField("dentro_tol", FIELD_INT),
        ])
        layer_preplot.updateFields()

        layer_lineas = QgsVectorLayer(f"LineString?crs={dest_crs.authid()}", self.t("layer_desplazamiento_preview"), "memory")
        prov_l = layer_lineas.dataProvider()
        prov_l.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("dist_2d", FIELD_DOUBLE),
            QgsField("dentro_tol", FIELD_INT),
        ])
        layer_lineas.updateFields()

        feats_p, feats_l = [], []
        for m in matches:
            dentro = 1 if m["dentro_tolerancia"] else 0
            p_diseno = QgsPointXY(m["x_diseno"], m["y_diseno"])
            p_levantado = QgsPointXY(m["x_levantado"], m["y_levantado"])

            fp = QgsFeature(layer_preplot.fields())
            fp.setGeometry(QgsGeometry.fromPointXY(p_diseno))
            fp.setAttributes([m["name_diseno"], m["distancia_2d"], dentro])
            feats_p.append(fp)

            fl = QgsFeature(layer_lineas.fields())
            fl.setGeometry(QgsGeometry.fromPolylineXY([p_diseno, p_levantado]))
            fl.setAttributes([m["name_levantado"], m["distancia_2d"], dentro])
            feats_l.append(fl)

        prov_p.addFeatures(feats_p)
        layer_preplot.updateExtents()
        prov_l.addFeatures(feats_l)
        layer_lineas.updateExtents()

        # Triángulo violeta para distinguir a simple vista el punto de
        # PREPLOT (diseño) del punto de la previsualización de campo
        # (círculos, ver `_aplicar_estilo_por_tipo`) y del de "Comparar"
        # (`crear_capa_comparacion`, también círculos).
        symbol_preplot = QgsMarkerSymbol.createSimple({"name": "triangle", "size": "3", "color": "#6a3d9a"})
        layer_preplot.setRenderer(QgsSingleSymbolRenderer(symbol_preplot))
        layer_preplot.triggerRepaint()

        categorias = []
        for valor, color, etiqueta_key in (
            (1, "#33a02c", "legend_desplazamiento_dentro"), (0, "#e31a1c", "legend_desplazamiento_fuera"),
        ):
            symbol = QgsLineSymbol.createSimple({"line_color": color, "line_width": "0.6"})
            categorias.append(QgsRendererCategory(valor, symbol, self.t(etiqueta_key)))
        layer_lineas.setRenderer(QgsCategorizedSymbolRenderer("dentro_tol", categorias))
        layer_lineas.triggerRepaint()

        self.project.addMapLayer(layer_preplot)
        self.project.addMapLayer(layer_lineas)
        # Ver el comentario equivalente en `_crear_capa_puntos_dc`: sin
        # procesar los eventos pendientes acá, las capas pueden no
        # aparecer todavía en `iface.mapCanvas().layers()`.
        QApplication.processEvents()

        self._provisional_preplot_match_layer = layer_preplot
        self._provisional_desplazamiento_layer = layer_lineas

    def _actualizar_capa_provisional_preplot_ext(self):
        """Crea/actualiza una capa de memoria PROVISIONAL con TODOS los
        puntos que haya ahora mismo en `self._preplot_ext_preview` --
        vengan de un SPS, un archivo `.qld`, o una capa de QGIS
        importada (ver "Importar preplot externo") -- para poder verlos
        de inmediato en el plano de QGIS antes incluso de subirlos a
        PREPLOT, igual que ya pasa con el preplot generado dentro del
        propio plugin (`generar_preplot()`, capa "Preplot generado").
        Se llama cada vez que cambia el contenido de
        `_preplot_ext_preview` (al agregar, subir o limpiar), y siempre
        reemplaza por completo la capa anterior en vez de acumularla."""
        capa_vieja = self._provisional_preplot_ext_layer
        if capa_vieja is not None:
            try:
                if QgsProject.instance().mapLayer(capa_vieja.id()) is not None:
                    self.project.removeMapLayer(capa_vieja.id())
            except RuntimeError:
                # El objeto Qt/QGIS ya fue eliminado (p.ej. el usuario
                # quitó la capa a mano) -- nada que limpiar.
                pass
            self._provisional_preplot_ext_layer = None

        if not self._preplot_ext_preview:
            return

        dest_crs = self._working_crs()
        layer = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", self.t("layer_preplot_ext_provisional"), "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("origen", FIELD_STRING),
            QgsField("linea", FIELD_STRING),
            QgsField("estacion", FIELD_STRING),
            QgsField("cota", FIELD_DOUBLE),
            QgsField("descriptor", FIELD_STRING),
            QgsField("estado", FIELD_STRING),
        ])
        layer.updateFields()

        feats = []
        for fila in self._preplot_ext_preview:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(fila["x"], fila["y"])))
            z = fila.get("z")
            estado = self.t("status_duplicate_preplot") if fila.get("duplicado") else self.t("status_new_point")
            f.setAttributes([
                fila["nombre"], fila.get("origen", ""),
                str(fila.get("track")) if fila.get("track") is not None else "",
                str(fila.get("bin")) if fila.get("bin") is not None else "",
                float(z) if z is not None else None,
                fila.get("descriptor", ""), estado,
            ])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)
        self._provisional_preplot_ext_layer = layer

    # -- Sección: Comparar --------------------------------------------------
    # -- Sección: Comparar (rediseño v2.67.0) -------------------------------
    # Arriba, dos tarjetas 50/50: "Configuración de la fuente" (CSV o tabla
    # PREPLOT; el formulario de mapeo del CSV sólo se ve con "Archivo CSV") y
    # "Parámetros de comparación" (tabla, tolerancia, emparejamiento
    # aproximado y el botón "Ejecutar comparación" al fondo). En el medio, la
    # tabla de discrepancias con todo el alto sobrante; abajo, una única
    # barra con las salidas (capa QGIS / CSV a la izquierda; interruptor
    # "Guardar también fuentes en PREPLOT" y botón verde a la derecha).
    def _build_tab_comparar(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(6)
        self._agregar_boton_ayuda(v, ["comparar_intro"], "tab4_title")

        # ---- Tarjeta izquierda: Configuración de la fuente ----
        grp_fuente, v_f = self._tarjeta_card("cmp_card_fuente")
        self.grp_cmp_fuente = grp_fuente
        fila_modo = QHBoxLayout()
        self.rb_fuente_csv = self._reg(QRadioButton(), "rb_source_csv")
        self.rb_fuente_preplot = self._reg(QRadioButton(), "cmp_rb_preplot")
        self.rb_fuente_csv.setChecked(True)
        grupo_fuente = QButtonGroup(self)
        grupo_fuente.addButton(self.rb_fuente_csv)
        grupo_fuente.addButton(self.rb_fuente_preplot)
        fila_modo.addWidget(self.rb_fuente_csv)
        fila_modo.addWidget(self.rb_fuente_preplot)
        fila_modo.addStretch(1)
        v_f.addLayout(fila_modo)

        # Formulario del CSV: se oculta entero con "Tabla PREPLOT"
        # (`_toggle_fuente_diseno`). Se conserva el nombre `grp_csv`.
        self.grp_csv = QWidget()
        v_csv = QVBoxLayout(self.grp_csv)
        v_csv.setContentsMargins(0, 0, 0, 0)
        v_csv.setSpacing(6)

        lbl_ruta = self._reg(QLabel(), "cmp_lbl_ruta_csv")
        lbl_ruta.setStyleSheet(ESTILO_ROTULO_TENUE)
        v_csv.addWidget(lbl_ruta)
        fila_csv = QHBoxLayout()
        self.lbl_csv_path = QLineEdit()
        self.lbl_csv_path.setReadOnly(True)
        self._reg(self.lbl_csv_path, "cmp_ph_ruta_csv", kind="placeholder")
        btn_csv = self._reg(QPushButton(), "cmp_btn_cargar")
        btn_csv.clicked.connect(self.cargar_csv)
        fila_csv.addWidget(self.lbl_csv_path, 1)
        fila_csv.addWidget(btn_csv)
        v_csv.addLayout(fila_csv)

        self.cb_col_nombre = self._combo_campo()
        self.cb_col_x = self._combo_campo()
        self.cb_col_y = self._combo_campo()
        self.cb_col_z = self._combo_campo()
        cont_cols, g = self._bloque_filas(2)
        self._celda_campo(g, 0, 0, "cmp_col_nombre", self.cb_col_nombre)
        self._celda_campo(g, 0, 1, "cmp_col_z", self.cb_col_z)
        self._celda_campo(g, 1, 0, "cmp_col_x", self.cb_col_x)
        self._celda_campo(g, 1, 1, "cmp_col_y", self.cb_col_y)

        # Fila 4: tipo de coordenadas | CRS.
        cont_tipo = QWidget()
        v_tipo = QVBoxLayout(cont_tipo)
        v_tipo.setContentsMargins(0, 0, 0, 0)
        v_tipo.setSpacing(2)
        lbl_tipo = self._reg(QLabel(), "cmp_lbl_tipo_coord")
        lbl_tipo.setStyleSheet(ESTILO_ROTULO_TENUE)
        v_tipo.addWidget(lbl_tipo)
        h_tipo = QHBoxLayout()
        self.rb_plana = self._reg(QRadioButton(), "cmp_rb_planas")
        self.rb_geografica = self._reg(QRadioButton(), "cmp_rb_geograficas")
        self.rb_plana.setChecked(True)
        grupo_tipo = QButtonGroup(self)
        grupo_tipo.addButton(self.rb_plana)
        grupo_tipo.addButton(self.rb_geografica)
        h_tipo.addWidget(self.rb_plana)
        h_tipo.addWidget(self.rb_geografica)
        h_tipo.addStretch(1)
        v_tipo.addLayout(h_tipo)
        g.addWidget(cont_tipo, 2, 0)

        if QgsProjectionSelectionWidget is not None:
            self.csv_crs_widget = QgsProjectionSelectionWidget()
            self.csv_crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:9377"))
            self.cont_csv_crs = self._celda_campo(g, 2, 1, "cmp_lbl_crs", self.csv_crs_widget)
        else:
            self.csv_crs_widget = None
            self.cont_csv_crs = None
        v_csv.addWidget(cont_cols)
        v_f.addWidget(self.grp_csv)

        self.lbl_preplot_source_note = self._reg(QLabel(), "info_preplot_source_note")
        self.lbl_preplot_source_note.setWordWrap(True)
        self.lbl_preplot_source_note.setVisible(False)
        v_f.addWidget(self.lbl_preplot_source_note)
        v_f.addStretch(1)

        self.rb_fuente_csv.toggled.connect(self._toggle_fuente_diseno)
        self.rb_fuente_preplot.toggled.connect(self._toggle_fuente_diseno)
        # El CRS del CSV sólo aplica a coordenadas planas.
        self.rb_plana.toggled.connect(self._actualizar_crs_csv_habilitado)

        # ---- Tarjeta derecha: Parámetros de comparación y tolerancia ----
        grp_comp, v_c = self._tarjeta_card("cmp_card_param")
        self.cb_tabla_levantado = QComboBox()
        self.cb_tabla_levantado.addItems(["POSTPLOT", "PREPLOT"])
        self.spn_tolerancia = QDoubleSpinBox()
        self.spn_tolerancia.setDecimals(3)
        self.spn_tolerancia.setRange(0.001, 1000.0)
        self.spn_tolerancia.setSingleStep(0.01)
        self.spn_tolerancia.setValue(0.10)
        self.spn_tolerancia.setSuffix(" m")
        self.chk_match_aproximado = self._reg(QCheckBox(), "chk_approx_match")
        self.chk_match_aproximado.setChecked(True)
        self._reg(self.chk_match_aproximado, "tip_approx_match", kind="tooltip")
        cont_p, gp = self._bloque_filas(2)
        self._celda_campo(gp, 0, 0, "cmp_lbl_contra", self.cb_tabla_levantado)
        self._celda_campo(gp, 0, 1, "cmp_lbl_tolerancia", self.spn_tolerancia)
        gp.addWidget(self.chk_match_aproximado, 1, 0, 1, 2)
        v_c.addWidget(cont_p)

        # Bloque desplegable (cerrado por defecto): comparar el resultado de
        # DOS consultas SQL guardadas / precargadas, las mismas de "Base de
        # Datos" (p.ej. PREPLOT receptoras contra POSTPLOT receptoras).
        self.acc_cmp_sql = AcordeonSeccion()
        self.acc_cmp_sql.setSizePolicy(SIZE_POLICY_IGNORED, self.acc_cmp_sql.sizePolicy().verticalPolicy())
        cont_sql = QWidget()
        v_sql = QVBoxLayout(cont_sql)
        v_sql.setContentsMargins(0, 0, 0, 0)
        v_sql.setSpacing(6)
        self.chk_cmp_usar_sql = self._reg(ToggleSwitch(), "cmp_chk_usar_sql")
        self._reg(self.chk_cmp_usar_sql, "cmp_tip_usar_sql", kind="tooltip")
        v_sql.addWidget(self.chk_cmp_usar_sql)
        self.cb_cmp_query_a = self._crear_combo_consulta_cmp()
        self.txt_cmp_sql_a = self._crear_texto_sql_cmp()
        self.cb_cmp_query_b = self._crear_combo_consulta_cmp()
        self.txt_cmp_sql_b = self._crear_texto_sql_cmp()
        self._fill_cmp_query_combos(defecto_a="preplot_all", defecto_b="postplot_all")
        for key, cb, txt in (
            ("cmp_lbl_query_a", self.cb_cmp_query_a, self.txt_cmp_sql_a),
            ("cmp_lbl_query_b", self.cb_cmp_query_b, self.txt_cmp_sql_b),
        ):
            lbl = self._reg(QLabel(), key)
            lbl.setStyleSheet(ESTILO_ROTULO_TENUE)
            v_sql.addWidget(lbl)
            v_sql.addWidget(cb)
            v_sql.addWidget(txt)
        lbl_nota = self._reg(QLabel(), "cmp_note_sql")
        lbl_nota.setWordWrap(True)
        lbl_nota.setStyleSheet(ESTILO_ROTULO_TENUE)
        v_sql.addWidget(lbl_nota)
        self.acc_cmp_sql.set_contenido(cont_sql)
        v_c.addWidget(self.acc_cmp_sql)
        self.cb_cmp_query_a.currentIndexChanged.connect(lambda _i: self._on_cmp_query_cambiada("a"))
        self.cb_cmp_query_b.currentIndexChanged.connect(lambda _i: self._on_cmp_query_cambiada("b"))
        self.chk_cmp_usar_sql.toggled.connect(self._on_cmp_sql_toggled)
        self._actualizar_resumen_cmp_sql()
        v_c.addStretch(1)
        self.btn_comparar = self._reg(QPushButton(), "cmp_btn_comparar")
        self.btn_comparar.setStyleSheet(ESTILO_BTN_PRIMARIO)
        self.btn_comparar.setMinimumHeight(36)
        self.btn_comparar.setCursor(_valor_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.btn_comparar.clicked.connect(self.comparar)
        v_c.addWidget(self.btn_comparar)

        for g_ in (grp_fuente, grp_comp):
            g_.setSizePolicy(SIZE_POLICY_IGNORED, g_.sizePolicy().verticalPolicy())
        grid_arriba = QGridLayout()
        grid_arriba.setColumnStretch(0, 1)
        grid_arriba.setColumnStretch(1, 1)
        grid_arriba.setHorizontalSpacing(10)
        grid_arriba.addWidget(grp_fuente, 0, 0)
        grid_arriba.addWidget(grp_comp, 0, 1)
        v.addLayout(grid_arriba)

        # ---- Centro: resumen + tabla de discrepancias ----
        self.lbl_resumen_comparacion = QLabel("")
        self.lbl_resumen_comparacion.setWordWrap(True)
        self.lbl_resumen_comparacion.setStyleSheet(ESTILO_ROTULO_TENUE)
        v.addWidget(self.lbl_resumen_comparacion)

        self.tbl_resultado = QTableWidget(0, 7)
        self.tbl_resultado.setHorizontalHeaderLabels(self._comparar_headers())
        self.tbl_resultado.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_resultado.verticalHeader().setDefaultSectionSize(24)
        self.tbl_resultado.setMinimumHeight(240)
        v.addWidget(self.tbl_resultado, 1)

        # ---- Barra inferior unificada: todas las salidas ----
        barra = QHBoxLayout()
        barra.addWidget(self._boton_barra("cmp_tb_capa", "cmp_tip_capa", self.crear_capa_comparacion))
        barra.addWidget(self._boton_barra("cmp_tb_csv", "cmp_tip_csv", self.exportar_comparacion))
        barra.addStretch(1)
        self.chk_subir_preplot = self._reg(ToggleSwitch(), "cmp_chk_subir_preplot")
        self.chk_subir_preplot.setChecked(True)
        barra.addWidget(self.chk_subir_preplot)
        barra.addSpacing(8)
        self.btn_subir_comparacion = self._reg(QPushButton(), "cmp_btn_guardar")
        self.btn_subir_comparacion.setStyleSheet(ESTILO_BTN_SUBIR_VERDE)
        self.btn_subir_comparacion.setMinimumHeight(40)
        self.btn_subir_comparacion.setMinimumWidth(260)
        self.btn_subir_comparacion.setCursor(_valor_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.btn_subir_comparacion.clicked.connect(self.subir_a_bd)
        barra.addWidget(self.btn_subir_comparacion)
        v.addLayout(barra)

        w.setStyleSheet(ESTILO_TARJETAS)
        self._toggle_fuente_diseno()
        return w

    # -- Comparar dos consultas SQL (v2.68.0) -------------------------------
    def _crear_combo_consulta_cmp(self):
        cb = QComboBox()
        cb.setSizeAdjustPolicy(_valor_enum(QComboBox, "AdjustToMinimumContentsLengthWithIcon", "SizeAdjustPolicy"))
        cb.setMinimumContentsLength(14)
        return cb

    def _crear_texto_sql_cmp(self):
        txt = QPlainTextEdit()
        alto = (
            txt.fontMetrics().lineSpacing() * 2
            + int(txt.document().documentMargin() * 2) + 2 * txt.frameWidth() + 2
        )
        txt.setFixedHeight(alto)
        return txt

    def _sql_para_clave_consulta(self, key):
        """SQL asociado a una entrada de los combos de consultas (preset de
        fábrica, con el override que el usuario haya guardado, o consulta
        propia/importada); None para "Personalizada"."""
        if not key:
            return None
        if isinstance(key, str) and key.startswith("custom_query:"):
            nombre = key[len("custom_query:"):]
            for q in self._load_custom_queries():
                if q["name"] == nombre:
                    return q["sql"]
            return None
        return self._get_effective_preset_sql(key)

    def _fill_cmp_query_combos(self, keep_selection=False, defecto_a=None, defecto_b=None):
        """(Re)llena los combos A y B de "Comparar dos consultas SQL" con la
        MISMA lista de "Base de Datos": consultas de ejemplo + las propias
        guardadas/importadas (p.ej. las de un .qrylt de GPSeismic)."""
        if not hasattr(self, "cb_cmp_query_a"):
            return
        for cb, txt, defecto in (
            (self.cb_cmp_query_a, self.txt_cmp_sql_a, defecto_a),
            (self.cb_cmp_query_b, self.txt_cmp_sql_b, defecto_b),
        ):
            actual = cb.currentData() if (keep_selection and cb.count()) else defecto
            cb.blockSignals(True)
            cb.clear()
            for key in self._PRESET_ORDER:
                cb.addItem(self.t(self._PRESET_KEY_LABELS[key]), key)
            for q in self._load_custom_queries():
                cb.addItem(q["name"], f"custom_query:{q['name']}")
            idx = cb.findData(actual) if actual is not None else -1
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)
            if not keep_selection:
                sql = self._sql_para_clave_consulta(cb.currentData())
                if sql:
                    txt.setPlainText(sql)
        self._actualizar_resumen_cmp_sql()

    def _on_cmp_query_cambiada(self, lado):
        cb = self.cb_cmp_query_a if lado == "a" else self.cb_cmp_query_b
        txt = self.txt_cmp_sql_a if lado == "a" else self.txt_cmp_sql_b
        sql = self._sql_para_clave_consulta(cb.currentData())
        if sql:
            txt.setPlainText(sql)
        self._actualizar_resumen_cmp_sql()

    def _cmp_sql_activo(self):
        chk = getattr(self, "chk_cmp_usar_sql", None)
        return chk is not None and chk.isChecked()

    def _on_cmp_sql_toggled(self, activo):
        # Con consultas SQL, la fuente (CSV/PREPLOT) y la tabla a comparar
        # no se usan: se deshabilitan para que no confundan.
        self.grp_cmp_fuente.setEnabled(not activo)
        self.cb_tabla_levantado.setEnabled(not activo)
        self._toggle_fuente_diseno()
        self._actualizar_resumen_cmp_sql()

    def _actualizar_resumen_cmp_sql(self):
        if not hasattr(self, "acc_cmp_sql"):
            return
        if self._cmp_sql_activo():
            resumen = self.t(
                "cmp_acc_resumen_on", a=self.cb_cmp_query_a.currentText(), b=self.cb_cmp_query_b.currentText()
            )
        else:
            resumen = self.t("cmp_acc_resumen_off")
        self.acc_cmp_sql.set_textos(self.t("cmp_acc_titulo"), resumen)

    def _puntos_desde_consulta(self, sql, dest_crs):
        """Ejecuta `sql` (sólo SELECT) y devuelve sus puntos [{name,x,y,z}]
        en el CRS de trabajo. Lanza ValueError con un mensaje legible."""
        try:
            cols, rows = db_schema.run_query(self.conn, sql)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(self.t("cmp_err_sql_ejecutar", error=e))
        try:
            crudos = csv_matcher.points_from_query_rows(cols, rows)
        except ValueError as e:
            clave = "cmp_err_sql_sin_nombre" if str(e) == "no_name" else "cmp_err_sql_sin_coords"
            raise ValueError(self.t(clave))
        puntos = []
        for p in crudos:
            if p["kind"] == "geo":
                x, y = _transform_xy(p["a"], p["b"], self.crs_wgs84, dest_crs, self.project)
            else:
                x, y = p["a"], p["b"]
            puntos.append({"name": p["name"], "x": x, "y": y, "z": p["z"]})
        return puntos

    def _preparar_comparacion_sql(self, dest_crs):
        """Arma (diseño, levantado, etiqueta_diseño, etiqueta_levantado) a
        partir de las consultas A (diseño) y B (levantado); None si algo
        falla (ya avisó al usuario)."""
        nombre_a = self.cb_cmp_query_a.currentText()
        nombre_b = self.cb_cmp_query_b.currentText()
        resultados = []
        for letra, sql, nombre in (
            ("A", self.txt_cmp_sql_a.toPlainText(), nombre_a),
            ("B", self.txt_cmp_sql_b.toPlainText(), nombre_b),
        ):
            try:
                puntos = self._puntos_desde_consulta(sql, dest_crs)
            except ValueError as e:
                QMessageBox.warning(self, self.t("cmp_err_sql_titulo", letra=letra, nombre=nombre), str(e))
                return None
            if not puntos:
                QMessageBox.warning(
                    self, self.t("cmp_err_sql_titulo", letra=letra, nombre=nombre), self.t("cmp_err_sql_vacia")
                )
                return None
            resultados.append(puntos)
        return resultados[0], resultados[1], self.t("cmp_origen_sql", nombre=nombre_a), nombre_b

    def _actualizar_crs_csv_habilitado(self, *_args):
        if getattr(self, "cont_csv_crs", None) is not None:
            self.cont_csv_crs.setEnabled(self.rb_plana.isChecked())

    def _comparar_headers(self):
        return [
            self.t("col_name_design"), self.t("col_name_surveyed"), self.t("col_match_type"),
            self.t("col_delta_x"), self.t("col_delta_y"), self.t("col_dist_2d"), self.t("col_within_tol"),
        ]

    def _toggle_fuente_diseno(self):
        usa_csv = self.rb_fuente_csv.isChecked()
        # Con "Tabla PREPLOT" el formulario de mapeo del CSV se OCULTA.
        self.grp_csv.setVisible(usa_csv)
        self._actualizar_crs_csv_habilitado()
        self.lbl_preplot_source_note.setVisible(not usa_csv)
        usa_sql = self._cmp_sql_activo()
        self.chk_subir_preplot.setEnabled(usa_csv and not usa_sql)
        if usa_sql:
            self.chk_subir_preplot.setChecked(False)
            self.chk_subir_preplot.setToolTip(self.t("cmp_tip_subir_sql"))
        elif not usa_csv:
            self.chk_subir_preplot.setChecked(False)
            self.chk_subir_preplot.setToolTip(self.t("tip_upload_preplot_disabled"))
        else:
            self.chk_subir_preplot.setToolTip("")

    def cargar_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("dlg_load_csv_title"), "", self.t("filter_csv"))
        if not path:
            return
        try:
            header = csv_matcher.read_csv_header(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_csv_read", error=e))
            return
        if not header:
            QMessageBox.warning(self, self.t("warn_csv_empty_title"), self.t("warn_csv_empty_body"))
            return

        self.lbl_csv_path.setText(path)
        for cb in (self.cb_col_nombre, self.cb_col_x, self.cb_col_y):
            cb.clear()
            cb.addItems(header)
        self.cb_col_z.clear()
        self.cb_col_z.addItem(self.t("none_option"))
        self.cb_col_z.addItems(header)

        # Adivina columnas típicas para ahorrarle clics al usuario.
        self._preseleccionar_columna(self.cb_col_nombre, ["nombre", "name", "punto", "codigo", "código", "id", "station"])
        self._preseleccionar_columna(self.cb_col_x, ["este", "easting", "x", "long", "lon"])
        self._preseleccionar_columna(self.cb_col_y, ["norte", "northing", "y", "lat"])
        self._preseleccionar_columna(self.cb_col_z, ["cota", "z", "altura", "elev", "height"])

    @staticmethod
    def _preseleccionar_columna(combo: QComboBox, candidatos):
        """Preselecciona, en `combo`, la columna/campo cuyo nombre mejor
        matchee alguno de `candidatos` (ambos comparados en minúsculas).
        Prioriza una coincidencia exacta, luego una coincidencia de
        palabra completa (separada por algo que no sea letra/número), y
        sólo al final una coincidencia de simple substring -- así un
        candidato corto y genérico como "id" no termina eligiendo, por
        ejemplo, el campo interno "fid" que agregan algunos formatos
        (GeoPackage) por encima de un campo obviamente mejor como
        "Nombre" o "Name" (v2.7.0, al reusar esto para elegir campos de
        una capa de QGIS en vez de sólo columnas de un CSV)."""
        mejor_idx = None
        mejor_puntaje = -1
        for i in range(combo.count()):
            texto = combo.itemText(i).strip().lower()
            if not texto:
                continue
            for rango, candidato in enumerate(candidatos):
                c = candidato.strip().lower()
                if not c:
                    continue
                if texto == c:
                    puntaje = 1000 - rango
                elif re.search(r'(?:^|[^a-z0-9])' + re.escape(c) + r'(?:[^a-z0-9]|$)', texto):
                    puntaje = 500 - rango
                elif c in texto:
                    puntaje = 100 - rango
                else:
                    continue
                if puntaje > mejor_puntaje:
                    mejor_puntaje = puntaje
                    mejor_idx = i
                break
        if mejor_idx is not None:
            combo.setCurrentIndex(mejor_idx)

    def _fetch_levantado_xy(self, tabla: str, dest_crs: QgsCoordinateReferenceSystem):
        """Lee Station_Text/coordenadas WGS84 de `tabla` (POSTPLOT o
        PREPLOT) y las transforma a `dest_crs`. Se usa tanto para el
        lado "levantado" de la comparación como, cuando la fuente de
        diseño elegida es PREPLOT, para ese mismo lado de diseño."""
        cur = self.conn.execute(
            # `tabla` siempre es "POSTPLOT" o "PREPLOT", pasado hardcodeado por el propio plugin (ver docstring de este método)
            f"SELECT Station_Text, WGS84_Latitude, WGS84_Longitude, WGS84_Height FROM {tabla} "  # nosec B608
            f"WHERE WGS84_Latitude IS NOT NULL AND WGS84_Longitude IS NOT NULL"
        )
        puntos = []
        for name, lat, lon, height in cur.fetchall():
            if name is None:
                continue
            x, y = _transform_xy(lon, lat, self.crs_wgs84, dest_crs, self.project)
            puntos.append({"name": str(name).strip(), "x": x, "y": y, "z": height, "lat": lat, "lon": lon})
        return puntos

    def _calcular_preplot_track_azimuths(self, dest_crs: QgsCoordinateReferenceSystem, line_digits: int) -> dict:
        """Calcula el rumbo (azimut, grados 0-360) de cada línea de
        PREPLOT del proyecto, agrupando sus puntos por Track y
        ajustando la mejor recta a través de ellos (ver
        `_fit_line_azimuth_deg`). Es el reemplazo, basado en la propia
        geometría del proyecto, del archivo CRK que GPSeismic usa para
        lo mismo (ver la nota junto a `_fit_line_azimuth_deg`).

        Devuelve {track_normalizado (str): azimut_grados}. Vacío si no
        hay proyecto abierto o la tabla PREPLOT no tiene puntos
        usables. El Track de cada punto se toma de la columna Track de
        la tabla si está poblada (caso normal: generado por la propia
        pestaña "Preplot Sísmico") y, si no, se deriva de su nombre con
        la misma heurística de dígitos que el resto del plugin."""
        if self.conn is None:
            return {}
        try:
            cur = self.conn.execute(
                "SELECT Station_Text, Track, Bin, Station_Value, WGS84_Latitude, WGS84_Longitude "
                "FROM PREPLOT WHERE WGS84_Latitude IS NOT NULL AND WGS84_Longitude IS NOT NULL"
            )
            filas = cur.fetchall()
        except Exception:
            return {}

        grupos: "dict[str, list]" = {}
        for name, track, bin_, station_value, lat, lon in filas:
            name = (str(name).strip() if name is not None else "")
            track_key = _normalize_track_key(track)
            if track_key is None:
                track_key = _normalize_track_key(_track_bin_heuristic(name, line_digits)[0])
            if track_key is None:
                continue
            if bin_ is not None:
                orden = bin_
            elif station_value is not None:
                orden = station_value
            else:
                _, bin_heur = _track_bin_heuristic(name, line_digits)
                try:
                    orden = float(bin_heur) if bin_heur is not None else 0.0
                except ValueError:
                    orden = 0.0
            x, y = _transform_xy(lon, lat, self.crs_wgs84, dest_crs, self.project)
            grupos.setdefault(track_key, []).append((orden, x, y))

        azimuts = {}
        for track_key, puntos in grupos.items():
            puntos.sort(key=lambda t: t[0])
            az = _fit_line_azimuth_deg([(px, py) for _, px, py in puntos])
            if az is not None:
                azimuts[track_key] = az
        return azimuts

    def comparar(self):
        if not self._require_project():
            return
        dest_crs = self._working_crs()

        usa_sql = self._cmp_sql_activo()
        if usa_sql:
            preparado = self._preparar_comparacion_sql(dest_crs)
            if preparado is None:
                return
            diseno, levantado, origen_diseno_label, tabla = preparado
        elif self.rb_fuente_csv.isChecked():
            csv_path = self.lbl_csv_path.text()
            if not csv_path:
                QMessageBox.information(self, self.t("info_missing_csv_title"), self.t("info_missing_csv_body"))
                return

            name_col = self.cb_col_nombre.currentText()
            x_col = self.cb_col_x.currentText()
            y_col = self.cb_col_y.currentText()
            z_col = self.cb_col_z.currentText()
            z_col = None if z_col in ("", self.t("none_option")) else z_col

            try:
                diseno_raw = csv_matcher.read_csv_points(csv_path, name_col, x_col, y_col, z_col)
            except Exception as e:
                QMessageBox.critical(self, self.t("err_title"), self.t("err_csv_columns", error=e))
                return
            if not diseno_raw:
                QMessageBox.warning(self, self.t("warn_csv_no_data_title"), self.t("warn_csv_no_data_body"))
                return

            src_crs_csv = self.crs_wgs84 if self.rb_geografica.isChecked() else (
                self.csv_crs_widget.crs() if self.csv_crs_widget is not None else self.crs_wgs84
            )
            diseno = []
            for p in diseno_raw:
                x, y = _transform_xy(p["x"], p["y"], src_crs_csv, dest_crs, self.project)
                diseno.append({"name": p["name"], "x": x, "y": y, "z": p["z"], "row": p["row"]})
            origen_diseno_label = os.path.basename(csv_path)
        else:
            diseno_pre = self._fetch_levantado_xy("PREPLOT", dest_crs)
            if not diseno_pre:
                QMessageBox.warning(self, self.t("warn_no_points_title"), self.t("warn_no_points_body", tabla="PREPLOT"))
                return
            diseno = [{"name": p["name"], "x": p["x"], "y": p["y"], "z": p["z"]} for p in diseno_pre]
            origen_diseno_label = self.t("origen_diseno_preplot")

        self.design_points = diseno
        self._origen_diseno_label = origen_diseno_label

        if not usa_sql:
            tabla = self.cb_tabla_levantado.currentText()
            if not self.rb_fuente_csv.isChecked() and tabla == "PREPLOT":
                QMessageBox.warning(self, self.t("warn_same_table_title"), self.t("warn_same_table_body"))
                return

            levantado = self._fetch_levantado_xy(tabla, dest_crs)
            if not levantado:
                QMessageBox.warning(self, self.t("warn_no_points_title"), self.t("warn_no_points_body", tabla=tabla))
                return

        tolerancia = self.spn_tolerancia.value()
        aproximado = self.chk_match_aproximado.isChecked()
        self.match_result = csv_matcher.match_by_name(levantado, diseno, tolerancia_m=tolerancia, permitir_aproximado=aproximado)
        self._llenar_tabla_resultado(self.match_result)

        self.lbl_resumen_comparacion.setText(self.t(
            "lbl_compare_summary",
            matched=self.match_result.n_matched,
            tol=tolerancia,
            within=self.match_result.n_dentro_tolerancia,
            only_design=len(self.match_result.solo_en_diseno),
            only_surveyed=len(self.match_result.solo_en_levantado),
            tabla=tabla,
        ))

    def _llenar_tabla_resultado(self, result: csv_matcher.MatchResult):
        self.tbl_resultado.setRowCount(len(result.matched))
        for row, m in enumerate(result.matched):
            valores = [
                m["name_diseno"], m["name_levantado"], m["tipo_match"],
                f"{m['delta_x']:.3f}", f"{m['delta_y']:.3f}", f"{m['distancia_2d']:.3f}",
                self.t("yes") if m["dentro_tolerancia"] else self.t("no"),
            ]
            dentro = m["dentro_tolerancia"]
            # Tinte sutil por fila (verde: dentro de tolerancia; rojo suave:
            # fuera), con texto oscuro fijo para que se lea también con un
            # tema oscuro; la distancia 2D se resalta en negrita si se pasa.
            color = COLOR_CMP_DENTRO if dentro else COLOR_CMP_FUERA
            valores[COMPARAR_COL_TOL] = ("✔ " if dentro else "✖ ") + valores[COMPARAR_COL_TOL]
            for col, val in enumerate(valores):
                item = QTableWidgetItem(str(val))
                item.setBackground(color)
                item.setForeground(COLOR_CMP_TEXTO)
                if not dentro and col in (COMPARAR_COL_DIST, COMPARAR_COL_TOL):
                    fuente = item.font()
                    fuente.setBold(True)
                    item.setFont(fuente)
                self.tbl_resultado.setItem(row, col, item)

    def crear_capa_comparacion(self):
        if self.match_result is None or not self.match_result.matched:
            QMessageBox.information(self, self.t("info_no_results_title"), self.t("info_no_results_body"))
            return
        dest_crs = self._working_crs()
        layer = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", "Comparación diseño vs levantado", "memory")
        prov = layer.dataProvider()
        prov.addAttributes([
            QgsField("nombre", FIELD_STRING),
            QgsField("tipo_match", FIELD_STRING),
            QgsField("delta_este", FIELD_DOUBLE),
            QgsField("delta_norte", FIELD_DOUBLE),
            QgsField("dist_2d", FIELD_DOUBLE),
            QgsField("dentro_tol", FIELD_INT),
        ])
        layer.updateFields()

        feats = []
        for m in self.match_result.matched:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(m["x_levantado"], m["y_levantado"])))
            f.setAttributes([
                m["name_levantado"], m["tipo_match"], m["delta_x"], m["delta_y"],
                m["distancia_2d"], 1 if m["dentro_tolerancia"] else 0,
            ])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()

        categorias = []
        for valor, color, etiqueta in ((1, "#33a02c", "Dentro de tolerancia"), (0, "#e31a1c", "Fuera de tolerancia")):
            symbol = QgsMarkerSymbol.createSimple({"name": "circle", "size": "3", "color": color})
            categorias.append(QgsRendererCategory(valor, symbol, etiqueta))
        layer.setRenderer(QgsCategorizedSymbolRenderer("dentro_tol", categorias))
        layer.triggerRepaint()

        self.project.addMapLayer(layer)
        # Ver el comentario equivalente en `_crear_capa_puntos_dc`: sin
        # procesar los eventos pendientes aquí, la capa puede no
        # aparecer todavía en `iface.mapCanvas().layers()` justo después
        # de agregarla.
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)

    def exportar_comparacion(self):
        if self.match_result is None:
            QMessageBox.information(self, self.t("info_no_results_title"), self.t("info_no_results_body_generic"))
            return
        path, _ = QFileDialog.getSaveFileName(self, self.t("dlg_export_compare_title"), "comparacion.csv", self.t("filter_csv"))
        if not path:
            return
        campos = [
            "name_diseno", "name_levantado", "tipo_match",
            "x_diseno", "y_diseno", "z_diseno",
            "x_levantado", "y_levantado", "z_levantado",
            "delta_x", "delta_y", "delta_z", "distancia_2d", "distancia_3d", "dentro_tolerancia",
        ]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                wr = csv.DictWriter(f, fieldnames=campos)
                wr.writeheader()
                for m in self.match_result.matched:
                    wr.writerow({k: m.get(k) for k in campos})
            QMessageBox.information(self, self.t("msg_export_ok_title"), self.t("msg_export_compare_body", path=path))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_export_generic", error=e))

    @_escritura()
    def subir_a_bd(self):
        if not self._require_project():
            return
        if self.match_result is None:
            QMessageBox.information(self, self.t("info_no_results_title"), self.t("info_no_results_body_generic"))
            return

        try:
            n_pre = 0
            if (
                self.chk_subir_preplot.isChecked() and self.design_points
                and self.rb_fuente_csv.isChecked() and not self._cmp_sql_activo()
            ):
                dest_crs = self._working_crs()
                filas_preplot = []
                for p in self.design_points:
                    lon, lat = None, None
                    if dest_crs != self.crs_wgs84:
                        lon, lat = _transform_xy(p["x"], p["y"], dest_crs, self.crs_wgs84, self.project)
                    filas_preplot.append({
                        "Station_Text": p["name"],
                        "Local_Easting": p["x"],
                        "Local_Northing": p["y"],
                        "WGS84_Longitude": lon,
                        "WGS84_Latitude": lat,
                        "WGS84_Height": p.get("z"),
                        "Local_System": dest_crs.authid(),
                        "Populate_Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Processor": "GNSSeismic (QGIS) - CSV de diseño",
                    })
                n_pre = db_schema.insert_rows(self.conn, "PREPLOT", db_schema.PREPLOT_COLUMNS, filas_preplot)

            origen = getattr(self, "_origen_diseno_label", "")
            filas_comp = []
            for m in self.match_result.matched:
                filas_comp.append({
                    "Station_Text": m["name_levantado"],
                    "Origen_Diseno": origen,
                    "Este_Diseno": m["x_diseno"], "Norte_Diseno": m["y_diseno"], "Cota_Diseno": m["z_diseno"],
                    "Este_Levantado": m["x_levantado"], "Norte_Levantado": m["y_levantado"], "Cota_Levantada": m["z_levantado"],
                    "Delta_Este": m["delta_x"], "Delta_Norte": m["delta_y"], "Delta_Cota": m["delta_z"],
                    "Distancia_2D": m["distancia_2d"], "Distancia_3D": m["distancia_3d"],
                    "Dentro_Tolerancia": 1 if m["dentro_tolerancia"] else 0,
                    "Tolerancia_m": self.spn_tolerancia.value(),
                })
            n_comp = db_schema.insert_comparacion_rows(self.conn, filas_comp)

            self.actualizar_conteos()
            extra = self.t("msg_upload_extra_preplot", n_pre=n_pre) if n_pre else ""
            QMessageBox.information(self, self.t("ok_title"), self.t("msg_upload_body", n_comp=n_comp, extra=extra))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_title"), self.t("err_upload_db", error=e, trace=traceback.format_exc()))

    # -- Sección: Base de Datos --------------------------------------------
    # -- Sección: Base de Datos (rediseño v2.66.0) ---------------------------
    # Arriba, dos tarjetas lado a lado (50/50): "Consola SQL" (selector de
    # consulta, cuadro de 3 líneas y barra de acciones) y "Edición rápida:
    # Buscar y reemplazar" (cuadrícula compacta). En el medio, la tabla de
    # resultados con un encabezado que cuenta los registros, ocupando todo el
    # alto sobrante. Abajo, dos tarjetas: "Mapeo de columnas" (cuadrícula de
    # 3 columnas + interruptor) y "Formato de salida" (formato + opciones SPS
    # sólo si se elige SPS + botón "Exportar...").
    def _build_tab_bd(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(6)
        v.addWidget(self._crear_banner_solo_lectura())
        self._agregar_boton_ayuda(
            v, [
                "bd_intro", "lbl_query_map_note", "lbl_query_edit_note",
                "note_import_export_queries", "lbl_search_replace_note",
                "note_bd_botones",
            ], "tab5_title",
        )

        # ---- Tarjeta izquierda: Consola SQL ----
        grp_sql, col_sql = self._tarjeta_card("bd_card_sql")

        fila_preset = QHBoxLayout()
        fila_preset.addWidget(self._reg(QLabel(), "lbl_query_preset"))
        self.cb_query_preset = QComboBox()
        self.cb_query_preset.setSizeAdjustPolicy(
            _valor_enum(QComboBox, "AdjustToMinimumContentsLengthWithIcon", "SizeAdjustPolicy")
        )
        self.cb_query_preset.setMinimumContentsLength(14)
        self._fill_query_preset_combo()
        self.cb_query_preset.currentIndexChanged.connect(self._aplicar_preset_consulta)
        fila_preset.addWidget(self.cb_query_preset, 1)

        # Renombrar / Importar / Exportar consultas guardadas (antes tres
        # botones sueltos): ahora un único botón "⋯" con un menú. Las
        # consultas guardadas con "Guardar" viven sólo en QSettings de ESTA
        # máquina/perfil de QGIS; "Importar consultas..." las trae de un
        # .qrylt de GPSeismic o de un .json exportado antes con "Exportar
        # consultas..." -- ver `_parse_qrylt_text`/
        # `_parse_custom_queries_json`/`_fusionar_consultas_importadas`
        # (funciones puras, con pruebas unitarias).
        self.btn_mas_consultas = QPushButton("⋯")
        self.btn_mas_consultas.setStyleSheet(ESTILO_BTN_ICONO)
        self.btn_mas_consultas.setMinimumWidth(40)
        self._reg(self.btn_mas_consultas, "bd_tip_mas", kind="tooltip")
        menu_consultas = QMenu(self.btn_mas_consultas)
        for key, slot in (
            ("btn_rename_query", self.renombrar_consulta_actual),
            ("btn_import_queries", self.importar_consultas_guardadas),
            ("btn_export_queries", self.exportar_consultas_guardadas),
        ):
            accion = self._reg(QAction(menu_consultas), key)
            self._reg(accion, "tip_" + key, kind="tooltip")
            accion.triggered.connect(slot)
            menu_consultas.addAction(accion)
        self.btn_mas_consultas.setMenu(menu_consultas)
        fila_preset.addWidget(self.btn_mas_consultas)
        col_sql.addLayout(fila_preset)

        # Cuadro de texto de tamaño fijo: 3 líneas.
        self.txt_sql = QPlainTextEdit()
        self.txt_sql.setPlainText(self._get_effective_preset_sql("postplot_all"))
        alto_3_lineas = (
            self.txt_sql.fontMetrics().lineSpacing() * 3
            + int(self.txt_sql.document().documentMargin() * 2)
            + 2 * self.txt_sql.frameWidth() + 2
        )
        self.txt_sql.setFixedHeight(alto_3_lineas)
        col_sql.addWidget(self.txt_sql)

        # Barra de acciones icónica, justo debajo del cuadro. Cada botón
        # tiene un tooltip ("tip_btn_...") con la explicación completa (ver
        # también "note_bd_botones" en el "?" de arriba).
        fila_ejecutar = QHBoxLayout()
        self.btn_run_query = self._boton_barra("bd_tb_run", "tip_btn_run_query", self.ejecutar_consulta)
        self.btn_save_query = self._boton_barra("bd_tb_save", "tip_btn_save_query", self.guardar_consulta_actual)
        self.btn_delete_query = self._boton_barra(
            "bd_tb_delete", "tip_btn_delete_query_results", self.borrar_resultados_consulta
        )
        self.btn_delete_query.setEnabled(False)
        self.btn_delete_query.setStyleSheet(ESTILO_BTN_BARRA + "QToolButton:enabled { color: #b3261e; font-weight: 600; }")
        self.btn_save_query_changes = self._boton_barra(
            "bd_tb_apply", "tip_btn_save_query_changes", self.guardar_cambios_consulta
        )
        self.btn_save_query_changes.setEnabled(False)
        for b in (self.btn_run_query, self.btn_save_query, self.btn_delete_query, self.btn_save_query_changes):
            fila_ejecutar.addWidget(b)
        fila_ejecutar.addStretch(1)
        col_sql.addLayout(fila_ejecutar)
        col_sql.addStretch(1)

        # ---- Tarjeta derecha: Edición rápida (Buscar y reemplazar) ----
        # Pedido explícito del usuario: buscar (o reemplazar en bloque) por
        # CUALQUIER columna de POSTPLOT/PREPLOT/COMPARACION sin escribir SQL.
        # "Buscar" arma un SELECT equivalente y lo corre con el mismo
        # mecanismo de la pestaña (`ejecutar_consulta`), así el resultado
        # queda en la misma tabla, con edición en línea, borrado, mapeo y
        # exportación ya funcionando -- ver `buscar_por_columna`.
        # "Reemplazar" SÍ escribe: pide confirmación y muestra antes
        # cuántas filas se van a modificar (`reemplazar_por_columna`/
        # `db_schema.replace_in_column`).
        grp_buscar, v_buscar = self._tarjeta_card("bd_card_buscar")

        self.cb_sr_tabla = QComboBox()
        for tabla in ("POSTPLOT", "PREPLOT", "COMPARACION"):
            self.cb_sr_tabla.addItem(tabla, tabla)
        self.cb_sr_tabla.currentIndexChanged.connect(self._poblar_columnas_buscar_reemplazar)
        self.cb_sr_columna = QComboBox()
        self.cb_sr_columna.setSizeAdjustPolicy(
            _valor_enum(QComboBox, "AdjustToMinimumContentsLengthWithIcon", "SizeAdjustPolicy")
        )
        self.cb_sr_columna.setMinimumContentsLength(10)
        self.chk_sr_exacto = self._reg(QCheckBox(), "chk_sr_exact")

        fila_1 = QHBoxLayout()
        fila_1.addWidget(self._reg(QLabel(), "lbl_sr_table"))
        fila_1.addWidget(self.cb_sr_tabla, 1)
        fila_1.addSpacing(6)
        fila_1.addWidget(self._reg(QLabel(), "lbl_sr_column"))
        fila_1.addWidget(self.cb_sr_columna, 1)
        fila_1.addSpacing(6)
        fila_1.addWidget(self.chk_sr_exacto)
        v_buscar.addLayout(fila_1)

        self.txt_sr_buscar = QLineEdit()
        self._reg(self.txt_sr_buscar, "ph_sr_search", kind="placeholder")
        self.txt_sr_reemplazar = QLineEdit()
        self._reg(self.txt_sr_reemplazar, "ph_sr_replace", kind="placeholder")
        fila_2 = QHBoxLayout()
        fila_2.addWidget(self._reg(QLabel(), "lbl_sr_search"))
        fila_2.addWidget(self.txt_sr_buscar, 1)
        fila_2.addSpacing(6)
        fila_2.addWidget(self._reg(QLabel(), "lbl_sr_replace"))
        fila_2.addWidget(self.txt_sr_reemplazar, 1)
        v_buscar.addLayout(fila_2)

        fila_sr_botones = QHBoxLayout()
        fila_sr_botones.addStretch(1)
        self.btn_sr_buscar = self._boton_barra("bd_tb_search", "tip_btn_sr_search", self.buscar_por_columna)
        self.btn_sr_reemplazar = self._boton_barra("bd_tb_replace", "tip_btn_sr_replace_all", self.reemplazar_por_columna)
        self.btn_sr_reemplazar.setStyleSheet(ESTILO_BTN_BARRA + "QToolButton { color: #b3261e; font-weight: 600; }")
        fila_sr_botones.addWidget(self.btn_sr_buscar)
        fila_sr_botones.addWidget(self.btn_sr_reemplazar)
        v_buscar.addLayout(fila_sr_botones)
        v_buscar.addStretch(1)

        # Mitad y mitad de verdad: `QSizePolicy.Ignored` le dice al layout
        # que IGNORE el sizeHint de cada tarjeta, y un QGridLayout con las
        # dos columnas al mismo `setColumnStretch` reparte el ancho 50/50
        # sin importar cuánto contenido tenga cada lado.
        for g in (grp_sql, grp_buscar):
            g.setSizePolicy(SIZE_POLICY_IGNORED, g.sizePolicy().verticalPolicy())
        grid_arriba = QGridLayout()
        grid_arriba.setColumnStretch(0, 1)
        grid_arriba.setColumnStretch(1, 1)
        grid_arriba.setHorizontalSpacing(10)
        grid_arriba.addWidget(grp_sql, 0, 0)
        grid_arriba.addWidget(grp_buscar, 0, 1)
        v.addLayout(grid_arriba)
        self._poblar_columnas_buscar_reemplazar()

        # ---- Centro: encabezado con el conteo + tabla de resultados ----
        # Edición de la base desde esta tabla (v2.21.0): doble clic en una
        # celda y "Aplicar" para guardar -- ver `_set_query_table_editable`/
        # `_on_query_cell_changed`/`guardar_cambios_consulta`; sólo se
        # habilita cuando la consulta es tan "borrable" como "editable".
        self.lbl_query_resumen = QLabel()
        self.lbl_query_resumen.setTextFormat(_valor_enum(Qt, "RichText", "TextFormat"))
        v.addWidget(self.lbl_query_resumen)
        self._set_query_resumen(None)

        self.tbl_query = QTableWidget(0, 0)
        self.tbl_query.setMinimumHeight(220)
        self.tbl_query.verticalHeader().setDefaultSectionSize(24)
        self._set_query_table_editable(False)
        self.tbl_query.itemChanged.connect(self._on_query_cell_changed)
        v.addWidget(self.tbl_query, 1)

        # ---- Abajo izquierda: Mapeo de columnas ----
        grp_map, v_map = self._tarjeta_card("bd_card_mapeo")
        self.cb_map_nombre = self._combo_campo()
        self.cb_map_linea = self._combo_campo()
        self.cb_map_punto_sps = self._combo_campo()
        self.cb_map_x = self._combo_campo()
        self.cb_map_y = self._combo_campo()
        self.cb_map_z = self._combo_campo()
        self.cb_map_codigo = self._combo_campo()
        cont_map, g = self._bloque_filas()
        self._celda_campo(g, 0, 0, "bd_map_nombre", self.cb_map_nombre)
        self._celda_campo(g, 0, 1, "bd_map_linea", self.cb_map_linea)
        self._celda_campo(g, 0, 2, "bd_map_punto", self.cb_map_punto_sps)
        self._celda_campo(g, 1, 0, "bd_map_x", self.cb_map_x)
        self._celda_campo(g, 1, 1, "bd_map_y", self.cb_map_y)
        self._celda_campo(g, 1, 2, "bd_map_z", self.cb_map_z)
        self._celda_campo(g, 2, 0, "bd_map_codigo", self.cb_map_codigo)
        v_map.addWidget(cont_map)
        v_map.addStretch(1)
        self.chk_map_geografica = self._reg(ToggleSwitch(), "chk_map_geographic")
        v_map.addWidget(self.chk_map_geografica)

        # ---- Abajo derecha: Formato de salida ----
        # Pedido del usuario (v2.21.0): una única lista desplegable de
        # formato + un solo botón "Exportar...", con Excel (.csv) como
        # cuarto formato. Las opciones de SPS (tipo de punto, índice, código
        # fijo) sólo se muestran si el formato elegido es SPS.
        grp_sal, v_sal = self._tarjeta_card("bd_card_salida")
        fila_fmt = QHBoxLayout()
        fila_fmt.addWidget(self._reg(QLabel(), "lbl_export_format"))
        self.cb_export_format = QComboBox()
        self._fill_export_format_combo()
        fila_fmt.addWidget(self.cb_export_format, 1)
        fila_fmt.addWidget(self._crear_icono_info("bd_export_info"))
        v_sal.addLayout(fila_fmt)

        self.cont_opciones_sps = QWidget()
        v_sps = QVBoxLayout(self.cont_opciones_sps)
        v_sps.setContentsMargins(0, 0, 0, 0)
        v_sps.setSpacing(6)
        self.rb_sps_fuente = self._reg(QRadioButton(), "rb_sps_source")
        self.rb_sps_receptor = self._reg(QRadioButton(), "rb_sps_receiver")
        self.rb_sps_fuente.setChecked(True)
        grupo_sps = QButtonGroup(self)
        grupo_sps.addButton(self.rb_sps_fuente)
        grupo_sps.addButton(self.rb_sps_receptor)
        h_sps_tipo = QHBoxLayout()
        h_sps_tipo.addWidget(self._reg(QLabel(), "lbl_sps_point_type"))
        h_sps_tipo.addWidget(self.rb_sps_fuente)
        h_sps_tipo.addWidget(self.rb_sps_receptor)
        h_sps_tipo.addStretch(1)
        v_sps.addLayout(h_sps_tipo)
        self.sp_sps_indice = self._spin_entero(0, 9, 1)
        self.txt_sps_codigo_fijo = QLineEdit()
        self.txt_sps_codigo_fijo.setMaxLength(2)
        self._reg(self.txt_sps_codigo_fijo, "tip_sps_fixed_code", kind="tooltip")
        cont_sps, g = self._bloque_filas(2)
        self._celda_campo(g, 0, 0, "lbl_sps_index", self.sp_sps_indice)
        self._celda_campo(g, 0, 1, "lbl_sps_fixed_code", self.txt_sps_codigo_fijo)
        v_sps.addWidget(cont_sps)
        v_sal.addWidget(self.cont_opciones_sps)
        v_sal.addStretch(1)

        self.btn_export = self._reg(QPushButton(), "btn_export_run")
        self.btn_export.setStyleSheet(ESTILO_BTN_PRIMARIO)
        self.btn_export.setMinimumHeight(36)
        self.btn_export.setCursor(_valor_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.btn_export.clicked.connect(lambda: self.exportar_query(self.cb_export_format.currentData()))
        v_sal.addWidget(self.btn_export)
        self.cb_export_format.currentIndexChanged.connect(self._actualizar_visibilidad_opciones_sps)
        self._actualizar_visibilidad_opciones_sps()

        for g in (grp_map, grp_sal):
            g.setSizePolicy(SIZE_POLICY_IGNORED, g.sizePolicy().verticalPolicy())
        grid_abajo = QGridLayout()
        grid_abajo.setColumnStretch(0, 1)
        grid_abajo.setColumnStretch(1, 1)
        grid_abajo.setHorizontalSpacing(10)
        grid_abajo.addWidget(grp_map, 0, 0)
        grid_abajo.addWidget(grp_sal, 0, 1)
        v.addLayout(grid_abajo)

        w.setStyleSheet(ESTILO_TARJETAS)
        return w

    def _actualizar_visibilidad_opciones_sps(self, *_args):
        """Las opciones de SPS (fuente/receptor, índice, código fijo) sólo
        se ven si el formato de exportación elegido es SPS."""
        if hasattr(self, "cont_opciones_sps"):
            self.cont_opciones_sps.setVisible(self.cb_export_format.currentData() == "sps")

    def _set_query_resumen(self, n, cols=0):
        """Encabezado de la tabla de resultados: "● N registros cargados"
        (verde con datos, ámbar con 0 filas, gris sin consulta). Guarda el
        estado para volver a dibujarlo al cambiar de idioma."""
        self._query_resumen_estado = None if n is None else (n, cols)
        self._render_query_resumen()

    def _render_query_resumen(self):
        if not hasattr(self, "lbl_query_resumen"):
            return
        estado = getattr(self, "_query_resumen_estado", None)
        if estado is None:
            punto, texto = "#9e9e9e", self.t("lbl_query_empty")
        else:
            n, cols = estado
            punto = "#2e9d4a" if n > 0 else "#f9a825"
            texto = self.t("bd_resumen_uno" if n == 1 else "bd_resumen_n", n=n, cols=cols)
        self.lbl_query_resumen.setText(f"<span style='color:{punto}'>&#9679;</span>&nbsp;{texto}")

    # -- Persistencia de "Guardar consulta..." (ver `guardar_consulta_actual`
    # más abajo): dos mecanismos separados en QSettings --
    #   1. Overrides de un preset de fábrica (`_load_preset_overrides` /
    #      `_save_preset_overrides`): permiten cambiar el SQL de un preset
    #      ya existente (ej. "POSTPLOT por tipo (Descriptor)") sin crear
    #      una entrada nueva en el combo -- exactamente lo que pidió el
    #      usuario ("cambiarlo... y que lo pueda guardar sin crear otro").
    #   2. Consultas propias con nombre (`_load_custom_queries` /
    #      `_save_custom_queries`): se agregan al final del combo,
    #      identificadas con la clave `"custom_query:<nombre>"`.
    def _load_preset_overrides(self):
        settings = QSettings()
        raw = settings.value(_SETTINGS_KEY_QUERY_OVERRIDES, "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_preset_overrides(self, overrides):
        settings = QSettings()
        settings.setValue(_SETTINGS_KEY_QUERY_OVERRIDES, json.dumps(overrides))

    def _get_effective_preset_sql(self, key):
        """SQL efectivo de un preset de fábrica: el que el usuario haya
        guardado encima con "Guardar consulta..." (si lo hay), si no el
        original de `_PRESET_SQL`. La opción "custom" (Personalizada)
        nunca tiene SQL propio -- es sólo el texto libre que el usuario
        haya escrito a mano -- así que nunca aparece acá."""
        overrides = self._load_preset_overrides()
        if key in overrides:
            return overrides[key]
        return self._PRESET_SQL.get(key)

    def _load_custom_queries(self):
        settings = QSettings()
        raw = settings.value(_SETTINGS_KEY_CUSTOM_QUERIES, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [q for q in data if isinstance(q, dict) and q.get("name") and "sql" in q]

    def _save_custom_queries(self, queries):
        settings = QSettings()
        settings.setValue(_SETTINGS_KEY_CUSTOM_QUERIES, json.dumps(queries))

    def _fill_query_preset_combo(self, keep_selection=False):
        current_data = self.cb_query_preset.currentData() if (keep_selection and self.cb_query_preset.count()) else "postplot_all"
        self.cb_query_preset.blockSignals(True)
        self.cb_query_preset.clear()
        for key in self._PRESET_ORDER:
            self.cb_query_preset.addItem(self.t(self._PRESET_KEY_LABELS[key]), key)
        for q in self._load_custom_queries():
            self.cb_query_preset.addItem(q["name"], f"custom_query:{q['name']}")
        idx = self.cb_query_preset.findData(current_data)
        self.cb_query_preset.setCurrentIndex(idx if idx >= 0 else 1)
        self.cb_query_preset.blockSignals(False)
        # Que "Comparar dos consultas SQL" vea también las consultas nuevas.
        self._fill_cmp_query_combos(keep_selection=True)

    def _fill_export_format_combo(self, keep_selection=False):
        """Repuebla `cb_export_format` (combo "Formato de exportación:",
        v2.21.0) con sus 4 opciones traducidas -- se llama al construir la
        pestaña y de nuevo en `retranslate_ui()` al cambiar de idioma,
        igual que `_fill_query_preset_combo`."""
        current_data = self.cb_export_format.currentData() if (keep_selection and self.cb_export_format.count()) else "shapefile"
        self.cb_export_format.blockSignals(True)
        self.cb_export_format.clear()
        for key in self._EXPORT_FORMAT_ORDER:
            self.cb_export_format.addItem(self.t(self._EXPORT_FORMAT_LABELS[key]), key)
        idx = self.cb_export_format.findData(current_data)
        self.cb_export_format.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_export_format.blockSignals(False)

    def _aplicar_preset_consulta(self, index):
        key = self.cb_query_preset.itemData(index)
        if not key:
            return
        if isinstance(key, str) and key.startswith("custom_query:"):
            nombre = key[len("custom_query:"):]
            for q in self._load_custom_queries():
                if q["name"] == nombre:
                    self.txt_sql.setPlainText(q["sql"])
                    break
            return
        sql = self._get_effective_preset_sql(key)
        if sql:
            self.txt_sql.setPlainText(sql)

    def _nombre_consulta_actual(self):
        """Nombre legible de la consulta actualmente seleccionada en el
        combo "Consulta de ejemplo:" (`cb_query_preset`): el nombre del
        preset de fábrica, el de una consulta propia ya guardada, o
        "Personalizada" para SQL libre sin preset asociado -- la misma
        lógica de `guardar_consulta_actual` para distinguir ambos casos.
        Pedido explícito del usuario (v2.56.0): que la capa provisional
        que se carga al mapa al ejecutar una consulta (ver
        `_actualizar_capa_provisional_query`) se llame igual que esta
        consulta, en vez de un nombre genérico fijo."""
        key = self.cb_query_preset.currentData()
        if isinstance(key, str) and key.startswith("custom_query:"):
            return key[len("custom_query:"):]
        if isinstance(key, str) and key in self._PRESET_KEY_LABELS:
            return self.t(self._PRESET_KEY_LABELS[key])
        return self.t(self._PRESET_KEY_LABELS["custom"])

    def guardar_consulta_actual(self):
        """Botón "Guardar consulta...": si la consulta actualmente
        seleccionada en el combo es un preset de fábrica o una consulta
        propia ya guardada, ofrece sobrescribirla en el mismo lugar (sin
        crear una entrada nueva) o guardarla aparte con un nombre nuevo.
        Si el combo está en "Personalizada" (sin preset seleccionado),
        sólo tiene sentido guardarla como nueva."""
        sql_actual = self.txt_sql.toPlainText().strip()
        if not sql_actual:
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("info_empty_query_body"))
            return

        key = self.cb_query_preset.currentData()
        es_preset_de_fabrica = isinstance(key, str) and key in self._PRESET_SQL and key != "custom"
        es_query_guardada = isinstance(key, str) and key.startswith("custom_query:")

        if not (es_preset_de_fabrica or es_query_guardada):
            self._guardar_consulta_como_nueva(sql_actual)
            return

        nombre_actual = (
            self.t(self._PRESET_KEY_LABELS[key]) if es_preset_de_fabrica
            else key[len("custom_query:"):]
        )
        box = QMessageBox(self)
        box.setWindowTitle(self.t("dlg_save_query_title"))
        box.setText(self.t("dlg_save_query_overwrite_body", nombre=nombre_actual))
        btn_overwrite = box.addButton(self.t("btn_save_query_overwrite"), MSG_ROLE_ACTION)
        btn_new = box.addButton(self.t("btn_save_query_as_new"), MSG_ROLE_ACTION)
        box.addButton(MSG_CANCEL)
        box.setDefaultButton(btn_overwrite)
        box.exec()
        clicked = box.clickedButton()

        if clicked is btn_overwrite:
            if es_preset_de_fabrica:
                overrides = self._load_preset_overrides()
                overrides[key] = sql_actual
                self._save_preset_overrides(overrides)
            else:
                queries = self._load_custom_queries()
                for q in queries:
                    if q["name"] == nombre_actual:
                        q["sql"] = sql_actual
                        break
                self._save_custom_queries(queries)
            QMessageBox.information(
                self, self.t("dlg_save_query_title"),
                self.t("info_query_saved_body", nombre=nombre_actual),
            )
        elif clicked is btn_new:
            self._guardar_consulta_como_nueva(sql_actual)
        # Si se cancela, no se toca nada.

    def _guardar_consulta_como_nueva(self, sql):
        nombre, ok = QInputDialog.getText(
            self, self.t("dlg_save_query_title"), self.t("dlg_save_query_name_label")
        )
        if not ok:
            return
        nombre = nombre.strip()
        if not nombre:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_query_name_invalid"))
            return
        if nombre in [self.t(self._PRESET_KEY_LABELS[k]) for k in self._PRESET_ORDER]:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_query_name_reserved"))
            return

        queries = self._load_custom_queries()
        ya_existe = any(q["name"] == nombre for q in queries)
        if ya_existe:
            resp = QMessageBox.question(
                self, self.t("confirm_overwrite_title"),
                self.t("confirm_query_overwrite_body", nombre=nombre),
            )
            if resp not in (MSG_YES,):
                return
            for q in queries:
                if q["name"] == nombre:
                    q["sql"] = sql
                    break
        else:
            queries.append({"name": nombre, "sql": sql})

        self._save_custom_queries(queries)
        self._fill_query_preset_combo(keep_selection=False)
        idx = self.cb_query_preset.findData(f"custom_query:{nombre}")
        if idx >= 0:
            self.cb_query_preset.blockSignals(True)
            self.cb_query_preset.setCurrentIndex(idx)
            self.cb_query_preset.blockSignals(False)
        QMessageBox.information(
            self, self.t("dlg_save_query_title"),
            self.t("info_query_saved_body", nombre=nombre),
        )

    def renombrar_consulta_actual(self):
        """Botón "Renombrar..." junto al combo de "Consulta de ejemplo":
        cambia el NOMBRE (no el SQL) de una consulta propia ya guardada
        con "Guardar consulta...". Sólo aplica a consultas propias
        (`"custom_query:<nombre>"`) -- los presets de fábrica tienen su
        nombre fijo por traducción (`_PRESET_KEY_LABELS`), no un nombre
        libre que tenga sentido renombrar."""
        key = self.cb_query_preset.currentData()
        if not (isinstance(key, str) and key.startswith("custom_query:")):
            QMessageBox.information(self, self.t("dlg_rename_query_title"), self.t("info_rename_only_custom_body"))
            return

        nombre_actual = key[len("custom_query:"):]
        nuevo_nombre, ok = QInputDialog.getText(
            self, self.t("dlg_rename_query_title"), self.t("dlg_rename_query_label"), text=nombre_actual
        )
        if not ok:
            return
        nuevo_nombre = nuevo_nombre.strip()
        if not nuevo_nombre:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_query_name_invalid"))
            return
        if nuevo_nombre == nombre_actual:
            return
        if nuevo_nombre in [self.t(self._PRESET_KEY_LABELS[k]) for k in self._PRESET_ORDER]:
            QMessageBox.warning(self, self.t("err_title"), self.t("err_query_name_reserved"))
            return

        queries = self._load_custom_queries()
        if any(q["name"] == nuevo_nombre for q in queries):
            QMessageBox.warning(self, self.t("err_title"), self.t("err_query_name_taken"))
            return
        for q in queries:
            if q["name"] == nombre_actual:
                q["name"] = nuevo_nombre
                break
        self._save_custom_queries(queries)
        self._fill_query_preset_combo(keep_selection=False)
        idx = self.cb_query_preset.findData(f"custom_query:{nuevo_nombre}")
        if idx >= 0:
            self.cb_query_preset.blockSignals(True)
            self.cb_query_preset.setCurrentIndex(idx)
            self.cb_query_preset.blockSignals(False)
        QMessageBox.information(
            self, self.t("dlg_rename_query_title"),
            self.t("info_query_renamed_body", antes=nombre_actual, despues=nuevo_nombre),
        )

    def importar_consultas_guardadas(self):
        """Botón "Importar consultas...": lee un archivo .qrylt (consultas
        guardadas nativas de GPSeismic -- ver `_parse_qrylt_text`) o un
        .json exportado antes por `exportar_consultas_guardadas`, y agrega
        su contenido a las consultas propias ya guardadas en este
        perfil de QGIS, sin pisar ninguna que ya existiera (ver
        `_fusionar_consultas_importadas`)."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("dlg_import_queries_title"), "",
            f"{self.t('filter_query_files')} (*.qrylt *.json);;GPSeismic (*.qrylt);;JSON (*.json)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".qrylt"):
                nuevas = _leer_archivo_qrylt(path)
            else:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                nuevas = _parse_custom_queries_json(data)
        except Exception as e:
            QMessageBox.critical(
                self, self.t("err_import_queries_title"),
                self.t("err_import_queries_body", error=e, trace=traceback.format_exc()),
            )
            return

        if not nuevas:
            QMessageBox.information(self, self.t("dlg_import_queries_title"), self.t("info_import_queries_empty_body"))
            return

        nombres_reservados = {self.t(self._PRESET_KEY_LABELS[k]) for k in self._PRESET_ORDER}
        existentes = self._load_custom_queries()
        combinadas, n_agregadas, n_renombradas = _fusionar_consultas_importadas(existentes, nuevas, nombres_reservados)
        self._save_custom_queries(combinadas)
        self._fill_query_preset_combo(keep_selection=True)
        QMessageBox.information(
            self, self.t("dlg_import_queries_title"),
            self.t("msg_import_queries_done_body", n=n_agregadas, renombradas=n_renombradas, path=path),
        )

    def exportar_consultas_guardadas(self):
        """Botón "Exportar consultas...": guarda las consultas propias ya
        guardadas en este perfil de QGIS (`_load_custom_queries`) en un
        archivo .json portátil, para llevarlas a otra máquina o a otro
        perfil de QGIS con "Importar consultas..." -- pedido explícito del
        usuario ("guardar los querys personalizados en otro archivo que
        pueda usar después en otro lado")."""
        queries = self._load_custom_queries()
        if not queries:
            QMessageBox.information(self, self.t("dlg_export_queries_title"), self.t("warn_no_custom_queries_body"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("dlg_export_queries_title"), "", "JSON (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"gnsseismic_custom_queries": 1, "queries": queries}, f, ensure_ascii=False, indent=2)
            QMessageBox.information(
                self, self.t("dlg_export_queries_title"),
                self.t("msg_export_queries_done_body", n=len(queries), path=path),
            )
        except Exception as e:
            QMessageBox.critical(
                self, self.t("err_export_title"),
                self.t("err_export_body", error=e, trace=traceback.format_exc()),
            )

    def ejecutar_consulta(self):
        if not self._require_project():
            return
        if not self._confirmar_descartar_ediciones_pendientes():
            return
        sql = self.txt_sql.toPlainText().strip()
        if not sql:
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("info_empty_query_body"))
            return
        try:
            cols, rows = db_schema.run_query(self.conn, sql)
        except ValueError as e:
            QMessageBox.warning(self, self.t("warn_query_not_allowed_title"), str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, self.t("err_query_title"), str(e))
            return

        self.query_columns = cols
        self.query_rows = rows
        self._query_delete_table, self._query_delete_where = db_schema.deletable_table_and_where(sql)
        self.btn_delete_query.setEnabled(self._query_delete_table is not None)
        self._set_query_table_editable(self._es_consulta_editable(cols))
        self._llenar_tabla_query()

        none_label = self.t("none_option")
        for combo in (self.cb_map_nombre, self.cb_map_x, self.cb_map_y):
            combo.clear()
            combo.addItems(cols)
        for combo in (self.cb_map_linea, self.cb_map_punto_sps, self.cb_map_z, self.cb_map_codigo):
            combo.clear()
            combo.addItem(none_label)
            combo.addItems(cols)

        self._preseleccionar_columna(self.cb_map_nombre, ["station_text", "nombre", "name", "punto"])
        self._preseleccionar_columna(self.cb_map_linea, ["track", "linea", "line"])
        self._preseleccionar_columna(self.cb_map_punto_sps, ["bin", "estacion", "station_value", "point"])
        self._preseleccionar_columna(self.cb_map_x, ["easting", "este", "longitude", "lon", "x"])
        self._preseleccionar_columna(self.cb_map_y, ["northing", "norte", "latitude", "lat", "y"])
        self._preseleccionar_columna(self.cb_map_z, ["height", "elevacion", "elevation", "altura", "z", "bin"])
        self._preseleccionar_columna(self.cb_map_codigo, ["descriptor", "codigo", "code"])

        # Vista previa automática en el mapa (v2.14.0): usa el mismo mapeo
        # de columnas que se acaba de preseleccionar arriba. Si la consulta
        # no tiene columnas de nombre/X/Y con las que armar geometría (por
        # ejemplo un SELECT COUNT(*)), simplemente no dibuja nada.
        self._actualizar_capa_provisional_query()

    def _llenar_tabla_query(self):
        """Repuebla `tbl_query` a partir de `self.query_columns`/
        `self.query_rows` sin volver a ejecutar la consulta SQL -- se usa
        tanto al ejecutar una consulta nueva como después de borrar
        puntos puntuales desde la capa provisional del mapa o de guardar
        cambios de edición (donde sólo cambia la lista en memoria, no
        hace falta re-consultar). Siempre limpia cualquier cambio de
        edición pendiente y deshabilita "Guardar cambios..." -- los
        llamadores que repueblan por perder filas/consultar de nuevo ya
        pidieron confirmación antes de descartar ediciones sin guardar
        (ver `_confirmar_descartar_ediciones_pendientes`); el que guarda
        cambios (`guardar_cambios_consulta`) ya los dejó vacíos antes de
        llegar acá."""
        cols = self.query_columns
        rows = self.query_rows
        self._query_pending_edits = {}
        self.btn_save_query_changes.setEnabled(False)
        self._set_query_resumen(len(rows), len(cols))
        self.tbl_query.blockSignals(True)
        self.tbl_query.setColumnCount(len(cols))
        self.tbl_query.setHorizontalHeaderLabels(cols)
        self.tbl_query.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                item = QTableWidgetItem("" if row[col] is None else str(row[col]))
                if col == "ID":
                    # La columna ID (PRIMARY KEY) nunca se edita, aunque el
                    # resto de la fila sea editable -- editarla rompería la
                    # correspondencia fila<->UPDATE de `guardar_cambios_consulta`.
                    item.setFlags(item.flags() & ~ITEM_IS_EDITABLE)
                self.tbl_query.setItem(r, c, item)
        self.tbl_query.blockSignals(False)

    def _set_query_table_editable(self, editable):
        """Habilita o deshabilita la edición en línea de `tbl_query`
        (v2.21.0, pedido del usuario: "habilitar la edicion de la base de
        datos"). Se decide en `ejecutar_consulta` con
        `_es_consulta_editable`, la misma condición que ya usa el borrado
        (`self._query_delete_table`/columna ID) más una validación extra:
        las columnas del resultado tienen que ser columnas reales de esa
        tabla (no alias, ej. `SELECT Descriptor AS Tipo ...`), para que
        `guardar_cambios_consulta` pueda armar un UPDATE válido con esos
        mismos nombres."""
        self._query_table_editable = editable
        if editable:
            triggers = (
                _valor_enum(QAbstractItemView, "DoubleClicked", "EditTrigger")
                | _valor_enum(QAbstractItemView, "EditKeyPressed", "EditTrigger")
            )
        else:
            triggers = _valor_enum(QAbstractItemView, "NoEditTriggers", "EditTrigger")
        self.tbl_query.setEditTriggers(triggers)

    def _es_consulta_editable(self, cols):
        """True si la consulta actual (ya identificada como "borrable" en
        `self._query_delete_table`) también puede quedar editable: trae la
        columna ID y el resto de sus columnas son columnas reales de esa
        tabla (`db_schema.table_column_names`), no alias ni expresiones
        calculadas."""
        if not self._query_delete_table or "ID" not in cols:
            return False
        try:
            columnas_reales = set(db_schema.table_column_names(self.conn, self._query_delete_table))
        except Exception:
            return False
        otras_columnas = [c for c in cols if c != "ID"]
        return bool(otras_columnas) and all(c in columnas_reales for c in otras_columnas)

    def _confirmar_descartar_ediciones_pendientes(self):
        """Si hay cambios de edición sin guardar en `tbl_query`, pide
        confirmación antes de descartarlos -- se llama antes de cualquier
        acción que vaya a repoblar la tabla desde cero (ejecutar una
        consulta nueva, o borrar filas desde la capa del mapa). Devuelve
        True si está bien continuar (no había nada pendiente, o el
        usuario confirmó descartarlo)."""
        if not self._query_pending_edits:
            return True
        resp = QMessageBox.question(
            self, self.t("confirm_discard_edits_title"), self.t("confirm_discard_edits_body"),
        )
        return resp in (MSG_YES,)

    def _on_query_cell_changed(self, item):
        """Conectado a `itemChanged` de `tbl_query`: registra (o retira,
        si el usuario volvió a escribir el valor original) un cambio
        pendiente en `self._query_pending_edits`, resaltando la celda
        mientras el cambio no esté guardado (ver `guardar_cambios_consulta`).
        Valida que el valor nuevo tenga un tipo compatible con el original
        (entero/decimal/texto) antes de aceptarlo -- si no, avisa y
        revierte la celda a su texto anterior."""
        if not self._query_table_editable:
            return
        row = item.row()
        col = item.column()
        if row >= len(self.query_rows) or col >= len(self.query_columns):
            return
        col_name = self.query_columns[col]
        if col_name == "ID":
            return

        original_value = self.query_rows[row].get(col_name)
        original_text = "" if original_value is None else str(original_value)
        new_text = item.text()

        if new_text != original_text:
            if new_text == "":
                valor_final = None
            elif isinstance(original_value, int) and not isinstance(original_value, bool):
                try:
                    valor_final = int(new_text)
                except ValueError:
                    self._revertir_celda_edicion_invalida(item, original_text, "err_edit_invalid_int", new_text)
                    return
            elif isinstance(original_value, float):
                try:
                    valor_final = float(new_text)
                except ValueError:
                    self._revertir_celda_edicion_invalida(item, original_text, "err_edit_invalid_float", new_text)
                    return
            else:
                valor_final = new_text

            self._query_pending_edits.setdefault(row, {})[col_name] = valor_final
            self.tbl_query.blockSignals(True)
            item.setBackground(COLOR_QUERY_EDITADO)
            self.tbl_query.blockSignals(False)
        else:
            fila_cambios = self._query_pending_edits.get(row)
            if fila_cambios and col_name in fila_cambios:
                del fila_cambios[col_name]
                if not fila_cambios:
                    del self._query_pending_edits[row]
            self.tbl_query.blockSignals(True)
            item.setBackground(QBrush())
            self.tbl_query.blockSignals(False)

        self.btn_save_query_changes.setEnabled(bool(self._query_pending_edits))

    def _revertir_celda_edicion_invalida(self, item, texto_original, err_key, valor_invalido):
        QMessageBox.warning(self, self.t("err_title"), self.t(err_key, valor=valor_invalido))
        self.tbl_query.blockSignals(True)
        item.setText(texto_original)
        self.tbl_query.blockSignals(False)

    @_escritura()
    def guardar_cambios_consulta(self):
        """Botón "Guardar cambios en la base de datos...": escribe todos
        los cambios pendientes de `tbl_query` (ver `_on_query_cell_changed`)
        con un UPDATE por fila cambiada, pidiendo confirmación explícita
        antes -- pedido del usuario (v2.21.0): "un boton para guardar los
        cambios, con mensaje de advertencia si quiere guardar los cambios
        o no". Si falla el guardado de alguna fila puntual (por ejemplo,
        otra ventana borró esa fila mientras tanto), sigue con el resto y
        avisa al final cuáles no se pudieron guardar, en vez de perder
        todos los cambios por el error de una sola fila."""
        if not self._require_project():
            return
        if not self._query_pending_edits:
            QMessageBox.information(self, self.t("info_no_pending_edits_title"), self.t("info_no_pending_edits_body"))
            return

        tabla = self._query_delete_table
        n_filas = len(self._query_pending_edits)
        n_celdas = sum(len(cambios) for cambios in self._query_pending_edits.values())
        resp = QMessageBox.question(
            self, self.t("confirm_save_edits_title"),
            self.t("confirm_save_edits_body", n_celdas=n_celdas, n_filas=n_filas, tabla=tabla),
        )
        if resp not in (MSG_YES,):
            return

        guardadas = 0
        errores = []
        for row_idx, cambios in list(self._query_pending_edits.items()):
            if row_idx >= len(self.query_rows):
                continue
            row_id = self.query_rows[row_idx].get("ID")
            if row_id is None:
                continue
            try:
                db_schema.update_row_by_id(self.conn, tabla, row_id, cambios)
            except Exception as e:
                errores.append(f"ID {row_id}: {e}")
                continue
            for col, valor in cambios.items():
                self.query_rows[row_idx][col] = valor
            guardadas += 1

        self._llenar_tabla_query()
        self._actualizar_capa_provisional_query()

        if errores:
            QMessageBox.warning(
                self, self.t("warn_save_edits_partial_title"),
                self.t("warn_save_edits_partial_body", n=guardadas, errores="\n".join(errores)),
            )
        else:
            QMessageBox.information(
                self, self.t("ok_title"), self.t("msg_save_edits_ok_body", n=guardadas, tabla=tabla),
            )

    @_escritura()
    def borrar_resultados_consulta(self):
        """Botón "Borrar resultados de la consulta": borra de la base de
        datos TODAS las filas que matchean la consulta SQL actual (no
        sólo las que se ven en `tbl_query`, que puede estar recortada al
        límite de previsualización de `run_query`) -- pide confirmación
        explícita mostrando cuántas filas y de qué tabla antes de
        ejecutar el DELETE. Sólo está habilitado cuando
        `db_schema.deletable_table_and_where()` pudo identificar sin
        ambigüedad una única tabla borrable para la consulta escrita."""
        if not self._require_project():
            return
        tabla = self._query_delete_table
        if not tabla:
            QMessageBox.warning(self, self.t("warn_delete_not_supported_title"), self.t("warn_delete_not_supported_body"))
            return
        where_sql = self._query_delete_where
        try:
            n = db_schema.count_matching_rows(self.conn, tabla, where_sql)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_query_title"), str(e))
            return
        if n == 0:
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("info_delete_nothing_body"))
            return

        resp = QMessageBox.question(
            self, self.t("confirm_delete_title"),
            self.t("confirm_delete_query_body", n=n, tabla=tabla),
        )
        if resp not in (MSG_YES,):
            return

        try:
            borrados = db_schema.delete_matching_rows(self.conn, tabla, where_sql)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_delete_title"), self.t("err_delete_body", error=e, trace=traceback.format_exc()))
            return

        self.query_columns = []
        self.query_rows = []
        self._query_delete_table = None
        self._query_delete_where = None
        self.btn_delete_query.setEnabled(False)
        self.tbl_query.setColumnCount(0)
        self.tbl_query.setRowCount(0)
        self._set_query_resumen(None)
        self._actualizar_capa_provisional_query()
        self.actualizar_conteos()
        QMessageBox.information(self, self.t("ok_title"), self.t("msg_delete_ok_body", n=borrados, tabla=tabla))

    # -- "Buscar / Buscar y reemplazar" (v2.53.0) -----------------------------
    #
    # Sección aparte del editor de SQL libre de arriba, para poder buscar
    # (y reemplazar en bloque) por CUALQUIER columna de POSTPLOT/PREPLOT/
    # COMPARACION sin tener que escribir SQL a mano -- pedido explícito
    # del usuario. Ver `_build_tab_bd` para los widgets y
    # `db_schema.count_replace_matches`/`replace_in_column` para la lógica
    # de reemplazo masivo.

    def _poblar_columnas_buscar_reemplazar(self):
        """Repuebla `cb_sr_columna` con las columnas reales de la tabla
        elegida en `cb_sr_tabla` (sin "ID": nunca tiene sentido como
        columna de búsqueda/reemplazo -- buscar un ID puntual se hace
        mejor escribiendo el SQL a mano arriba, y reemplazarlo rompería
        la clave primaria). Se llama al construir la pestaña, cada vez
        que cambia la tabla elegida, y cada vez que se abre/crea un
        proyecto (ver `actualizar_conteos`); si todavía no hay un
        proyecto abierto, deja el combo vacío en vez de fallar."""
        tabla = self.cb_sr_tabla.currentData()
        columna_previa = self.cb_sr_columna.currentText()
        self.cb_sr_columna.clear()
        if not tabla or self.conn is None:
            return
        try:
            columnas = db_schema.table_column_names(self.conn, tabla)
        except Exception:
            return
        self.cb_sr_columna.addItems([c for c in columnas if c != "ID"])
        idx = self.cb_sr_columna.findText(columna_previa)
        if idx >= 0:
            self.cb_sr_columna.setCurrentIndex(idx)

    def buscar_por_columna(self):
        """Botón "Buscar": arma un SELECT simple sobre la tabla/columna
        elegidas (coincidencia exacta o "contiene", según
        `chk_sr_exacto`) y lo corre con el mismo mecanismo que la
        consulta SQL libre de más arriba (`ejecutar_consulta`) -- el
        resultado queda en la misma tabla de abajo, con edición en
        línea, borrado, mapeo de columnas y exportación ya disponibles
        sin duplicar esa lógica. El SQL armado también queda visible en
        el cuadro de consulta, por si el usuario quiere ajustarlo a mano
        después (mismo criterio que ya usan los presets del combo de
        arriba)."""
        tabla = self.cb_sr_tabla.currentData()
        columna = self.cb_sr_columna.currentText()
        if not tabla or not columna:
            QMessageBox.warning(self, self.t("warn_missing_data_title"), self.t("err_sr_missing_column"))
            return
        valor = self.txt_sr_buscar.text()
        if valor == "":
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("err_sr_missing_search_value"))
            return

        valor_sql = valor.replace("'", "''")
        if self.chk_sr_exacto.isChecked():
            where = f"[{columna}] = '{valor_sql}'"
        else:
            where = f"[{columna}] LIKE '%{valor_sql}%'"
        # `tabla` viene de un combo con la lista fija de tablas reales; `where` ya tiene su valor escapado a mano arriba (comillas duplicadas); este texto sólo se MUESTRA en el editor para que el usuario lo revise/ajuste, no se ejecuta directo
        self.txt_sql.setPlainText(f"SELECT * FROM {tabla} WHERE {where}")  # nosec B608
        # Este SQL es ad hoc, sin preset asociado -- si el combo de arriba
        # se había quedado en un preset o consulta guardada de antes, hay
        # que pasarlo a "Personalizada" para que `_nombre_consulta_actual`
        # (usado para nombrar la capa provisional, pedido del usuario en
        # la v2.56.0) no le ponga a esta búsqueda el nombre de una
        # consulta que no es la que de verdad se está corriendo.
        idx_custom = self.cb_query_preset.findData("custom")
        if idx_custom >= 0 and self.cb_query_preset.currentIndex() != idx_custom:
            self.cb_query_preset.blockSignals(True)
            self.cb_query_preset.setCurrentIndex(idx_custom)
            self.cb_query_preset.blockSignals(False)
        self.ejecutar_consulta()

    @_escritura()
    def reemplazar_por_columna(self):
        """Botón "Reemplazar todos...": reemplaza, en TODAS las filas de
        `tabla` donde `columna` matchea el valor de "Buscar" (exacto o
        "contiene"), ese valor por el de "Reemplazar por" -- ver
        `db_schema.replace_in_column` para la diferencia entre ambos
        modos (exacto reemplaza la celda completa; "contiene" reemplaza
        sólo la parte encontrada con `REPLACE()` de SQL, conservando el
        resto del texto de la celda). Pide confirmación mostrando antes
        cuántas filas se van a modificar, igual que el resto de las
        acciones de escritura de este panel (borrar resultados, guardar
        cambios de edición)."""
        if not self._require_project():
            return
        tabla = self.cb_sr_tabla.currentData()
        columna = self.cb_sr_columna.currentText()
        if not tabla or not columna:
            QMessageBox.warning(self, self.t("warn_missing_data_title"), self.t("err_sr_missing_column"))
            return
        buscar = self.txt_sr_buscar.text()
        if buscar == "":
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("err_sr_missing_search_value"))
            return
        reemplazar = self.txt_sr_reemplazar.text()
        exacto = self.chk_sr_exacto.isChecked()

        try:
            n = db_schema.count_replace_matches(self.conn, tabla, columna, buscar, exacto)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_query_title"), str(e))
            return
        if n == 0:
            QMessageBox.information(self, self.t("info_empty_query_title"), self.t("info_sr_nothing_to_replace"))
            return

        resp = QMessageBox.question(
            self, self.t("confirm_replace_title"),
            self.t(
                "confirm_replace_body", n=n, tabla=tabla, columna=columna,
                buscar=buscar, reemplazar=reemplazar,
            ),
        )
        if resp not in (MSG_YES,):
            return

        try:
            modificadas = db_schema.replace_in_column(self.conn, tabla, columna, buscar, reemplazar, exacto)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_delete_title"), self.t("err_delete_body", error=e, trace=traceback.format_exc()))
            return

        QMessageBox.information(
            self, self.t("ok_title"),
            self.t("msg_sr_replace_ok_body", n=modificadas, tabla=tabla, columna=columna),
        )
        # Vuelve a correr la misma búsqueda para que la tabla de abajo
        # refleje de inmediato el resultado del reemplazo (normalmente
        # mostrando menos filas, o ninguna, porque ya no matchean el
        # valor buscado) -- confirma visualmente que el reemplazo
        # funcionó, sin que el usuario tenga que volver a apretar nada.
        self.buscar_por_columna()
        self.actualizar_conteos()

    def _actualizar_capa_provisional_query(self):
        """Crea/actualiza una capa de memoria PROVISIONAL con los puntos
        de `self.query_rows` (la última consulta ejecutada en "Base de
        Datos"), usando el mismo mapeo de columnas Nombre/X/Y/geográfica
        que ya usan los botones de exportar (`_filas_export_con_xy()`).
        Se llama automáticamente cada vez que se ejecuta una consulta
        nueva, y siempre reemplaza la capa anterior en vez de
        acumularla -- igual que el resto de capas provisionales del
        plugin (ver `_actualizar_capa_provisional_preview`/
        `_actualizar_capa_provisional_preplot_ext`).

        Si la consulta actual es "borrable" (`self._query_delete_table`
        no es None) y su resultado incluye la columna ID, la capa queda
        conectada a `_on_query_layer_features_deleted` -- pero YA NO se
        activa el modo edición ni se pone esta capa como "capa activa"
        automáticamente (bug real reportado por el usuario en la v2.57.0:
        "al parecer me está borrando los datos que busco... después que
        lo busco la primera vez, si vuelvo a buscar el mismo dato, ya no
        aparece" -- la causa real era justamente esto, confirmada por el
        propio usuario: con la capa YA en edición y activa apenas se
        buscaba, era muy fácil confundir "sacar la capa temporal de la
        vista" con seleccionar el punto encontrado y apretar Supr/Delete
        -- eso SÍ borraba la fila real de la base de datos, con
        confirmación de por medio, pero una confirmación fácil de
        aceptar sin pensar que se trataba de un borrado real y
        permanente). Ahora, para poder borrar puntos desde el mapa, el
        usuario tiene que activar "Editar capa" a mano (el lápiz de
        QGIS) como con cualquier otra capa -- recién ahí seleccionar
        puntos y borrarlos con la tecla Supr/Delete (o con cualquier
        otra forma que QGIS ofrezca de borrar features seleccionados de
        una capa en edición) dispara `_on_query_layer_features_deleted`,
        que pide confirmación y borra esas filas de la base de datos
        real antes de confirmar el borrado en el mapa."""
        capa_vieja = self._provisional_query_layer
        if capa_vieja is not None:
            try:
                if QgsProject.instance().mapLayer(capa_vieja.id()) is not None:
                    self.project.removeMapLayer(capa_vieja.id())
            except RuntimeError:
                # El objeto Qt/QGIS ya fue eliminado (p.ej. el usuario
                # quitó la capa a mano) -- nada que limpiar.
                pass
            self._provisional_query_layer = None
        self._query_layer_row_ids = {}

        if not self.query_rows:
            return
        # Si la consulta sólo tiene una columna (ej. "SELECT COUNT(*) AS
        # n FROM POSTPLOT"), los combos Nombre/X/Y quedan los tres
        # apuntando a esa misma única columna -- no hay forma de que eso
        # sea una geometría real, así que se trata igual que "sin mapeo
        # válido" en vez de dibujar un punto sin sentido con ese valor
        # repetido como X e Y.
        if len({self.cb_map_nombre.currentText(), self.cb_map_x.currentText(), self.cb_map_y.currentText()}) < 3:
            return
        try:
            rows_out, name_col = self._filas_export_con_xy()
        except ValueError:
            # La consulta actual no tiene columnas Nombre/X/Y mapeadas
            # (por ejemplo columnas no numéricas) -- no hay nada que
            # dibujar en el mapa.
            return
        if not rows_out:
            return

        dest_crs = self._working_crs()
        # Pedido explícito del usuario (v2.56.0): la capa provisional debe
        # llamarse igual que la consulta seleccionada arriba, no un
        # nombre genérico fijo -- ver `_nombre_consulta_actual`.
        nombre_capa = self._nombre_consulta_actual() or self.t("layer_query_provisional")
        layer = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", nombre_capa, "memory")
        prov = layer.dataProvider()
        columnas_extra = list(self.query_columns)
        prov.addAttributes([QgsField(c, FIELD_STRING) for c in columnas_extra])
        layer.updateFields()

        puede_borrar_desde_mapa = bool(self._query_delete_table) and "ID" in self.query_columns

        feats = []
        row_ids = []
        for row in rows_out:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(row["_x_out"], row["_y_out"])))
            f.setAttributes(["" if row.get(c) is None else str(row.get(c)) for c in columnas_extra])
            feats.append(f)
            row_ids.append(row.get("ID") if puede_borrar_desde_mapa else None)
        # `addFeatures` devuelve (ok, features_agregadas) -- las features
        # agregadas son las que traen el fid real ya asignado por el
        # proveedor; la lista `feats` original NO se puede asumir
        # mutada in-place con ese fid (varía según el proveedor/versión
        # de QGIS), así que el mapeo fid->ID de fila se arma a partir de
        # lo que devuelve `addFeatures`, no de `feats`.
        _, feats_agregadas = prov.addFeatures(feats)
        layer.updateExtents()
        self.project.addMapLayer(layer)
        self._activar_conteo_features(layer)
        QApplication.processEvents()
        self._zoom_canvas_a_capa(layer)
        self._provisional_query_layer = layer

        if puede_borrar_desde_mapa:
            self._query_layer_row_ids = {f.id(): row_id for f, row_id in zip(feats_agregadas, row_ids)}
            layer.featuresDeleted.connect(self._on_query_layer_features_deleted)
            # v2.57.0: ya NO se llama `layer.startEditing()` ni
            # `self.iface.setActiveLayer(layer)` acá -- ver el docstring
            # de arriba. La capa queda conectada y lista para borrar
            # igual, pero sólo si el usuario activa "Editar capa" él
            # mismo primero (acción explícita, no automática).

    def _on_query_layer_features_deleted(self, fids):
        """Conectado a `featuresDeleted` de la capa provisional de
        consultas: se dispara apenas el usuario borra features
        seleccionados de esa capa (tecla Supr/Delete, o cualquier otra
        vía de QGIS para borrar de una capa en edición) -- pero TODAVÍA
        DENTRO de `deleteSelectedFeatures()`, antes de que ésta llame a
        `endEditCommand()` y recién ahí empuje el comando de deshacer al
        `undoStack()` de la capa. Si se pide confirmación y se llama a
        `undoStack().undo()` aquí mismo, todavía no hay nada que
        deshacer (probado en vivo: el `undo()` no tenía efecto y el
        punto quedaba borrado del mapa igual aunque el usuario hubiera
        cancelado). Por eso el trabajo real se pospone con
        `QTimer.singleShot(0, ...)` a la siguiente vuelta del loop de
        eventos de Qt, momento en el que `deleteSelectedFeatures()` ya
        terminó por completo y el comando ya está en el `undoStack()`."""
        fids_lista = list(fids)
        QTimer.singleShot(0, lambda: self._confirmar_borrado_capa_query(fids_lista))

    @_escritura()
    def _confirmar_borrado_capa_query(self, fids):
        """Lógica real del borrado desde el mapa (ver
        `_on_query_layer_features_deleted` para por qué se pospone hasta
        acá con QTimer.singleShot). Pide confirmación explícita y, si el
        usuario acepta, borra esas mismas filas (por ID) de la tabla
        real en la base de datos y recién ahí confirma
        (`commitChanges()`) el borrado en el mapa; si el usuario cancela,
        o si el borrado en la base de datos falla, deshace el borrado en
        el mapa (`undoStack().undo()`) para que el punto reaparezca --
        mapa y base de datos nunca quedan desincronizados."""
        layer = self._provisional_query_layer
        tabla = self._query_delete_table
        if layer is None or not tabla:
            return
        mapping = self._query_layer_row_ids
        ids = [mapping.get(fid) for fid in fids]
        ids = [i for i in ids if i is not None]
        if not ids:
            return

        # Borrar filas desde el mapa repuebla `tbl_query` desde cero al
        # terminar (los índices de fila cambian), lo que descartaría
        # cualquier edición todavía sin guardar -- avisar antes, igual que
        # `ejecutar_consulta` (ver `_confirmar_descartar_ediciones_pendientes`).
        if not self._confirmar_descartar_ediciones_pendientes():
            layer.undoStack().undo()
            return

        resp = QMessageBox.question(
            self, self.t("confirm_delete_title"),
            self.t("confirm_delete_map_body", n=len(ids), tabla=tabla),
        )
        if resp not in (MSG_YES,):
            layer.undoStack().undo()
            return

        try:
            borrados = db_schema.delete_rows_by_id(self.conn, tabla, ids)
        except Exception as e:
            layer.undoStack().undo()
            QMessageBox.critical(self, self.t("err_delete_title"), self.t("err_delete_body", error=e, trace=traceback.format_exc()))
            return

        try:
            layer.commitChanges()
        # el borrado real ya se confirmó y manejó arriba; esto es sólo el refresco cosmético del buffer de edición de QGIS
        except Exception:  # nosec B110
            pass
        layer.startEditing()

        ids_borrados = set(ids)
        self.query_rows = [r for r in self.query_rows if r.get("ID") not in ids_borrados]
        for fid in fids:
            self._query_layer_row_ids.pop(fid, None)
        self._llenar_tabla_query()
        self.actualizar_conteos()
        QMessageBox.information(self, self.t("ok_title"), self.t("msg_delete_ok_body", n=borrados, tabla=tabla))

    def _columna_opcional(self, combo: QComboBox):
        texto = combo.currentText()
        return None if texto in ("", self.t("none_option")) else texto

    def _filas_export_con_xy(self):
        """Devuelve (rows, x_col, y_col) con las coordenadas X/Y ya
        transformadas al CRS de trabajo si el usuario marcó que las
        columnas elegidas son geográficas. Los nombres de columna
        'x_out'/'y_out' se agregan a cada fila sin pisar las originales.
        """
        if not self.query_rows:
            raise ValueError(self.t("err_no_query_results"))
        name_col = self.cb_map_nombre.currentText()
        x_col = self.cb_map_x.currentText()
        y_col = self.cb_map_y.currentText()
        if not name_col or not x_col or not y_col:
            raise ValueError(self.t("err_missing_map_columns"))

        dest_crs = self._working_crs()
        es_geografica = self.chk_map_geografica.isChecked()
        src_crs = self.crs_wgs84 if es_geografica else dest_crs

        rows_out = []
        for row in self.query_rows:
            try:
                x = float(row[x_col])
                y = float(row[y_col])
            except (TypeError, ValueError, KeyError):
                continue
            if src_crs != dest_crs:
                x, y = _transform_xy(x, y, src_crs, dest_crs, self.project)
            nueva = dict(row)
            nueva["_x_out"] = x
            nueva["_y_out"] = y
            rows_out.append(nueva)
        return rows_out, name_col

    def exportar_query(self, formato):
        if not self._require_project():
            return
        if not formato:
            return

        # Excel (.csv), a diferencia de Shapefile/GeoPackage/SPS, exporta
        # tal cual el resultado de la consulta (todas sus columnas y
        # filas, sin geometría) -- no depende del mapeo de columnas
        # Nombre/X/Y de "Mapeo de columnas" (una consulta sin columnas de
        # coordenadas, como un SELECT COUNT(*), igual se puede exportar a
        # CSV, aunque no tenga sentido exportarla a un formato espacial).
        if formato == "csv":
            self._exportar_csv()
            return

        try:
            rows_out, name_col = self._filas_export_con_xy()
        except ValueError as e:
            QMessageBox.warning(self, self.t("warn_missing_data_title"), str(e))
            return

        if not rows_out:
            QMessageBox.warning(self, self.t("warn_no_valid_rows_title"), self.t("warn_no_valid_rows_body"))
            return

        if formato == "sps":
            self._exportar_sps(rows_out, name_col)
        else:
            self._exportar_ogr(rows_out, name_col, formato)

    def _exportar_csv(self):
        if not self.query_rows:
            QMessageBox.warning(self, self.t("warn_missing_data_title"), self.t("err_no_query_results"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("dlg_export_to", driver=self.t("export_format_csv")), "", "CSV (*.csv)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            n = export_writers.write_csv(self.query_columns, self.query_rows, path)
            QMessageBox.information(self, self.t("msg_export_ok_title"), self.t("msg_export_csv_body", n=n, path=path))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_export_title"), self.t("err_export_body", error=e, trace=traceback.format_exc()))

    def _exportar_ogr(self, rows_out, name_col, formato):
        extensiones = {"shapefile": ("ESRI Shapefile", "Shapefile (*.shp)", ".shp"), "gpkg": ("GPKG", "GeoPackage (*.gpkg)", ".gpkg")}
        driver, filtro, ext = extensiones[formato]
        path, _ = QFileDialog.getSaveFileName(self, self.t("dlg_export_to", driver=driver), "", filtro)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext

        dest_crs = self._working_crs()
        layer = QgsVectorLayer(f"Point?crs={dest_crs.authid()}", "exportacion", "memory")
        prov = layer.dataProvider()

        columnas_extra = [c for c in self.query_columns]
        prov.addAttributes([QgsField(c, FIELD_STRING) for c in columnas_extra])
        layer.updateFields()

        feats = []
        for row in rows_out:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(row["_x_out"], row["_y_out"])))
            f.setAttributes(["" if row.get(c) is None else str(row.get(c)) for c in columnas_extra])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()

        try:
            opciones = QgsVectorFileWriter.SaveVectorOptions()
            opciones.driverName = driver
            opciones.fileEncoding = "UTF-8"
            resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path, self.project.transformContext(), opciones
            )
            # writeAsVectorFormatV3 devuelve una tupla (código, mensaje, ...)
            # según la versión de QGIS; el código 0 es éxito (NoError).
            codigo = resultado[0] if isinstance(resultado, (tuple, list)) else resultado
            if codigo != _valor_enum(QgsVectorFileWriter, "NoError", "WriterError"):
                mensaje = resultado[1] if isinstance(resultado, (tuple, list)) and len(resultado) > 1 else str(resultado)
                raise RuntimeError(mensaje)
            QMessageBox.information(self, self.t("msg_export_ok_title"), self.t("msg_export_points_body", n=len(feats), path=path))
        except Exception as e:
            QMessageBox.critical(self, self.t("err_export_title"), self.t("err_export_body", error=e, trace=traceback.format_exc()))

    def _exportar_sps(self, rows_out, name_col):
        tipo = "S" if self.rb_sps_fuente.isChecked() else "R"
        ext = ".S01" if tipo == "S" else ".R01"
        path, _ = QFileDialog.getSaveFileName(self, self.t("dlg_export_sps_title"), "", f"SPS (*{ext})")
        if not path:
            return
        if not path.lower().endswith(ext.lower()):
            path += ext

        elev_col = self._columna_opcional(self.cb_map_z)
        code_col = self._columna_opcional(self.cb_map_codigo)
        line_col = self._columna_opcional(self.cb_map_linea)
        punto_col = self._columna_opcional(self.cb_map_punto_sps)

        if not line_col or not punto_col:
            faltan = []
            if not line_col:
                faltan.append(self.t("sps_missing_line"))
            if not punto_col:
                faltan.append(self.t("sps_missing_point"))
            QMessageBox.warning(
                self, self.t("warn_missing_sps_columns_title"),
                self.t("warn_missing_sps_columns_body", faltan=" y ".join(faltan)),
            )
            return

        try:
            n = export_writers.write_sps(
                rows_out, path, tipo=tipo,
                line_col=line_col, point_col=punto_col,
                x_col="_x_out", y_col="_y_out", elev_col=elev_col, code_col=code_col,
                code_fijo=self.txt_sps_codigo_fijo.text(),
                point_index=self.sp_sps_indice.value(),
            )
            omitidas = len(rows_out) - n
            msg = self.t("msg_export_sps_body", n=n, path=path)
            if omitidas:
                msg += self.t("msg_export_sps_skipped", n=omitidas)
            QMessageBox.information(self, self.t("msg_export_ok_title"), msg)
        except Exception as e:
            QMessageBox.critical(self, self.t("err_export_title"), self.t("err_export_sps_body", error=e, trace=traceback.format_exc()))

    def closeEvent(self, event):
        # No se cierra la conexión a la BD para permitir reabrir el
        # diálogo sin perder el proyecto activo durante la sesión de QGIS.
        super().closeEvent(event)
