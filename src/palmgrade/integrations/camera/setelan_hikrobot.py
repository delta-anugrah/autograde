"""Read the camera settings nodes (`domain/setelan_kamera.SETELAN_KAMERA`) through the Hikrobot SDK.

Called only on the capture thread under `state.lock` (rule 3), through the command queue. A node the camera
refuses becomes one row with its SDK code (logged here, never shown on screen); the others still read.
"""

from __future__ import annotations

import logging
from typing import Any

from ...domain.setelan_kamera import ENUM, FLOAT, INT, SETELAN_KAMERA, NilaiSetelan, NodeSetelan
from .mvs_error import format_mvs_ret

logger = logging.getLogger(__name__)


def baca_setelan_hikrobot(cam: Any) -> list[NilaiSetelan]:
    from MvImport.MvCameraControl_class import (  # type: ignore
        MVCC_ENUMENTRY,
        MVCC_ENUMVALUE,
        MVCC_FLOATVALUE,
        MVCC_INTVALUE_EX,
    )

    sdk = {FLOAT: MVCC_FLOATVALUE, INT: MVCC_INTVALUE_EX, ENUM: (MVCC_ENUMVALUE, MVCC_ENUMENTRY)}
    return [_baca_satu(cam, node, sdk) for node in SETELAN_KAMERA]


def _baca_satu(cam: Any, node: NodeSetelan, sdk: dict) -> NilaiSetelan:
    if node.jenis == FLOAT:
        v = sdk[FLOAT]()
        ret = cam.MV_CC_GetFloatValue(node.node, v)
        if ret == 0:
            return NilaiSetelan(node.kunci, float(v.fCurValue), float(v.fMin), float(v.fMax))
    elif node.jenis == INT:
        v = sdk[INT]()
        ret = cam.MV_CC_GetIntValueEx(node.node, v)
        if ret == 0:
            return NilaiSetelan(node.kunci, int(v.nCurValue), int(v.nMin), int(v.nMax), int(v.nInc))
    else:
        jenis_nilai, jenis_entri = sdk[ENUM]
        v = jenis_nilai()
        ret = cam.MV_CC_GetEnumValue(node.node, v)
        if ret == 0:
            pilihan = tuple(
                _simbol(cam, node.node, jenis_entri, v.nSupportValue[i]) for i in range(v.nSupportedNum)
            )
            return NilaiSetelan(node.kunci, _simbol(cam, node.node, jenis_entri, v.nCurValue), pilihan=pilihan)
    kode = format_mvs_ret(ret)
    logger.info("Camera refused setting %s (%s); the console shows it as not supported", node.node, kode)
    return NilaiSetelan(node.kunci, None, kode_galat=kode)


def _simbol(cam: Any, node: str, jenis_entri: type, nilai: int) -> str:
    """The enum entry's name ("Continuous"); its number as text when the camera will not name it."""
    entri = jenis_entri()
    entri.nValue = nilai
    if cam.MV_CC_GetEnumEntrySymbolic(node, entri) == 0:
        return bytes(entri.chSymbolic).split(b"\0", 1)[0].decode("ascii", errors="ignore")
    return str(nilai)
