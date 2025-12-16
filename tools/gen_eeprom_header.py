#!/usr/bin/env python3
"""Generate a packed C++ header for the EEPROM layout.

Usage:
    python tools/gen_eeprom_header.py --out tools/generated/eeprom_layout.h
"""
from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent

from dosview.eeprom_schema import DeviceType, TOTAL_SIZE

HEADER_TEMPLATE = """// AUTO-GENERATED. Do not edit by hand.
#pragma once

#include <cstddef>
#include <cstdint>

namespace eeprom {{

enum class DeviceType : std::uint16_t {{
{device_enum}
}};

// Packed, little-endian layout. CRC32 covers the whole blob with the crc32
// field zeroed.
struct __attribute__((packed)) EepromRecord {{
    std::uint16_t format_version;
    std::uint16_t device_type;
    std::uint32_t crc32;
    std::uint8_t  hw_rev_major;
    std::uint8_t  hw_rev_minor;
    char          device_id[10];
    std::uint32_t config_flags;
    std::uint8_t  rtc_flags;
    std::uint32_t rtc_triplets[15]; // 5× (ts_init, ts_ref, rtc_value)
    float         calib[3];
    std::uint32_t calib_ts;
}};

constexpr std::size_t EepromRecordSize = sizeof(EepromRecord);
static_assert(EepromRecordSize == {size}, "EEPROM layout size mismatch");

}} // namespace eeprom
"""


def render_enum() -> str:
    return "\n".join(
        f"    {member.name} = {int(member)}," for member in DeviceType
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate EEPROM C++ header")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tools/generated/eeprom_layout.h"),
        help="Output header path",
    )
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    header = HEADER_TEMPLATE.format(device_enum=render_enum(), size=TOTAL_SIZE)
    args.out.write_text(header)
    print(f"Wrote {args.out} ({args.out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
