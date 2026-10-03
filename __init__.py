# -*- coding: utf-8 -*-
"""
gnsseismic
----------
Plugin de QGIS para gestión de proyectos topográficos: base de datos
PREPLOT/POSTPLOT, importación de archivos .dc con aplicación de geoide,
comparación con CSV o con PREPLOT, generación de preplot sísmico y panel
de base de datos con exportación a Shapefile/GeoPackage/SPS.

Nota histórica: este plugin se llamó "Gestor DC Topografía" (identificador
interno `gestor_dc`) hasta la v1.3.0; desde la v2.0.0 se renombró a
"GNSSeismic" (identificador interno `gnsseismic`), y además la interfaz
dejó de ser un único diálogo con pestañas para pasar a un toolbar con un
ícono por sección, cada uno abriendo su propia ventana. QGIS trata este
cambio de identificador como un plugin nuevo: quienes tuvieran instalado
"Gestor DC Topografía" deben desinstalarlo aparte para no quedar con dos
plugins duplicados.
"""


def classFactory(iface):
    from .gnsseismic import GNSSeismicPlugin
    return GNSSeismicPlugin(iface)
