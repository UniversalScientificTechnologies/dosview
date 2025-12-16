"""EEPROM layout schema, packing/unpacking, and CRC helpers.

This is the single source of truth for both Python handling and the C++
header generator. Packing uses little-endian, packed layout (no padding).
"""
from __future__ import annotations

import enum
import struct
import zlib
from dataclasses import dataclass
from typing import Iterable, Tuple


class DeviceType(enum.IntEnum):
    AIRDOS04 = 0
    BATDATUNIT01 = 1
    LABDOS01 = 2


# Little-endian, packed, no padding. Calib uses float (4 bytes) for MCU
# compatibility.
# RTC: init_time, sync_time, sync_rtc_seconds (3× uint32)
STRUCT_FORMAT = "<HHIBB10sIB3I3fI"
STRUCT = struct.Struct(STRUCT_FORMAT)
CRC_OFFSET = 4  # offset where the CRC32 field starts
CRC_SIZE = 4
TOTAL_SIZE = STRUCT.size


@dataclass
class EepromRecord:
    format_version: int = 0
    device_type: DeviceType = DeviceType.AIRDOS04
    crc32: int = 0
    hw_rev_major: int = 0
    hw_rev_minor: int = 0
    device_id: str = ""
    config_flags: int = 0
    rtc_flags: int = 0
    # RTC synchronization fields
    init_time: int = 0           # Unix timestamp (s) kdy RTC čítač byl na 0
    sync_time: int = 0           # Unix timestamp (s) poslední synchronizace
    sync_rtc_seconds: int = 0    # Hodnota RTC čítače (s) při synchronizaci
    calib: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    calib_ts: int = 0

    def to_dict(self) -> dict:
        """Převede záznam na slovník pro JSON zobrazení."""
        import datetime
        
        # RTC synchronizační data
        init_time_str = None
        if self.init_time > 0:
            try:
                init_time_str = datetime.datetime.fromtimestamp(self.init_time, tz=datetime.timezone.utc).isoformat()
            except (OSError, ValueError):
                pass
        
        sync_time_str = None
        if self.sync_time > 0:
            try:
                sync_time_str = datetime.datetime.fromtimestamp(self.sync_time, tz=datetime.timezone.utc).isoformat()
            except (OSError, ValueError):
                pass
        
        # Kalibrace timestamp
        calib_time = None
        if self.calib_ts > 0:
            try:
                calib_time = datetime.datetime.fromtimestamp(self.calib_ts, tz=datetime.timezone.utc).isoformat()
            except (OSError, ValueError):
                pass
        
        return {
            'format_version': self.format_version,
            'device_type': self.device_type.name if isinstance(self.device_type, DeviceType) else str(self.device_type),
            'crc32': f"0x{self.crc32:08X}",
            'hw_revision': f"{self.hw_rev_major}.{self.hw_rev_minor}",
            'device_id': self.device_id,
            'config_flags': f"0x{self.config_flags:08X}",
            'rtc_flags': f"0x{self.rtc_flags:02X}",
            'rtc_sync': {
                'init_time': self.init_time,
                'init_time_str': init_time_str,
                'sync_time': self.sync_time,
                'sync_time_str': sync_time_str,
                'sync_rtc_seconds': self.sync_rtc_seconds,
            },
            'calibration': {
                'a0': self.calib[0],
                'a1': self.calib[1],
                'a2': self.calib[2],
                'timestamp': self.calib_ts,
                'time': calib_time,
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
        unpacked = STRUCT.unpack_from(blob)
        device_id_bytes = unpacked[5]
        # RTC sync fields: index 8, 9, 10
        init_time = unpacked[8]
        sync_time = unpacked[9]
        sync_rtc_seconds = unpacked[10]
        # Calib: index 11, 12, 13
        calib_values = unpacked[11:14]
        record = cls(
            format_version=unpacked[0],
            device_type=DeviceType(unpacked[1]),
            crc32=unpacked[2],
            hw_rev_major=unpacked[3],
            hw_rev_minor=unpacked[4],
            device_id=_decode_device_id(device_id_bytes),
            config_flags=unpacked[6],
            rtc_flags=unpacked[7],
            init_time=init_time,
            sync_time=sync_time,
            sync_rtc_seconds=sync_rtc_seconds,
            calib=tuple(calib_values),
            calib_ts=unpacked[14],
        )
        if verify_crc:
            expected = compute_crc32(blob)
            if expected != record.crc32:
                raise ValueError(
                    f"CRC mismatch: stored=0x{record.crc32:08X}, computed=0x{expected:08X}"
                )
        return record


def compute_crc32(blob: bytes) -> int:
    """Compute CRC32 (IEEE) over the blob with the CRC field zeroed."""
    masked = _mask_crc(blob)
    return zlib.crc32(masked, 0xFFFFFFFF) ^ 0xFFFFFFFF


def _mask_crc(blob: bytes) -> bytes:
    return blob[:CRC_OFFSET] + b"\x00" * CRC_SIZE + blob[CRC_OFFSET + CRC_SIZE :]


def _inject_crc(blob: bytes, crc: int) -> bytes:
    return (
        blob[:CRC_OFFSET]
        + int(crc & 0xFFFFFFFF).to_bytes(4, byteorder="little")
        + blob[CRC_OFFSET + CRC_SIZE :]
    )


def _encode_device_id(device_id: str) -> bytes:
    raw = (device_id or "").encode("ascii", errors="ignore")[:10]
    return raw.ljust(10, b"\x00")


def _decode_device_id(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="ignore")


def _normalize_calib(calib: Iterable[float]) -> Tuple[float, float, float]:
    values = list(calib)[:3]
    if len(values) < 3:
        values.extend([0.0] * (3 - len(values)))
    return tuple(float(v) for v in values)


def _pack_payload(record: EepromRecord, crc_override: int) -> bytes:
    calib_values = _normalize_calib(record.calib)
    device_id_bytes = _encode_device_id(record.device_id)
    return STRUCT.pack(
        int(record.format_version) & 0xFFFF,
        int(record.device_type) & 0xFFFF,
        int(crc_override) & 0xFFFFFFFF,
        int(record.hw_rev_major) & 0xFF,
        int(record.hw_rev_minor) & 0xFF,
        device_id_bytes,
        int(record.config_flags) & 0xFFFFFFFF,
        int(record.rtc_flags) & 0xFF,
        int(record.init_time) & 0xFFFFFFFF,
        int(record.sync_time) & 0xFFFFFFFF,
        int(record.sync_rtc_seconds) & 0xFFFFFFFF,
        *calib_values,
        int(record.calib_ts) & 0xFFFFFFFF,
    )


def pack_record(record: EepromRecord, with_crc: bool = True) -> bytes:
    return record.pack(with_crc=with_crc)


def unpack_record(blob: bytes, verify_crc: bool = False) -> EepromRecord:
    return EepromRecord.unpack(blob, verify_crc=verify_crc)
