# -*- coding: utf-8 -*-
"""
tabla_fija.py
--------------
`TablaColumnasFijas`: un `QTableWidget` cuyas primeras columnas (por
defecto "Incluir" y "Nombre") quedan FIJAS a la izquierda mientras el
resto de la tabla se desplaza en horizontal -- pedido explícito del
usuario para la previsualización de "Importar datos de campo" (la tabla
tiene ~68 columnas y el nombre del punto se perdía de vista al ir a
columnas lejanas como Descriptor, Comentario o Surveyor).

Técnica (la del ejemplo "Frozen Column" de Qt): una segunda vista
(`QTableView`) COMPARTE el mismo modelo y la misma selección que la
tabla, muestra sólo las columnas fijas y se coloca encima del borde
izquierdo de la tabla. Como el modelo es el mismo, editar una celda,
marcar la casilla o cambiar el color de una fila se ve en ambas vistas
sin ningún código extra, y las señales `itemChanged`/`cellChanged` de la
tabla se siguen emitiendo con normalidad desde cualquiera de las dos.

Sólo usa `qgis.PyQt` (PyQt5 o PyQt6 según la versión de QGIS).
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QFrame, QHeaderView, QTableView, QTableWidget


def _enum(clase, nombre, subespacio):
    """Valor de un enum de Qt tanto en su forma escopada (PyQt6) como en
    la plana (PyQt5) -- ver `_valor_enum` en gnsseismic_windows.py."""
    sub = getattr(clase, subespacio, None)
    if sub is not None:
        valor = getattr(sub, nombre, None)
        if valor is not None:
            return valor
    return getattr(clase, nombre)


class TablaColumnasFijas(QTableWidget):
    def __init__(self, filas, columnas, fijas=(0, 1), parent=None):
        super().__init__(filas, columnas, parent)
        self._fijas = tuple(fijas)
        self._en_sync = False

        sin_barra = _enum(Qt, "ScrollBarAlwaysOff", "ScrollBarPolicy")
        por_pixel = _enum(QAbstractItemView, "ScrollPerPixel", "ScrollMode")
        self.setHorizontalScrollMode(por_pixel)

        cong = QTableView(self)
        self._cong = cong
        cong.setModel(self.model())
        cong.setSelectionModel(self.selectionModel())
        cong.setFrameShape(_enum(QFrame, "NoFrame", "Shape"))
        cong.setHorizontalScrollBarPolicy(sin_barra)
        cong.setVerticalScrollBarPolicy(sin_barra)
        cong.setHorizontalScrollMode(por_pixel)
        cong.verticalHeader().hide()
        cong.horizontalHeader().setSectionResizeMode(_enum(QHeaderView, "Interactive", "ResizeMode"))
        cong.horizontalHeader().setHighlightSections(False)
        cong.verticalHeader().setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
        cong.setStyleSheet("QTableView { border: none; border-right: 2px solid #7f8c8d; }")
        for col in range(columnas):
            if col not in self._fijas:
                cong.setColumnHidden(col, True)

        # Sincronización: scroll vertical (ambos sentidos), ancho de las
        # columnas fijas (ambos sentidos) y alto de las filas.
        self.verticalScrollBar().valueChanged.connect(cong.verticalScrollBar().setValue)
        cong.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        self.horizontalHeader().sectionResized.connect(self._ancho_cambiado_tabla)
        cong.horizontalHeader().sectionResized.connect(self._ancho_cambiado_cong)
        self.verticalHeader().sectionResized.connect(self._alto_cambiado)

        # La vista fija encima del viewport (si no, quedaría tapada).
        cong.raise_()
        self._actualizar_geometria()

    # -- API ---------------------------------------------------------------
    def columnas_fijas(self):
        return self._fijas

    def vista_fija(self):
        return self._cong

    # -- sincronización ----------------------------------------------------
    def _ancho_cambiado_tabla(self, col, _viejo, nuevo):
        if col in self._fijas and not self._en_sync:
            self._en_sync = True
            try:
                self._cong.setColumnWidth(col, nuevo)
            finally:
                self._en_sync = False
        if col in self._fijas:
            self._actualizar_geometria()

    def _ancho_cambiado_cong(self, col, _viejo, nuevo):
        if col in self._fijas and not self._en_sync:
            self._en_sync = True
            try:
                self.setColumnWidth(col, nuevo)
            finally:
                self._en_sync = False
            self._actualizar_geometria()

    def _alto_cambiado(self, fila, _viejo, nuevo):
        self._cong.setRowHeight(fila, nuevo)

    def _ancho_fijo(self):
        return sum(self.columnWidth(c) for c in self._fijas if not self.isColumnHidden(c))

    def _actualizar_geometria(self):
        if not hasattr(self, "_cong"):
            return
        for c in self._fijas:
            if self._cong.columnWidth(c) != self.columnWidth(c):
                self._cong.setColumnWidth(c, self.columnWidth(c))
        marco = self.frameWidth()
        self._cong.horizontalHeader().setFixedHeight(self.horizontalHeader().height())
        self._cong.setGeometry(
            self.verticalHeader().width() + marco, marco,
            self._ancho_fijo(), self.viewport().height() + self.horizontalHeader().height(),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._actualizar_geometria()

    def showEvent(self, event):
        super().showEvent(event)
        self._actualizar_geometria()

    def updateGeometries(self):  # noqa: N802 - override de Qt
        super().updateGeometries()
        self._actualizar_geometria()

    # -- navegación con teclado: que el cursor no quede tapado por las columnas fijas
    def moveCursor(self, accion, modificadores):  # noqa: N802 - override de Qt
        actual = super().moveCursor(accion, modificadores)
        if (
            accion == _enum(QAbstractItemView, "MoveLeft", "CursorAction")
            and actual.isValid() and actual.column() not in self._fijas
        ):
            x = self.visualRect(actual).topLeft().x()
            ancho = self._ancho_fijo()
            if x < ancho:
                barra = self.horizontalScrollBar()
                barra.setValue(int(barra.value() + x - ancho))
        return actual

    def scrollTo(self, indice, sugerencia=None):  # noqa: N802 - override de Qt
        # Las celdas fijas nunca necesitan desplazar la tabla en horizontal.
        if indice.column() in self._fijas:
            return
        if sugerencia is None:
            super().scrollTo(indice)
        else:
            super().scrollTo(indice, sugerencia)
