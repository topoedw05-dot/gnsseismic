# -*- coding: utf-8 -*-
"""
hitarget_raw_parser.py
------------------------
Lector del archivo ".raw" binario propio de Hi-Target (el log interno del
receptor/controlador, NO el CSV que ya lee `hitarget_parser.py`) para la
sección "Importar datos de campo". Añadido en la v2.23.0 a pedido del
usuario, que subió un archivo real llamado "GPS.raw" (renombrado a .txt
sólo para poder subirlo, el contenido es binario intacto).

Formato (deducido por ingeniería inversa a partir de DOS archivos reales
del usuario, NO documentado por Hi-Target en ningún lado público):

- Un encabezado fijo de 86 bytes al inicio del archivo (contenido no
  usado por este parser).
- A partir de ahí, una serie de REGISTROS DE LONGITUD FIJA de 398 bytes
  cada uno, hasta el final del archivo. (`(len(datos) - 86) % 398 == 0`
  en los dos archivos reales analizados).
- Cada registro trae, dentro de esos 398 bytes:
    * bytes 0-2 (3 letras ASCII): código de tipo de registro. Se
      observaron dos: "RMV" y "HSD". Cada punto real del levantamiento
      aparece exactamente UNA VEZ como registro "HSD" -- los "RMV" son
      lecturas duplicadas/preliminares del mismo punto (mismo nombre,
      misma posición) que ya vuelve a aparecer como "HSD" más adelante
      en el archivo; por eso este parser IGNORA por completo los
      registros "RMV" y sólo procesa los "HSD" (evita duplicar puntos
      sin necesidad de una segunda pasada de deduplicación).
    * bytes 13-20: latitud, en RADIANES, como IEEE-754 double de 8
      bytes en BIG-ENDIAN (a diferencia de todos los demás formatos que
      lee este plugin -- .dc, .rw5, CSV --, que son little-endian o
      texto; aquí el propio archivo real lo confirma, ver más abajo).
    * bytes 21-28: longitud, en RADIANES, mismo formato (double BE),
      inmediatamente a continuación de la latitud.
    * bytes 142-171 (30 bytes, rellenados con 0x00): nombre del modelo
      del equipo, ej. "Hi-Target:V60-2" (la base) o "Hi-Target:V30
      Plus" (el móvil). No se usa para nada que se suba (es informativo
      del equipo, no del punto), pero ayuda a distinguir visualmente
      una fila de base de una de rover si hace falta depurar.
    * bytes 172-195 (24 bytes, rellenados con 0x00): NOMBRE del punto
      (columna "Nombre" del CSV que exporta el mismo software).
    * bytes 196-255 (60 bytes, rellenados con 0x00): comentario/código
      de campo (columna "Desc" del CSV -- "set_base" para una ocupación
      de base, o el código que haya escrito el topógrafo, ej. "L cc"/
      "L ceme"/"BM HOSPITAL").
    * bytes 280-287: N (grilla local del equipo), double BE -- NO se
      usa, por la misma razón que `hitarget_parser.py` tampoco usa las
      columnas N/E/Z del CSV (no hay forma de saber en qué CRS está esa
      grilla local desde este archivo solo).
    * bytes 288-295: E (grilla local), double BE -- tampoco se usa.
    * bytes 296-303: altura elipsoidal WGS84 (columna "H" del CSV),
      double BE.

  La ALTURA DE ANTENA (columna "AntH" del CSV) se buscó exhaustivamente
  -- cada offset del registro, como double y como float32, en ambos
  órdenes de bytes -- y NO aparece en ninguna parte del archivo binario
  en ninguno de los dos archivos reales analizados (a diferencia de
  latitud/longitud/altura, que sí se encontraron y verificaron). Esto
  indica que el software de Hi-Target la agrega recién al exportar el
  CSV, tomándola de la configuración del trabajo/proyecto (que se
  configura una sola vez por sesión), no del log binario punto por
  punto. Por eso `HiTargetPoint.ant_height` queda siempre en `None`
  para un punto que viene de un .raw -- exactamente igual que para un
  punto de un .dc de Trimble sin registro 57KI, o de un .rw5 de CHCNav
  sin registro LS: se deja vacío y editable en la previsualización (o
  se usa "Aplicar a todos" si el usuario conoce el valor).

VERIFICACIÓN (nivel de confianza alto, con referencia real del usuario):
el archivo real "GPS.raw" (43 puntos + 2 ocupaciones de base "GPS01"/
"GPS01_1") se comparó, byte por byte y en todos los offsets posibles,
contra el CSV real "La_Yerbabuena_csv_072810.csv" que el usuario
confirmó que es la exportación de ESA MISMA sesión de campo (mismos 45
puntos únicos, incluyendo el nombre no numérico "31 (25cm oriente)" y
el punto final "BM HOSPITAL"). Latitud, longitud y altura de los 45
puntos coincidieron con los de ese CSV (convertidos a radianes/grados)
hasta la 7ª-9ª cifra decimal -- la única forma de que coincidan tan
exacto en los 45 puntos a la vez es que sea, en efecto, el campo
correcto. Un primer CSV que el usuario subió por error ("San Antonio",
de otra sesión distinta) NO coincidió con ningún valor del .raw en
ningún offset -- así se detectó el error antes de dar por buena
cualquier interpretación.

Lo que NO se pudo verificar (y por eso no se usa/expone todavía):
número de satélites, PDOP, épocas promediadas, duración de la ocupación
y la línea base a la estación de referencia -- se buscaron los valores
conocidos del CSV (Sats/PDOP/N Promedios/σN/σE/σZ) en la zona final de
cada registro (bytes 256-398) sin encontrar una coincidencia clara; se
deja pendiente para una futura versión si aparece un archivo real que
permita verificarlos con la misma rigurosidad.

Este módulo no depende de QGIS ni de PyQt (igual que los demás
parsers), y reutiliza las mismas clases `HiTargetPoint`/`HiTargetFile`
de `hitarget_parser.py` (y su misma lógica de emparejar cada punto con
la ocupación de base más cercana del propio archivo) para que el resto
del plugin (previsualización, comparación, subida a POSTPLOT) funcione
exactamente igual sin importar si el Hi-Target vino de un .csv o de un
.raw.
"""

