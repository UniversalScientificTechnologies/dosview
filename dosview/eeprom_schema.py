"""EEPROM layout schema, packing/unpacking, and CRC helpers.

Device type enum and structure definition are taken from the xDOS-versions
submodule (xDOS-versions/generated/). Packing uses little-endian, packed
layout (no padding) — byte-identical to the C++ DosimeterEeprom struct.
"""
from __future__ import annotations

import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

# Make xDOS-versions/generated importable as a package.
_XDOS_GENERATED = Path(__file__).parent.parent / "xDOS-versions" / "generated"
if str(_XDOS_GENERATED.parent) not in sys.path:
    sys.path.insert(0, str(_XDOS_GENERATED.parent))

from generated import DeviceType, KNOWN_DEVICES, KNOWN_DEVICES_BY_NAME  # noqa: E402

# Re-export so callers that do `from .eeprom_schema import DeviceType` still work.
__all__ = [
    "DeviceType",
    "KNOWN_DEVICES",
    "KNOWN_DEVICES_BY_NAME",
    "EepromRecord",
    "TOTAL_SIZE",
    "CRC_OFFSET",
    "compute_crc32",
    "pack_record",
    "unpack_record",
]

# Little-endian, packed, no padding — mirrors DosimeterEeprom in xDOS-versions.
# Fields in order:
#   format_version (H), device_type (H), crc32 (I),
#   hardware_version.device_version (B), hardware_version.hardware_revision (B),
#   device_identifier (24s),
#   operating_modes (H), rtc_flags (B),
#   rtc_history[5] × 3 × uint32 (15I),
#   calibration_constants[3] (3f), calibration_version (I)
STRUCT_FORMAT = "<HHIBB24sHB15I3fI"
STRUCT = struct.Struct(STRUCT_FORMAT)
CRC_OFFSET = 4   # byte offset of the crc32 field
CRC_SIZE = 4
TOTAL_SIZE = STRUCT.size  # 113 bytes


@dataclass
class EepromRecord:
    format_version: int = 0
    device_type: DeviceType = DeviceType.AIRDOS
    crc32: int = 0
    device_version: int = 0
    hardware_revision: int = 0
    device_identifier: str = ""
    operating_modes: int = 0
    rtc_flags: int = 0
    # 5 RTC history entries, each (rtc_initialization_timestamp, reference_timestamp,
    # rtc_value_at_reference_timestamp).  Index 0 is the most recent entry.
    rtc_history: List[Tuple[int, int, int]] = field(
        default_factory=lambda: [(0, 0, 0)] * 5
    )
    calibration_constants: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    calibration_version: int = 0

    def to_dict(self) -> dict:
        import datetime

        def _ts(ts: int):
            if ts <= 0:
                return None
            try:
                return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
            except (OSError, ValueError):
                return None

        rtc_entries = []
        for init_ts, ref_ts, rtc_val in self.rtc_history:
            rtc_entries.append({
                "rtc_initialization_timestamp": init_ts,
                "rtc_initialization_time": _ts(init_ts),
                "reference_timestamp": ref_ts,
                "reference_time": _ts(ref_ts),
                "rtc_value_at_reference_timestamp": rtc_val,
            })

        calib_ts = _ts(self.calibration_version)
        return {
            "format_version": self.format_version,
            "device_type": self.device_type.name if isinstance(self.device_type, DeviceType) else str(self.device_type),
            "crc32": f"0x{self.crc32:08X}",
            "hardware_version": {
                "device_version": self.device_version,
                "hardware_revision": self.hardware_revision,
            },
            "device_identifier": self.device_identifier,
            "operating_modes": f"0x{self.operating_modes:04X}",
            "rtc_flags": f"0x{self.rtc_flags:02X}",
            "rtc_history": rtc_entries,
            "calibration": {
                "a0": self.calibration_constants[0],
                "a1": self.calibration_constants[1],
                "a2": self.calibration_constants[2],
                "calibration_version": self.calibration_version,
                "time": calib_ts,
            },
        }

    def pack(self, with_crc: bool = True) -> bytes:
        payload = _pack_payload(self, crc_override=0)
        if with_crc:
            crc = compute_crc32(payload)
            payload = _inject_crc(payload, crc)
        return payload

    @classmethod
    def unpack(cls, blob: bytes, verify_crc: bool = False) -> "EepromRecord":
        if len(blob) < TOTAL_SIZE:
            raise ValueError(f"Blob too short: {len(blob)} < {TOTAL_SIZE}")
        u = STRUCT.unpack_from(blob)
        # u indices:
        # 0=format_version, 1=device_type, 2=crc32,
        # 3=device_version, 4=hardware_revision, 5=device_identifier,
        # 6=operating_modes, 7=rtc_flags,
        # 8..22 = 15 uint32s for rtc_history (5×3),
        # 23..25 = 3 floats, 26 = calibration_version
        rtc_flat = u[8:23]
        rtc_history = [
            (rtc_flat[i * 3], rtc_flat[i * 3 + 1], rtc_flat[i * 3 + 2])
            for i in range(5)
        ]
        try:
            device_type = DeviceType(u[1])
        except ValueError:
            device_type = u[1]
        record = cls(
            format_version=u[0],
            device_type=device_type,
            crc32=u[2],
            device_version=u[3],
            hardware_revision=u[4],
            device_identifier=u[5].split(b"\x00", 1)[0].decode("ascii", errors="ignore"),
            operating_modes=u[6],
            rtc_flags=u[7],
            rtc_history=rtc_history,
            calibration_constants=(u[23], u[24], u[25]),
            calibration_version=u[26],
        )
        if verify_crc:
            expected = compute_crc32(blob)
            if expected != record.crc32:
                raise ValueError(
                    f"CRC mismatch: stored=0x{record.crc32:08X}, computed=0x{expected:08X}"
                )
        return record


