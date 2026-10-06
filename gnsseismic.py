# -*- coding: utf-8 -*-
"""
gnsseismic.py
-------------
Clase principal del plugin. Registra un ÚNICO toolbar de QGIS
("GNSSeismic") con un ícono por sección -- Proyecto / Preplot Sísmico /
Importar datos de campo / Base de Datos -- más un selector de idioma
embebido en el mismo toolbar. Cada ícono abre esa sección como una
ventana independiente y no modal (`GNSSeismicController.show_window`),
para que el usuario pueda tener varias abiertas al mismo tiempo en vez de
cambiar de pestaña dentro de un único diálogo (así funcionaba hasta la
v1.3.0, cuando el plugin se llamaba "Gestor DC Topografía").

Las mismas acciones también se agregan al menú de Complementos, por si
el usuario oculta el toolbar.
"""

import os

from qgis.PyQt.QtWidgets import QAction, QLabel, QComboBox
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProject, QgsApplication

from . import i18n

_MENU_NAME = "&GNSSeismic"

# Clave interna de cada sección -> claves de i18n (título/tooltip) e
# íconos candidatos del tema de QGIS, en orden de preferencia. Los
# nombres exactos disponibles varían un poco entre versiones de QGIS, así
# que se prueban varias alternativas antes de caer al ícono propio del
# plugin (`icon.png`), para no terminar con un botón sin ícono.
_SECTIONS = [
    ("proyecto", "tab1_title", ["/mActionFileNew.svg", "/mIconGeoPackage.svg", "/mActionNewVectorLayer.svg"]),
    ("preplot", "tab2_title", ["/mIconPointLayer.svg", "/mActionAddRegularLayer.svg", "/mIconPointCloudLayer.svg"]),
    ("importar", "tab3_title", ["/mActionAddGpxLayer.svg", "/mActionSharingImport.svg", "/mActionFileOpen.svg"]),
    ("bd", "tab5_title", ["/mIconDbSchema.svg", "/mActionOpenTable.svg", "/mIconSqliteLayer.svg"]),
]


def _pick_theme_icon(candidates, fallback_path):
    """Prueba una lista de nombres de ícono del tema activo de QGIS
    (mIconX.svg / mActionX.svg, buscados con QgsApplication.getThemeIcon)
    y devuelve el primero que exista; si ninguno existe, cae al ícono
    propio del plugin en `fallback_path`."""
    for name in candidates:
        try:
            icon = QgsApplication.getThemeIcon(name)
        except Exception:
            icon = None
        if icon is not None and not icon.isNull():
            return icon
    return QIcon(fallback_path)


class GNSSeismicPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.toolbar = None
        self.actions = []  # [(key, QAction), ...]
        self.cb_lang = None
        self._lbl_lang = None
        self.controller = None

    def initGui(self):
        self.toolbar = self.iface.addToolBar("GNSSeismic")
        self.toolbar.setObjectName("GNSSeismicToolbar")

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        lang = i18n.DEFAULT_LANG

        for key, title_key, candidates in _SECTIONS:
            icon = _pick_theme_icon(candidates, icon_path)
            text = i18n.t(lang, title_key)
            action = QAction(icon, text, self.iface.mainWindow())
            action.setToolTip(text)
            action.triggered.connect(lambda checked=False, k=key: self._show_window(k))
            self.toolbar.addAction(action)
            self.iface.addPluginToMenu(_MENU_NAME, action)
            self.actions.append((key, action))

        self.toolbar.addSeparator()
        self._lbl_lang = QLabel(" " + i18n.t(lang, "lang_label") + " ")
        self.toolbar.addWidget(self._lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.addItem(i18n.t("es", "lang_es"), "es")
        self.cb_lang.addItem(i18n.t("en", "lang_en"), "en")
        self.cb_lang.currentIndexChanged.connect(self._on_language_changed)
        self.toolbar.addWidget(self.cb_lang)

    def unload(self):
        for key, action in self.actions:
            try:
                self.iface.removePluginMenu(_MENU_NAME, action)
            # limpieza de descarga del plugin: no hay nada que hacer si la acción del menú ya no existe
            except Exception:  # nosec B110
                pass
        self.actions = []
        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None
        self.cb_lang = None
        self._lbl_lang = None
        if self.controller is not None:
            self.controller.close_all_windows()
            self.controller = None

    def _ensure_controller(self):
        # Se importa aquí (y no arriba del todo) para que QGIS pueda
        # cargar el plugin -- e initGui() pueda registrar el toolbar --
        # incluso si, por algún motivo, el controlador tuviera un error
        # de importación tardío: el error se vería sólo al usar una
        # acción, no al arrancar QGIS.
        if self.controller is None:
            from .gnsseismic_windows import GNSSeismicController
            self.controller = GNSSeismicController(self.iface, QgsProject.instance())
        return self.controller

    def _show_window(self, key):
        self._ensure_controller().show_window(key)

    def _on_language_changed(self, index):
        lang = self.cb_lang.itemData(index)
        if not lang:
            return
        self._ensure_controller().set_language(lang)
        section_title_keys = {key: title_key for key, title_key, _c in _SECTIONS}
        for key, action in self.actions:
            text = i18n.t(lang, section_title_keys[key])
            action.setText(text)
            action.setToolTip(text)
        if self._lbl_lang is not None:
            self._lbl_lang.setText(" " + i18n.t(lang, "lang_label") + " ")