import math
import struct
from typing import Optional

try:  # pragma: no cover - depende de si se importa como paquete o suelto
    # Import relativo normal cuando corre dentro de QGIS como parte del
    # paquete del plugin (igual que hace gnsseismic_windows.py).
    from .hitarget_parser import HiTargetFile, HiTargetPoint, _haversine_m
except ImportError:
    # Import absoluto cuando corre suelto (p.ej. test_gnsseismic.py, que
    # importa todos los módulos de lógica pura sin paquete contenedor).
    from hitarget_parser import HiTargetFile, HiTargetPoint, _haversine_m

_HEADER_SIZE = 86
_RECORD_SIZE = 398

_OFF_TYPE = 0
_LEN_TYPE = 3
_OFF_LAT_RAD = 13
_OFF_LON_RAD = 21
_OFF_MODEL = 142
_LEN_MODEL = 30
_OFF_NAME = 172
_LEN_NAME = 24
_OFF_DESC = 196
_LEN_DESC = 60
_OFF_HEIGHT = 296

_RECORD_TYPE_POINT = b"HSD"

# Rango de latitud/longitud sano (radianes) para descartar un registro
# corrupto/con offsets mal alineados en vez de subir una coordenada
# absurda -- igual de conservador que el rango 0-10 m que usa
# `dc_parser._parse_57ki_antenna_height` para el mismo propósito.
_LAT_RAD_RANGE = (-math.pi / 2, math.pi / 2)
_LON_RAD_RANGE = (-math.pi, math.pi)


