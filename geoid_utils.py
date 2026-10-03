# -*- coding: utf-8 -*-
"""
geoid_utils.py
--------------
Aritmética pura (sin dependencias de QGIS) para aplicar un modelo de
geoide a alturas elipsoidales, tal como se piden en la sección
"Proyecto" (cargar el geoide del proyecto) y en la sección
"Importar datos de campo" (aplicarlo a los puntos importados antes de subirlos
a POSTPLOT).

La lectura del ráster del geoide y el muestreo en cada punto (que sí
necesitan QGIS: QgsRasterLayer / QgsCoordinateTransform) viven en
`gnsseismic_windows.py`; aquí sólo queda la fórmula, para poder probarla
sin QGIS instalado.

Convención estándar de geodesia física:
    H (altura ortométrica / sobre el nivel medio del mar)
        = h (altura elipsoidal, p.ej. WGS84)  -  N (ondulación del geoide)
"""

from typing import Optional


def orthometric_height(ellipsoidal_height: Optional[float], undulation: Optional[float]) -> Optional[float]:
    """H = h - N. Devuelve None si falta cualquiera de los dos valores
    (no se puede calcular una altura ortométrica sin ambos)."""
    if ellipsoidal_height is None or undulation is None:
        return None
    return float(ellipsoidal_height) - float(undulation)
