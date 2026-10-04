# -*- coding: utf-8 -*-
"""
surpad_parser.py
-----------------
Lector de los archivos de campo de la app SurPad (usada con receptores de
varias marcas, p.ej. eSurvey/E300): el .rw5 (dialecto "surpad" de
`chcnav_parser.py`, LA/LN en DD.MMSSssss) y el .raw (este módulo).

El .raw de SurPad -- VERIFICADO contra un archivo real del usuario
(`LASUIZA.raw`, 1230 puntos de campo + 8 ocupaciones de base, codificado
en Windows-1252) y contra el .rw5 del mismo trabajo -- es un archivo de
texto por registros separados por comas (mismo estilo que el .rw5:
código de registro + campos de 2 letras pegados a su valor), pero con
las coordenadas en GRADOS DECIMALES con todos sus dígitos (a diferencia
del .rw5), por lo que es la fuente más fiable: sus posiciones 'EP' y
alturas 'HT' coinciden con los N/E/EL de la grilla local ('GS') de cada
punto a < 0.1 mm en los 1230 puntos, y no sufre del problema de
compensación de inclinación que afecta ~22 puntos del .rw5.

Secuencia de registros de un punto levantado (la posición completa del
punto sólo se conoce al llegar al 'GS' final, por eso se acumula en un
bloque "pendiente"):

    --GNSS Statistics RT: ...,SVMin=11,...   (satélites mínimos)
    AH,DC2,MA1.800,ME0,RA1.825              (altura de antena del rover)
    EP,TM10:39:24.000,LA<dec>,LN<dec>,HT<h>,RH..,RN..,RE..,RV..,DH<PDOP>,DV<VDOP>,GM4,CL1
    HCDP,DOP 1.2000,DIF 4
    HCRV,HCTM2026Y09M02D10H39M21S---2026Y09M02D10H39M24S,RVWB..,RVWL..,RVWH..,DRTM4,EPCH2,NGPS0,NGNS0,NALL12
    BL,DCROVER,PN1,DX..,DY..,DZ..,--RS,GM4,...
    GS,PN1,N ..,E ..,EL..,--TN              (nombre + sufijo de tipo)

Otros registros: 'BP' (ocupación de base, con 'PN'/'LA'/'LN'/'HT' y
nombre repetido entre ocupaciones -- ver
`chcnav_parser.asignar_bases_vigentes`), 'AP' (re-volcado de los puntos
al final del archivo, se ignora), 'JB'/'MO'/'CS'/'ES'/'HCAT'/'HCBS'/'CV'
(informativos). Mapeos: GM4 = FIJO ("FIXED"), GM3 = FLOTANTE ("FLOAT"),
GM2 = autónomo; 'DH' = PDOP y 'DV' = VDOP (HDOP no viene en el .raw);
'EPCH' = épocas. La fecha sale de 'HCTM' y se guarda como MM-DD-YYYY
(igual que el .rw5 de SurPad). El modelo/serie del receptor salen del
comentario "--Gnss Device: Model=...,Serial=...".

Devuelve los mismos `ChcnavFile`/`ChcnavPoint` que `chcnav_parser`, así
que el resto del plugin (previsualización, subida a POSTPLOT, corrección
de base) los trata por duck-typing, sin cambios.

Lógica pura, sin QGIS/PyQt.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

try:  # pragma: no cover - depende de si se importa como paquete o suelto
    from . import chcnav_parser
    from .chcnav_parser import ChcnavFile, ChcnavPoint
except ImportError:
    import chcnav_parser
    from chcnav_parser import ChcnavFile, ChcnavPoint

DIALECT_SURPAD_RAW = "surpad_raw"

_DEVICE_RE = re.compile(r"Model=([^,]+),\s*Serial=([^,\s]+)", re.IGNORECASE)
_SVMIN_RE = re.compile(r"SVMin=(\d+)")
_HCRV_TM_RE = re.compile(r"HCTM(\d{4})Y(\d{2})M(\d{2})D(\d{2})H(\d{2})M(\d{2})S")
_EPCH_RE = re.compile(r"EPCH(\d+)")
_NALL_RE = re.compile(r"NALL(\d+)")
_HCDP_RE = re.compile(r"^HCDP,\s*DOP\s*([\d.]+)", re.IGNORECASE)

_GM_STATUS = {"4": "FIXED", "3": "FLOAT", "2": "AUTONOMOUS", "1": "AUTONOMOUS"}


def looks_like_surpad_raw(text: str) -> bool:
    """True si `text` parece un .raw de SurPad: registro 'JB,', al menos
    un 'EP,' (posición de un punto) y ningún registro 'GPS,' (que
    delataría un .rw5)."""
    if not text:
        return False
    has_jb = has_ep = False
    for raw in text.splitlines():
        s = raw.lstrip()
        if s.startswith("GPS,"):
            return False
        if s.startswith("JB,"):
            has_jb = True
        elif s.startswith("EP,"):
            has_ep = True
    return has_jb and has_ep


def parse_surpad_raw_text(text: str, path: str = "") -> ChcnavFile:
    cf = ChcnavFile(path=path, dialect=DIALECT_SURPAD_RAW, coord_format="decimal")
    pend: Dict[str, object] = {}
    receiver_type: Optional[str] = None
    receiver_sn: Optional[str] = None
    ant_height: Optional[float] = None
    n_bases = 0
    n_sin_gs = 0

    for i, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("--"):
            m = _DEVICE_RE.search(line)
            if m and receiver_type is None:
                receiver_type, receiver_sn = m.group(1).strip(), m.group(2).strip()
            elif line.startswith("--GNSS Statistics RT"):
                m = _SVMIN_RE.search(line)
                if m:
                    pend["svmin"] = int(m.group(1))
            continue

        code = line.split(",", 1)[0].strip().upper()
        if code == "AH":
            parsed = chcnav_parser._split_rw5_record(line)
            if parsed and parsed[1].get("DC", "").strip() == "2":
                ra = chcnav_parser._parse_float(parsed[1].get("RA"))
                if ra is not None:
                    ant_height = ra
        elif code == "EP":
            parsed = chcnav_parser._split_rw5_record(line)
            if not parsed:
                continue
            f = parsed[1]
            lat = chcnav_parser._parse_float(f.get("LA"))
            lon = chcnav_parser._parse_float(f.get("LN"))
            ht = chcnav_parser._parse_float(f.get("HT"))
            if lat is None or lon is None or ht is None:
                cf.warnings.append(f"Línea {i + 1}: registro EP incompleto (falta LA/LN/HT), se omite.")
                pend.clear()
                continue
            tm = (f.get("TM") or "").strip()
            if "." in tm:
                tm = tm.split(".", 1)[0]
            pend.update(
                line_no=i + 1, lat=lat, lon=lon, ht=ht, time=tm or None,
                pdop=chcnav_parser._parse_float(f.get("DH")),
                vdop=chcnav_parser._parse_float(f.get("DV")),
                gm=(f.get("GM") or "").strip(), ant=ant_height,
            )
        elif code == "HCDP":
            m = _HCDP_RE.match(line)
            if m and pend.get("pdop") is None:
                pend["pdop"] = chcnav_parser._parse_float(m.group(1))
        elif code == "HCRV":
            m = _HCRV_TM_RE.search(line)
            if m:
                y, mo, d = m.group(1), m.group(2), m.group(3)
                pend["date"] = f"{mo}-{d}-{y}"
            m = _EPCH_RE.search(line)
            if m:
                pend["epochs"] = int(m.group(1))
            m = _NALL_RE.search(line)
            if m:
                pend["nall"] = int(m.group(1))
        elif code == "GS":
            if "lat" not in pend:
                continue  # GS de una base: no es un punto de campo
            parsed = chcnav_parser._split_rw5_record(line)
            name = ((parsed[1].get("PN") if parsed else "") or "").strip()
            suffix = (parsed[2] if parsed else None) or ""
            if not name:
                n_sin_gs += 1
                pend.clear()
                continue
            nsats = pend.get("svmin")
            if nsats is None:
                nsats = pend.get("nall")
            cf.points.append(ChcnavPoint(
                name=name, lat=pend["lat"], lon=pend["lon"], height=pend["ht"],
                tipo=suffix.strip(), line_no=pend["line_no"],
                status=_GM_STATUS.get(str(pend.get("gm"))),
                n_sats=nsats, pdop=pend.get("pdop"), hdop=None, vdop=pend.get("vdop"),
                n_epochs=pend.get("epochs"), date_text=pend.get("date"),
                time_text=pend.get("time"), ant_height=pend.get("ant"),
                receiver_type=receiver_type, receiver_sn=receiver_sn,
            ))
            pend.clear()
        elif code == "BP":
            parsed = chcnav_parser._split_rw5_record(line)
            if not parsed:
                continue
            f = parsed[1]
            lat = chcnav_parser._parse_float(f.get("LA"))
            lon = chcnav_parser._parse_float(f.get("LN"))
            ht = chcnav_parser._parse_float(f.get("HT"))
            if lat is None or lon is None or ht is None:
                cf.warnings.append(f"Línea {i + 1}: registro BP sin LA/LN/HT completos, se omite.")
                continue
            n_bases += 1
            name = (f.get("PN") or "").strip() or f"BASE{n_bases}"
            cf.points.append(ChcnavPoint(
                name=name, lat=lat, lon=lon, height=ht, tipo="BASE",
                line_no=i + 1, is_base=True,
                receiver_type=receiver_type, receiver_sn=receiver_sn,
            ))
            pend.clear()

    cf.receiver_type, cf.receiver_sn = receiver_type, receiver_sn
    # El modelo/serie aparece en el encabezado, DESPUÉS de crearse nada:
    # se completa en los puntos por si el comentario venía más abajo.
    for p in cf.points:
        if p.receiver_type is None:
            p.receiver_type, p.receiver_sn = receiver_type, receiver_sn
    if n_sin_gs:
        cf.warnings.append(f"{n_sin_gs} punto(s) sin nombre en el registro GS, omitido(s).")
    chcnav_parser.asignar_bases_vigentes(cf, colapsar_bases_repetidas=True)
    dup = cf.duplicated_names()
    if dup:
        ejemplos = ", ".join(list(dup.keys())[:5])
        cf.warnings.append(
            f"{len(dup)} nombre(s) de punto repetido(s) en el archivo (ej: {ejemplos})."
        )
    return cf


def parse_surpad_file(path: str, encoding: Optional[str] = None) -> ChcnavFile:
    """Lee un archivo de SurPad (.rw5 o .raw): el formato se decide por
    el CONTENIDO (un .raw trae registros 'EP,' y ningún 'GPS,'); si el
    contenido no se reconoce como ninguno de los dos, se lanza
    ValueError."""
    text = chcnav_parser.leer_texto_con_fallback(path, encoding)
    if looks_like_surpad_raw(text):
        return parse_surpad_raw_text(text, path=path)
    if chcnav_parser.looks_like_rw5(text):
        return chcnav_parser.parse_rw5_text(
            text, path=path, dialect=chcnav_parser.DIALECT_SURPAD
        )
    raise ValueError(
        "El archivo no parece un .rw5 ni un .raw de SurPad (no se encontraron "
        "registros 'GPS' ni 'EP')."
    )
