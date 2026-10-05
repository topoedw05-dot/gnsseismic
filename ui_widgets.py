# -*- coding: utf-8 -*-
"""
ui_widgets.py
--------------
Widgets propios, reutilizables, para los rediseños de "Importar datos de
campo" (v2.63.0) y "Preplot Sísmico" (v2.65.0):

  * `PestanasAltoActual` -- `QTabWidget` cuyo alto preferido es el de la
                        pestaña ACTIVA (el de fábrica reserva el de la más
                        alta), para que el resto del alto sea de lo que
                        haya debajo.

  * `ToggleSwitch`   -- un `QCheckBox` dibujado como interruptor moderno
                        (pastilla con perilla). Sigue siendo un QCheckBox
                        (`isChecked`, `setChecked`, señal `toggled`...), así
                        que el resto del código no cambia.
  * `AcordeonSeccion` -- bloque desplegable (acordeón): una cabecera
                        clicable que muestra el título y un RESUMEN del
                        estado actual de la sección, y un contenido que
                        sólo se ve al desplegarlo. Cerrado ocupa una línea.

Sólo usan `qgis.PyQt` (PyQt5 o PyQt6 según la versión de QGIS).
"""

from qgis.PyQt.QtCore import QRectF, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QCheckBox, QFrame, QLabel, QListWidget, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)


def _enum(clase, nombre, subespacio):
    """Valor de un enum de Qt tanto en su forma escopada (PyQt6) como en
    la plana (PyQt5) -- ver `_valor_enum` en gnsseismic_windows.py."""
    sub = getattr(clase, subespacio, None)
    if sub is not None:
        valor = getattr(sub, nombre, None)
        if valor is not None:
            return valor
    return getattr(clase, nombre)


class PestanasAltoActual(QTabWidget):
    """`QTabWidget` cuyo `sizeHint` usa el alto de la pestaña activa. Qt
    calcula el de fábrica con la MÁS ALTA de todas las páginas, así que
    cambiar a una pestaña corta dejaba un hueco vacío del alto de la más
    larga. Hay que llamar a `updateGeometry()` al cambiar de pestaña (lo
    hace el controlador en `_on_pestana_preplot_cambiada`)."""

    def sizeHint(self):  # noqa: N802 - override de Qt
        base = super().sizeHint()
        actual = self.currentWidget()
        if actual is None or self.count() == 0:
            return base
        alto_max = max(self.widget(i).sizeHint().height() for i in range(self.count()))
        return QSize(base.width(), max(base.height() - alto_max + actual.sizeHint().height(), 0))


class ListaCompacta(QListWidget):
    """`QListWidget` con un tamaño preferido bajo (el de fábrica, ~190 px
    de alto, hace que la tarjeta que la contiene quede más alta de lo
    necesario); sigue pudiendo estirarse si el layout le da más espacio."""

    def sizeHint(self):  # noqa: N802 - override de Qt
        return QSize(240, 90)


