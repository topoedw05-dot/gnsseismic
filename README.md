# GNSSeismic (plugin QGIS)

Plugin **bilingüe (español / inglés)** de QGIS para topografía **GNSS/RTK
y sísmica**: gestión de proyectos con base de datos SQLite compatible con
el esquema **PREPLOT / POSTPLOT** usado habitualmente en posicionamiento
de puntos sísmicos (fuentes y receptores), importación de datos de campo
de varias marcas de equipo GNSS/RTK, comparación contra el diseño,
generación de preplot, y consulta/exportación de la base de datos.

> **Estado: EXPERIMENTAL.** Este plugin está en desarrollo activo y se
> comparte para que un grupo chico de usuarios lo pruebe con sus propios
> datos reales y ayude a encontrarle problemas antes de un lanzamiento
> más estable. Puede tener errores, cambiar de interfaz de una versión a
> otra sin aviso previo, y algunas columnas quedan deliberadamente en
> blanco cuando el plugin no tiene todavía un dato o fórmula verificada
> para tu equipo/formato en particular (ver "Notas y limitaciones
> conocidas" más abajo) -- se prefiere dejarlas vacías a inventar un
> valor. Si lo probás, reportá lo que encuentres (ver "Cómo colaborar"
> al final) -- es justamente lo que hace falta para pulirlo.

> Este plugin se llamaba **"Gestor DC Topografía"** hasta la versión
> 1.3.0. Desde la **2.0.0** se renombró a **GNSSeismic** y cambió de
> interfaz: en vez de un único diálogo con pestañas, ahora es un
> **toolbar con un ícono por sección**; cada uno abre esa sección como
> una ventana independiente, para poder tener varias abiertas a la vez.
> Internamente también cambió de identificador (`gestor_dc` →
> `gnsseismic`), así que QGIS lo trata como un plugin nuevo: si ya tenías
> instalado "Gestor DC Topografía", desinstálalo aparte para no quedar
> con dos plugins duplicados (ver "Instalación" más abajo).

Un selector de idioma en el mismo toolbar (**Idioma / Language**) cambia
toda la interfaz —de todas las ventanas que tengas abiertas— entre
español e inglés en el momento, sin reiniciar el plugin.

## Qué hace

El toolbar **GNSSeismic** tiene cinco íconos, uno por sección; cada uno
abre su sección en una ventana independiente y no modal (podés tener
varias abiertas a la vez).

### 1. Proyecto

Crea un proyecto nuevo como una carpeta (con subcarpetas
`database/maps/preplot/posplot`) con una base de datos SQLite propia
(tablas `POSTPLOT`, `PREPLOT`, `TableDescriptions`, `COMPARACION` y
`ProjectSettings`), o abre uno ya existente -- con una ventana **"Mis
proyectos"** para cambiar con un clic entre todos los proyectos ya
usados, sin importar en qué carpeta o unidad esté cada uno. El recuadro
"Base de datos del proyecto" (ruta, botones Nuevo/Abrir/Mis proyectos/
Actualizar conteos, y los conteos POSTPLOT/PREPLOT/COMPARACION) queda
siempre visible; debajo, un botón despliega/oculta la configuración más
detallada del proyecto:

- **CRS de trabajo** (por defecto MAGNA-SIRGAS/Origen-Nacional,
  EPSG:9377, pero ajustable a cualquier CRS proyectado -- por ejemplo
  POSGAR/Gauss-Krüger para Argentina), guardado con cada proyecto para
  que cambiar de proyecto cambie también su sistema de coordenadas.
- **Geoide del proyecto** (opcional): cualquier ráster que QGIS abra
  directamente (GeoTIFF, GTX, ASCII Grid, o el binario Surfer GRD en que
  suele distribuirse el QGeoiCol2004 de IGAC), o el formato binario
  propietario **.ggf ("TNL GRID FILE") de Trimble**, leído con un parser
  propio incluido en el plugin.
- **Tipo de levantamiento** (2D/3D) y, si es 3D, los azimutes de línea
  fuente/receptora, usados para calcular Offset/Azimut de línea al
  importar datos de campo.
- **Factor de escala del proyecto** (terreno ↔ grilla, pensado para un
  futuro módulo de Estación Total): un punto de referencia (con un botón
  para tomarlo con un clic en el mapa) calcula el factor de la
  proyección, el de elevación y el combinado.

### 2. Importar datos de campo

Importa archivos de **cuatro marcas** de equipo GNSS/RTK, agrupadas bajo
un único botón "Agregar..." con un ítem por marca:

- **Trimble** (`.dc`/`.dsc`): registros KI (cinemático) y SO (estación,
  con control de calidad).
- **Hi-Target** (CSV o el binario `.raw` propio del equipo).
- **CHCNav/LandStar** (`.rw5`).
- **Stonex** (`.PD`, en realidad una base de datos SQLite propia).
- **SurPad** (`.rw5` y `.raw`).
- **SourceLink** (`.csv` con las posiciones de los vibros; el *Unit ID* de cada disparo se sube como *Surveyor*).
- **Inova** (`.xls` de los vibros: el COG de cada VP, con la altura de antena editable en la columna HI; los vibros del VP se suben como *Surveyor*).

Para cada punto, cuando el formato lo trae, se aprovechan satélites
usados, PDOP/HDOP/VDOP, duración de la ocupación, calidad de la
solución (Fijo/Flotante/Autónomo), y la distancia/nombre de la base RTK
usada. Si hay una base RTK física detectada entre los puntos cargados
(libre, sin corregir), la sección **"Corrección de base RTK"** permite
escribir o cargar su coordenada ya corregida por post-proceso, y el
plugin traslada todos los puntos levantados con esa base antes de
subirlos. La previsualización es editable (incluido un editor en bloque
para pisar de una sola vez la altura de antena o el Descriptor de todos
los puntos incluidos), se compara automáticamente contra el PREPLOT del
proyecto para decidir qué puntos subir, admite filtros SQL con presets
predefinidos (por ejemplo "Sin PREPLOT") y un asistente para armar
filtros propios sin escribir SQL, y permite verificar duplicados contra
la base antes de subir. Si hay un geoide asignado al proyecto, calcula
también la altura ortométrica (`Local_Height = WGS84_Height − N`). Al
confirmar, los puntos se insertan en `POSTPLOT` y se crea una capa de
puntos en el proyecto de QGIS, simbolizada por tipo.

### 3. Comparar

Compara puntos levantados contra puntos de diseño, cuya fuente puede ser
un **CSV** cargado por el usuario (con mapeo de columnas) o directamente
la **tabla PREPLOT** ya guardada en la base del proyecto. Empareja por
nombre de punto (con un segundo intento ignorando guiones, espacios y
ceros a la izquierda si el primero no coincide exacto), calcula ΔEste,
ΔNorte y distancia 2D/3D, y marca qué puntos quedan dentro o fuera de
una tolerancia configurable. El resultado se puede subir a la tabla
`COMPARACION` del proyecto.

### 4. Preplot Sísmico

Genera puntos de diseño directamente desde el plugin, sin CSV externo,
en **Grilla 3D** (origen + azimut + espaciamientos + cantidad de
líneas/estaciones) o **Línea 2D** (dos puntos, u origen + azimut +
longitud), al estilo GPSeismic. También importa un preplot ya armado en
otro software: un archivo **SPS** (SEG rev. 2.1), un archivo **.qld**
("QLD9", formato binario propietario, leído con un parser propio), o una
capa de puntos ya cargada en QGIS (Shapefile, GeoPackage, CSV). Todo se
guarda en la tabla `PREPLOT`.

### 5. Base de Datos

Editor de consultas SQL de sólo lectura (`SELECT`/`WITH`) sobre la base
del proyecto, con presets comunes y una sección "Buscar / Buscar y
reemplazar" para no tener que escribir SQL a mano. El resultado se
muestra como capa temporal en el mapa, admite edición en línea y borrado
de filas seleccionadas, y se puede exportar a **Shapefile**, **GeoPackage**,
**CSV** o **SPS** (.S01/.R01).

## Formatos de archivo de campo soportados

| Marca | Formato | Parser propio |
|---|---|---|
| Trimble | `.dc` / `.dsc` | `dc_parser.py` |
| Hi-Target | `.csv` / `.raw` | `hitarget_parser.py` / `hitarget_raw_parser.py` |
| CHCNav / LandStar | `.rw5` | `chcnav_parser.py` |
| Stonex | `.PD` (SQLite) | `stonex_parser.py` |
| SurPad | `.rw5` / `.raw` | `chcnav_parser.py` / `surpad_parser.py` |
| SourceLink (vibros) | `.csv` | `sourcelink_parser.py` |
| Inova (vibros, COG) | `.xls` | `inova_parser.py` (+ `_xlrd/`, xlrd BSD incluido) |

Los cuatro se reconstruyeron por ingeniería inversa, verificando cada
campo contra archivos reales y, cuando estuvo disponible, contra bases
de datos POSTPLOT reales exportadas por GPSeismic -- no hay
documentación oficial pública de ninguno de los cuatro formatos. Si tu
equipo genera un archivo con una estructura distinta (otro firmware o
modelo), es muy probable que el parser necesite un ajuste menor.

## Instalación

1. Descarga/clona esta carpeta (`gnsseismic/`).
2. Si tenías instalada una versión anterior con el nombre **"Gestor DC
   Topografía"**, desinstálala primero desde `Complementos > Administrar
   e instalar complementos > Instalados` (botón "Desinstalar complemento")
   — QGIS trata a `gnsseismic` como un plugin distinto de `gestor_dc`, así
   que si no la quitas quedarán las dos instaladas a la vez.
3. Copia la carpeta `gnsseismic/` dentro de la carpeta de plugins de tu
   perfil de QGIS:
   - Windows (QGIS 4.x): `C:\Users\<usuario>\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins\`
   - Windows (QGIS 3.x): `C:\Users\<usuario>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
   - Linux/Mac (QGIS 3.x o 4.x): `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

   (el nombre de la carpeta de perfil -- `QGIS3` o `QGIS4` -- depende de
   la versión de QGIS instalada, no del plugin; si no la encontrás, abrí
   QGIS y mirá `Configuración > Perfiles de usuario > Abrir carpeta de
   perfil activo`).
4. Al venir marcado como **experimental**, QGIS no lo muestra por
   defecto en el Administrador de complementos: primero activá
   `Complementos > Administrar e instalar complementos > Configuración >
   "Mostrar también los complementos experimentales"`.
5. En `Complementos > Administrar e instalar complementos > Instalados`,
   marca **"GNSSeismic"**.
6. Aparecerá un nuevo toolbar **"GNSSeismic"** con cinco íconos (uno por
   sección) y una entrada **GNSSeismic** en el menú **Complementos** con
   esas mismas cinco acciones, por si prefieres el menú o tienes el
   toolbar oculto.

## Idioma

El toolbar del plugin incluye un selector **Idioma / Language** (Español
/ English) que cambia toda la interfaz —títulos de ventana, etiquetas,
botones, mensajes, de las cinco secciones a la vez, estén o no abiertas
en ese momento— sin perder lo que ya se cargó (proyecto abierto,
archivos cargados, resultados de una consulta, etc.). Los datos
guardados en la base (nombres de tabla, valores de `Descriptor`, etc.)
no cambian con el idioma de la interfaz, para no romper la
compatibilidad con el software de origen.

## Estructura de archivos

- `metadata.txt`, `__init__.py`, `icon.png` — metadatos del plugin.
- `gnsseismic.py` — registro del plugin en QGIS: arma el toolbar
  "GNSSeismic" (cinco íconos + selector de idioma) y el menú de
  Complementos; delega la lógica al controlador de `gnsseismic_windows.py`.
- `gnsseismic_windows.py` — `GNSSeismicController` (estado compartido y
  lógica de las cinco secciones) y `_SectionWindow` (la ventana no modal
  que envuelve cada sección); integración con capas/CRS/ráster de QGIS.
  Enums escopados de Qt6 + fallback PyQt5.
- `i18n.py` — diccionario de traducciones ES/EN y la función `t()` que las
  aplica; sin dependencias de QGIS.
- `dc_parser.py` — lector del formato Trimble `.dc`/`.dsc`.
- `hitarget_parser.py` / `hitarget_raw_parser.py` — lectores del CSV y
  del binario `.raw` de Hi-Target.
- `chcnav_parser.py` — lector del `.rw5` de CHCNav/LandStar.
- `stonex_parser.py` — lector de la base de datos SQLite (`.PD`) de
  Stonex.
- `surpad_parser.py` — lector del `.raw` de SurPad (y despachador `.rw5`/`.raw`).
- `sourcelink_parser.py` — lector del CSV de SourceLink (posiciones de vibros).
- `tabla_fija.py` — `QTableWidget` con columnas fijas a la izquierda (previsualización de campo).
- `ui_widgets.py` — widgets propios de la interfaz: interruptor (`ToggleSwitch`), bloque desplegable (`AcordeonSeccion`), lista compacta, etiqueta con texto resumido (`EtiquetaElidida`) y pestañas que toman el alto de la activa (`PestanasAltoActual`).
- `shared_project.py` — modo compartido opcional (bloqueo de un solo editor, copia local y publicación atómica).
- `punto_nombre.py` — Station (value)/Línea/Estaca derivados del nombre del punto.
- `inova_parser.py` — lector del `.xls` de Inova (algoritmo de la macro
  `ExtraerCOG_GPSeismic`); usa la copia de xlrd de `_xlrd/` (licencia BSD).
- `db_schema.py` — esquema SQLite (POSTPLOT/PREPLOT/TableDescriptions/
  COMPARACION/ProjectSettings), funciones de inserción/consulta, el
  editor de consultas de sólo lectura y el guardado de ajustes del
  proyecto; sin dependencias de QGIS.
- `geoid_utils.py` — fórmula de altura ortométrica (`H = h - N`); sin
  dependencias de QGIS.
- `ggf_reader.py` — lector propio del `.ggf` de Trimble para modelos de
  geoide, con interpolación bilineal; sin dependencias de QGIS ni GDAL.
- `qld_reader.py` — lector propio del `.qld` ("QLD9") de diseño/QC de
  puntos sísmicos; sin dependencias de QGIS.
- `csv_matcher.py` — lectura de CSV y emparejamiento de puntos por
  nombre.
- `preplot_generator.py` — generación de puntos de preplot sísmico
  (grilla 3D y línea 2D); sin dependencias de QGIS.
- `export_writers.py` — escritura del formato sísmico SPS (SEG rev. 2.1,
  .S01/.R01); sin dependencias de QGIS.
- `test_gnsseismic.py` — pruebas unitarias de parsers/lógica de datos
  (no requieren QGIS instalado; se corren con
  `python3 -m pytest test_gnsseismic.py -v`). Cubren los parsers de
  archivo y la lógica de base de datos/filtros/exportación -- no la
  interfaz de QGIS en sí, que se verifica a mano.
- `LICENSE` — GPLv3.

## Notas y limitaciones conocidas

- Varias columnas de la previsualización de "Importar datos de campo"
  (precisión 95%, hora de levantamiento GMT/local, offset de altura de
  antena por modelo de receptor, factor de escala/convergencia) se
  calculan con fórmulas verificadas al milímetro/segundo contra archivos
  y bases de datos POSTPLOT reales del autor, pero dependen de datos que
  sólo algunos formatos traen, o de tablas de calibración que se
  completan de a un receptor/semana de trabajo por vez, a medida que
  aparece un archivo real para verificar -- si tu equipo o tu rango de
  fechas todavía no está cubierto, esas columnas quedan en blanco en vez
  de mostrar un valor adivinado. Si tenés un archivo real de un
  receptor/formato que no se complete, es justo el tipo de reporte que
  ayuda a pulir el plugin (ver "Cómo colaborar" abajo).
- La separación del nombre del punto en "Línea" (Track) y "Estaca" (Bin)
  es una heurística configurable (número de dígitos iniciales); ajústala
  a la convención de nomenclatura real de tu proyecto o desactívala
  (0 dígitos) si no aplica.
- El panel de consultas de "Base de Datos" sólo permite `SELECT`/`WITH`
  (una sola sentencia, sin `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ATTACH`/
  etc.); para modificar datos usa las otras secciones del plugin, o
  "Buscar y reemplazar" dentro de la misma sección.
- La exportación SPS genera los archivos de puntos de Fuente (.S01) y
  Receptor (.R01); no genera el archivo relacional (.X01), que requiere
  información de geometría de arreglo/canales que este plugin no modela.
- El geoide se aplica sobre un único punto por vez (no una operación
  matricial); para levantamientos muy grandes esto es más lento, pero
  evita depender de que el ráster esté registrado como "vertical shift
  grid" de PROJ. Si un punto cae fuera de la extensión del geoide, esa
  fila queda sin `Geoid_Height`/`Local_Height` (no se interrumpe la
  importación).
- Los formatos `.dc`/`.dsc` (Trimble), `.raw` (Hi-Target) y `.PD`
  (Stonex) no tienen documentación oficial pública; sus parsers se
  construyeron por inspección directa de archivos reales y, cuando fue
  posible, verificación contra bases de datos POSTPLOT reales de
  GPSeismic.
- Cada sección abre en su propia ventana (no modal), y las cinco se
  arman al activar el plugin (no sólo cuando se abren por primera vez),
  para que un cambio en "Proyecto" (por ejemplo, cargar un geoide nuevo)
  se refleje de inmediato en las otras secciones aunque todavía no se
  hayan abierto en la sesión.
- Al cerrar una ventana de sección con la X no se pierde lo que tenía
  cargado (proyecto abierto, archivos cargados, último resultado de
  comparación, etc.): simplemente se oculta, y se reconstruye tal cual
  estaba al volver a abrirla desde el toolbar.

## Cómo colaborar / reportar problemas

Este plugin se comparte como **experimental** justamente para recibir
reportes de gente que lo prueba con sus propios datos y equipos. Si
encontrás un error, un cálculo que no coincide con tu software de
referencia, o una columna que debería completarse y queda en blanco,
abrí un issue en el tracker del repositorio con, si es posible, el
archivo real (o un fragmento) que lo dispara -- es la forma más rápida
de verificarlo y corregirlo, siguiendo el mismo criterio de este plugin
de nunca adivinar un valor sin poder comprobarlo contra un dato real.

- Repositorio: https://github.com/topoedw05-dot/gnsseismic
- Reportar un problema: https://github.com/topoedw05-dot/gnsseismic/issues


## Proyecto compartido (opcional)

Para que varias oficinas (por ejemplo la oficina de campo y Buenos Aires)
vean o procesen el mismo proyecto a través de una carpeta sincronizada
(Google Drive para escritorio u otra), en la pestaña **Proyecto** use
*Compartir este proyecto...* (o responda que sí al crear uno nuevo). Es
opcional: un proyecto no compartido funciona exactamente como siempre.

- **Un solo editor a la vez.** Quien abre primero edita; el resto abre el
  proyecto en **solo lectura** (con un aviso rojo en las pestañas que
  escriben) y puede ver el avance. Un lector puede *Tomar el control* si el
  editor terminó o quedó colgado; el anterior pasa a solo lectura y sus
  cambios no publicados se guardan como respaldo en su computador.
- **Copia local + publicación.** El editor trabaja sobre una copia local y
  el plugin **publica** la base completa en la carpeta compartida (reemplazo
  atómico) después de cada cambio, cada minuto si hubo cambios, al cerrar y
  con *Publicar ahora*. Los lectores siempre reciben una versión completa
  (la última publicada) y la renuevan con *Actualizar*.
- **Archivos de campo, mapas, preplot:** viven en la misma carpeta del
  proyecto y se abren con las rutas de la unidad de Drive como cualquier
  archivo.
- Junto a la base se crean `<base>.sqlite.shared.json` (marca de proyecto
  compartido) y `<base>.sqlite.lock.json` (quién edita). No los borre a
  mano salvo que nadie esté editando. El bloqueo es un aviso: Drive tarda en
  sincronizar y en campo puede no haber internet, así que dos personas
  pueden verse libres durante unos instantes; el plugin lo detecta en el
  siguiente latido (cada minuto).