def compute_crc32(blob: bytes) -> int:
    """CRC32 (IEEE) over the blob with the crc32 field zeroed."""
    masked = blob[:CRC_OFFSET] + b"\x00" * CRC_SIZE + blob[CRC_OFFSET + CRC_SIZE:]
    return zlib.crc32(masked, 0xFFFFFFFF) ^ 0xFFFFFFFF


def _inject_crc(blob: bytes, crc: int) -> bytes:
    return (
        blob[:CRC_OFFSET]
        + int(crc & 0xFFFFFFFF).to_bytes(4, byteorder="little")
        + blob[CRC_OFFSET + CRC_SIZE:]
    )


def _pack_payload(record: EepromRecord, crc_override: int) -> bytes:
    raw_id = (record.device_identifier or "").encode("ascii", errors="ignore")[:24]
    raw_id = raw_id.ljust(24, b"\x00")

    history = list(record.rtc_history)
    while len(history) < 5:
        history.append((0, 0, 0))
    rtc_flat = []
    for init_ts, ref_ts, rtc_val in history[:5]:
        rtc_flat += [int(init_ts), int(ref_ts), int(rtc_val)]

    calib = list(record.calibration_constants)[:3]
    calib += [0.0] * (3 - len(calib))

    return STRUCT.pack(
        int(record.format_version) & 0xFFFF,
        int(record.device_type) & 0xFFFF,
        int(crc_override) & 0xFFFFFFFF,
        int(record.device_version) & 0xFF,
        int(record.hardware_revision) & 0xFF,
        raw_id,
        int(record.operating_modes) & 0xFFFF,
        int(record.rtc_flags) & 0xFF,
        *rtc_flat,
        *calib,
        int(record.calibration_version) & 0xFFFFFFFF,
    )


def pack_record(record: EepromRecord, with_crc: bool = True) -> bytes:
    return record.pack(with_crc=with_crc)


def unpack_record(blob: bytes, verify_crc: bool = False) -> EepromRecord:
    return EepromRecord.unpack(blob, verify_crc=verify_crc)
