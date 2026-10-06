# -*- coding: utf-8 -*-
"""
i18n.py
-------
Traducciones de la interfaz del plugin (español / inglés), sin
dependencias de QGIS para poder probarlas de forma aislada.

Es un mecanismo de traducción simple y liviano (no usa el sistema
Qt Linguist / archivos .ts-.qm): un diccionario `TR` de
`clave -> {"es": texto, "en": texto}` y una función `t(lang, key, **kw)`
que aplica `str.format(**kw)` si hace falta interpolar valores (rutas,
números, mensajes de error).

`gestor_dc_dialog.py` guarda una lista de "widgets registrados"
(`self._i18n_widgets`) para poder re-aplicar la traducción completa de
la interfaz cuando el usuario cambia el idioma desde el selector de la
parte superior del diálogo, sin tener que reconstruir toda la UI.

Las claves de datos (nombres de tabla como "POSTPLOT"/"PREPLOT", los
valores guardados como Descriptor en la base como "RECEPTOR"/"FUENTE",
"S"/"R" para SPS, los códigos de idioma "es"/"en") NO pasan por este
módulo: viven como `userData` de los combos correspondientes para que
el significado de los datos no cambie al cambiar el idioma de la UI.
"""

from typing import Any

DEFAULT_LANG = "es"