class EtiquetaElidida(QLabel):
    """`QLabel` de una línea para textos largos (p.ej. la ruta de un
    archivo): muestra el texto resumido con "..." en el MEDIO cuando no
    cabe, con el texto completo en el tooltip, y nunca obliga a ensanchar
    la ventana. Imita la API de un `QLineEdit` de sólo lectura (`setText`,
    `text`, `clear`, `setPlaceholderText`) para reemplazarlo sin tocar el
    resto del código."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completo = ""
        self._placeholder = ""
        self.setSizePolicy(_enum(QSizePolicy, "Ignored", "Policy"), _enum(QSizePolicy, "Preferred", "Policy"))
        self._refrescar()

    def setText(self, texto):  # noqa: N802 - API de Qt
        self._completo = texto or ""
        self._refrescar()

    def text(self):
        return self._completo

    def clear(self):
        self.setText("")

    def setPlaceholderText(self, texto):  # noqa: N802 - API de Qt
        self._placeholder = texto or ""
        self._refrescar()

    def minimumSizeHint(self):  # noqa: N802 - override de Qt
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event):  # noqa: N802 - override de Qt
        super().resizeEvent(event)
        self._refrescar()

    def _refrescar(self):
        visible = self._completo or self._placeholder
        ancho = max(self.width() - 4, 20)
        modo = _enum(Qt, "ElideMiddle", "TextElideMode")
        super().setText(self.fontMetrics().elidedText(visible, modo, ancho))
        self.setToolTip(self._completo)


_COLOR_ENCENDIDO = QColor("#2e7d32")  # mismo verde que el botón "Subir"


class ToggleSwitch(QCheckBox):
    """`QCheckBox` con aspecto de interruptor (pastilla + perilla) y el
    texto a la derecha."""

    _PISTA_W = 38
    _PISTA_H = 20
    _SEPARACION = 8

    def __init__(self, texto="", parent=None):
        super().__init__(texto, parent)
        self.setCursor(_enum(Qt, "PointingHandCursor", "CursorShape"))
        self.setSizePolicy(_enum(QSizePolicy, "Preferred", "Policy"), _enum(QSizePolicy, "Fixed", "Policy"))

    def sizeHint(self):  # noqa: N802 - override de Qt
        fm = self.fontMetrics()
        ancho = self._PISTA_W + (self._SEPARACION + fm.horizontalAdvance(self.text()) if self.text() else 0) + 4
        return QSize(ancho, max(self._PISTA_H + 4, fm.height() + 6))

    def minimumSizeHint(self):  # noqa: N802 - override de Qt
        return self.sizeHint()

    def hitButton(self, pos):  # noqa: N802 - override de Qt
        return self.rect().contains(pos)

    def paintEvent(self, _event):  # noqa: N802 - override de Qt
        p = QPainter(self)
        p.setRenderHint(_enum(QPainter, "Antialiasing", "RenderHint"))
        habilitado = self.isEnabled()
        encendido = self.isChecked()
        paleta = self.palette()
        alto = self.height()
        y = (alto - self._PISTA_H) / 2.0
        pista = QRectF(1.0, y, float(self._PISTA_W), float(self._PISTA_H))

        if encendido:
            color_pista = QColor(_COLOR_ENCENDIDO)
        else:
            color_pista = QColor(paleta.mid().color())
        if not habilitado:
            color_pista.setAlpha(110)
        p.setPen(_enum(Qt, "NoPen", "PenStyle"))
        p.setBrush(color_pista)
        p.drawRoundedRect(pista, self._PISTA_H / 2.0, self._PISTA_H / 2.0)

        radio = self._PISTA_H - 6.0
        x_perilla = pista.right() - radio - 3.0 if encendido else pista.left() + 3.0
        p.setBrush(QColor(255, 255, 255, 255 if habilitado else 170))
        p.drawEllipse(QRectF(x_perilla, y + 3.0, radio, radio))

        if self.hasFocus():
            p.setPen(QPen(QColor(paleta.highlight().color()), 1.2))
            p.setBrush(_enum(Qt, "NoBrush", "BrushStyle"))
            p.drawRoundedRect(pista.adjusted(-1.5, -1.5, 1.5, 1.5), self._PISTA_H / 2.0 + 1.5, self._PISTA_H / 2.0 + 1.5)

        if self.text():
            color_texto = QColor(paleta.windowText().color())
            if not habilitado:
                color_texto.setAlpha(120)
            p.setPen(color_texto)
            zona = QRectF(pista.right() + self._SEPARACION, 0.0, self.width() - pista.right() - self._SEPARACION, float(alto))
            alineacion = _enum(Qt, "AlignVCenter", "AlignmentFlag") | _enum(Qt, "AlignLeft", "AlignmentFlag")
            p.drawText(zona, int(getattr(alineacion, "value", alineacion)), self.text())
        p.end()


_ESTILO_CABECERA = (
    "QPushButton { text-align: left; padding: 6px 10px; border: 1px solid palette(mid);"
    " border-radius: 6px; background: palette(window); color: palette(window-text); }"
    "QPushButton:hover { background: palette(midlight); }"
    "QPushButton:checked { border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }"
)
_ESTILO_CONTENIDO = (
    "QFrame#acordeon_contenido { border: 1px solid palette(mid); border-top: none;"
    " border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }"
)


class AcordeonSeccion(QWidget):
    """Bloque desplegable. La cabecera muestra "▸ <título>: <resumen>"
    (cerrado) o "▾ <título>: <resumen>" (abierto); el contenido sólo se
    ve abierto. `set_textos(titulo, resumen)` refresca la cabecera sin
    tocar el estado abierto/cerrado."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._titulo = ""
        self._resumen = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._cabecera = QPushButton()
        self._cabecera.setCheckable(True)
        self._cabecera.setChecked(False)
        self._cabecera.setStyleSheet(_ESTILO_CABECERA)
        self._cabecera.setCursor(_enum(Qt, "PointingHandCursor", "CursorShape"))
        lay.addWidget(self._cabecera)

        self._marco = QFrame()
        self._marco.setObjectName("acordeon_contenido")
        self._marco.setStyleSheet(_ESTILO_CONTENIDO)
        self._marco_lay = QVBoxLayout(self._marco)
        self._marco_lay.setContentsMargins(8, 8, 8, 8)
        self._marco.setVisible(False)
        lay.addWidget(self._marco)

        self._cabecera.toggled.connect(self._on_toggled)
        self._refrescar_texto()

    # -- API ---------------------------------------------------------------
    def set_contenido(self, widget_o_layout):
        """Agrega un widget (o un layout) al contenido desplegable."""
        if isinstance(widget_o_layout, QWidget):
            self._marco_lay.addWidget(widget_o_layout)
        else:
            self._marco_lay.addLayout(widget_o_layout)

    def set_textos(self, titulo, resumen=""):
        self._titulo = titulo
        self._resumen = resumen
        self._refrescar_texto()

    def esta_abierto(self):
        return self._cabecera.isChecked()

    def abrir(self, abierto=True):
        self._cabecera.setChecked(bool(abierto))

    def cabecera(self):
        return self._cabecera

    # -- interno -----------------------------------------------------------
    def _on_toggled(self, abierto):
        self._marco.setVisible(abierto)
        self._refrescar_texto()
        self.toggled.emit(abierto)

    def _refrescar_texto(self):
        flecha = "▾" if self._cabecera.isChecked() else "▸"
        cuerpo = f"{self._titulo}: {self._resumen}" if self._resumen else self._titulo
        self._cabecera.setText(f"{flecha}  {cuerpo}")