def _decode_padded_text(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()


def looks_like_hitarget_raw(data: bytes) -> bool:
    """True si `data` (los bytes crudos del archivo) tiene la forma
    esperada de un .raw de Hi-Target: al menos un registro completo
    después del encabezado de 86 bytes, con una longitud total múltiplo
    exacto de 398 a partir de ahí, y con "RMV"/"HSD" reconocibles en la
    posición esperada del primer registro."""
    if len(data) < _HEADER_SIZE + _RECORD_SIZE:
        return False
    if (len(data) - _HEADER_SIZE) % _RECORD_SIZE != 0:
        return False
    primer_tipo = data[_HEADER_SIZE:_HEADER_SIZE + _LEN_TYPE]
    return primer_tipo in (b"RMV", b"HSD")


def parse_hitarget_raw(path: str) -> HiTargetFile:
    """Lee y parsea un .raw binario de Hi-Target desde disco."""
    with open(path, "rb") as f:
        data = f.read()

    hf = HiTargetFile(path=path)
    if not looks_like_hitarget_raw(data):
        raise ValueError(
            "El archivo no tiene la forma esperada de un .raw de "
            "Hi-Target (encabezado de 86 bytes + registros de 398 "
            "bytes cada uno)."
        )

    n_records = (len(data) - _HEADER_SIZE) // _RECORD_SIZE
    for i in range(n_records):
        base = _HEADER_SIZE + i * _RECORD_SIZE
        rec = data[base:base + _RECORD_SIZE]
        tipo = rec[_OFF_TYPE:_OFF_TYPE + _LEN_TYPE]
        if tipo != _RECORD_TYPE_POINT:
            continue  # "RMV": lectura duplicada/preliminar, ver docstring.

        nombre = _decode_padded_text(rec[_OFF_NAME:_OFF_NAME + _LEN_NAME])
        if not nombre:
            hf.warnings.append(f"Registro {i}: sin nombre de punto, se omite.")
            continue

        try:
            lat_rad = struct.unpack_from(">d", rec, _OFF_LAT_RAD)[0]
            lon_rad = struct.unpack_from(">d", rec, _OFF_LON_RAD)[0]
            altura = struct.unpack_from(">d", rec, _OFF_HEIGHT)[0]
        except struct.error:
            hf.warnings.append(f"Registro {i} ('{nombre}'): no se pudo leer lat/lon/altura.")
            continue

        if not (_LAT_RAD_RANGE[0] <= lat_rad <= _LAT_RAD_RANGE[1]) or \
           not (_LON_RAD_RANGE[0] <= lon_rad <= _LON_RAD_RANGE[1]):
            hf.warnings.append(f"Registro {i} ('{nombre}'): latitud/longitud fuera de rango, se omite.")
            continue

        desc = _decode_padded_text(rec[_OFF_DESC:_OFF_DESC + _LEN_DESC])

        hf.points.append(HiTargetPoint(
            row_id=str(i),
            name=nombre,
            lat=math.degrees(lat_rad),
            lon=math.degrees(lon_rad),
            height=altura,
            # Ver el docstring del módulo: la altura de antena no está
            # presente en el .raw, sólo la agrega el CSV al exportar.
            ant_height=None,
            # El estado de solución (RTK Fijo/Fix/Flotante/Cálculo) del
            # CSV tampoco se encontró en el .raw -- se deja vacío
            # (`modo_texto` en gnsseismic_windows.py ya maneja Estado=""
            # con un texto genérico "RTK Hi-Target", igual que si viniera
            # de un .dc/.rw5 sin ese dato).
            estado="",
            desc=desc,
            is_base=(desc.strip().lower() == "set_base"),
            line_no=i,
        ))

    # Igual que la segunda pasada de `hitarget_parser.parse_hitarget_csv`:
    # a cada punto no-base se le calcula la distancia (línea base) a la
    # ocupación de base más cercana DEL MISMO ARCHIVO. A diferencia del
    # CSV (que trae una columna "Base B"/"Base L" propia por fila), el
    # .raw no la tiene, así que aquí se usa directamente la ocupación de
    # base más cercana en vez de exigir que coincida con una referencia
    # ya grabada -- sigue siendo la misma fórmula de distancia
    # (`_haversine_m`) ya usada y probada para el CSV.
    bases = [p for p in hf.points if p.is_base]
    if bases:
        for p in hf.points:
            if p.is_base:
                continue
            mejor_base = min(bases, key=lambda b: _haversine_m(p.lat, p.lon, b.lat, b.lon))
            dist = _haversine_m(p.lat, p.lon, mejor_base.lat, mejor_base.lon)
            p.base_lat, p.base_lon = mejor_base.lat, mejor_base.lon
            p.base_baseline_m = math.hypot(dist, p.height - mejor_base.height)
            p.base_station_name = mejor_base.name

    dup = hf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        hf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplos})."
        )
    return hf
