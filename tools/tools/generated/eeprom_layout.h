// AUTO-GENERATED. Do not edit by hand.
#pragma once

#include <cstddef>
#include <cstdint>

namespace eeprom {

enum class DeviceType : std::uint16_t {
    AIRDOS04 = 0,
    BATDATUNIT01 = 1,
    LABDOS01 = 2,
};

// Packed, little-endian layout. CRC32 covers the whole blob with the crc32
// field zeroed.
struct __attribute__((packed)) EepromRecord {
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
};

constexpr std::size_t EepromRecordSize = sizeof(EepromRecord);
static_assert(EepromRecordSize == 53, "EEPROM layout size mismatch");

} // namespace eeprom