TR = {
    # -- General / ventana -------------------------------------------------
    "window_title": {"es": "GNSSeismic", "en": "GNSSeismic"},
    "lang_label": {"es": "Idioma:", "en": "Language:"},
    "lang_es": {"es": "Español", "en": "Spanish"},
    "lang_en": {"es": "Inglés", "en": "English"},
    "btn_close": {"es": "Cerrar", "en": "Close"},
    "btn_help_tooltip": {"es": "Ayuda de esta sección", "en": "Help for this section"},
    "none_option": {"es": "(ninguna)", "en": "(none)"},
    "ok_title": {"es": "Listo", "en": "Done"},
    "err_title": {"es": "Error", "en": "Error"},
    "warn_title": {"es": "Aviso", "en": "Warning"},
    "no_project_title": {"es": "Sin proyecto", "en": "No project"},
    "no_project_body": {
        "es": "Primero crea o abre un proyecto en la sección \"Proyecto\".",
        "en": "First create or open a project in the \"Project\" section.",
    },

    # -- Secciones (título de cada ícono del toolbar / ventana) --------------
    "tab1_title": {"es": "Proyecto", "en": "Project"},
    "tab2_title": {"es": "Preplot Sísmico", "en": "Seismic Preplot"},
    "tab3_title": {"es": "Importar datos de campo", "en": "Import field data"},
    "tab5_title": {"es": "Base de Datos", "en": "Database"},

    # -- Sección: Proyecto --------------------------------------------------
    "grp_db": {"es": "Base de datos del proyecto", "en": "Project database"},
    "db_path_placeholder": {"es": "Sin proyecto abierto", "en": "No project open"},
    "btn_new_project": {"es": "Nuevo proyecto...", "en": "New project..."},
    "btn_open_project": {"es": "Abrir proyecto existente...", "en": "Open existing project..."},
    "btn_switch_project": {"es": "Mis proyectos...", "en": "My projects..."},
    "btn_refresh_counts": {"es": "Actualizar conteos", "en": "Refresh counts"},
    "lbl_counts": {
        "es": "POSTPLOT: {post}    PREPLOT: {pre}    COMPARACION: {comp}",
        "en": "POSTPLOT: {post}    PREPLOT: {pre}    COMPARISON: {comp}",
    },
    "lbl_counts_empty": {
        "es": "POSTPLOT: -    PREPLOT: -    COMPARACION: -",
        "en": "POSTPLOT: -    PREPLOT: -    COMPARISON: -",
    },
    "lbl_counts_error": {
        "es": "(No se pudieron leer los conteos: {error})",
        "en": "(Could not read the counts: {error})",
    },
    "btn_config_proyecto_show": {
        "es": "▸ Configurar proyecto (CRS, geoide, tipo de levantamiento, factor de escala)",
        "en": "▸ Configure project (CRS, geoid, survey type, scale factor)",
    },
    "btn_config_proyecto_hide": {
        "es": "▾ Ocultar configuración del proyecto",
        "en": "▾ Hide project configuration",
    },
    "grp_crs": {
        "es": "CRS de trabajo (para Este/Norte locales y para medir distancias en la comparación)",
        "en": "Working CRS (for local Easting/Northing and for measuring distances when comparing)",
    },
    "crs_widget_unavailable": {
        "es": "(Selector de CRS no disponible en esta versión de QGIS; se usará EPSG:4326)",
        "en": "(CRS selector not available in this QGIS version; EPSG:4326 will be used)",
    },
    "btn_save_crs": {"es": "Guardar CRS de este proyecto", "en": "Save CRS for this project"},
    "msg_crs_saved": {
        "es": "CRS guardado con este proyecto: {crs}.",
        "en": "CRS saved with this project: {crs}.",
    },
    "crs_saved_note": {
        "es": (
            "El CRS con el que se crea un proyecto queda guardado con él y se "
            "recupera solo al volver a abrirlo o cambiar de proyecto (evita "
            "subir datos con el CRS de otro proyecto). Si necesitás "
            "corregirlo en un proyecto ya abierto, elegí el CRS correcto y "
            "usá \"Aplicar configuración\" (botón del fondo de la sección)."
        ),
        "en": (
            "The CRS a project is created with is saved with it and restored "
            "automatically when you reopen it or switch projects (avoids "
            "uploading data with another project's CRS). To correct it on a "
            "project that is already open, pick the right CRS and use "
            "\"Apply configuration\" (button at the bottom of the section)."
        ),
    },
    "warn_crs_not_saved_title": {"es": "CRS no guardado con este proyecto", "en": "CRS not saved with this project"},
    "warn_crs_not_saved_body": {
        "es": (
            "Este proyecto no tenía un sistema de coordenadas guardado "
            "(viene de una versión anterior del plugin). Se mantiene el CRS "
            "actualmente seleccionado: {crs}. Verificalo antes de subir "
            "datos -- a partir de ahora quedará guardado con este proyecto."
        ),
        "en": (
            "This project had no saved coordinate system (it comes from an "
            "earlier version of the plugin). The currently selected CRS is "
            "kept: {crs}. Double-check it before uploading data -- from now "
            "on it will be saved with this project."
        ),
    },
    "grp_geoid": {"es": "Modelo de geoide (opcional)", "en": "Geoid model (optional)"},
    "geoid_path_placeholder": {
        "es": "Sin geoide asignado al proyecto",
        "en": "No geoid assigned to the project",
    },
    "btn_load_geoid": {"es": "Cargar geoide...", "en": "Load geoid..."},
    "btn_clear_geoid": {"es": "Quitar geoide", "en": "Clear geoid"},
    "geoid_info": {
        "es": (
            "Ondulación N (m) para la altura ortométrica al importar .dc. "
            "Admite ráster (GeoTIFF, GTX, ASCII Grid, Surfer GRD) o .ggf de "
            "Trimble; se guarda con el proyecto."
        ),
        "en": (
            "Undulation N (m), used for orthometric height on .dc import. "
            "Accepts raster (GeoTIFF, GTX, ASCII Grid, Surfer GRD) or "
            "Trimble's .ggf; saved with the project."
        ),
    },
    "btn_accept": {"es": "Aceptar", "en": "Accept"},
    "btn_cancel": {"es": "Cancelar", "en": "Cancel"},
    "grp_factor_escala": {
        "es": "Factor de escala del proyecto (terreno <-> grilla, para Estación Total)",
        "en": "Project scale factor (ground <-> grid, for Total Station)",
    },
    "lbl_factor_escala_lat": {"es": "Latitud de referencia (WGS84):", "en": "Reference latitude (WGS84):"},
    "lbl_factor_escala_lon": {"es": "Longitud de referencia (WGS84):", "en": "Reference longitude (WGS84):"},
    "lbl_factor_escala_altura": {"es": "Altura de referencia (m):", "en": "Reference height (m):"},
    "tip_factor_escala_altura": {
        "es": (
            "Altura media del área de trabajo sobre el elipsoide (o la "
            "elevación/ortométrica, si no tenés la elipsoidal a mano -- la "
            "diferencia entre ambas pesa muy poco en este cálculo)."
        ),
        "en": (
            "Mean height of the work area above the ellipsoid (or the "
            "orthometric elevation, if the ellipsoidal one isn't at hand -- "
            "the difference between the two barely matters for this "
            "calculation)."
        ),
    },
    "btn_click_mapa_factor_escala": {
        "es": "Usar clic en el mapa de QGIS...",
        "en": "Use a click on the QGIS map...",
    },
    "status_factor_escala_esperando_click": {
        "es": "Hacé clic en cualquier punto del mapa de QGIS para tomar su coordenada...",
        "en": "Click anywhere on the QGIS map to pick its coordinate...",
    },
    "status_factor_escala_tomado": {
        "es": "Coordenada tomada del mapa: lat={lat:.8f}, lon={lon:.8f}",
        "en": "Coordinate taken from the map: lat={lat:.8f}, lon={lon:.8f}",
    },
    "status_factor_escala_sin_calcular": {
        "es": "Factor de escala sin calcular todavía para este punto/altura.",
        "en": "Scale factor not calculated yet for this point/height.",
    },
    "btn_calcular_factor_escala": {"es": "Calcular", "en": "Calculate"},
    "lbl_factor_escala_resultado": {
        "es": (
            "Factor de escala (proyección): {factor_proyeccion:.8f}\n"
            "Factor de elevación: {factor_elevacion:.8f}\n"
            "Factor combinado (terreno -> grilla): {factor_combinado:.8f}\n"
            "Convergencia de meridiano: {convergencia:.6f}°"
        ),
        "en": (
            "Scale factor (projection): {factor_proyeccion:.8f}\n"
            "Elevation factor: {factor_elevacion:.8f}\n"
            "Combined factor (ground -> grid): {factor_combinado:.8f}\n"
            "Meridian convergence: {convergencia:.6f}°"
        ),
    },
    "btn_save_factor_escala": {
        "es": "Guardar factor de este proyecto",
        "en": "Save factor for this project",
    },
    "msg_factor_escala_saved": {
        "es": "Factor combinado guardado con este proyecto: {factor:.8f} (punto lat={lat:.6f}, lon={lon:.6f}, altura={altura:.2f} m).",
        "en": "Combined factor saved with this project: {factor:.8f} (point lat={lat:.6f}, lon={lon:.6f}, height={altura:.2f} m).",
    },
    "warn_factor_escala_crs_geografico_title": {
        "es": "CRS de trabajo geográfico",
        "en": "Working CRS is geographic",
    },
    "warn_factor_escala_crs_geografico_body": {
        "es": (
            "El CRS de trabajo elegido en \"CRS de trabajo\" de arriba es "
            "geográfico (sin proyección, ej. EPSG:4326) -- un factor de "
            "escala sólo tiene sentido para un CRS proyectado (en metros). "
            "Elegí un CRS proyectado arriba antes de calcular esto."
        ),
        "en": (
            "The working CRS chosen in \"Working CRS\" above is geographic "
            "(no projection, e.g. EPSG:4326) -- a scale factor is only "
            "meaningful for a projected CRS (in meters). Pick a projected "
            "CRS above before calculating this."
        ),
    },
    "warn_factor_escala_no_calculado_title": {
        "es": "Factor sin calcular",
        "en": "Factor not calculated",
    },
    "warn_factor_escala_no_calculado_body": {
        "es": "Calculá el factor de escala (botón \"Calcular\") antes de guardarlo.",
        "en": "Calculate the scale factor (\"Calculate\" button) before saving it.",
    },
    "note_factor_escala": {
        "es": (
            "Este grupo NO afecta las coordenadas Este/Norte que ya calcula "
            "el plugin en \"Importar datos de campo\"/\"Base de "
            "Datos\" -- sigue siendo la proyección directa de lat/lon al CRS "
            "de trabajo, sin ningún factor de escala aplicado (investigado y "
            "confirmado en la v2.58.0 contra bases de datos reales de "
            "GPSeismic: así es como GPSeismic calcula sus propias "
            "coordenadas también). Lo que calcula este grupo es el factor de "
            "escala COMBINADO (el de la proyección, que depende de qué tan "
            "lejos esté el punto del meridiano central, multiplicado por el "
            "factor de elevación, que depende de la altura sobre el "
            "elipsoide) de UN punto de referencia -- típicamente el centro "
            "del área de trabajo y su altura media -- con la fórmula "
            "estándar de topografía Factor de elevación = R / (R + altura), "
            "R = 6.371.000 m. Esto todavía no se usa en ningún cálculo del "
            "plugin: es la base para un futuro módulo de Estación Total, "
            "donde SÍ hace falta (para una Estación Total, a diferencia de "
            "un GPS/RTK, la distancia que mide es una distancia real de "
            "terreno, no de grilla -- hay que multiplicarla por este factor "
            "combinado antes de calcular el Este/Norte del punto, para que "
            "coincida con los puntos ya levantados por RTK en el mismo "
            "proyecto). \"Usar clic en el mapa...\" activa una herramienta "
            "que toma la coordenada de donde hagas clic en el canvas de "
            "QGIS (convertida a lat/lon WGS84 automáticamente, sin importar "
            "en qué CRS esté el canvas); la altura hay que escribirla a "
            "mano, porque un clic en el mapa sólo da la posición horizontal. "
            "\"Guardar factor de este proyecto\" lo deja guardado junto con "
            "el CRS/geoide de este proyecto, para cuando se implemente el "
            "módulo de Estación Total."
        ),
        "en": (
            "This group does NOT affect the Easting/Northing the plugin "
            "already computes in \"Import field data\"/\"Database\" "
            "-- that is still a direct projection of lat/lon into the "
            "working CRS, with no scale factor applied (investigated and "
            "confirmed in v2.58.0 against real GPSeismic databases: that is "
            "how GPSeismic computes its own coordinates too). What this "
            "group computes is the COMBINED scale factor (the projection's, "
            "which depends on how far the point is from the central "
            "meridian, times the elevation factor, which depends on height "
            "above the ellipsoid) at ONE reference point -- typically the "
            "center of the work area and its mean height -- using the "
            "standard surveying formula Elevation factor = R / (R + "
            "height), R = 6,371,000 m. This isn't used in any of the "
            "plugin's calculations yet: it's groundwork for a future Total "
            "Station module, where it IS needed (unlike GPS/RTK, a Total "
            "Station measures a real ground distance, not a grid one -- it "
            "has to be multiplied by this combined factor before computing "
            "the point's Easting/Northing, so it agrees with points already "
            "surveyed by RTK in the same project). \"Use a click on the "
            "QGIS map...\" activates a tool that takes the coordinate of "
            "wherever you click on the QGIS canvas (converted to WGS84 "
            "lat/lon automatically, whatever CRS the canvas is in); the "
            "height has to be typed in by hand, since a map click only "
            "gives the horizontal position. \"Save factor for this "
            "project\" stores it alongside this project's CRS/geoid, for "
            "when the Total Station module is implemented."
        ),
    },
    "grp_survey_type": {
        "es": "Tipo de levantamiento (2D/3D)",
        "en": "Survey type (2D/3D)",
    },
    "opt_survey_2d": {"es": "2D", "en": "2D"},
    "opt_survey_3d": {"es": "3D", "en": "3D"},
    "lbl_survey_type": {"es": "Tipo de levantamiento:", "en": "Survey type:"},
    "lbl_survey_az_fuente": {"es": "Azimut línea fuente:", "en": "Source-line azimuth:"},
    "lbl_survey_az_receptora": {"es": "Azimut línea receptora:", "en": "Receiver-line azimuth:"},
    "lbl_survey_cod_fuente": {
        "es": "Códigos Descriptor de línea fuente:",
        "en": "Source-line Descriptor codes:",
    },
    "lbl_survey_cod_receptora": {
        "es": "Códigos Descriptor de línea receptora:",
        "en": "Receiver-line Descriptor codes:",
    },
    "tip_survey_cod_placeholder": {
        "es": "Códigos separados por coma, ej. 60,62,63",
        "en": "Comma-separated codes, e.g. 60,62,63",
    },
    "btn_save_survey_type": {
        "es": "Guardar configuración de levantamiento",
        "en": "Save survey configuration",
    },
    "msg_survey_config_saved": {
        "es": "Configuración de levantamiento guardada con este proyecto.",
        "en": "Survey configuration saved with this project.",
    },
    "err_survey_codes_required": {
        "es": (
            "Para un proyecto 3D hay que indicar al menos un código Descriptor "
            "de línea fuente y uno de línea receptora."
        ),
        "en": (
            "For a 3D project, at least one source-line Descriptor code and one "
            "receiver-line code are required."
        ),
    },
    "err_survey_codes_overlap": {
        "es": "Un mismo código Descriptor no puede estar en las dos listas (fuente y receptora) a la vez.",
        "en": "A Descriptor code cannot be listed as both source-line and receiver-line at the same time.",
    },
    "dlg_survey_type_title": {
        "es": "Tipo de levantamiento del proyecto",
        "en": "Project survey type",
    },
    "dlg_survey_type_intro": {
        "es": (
            "¿Este proyecto es un levantamiento 2D o 3D? En un proyecto 3D, "
            "las líneas fuente y receptora suelen tener rumbos distintos: "
            "indicá el azimut de cada una y los códigos Descriptor (el "
            "código real del punto sísmico, no el tipo de solución GNSS) "
            "que identifican a cada línea, para calcular correctamente el "
            "Offset Inline/Crossline de cada punto al importarlo."
        ),
        "en": (
            "Is this project a 2D or 3D survey? In a 3D project, source and "
            "receiver lines usually run in different directions: enter each "
            "line's azimuth and the Descriptor codes (the actual seismic "
            "point code, not the GNSS fix type) that identify each line, so "
            "each point's Inline/Crossline offset is computed correctly on "
            "import."
        ),
    },
    "note_survey_3d": {
        "es": (
            "2D/3D y azimutes de línea (Proyecto): revisado contra el manual "
            "oficial de GPSeismic (Project Manager, \"Entering Azimuths\"). Un "
            "proyecto 3D define dos azimutes fijos -- línea fuente y línea "
            "receptora -- y cada punto se clasifica por su código Descriptor "
            "real (el código de punto sísmico, ej. 60=fuente/VP, 51=receptor -- "
            "no el tipo de solución GNSS KI/SO/FIX/FLOAT) contra las listas de "
            "códigos configuradas. El azimut fijo así asignado se usa para "
            "calcular Offset Inline/Crossline e Inline Azimuth de cada punto, "
            "tanto en la previsualización de \"Importar datos de campo\" como "
            "al subirlo a POSTPLOT. Si un punto no clasifica en ninguna de las "
            "dos listas (o el proyecto es 2D), se sigue usando -- sin cambios "
            "-- el rumbo ajustado automáticamente por Track a partir de la "
            "geometría de PREPLOT. Para un proyecto ya creado en 2D, se puede "
            "pasar a 3D en cualquier momento eligiéndolo en \"Tipo de "
            "levantamiento\" y pulsando \"Aplicar configuración\"."
        ),
        "en": (
            "2D/3D and line azimuths (Project): reviewed against GPSeismic's "
            "official manual (Project Manager, \"Entering Azimuths\"). A 3D "
            "project defines two fixed azimuths -- source line and receiver "
            "line -- and each point is classified by its real Descriptor code "
            "(the seismic point code, e.g. 60=source/VP, 51=receiver -- not "
            "the GNSS fix type KI/SO/FIX/FLOAT) against the configured code "
            "lists. The fixed azimuth assigned this way is used to compute "
            "each point's Offset Inline/Crossline and Inline Azimuth, both in "
            "the \"Import field data\" preview and when uploading to POSTPLOT. "
            "If a point does not classify under either list (or the project "
            "is 2D), the line's automatically fitted PREPLOT-Track bearing is "
            "used instead, unchanged. An existing 2D project can be switched "
            "to 3D at any time by choosing it in \"Survey type\" and "
            "pressing \"Apply configuration\"."
        ),
    },
    "dlg_new_project_title": {
        "es": "Nuevo proyecto - base de datos",
        "en": "New project - database",
    },
    "filter_sqlite": {
        "es": "Base de datos SQLite (*.sqlite)",
        "en": "SQLite database (*.sqlite)",
    },
    "dlg_open_project_title": {
        "es": "Abrir proyecto - base de datos",
        "en": "Open project - database",
    },
    "filter_sqlite_open": {
        "es": "Base de datos SQLite (*.sqlite *.db)",
        "en": "SQLite database (*.sqlite *.db)",
    },
    "dlg_new_project_folder_title": {
        "es": "Elegí la carpeta donde crear el proyecto",
        "en": "Choose the folder where the project will be created",
    },
    "dlg_new_project_name_title": {"es": "Nombre del proyecto", "en": "Project name"},
    "dlg_new_project_name_label": {"es": "Nombre del proyecto:", "en": "Project name:"},
    "err_project_name_invalid": {
        "es": "El nombre del proyecto no puede quedar vacío.",
        "en": "The project name cannot be empty.",
    },
    "confirm_title": {"es": "Confirmar", "en": "Confirm"},
    "confirm_overwrite_title": {"es": "¿Sobrescribir?", "en": "Overwrite?"},
    "confirm_project_overwrite_body": {
        "es": "Ya existe una base de datos en:\n{path}\n\n¿Querés sobrescribirla? Se perderán los datos que tenga.",
        "en": "A database already exists at:\n{path}\n\nOverwrite it? Its existing data will be lost.",
    },
    "msg_project_created_title": {"es": "Proyecto creado", "en": "Project created"},
    "msg_project_created_body": {
        "es": (
            "Proyecto creado en:\n{path}\n\n"
            "Carpetas: database (base de datos), maps, preplot, posplot.\n"
            "CRS de trabajo guardado con este proyecto: {crs}."
        ),
        "en": (
            "Project created at:\n{path}\n\n"
            "Folders: database (database file), maps, preplot, posplot.\n"
            "Working CRS saved with this project: {crs}."
        ),
    },
    "err_project_create": {
        "es": "No se pudo crear el proyecto:\n{error}\n\n{trace}",
        "en": "Could not create the project:\n{error}\n\n{trace}",
    },
    "err_project_open": {
        "es": "No se pudo abrir el proyecto:\n{error}",
        "en": "Could not open the project:\n{error}",
    },
    "dlg_switch_project_title": {"es": "Mis proyectos", "en": "My projects"},
    "col_project_name": {"es": "Nombre", "en": "Name"},
    "col_project_crs": {"es": "CRS", "en": "CRS"},
    "col_project_crs_not_saved": {"es": "(sin guardar)", "en": "(not saved)"},
    "col_project_crs_unavailable": {"es": "(no accesible)", "en": "(unavailable)"},
    "col_project_path": {"es": "Ruta", "en": "Path"},
    "col_project_last_opened": {"es": "Última apertura", "en": "Last opened"},
    "btn_open_selected_project": {"es": "Abrir", "en": "Open"},
    "btn_remove_project_from_list": {"es": "Quitar de la lista", "en": "Remove from list"},
    "btn_add_existing_project": {"es": "Agregar proyecto existente...", "en": "Add existing project..."},
    "info_no_known_projects": {
        "es": "Todavía no hay proyectos registrados. Creá uno nuevo o abrí uno existente.",
        "en": "No projects registered yet. Create a new one or open an existing one.",
    },
    "info_select_project_title": {"es": "Seleccioná un proyecto", "en": "Select a project"},
    "info_select_project_body": {
        "es": "Elegí un proyecto de la lista primero.",
        "en": "Pick a project from the list first.",
    },
    "confirm_remove_project_body": {
        "es": "¿Quitar \"{name}\" de la lista de proyectos? Esto no borra sus archivos.",
        "en": "Remove \"{name}\" from the project list? This does not delete its files.",
    },
    "warn_project_missing_title": {"es": "No se encuentra el proyecto", "en": "Project not found"},
    "warn_project_missing_body": {
        "es": "No se encontró la base de datos en:\n{path}\n\n¿La ruta cambió o se movió la carpeta? Se quitará de la lista.",
        "en": "The database was not found at:\n{path}\n\nDid the folder move? It will be removed from the list.",
    },
    "dlg_load_geoid_title": {"es": "Cargar modelo de geoide", "en": "Load geoid model"},
    "filter_raster": {
        "es": (
            "Geoide o ráster (*.tif *.tiff *.gtx *.asc *.bil *.grd *.ggf);;"
            "Geoide Trimble (*.ggf);;Surfer GRD -- ej. QGeoiCol2004 (*.grd);;"
            "Todos (*.*)"
        ),
        "en": (
            "Geoid or raster (*.tif *.tiff *.gtx *.asc *.bil *.grd *.ggf);;"
            "Trimble geoid (*.ggf);;Surfer GRD -- e.g. QGeoiCol2004 (*.grd);;"
            "All files (*.*)"
        ),
    },
    "err_geoid_invalid": {
        "es": "El archivo elegido no es un ráster válido ni un .ggf de Trimble reconocible.",
        "en": "The chosen file is neither a raster QGIS can read nor a recognizable Trimble .ggf file.",
    },
    "msg_geoid_loaded": {
        "es": "Geoide cargado y asignado al proyecto:\n{path}",
        "en": "Geoid loaded and assigned to the project:\n{path}",
    },
    "err_geoid_load": {
        "es": "No se pudo cargar el geoide:\n{error}",
        "en": "Could not load the geoid:\n{error}",
    },
    "err_geoid_crs_mismatch_title": {
        "es": "El geoide no cubre esa zona",
        "en": "The geoid doesn't cover that area",
    },
    "err_geoid_crs_mismatch_body": {
        "es": (
            "El geoide cargado ({geoid}) no tiene cobertura en la zona de uso "
            "del CRS elegido ({crs}: lon {xmin}° a {xmax}°, lat {ymin}° a "
            "{ymax}°). No se puede crear el proyecto así -- elegí un CRS de "
            "esa zona, o cargá/quitá el geoide, y volvé a intentar."
        ),
        "en": (
            "The loaded geoid ({geoid}) has no coverage in the area of use "
            "of the chosen CRS ({crs}: lon {xmin}° to {xmax}°, lat {ymin}° "
            "to {ymax}°). The project can't be created like this -- pick a "
            "CRS for that area, or load/clear the geoid, and try again."
        ),
    },

    # -- Sección: Preplot Sísmico ---------------------------------------------
    "preplot_intro": {
        "es": (
            "Genera puntos de diseño (preplot) en el CRS de trabajo elegido en la "
            "sección \"Proyecto\" (coordenadas planas Este/Norte, en metros)."
        ),
        "en": (
            "Generates design (preplot) points in the working CRS chosen in the "
            "\"Project\" section (flat Easting/Northing coordinates, in meters)."
        ),
    },
    "grp_preplot_mode": {"es": "Tipo de preplot", "en": "Preplot type"},
    "rb_grid": {"es": "Grilla 3D", "en": "3D Grid"},
    "rb_line": {"es": "Línea 2D", "en": "2D Line"},
    "lbl_origin_x": {"es": "Origen Este (X):", "en": "Origin Easting (X):"},
    "lbl_origin_y": {"es": "Origen Norte (Y):", "en": "Origin Northing (Y):"},
    "lbl_grid_azimuth": {"es": "Azimut de las líneas (°):", "en": "Line azimuth (°):"},
    "tip_grid_azimuth": {
        "es": (
            "Dirección (azimut, grados desde el Norte) a lo largo de la cual "
            "avanzan las estaciones dentro de cada línea. Las líneas se separan "
            "perpendicularmente a esta dirección."
        ),
        "en": (
            "Direction (azimuth, degrees from North) along which stations advance "
            "within each line. Lines are spaced perpendicular to this direction."
        ),
    },
    "lbl_line_spacing": {"es": "Espaciamiento entre líneas (m):", "en": "Line spacing (m):"},
    "lbl_station_spacing": {"es": "Espaciamiento entre estaciones (m):", "en": "Station spacing (m):"},
    "lbl_n_lines": {"es": "Número de líneas:", "en": "Number of lines:"},
    "lbl_n_stations": {"es": "Estaciones por línea:", "en": "Stations per line:"},
    "lbl_first_line": {"es": "Primer número de línea:", "en": "First line number:"},
    "lbl_line_incr": {"es": "Incremento entre líneas:", "en": "Line increment:"},
    "lbl_first_station": {"es": "Primer número de estación:", "en": "First station number:"},
    "lbl_station_incr": {"es": "Incremento entre estaciones:", "en": "Station increment:"},
    "lbl_line_digits": {"es": "Dígitos del número de línea:", "en": "Line number digits:"},
    "lbl_station_digits": {"es": "Dígitos del número de estación:", "en": "Station number digits:"},
    "lbl_descriptor": {"es": "Descriptor:", "en": "Descriptor:"},
    "descriptor_receiver": {"es": "RECEPTOR", "en": "RECEIVER"},
    "descriptor_source": {"es": "FUENTE", "en": "SOURCE"},
    "descriptor_none": {"es": "(sin descriptor)", "en": "(no descriptor)"},
    "grp_line_mode": {"es": "Cómo definir la línea", "en": "How to define the line"},
    "rb_line_two_points": {"es": "Entre dos puntos", "en": "Between two points"},
    "rb_line_azimuth": {"es": "Punto de inicio + azimut + longitud", "en": "Start point + azimuth + length"},
    "lbl_start_x": {"es": "Punto inicial Este (X):", "en": "Start point Easting (X):"},
    "lbl_start_y": {"es": "Punto inicial Norte (Y):", "en": "Start point Northing (Y):"},
    "lbl_end_x": {"es": "Punto final Este (X):", "en": "End point Easting (X):"},
    "lbl_end_y": {"es": "Punto final Norte (Y):", "en": "End point Northing (Y):"},
    "lbl_azimuth": {"es": "Azimut (°):", "en": "Azimuth (°):"},
    "lbl_length": {"es": "Longitud total (m):", "en": "Total length (m):"},
    "lbl_line_number": {"es": "Número de línea:", "en": "Line number:"},
    "chk_include_end": {
        "es": "Incluir el punto final aunque no calce exacto con el espaciamiento",
        "en": "Include the end point even if it doesn't land exactly on the spacing",
    },
    "btn_preplot_generate": {
        "es": "Generar y ver en el mapa (capa temporal)",
        "en": "Generate and view on map (temporary layer)",
    },
    "btn_preplot_save": {"es": "Guardar en PREPLOT", "en": "Save to PREPLOT"},
    "lbl_preplot_empty": {"es": "Sin puntos generados todavía.", "en": "No points generated yet."},
    "lbl_preplot_summary": {
        "es": "{n} puntos generados ({modo}).",
        "en": "{n} points generated ({modo}).",
    },
    "preplot_mode_grid": {"es": "grilla 3D", "en": "3D grid"},
    "preplot_mode_line": {"es": "línea 2D", "en": "2D line"},
    "log_preplot_generated": {
        "es": "Generados {n} puntos ({modo}).",
        "en": "Generated {n} points ({modo}).",
    },
    "warn_invalid_params_title": {"es": "Parámetros inválidos", "en": "Invalid parameters"},
    "info_nothing_to_save_title": {"es": "Nada que guardar", "en": "Nothing to save"},
    "info_nothing_to_save_body": {
        "es": "Primero genera un preplot con el botón de arriba.",
        "en": "First generate a preplot with the button above.",
    },
    "log_preplot_saved": {
        "es": "{n} puntos guardados en PREPLOT.",
        "en": "{n} points saved to PREPLOT.",
    },
    "msg_preplot_saved_body": {
        "es": "{n} puntos guardados en la tabla PREPLOT.",
        "en": "{n} points saved to the PREPLOT table.",
    },
    "err_preplot_save": {
        "es": "No se pudo guardar en PREPLOT:\n{error}\n\n{trace}",
        "en": "Could not save to PREPLOT:\n{error}\n\n{trace}",
    },

    # -- Preplot externo (SPS de Omni 3D/mesa de Sercel, o capa de QGIS) ----
    "grp_preplot_external": {
        "es": "Importar preplot externo (Omni 3D, mesa de Sercel, capa de QGIS)",
        "en": "Import external preplot (Omni 3D, Sercel console, QGIS layer)",
    },
    "note_preplot_external": {
        "es": (
            "Sube a PREPLOT un preplot ya armado en otro software, en vez de "
            "generarlo aquí. SPS: se lee tal cual, asumiendo que sus "
            "coordenadas ya están en el CRS de trabajo del proyecto. Capa de "
            "QGIS: elegís una capa de puntos ya cargada en el proyecto "
            "(shapefile, GeoPackage, o un CSV delimitado por comas que ya "
            "hayas agregado como capa de puntos) y qué campo de esa capa es "
            "cada dato; las coordenadas se toman del CRS propio de la capa."
        ),
        "en": (
            "Uploads to PREPLOT a preplot already built in other software, "
            "instead of generating it here. SPS: read as-is, assuming its "
            "coordinates are already in the project's working CRS. QGIS "
            "layer: choose a point layer already loaded in the project "
            "(shapefile, GeoPackage, or a comma-delimited CSV you already "
            "added as a point layer) and which field of that layer is which "
            "data; coordinates are taken from the layer's own CRS."
        ),
    },
    "lbl_processor": {"es": "Persona que sube los datos (Processor)", "en": "Person uploading the data (Processor)"},
    "btn_import_sps": {
        "es": "Importar SPS (Omni 3D / mesa de Sercel)...",
        "en": "Import SPS (Omni 3D / Sercel console)...",
    },
    "dlg_import_sps_title": {"es": "Importar archivo SPS", "en": "Import SPS file"},
    "filter_sps": {
        "es": "Archivos SPS (*.sps *.S01 *.R01 *.s01 *.r01);;Todos los archivos (*)",
        "en": "SPS files (*.sps *.S01 *.R01 *.s01 *.r01);;All files (*)",
    },
    "err_sps_read": {"es": "No se pudo leer el archivo SPS:\n{error}", "en": "Could not read the SPS file:\n{error}"},
    "warn_sps_empty_title": {"es": "Sin puntos en el SPS", "en": "No points in the SPS"},
    "warn_sps_empty_body": {
        "es": "No se encontró ningún registro de punto ('S' o 'R') válido en ese archivo.",
        "en": "No valid point record ('S' or 'R') was found in that file.",
    },
    "btn_import_qld": {
        "es": "Importar QLD...",
        "en": "Import QLD...",
    },
    "dlg_import_qld_title": {"es": "Importar archivo QLD", "en": "Import QLD file"},
    "filter_qld": {
        "es": "Archivos QLD (*.qld);;Todos los archivos (*)",
        "en": "QLD files (*.qld);;All files (*)",
    },
    "err_qld_read": {"es": "No se pudo leer el archivo QLD:\n{error}", "en": "Could not read the QLD file:\n{error}"},
    "warn_qld_empty_title": {"es": "Sin puntos en el QLD", "en": "No points in the QLD"},
    "warn_qld_empty_body": {
        "es": "No se encontró ningún punto con nombre válido en ese archivo.",
        "en": "No point with a valid name was found in that file.",
    },
    "log_qld_datum_warning": {
        "es": "Aviso del archivo QLD: {warning}",
        "en": "Warning from the QLD file: {warning}",
    },
    "lbl_ext_layer": {"es": "Capa de QGIS:", "en": "QGIS layer:"},
    "btn_refresh_layers": {"es": "Actualizar lista de capas", "en": "Refresh layer list"},
    "opt_select_layer": {"es": "(elegir capa)", "en": "(choose a layer)"},
    "lbl_ext_col_track": {
        "es": "Campo de Línea/Track (opcional):",
        "en": "Line/Track field (optional):",
    },
    "lbl_ext_col_bin": {
        "es": "Campo de Estación/Bin (opcional):",
        "en": "Station/Bin field (optional):",
    },
    "lbl_ext_col_descriptor": {
        "es": "Campo Descriptor (opcional):",
        "en": "Descriptor field (optional):",
    },
    "btn_import_capa_qgis": {
        "es": "Importar capa de QGIS a la previsualización",
        "en": "Import QGIS layer to preview",
    },
    "warn_no_layers_title": {"es": "Sin capas disponibles", "en": "No layers available"},
    "warn_no_layers_body": {
        "es": (
            "No hay ninguna capa de puntos cargada en QGIS. Cargá primero el "
            "shapefile, GeoPackage o CSV (como capa de puntos) que querés "
            "importar."
        ),
        "en": (
            "There is no point layer loaded in QGIS. First load the "
            "shapefile, GeoPackage or CSV (as a point layer) you want to "
            "import."
        ),
    },
    "info_select_layer_title": {"es": "Elegí una capa", "en": "Choose a layer"},
    "info_select_layer_body": {
        "es": "Elegí primero, en la lista, la capa de QGIS que querés importar.",
        "en": "First choose, from the list, the QGIS layer you want to import.",
    },
    "warn_missing_name_field_title": {"es": "Falta el campo de nombre", "en": "Missing name field"},
    "warn_missing_name_field_body": {
        "es": "Elegí qué campo de la capa contiene el nombre/código de cada punto.",
        "en": "Choose which field of the layer holds each point's name/code.",
    },
    "warn_layer_no_points_title": {
        "es": "La capa no tiene geometría de puntos",
        "en": "Layer has no point geometry",
    },
    "warn_layer_no_points_body": {
        "es": "Esa capa no tiene geometría de puntos (o está vacía); no se puede importar a PREPLOT así.",
        "en": "That layer has no point geometry (or is empty); it can't be imported to PREPLOT this way.",
    },
    "err_layer_import": {
        "es": "No se pudo leer la capa:\n{error}",
        "en": "Could not read the layer:\n{error}",
    },
    "col_source": {"es": "Origen", "en": "Source"},
    "col_track": {"es": "Línea", "en": "Line"},
    "col_bin": {"es": "Estación", "en": "Station"},
    "col_easting": {"es": "Este", "en": "Easting"},
    "col_northing": {"es": "Norte", "en": "Northing"},
    "col_elevation": {"es": "Cota", "en": "Elevation"},
    "status_duplicate_preplot": {"es": "Ya existe en PREPLOT", "en": "Already exists in PREPLOT"},
    "status_new_point": {"es": "Punto nuevo", "en": "New point"},
    "lbl_preplot_ext_summary": {
        "es": "{n} puntos en la previsualización ({dup} posibles duplicados).",
        "en": "{n} points in preview ({dup} possible duplicates).",
    },
    "btn_clear_preview": {"es": "Limpiar previsualización", "en": "Clear preview"},
    "btn_upload_preplot_external": {
        "es": "Subir seleccionados a PREPLOT",
        "en": "Upload selected to PREPLOT",
    },
    "log_preplot_ext_saved": {
        "es": "{n} puntos de preplot externo guardados en PREPLOT.",
        "en": "{n} external preplot points saved to PREPLOT.",
    },

    # -- Rediseño v2.65.0 de "Preplot Sísmico": 3 pestañas, formulario en
    # bloques, barra de acciones fija, tabla ampliada y CTA verde ---------
    "pp_tab_generar": {"es": "Generar preplot manual", "en": "Generate preplot manually"},
    "pp_tab_archivo": {"es": "Importar archivo externo (SPS / QLD)", "en": "Import external file (SPS / QLD)"},
    "pp_tab_capa": {"es": "Importar capa de QGIS", "en": "Import QGIS layer"},
    "pp_card_a": {"es": "A. Geometría base", "en": "A. Base geometry"},
    "pp_card_b": {"es": "B. Espaciados y líneas", "en": "B. Spacing and lines"},
    "pp_card_c": {"es": "C. Indexación y nomenclatura", "en": "C. Indexing and naming"},
    "pp_lbl_tipo": {"es": "Tipo de preplot:", "en": "Preplot type:"},
    "pp_lbl_def_linea": {"es": "Definir la línea:", "en": "Define the line:"},
    "pp_origen_x": {"es": "Origen Este (X)", "en": "Origin Easting (X)"},
    "pp_origen_y": {"es": "Origen Norte (Y)", "en": "Origin Northing (Y)"},
    "pp_azimut": {"es": "Azimut de líneas (°)", "en": "Line azimuth (°)"},
    "pp_ini_x": {"es": "Inicio Este (X)", "en": "Start Easting (X)"},
    "pp_ini_y": {"es": "Inicio Norte (Y)", "en": "Start Northing (Y)"},
    "pp_fin_x": {"es": "Final Este (X)", "en": "End Easting (X)"},
    "pp_fin_y": {"es": "Final Norte (Y)", "en": "End Northing (Y)"},
    "pp_longitud": {"es": "Longitud total (m)", "en": "Total length (m)"},
    "pp_dist_lineas": {"es": "Distancia entre líneas (m)", "en": "Distance between lines (m)"},
    "pp_dist_estaciones": {"es": "Distancia entre estaciones (m)", "en": "Distance between stations (m)"},
    "pp_n_lineas": {"es": "Número de líneas", "en": "Number of lines"},
    "pp_n_estaciones": {"es": "Estaciones por línea", "en": "Stations per line"},
    "pp_num_linea": {"es": "Número de línea", "en": "Line number"},
    "pp_primer_linea": {"es": "Primer Nº de línea", "en": "First line no."},
    "pp_incr_linea": {"es": "Incremento de líneas", "en": "Line increment"},
    "pp_dig_linea": {"es": "Dígitos Nº de línea", "en": "Line no. digits"},
    "pp_primer_estacion": {"es": "Primer Nº de estación", "en": "First station no."},
    "pp_incr_estacion": {"es": "Incremento de estación", "en": "Station increment"},
    "pp_dig_estacion": {"es": "Dígitos Nº de estación", "en": "Station no. digits"},
    "pp_descriptor": {"es": "Descriptor", "en": "Descriptor"},
    "pp_tb_generar": {"es": "🛠  Generar en mapa (temporal)", "en": "🛠  Generate on map (temporary)"},
    "pp_tb_limpiar": {"es": "🧹  Limpiar previsualización", "en": "🧹  Clear preview"},
    "pp_tb_guardar": {"es": "💾  Guardar en PREPLOT", "en": "💾  Save to PREPLOT"},
    "pp_tip_generar": {
        "es": "Genera los puntos con los parámetros de arriba y los muestra en el mapa como una capa temporal "
              "(la capa anterior se reemplaza).",
        "en": "Generates the points with the parameters above and shows them on the map as a temporary layer "
              "(the previous one is replaced).",
    },
    "pp_tip_limpiar": {
        "es": "Quita la capa temporal del mapa y vacía la tabla; no toca lo ya guardado en PREPLOT.",
        "en": "Removes the temporary layer from the map and empties the table; what is already saved in PREPLOT is untouched.",
    },
    "pp_tip_guardar": {
        "es": "Guarda en la tabla PREPLOT del proyecto los puntos generados.",
        "en": "Saves the generated points to the project's PREPLOT table.",
    },
    "pp_estado_vacio": {"es": "Sin puntos generados", "en": "No points generated"},
    "pp_estado_listo": {
        "es": "{n} puntos generados ({modo})",
        "en": "{n} points generated ({modo})",
    },
    "pp_gen_truncado": {
        "es": "Se muestran los primeros {shown} de {n} puntos (todos se guardan).",
        "en": "Showing the first {shown} of {n} points (all of them are saved).",
    },
    "pp_card_archivo": {"es": "Archivo SPS o QLD", "en": "SPS or QLD file"},
    "pp_card_capa": {"es": "Capa de puntos de QGIS", "en": "QGIS point layer"},
    "pp_lbl_dig_linea_ext": {"es": "Dígitos Nº de línea", "en": "Line no. digits"},
    "pp_lbl_dig_estacion_ext": {"es": "Dígitos Nº de estación", "en": "Station no. digits"},
    "pp_tip_digitos_ext": {
        "es": "Se usan para armar el nombre del punto desde un SPS y para separar línea/estación del nombre en un QLD.",
        "en": "Used to build the point name from an SPS and to split line/station from the name in a QLD.",
    },
    "pp_campo_nombre": {"es": "Nombre / Código", "en": "Name / Code"},
    "pp_campo_linea": {"es": "Línea / Track (opcional)", "en": "Line / Track (optional)"},
    "pp_campo_estacion": {"es": "Estación / Bin (opcional)", "en": "Station / Bin (optional)"},
    "pp_campo_cota": {"es": "Cota Z (opcional)", "en": "Z / Elevation (optional)"},
    "pp_campo_descriptor": {"es": "Descriptor (opcional)", "en": "Descriptor (optional)"},
    "pp_tip_refrescar_capas": {"es": "Actualizar la lista de capas", "en": "Refresh the layer list"},
    "pp_lbl_processor": {"es": "Processor:", "en": "Processor:"},
    "pp_ph_processor": {"es": "Persona que sube los datos", "en": "Person uploading the data"},

    # -- Rediseño v2.66.0 de "Base de Datos" ---------------------------------
    # -- Rediseño v2.67.0 de "Comparar" --------------------------------------
    "cmp_note_sql": {
        "es": (
            "Comparar dos consultas SQL: elige una consulta A (capa 1) y una B (capa 2) -- las mismas "
            "de la lista de la consola (de ejemplo, guardadas o importadas; \"Personalizada\" usa el "
            "texto de la consola) -- y pulsa el botón azul. Cada consulta debe ser un SELECT y devolver "
            "una columna de nombre (Station_Text, Name...) más WGS84_Latitude/WGS84_Longitude o "
            "Local_Easting/Local_Northing. Se agregan al mapa las dos capas de puntos unidas por líneas "
            "donde el nombre coincide exactamente; los puntos sin pareja llevan otro ícono. Un cuadro "
            "informa cuántos puntos hay en cada capa, cuántos coinciden y cuántos no. No escribe nada "
            "en la base de datos."
        ),
        "en": (
            "Compare two SQL queries: pick a query A (layer 1) and a query B (layer 2) -- the same "
            "ones as in the console list (example, saved or imported; \"Custom\" uses the console "
            "text) -- and press the blue button. Each query must be a SELECT and return a name column "
            "(Station_Text, Name...) plus WGS84_Latitude/WGS84_Longitude or Local_Easting/Local_Northing. "
            "Both point layers are added to the map, joined by lines where the name matches exactly; "
            "points without a partner get a different icon. A dialog reports how many points are in "
            "each layer, how many match and how many do not. Nothing is written to the database."
        ),
    },
    "cmp_lbl_fila": {"es": "Comparar dos consultas SQL:", "en": "Compare two SQL queries:"},
    "cmp_tip_query_a": {
        "es": "Consulta A (capa 1): la misma lista de la consola SQL (de ejemplo, guardadas e importadas).",
        "en": "Query A (layer 1): same list as the SQL console (example, saved and imported).",
    },
    "cmp_tip_query_b": {
        "es": "Consulta B (capa 2): la misma lista de la consola SQL (de ejemplo, guardadas e importadas).",
        "en": "Query B (layer 2): same list as the SQL console (example, saved and imported).",
    },
    "cmp_tip_ejecutar": {
        "es": "Ejecutar la comparación: agrega al mapa las dos capas unidas por líneas donde el nombre coincide y muestra un resumen.",
        "en": "Run the comparison: adds both layers to the map joined by lines where the name matches, and shows a summary.",
    },
    "cmp_res_titulo": {"es": "Comparación de consultas", "en": "Query comparison"},
    "cmp_res_cuerpo": {
        "es": (
            "Capa 1 ({nombre_a}): {n_a} puntos\n"
            "Capa 2 ({nombre_b}): {n_b} puntos\n\n"
            "Coinciden por nombre: {n_coinciden}\n"
            "No coinciden: {n_no}  ({solo_a} sólo en la capa 1, {solo_b} sólo en la capa 2)"
        ),
        "en": (
            "Layer 1 ({nombre_a}): {n_a} points\n"
            "Layer 2 ({nombre_b}): {n_b} points\n\n"
            "Matching by name: {n_coinciden}\n"
            "Not matching: {n_no}  ({solo_a} only in layer 1, {solo_b} only in layer 2)"
        ),
    },
    "cmp_layer_1": {"es": "Comparación capa 1: {nombre}", "en": "Comparison layer 1: {nombre}"},
    "cmp_layer_2": {"es": "Comparación capa 2: {nombre}", "en": "Comparison layer 2: {nombre}"},
    "cmp_layer_enlaces": {"es": "Comparación: enlaces por nombre", "en": "Comparison: links by name"},
    "cmp_leg_coincide_1": {"es": "Coincide con la capa 2", "en": "Matches layer 2"},
    "cmp_leg_no_1": {"es": "Sin pareja en la capa 2", "en": "No partner in layer 2"},
    "cmp_leg_coincide_2": {"es": "Coincide con la capa 1", "en": "Matches layer 1"},
    "cmp_leg_no_2": {"es": "Sin pareja en la capa 1", "en": "No partner in layer 1"},
    "cmp_err_sql_titulo": {"es": "Consulta {letra} ({nombre})", "en": "Query {letra} ({nombre})"},
    "cmp_err_sql_ejecutar": {"es": "No se pudo ejecutar la consulta: {error}", "en": "Could not run the query: {error}"},
    "cmp_err_sql_sin_nombre": {"es": "La consulta no devuelve una columna de nombre (Station_Text, Name, Point...).", "en": "The query does not return a name column (Station_Text, Name, Point...)."},
    "cmp_err_sql_sin_coords": {"es": "La consulta no devuelve coordenadas (WGS84_Latitude/Longitude o Local_Easting/Northing).", "en": "The query returns no coordinates (WGS84_Latitude/Longitude or Local_Easting/Northing)."},
    "cmp_err_sql_vacia": {"es": "La consulta no devolvió puntos con nombre y coordenadas válidas.", "en": "The query returned no points with a name and valid coordinates."},
    "bd_card_sql": {"es": "Consola SQL", "en": "SQL console"},
    "bd_card_buscar": {"es": "Edición rápida: Buscar y reemplazar", "en": "Quick edit: Find and replace"},
    "bd_card_mapeo": {"es": "Mapeo de columnas", "en": "Column mapping"},
    "bd_card_salida": {"es": "Formato de salida", "en": "Output format"},
    "bd_acc_exportar": {"es": "Exportar consulta a", "en": "Export query to"},
    "tip_btn_agregar_condicion_consulta": {
        "es": "Arma una condición con la columna/condición/valor elegidos y la agrega al filtro (WHERE) de la consulta, uniéndola con Y/O si ya había una. Después pulsa Ejecutar.",
        "en": "Builds a condition from the chosen column/condition/value and adds it to the query's filter (WHERE), joined with AND/OR if one already existed. Then press Run.",
    },
    "tip_btn_sql_dev_consulta": {
        "es": "Muestra u oculta el cuadro con la consulta SQL completa -- para escribirla o ajustarla a mano.",
        "en": "Shows or hides the box with the full SQL query -- to write or tweak it by hand.",
    },
    "bd_cond_sql_compleja": {"es": "(consulta personalizada: ver Modo Desarrollador)", "en": "(custom query: see Developer mode)"},
    "err_bd_wiz_sql_compleja": {
        "es": "La consulta actual es más compleja que un SELECT simple de una tabla (tiene JOIN, UNION, GROUP BY o WITH), así que el asistente no puede agregarle la condición. Ábrela en Modo Desarrollador (SQL) y edítala a mano, o elige otra consulta.",
        "en": "The current query is more complex than a simple single-table SELECT (it has JOIN, UNION, GROUP BY or WITH), so the assistant cannot add the condition. Open it in Developer mode (SQL) and edit it by hand, or pick another query.",
    },
    "bd_tb_run": {"es": "▶  Ejecutar", "en": "▶  Run"},
    "bd_tb_save": {"es": "💾  Guardar", "en": "💾  Save"},
    "bd_tb_delete": {"es": "🗑  Borrar", "en": "🗑  Delete"},
    "bd_tb_apply": {"es": "✔  Aplicar", "en": "✔  Apply"},
    "bd_tb_search": {"es": "🔍  Buscar", "en": "🔍  Find"},
    "bd_tb_replace": {"es": "🔄  Reemplazar", "en": "🔄  Replace"},
    "bd_tip_mas": {
        "es": "Renombrar, importar y exportar consultas guardadas",
        "en": "Rename, import and export saved queries",
    },
    "bd_resumen_n": {"es": "{n} registros cargados", "en": "{n} records loaded"},
    "bd_resumen_uno": {"es": "1 registro cargado", "en": "1 record loaded"},
    "bd_map_nombre": {"es": "Nombre / Punto", "en": "Name / Point"},
    "bd_map_linea": {"es": "Línea (Track)", "en": "Line (Track)"},
    "bd_map_punto": {"es": "Punto/Estación SPS (Bin)", "en": "SPS Point/Station (Bin)"},
    "bd_map_x": {"es": "X / Este / Longitud", "en": "X / Easting / Longitude"},
    "bd_map_y": {"es": "Y / Norte / Latitud", "en": "Y / Northing / Latitude"},
    "bd_map_z": {"es": "Z / Elevación", "en": "Z / Elevation"},
    "bd_map_codigo": {"es": "Código", "en": "Code"},
    "bd_export_info": {
        "es": "<table width='360'><tr><td>Shapefile y GeoPackage usan el mapeo de columnas de la izquierda "
              "(Nombre y X/Y obligatorios). Excel (.csv) exporta la consulta tal cual, sin mapeo. "
              "SPS genera archivos .S01 (fuente) o .R01 (receptor): al elegirlo aparecen sus opciones "
              "de tipo de punto, índice y código fijo.</td></tr></table>",
        "en": "<table width='360'><tr><td>Shapefile and GeoPackage use the column mapping on the left "
              "(Name and X/Y required). Excel (.csv) exports the query as-is, without mapping. "
              "SPS writes .S01 (source) or .R01 (receiver) files: choosing it shows its point type, "
              "index and fixed code options.</td></tr></table>",
    },

    # -- Sección: Importar datos de campo (antes "Importar .dc"; desde la
    # v2.8.0 soporta Trimble .dc e Hi-Target CSV, desde la v2.15.0 también
    # CHCNav .rw5, desde la v2.26.0 también la base SQLite de Stonex) ---
    "note_datos_campo": {
        "es": (
            "Por ahora se pueden importar archivos .dc/.dsc de Trimble, "
            "CSV/.raw de Hi-Target (usando sus coordenadas geográficas "
            "B/L/H), .rw5 de CHCNav, .rw5/.raw de SurPad, la base de datos "
            "de la app de campo de Stonex y el CSV de SourceLink (posiciones "
            "de vibros; el Unit ID de cada disparo se sube como Surveyor) y el "
            ".xls de Inova (COG de cada VP, con altura de antena editable en HI). "
            "Está planeado agregar también otras marcas (South)."
        ),
        "en": (
            "Right now Trimble .dc/.dsc files, Hi-Target CSV/.raw files "
            "(using their B/L/H geographic coordinates), CHCNav .rw5 files, "
            "SurPad .rw5/.raw files, Stonex's field-app database and the "
            "SourceLink CSV (vibrator positions; each shot's Unit ID is "
            "uploaded as Surveyor) and the Inova .xls (COG of each VP, antenna "
            "height editable in HI) can be imported. Support for "
            "other brands is planned (South)."
        ),
    },
    "lbl_dc_files": {"es": "Archivos a importar:", "en": "Files to import:"},
    "grp_archivos_campo": {"es": "Archivos de campo", "en": "Field files"},
    "grp_bulk_apply": {"es": "Editar en bloque", "en": "Bulk edit"},
    "grp_finalizar_importacion": {"es": "Finalizar importación", "en": "Finish import"},
    # Botón/solapa desplegable "Archivos de campo" (desde la v2.15.0
    # reemplaza los botones "Agregar .dc.../Agregar CSV Hi-Target..." de
    # antes, uno por marca) y sus ítems, uno por marca soportada -- ver
    # `_CAMPO_BRANDS` en gnsseismic_windows.py para cómo agregar una
    # marca nueva de punta a punta.
    "btn_add_campo_menu": {"es": "Agregar...", "en": "Add..."},
    "tip_btn_add_campo": {
        "es": "Agrega uno o más archivos de campo -- elige la marca en el menú (Trimble .dc/.dsc, Hi-Target CSV/.raw, CHCNav .rw5, Stonex .PD).",
        "en": "Adds one or more field files -- pick the brand from the menu (Trimble .dc/.dsc, Hi-Target CSV/.raw, CHCNav .rw5, Stonex .PD).",
    },
    "menu_add_dc": {"es": "Trimble (.dc/.dsc)", "en": "Trimble (.dc/.dsc)"},
    "menu_add_hitarget": {"es": "Hi-Target (.csv/.raw)", "en": "Hi-Target (.csv/.raw)"},
    "menu_add_chcnav": {"es": "CHCNav (.rw5)", "en": "CHCNav (.rw5)"},
    "menu_add_stonex": {"es": "Stonex (.PD)", "en": "Stonex (.PD)"},
    "menu_add_surpad": {"es": "SurPad (.rw5 / .raw)", "en": "SurPad (.rw5 / .raw)"},
    "btn_remove_dc": {"es": "Quitar", "en": "Remove"},
    "tip_btn_remove_dc": {
        "es": "Quita de la lista el/los archivo(s) seleccionado(s) -- también borra la previsualización, la capa del mapa y la corrección de base si dependían de ese archivo.",
        "en": "Removes the selected file(s) from the list -- also clears the preview, the map layer, and the base correction if they depended on that file.",
    },
    "chk_create_layer": {
        "es": "Crear capa de puntos en QGIS al importar",
        "en": "Create a points layer in QGIS on import",
    },
    "menu_add_sourcelink": {"es": "SourceLink (.csv, vibros)", "en": "SourceLink (.csv, vibroseis)"},
    "dlg_add_sourcelink_title": {"es": "Seleccionar CSV de SourceLink (vibros)", "en": "Select SourceLink CSV files (vibroseis)"},
    "filter_sourcelink_csv": {"es": "Archivos CSV (*.csv);;Todos (*.*)", "en": "CSV files (*.csv);;All files (*.*)"},
    "log_sourcelink_summary": {
        "es": "{name}  —  {n} disparos SourceLink ({unidades} vibros, {anulados} anulados omitidos)",
        "en": "{name}  —  {n} SourceLink shots ({unidades} vibrators, {anulados} voided omitted)",
    },
    "menu_add_inova": {"es": "Inova (.xls, vibros COG)", "en": "Inova (.xls, vibroseis COG)"},
    "dlg_add_inova_title": {"es": "Seleccionar libro Excel de Inova (.xls)", "en": "Select Inova Excel workbook (.xls)"},
    "filter_inova_xls": {"es": "Libros Excel 97-2003 (*.xls *.XLS);;Todos (*.*)", "en": "Excel 97-2003 workbooks (*.xls *.XLS);;All files (*.*)"},
    "log_inova_summary": {
        "es": "{name}  —  {n} VP Inova (COG; {unidades} vibros, {fail} con estado Fail)",
        "en": "{name}  —  {n} Inova VPs (COG; {unidades} vibrators, {fail} with Fail status)",
    },
    "tip_surveyor_inova": {
        "es": (
            "En el .xls de Inova cada VP trae el/los vibro(s) que lo registraron "
            "(columna Unit de la hoja GPS, p.ej. \"7 y 8\"): se sube como Surveyor de "
            "cada punto, por eso este campo no se usa."
        ),
        "en": (
            "In an Inova .xls each VP carries the vibrator(s) that recorded it "
            "(Unit column of the GPS sheet, e.g. \"7 y 8\"): it is uploaded as the "
            "Surveyor of each point, so this field is not used."
        ),
    },
    # -- Proyecto compartido (opcional) -- ver shared_project.py
    "grp_shared": {"es": "Proyecto compartido (opcional)", "en": "Shared project (optional)"},
    "btn_shared_enable": {"es": "Compartir este proyecto...", "en": "Share this project..."},
    # -- Rediseño de la pestaña Proyecto (v2.64.0) --
    "tb_proj_new": {"es": "✚ Nuevo", "en": "✚ New"},
    "tb_proj_open": {"es": "▤ Abrir", "en": "▤ Open"},
    "tb_proj_switch": {"es": "⇄ Mis proyectos", "en": "⇄ My projects"},
    "tb_proj_refresh": {"es": "⟳ Actualizar", "en": "⟳ Refresh"},
    "badge_post": {"es": "POSTPLOT {n}", "en": "POSTPLOT {n}"},
    "badge_pre": {"es": "PREPLOT {n}", "en": "PREPLOT {n}"},
    "badge_comp": {"es": "COMPARACION {n}", "en": "COMPARISON {n}"},
    "tip_badge_post": {"es": "Puntos levantados cargados en POSTPLOT.", "en": "Surveyed points loaded in POSTPLOT."},
    "tip_badge_pre": {"es": "Puntos de diseño cargados en PREPLOT.", "en": "Design points loaded in PREPLOT."},
    "tip_badge_comp": {"es": "Filas guardadas en la tabla COMPARACION.", "en": "Rows saved in the COMPARACION table."},
    "chk_shared_enable": {"es": "Habilitar proyecto compartido en la nube", "en": "Enable shared project in the cloud"},
    "shared_info_tip": {
        "es": (
            "<table width='360'><tr><td><b>Proyecto compartido (opcional)</b><br>"
            "Permite que varias oficinas vean o procesen el mismo proyecto: un solo editor a la vez y el "
            "resto en solo lectura. Funciona con una carpeta sincronizada (por ejemplo Google Drive para "
            "escritorio) o con una carpeta de red o de un servidor local. Deje la carpeta del proyecto "
            "dentro de esa carpeta y active el interruptor. El proyecto sigue siendo un solo archivo; "
            "para dejar de compartir, apague el interruptor.</td></tr></table>"
        ),
        "en": (
            "<table width='360'><tr><td><b>Shared project (optional)</b><br>"
            "Lets several offices view or process the same project: one editor at a time and everyone "
            "else read-only. It works with a synced folder (for example Google Drive for desktop) or with "
            "a network or local-server folder. Keep the project folder inside that folder and turn the "
            "switch on. The project stays a single file; to stop sharing, turn the switch off.</td></tr></table>"
        ),
    },
    "grp_config_geografica": {"es": "Configuración Geográfica", "en": "Geographic configuration"},
    "grp_config_factor_survey": {"es": "Factor de Escala y Tipo de Levantamiento", "en": "Scale factor and survey type"},
    "lbl_crs_title": {"es": "Sistema de coordenadas (CRS)", "en": "Coordinate system (CRS)"},
    "lbl_factor_title": {"es": "Factor de escala (terreno ↔ grilla)", "en": "Scale factor (ground ↔ grid)"},
    "fe_cap_lat": {"es": "Latitud (WGS84)", "en": "Latitude (WGS84)"},
    "fe_cap_lon": {"es": "Longitud (WGS84)", "en": "Longitude (WGS84)"},
    "fe_cap_alt": {"es": "Altura (m)", "en": "Height (m)"},
    "tb_fe_map": {"es": "⌖ Clic en el mapa", "en": "⌖ Click on map"},
    "tb_fe_calc": {"es": "▶ Calcular", "en": "▶ Calculate"},
    "tb_fe_save": {"es": "✔ Guardar factor", "en": "✔ Save factor"},
    "btn_aplicar_config": {"es": "Aplicar configuración", "en": "Apply configuration"},
    "tip_btn_aplicar_config": {
        "es": "Guarda con este proyecto el CRS de trabajo y el tipo de levantamiento (2D/3D) elegidos. El geoide se guarda al elegirlo y el factor de escala con \"Guardar factor\".",
        "en": "Saves the chosen working CRS and survey type (2D/3D) with this project. The geoid is saved when you pick it and the scale factor with \"Save factor\".",
    },
    "msg_config_applied": {
        "es": "Configuración aplicada a este proyecto: CRS {crs}, levantamiento {tipo}.",
        "en": "Configuration applied to this project: CRS {crs}, {tipo} survey.",
    },
    "btn_shared_publish": {"es": "Publicar ahora", "en": "Publish now"},
    "btn_shared_release": {"es": "Dejar de editar", "en": "Stop editing"},
    "btn_shared_takeover": {"es": "Tomar el control", "en": "Take control"},
    "btn_shared_refresh": {"es": "Actualizar", "en": "Refresh"},
    "btn_shared_disable": {"es": "Dejar de compartir", "en": "Stop sharing"},
    "shared_status_no_project": {
        "es": "Abra o cree un proyecto. El modo compartido es opcional.",
        "en": "Open or create a project. Shared mode is optional.",
    },
    "shared_status_not_shared": {
        "es": (
            "Este proyecto NO es compartido: se trabaja directamente sobre su archivo. Para que varias "
            "oficinas lo vean y editen por turnos, deje la carpeta del proyecto dentro de una carpeta "
            "sincronizada o de red (por ejemplo Google Drive para escritorio) y active el interruptor \"Habilitar proyecto compartido en la nube\"."
        ),
        "en": (
            "This project is NOT shared: you work directly on its file. To let several offices view and "
            "edit it in turns, keep the project folder inside a synced folder (for example Google Drive "
            "for desktop) or a network folder and turn on the \"Enable shared project in the cloud\" switch."
        ),
    },
    "shared_status_editor": {
        "es": (
            "Usted es el EDITOR de este proyecto compartido. Trabaja en una copia local y los cambios se "
            "publican solos en la carpeta compartida (última publicación: {fecha}); las demás personas lo "
            "ven en solo lectura."
        ),
        "en": (
            "You are the EDITOR of this shared project. You work on a local copy and changes are published "
            "to the shared folder automatically (last publication: {fecha}); everyone else sees it read-only."
        ),
    },
    "shared_status_viewer": {
        "es": "SOLO LECTURA. {editor} Está viendo la versión publicada el {fecha}.",
        "en": "READ-ONLY. {editor} You are viewing the version published on {fecha}.",
    },
    "shared_viewer_nobody": {"es": "Nadie está editando ahora.", "en": "Nobody is editing right now."},
    "shared_viewer_editing": {
        "es": "Editando ahora: {quien} (desde {desde}, último latido hace {min} min{caida}).",
        "en": "Editing now: {quien} (since {desde}, last heartbeat {min} min ago{caida}).",
    },
    "shared_viewer_stale": {"es": " -- posible sesión caída", "en": " -- session may have crashed"},
    "shared_viewer_newer": {
        "es": "Hay una versión más nueva publicada: pulse \"Actualizar\".",
        "en": "A newer version has been published: press \"Refresh\".",
    },
    "shared_last_error": {"es": "Último aviso: {error}", "en": "Last notice: {error}"},
    "shared_banner_readonly": {
        "es": "PROYECTO COMPARTIDO EN SOLO LECTURA: no se puede escribir en la base de datos desde esta ventana. Use \"Tomar el control\" en la pestaña Proyecto para editar.",
        "en": "SHARED PROJECT IN READ-ONLY MODE: this window cannot write to the database. Use \"Take control\" in the Project tab to edit.",
    },
    "shared_ro_title": {"es": "Solo lectura", "en": "Read-only"},
    "shared_ro_blocked_body": {
        "es": "Este proyecto compartido está abierto en solo lectura: otra persona es la editora. Pulse \"Tomar el control\" en la pestaña Proyecto si necesita editar.",
        "en": "This shared project is open read-only: another person is the editor. Press \"Take control\" in the Project tab if you need to edit.",
    },
    "shared_open_title": {"es": "Proyecto compartido en uso", "en": "Shared project in use"},
    "shared_open_body": {
        "es": (
            "{quien} está editando este proyecto compartido (desde {desde}, último latido hace {min} min{caida}).\n\n"
            "Puede abrirlo en SOLO LECTURA para ver el avance, o TOMAR EL CONTROL (la otra persona pasará a solo "
            "lectura y los cambios que no haya publicado se perderán para el proyecto)."
        ),
        "en": (
            "{quien} is editing this shared project (since {desde}, last heartbeat {min} min ago{caida}).\n\n"
            "You can open it READ-ONLY to see progress, or TAKE CONTROL (the other person becomes read-only and "
            "any changes they have not published are lost to the project)."
        ),
    },
    "btn_shared_open_ro": {"es": "Abrir en solo lectura", "en": "Open read-only"},
    "btn_shared_open_takeover": {"es": "Tomar el control", "en": "Take control"},
    "shared_lock_race_body": {
        "es": "{quien} tomó el proyecto justo ahora. Vuelva a intentarlo.",
        "en": "{quien} just took the project. Please try again.",
    },
    "shared_recover_title": {"es": "Cambios locales sin publicar", "en": "Unpublished local changes"},
    "shared_recover_body": {
        "es": "Se encontró una copia local de este proyecto con cambios que no llegaron a publicarse (una sesión anterior se cerró sin poder publicar). ¿Recuperarla y publicarla? Si responde No, se descarta y se usa la versión publicada.",
        "en": "A local copy of this project with changes that were never published was found (a previous session closed before it could publish). Recover and publish it? If you answer No it is discarded and the published version is used.",
    },
    "shared_publish_error_title": {"es": "No se pudo publicar", "en": "Could not publish"},
    "shared_publish_error_body": {
        "es": "No se pudo publicar en la carpeta compartida (¿sin conexión o Drive sin sincronizar?): {error}\n\nSus cambios siguen a salvo en la copia local y se reintentará solo.",
        "en": "Could not publish to the shared folder (offline or Drive not syncing?): {error}\n\nYour changes are safe in the local copy and publishing will be retried automatically.",
    },
    "shared_publish_ok_title": {"es": "Publicado", "en": "Published"},
    "shared_publish_ok_body": {"es": "Versión publicada ({fecha}).", "en": "Version published ({fecha})."},
    "shared_takeover_title": {"es": "Tomar el control", "en": "Take control"},
    "shared_takeover_body": {
        "es": "{quien} figura como editor{caida}. Si toma el control, esa persona pasará a solo lectura y lo que no haya publicado no se incluirá. ¿Continuar?",
        "en": "{quien} is listed as the editor{caida}. If you take control that person becomes read-only and anything they have not published will not be included. Continue?",
    },
    "shared_lost_title": {"es": "Perdió el control del proyecto", "en": "You lost control of the project"},
    "shared_lost_body": {
        "es": "Otra persona tomó el control de este proyecto compartido. Esta ventana pasó a SOLO LECTURA sobre la versión que esa persona publique.",
        "en": "Someone else took control of this shared project. This window is now READ-ONLY on the version that person publishes.",
    },
    "shared_lost_backup": {
        "es": "Sus cambios sin publicar se guardaron como respaldo en:\n{path}",
        "en": "Your unpublished changes were saved as a backup at:\n{path}",
    },
    "shared_enable_title": {"es": "Compartir proyecto", "en": "Share project"},
    "shared_enable_body": {
        "es": (
            "Se marcará este proyecto como COMPARTIDO:\n{path}\n\n"
            "Usted pasará a ser el editor (trabaja en una copia local y el plugin publica la base en la carpeta "
            "del proyecto) y quien más lo abra lo verá en solo lectura. La carpeta del proyecto debe estar dentro "
            "de una carpeta sincronizada (por ejemplo Google Drive para escritorio). ¿Continuar?"
        ),
        "en": (
            "This project will be marked as SHARED:\n{path}\n\n"
            "You become the editor (you work on a local copy and the plugin publishes the database to the project "
            "folder) and anyone else who opens it sees it read-only. The project folder must be inside a synced "
            "folder (for example Google Drive for desktop). Continue?"
        ),
    },
    "shared_disable_title": {"es": "Dejar de compartir", "en": "Stop sharing"},
    "shared_disable_body": {
        "es": "Se publicará la versión actual y el proyecto volverá a trabajarse directamente sobre su archivo, sin bloqueo. ¿Continuar?",
        "en": "The current version will be published and the project will go back to working directly on its file, without locking. Continue?",
    },
    "shared_new_title": {"es": "¿Proyecto compartido?", "en": "Shared project?"},
    "shared_new_body": {
        "es": "¿Quiere que este proyecto sea COMPARTIDO (varias oficinas, una carpeta sincronizada como Google Drive)?\n\n{path}\n\nEs opcional; se puede activar después desde la pestaña Proyecto.",
        "en": "Do you want this project to be SHARED (several offices, a synced folder such as Google Drive)?\n\n{path}\n\nIt is optional; you can enable it later from the Project tab.",
    },
    "ph_surveyor_unit_id": {"es": "Unit ID (automático)", "en": "Unit ID (automatic)"},
    "tip_surveyor_sourcelink": {
        "es": (
            "En el CSV de SourceLink cada disparo trae el número de su vibrador "
            "(columna Unit ID): se sube como Surveyor de cada punto, por eso este "
            "campo no se usa."
        ),
        "en": (
            "In a SourceLink CSV each shot carries its vibrator number (Unit ID "
            "column): it is uploaded as the Surveyor of each point, so this field is not used."
        ),
    },
    "col_surveyor": {"es": "Surveyor", "en": "Surveyor"},
    "lbl_processor_import": {
        "es": "Processor (quien procesa/sube los datos):",
        "en": "Processor (person processing/uploading the data):",
    },
    "tip_processor_import": {
        "es": (
            "Se guarda en la columna Processor de POSTPLOT para todos los "
            "puntos que se suban en esta importación. Opcional."
        ),
        "en": (
            "Saved in the Processor column of POSTPLOT for every point "
            "uploaded in this import. Optional."
        ),
    },
    "tip_surveyor_archivo": {
        "es": (
            "Topógrafo de este archivo de campo: se guarda en la columna "
            "Surveyor de POSTPLOT para los puntos de ESTE archivo (cada "
            "archivo cargado puede tener un topógrafo distinto). Opcional."
        ),
        "en": (
            "Surveyor of this field file: saved in the Surveyor column of "
            "POSTPLOT for the points of THIS file (each loaded file can have "
            "a different surveyor). Optional."
        ),
    },
    "lbl_track_digits": {
        "es": "Dígitos de línea (Track) en el nombre del punto:",
        "en": "Line (Track) digits in the point name:",
    },
    "tip_track_digits": {
        "es": (
            "Si el nombre del punto es numérico, cuántos dígitos iniciales "
            "corresponden a la línea/track (el resto se toma como "
            "estaca/bin). Ponlo en 0 para no separar."
        ),
        "en": (
            "If the point name is numeric, how many leading digits belong to the "
            "line/track (the rest is taken as the station/bin). Set to 0 to skip "
            "the split."
        ),
    },
    "chk_apply_geoid": {
        "es": "Aplicar geoide del proyecto (calcular altura ortométrica)",
        "en": "Apply the project's geoid (compute orthometric height)",
    },
    "tip_apply_geoid": {
        "es": (
            "Usa el ráster de geoide cargado en la sección \"Proyecto\" para calcular, por "
            "cada punto, Geoid_Height (ondulación N) y Local_Height = WGS84_Height "
            "− N, antes de subir el punto a POSTPLOT. Sólo tiene sentido para "
            "puntos con altura elipsoidal real (algunos formatos .dc reportan 0.0 "
            "en ciertos tipos de registro)."
        ),
        "en": (
            "Uses the geoid raster loaded in the \"Project\" section to compute, for each point, "
            "Geoid_Height (undulation N) and Local_Height = WGS84_Height − N, "
            "before uploading the point to POSTPLOT. Only meaningful for points "
            "with a real ellipsoidal height (some .dc record types report 0.0)."
        ),
    },
    "tip_apply_geoid_disabled": {
        "es": "Carga un geoide en la sección \"Proyecto\" para habilitar esta opción.",
        "en": "Load a geoid in the \"Project\" section to enable this option.",
    },
    "btn_import_dc": {"es": "Previsualizar", "en": "Preview"},
    "tip_btn_import_dc": {
        "es": "Procesa todos los archivos cargados, muestra la previsualización editable de abajo y la compara de una vez contra el PREPLOT del proyecto (si hay uno).",
        "en": "Processes every loaded file, shows the editable preview below, and compares it against the project's PREPLOT (if any) right away.",
    },
    "grp_compare_preplot_import": {
        "es": "Comparación con PREPLOT (antes de subir)",
        "en": "Comparison with PREPLOT (before uploading)",
    },
    "btn_refresh_compare_import": {"es": "Actualizar", "en": "Refresh"},
    "tip_btn_refresh_compare_import": {
        "es": "Vuelve a comparar la previsualización actual contra el PREPLOT con la tolerancia/emparejamiento aproximado elegidos, sin volver a leer los archivos de campo.",
        "en": "Re-compares the current preview against PREPLOT with the chosen tolerance/approximate matching, without re-reading the field files.",
    },
    "note_manual_fields_import": {
        "es": (
            "La altura de antena se detecta automáticamente cuando el "
            "archivo la trae (CSV de Hi-Target siempre; desde la v2.22.0 "
            "también un .dc de Trimble con registro '57KI' o un .rw5 de "
            "CHCNav con registro 'LS,HR'). El .raw de Hi-Target (desde la "
            "v2.23.0) NO la trae -- ese formato no la incluye, se agrega "
            "recién al exportar el CSV -- así que ahí queda vacía como en "
            "un .dc/.rw5 sin esos registros. En todos los casos revísala "
            "antes de subir, sigue siendo editable aquí (o usa \"Aplicar a "
            "todos\"). El comentario no viene en el .dc, el .rw5 ni el "
            ".raw (el CSV de Hi-Target sí lo trae de fábrica): complétalo "
            "aquí si lo necesitas, y corrige el nombre si el usuario se "
            "equivocó en campo. Todo esto se aplica antes de subir a la "
            "base de datos."
        ),
        "en": (
            "Antenna height is auto-detected when the file includes it "
            "(Hi-Target CSV always; since v2.22.0 also a Trimble .dc with "
            "a '57KI' record or a CHCNav .rw5 with an 'LS,HR' record). "
            "Hi-Target's .raw format (since v2.23.0) does NOT include it "
            "-- that format lacks it entirely, it's only added when "
            "exporting to CSV -- so it's left blank there just like a "
            ".dc/.rw5 without those records. Either way, review it before "
            "uploading, it's still editable here (or use \"Apply to "
            "all\"). The comment isn't in the .dc, .rw5, or .raw file "
            "(Hi-Target's CSV does include it): fill it in here if you "
            "need it, and fix the name if it was mistyped in the field. "
            "All of this applies before uploading to the database."
        ),
    },
    "lbl_hi_bulk": {
        "es": "Altura de antena para todos los puntos incluidos:",
        "en": "Antenna height for all included points:",
    },
    "lbl_bulk_apply": {"es": "Campo:", "en": "Field:"},
    "opt_bulk_field_hi": {"es": "Altura de antena (HI)", "en": "Antenna height (HI)"},
    "opt_bulk_field_descriptor": {"es": "Descriptor", "en": "Descriptor"},
    "ph_bulk_descriptor": {
        "es": "Valor de Descriptor a aplicar, ej. 51",
        "en": "Descriptor value to apply, e.g. 51",
    },
    "btn_hi_bulk_apply": {"es": "Aplicar", "en": "Apply"},
    "tip_btn_hi_bulk_apply": {
        "es": "Escribe el valor elegido (Altura de antena o Descriptor) en todos los puntos incluidos que todavía no se subieron -- nunca toca un punto ya subido.",
        "en": "Writes the chosen value (Antenna height or Descriptor) to every included point not yet uploaded -- never touches an already-uploaded point.",
    },
    "col_include": {"es": "Incluir", "en": "Include"},
    "col_file": {"es": "Archivo", "en": "File"},
    "col_type": {"es": "Tipo", "en": "Type"},
    "col_point_name": {"es": "Nombre", "en": "Name"},
    "col_lat": {"es": "Latitud", "en": "Latitude"},
    "col_lon": {"es": "Longitud", "en": "Longitude"},
    "col_height_wgs84": {"es": "Alt. WGS84 (m)", "en": "WGS84 height (m)"},
    "col_antenna_height": {"es": "Alt. antena / HI (m)", "en": "Antenna height / HI (m)"},
    "col_comment": {"es": "Comentario", "en": "Comment"},
    "col_preplot_match": {"es": "PREPLOT emparejado", "en": "Matched PREPLOT"},
    "col_status": {"es": "Estado", "en": "Status"},
    "status_within_tolerance": {"es": "Dentro de tolerancia", "en": "Within tolerance"},
    "status_outside_tolerance": {"es": "Fuera de tolerancia", "en": "Outside tolerance"},
    "status_no_preplot_match": {"es": "Sin PREPLOT", "en": "No PREPLOT"},
    "status_already_uploaded": {"es": "Ya subido", "en": "Already uploaded"},
    "lbl_preview_summary": {
        "es": (
            "{n} punto(s) en la previsualización. Comparación con PREPLOT: "
            "{matched} emparejado(s), {within} dentro de tolerancia."
        ),
        "en": (
            "{n} point(s) in the preview. Comparison with PREPLOT: {matched} "
            "matched, {within} within tolerance."
        ),
    },
    "lbl_preview_summary_no_preplot": {
        "es": (
            "{n} punto(s) en la previsualización. El proyecto no tiene puntos "
            "en PREPLOT para comparar todavía."
        ),
        "en": (
            "{n} point(s) in the preview. The project doesn't have any "
            "PREPLOT points to compare against yet."
        ),
    },
    # -- Consulta/filtro SQL de la previsualización (pedido explícito del
    # usuario: "que se comporte como una base de datos... que pueda hacer
    # querys", inspirado en "View - Grid Display" de QuikView -- ver
    # `_construir_conexion_preview_sqlite`/`_ejecutar_filtro_preview` en
    # gnsseismic_windows.py). A propósito NO incluye ordenar por columna
    # (ver la nota junto a `grp_preview_query` en `_build_tab_importar`).
    "grp_preview_query": {
        "es": "Consultar / filtrar antes de subir",
        "en": "Query / filter before uploading",
    },
    "lbl_preview_filter_preset": {"es": "Filtro predeterminado:", "en": "Default filter:"},
    "preset_preview_filter_custom": {"es": "Personalizado", "en": "Custom"},
    "preset_preview_filter_sin_preplot": {"es": "Sin PREPLOT", "en": "No PREPLOT"},
    "preset_preview_filter_fuera_tolerancia": {"es": "Fuera de tolerancia", "en": "Outside tolerance"},
    "preset_preview_filter_dentro_tolerancia": {"es": "Dentro de tolerancia", "en": "Within tolerance"},
    "preset_preview_filter_ya_subidos": {"es": "Ya subidos", "en": "Already uploaded"},
    "preset_preview_filter_no_incluidos": {"es": "No incluidos", "en": "Not included"},
    "btn_save_preview_filter": {"es": "Guardar...", "en": "Save..."},
    "tip_btn_save_preview_filter": {
        "es": "Guarda el filtro escrito arriba con un nombre propio (o sobrescribe uno ya guardado) para reutilizarlo después en el combo \"Filtro predeterminado\".",
        "en": "Saves the filter written above under your own name (or overwrites one already saved) to reuse later from the \"Default filter\" combo.",
    },
    "dlg_save_filter_title": {"es": "Guardar filtro", "en": "Save filter"},
    "dlg_save_filter_overwrite_body": {
        "es": (
            "El filtro actual del cuadro de texto es distinto al que tenías "
            "guardado \"{nombre}\".\n\n¿Querés sobrescribir \"{nombre}\" con "
            "éste, o guardarlo aparte con otro nombre?"
        ),
        "en": (
            "The current filter in the text box is different from the one you "
            "had saved as \"{nombre}\".\n\nOverwrite \"{nombre}\" with this one, "
            "or save it separately under a new name?"
        ),
    },
    "btn_save_filter_overwrite": {"es": "Sobrescribir \"{nombre}\"", "en": "Overwrite \"{nombre}\""},
    "btn_save_filter_as_new": {"es": "Guardar como nuevo...", "en": "Save as new..."},
    "dlg_save_filter_name_label": {"es": "Nombre para este filtro:", "en": "Name for this filter:"},
    "err_filter_name_invalid": {
        "es": "El nombre del filtro no puede quedar vacío.",
        "en": "The filter name cannot be empty.",
    },
    "err_filter_name_reserved": {
        "es": (
            "Ese nombre ya lo usa un filtro predeterminado del plugin. "
            "Elegí otro nombre para tu filtro."
        ),
        "en": (
            "That name is already used by one of the plugin's default filters. "
            "Pick another name for your filter."
        ),
    },
    "confirm_filter_overwrite_body": {
        "es": "Ya tenés un filtro guardado como \"{nombre}\".\n\n¿Querés sobrescribirlo con la condición actual?",
        "en": "You already have a filter saved as \"{nombre}\".\n\nOverwrite it with the current condition?",
    },
    "info_filter_saved_body": {
        "es": "Filtro \"{nombre}\" guardado.",
        "en": "Filter \"{nombre}\" saved.",
    },
    "info_empty_filter_title": {"es": "Filtro vacío", "en": "Empty filter"},
    "info_empty_filter_body": {
        "es": "Escribí una condición primero (o armala con el asistente de abajo).",
        "en": "Write a condition first (or build one with the wizard below).",
    },
    "grp_filtro_wizard": {
        "es": "Asistente de filtro (sin escribir SQL)",
        "en": "Filter wizard (no SQL needed)",
    },
    "lbl_filtro_wizard_columna": {"es": "Columna:", "en": "Column:"},
    "lbl_filtro_wizard_operador": {"es": "Condición:", "en": "Condition:"},
    "ph_filtro_wizard_valor": {"es": "Valor...", "en": "Value..."},
    "lbl_filtro_wizard_conector": {"es": "Conector:", "en": "Connector:"},
    "opt_filtro_wizard_and": {"es": "Y (AND)", "en": "AND"},
    "opt_filtro_wizard_or": {"es": "O (OR)", "en": "OR"},
    "btn_agregar_condicion_filtro": {"es": "Agregar", "en": "Add"},
    "tip_btn_agregar_condicion_filtro": {
        "es": "Arma una condición con la columna/condición/valor elegidos y la agrega al cuadro de filtro de arriba (uniéndola con Y/O si ya había algo escrito).",
        "en": "Builds a condition from the chosen column/condition/value and adds it to the filter box above (joined with AND/OR if something was already written).",
    },
    "err_filtro_wizard_valor_invalido": {
        "es": (
            "Ese valor no sirve para la columna/condición elegida -- revisá que "
            "sea un número si la columna es numérica, o escribí un valor si la "
            "condición no es \"está vacío\"/\"no está vacío\"."
        ),
        "en": (
            "That value doesn't work for the chosen column/condition -- check "
            "that it's a number if the column is numeric, or type a value if "
            "the condition isn't \"is empty\"/\"is not empty\"."
        ),
    },
    "lbl_filtro_wizard_col_subido": {"es": "Ya subido", "en": "Already uploaded"},
    "op_eq": {"es": "= (igual a)", "en": "= (equals)"},
    "op_neq": {"es": "≠ (distinto de)", "en": "≠ (not equal to)"},
    "op_gt": {"es": "> (mayor que)", "en": "> (greater than)"},
    "op_lt": {"es": "< (menor que)", "en": "< (less than)"},
    "op_gte": {"es": "≥ (mayor o igual)", "en": "≥ (greater or equal)"},
    "op_lte": {"es": "≤ (menor o igual)", "en": "≤ (less or equal)"},
    "op_contains": {"es": "contiene", "en": "contains"},
    "op_not_contains": {"es": "no contiene", "en": "does not contain"},
    "op_is_empty": {"es": "está vacío", "en": "is empty"},
    "op_is_not_empty": {"es": "no está vacío", "en": "is not empty"},
    "tip_preview_filter_placeholder": {
        "es": 'Condición SQL, ej: calidad = "FIX" AND track = 1025',
        "en": 'SQL condition, e.g.: calidad = "FIX" AND track = 1025',
    },
    "btn_apply_preview_filter": {"es": "Filtrar", "en": "Filter"},
    "tip_btn_apply_preview_filter": {
        "es": "Corre la condición del cuadro de arriba contra la previsualización actual y resalta las filas que cumplen.",
        "en": "Runs the condition from the box above against the current preview and highlights the matching rows.",
    },
    "btn_clear_preview_filter": {"es": "Limpiar", "en": "Clear"},
    "tip_btn_clear_preview_filter": {
        "es": "Borra el filtro actual: ya no resalta ninguna fila y \"Marcar\"/\"Desmarcar\" vuelven a aplicar a todos los puntos.",
        "en": "Clears the current filter: no row stays highlighted and \"Check\"/\"Uncheck\" apply to every point again.",
    },
    "btn_mark_include_filtered": {"es": "Marcar", "en": "Check"},
    "tip_btn_mark_include_filtered": {
        "es": "Activa la casilla \"Incluir\" en todos los puntos que cumplen el filtro actual.",
        "en": "Checks the \"Include\" box on every point matching the current filter.",
    },
    "btn_unmark_include_filtered": {"es": "Desmarcar", "en": "Uncheck"},
    "tip_btn_unmark_include_filtered": {
        "es": "Desactiva la casilla \"Incluir\" en todos los puntos que cumplen el filtro actual.",
        "en": "Unchecks the \"Include\" box on every point matching the current filter.",
    },
    "btn_show_filtered_on_map": {"es": "Mapa", "en": "Map"},
    "tip_btn_show_filtered_on_map": {
        "es": "Muestra en una capa aparte de QGIS sólo los puntos que cumplen el filtro actual.",
        "en": "Shows only the points matching the current filter in a separate QGIS layer.",
    },
    "btn_export_preview": {"es": "Exportar...", "en": "Export..."},
    "tip_btn_export_preview": {
        "es": "Exporta la previsualización actual (filtrada, si hay un filtro activo, o completa) en el formato elegido -- sin subir nada a la base de datos.",
        "en": "Exports the current preview (filtered, if a filter is active, or complete) in the chosen format -- without uploading anything to the database.",
    },
    "lbl_preview_filter_summary": {
        "es": "{n} de {total} punto(s) cumplen el filtro (resaltados a la izquierda de la tabla).",
        "en": "{n} of {total} point(s) match the filter (highlighted on the left of the table).",
    },
    "warn_invalid_query_title": {"es": "Consulta inválida", "en": "Invalid query"},
    "warn_invalid_query_body": {
        "es": "No se pudo interpretar la condición SQL: {error}",
        "en": "Couldn't parse the SQL condition: {error}",
    },
    "log_preview_filter_marked_on": {
        "es": "\"Incluir\" marcado en {n} punto(s) filtrado(s) (no incluye los ya subidos).",
        "en": "\"Include\" checked on {n} filtered point(s) (already-uploaded points are skipped).",
    },
    "log_preview_filter_marked_off": {
        "es": "\"Incluir\" desmarcado en {n} punto(s) filtrado(s) (no incluye los ya subidos).",
        "en": "\"Include\" unchecked on {n} filtered point(s) (already-uploaded points are skipped).",
    },
    "layer_preview_filtro": {
        "es": "Previsualización filtrada",
        "en": "Filtered preview",
    },
    "note_preview_query": {
        "es": (
            "Este cuadro filtra la tabla de previsualización con una consulta SQL "
            "de verdad (arma una base en memoria, nunca se guarda en disco), igual "
            "que la solapa \"Base de Datos\" -- útil para revisar sólo una parte de "
            "lo levantado en campo antes de decidir qué subir, o para ubicar en el "
            "mapa de QGIS puntos con algún problema en particular. Sólo escribí la "
            "condición (lo que iría después de un WHERE), por ejemplo:\n\n"
            "  calidad = \"FIX\"\n"
            "  track = 1025 AND incluir = 1\n"
            "  estado = \"fuera_tolerancia\"\n"
            "  comentario LIKE \"%rehacer%\"\n\n"
            "Columnas disponibles: nombre, track, bin, descriptor, lat, lon, este, "
            "norte, altura, hi, comentario, tipo, calidad, survey_mode_text, "
            "survey_mode_value, incluir, subido, archivo, estado (uno de: "
            "sin_match, dentro_tolerancia, fuera_tolerancia, subido). Con un filtro "
            "aplicado, \"Marcar/Desmarcar Incluir\", \"Ver filtrados en el mapa\" y "
            "\"Exportar previsualización\" actúan sólo sobre esas filas (sin "
            "filtro, sobre todas). A propósito esta tabla NUNCA se puede ordenar "
            "haciendo clic en una columna, para no arriesgar que se suba o excluya "
            "el punto equivocado -- las filas que cumplen el filtro se resaltan a "
            "la izquierda en vez de reordenarse.\n\n"
            "\"Filtro predeterminado\" trae listos los filtros más comunes -- por "
            "ejemplo \"Sin PREPLOT\" (los puntos que no matchearon con ningún "
            "PREPLOT, útil para ver de un vistazo qué falta levantar o qué quedó "
            "sin diseño) -- y, al final de la lista, cualquier filtro propio que "
            "hayas guardado antes con \"Guardar filtro...\" (mismo mecanismo que "
            "\"Guardar consulta...\" de \"Base de Datos\": si el filtro elegido ya "
            "es uno guardado, ofrece sobrescribirlo o guardar uno nuevo aparte). "
            "Elegir un filtro de la lista sólo llena el cuadro de texto -- no "
            "filtra solo, hay que apretar \"Filtrar\" después, para poder "
            "revisarlo o ajustarlo primero. Si no querés escribir la condición a "
            "mano, el \"Asistente de filtro\" de abajo arma una por vos: elegí la "
            "columna, la condición (=, contiene, está vacío, etc.) y el valor, y "
            "\"Agregar condición\" la suma al cuadro de texto (con Y/O si ya "
            "había algo escrito) -- podés usarlo varias veces seguidas para armar "
            "condiciones compuestas sin acordarte de la sintaxis SQL."
        ),
        "en": (
            "This box filters the preview table with a real SQL query (it builds "
            "an in-memory database, never saved to disk), the same as the "
            "\"Database\" tab -- useful for reviewing only part of what was "
            "surveyed before deciding what to upload, or for locating points with "
            "a specific issue on the QGIS map. Just type the condition (whatever "
            "would go after a WHERE), for example:\n\n"
            "  calidad = \"FIX\"\n"
            "  track = 1025 AND incluir = 1\n"
            "  estado = \"fuera_tolerancia\"\n"
            "  comentario LIKE \"%redo%\"\n\n"
            "Available columns: nombre, track, bin, descriptor, lat, lon, este, "
            "norte, altura, hi, comentario, tipo, calidad, survey_mode_text, "
            "survey_mode_value, incluir, subido, archivo, estado (one of: "
            "sin_match, dentro_tolerancia, fuera_tolerancia, subido). With a "
            "filter applied, \"Check/Uncheck Include\", \"Show filtered on map\" "
            "and \"Export preview\" act only on those rows (with no filter, on "
            "all of them). This table can NEVER be sorted by clicking a column "
            "header, on purpose, so the wrong point is never uploaded or excluded "
            "by mistake -- rows matching the filter are highlighted on the left "
            "instead of being reordered.\n\n"
            "\"Default filter\" has the most common filters ready to go -- for "
            "example \"No PREPLOT\" (points that didn't match any PREPLOT, handy "
            "for seeing at a glance what's missing or wasn't designed) -- and, at "
            "the end of the list, any filter of your own you saved earlier with "
            "\"Save filter...\" (same mechanism as \"Save query...\" in "
            "\"Database\": if the selected filter is already a saved one, it "
            "offers to overwrite it or save a new one instead). Picking a filter "
            "from the list only fills the text box -- it doesn't filter on its "
            "own, you still press \"Filter\" afterwards, so you can review or "
            "tweak it first. If you'd rather not type the condition by hand, the "
            "\"Filter wizard\" below builds one for you: pick the column, the "
            "condition (=, contains, is empty, etc.) and the value, and \"Add "
            "condition\" appends it to the text box (with AND/OR if something was "
            "already there) -- use it more than once to build compound "
            "conditions without having to remember SQL syntax."
        ),
    },
    "btn_check_db_duplicates": {"es": "Duplicados", "en": "Duplicates"},
    "tip_btn_check_db_duplicates": {
        "es": "Compara los nombres de la previsualización contra los que ya existen en POSTPLOT -- resalta en rojo las filas que coinciden y desmarca su \"Incluir\" (es sólo un aviso, se puede volver a marcar a mano).",
        "en": "Compares the preview's names against the ones already in POSTPLOT -- highlights matching rows in red and unchecks their \"Include\" (it's only a warning, it can be checked again by hand).",
    },
    "note_importar_botones": {
        "es": (
            "Guía de la pestaña (rediseño v2.63.0), por sección:\n\n"
            "\"1. Archivo de Origen\":\n"
            "- \"+\" (esquina superior): agrega uno o más archivos -- elige la "
            "marca en el menú (Trimble .dc/.dsc, Hi-Target CSV/.raw, CHCNav .rw5, "
            "SurPad, Stonex .PD, SourceLink, Inova).\n"
            "- \"-\": quita de la lista el/los archivo(s) seleccionado(s) (y "
            "limpia la previsualización/capa del mapa/corrección de base si "
            "dependían de ese archivo).\n"
            "- \"Previsualizar\": procesa todos los archivos cargados, muestra la "
            "tabla editable de abajo y la compara de una vez contra el PREPLOT.\n\n"
            "\"2. Filtrado Avanzado\":\n"
            "- \"Filtro predeterminado\" + \"Guardar...\": elige un filtro de "
            "fábrica o propio, o guarda el actual con un nombre.\n"
            "- Asistente (Columna | Condición | Valor | Unir con) y \"+\": agrega "
            "la condición armada al filtro actual, sin escribir SQL.\n"
            "- \"▸ Modo Desarrollador (SQL)\": muestra el cuadro con la condición "
            "SQL cruda (oculto por defecto), para editarla a mano.\n"
            "- Barra: \"Filtrar\" (corre la condición y resalta las filas), "
            "\"Limpiar\", \"Mapa\" (sólo los puntos filtrados en una capa "
            "aparte), \"Marcar\"/\"Desmarcar\" (activa/desactiva \"Incluir\" en "
            "los puntos que cumplen el filtro).\n\n"
            "Bloques desplegables (cerrados por defecto; la cabecera resume su "
            "estado, un clic los abre):\n"
            "- \"PREPLOT\": tolerancia (5 m por defecto), emparejamiento "
            "aproximado de nombres (desmarcado por defecto) y \"Actualizar\" "
            "para volver a comparar sin releer los archivos.\n"
            "- \"Editar en bloque\": \"Aplicar\" escribe el valor elegido "
            "(Altura de antena o Descriptor) en todos los puntos incluidos "
            "todavía no subidos.\n"
            "- \"Corrección de base RTK\" (sólo visible si hay una base "
            "detectada): \"Aplicar\" traslada los puntos levantados con cada base "
            "por la diferencia entre su coordenada libre y la corregida.\n\n"
            "\"3. Formato y Finalización\":\n"
            "- Formato + \"Exportar...\": exporta la previsualización (filtrada o "
            "completa) en el formato elegido, sin subir nada a la base de datos.\n"
            "- Interruptor \"Crear capa de puntos en QGIS\": crea (o no) la capa al "
            "subir.\n"
            "- \"Duplicados\": compara los nombres contra los que ya existen en "
            "POSTPLOT y resalta en rojo los que coinciden (sólo un aviso).\n"
            "- \"▸ Mostrar registro\"/\"▾ Ocultar registro\": despliega/oculta el "
            "detalle de lo procesado -- sigue recibiendo texto esté visible o no.\n"
            "- \"Subir\" (botón verde grande): sube a POSTPLOT los puntos con "
            "\"Incluir\" marcado."
        ),
        "en": (
            "Tab guide (v2.63.0 redesign), by section:\n\n"
            "\"1. Source file\":\n"
            "- \"+\" (top corner): adds one or more files -- pick the brand from "
            "the menu (Trimble .dc/.dsc, Hi-Target CSV/.raw, CHCNav .rw5, SurPad, "
            "Stonex .PD, SourceLink, Inova).\n"
            "- \"-\": removes the selected file(s) from the list (also clears the "
            "preview/map layer/base correction if they depended on it).\n"
            "- \"Preview\": processes every loaded file, shows the editable table "
            "below, and compares it against PREPLOT right away.\n\n"
            "\"2. Advanced filtering\":\n"
            "- \"Default filter\" + \"Save...\": pick a factory or your own filter, "
            "or save the current one under a name.\n"
            "- Wizard (Column | Condition | Value | Join with) and \"+\": adds the "
            "built condition to the current filter, no SQL needed.\n"
            "- \"▸ Developer mode (SQL)\": shows the box with the raw SQL "
            "condition (hidden by default), to edit it by hand.\n"
            "- Toolbar: \"Filter\" (runs the condition and highlights rows), "
            "\"Clear\", \"Map\" (only the filtered points in a separate layer), "
            "\"Check\"/\"Uncheck\" (checks/unchecks \"Include\" on the points "
            "matching the filter).\n\n"
            "Collapsible blocks (closed by default; the header summarizes their "
            "state, one click opens them):\n"
            "- \"PREPLOT\": tolerance (5 m by default), approximate name matching "
            "(unchecked by default) and \"Refresh\" to compare again without "
            "re-reading the files.\n"
            "- \"Bulk edit\": \"Apply\" writes the chosen value (Antenna height "
            "or Descriptor) to every included point not yet uploaded.\n"
            "- \"RTK base correction\" (only shown if a base was detected): "
            "\"Apply\" shifts the points surveyed with each base by the difference "
            "between its free coordinate and the corrected one.\n\n"
            "\"3. Format and finish\":\n"
            "- Format + \"Export...\": exports the preview (filtered or complete) "
            "in the chosen format, without uploading anything to the database.\n"
            "- \"Create a points layer in QGIS\" switch: creates (or not) the "
            "layer on upload.\n"
            "- \"Duplicates\": compares the names against the ones already in "
            "POSTPLOT and highlights matches in red (just a warning).\n"
            "- \"▸ Show log\"/\"▾ Hide log\": shows/hides the processing detail -- "
            "it keeps receiving text whether it's visible or not.\n"
            "- \"Upload\" (big green button): uploads the points with \"Include\" "
            "checked to POSTPLOT."
        ),
    },
    "note_check_db_duplicates": {
        "es": (
            "Compara cada punto de la previsualización (que todavía no se subió "
            "en esta sesión) contra los nombres (Station_Text) que ya existen en "
            "la tabla POSTPLOT del proyecto, sin importar mayúsculas/minúsculas. "
            "Los que ya existen se resaltan en rojo -- la fila completa, no sólo "
            "una celda -- y se desmarca su casilla \"Incluir\" para que no se "
            "suban de nuevo por accidente al presionar \"Subir seleccionados a la "
            "base de datos\". Es un aviso, no un bloqueo: la casilla sigue "
            "editable, así que si de verdad se quiere volver a subir un punto con "
            "ese nombre (por ejemplo, una reocupación intencional), se puede "
            "volver a marcar a mano. Si se edita el nombre de un punto después de "
            "verificar, hay que volver a presionar este botón para actualizar el "
            "resultado."
        ),
        "en": (
            "Compares each point in the preview (that hasn't been uploaded yet in "
            "this session) against the names (Station_Text) that already exist in "
            "the project's POSTPLOT table, case-insensitively. Matches are "
            "highlighted in red -- the whole row, not just one cell -- and their "
            "\"Include\" checkbox is unchecked so they don't get uploaded again by "
            "accident when pressing \"Upload selected points to database\". This "
            "is a warning, not a lock: the checkbox stays editable, so if a point "
            "with that name really should be uploaded again (an intentional "
            "reoccupation, say), it can be checked back by hand. If a point's name "
            "is edited after checking, press this button again to refresh the "
            "result."
        ),
    },
    "warn_duplicates_found_title": {
        "es": "Puntos duplicados encontrados",
        "en": "Duplicate points found",
    },
    "warn_duplicates_found_body": {
        "es": (
            "{n} punto(s) de la previsualización ya existen en la base de datos "
            "(POSTPLOT) con ese mismo nombre. Se resaltaron en rojo y se "
            "desmarcó su casilla \"Incluir\" para que no se suban de nuevo por "
            "accidente."
        ),
        "en": (
            "{n} preview point(s) already exist in the database (POSTPLOT) under "
            "that same name. They were highlighted in red and their \"Include\" "
            "checkbox was unchecked so they don't get uploaded again by accident."
        ),
    },
    "info_no_duplicates_title": {"es": "Sin duplicados", "en": "No duplicates"},
    "info_no_duplicates_body": {
        "es": "Ningún punto de la previsualización coincide por nombre con puntos ya existentes en POSTPLOT.",
        "en": "No preview point matches, by name, a point already in POSTPLOT.",
    },
    "btn_upload_dc": {"es": "Subir", "en": "Upload"},
    "btn_upload_retire_dc": {"es": "Subir/Retirar", "en": "Upload/Withdraw"},
    "tip_btn_upload_retire_dc": {
        "es": (
            "Ya subiste puntos a POSTPLOT. Al presionar puedes subir los puntos "
            "pendientes o RETIRAR de la base de datos los puntos de la última subida."
        ),
        "en": (
            "You already uploaded points to POSTPLOT. Click to upload the pending "
            "points or WITHDRAW the last upload's points from the database."
        ),
    },
    "dlg_upload_retire_title": {"es": "Subir / Retirar", "en": "Upload / Withdraw"},
    "dlg_upload_retire_body": {
        "es": "La última subida insertó {n} punto(s) en POSTPLOT. ¿Qué quieres hacer?",
        "en": "The last upload inserted {n} point(s) into POSTPLOT. What do you want to do?",
    },
    "btn_dialog_upload_pending": {"es": "Subir pendientes", "en": "Upload pending"},
    "btn_dialog_retire_last": {
        "es": "Retirar los {n} punto(s) de la última subida",
        "en": "Withdraw the last upload's {n} point(s)",
    },
    "confirm_retire_upload_title": {"es": "Retirar última subida", "en": "Withdraw last upload"},
    "confirm_retire_upload_body": {
        "es": (
            "Se borrarán de POSTPLOT los {n} punto(s) de la última subida. "
            "Los puntos volverán a la previsualización como pendientes. ¿Continuar?"
        ),
        "en": (
            "The {n} point(s) of the last upload will be deleted from POSTPLOT. "
            "They will return to the preview as pending. Continue?"
        ),
    },
    "warn_retire_upload_title": {"es": "No se pudo retirar", "en": "Could not withdraw"},
    "warn_retire_upload_error": {
        "es": "No se pudieron borrar los puntos de la base de datos: {error}",
        "en": "The points could not be deleted from the database: {error}",
    },
    "info_retire_upload_title": {"es": "Subida retirada", "en": "Upload withdrawn"},
    "info_retire_upload_body": {
        "es": "Se retiraron {n} punto(s) de POSTPLOT.",
        "en": "{n} point(s) were withdrawn from POSTPLOT.",
    },
    "log_retire_upload_ok": {
        "es": "Subida retirada: {n} punto(s) borrado(s) de POSTPLOT.",
        "en": "Upload withdrawn: {n} point(s) deleted from POSTPLOT.",
    },
    "msg_import_done_retire_hint": {
        "es": "Si fue un error, usa el botón \"Subir/Retirar\" para retirar estos puntos de la base de datos.",
        "en": "If this was a mistake, use the \"Upload/Withdraw\" button to withdraw these points from the database.",
    },
    "warn_upload_duplicates_title": {"es": "Puntos ya existentes en la base de datos", "en": "Points already in the database"},
    "warn_upload_duplicates_body": {
        "es": (
            "{n} punto(s) que vas a subir ya existen en POSTPLOT por nombre (ej: {ejemplos}).\n\n"
            "Si continúas quedarán duplicados. ¿Estás seguro de continuar?\n\n"
            "(Si te equivocas, podrás retirarlos con el botón \"Subir/Retirar\".)"
        ),
        "en": (
            "{n} point(s) you are about to upload already exist in POSTPLOT by name (e.g. {ejemplos}).\n\n"
            "If you continue they will be duplicated. Are you sure you want to continue?\n\n"
            "(If you make a mistake, you can withdraw them with the \"Upload/Withdraw\" button.)"
        ),
    },
    "tip_btn_upload_dc": {
        "es": "Sube a POSTPLOT todos los puntos con \"Incluir\" marcado, con el nombre/altura de antena/descriptor/comentario que hayas editado en la tabla.",
        "en": "Uploads every point with \"Include\" checked to POSTPLOT, using the name/antenna height/descriptor/comment you edited in the table.",
    },
    "info_nothing_to_upload_title": {"es": "Nada para subir", "en": "Nothing to upload"},
    "info_nothing_to_upload_body": {
        "es": (
            "No hay puntos incluidos para subir. Marca la casilla \"Incluir\" "
            "en al menos un punto de la previsualización, o genera la "
            "previsualización primero."
        ),
        "en": (
            "There are no included points to upload. Check \"Include\" on at "
            "least one previewed point, or generate the preview first."
        ),
    },
    "lbl_log": {"es": "Registro:", "en": "Log:"},
    "btn_log_show": {"es": "▸ Mostrar registro", "en": "▸ Show log"},
    "btn_log_hide": {"es": "▾ Ocultar registro", "en": "▾ Hide log"},
    # -- Rediseño de "Importar datos de campo" (v2.63.0) --
    "grp_origen_card": {"es": "1. Archivo de Origen", "en": "1. Source file"},
    "grp_filtrado_card": {"es": "2. Filtrado Avanzado", "en": "2. Advanced filtering"},
    "grp_finalizar_card": {"es": "3. Formato y Finalización", "en": "3. Format and finish"},
    "ph_filtro_wizard_valor_lbl": {"es": "Valor:", "en": "Value:"},
    "lbl_filtro_actual": {"es": "Condición actual: {c}", "en": "Current condition: {c}"},
    "btn_sql_dev_show": {"es": "▸ Modo Desarrollador (SQL)", "en": "▸ Developer mode (SQL)"},
    "btn_sql_dev_hide": {"es": "▾ Modo Desarrollador (SQL)", "en": "▾ Developer mode (SQL)"},
    "tip_btn_sql_dev": {
        "es": "Muestra u oculta el cuadro con la condición SQL cruda del filtro -- para usuarios avanzados que quieran escribirla o ajustarla a mano.",
        "en": "Shows or hides the box with the filter's raw SQL condition -- for advanced users who want to write or tweak it by hand.",
    },
    "tb_filter": {"es": "▶ Filtrar", "en": "▶ Filter"},
    "tb_clear": {"es": "✕ Limpiar", "en": "✕ Clear"},
    "tb_map": {"es": "◎ Mapa", "en": "◎ Map"},
    "tb_mark": {"es": "☑ Marcar", "en": "☑ Check"},
    "tb_unmark": {"es": "☐ Desmarcar", "en": "☐ Uncheck"},
    "acc_preplot_title": {"es": "PREPLOT", "en": "PREPLOT"},
    "acc_preplot_summary": {
        "es": "Tolerancia {tol} m · Nombre aproximado: {aprox} ({estado})",
        "en": "Tolerance {tol} m · Approximate name: {aprox} ({estado})",
    },
    "acc_bulk_title": {"es": "Editar en bloque", "en": "Bulk edit"},
    "acc_state_active": {"es": "Activo", "en": "Active"},
    "acc_state_no_preplot": {"es": "Sin PREPLOT", "en": "No PREPLOT"},
    "acc_state_waiting": {"es": "En espera", "en": "Waiting"},
    "acc_yes": {"es": "Sí", "en": "Yes"},
    "acc_no": {"es": "No", "en": "No"},
    "acc_empty": {"es": "(vacío)", "en": "(empty)"},
    "acc_none": {"es": "(ninguna)", "en": "(none)"},
    "dlg_add_dc_title": {"es": "Seleccionar archivos .dc/.dsc", "en": "Select .dc/.dsc files"},
    "filter_dc": {
        "es": "Trimble (*.dc *.dsc);;Archivos DC (*.dc);;Archivos DSC (*.dsc);;Todos (*.*)",
        "en": "Trimble (*.dc *.dsc);;DC files (*.dc);;DSC files (*.dsc);;All files (*.*)",
    },
    "dlg_add_hitarget_title": {"es": "Seleccionar CSV o .raw de Hi-Target", "en": "Select Hi-Target CSV or .raw files"},
    "filter_hitarget_csv": {
        "es": "Hi-Target (*.csv *.raw);;Archivos CSV (*.csv);;Archivos RAW (*.raw);;Todos (*.*)",
        "en": "Hi-Target (*.csv *.raw);;CSV files (*.csv);;RAW files (*.raw);;All files (*.*)",
    },
    "dlg_add_chcnav_title": {"es": "Seleccionar archivos .rw5 de CHCNav", "en": "Select CHCNav .rw5 files"},
    "filter_chcnav_rw5": {"es": "Archivos RW5 (*.rw5);;Todos (*.*)", "en": "RW5 files (*.rw5);;All files (*.*)"},
    "dlg_add_stonex_title": {
        "es": "Seleccionar archivo .PD de Stonex",
        "en": "Select Stonex .PD file",
    },
    # Hasta la v2.27.0 se aceptaba cualquier extensión a propósito (el
    # archivo de Stonex es una base SQLite y el usuario podía haberle
    # cambiado la extensión). Desde la v2.28.0, a pedido explícito del
    # usuario, el filtro y `agregar_stonex()` sólo reconocen archivos
    # con extensión ".PD" -- ver el chequeo adicional en
    # `agregar_stonex()` (el filtro del diálogo por sí solo no alcanza
    # en todos los sistemas operativos, porque algunos permiten escribir
    # un nombre de archivo a mano sin pasar por él). El chequeo de
    # contenido (`stonex_parser.looks_like_stonex_db`) se mantiene
    # además, como segunda validación.
    "filter_stonex_db": {"es": "Archivos PD (*.pd)", "en": "PD files (*.pd)"},
    "dlg_add_surpad_title": {"es": "Seleccionar archivos .rw5 o .raw de SurPad", "en": "Select SurPad .rw5 or .raw files"},
    # SurPad exporta un .rw5 de la misma familia de formato que
    # LandStar/CHCNav -- se reutiliza el mismo filtro de extensión
    # (ver `agregar_surpad()`/chcnav_parser.py).
    "filter_surpad_rw5": {"es": "Archivos SurPad (*.rw5 *.raw);;Todos (*.*)", "en": "SurPad files (*.rw5 *.raw);;All files (*.*)"},
    "err_stonex_wrong_extension": {
        "es": "{name}: sólo se reconocen archivos con extensión .PD.",
        "en": "{name}: only files with a .PD extension are recognized.",
    },
    "err_stonex_not_recognized": {
        "es": "{name}: no se reconoce como una base de datos de Stonex (no tiene el esquema esperado).",
        "en": "{name}: not recognized as a Stonex database (schema not found).",
    },
    "warn_read_file_title": {"es": "Error al leer archivo", "en": "Error reading file"},
    "log_dc_summary": {
        "es": "{name}  —  {n} puntos (KI: {ki}, SO: {so})",
        "en": "{name}  —  {n} points (KI: {ki}, SO: {so})",
    },
    "log_hitarget_summary": {
        "es": "{name}  —  {n} puntos Hi-Target ({base} de base)",
        "en": "{name}  —  {n} Hi-Target points ({base} base)",
    },
    "log_hitarget_raw_no_ant_height": {
        "es": (
            "Nota: el .raw de Hi-Target no trae la altura de antena (ese "
            "dato sólo lo agrega el software al exportar a CSV) -- queda "
            "vacía en la previsualización. Complétala con \"Aplicar a "
            "todos\" si usaste la misma altura en toda la sesión, o "
            "celda por celda si no."
        ),
        "en": (
            "Note: Hi-Target's .raw doesn't include antenna height (only "
            "added by the software when exporting to CSV) -- it's left "
            "blank in the preview. Fill it in with \"Apply to all\" if "
            "you used the same height throughout the session, or "
            "cell-by-cell otherwise."
        ),
    },
    "log_chcnav_summary": {
        "es": "{name}  —  {n} puntos CHCNav ({con_calidad} con estadísticas de calidad, {base} de base)",
        "en": "{name}  —  {n} CHCNav points ({con_calidad} with quality stats, {base} base)",
    },
    "log_stonex_summary": {
        "es": "{name}  —  {n} puntos Stonex",
        "en": "{name}  —  {n} Stonex points",
    },
    "log_surpad_summary": {
        "es": "{name}  —  {n} puntos SurPad ({con_calidad} con estadísticas de calidad, {base} de base)",
        "en": "{name}  —  {n} SurPad points ({con_calidad} with quality stats, {base} base)",
    },
    "log_dc_warnings": {
        "es": "[{name}] {n} advertencia(s) al leer el archivo.",
        "en": "[{name}] {n} warning(s) while reading the file.",
    },
    "log_dc_base_detectada": {
        "es": "— base RTK física detectada: {base}.",
        "en": "— physical RTK base detected: {base}.",
    },
    "log_dc_bases_multiples": {
        "es": "— {n} bases RTK físicas distintas detectadas: cada punto se asocia a la que estaba vigente al levantarlo.",
        "en": "— {n} distinct physical RTK bases detected: each point is associated with whichever was active when it was surveyed.",
    },
    # -- Corrección de base RTK libre -> corregida (opcional, ver la nota
    # junto a `CORR_BASE_COL_ARCHIVO` en gnsseismic_windows.py): sección
    # que aparece en "Importar datos de campo" sólo cuando se detecta al
    # menos una ocupación de base entre los puntos de Hi-Target/CHCNav
    # cargados. No aplica a Trimble .dc por ahora.
    "grp_correccion_base_title": {
        "es": "Corrección de base RTK (opcional)",
        "en": "RTK base correction (optional)",
    },
    "note_correccion_base": {
        "es": (
            "Se detectó al menos una ocupación de base en los archivos "
            "cargados (Hi-Target o CHCNav). Si el levantamiento se hizo "
            "con una base propia con coordenadas libres/sin corregir (no "
            "es necesario si se usó RTX de Trimble o HAS de Galileo, que "
            "ya entregan coordenadas corregidas), escribe aquí la "
            "coordenada de esa base ya corregida por post-proceso de una "
            "sesión estática (a mano o cargándola de un archivo), y "
            "\"Aplicar correcciones\" trasladará por igual (misma "
            "distancia y dirección) todos los puntos levantados con esa "
            "base, antes de subir a la base de datos. Dejar la fila vacía "
            "no cambia nada; una base sin corrección se sube tal cual se "
            "levantó."
        ),
        "en": (
            "At least one base occupation was found in the loaded files "
            "(Hi-Target or CHCNav). If the survey used your own base "
            "station with a free/uncorrected coordinate (not needed if "
            "you used Trimble RTX or Galileo HAS, which already deliver "
            "corrected coordinates), enter that base's coordinate here "
            "once corrected via a static session's post-processing "
            "(manually or loaded from a file), and \"Apply corrections\" "
            "will shift every point surveyed from that base by the same "
            "amount and direction, before uploading to the database. "
            "Leaving a row blank changes nothing; an uncorrected base is "
            "uploaded as surveyed."
        ),
    },
    "col_base_name": {"es": "Base", "en": "Base"},
    "col_lat_libre": {"es": "Lat. libre", "en": "Free lat."},
    "col_lon_libre": {"es": "Lon. libre", "en": "Free lon."},
    "col_alt_libre": {"es": "Alt. libre (m)", "en": "Free height (m)"},
    "col_lat_corregida": {"es": "Lat. corregida", "en": "Corrected lat."},
    "col_lon_corregida": {"es": "Lon. corregida", "en": "Corrected lon."},
    "col_alt_corregida": {"es": "Alt. corregida (m)", "en": "Corrected height (m)"},
    "col_cargar": {"es": "Cargar", "en": "Load"},
    "btn_cargar_correccion_base": {"es": "Cargar desde archivo...", "en": "Load from file..."},
    "btn_aplicar_correccion_base": {"es": "Aplicar", "en": "Apply"},
    "tip_btn_aplicar_correccion_base": {
        "es": "Traslada (misma distancia y dirección) todos los puntos levantados con cada base por la diferencia entre su coordenada libre y la corregida que escribiste arriba.",
        "en": "Shifts (same distance and direction) every point surveyed with each base by the difference between its free coordinate and the corrected one you entered above.",
    },
    "status_correccion_pendiente": {"es": "Sin corregir", "en": "Uncorrected"},
    "status_correccion_aplicada": {"es": "Corrección aplicada", "en": "Correction applied"},
    "dlg_cargar_correccion_title": {
        "es": "Seleccionar archivo con la coordenada corregida",
        "en": "Select file with the corrected coordinate",
    },
    "filter_correccion_csv": {
        "es": "CSV / texto (*.csv *.txt);;Todos (*.*)",
        "en": "CSV / text (*.csv *.txt);;All files (*.*)",
    },
    "err_correccion_archivo_vacio": {
        "es": "El archivo está vacío.",
        "en": "The file is empty.",
    },
    "err_correccion_archivo_sin_datos": {
        "es": (
            "No se encontró ninguna fila con una coordenada válida. Se "
            "espera \"Lat,Lon[,Altura]\" o \"Nombre,Lat,Lon[,Altura]\" "
            "(un valor por línea, coma o punto decimal)."
        ),
        "en": (
            "No row with a valid coordinate was found. Expected "
            "\"Lat,Lon[,Height]\" or \"Name,Lat,Lon[,Height]\" (one value "
            "per line, comma or dot decimal separator)."
        ),
    },
    "err_correccion_archivo_sin_match": {
        "es": (
            "El archivo trae varias coordenadas, pero ninguna con el "
            "nombre \"{nombre}\" de esta base."
        ),
        "en": (
            "The file has several coordinates, but none named \"{nombre}\" "
            "matching this base."
        ),
    },
    "warn_correccion_incompleta_title": {"es": "Coordenada incompleta", "en": "Incomplete coordinate"},
    "warn_correccion_incompleta_body": {
        "es": (
            "En \"{archivo}\" hay que llenar tanto la latitud como la "
            "longitud corregidas (o dejar ambas vacías para no corregir "
            "esa base)."
        ),
        "en": (
            "In \"{archivo}\" you must fill in both the corrected "
            "latitude and longitude (or leave both blank to not correct "
            "that base)."
        ),
    },
    "warn_correccion_invalida_title": {"es": "Coordenada inválida", "en": "Invalid coordinate"},
    "warn_correccion_invalida_body": {
        "es": (
            "La coordenada corregida de \"{archivo}\" no es un número "
            "válido, o la latitud/longitud está fuera de rango."
        ),
        "en": (
            "The corrected coordinate for \"{archivo}\" isn't a valid "
            "number, or the latitude/longitude is out of range."
        ),
    },
    "warn_correccion_salto_grande_title": {
        "es": "Corrección con un salto grande",
        "en": "Correction has a large shift",
    },
    "warn_correccion_salto_grande_body": {
        "es": (
            "La coordenada corregida queda a más de {umbral} de la libre "
            "en:\n{detalle}\n\n"
            "Una corrección de base real suele ser de centímetros a pocos "
            "metros -- un salto así de grande puede ser un error de "
            "digitación (coordenada equivocada, signo invertido, etc.). "
            "¿Aplicar de todas formas?"
        ),
        "en": (
            "The corrected coordinate is more than {umbral} away from the "
            "free one in:\n{detalle}\n\n"
            "A real base correction is usually centimeters to a few "
            "meters -- a shift this large may be a data-entry mistake "
            "(wrong coordinate, flipped sign, etc.). Apply anyway?"
        ),
    },
    "log_correccion_base_aplicada": {
        "es": "Corrección de base RTK aplicada a {n} ocupación(es) de base.",
        "en": "RTK base correction applied to {n} base occupation(s).",
    },
    "log_correccion_base_quitada": {
        "es": "Corrección de base RTK quitada de {n} ocupación(es) de base (vuelven a su coordenada libre).",
        "en": "RTK base correction removed from {n} base occupation(s) (back to their free coordinate).",
    },
    # -- Columnas agregadas en la v2.25.0 a la previsualización de
    # "Importar datos de campo" (coordenadas planas, geográficas en GMS,
    # elevación ortométrica y calidad) y a la tabla de "Corrección de
    # base RTK" (coordenadas planas de la base libre y corregida) -- ver
    # `_llenar_tabla_preview`/`_actualizar_seccion_correccion_base` en
    # gnsseismic_windows.py.
    "col_lat_dms": {"es": "Latitud (GMS)", "en": "Latitude (DMS)"},
    "col_lon_dms": {"es": "Longitud (GMS)", "en": "Longitude (DMS)"},
    "col_ortometrica": {"es": "Elev. ortométrica (m)", "en": "Orthometric elev. (m)"},
    "col_calidad": {"es": "Calidad", "en": "Quality"},
    "col_este_libre": {"es": "Este libre", "en": "Free easting"},
    "col_norte_libre": {"es": "Norte libre", "en": "Free northing"},
    "col_este_corregida": {"es": "Este corregida", "en": "Corrected easting"},
    "col_norte_corregida": {"es": "Norte corregida", "en": "Corrected northing"},
    # Textos de la columna "Calidad": Hi-Target CSV sí trae el estado
    # real de la solución (columna Estado: "RTK Fijo"/"Fix"/"Flotante"/
    # "Cálculo") y se traduce a estas etiquetas; CHCNav sólo confirma el
    # valor "FIXED" en el archivo real de referencia usado para construir
    # este plugin (nunca se vio un valor float/autónomo real con el que
    # verificar una traducción), así que para CHCNav se muestra el
    # STATUS tal cual viene del archivo, sin pasar por estas claves;
    # Trimble .dc y el .raw de Hi-Target no traen ningún dato de calidad
    # de la solución, así que sus puntos se muestran como "Autónomo" por
    # defecto (decisión del usuario, no un dato confirmado del archivo).
    "calidad_fijo": {"es": "Fijo", "en": "Fixed"},
    "calidad_flotante": {"es": "Flotante", "en": "Float"},
    "calidad_calculo": {"es": "Cálculo", "en": "Calculated"},
    "calidad_autonomo": {"es": "Autónomo", "en": "Autonomous"},
    "calidad_otro": {"es": "Otro", "en": "Other"},
    "calidad_nd": {"es": "N/D", "en": "N/A"},
    # Aviso (QMessageBox) que informa, cada vez que se genera la
    # previsualización desde el botón (no en re-previsualizaciones
    # internas como la de "Aplicar correcciones"), que los puntos se
    # proyectaron al CRS de trabajo del proyecto y si se les aplicó el
    # geoide -- ver `previsualizar_dc(mostrar_aviso=...)`.
    "dlg_aviso_transform_title": {
        "es": "Transformación aplicada",
        "en": "Transformation applied",
    },
    "dlg_aviso_transform_body_con_geoid": {
        "es": (
            "Los {n} punto(s) importados se proyectaron al sistema de "
            "coordenadas de trabajo del proyecto ({crs}) para calcular "
            "sus coordenadas planas (Este/Norte), y se les aplicó el "
            "geoide del proyecto ({geoid}) para calcular la elevación "
            "ortométrica a partir de la altura elipsoidal."
        ),
        "en": (
            "The {n} imported point(s) were projected to the project's "
            "working coordinate system ({crs}) to compute their plane "
            "coordinates (Easting/Northing), and the project's geoid "
            "({geoid}) was applied to compute the orthometric elevation "
            "from the ellipsoidal height."
        ),
    },
    "dlg_aviso_transform_body_sin_geoid": {
        "es": (
            "Los {n} punto(s) importados se proyectaron al sistema de "
            "coordenadas de trabajo del proyecto ({crs}) para calcular "
            "sus coordenadas planas (Este/Norte). El proyecto no tiene "
            "un geoide configurado, así que la elevación ortométrica no "
            "está disponible (sólo la altura elipsoidal)."
        ),
        "en": (
            "The {n} imported point(s) were projected to the project's "
            "working coordinate system ({crs}) to compute their plane "
            "coordinates (Easting/Northing). The project has no geoid "
            "configured, so the orthometric elevation isn't available "
            "(only the ellipsoidal height)."
        ),
    },
    "info_nothing_to_import_title": {"es": "Nada que importar", "en": "Nothing to import"},
    "info_nothing_to_import_body": {
        "es": "Agrega al menos un archivo .dc o CSV de Hi-Target.",
        "en": "Add at least one .dc or Hi-Target CSV file.",
    },
    "log_import_ok": {
        "es": "[{name}] {n} puntos insertados en POSTPLOT (job: {job}, instrumento: {instr}).",
        "en": "[{name}] {n} points inserted into POSTPLOT (job: {job}, instrument: {instr}).",
    },
    "log_import_warning": {"es": "    ADVERTENCIA: {warn}", "en": "    WARNING: {warn}"},
    "log_import_error": {
        "es": "[{name}] ERROR al insertar: {error}",
        "en": "[{name}] ERROR while inserting: {error}",
    },
    "msg_import_done_title": {"es": "Importación finalizada", "en": "Import finished"},
    "msg_import_done_body": {
        "es": "{n} puntos importados a POSTPLOT.",
        "en": "{n} points imported into POSTPLOT.",
    },
    "layer_dc_points": {"es": "Puntos levantados", "en": "Surveyed points"},
    "log_preview_discarded_no_field_data": {
        "es": "Se descartaron {n} de {total} puntos sin datos de campo (sin satélites/PDOP) -- no se muestran en la previsualización.",
        "en": "Discarded {n} of {total} points with no field data (no satellites/PDOP) -- not shown in the preview.",
    },
    "log_receptor_sin_offset_arp": {
        "es": "Aviso: {archivo} usa un receptor '{receptor}' que todavía no tiene un offset de antena (ARP) confirmado -- la \"Altura de antena\" y la elevación de este archivo se muestran SIN corregir ese offset. Si conocés la altura de antena real (por ejemplo, de GPSeismic) para comparar, reportala para agregar este modelo a la tabla.",
        "en": "Warning: {archivo} uses a '{receptor}' receiver that doesn't have a confirmed antenna (ARP) offset yet -- this file's \"Antenna height\" and elevation are shown WITHOUT that offset correction. If you know the real antenna height (e.g. from GPSeismic) to compare, report it so this model can be added to the table.",
    },
    "layer_preview_provisional": {
        "es": "Vista previa de campo (sin subir)",
        "en": "Field data preview (not uploaded)",
    },
    # Pedido explícito del usuario: cuando TODOS los puntos de la
    # previsualización vienen de un único archivo cargado, la capa
    # temporal del mapa debe mostrar el nombre de ese archivo en vez del
    # título genérico de arriba (que no decía nada de cuál archivo era) --
    # ver `_actualizar_capa_provisional_preview`. Cuando hay más de un
    # archivo cargado a la vez, se mantiene el título genérico (no hay un
    # único nombre de archivo que mostrar).
    "layer_preview_provisional_archivo": {
        "es": "{archivo} (vista previa, sin subir)",
        "en": "{archivo} (preview, not uploaded)",
    },
    "layer_preplot_match_preview": {
        "es": "Preplot coincidente (vista previa)",
        "en": "Matching preplot (preview)",
    },
    "layer_desplazamiento_preview": {
        "es": "Desplazamiento preplot -> campo (vista previa)",
        "en": "Preplot -> field displacement (preview)",
    },
    "legend_desplazamiento_dentro": {"es": "Dentro de tolerancia", "en": "Within tolerance"},
    "legend_desplazamiento_fuera": {"es": "Fuera de tolerancia", "en": "Outside tolerance"},
    "note_desplazamiento_preview": {
        "es": (
            "Al previsualizar (o volver a comparar con PREPLOT), además de la "
            "capa con los puntos de campo, se agregan otras dos capas "
            "temporales al mapa: \"Preplot coincidente (vista previa)\" (un "
            "triángulo violeta por cada punto de PREPLOT cuyo nombre coincidió "
            "con uno de la previsualización) y \"Desplazamiento preplot -> "
            "campo (vista previa)\" (una línea entre ese punto de PREPLOT y el "
            "punto levantado en campo, verde si quedó dentro de tolerancia y "
            "roja si quedó fuera) -- así se ve de un vistazo, en el mapa, hacia "
            "dónde y cuánto se corrió cada punto respecto a su diseño, sin "
            "necesidad de subirlo ni de exportar la comparación. Ambas capas se "
            "reemplazan por completo cada vez (nunca se acumulan capas viejas) "
            "y sólo incluyen los puntos que sí matchearon por nombre contra "
            "PREPLOT."
        ),
        "en": (
            "When previewing (or re-comparing against PREPLOT), besides the "
            "field-points layer, two more temporary layers are added to the "
            "map: \"Matching preplot (preview)\" (a purple triangle for each "
            "PREPLOT point whose name matched one in the preview) and "
            "\"Preplot -> field displacement (preview)\" (a line between that "
            "PREPLOT point and the field-surveyed point, green if within "
            "tolerance and red if outside) -- so it's clear at a glance, on "
            "the map, where and how far each point moved from its design "
            "location, without uploading it or exporting the comparison. Both "
            "layers are fully replaced every time (old layers never pile up) "
            "and only include points that actually matched PREPLOT by name."
        ),
    },
    "layer_preplot_ext_provisional": {
        "es": "Preplot importado (vista previa)",
        "en": "Imported preplot (preview)",
    },
    "legend_ki": {"es": "KI (receptor/estaca)", "en": "KI (receiver/stake)"},
    "legend_so": {"es": "SO (fuente)", "en": "SO (source)"},
    "legend_fix": {"es": "Hi-Target: RTK Fijo", "en": "Hi-Target: RTK Fix"},
    "legend_float": {"es": "Hi-Target: RTK Flotante", "en": "Hi-Target: RTK Float"},
    "legend_calc": {"es": "Hi-Target: Cálculo", "en": "Hi-Target: Calculated"},
    # SIN nombre de marca por delante (corregido en esta ronda, a pedido
    # explícito del usuario al ver "Hi-Target: Base" en la previsualización
    # de un archivo de CHCNav/SurPad): a diferencia de FIX/FLOAT/CALC
    # (exclusivos de Hi-Target, derivados de su "Estado" -- ver
    # `_hitarget_tipo_code`), el tipo "BASE" lo producen TODAS las marcas
    # con ocupación de base RTK -- Hi-Target, DC (`dc_parser.py`), CHCNav/
    # SurPad (registro 'BP' o sufijo "--BASE", ver `chcnav_parser.py`) y
    # Stonex -- así que "Hi-Target: Base" era directamente incorrecto para
    # las otras cuatro. Mismo criterio ya aplicado a LD/CT/CHKAM/CHKPM en
    # la v2.26.0 (ver la nota junto a `COLOR_POR_TIPO` en
    # gnsseismic_windows.py): sin confirmar que el significado sea
    # idéntico entre marcas, la etiqueta queda neutral.
    "legend_base": {"es": "Base", "en": "Base"},
    # Códigos de sufijo/clasificación de punto tal cual los trae el
    # archivo de origen (.rw5 de CHCNav -- ver chcnav_parser.py -- o la
    # base de Stonex -- ver stonex_parser.py) -- NO se traduce/adivina su
    # significado exacto (p.ej. qué distingue CHKAM de CHKPM), sólo se
    # etiquetan con el código original para que el usuario lo reconozca
    # en la leyenda. SIN nombre de marca por delante a propósito desde la
    # v2.26.0 (antes decían "CHCNav: LD", etc.): al agregar Stonex, su
    # archivo real trajo el mismo código "LD" que ya usaba CHCNav -- como
    # el plugin no confirma si dos marcas distintas le dan el mismo
    # significado a un código de 2-4 letras, la leyenda de estos códigos
    # queda siempre neutral (ver la nota junto a `COLOR_POR_TIPO` en
    # gnsseismic_windows.py).
    "legend_ld": {"es": "LD", "en": "LD"},
    "legend_ct": {"es": "CT", "en": "CT"},
    "legend_chkam": {"es": "CHKAM", "en": "CHKAM"},
    "legend_chkpm": {"es": "CHKPM", "en": "CHKPM"},
    "legend_chk": {"es": "CHK", "en": "CHK"},
    "legend_other": {"es": "Otro", "en": "Other"},

    # -- Sección: Comparar ---------------------------------------------------
    "grp_source": {"es": "1. Fuente de los puntos de diseño", "en": "1. Design points source"},
    "rb_source_preplot": {
        "es": "Tabla PREPLOT de la base de datos del proyecto",
        "en": "Project database's PREPLOT table",
    },
    "grp_csv_data": {"es": "Archivo CSV de diseño / preplot", "en": "Design / preplot CSV file"},
    "btn_load_csv": {"es": "Cargar CSV...", "en": "Load CSV..."},
    "lbl_col_name": {"es": "Columna de Nombre/Código:", "en": "Name/Code column:"},
    "lbl_col_x": {"es": "Columna X / Este / Longitud:", "en": "X / Easting / Longitude column:"},
    "lbl_col_y": {"es": "Columna Y / Norte / Latitud:", "en": "Y / Northing / Latitude column:"},
    "lbl_col_z": {"es": "Columna Z / Cota (opcional):", "en": "Z / Elevation column (optional):"},
    "grp_csv_coord_type": {"es": "Tipo de coordenadas del CSV", "en": "CSV coordinate type"},
    "rb_geographic": {
        "es": "Geográficas (Longitud, Latitud en grados)",
        "en": "Geographic (Longitude, Latitude in degrees)",
    },
    "rb_planar": {"es": "Planas (Este, Norte) en el CRS de abajo", "en": "Planar (Easting, Northing) in the CRS below"},
    "lbl_csv_crs": {
        "es": "CRS del CSV (si es de coordenadas planas):",
        "en": "CSV's CRS (if using planar coordinates):",
    },
    "grp_compare": {"es": "2. Comparación", "en": "2. Comparison"},
    "lbl_compare_against": {"es": "Comparar contra tabla:", "en": "Compare against table:"},
    "lbl_tolerance": {"es": "Tolerancia (m):", "en": "Tolerance (m):"},
    "chk_approx_match": {
        "es": "Permitir emparejamiento aproximado de nombres",
        "en": "Allow approximate name matching",
    },
    "tip_approx_match": {
        "es": (
            "Si un nombre no calza exactamente (p.ej. '1025-5092' vs "
            "'10255092'), intenta emparejar quitando guiones/espacios y "
            "ceros a la izquierda."
        ),
        "en": (
            "If a name doesn't match exactly (e.g. '1025-5092' vs '10255092'), "
            "tries matching again after stripping dashes/spaces and leading zeros."
        ),
    },
    "btn_compare": {"es": "Comparar", "en": "Compare"},
    "col_delta_x": {"es": "ΔEste (m)", "en": "ΔEasting (m)"},
    "col_delta_y": {"es": "ΔNorte (m)", "en": "ΔNorthing (m)"},
    "col_dist_2d": {"es": "Dist. 2D (m)", "en": "2D Dist. (m)"},
    "btn_create_compare_layer": {
        "es": "Crear capa de comparación en QGIS",
        "en": "Create comparison layer in QGIS",
    },
    "btn_export_compare_csv": {"es": "Exportar comparación a CSV...", "en": "Export comparison to CSV..."},
    "grp_upload": {"es": "3. Subir a la base de datos del proyecto", "en": "3. Upload to the project database"},
    "chk_upload_preplot": {
        "es": "Subir también los puntos del CSV a la tabla PREPLOT",
        "en": "Also upload the CSV points to the PREPLOT table",
    },
    "btn_upload_db": {"es": "Guardar comparación en la base de datos", "en": "Save comparison to the database"},
    "msg_export_ok_title": {"es": "Exportado", "en": "Exported"},

    # -- Sección: Base de Datos ----------------------------------------------
    "bd_intro": {
        "es": (
            "Arma una consulta (sólo SELECT) sobre la base del proyecto y exporta "
            "el resultado. Útil para filtrar qué puntos van a cada archivo "
            "(por ejemplo, sólo los receptores de una línea, o los puntos fuera "
            "de tolerancia de la comparación). Los filtros se arman con el asistente "
            "(columna, condición y valor); el SQL queda en \"Modo Desarrollador\". Junto a Buscar y "
            "reemplazar, la fila \"Comparar dos consultas SQL\" compara dos consultas entre sí."
        ),
        "en": (
            "Build a query (SELECT only) against the project database and export "
            "the result. Useful for filtering which points go into each file "
            "(e.g. only the receivers of one line, or the points outside the "
            "comparison's tolerance). Filters are built with the assistant "
            "(column, condition and value); the SQL stays under \"Developer mode\". Next to Find and "
            "replace, the \"Compare two SQL queries\" row compares two queries against each other."
        ),
    },
    "lbl_query_preset": {"es": "Consulta de ejemplo:", "en": "Example query:"},
    "preset_custom": {"es": "Personalizada", "en": "Custom"},
    "preset_postplot_all": {"es": "POSTPLOT (todos)", "en": "POSTPLOT (all)"},
    "preset_preplot_all": {"es": "PREPLOT (todos)", "en": "PREPLOT (all)"},
    "preset_postplot_by_type": {
        "es": "POSTPLOT por tipo (Descriptor)",
        "en": "POSTPLOT by type (Descriptor)",
    },
    "preset_postplot_by_track": {
        "es": "POSTPLOT por Track",
        "en": "POSTPLOT by Track",
    },
    "preset_postplot_by_station_value": {
        "es": "POSTPLOT por valor de estación (Station_Value)",
        "en": "POSTPLOT by station value (Station_Value)",
    },
    "preset_postplot_by_julian_date_local": {
        "es": "POSTPLOT por fecha juliana (Julian_Date_Local)",
        "en": "POSTPLOT by Julian date (Julian_Date_Local)",
    },
    "preset_comparacion_fuera_tol": {
        "es": "COMPARACION fuera de tolerancia",
        "en": "COMPARISON outside tolerance",
    },
    "btn_run_query": {"es": "Ejecutar", "en": "Run"},
    "btn_save_query": {"es": "Guardar", "en": "Save"},
    "dlg_save_query_title": {"es": "Guardar consulta", "en": "Save query"},
    "dlg_save_query_overwrite_body": {
        "es": (
            "La consulta actual del cuadro de texto es distinta a la que tenía "
            "guardada \"{nombre}\".\n\n¿Querés sobrescribir \"{nombre}\" con este "
            "SQL, o guardarlo como una consulta nueva y aparte?"
        ),
        "en": (
            "The current text box query is different from the one saved as "
            "\"{nombre}\".\n\nDo you want to overwrite \"{nombre}\" with this "
            "SQL, or save it as a separate, new query?"
        ),
    },
    "btn_save_query_overwrite": {"es": "Sobrescribir \"{nombre}\"", "en": "Overwrite \"{nombre}\""},
    "btn_save_query_as_new": {"es": "Guardar como nueva...", "en": "Save as new..."},
    "dlg_save_query_name_label": {
        "es": "Nombre para esta consulta:",
        "en": "Name for this query:",
    },
    "err_query_name_invalid": {
        "es": "El nombre de la consulta no puede quedar vacío.",
        "en": "The query name cannot be empty.",
    },
    "err_query_name_reserved": {
        "es": (
            "Ese nombre ya lo usa una consulta de ejemplo del plugin. "
            "Elegí otro nombre para tu consulta."
        ),
        "en": (
            "That name is already used by one of the plugin's example queries. "
            "Choose a different name for your query."
        ),
    },
    "confirm_query_overwrite_body": {
        "es": "Ya tenés una consulta guardada como \"{nombre}\".\n\n¿Querés sobrescribirla con el SQL actual?",
        "en": "You already have a query saved as \"{nombre}\".\n\nOverwrite it with the current SQL?",
    },
    "info_query_saved_body": {
        "es": "Consulta \"{nombre}\" guardada.",
        "en": "Query \"{nombre}\" saved.",
    },
    "btn_rename_query": {"es": "Renombrar...", "en": "Rename..."},
    "dlg_rename_query_title": {"es": "Renombrar consulta", "en": "Rename query"},
    "dlg_rename_query_label": {
        "es": "Nuevo nombre para esta consulta:",
        "en": "New name for this query:",
    },
    "info_rename_only_custom_body": {
        "es": (
            "Sólo se puede renombrar una consulta propia que hayas guardado con "
            "\"Guardar\". Las consultas de ejemplo del plugin tienen "
            "un nombre fijo (podés cambiar su SQL, pero no su nombre)."
        ),
        "en": (
            "Only a query you saved yourself with \"Save\" can be renamed. "
            "The plugin's example queries have a fixed name (you can change their "
            "SQL, but not their name)."
        ),
    },
    "err_query_name_taken": {
        "es": "Ya tenés otra consulta guardada con ese nombre. Elegí uno distinto.",
        "en": "You already have another saved query with that name. Choose a different one.",
    },
    "info_query_renamed_body": {
        "es": "Consulta renombrada de \"{antes}\" a \"{despues}\".",
        "en": "Query renamed from \"{antes}\" to \"{despues}\".",
    },
    # -- Importar/exportar consultas guardadas (pedido explícito del
    # usuario, con un archivo .qrylt real de GPSeismic como referencia --
    # ver `_parse_qrylt_text`/`importar_consultas_guardadas` en
    # gnsseismic_windows.py).
    "btn_import_queries": {"es": "Importar consultas...", "en": "Import queries..."},
    "btn_export_queries": {"es": "Exportar consultas...", "en": "Export queries..."},
    "dlg_import_queries_title": {"es": "Importar consultas guardadas", "en": "Import saved queries"},
    "dlg_export_queries_title": {"es": "Exportar consultas guardadas", "en": "Export saved queries"},
    "filter_query_files": {"es": "Archivos de consultas", "en": "Query files"},
    "err_import_queries_title": {"es": "Error al importar consultas", "en": "Query import error"},
    "err_import_queries_body": {
        "es": "No se pudo leer el archivo: {error}",
        "en": "Couldn't read the file: {error}",
    },
    "info_import_queries_empty_body": {
        "es": (
            "El archivo no tiene ninguna consulta con SQL para importar (en "
            "un .qrylt de GPSeismic, las casillas vacías no cuentan)."
        ),
        "en": (
            "The file has no query with SQL to import (in a GPSeismic .qrylt "
            "file, empty slots don't count)."
        ),
    },
    "msg_import_queries_done_body": {
        "es": (
            "Se importaron {n} consulta(s) desde:\n{path}\n\n"
            "{renombradas} de ellas se guardaron con un nombre distinto porque "
            "ya tenías una consulta propia (o un preset de fábrica) con ese "
            "mismo nombre -- ninguna consulta que ya tenías guardada se "
            "sobrescribió."
        ),
        "en": (
            "{n} quer(y/ies) imported from:\n{path}\n\n"
            "{renombradas} of them were saved under a different name because "
            "you already had a query of your own (or a factory preset) with "
            "that same name -- no query you already had saved was overwritten."
        ),
    },
    "warn_no_custom_queries_body": {
        "es": "Todavía no guardaste ninguna consulta propia con \"Guardar\".",
        "en": "You haven't saved any query of your own yet with \"Save\".",
    },
    "msg_export_queries_done_body": {
        "es": "Se exportaron {n} consulta(s) a:\n{path}",
        "en": "{n} quer(y/ies) exported to:\n{path}",
    },
    "note_import_export_queries": {
        "es": (
            "\"Importar consultas...\" trae consultas guardadas desde un "
            "archivo .qrylt (el formato nativo de consultas guardadas de "
            "GPSeismic -- si ya tenés una lista armada ahí, con esto no hace "
            "falta rearmarla a mano) o desde un .json exportado antes con "
            "\"Exportar consultas...\" (para llevar tus propias consultas "
            "guardadas de una máquina o perfil de QGIS a otro). En ambos "
            "casos se agregan al final de \"Consulta de ejemplo:\", junto a "
            "las que ya tenías -- si el archivo trae una consulta con el "
            "mismo nombre que una que ya guardaste, la que se importa se "
            "guarda con un nombre distinto (nunca se pisa una consulta que "
            "ya tenías). El SQL de un archivo .qrylt de GPSeismic se importa "
            "tal cual, sin traducirlo: en general funciona directo porque "
            "SQLite entiende esa misma sintaxis (corchetes y comillas "
            "invertidas para nombres, \"Like\", \"Between... And\"), pero una "
            "consulta que se refiera a una tabla que este plugin no tiene "
            "(por ejemplo \"VIBROS\", de otro módulo de GPSeismic) va a dar "
            "error recién al EJECUTARLA, no al importarla."
        ),
        "en": (
            "\"Import queries...\" brings in saved queries from a .qrylt "
            "file (GPSeismic's native saved-query format -- if you already "
            "have a list built there, this saves you from rebuilding it by "
            "hand) or from a .json file exported earlier with \"Export "
            "queries...\" (to carry your own saved queries from one machine "
            "or QGIS profile to another). Either way they're added to the "
            "end of \"Example query:\", alongside the ones you already had -- "
            "if the file has a query with the same name as one you already "
            "saved, the imported one is saved under a different name "
            "(a query you already had is never overwritten). A GPSeismic "
            ".qrylt file's SQL is imported as-is, with no translation: it "
            "generally works directly because SQLite understands that same "
            "syntax (brackets and backticks for names, \"Like\", \"Between... "
            "And\"), but a query referring to a table this plugin doesn't "
            "have (for example \"VIBROS\", from another GPSeismic module) "
            "will only error out when you RUN it, not when you import it."
        ),
    },
    # -- "Buscar / Buscar y reemplazar" (v2.53.0, pedido explícito del
    # usuario: poder buscar y reemplazar por CUALQUIER columna de
    # POSTPLOT/PREPLOT/COMPARACION sin escribir SQL a mano) --------------
    "grp_sql_query": {"es": "Consulta SQL", "en": "SQL query"},
    "grp_search_replace": {"es": "Buscar / Buscar y reemplazar", "en": "Find / Find and replace"},
    "lbl_search_replace_note": {
        "es": (
            "Elegí la tabla y la columna donde buscar, escribí el valor y apretá "
            "\"Buscar\" -- arma un SELECT equivalente y lo corre igual que una consulta "
            "manual (el resultado aparece en la tabla de abajo, con edición, borrado, "
            "mapeo de columnas y exportación ya disponibles). \"Coincidencia exacta\" "
            "busca el valor completo de la celda; sin marcar, busca cualquier celda que "
            "CONTENGA ese texto. \"Reemplazar\" escribe el valor de "
            "\"Reemplazar por\" en TODAS las filas que matcheen la búsqueda -- con "
            "coincidencia exacta reemplaza la celda completa; sin marcar, reemplaza sólo "
            "la parte encontrada dentro de cada celda, conservando el resto del texto "
            "(por ejemplo, para corregir una palabra repetida en varios comentarios sin "
            "tener que reescribirlos enteros). Pide confirmación antes de aplicar "
            "cualquier reemplazo, mostrando cuántas filas se van a modificar."
        ),
        "en": (
            "Choose the table and column to search, type the value and click \"Find\" "
            "-- it builds an equivalent SELECT and runs it just like a manual query (the "
            "result shows up in the table below, with editing, deletion, column mapping "
            "and export already available). \"Exact match\" searches for the full cell "
            "value; unchecked, it searches any cell that CONTAINS that text. \"Replace\" "
            "writes the \"Replace with\" value into EVERY row that matches the "
            "search -- with exact match it replaces the whole cell; unchecked, it "
            "replaces only the matched part within each cell, keeping the rest of the "
            "text (for example, to fix a repeated word across several comments without "
            "retyping them whole). It asks for confirmation before applying any "
            "replacement, showing how many rows would be changed."
        ),
    },
    # -- Nombres de botones acortados (v2.55.0, pedido explícito del
    # usuario): al repartir la pestaña 50/50 (v2.54.0) entre "Consulta
    # SQL" y "Buscar / Buscar y reemplazar", la fila de cuatro botones de
    # "Consulta SQL" (Ejecutar/Guardar/Borrar/Aplicar) quedó demasiado
    # angosta y el texto se truncaba. Se acortaron a una sola palabra
    # intuitiva cada uno, se les agregó un tooltip (aparece al dejar el
    # mouse encima) con la explicación completa, y además se agregó esta
    # nota al botón de ayuda ("?") de la pestaña con el detalle de los
    # nueve botones del panel, agrupados por sección.
    "note_bd_botones": {
        "es": (
            "Botones de \"Consulta SQL\":\n"
            "- \"Ejecutar\": corre el SQL escrito arriba y muestra el resultado en la "
            "tabla de abajo.\n"
            "- \"Guardar\": guarda el SQL actual como una consulta propia reutilizable "
            "(aparece después en \"Consulta de ejemplo:\").\n"
            "- \"Renombrar...\": cambia el nombre de la consulta propia seleccionada "
            "(no de las de ejemplo del plugin).\n"
            "- \"Importar consultas...\" / \"Exportar consultas...\": traen consultas "
            "guardadas desde un archivo .qrylt de GPSeismic o un .json exportado antes, "
            "o guardan las tuyas en un .json para llevarlas a otra máquina o perfil.\n"
            "- \"Borrar\": borra de la base de datos TODAS las filas que trajo la "
            "consulta actual -- sólo se habilita cuando la consulta lo permite (una "
            "sola tabla, sin JOIN/GROUP BY) y pide confirmación antes de borrar.\n"
            "- \"Aplicar\": escribe en la base de datos los cambios pendientes que "
            "hiciste a mano en la tabla (doble clic en una celda) -- sólo se habilita "
            "cuando hay cambios pendientes y pide confirmación antes de guardarlos.\n\n"
            "Botones de \"Buscar / Buscar y reemplazar\":\n"
            "- \"Buscar\": arma y corre un SELECT equivalente a la tabla, columna y "
            "valor elegidos, igual que una consulta manual.\n"
            "- \"Reemplazar\": escribe el valor de \"Reemplazar por\" en TODAS las "
            "filas que coincidan con la búsqueda, pidiendo confirmación y mostrando "
            "cuántas filas se van a modificar."
        ),
        "en": (
            "\"SQL query\" buttons:\n"
            "- \"Run\": runs the SQL written above and shows the result in the table "
            "below.\n"
            "- \"Save\": saves the current SQL as your own reusable query (shows up "
            "later in \"Example query:\").\n"
            "- \"Rename...\": renames the selected query of your own (not the "
            "plugin's example queries).\n"
            "- \"Import queries...\" / \"Export queries...\": bring in saved queries "
            "from a GPSeismic .qrylt file or a .json exported earlier, or save yours "
            "to a .json to carry them to another machine or profile.\n"
            "- \"Delete\": deletes from the database EVERY row the current query "
            "brought back -- only enabled when the query allows it (a single table, "
            "no JOIN/GROUP BY) and asks for confirmation before deleting.\n"
            "- \"Apply\": writes to the database the pending changes you made by "
            "hand in the table (double-click a cell) -- only enabled when there are "
            "pending changes, and asks for confirmation before saving them.\n\n"
            "\"Find / Find and replace\" buttons:\n"
            "- \"Find\": builds and runs an equivalent SELECT for the chosen table, "
            "column and value, just like a manual query.\n"
            "- \"Replace\": writes the \"Replace with\" value into EVERY row that "
            "matches the search, asking for confirmation and showing how many rows "
            "would be changed."
        ),
    },
    "tip_btn_run_query": {
        "es": "Ejecuta el SQL escrito arriba y muestra el resultado en la tabla de abajo.",
        "en": "Runs the SQL written above and shows the result in the table below.",
    },
    "tip_btn_save_query": {
        "es": "Guarda el SQL actual como una consulta propia reutilizable.",
        "en": "Saves the current SQL as your own reusable query.",
    },
    "tip_btn_delete_query_results": {
        "es": "Borra de la base de datos todas las filas de la consulta actual (pide confirmación).",
        "en": "Deletes from the database every row of the current query (asks for confirmation).",
    },
    "tip_btn_save_query_changes": {
        "es": "Escribe en la base de datos los cambios pendientes hechos a mano en la tabla (pide confirmación).",
        "en": "Writes the pending changes made by hand in the table to the database (asks for confirmation).",
    },
    "tip_btn_rename_query": {
        "es": "Cambia el nombre de la consulta propia seleccionada.",
        "en": "Renames the selected query of your own.",
    },
    "tip_btn_import_queries": {
        "es": "Trae consultas guardadas desde un archivo .qrylt o un .json exportado antes.",
        "en": "Brings in saved queries from a .qrylt file or a .json exported earlier.",
    },
    "tip_btn_export_queries": {
        "es": "Exporta tus consultas guardadas a un archivo .json.",
        "en": "Exports your saved queries to a .json file.",
    },
    "tip_btn_sr_search": {
        "es": "Busca el valor en la tabla y columna elegidas y muestra el resultado abajo.",
        "en": "Searches for the value in the chosen table and column and shows the result below.",
    },
    "tip_btn_sr_replace_all": {
        "es": "Reemplaza el valor encontrado por el nuevo valor en todas las filas que coincidan (pide confirmación).",
        "en": "Replaces the found value with the new value in every matching row (asks for confirmation).",
    },
    "lbl_sr_table": {"es": "Tabla:", "en": "Table:"},
    "lbl_sr_column": {"es": "Columna:", "en": "Column:"},
    "lbl_sr_search": {"es": "Buscar:", "en": "Find:"},
    "ph_sr_search": {"es": "Valor a buscar...", "en": "Value to search for..."},
    "chk_sr_exact": {"es": "Coincidencia exacta", "en": "Exact match"},
    "lbl_sr_replace": {"es": "Reemplazar por:", "en": "Replace with:"},
    "ph_sr_replace": {
        "es": "Valor nuevo...",
        "en": "New value...",
    },
    "btn_sr_search": {"es": "Buscar", "en": "Find"},
    "btn_sr_replace_all": {"es": "Reemplazar", "en": "Replace"},
    "err_sr_missing_column": {
        "es": "Elegí una tabla y una columna primero.",
        "en": "Choose a table and a column first.",
    },
    "err_sr_missing_search_value": {
        "es": "Escribí un valor para buscar.",
        "en": "Type a value to search for.",
    },
    "info_sr_nothing_to_replace": {
        "es": "Ninguna fila matchea ese valor de búsqueda -- no hay nada para reemplazar.",
        "en": "No row matches that search value -- there's nothing to replace.",
    },
    "confirm_replace_title": {"es": "Confirmar reemplazo", "en": "Confirm replacement"},
    "confirm_replace_body": {
        "es": (
            "¿Seguro que querés reemplazar \"{buscar}\" por \"{reemplazar}\" en la "
            "columna {columna} de {tabla}?\n\nEsto va a modificar {n} fila(s) de la base "
            "de datos real.\n\nEsta acción no se puede deshacer."
        ),
        "en": (
            "Are you sure you want to replace \"{buscar}\" with \"{reemplazar}\" in "
            "column {columna} of {tabla}?\n\nThis will change {n} row(s) in the real "
            "database.\n\nThis action cannot be undone."
        ),
    },
    "msg_sr_replace_ok_body": {
        "es": "Se reemplazó el valor en {n} fila(s) de la columna {columna} de {tabla}.",
        "en": "The value was replaced in {n} row(s) of column {columna} of {tabla}.",
    },
    "btn_delete_query_results": {
        "es": "Borrar",
        "en": "Delete",
    },
    "btn_save_query_changes": {
        "es": "Aplicar",
        "en": "Apply",
    },
    "lbl_query_empty": {"es": "Sin resultados todavía.", "en": "No results yet."},
    "lbl_query_edit_note": {
        "es": (
            "Cuando la tabla de abajo queda habilitada para editar (mismo caso que el "
            "borrado: una sola tabla POSTPLOT/PREPLOT/COMPARACION, sin JOIN/GROUP BY, y "
            "con columnas reales de esa tabla), podés hacer doble clic en una celda para "
            "cambiar su valor -- la columna ID nunca se puede editar. Los cambios quedan "
            "resaltados y pendientes hasta que apretás \"Aplicar\", que pide "
            "confirmación antes de escribirlos de verdad."
        ),
        "en": (
            "When the table below becomes editable (same rule as deletion: a single "
            "POSTPLOT/PREPLOT/COMPARACION table, no JOIN/GROUP BY, and real columns of "
            "that table), you can double-click a cell to change its value -- the ID column "
            "can never be edited. Changes stay highlighted and pending until you click "
            "\"Apply\", which asks for confirmation before writing "
            "them for real."
        ),
    },
    "confirm_discard_edits_title": {"es": "Cambios sin guardar", "en": "Unsaved changes"},
    "confirm_discard_edits_body": {
        "es": (
            "Tenés cambios de edición sin guardar en la tabla de resultados. Si "
            "continuás, se van a descartar (no se pierde nada de la base de datos, sólo "
            "lo que escribiste y todavía no guardaste).\n\n¿Continuar?"
        ),
        "en": (
            "You have unsaved edits in the results table. If you continue, they'll be "
            "discarded (nothing in the database is lost, only what you typed and haven't "
            "saved yet).\n\nContinue?"
        ),
    },
    "confirm_save_edits_title": {"es": "Confirmar guardado", "en": "Confirm save"},
    "confirm_save_edits_body": {
        "es": (
            "¿Seguro que querés guardar {n_celdas} cambio(s) en {n_filas} fila(s) de la "
            "tabla {tabla}?\n\nEsta acción se aplica de inmediato a la base de datos real."
        ),
        "en": (
            "Are you sure you want to save {n_celdas} change(s) in {n_filas} row(s) of "
            "table {tabla}?\n\nThis is applied immediately to the real database."
        ),
    },
    "info_no_pending_edits_title": {"es": "Sin cambios", "en": "No changes"},
    "info_no_pending_edits_body": {
        "es": "No hay ningún cambio de edición pendiente de guardar.",
        "en": "There are no pending edits to save.",
    },
    "msg_save_edits_ok_body": {
        "es": "Se guardaron los cambios de {n} fila(s) en la tabla {tabla}.",
        "en": "Changes to {n} row(s) in table {tabla} were saved.",
    },
    "warn_save_edits_partial_title": {
        "es": "Algunos cambios no se guardaron",
        "en": "Some changes were not saved",
    },
    "warn_save_edits_partial_body": {
        "es": "Se guardaron los cambios de {n} fila(s), pero hubo errores en otras:\n\n{errores}",
        "en": "Changes to {n} row(s) were saved, but there were errors in others:\n\n{errores}",
    },
    "err_edit_invalid_int": {
        "es": "\"{valor}\" no es un número entero válido para esta columna.",
        "en": "\"{valor}\" is not a valid whole number for this column.",
    },
    "err_edit_invalid_float": {
        "es": "\"{valor}\" no es un número válido para esta columna.",
        "en": "\"{valor}\" is not a valid number for this column.",
    },
    "lbl_query_map_note": {
        "es": (
            "Cada vez que ejecutás una consulta (o una búsqueda), sus resultados se "
            "muestran también como una capa temporal en el mapa (usando el mapeo de "
            "columnas de abajo), siempre de SOLO LECTURA al cargarse -- no hace falta "
            "sacarla a mano, la reemplaza la siguiente consulta/búsqueda sola. Cuando la "
            "consulta es sobre una sola tabla (POSTPLOT, PREPLOT o COMPARACION), activando "
            "\"Editar capa\" en QGIS (el lápiz, igual que en cualquier otra capa) podés "
            "seleccionar puntos y borrarlos con la tecla Supr/Delete -- recién ahí el "
            "borrado se aplica de inmediato a la base de datos real, con un mensaje de "
            "confirmación antes que deja bien claro que es un borrado permanente. Mientras "
            "no actives \"Editar capa\" vos mismo, nada de lo que hagas en el mapa puede "
            "borrar datos reales."
        ),
        "en": (
            "Every time you run a query (or a search), its results are also shown as a "
            "temporary map layer (using the column mapping below), always read-only when "
            "loaded -- no need to remove it by hand, the next query/search replaces it on "
            "its own. When the query is over a single table (POSTPLOT, PREPLOT or "
            "COMPARACION), turning on \"Toggle Editing\" in QGIS (the pencil, same as any "
            "other layer) lets you select points and delete them with the Delete key -- "
            "only then is the deletion applied immediately to the real database, with a "
            "confirmation message first that makes clear it's permanent. Until you turn on "
            "editing yourself, nothing you do on the map can delete real data."
        ),
    },
    "grp_col_mapping": {
        "es": "Mapeo de columnas del resultado (para exportar y ver en el mapa)",
        "en": "Result column mapping (for export and map preview)",
    },
    "lbl_map_name": {"es": "Columna Nombre/Punto:", "en": "Name/Point column:"},
    "lbl_map_line": {"es": "Columna Línea (Track, opcional):", "en": "Line column (Track, optional):"},
    "lbl_map_sps_point": {
        "es": "Columna Punto/Estación para SPS (Bin, opcional):",
        "en": "Point/Station column for SPS (Bin, optional):",
    },
    "lbl_map_x": {"es": "Columna X / Este / Longitud:", "en": "X / Easting / Longitude column:"},
    "lbl_map_y": {"es": "Columna Y / Norte / Latitud:", "en": "Y / Northing / Latitude column:"},
    "lbl_map_z": {"es": "Columna Z / Elevación (opcional):", "en": "Z / Elevation column (optional):"},
    "lbl_map_code": {"es": "Columna Código (opcional):", "en": "Code column (optional):"},
    "chk_map_geographic": {
        "es": "Las columnas X/Y elegidas son geográficas (Longitud/Latitud)",
        "en": "The chosen X/Y columns are geographic (Longitude/Latitude)",
    },
    "grp_export_options": {
        "es": "Opciones para exportar",
        "en": "Export options",
    },
    "lbl_sps_options_hint": {
        "es": "Las opciones de tipo de punto, índice y código fijo de acá abajo sólo se usan si el formato elegido más abajo es SPS.",
        "en": "The point type, index and fixed code options below only apply if the format chosen further down is SPS.",
    },
    "rb_sps_source": {"es": "Fuente (archivo .S01)", "en": "Source (.S01 file)"},
    "rb_sps_receiver": {"es": "Receptor (archivo .R01)", "en": "Receiver (.R01 file)"},
    "lbl_sps_point_type": {"es": "Tipo de punto:", "en": "Point type:"},
    "lbl_sps_index": {"es": "Índice de punto:", "en": "Point index:"},
    "lbl_sps_fixed_code": {
        "es": "Código fijo (si no hay columna):",
        "en": "Fixed code (if no column is chosen):",
    },
    "tip_sps_fixed_code": {
        "es": "Código de 2 caracteres a usar si no eliges una columna de Código arriba.",
        "en": "2-character code to use if you don't choose a Code column above.",
    },
    "lbl_export_format": {"es": "Formato de exportación:", "en": "Export format:"},
    "export_format_shapefile": {"es": "Shapefile (.shp)", "en": "Shapefile (.shp)"},
    "export_format_gpkg": {"es": "GeoPackage (.gpkg)", "en": "GeoPackage (.gpkg)"},
    "export_format_sps": {"es": "SPS (.S01/.R01)", "en": "SPS (.S01/.R01)"},
    "export_format_csv": {"es": "Excel (.csv)", "en": "Excel (.csv)"},
    "btn_export_run": {"es": "Exportar...", "en": "Export..."},
    "msg_export_csv_body": {
        "es": "{n} fila(s) exportadas a:\n{path}",
        "en": "{n} row(s) exported to:\n{path}",
    },
    "info_empty_query_title": {"es": "Consulta vacía", "en": "Empty query"},
    "info_empty_query_body": {
        "es": "Escribe una consulta SELECT primero.",
        "en": "Write a SELECT query first.",
    },
    "warn_query_not_allowed_title": {"es": "Consulta no permitida", "en": "Query not allowed"},
    "err_query_title": {"es": "Error en la consulta", "en": "Query error"},
    "lbl_query_summary": {
        "es": "{n} fila(s), {cols} columna(s).",
        "en": "{n} row(s), {cols} column(s).",
    },
    "warn_missing_data_title": {"es": "Faltan datos", "en": "Missing data"},
    "err_no_query_results": {
        "es": "Primero ejecuta una consulta con resultados.",
        "en": "First run a query with results.",
    },
    "err_missing_map_columns": {
        "es": "Elige al menos las columnas de Nombre, X e Y en el mapeo.",
        "en": "Choose at least the Name, X and Y columns in the mapping.",
    },
    "warn_no_valid_rows_title": {"es": "Sin filas válidas", "en": "No valid rows"},
    "warn_no_valid_rows_body": {
        "es": "Ninguna fila tiene coordenadas X/Y numéricas válidas.",
        "en": "No row has valid numeric X/Y coordinates.",
    },
    "dlg_export_to": {"es": "Exportar a {driver}", "en": "Export to {driver}"},
    "msg_export_points_body": {
        "es": "{n} puntos exportados a:\n{path}",
        "en": "{n} points exported to:\n{path}",
    },
    "err_export_title": {"es": "Error al exportar", "en": "Export error"},
    "err_export_body": {
        "es": "No se pudo exportar:\n{error}\n\n{trace}",
        "en": "Could not export:\n{error}\n\n{trace}",
    },
    "warn_delete_not_supported_title": {"es": "No se puede borrar", "en": "Can't delete"},
    "warn_delete_not_supported_body": {
        "es": (
            "No se puede determinar de forma segura qué tabla y qué filas borrar para "
            "esta consulta.\n\nSólo se puede borrar con un SELECT simple sobre una sola "
            "tabla -- POSTPLOT, PREPLOT o COMPARACION --, sin JOIN, UNION, GROUP BY ni "
            "\"WITH ...\" (CTE)."
        ),
        "en": (
            "Can't safely determine which table and which rows to delete for this query.\n\n"
            "Deleting only works for a simple SELECT over a single table -- POSTPLOT, "
            "PREPLOT or COMPARACION --, with no JOIN, UNION, GROUP BY or \"WITH ...\" (CTE)."
        ),
    },
    "info_delete_nothing_body": {
        "es": "La consulta no tiene ninguna fila para borrar.",
        "en": "The query has no rows to delete.",
    },
    "confirm_delete_title": {"es": "Confirmar borrado", "en": "Confirm deletion"},
    "confirm_delete_query_body": {
        "es": (
            "¿Seguro que querés borrar {n} fila(s) de la tabla {tabla}?\n\n"
            "Esta acción no se puede deshacer."
        ),
        "en": (
            "Are you sure you want to delete {n} row(s) from table {tabla}?\n\n"
            "This action cannot be undone."
        ),
    },
    "confirm_delete_map_body": {
        "es": (
            "¿Seguro que querés borrar {n} punto(s) de la tabla {tabla}?\n\n"
            "Esta acción no se puede deshacer."
        ),
        "en": (
            "Are you sure you want to delete {n} point(s) from table {tabla}?\n\n"
            "This action cannot be undone."
        ),
    },
    "err_delete_title": {"es": "Error al borrar", "en": "Delete error"},
    "err_delete_body": {
        "es": "No se pudo borrar:\n{error}\n\n{trace}",
        "en": "Could not delete:\n{error}\n\n{trace}",
    },
    "msg_delete_ok_body": {
        "es": "Se borraron {n} fila(s) de la tabla {tabla}.",
        "en": "{n} row(s) deleted from table {tabla}.",
    },
    "layer_query_provisional": {
        "es": "Resultado de consulta (vista previa)",
        "en": "Query result (preview)",
    },
    "dlg_export_sps_title": {"es": "Exportar a SPS", "en": "Export to SPS"},
    "warn_missing_sps_columns_title": {
        "es": "Faltan columnas para SPS",
        "en": "Missing columns for SPS",
    },
    "warn_missing_sps_columns_body": {
        "es": (
            "El formato SPS necesita números de línea y de punto/estación "
            "por separado (no el nombre completo del punto).\n\n"
            "Elige en el mapeo de columnas: {faltan}."
        ),
        "en": (
            "The SPS format needs separate line and point/station numbers "
            "(not the full point name).\n\n"
            "Choose in the column mapping: {faltan}."
        ),
    },
    "sps_missing_line": {"es": "Línea (Track)", "en": "Line (Track)"},
    "sps_missing_point": {"es": "Punto/Estación para SPS (Bin)", "en": "Point/Station for SPS (Bin)"},
    "msg_export_sps_body": {
        "es": "{n} registro(s) escritos en:\n{path}",
        "en": "{n} record(s) written to:\n{path}",
    },
    "msg_export_sps_skipped": {
        "es": "\n\n({n} fila(s) omitidas por no tener línea/punto/X/Y numéricos válidos.)",
        "en": "\n\n({n} row(s) skipped for not having valid numeric line/point/X/Y.)",
    },
    "err_export_sps_body": {
        "es": "No se pudo exportar a SPS:\n{error}\n\n{trace}",
        "en": "Could not export to SPS:\n{error}\n\n{trace}",
    },

    # Columnas de la previsualización de "Importar datos de campo",
    # reorganizada para reproducir el layout de 58 columnas de la base de
    # datos POSTPLOT real que exporta GPSeismic (ver la nota junto a
    # `PREVIEW_COL_INCLUDE` en gnsseismic_windows.py) -- los nombres en
    # inglés son, a propósito, los mismos que usa GPSeismic (para que el
    # usuario los reconozca de inmediato si ya conoce ese software); los
    # de español son una traducción directa, no una convención propia
    # del plugin.
    "col_station_value": {"es": "Estación (valor)", "en": "Station (value)"},
    "col_track": {"es": "Línea", "en": "Track"},
    "col_bin": {"es": "Estaca", "en": "Bin"},
    "col_descriptor": {"es": "Descriptor", "en": "Descriptor"},
    "col_lat_wgs84": {"es": "Latitud WGS84", "en": "WGS84 Latitude"},
    "col_lon_wgs84": {"es": "Longitud WGS84", "en": "WGS84 Longitude"},
    "col_lat_local": {"es": "Latitud local", "en": "Local Latitude"},
    "col_lon_local": {"es": "Longitud local", "en": "Local Longitude"},
    "col_scale_factor": {"es": "Factor de escala", "en": "Scale Factor"},
    "col_convergence": {"es": "Convergencia", "en": "Convergence"},
    "col_survey_mode_text": {"es": "Modo de levant. (texto)", "en": "Survey Mode (text)"},
    "col_survey_mode_value": {"es": "Modo de levant. (valor)", "en": "Survey Mode (value)"},
    "col_offset_north": {"es": "Offset Norte", "en": "Offset (North)"},
    "col_offset_east": {"es": "Offset Este", "en": "Offset (East)"},
    "col_offset_range": {"es": "Offset Rango", "en": "Offset (Range)"},
    "col_offset_bearing": {"es": "Offset Rumbo", "en": "Offset (Bearing)"},
    "col_offset_inline": {"es": "Offset Inline", "en": "Offset (Inline)"},
    "col_offset_crossline": {"es": "Offset Crossline", "en": "Offset (Crossline)"},
    "col_offset_height": {"es": "Offset Altura", "en": "Offset (Height)"},
    "col_inline_azimuth": {"es": "Azimut de línea", "en": "Inline Azimuth"},
    "col_hor_precision": {"es": "Precisión Hor. 95%", "en": "Hor 95% Precision"},
    "col_ver_precision": {"es": "Precisión Vert. 95%", "en": "Ver 95% Precision"},
    "col_cq": {"es": "CQ", "en": "CQ"},
    "col_n_sats": {"es": "N° Satélites", "en": "Number of Satellites"},
    "col_pdop": {"es": "PDOP", "en": "PDOP"},
    "col_hdop": {"es": "HDOP", "en": "HDOP"},
    "col_vdop": {"es": "VDOP", "en": "VDOP"},
    "col_julian_date": {"es": "Fecha juliana (local)", "en": "Julian Date (Local)"},
    "col_survey_time_local": {"es": "Hora de levant. (local)", "en": "Survey Time (Local)"},
    "col_survey_time_gmt": {"es": "Hora de levant. (GMT)", "en": "Survey Time (GMT)"},
    "col_serial_time_gps": {"es": "Hora serial (GPS)", "en": "Serial Time (GPS)"},
    "col_elapsed_time": {"es": "Tiempo transcurrido", "en": "Elapsed Time"},
    "col_populate_time": {"es": "Hora de carga", "en": "Populate Time"},
    "col_local_datum": {"es": "Datum local", "en": "Local Datum"},
    "col_local_system": {"es": "Sistema local", "en": "Local System"},
    "col_distance_units": {"es": "Unidades de distancia", "en": "Distance Units"},
    "col_distance_factor": {"es": "Factor de distancia", "en": "Distance Factor"},
    "col_download_file": {"es": "Archivo de descarga", "en": "Download File"},
    "col_job_name": {"es": "Nombre del trabajo", "en": "Collector Job Name"},
    "col_receiver_type": {"es": "Tipo de receptor", "en": "Receiver Type"},
    "col_receiver_sn": {"es": "N° de serie del receptor", "en": "Receiver SN"},
    "col_gdop": {"es": "GDOP", "en": "GDOP"},
    "col_unit_variance": {"es": "Varianza unitaria", "en": "Unit Variance"},
    "col_gps_baseline": {"es": "Línea base GPS (m)", "en": "GPS Baseline"},
    "col_gps_base_station": {"es": "Base GPS", "en": "GPS Base Station"},
    "col_occupation_time": {"es": "Tiempo de ocupación", "en": "Occupation Time"},
    "col_init_block": {"es": "Bloque de inicialización", "en": "Init Block"},
    "col_station_deltas": {"es": "Deltas de estación", "en": "Station Deltas"},
    "col_consecutive_intervals": {"es": "Intervalos consecutivos", "en": "Consecutive Intervals"},
    "col_consecutive_azimuths": {"es": "Azimuts consecutivos", "en": "Consecutive Azimuths"},
    "col_recnum": {"es": "N° de registro", "en": "recnum"},
    "col_reserved": {"es": "Reservado", "en": "Reserved"},
    "col_local_datum_wgs84": {"es": "WGS84", "en": "WGS84"},
    "col_distance_units_meter": {"es": "Metro", "en": "Meter"},
    "survey_mode_phase": {"es": "Fase", "en": "Phase"},
    "survey_mode_autonomo": {"es": "Autónomo", "en": "Autonomous"},
    "survey_mode_float": {"es": "Flotante", "en": "Float"},
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Devuelve el texto traducido para `key` en `lang` ('es'/'en'),
    aplicando `str.format(**kwargs)` si se pasan argumentos. Si falta la
    clave o el idioma, cae a español y luego a la propia clave (para
    nunca romper la interfaz por una traducción faltante).
    """
    entry = TR.get(key)
    if entry is None:
        text = key
    else:
        text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
