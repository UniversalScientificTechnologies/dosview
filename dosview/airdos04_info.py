#!/usr/bin/env python3
"""CLI nástroj pro vyčtení informací z detektoru AIRDOS04.

Použití:
    python -m dosview.airdos04_info
    # nebo po instalaci:
    airdos04-info
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta

try:
    import hid
except ImportError:
    hid = None

try:
    import ft260
    FT260_I2C = ft260.FT260_I2C
except ImportError:
    ft260 = None
    FT260_I2C = None

from .airdos04 import Airdos04Hardware, Airdos04Addresses


# FT260 USB identifiers
FT260_VID = 0x1209
FT260_PID = 0x7aa0


def find_ft260_device():
    """Najde FT260 HID zařízení."""
    if hid is None:
        print("❌ Modul 'hid' není nainstalován. Nainstalujte: pip install hidapi")
        return None
    
    devices = hid.enumerate(FT260_VID, FT260_PID)
    if not devices:
        print("❌ FT260 zařízení nenalezeno")
        print("   Ujistěte se, že je detektor AIRDOS04 připojen přes USB")
        
        # Zobrazit všechna HID zařízení pro debug
        all_devices = hid.enumerate()
        if all_devices:
            print("\n   Nalezená HID zařízení:")
            for d in all_devices[:10]:  # Omezíme na 10
                vid = d.get('vendor_id', 0)
                pid = d.get('product_id', 0)
                prod = d.get('product_string', 'N/A')
                print(f"     - VID:0x{vid:04X} PID:0x{pid:04X} '{prod}'")
        return None
    
    # Hledáme interface 0 (I2C)
    for dev_info in devices:
        if dev_info.get('interface_number', -1) == 0:
            dev = hid.device()
            dev.open_path(dev_info['path'])
            
            # Inicializace FT260 - I2C reset a nastavení módu
            dev.send_feature_report([0xA1, 0x20])      # I2C reset
            dev.send_feature_report([0xA1, 0x02, 0x01]) # I2C enable
            
            return dev
    
    # Fallback - první zařízení
    dev = hid.device()
    dev.open_path(devices[0]['path'])
    dev.send_feature_report([0xA1, 0x20])
    dev.send_feature_report([0xA1, 0x02, 0x01])
    return dev


def format_time(seconds: float) -> str:
    """Formátuje čas v sekundách na čitelný řetězec."""
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    
    return " ".join(parts)


def print_header(title: str):
    """Vytiskne nadpis sekce."""
    print()
    print(f"{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def print_row(label: str, value, unit: str = ""):
    """Vytiskne řádek s hodnotou."""
    if value is None:
        value_str = "N/A"
    elif isinstance(value, float):
        value_str = f"{value:.2f}"
    else:
        value_str = str(value)
    
    if unit:
        value_str = f"{value_str} {unit}"
    
    print(f"  {label:<30} {value_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Vyčte informace z detektoru AIRDOS04 přes FT260 I2C bridge"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Podrobný výstup"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Výstup ve formátu JSON"
    )
    parser.add_argument(
        "--no-sensors",
        action="store_true",
        help="Přeskočit čtení senzorů (rychlejší)"
    )
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Provést testovací zápis do EEPROM (adresa 0x0100)"
    )
    parser.add_argument(
        "--write-data",
        type=str,
        metavar="HEX",
        help="Zapsat hex data do EEPROM (např. '48454C4C4F' pro 'HELLO')"
    )
    parser.add_argument(
        "--write-addr",
        type=lambda x: int(x, 0),
        default=0x0100,
        metavar="ADDR",
        help="Adresa pro zápis do EEPROM (výchozí: 0x0100)"
    )
    args = parser.parse_args()

    # Kontrola závislostí
    if FT260_I2C is None:
        print("❌ Modul 'ft260' není nainstalován.")
        print("   Nainstalujte: pip install PyFT260")
        sys.exit(1)

    # Připojení k zařízení
    print("🔍 Hledám FT260 zařízení...")
    dev = find_ft260_device()
    if dev is None:
        sys.exit(1)

    try:
        print("✅ FT260 nalezeno, připojuji...")
        ftdi = FT260_I2C(hid_device=dev)
        hw = Airdos04Hardware(ftdi)
        
        # Přepnout I2C směr na USB
        hw.set_i2c_direction(to_usb=True)
        
        # Zpracování zápisu do EEPROM
        if args.write_test or args.write_data:
            write_addr = args.write_addr
            
            if args.write_data:
                # Převod hex stringu na bajty
                try:
                    write_data = bytes.fromhex(args.write_data)
                except ValueError:
                    print(f"❌ Neplatná hex data: {args.write_data}")
                    sys.exit(1)
            else:
                # Testovací data
                write_data = b"AIRDOS04 Test " + bytes([0x00, 0x01, 0x02, 0x03])
            
            print(f"\n📝 Zápis do EEPROM:")
            print(f"   Adresa: 0x{write_addr:04X}")
            print(f"   Délka:  {len(write_data)} bajtů")
            print(f"   Data:   {write_data.hex().upper()}")
            
            # Přečíst původní data
            print(f"\n   Původní data na adrese 0x{write_addr:04X}:")
            original = hw.read_eeprom(len(write_data), start_address=write_addr)
            print(f"   {original.hex().upper()}")
            
            # Zápis
            print(f"\n   Zapisuji...")
            success = hw.write_eeprom(write_data, start_address=write_addr)
            
            if success:
                print(f"   ✅ Zápis úspěšný!")
                # Ověření
                verify = hw.read_eeprom(len(write_data), start_address=write_addr)
                print(f"   Ověření: {verify.hex().upper()}")
                if verify == write_data:
                    print(f"   ✅ Data ověřena!")
                else:
                    print(f"   ❌ Data se neshodují!")
            else:
                print(f"   ❌ Zápis selhal!")
            
            print()
        
        if args.json:
            # JSON výstup
            import json
            status = hw.get_full_status(include_sensors=not args.no_sensors)
            print(json.dumps(status.to_dict(), indent=2, default=str))
        else:
            # Textový výstup
            print_info(hw, verbose=args.verbose, include_sensors=not args.no_sensors)
        
    except Exception as e:
        print(f"❌ Chyba: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        hw.set_i2c_direction(to_usb=False)
        dev.close()


def print_info(hw: Airdos04Hardware, verbose: bool = False, include_sensors: bool = True):
    """Vytiskne informace o detektoru."""
    
    print()
    print("=" * 50)
    print("       AIRDOS04 Detector Information")
    print("=" * 50)
    
    # ─── Sériová čísla ───
    print_header("📋 Identifikace")
    
    try:
        sn_batdat = hw.read_serial_number_batdatunit()
        print_row("SN BATDATUNIT", sn_batdat)
    except Exception as e:
        print_row("SN BATDATUNIT", f"Chyba: {e}")
    
    try:
        sn_ustsipin = hw.read_serial_number_ustsipin()
        print_row("SN USTSIPIN", sn_ustsipin)
    except Exception as e:
        print_row("SN USTSIPIN", f"Chyba: {e}")

    # ─── RTC / Stopky ───
    print_header("⏱️  RTC (Stopky)")
    
    try:
        rtc = hw.read_rtc()
        total_secs = rtc.elapsed.total_seconds()
        print_row("Celkový čas", format_time(total_secs))
        print_row("Sekundy (raw)", total_secs, "s")
        print_row("Start time", str(rtc.start_time))
        print_row("Aktuální čas", str(rtc.absolute_time))
        if verbose and rtc.raw_registers:
            regs = " ".join(f"{r:02X}" for r in rtc.raw_registers)
            print_row("Raw registry", regs)
    except Exception as e:
        print_row("RTC", f"Chyba: {e}")

    # ─── Baterie ───
    print_header("🔋 Baterie")
    
    try:
        battery = hw.read_battery_status()
        
        # Fuel gauge (MAX17048)
        if battery.voltage:
            # Převod raw hodnoty na V (MAX17048: 78.125µV/LSB)
            voltage_v = battery.voltage * 78.125 / 1000000
            print_row("Napětí (raw)", battery.voltage)
            print_row("Napětí", voltage_v, "V")
        if battery.remaining_capacity:
            print_row("Zbývající kapacita", battery.remaining_capacity)
        if battery.full_capacity:
            print_row("Plná kapacita", battery.full_capacity)
        if battery.temperature:
            print_row("Teplota", battery.temperature)
        if battery.current_avg:
            print_row("Průměrný proud", battery.current_avg)
        if battery.state:
            print_row("Stav", battery.state)
        
        # Charger (BQ25180) ADC values
        if verbose:
            if battery.vbat_adc:
                print_row("VBAT ADC", battery.vbat_adc, "V")
            if battery.vbus_adc:
                print_row("VBUS ADC", battery.vbus_adc, "V")
            if battery.ibat_adc:
                print_row("IBAT ADC", battery.ibat_adc, "mA")
            if battery.tdie_adc:
                print_row("Teplota čipu", battery.tdie_adc, "°C")
            
    except Exception as e:
        print_row("Baterie", f"Chyba: {e}")

    # ─── Senzory ───
    if include_sensors:
        print_header("🌡️  Senzory prostředí")
        
        # SHT senzory
        sht_addresses = [
            ("BATDATUNIT", hw.addr.sht),
            ("USTSIPIN", hw.addr.an_sht),
        ]
        for name, addr in sht_addresses:
            try:
                sht = hw.read_sht(addr)
                label_prefix = f"SHT {name} (0x{addr:02X})"
                print_row(f"{label_prefix} Teplota", sht.temperature, "°C")
                print_row(f"{label_prefix} Vlhkost", sht.humidity, "%RH")
            except Exception as e:
                if verbose:
                    print_row(f"SHT {name} (0x{addr:02X})", f"Chyba: {e}")
        
        # Altimetr MS5611
        try:
            alt = hw.read_altimeter()
            print_row("MS5611 Tlak (raw)", alt.pressure_raw)
            print_row("MS5611 Teplota (raw)", alt.temperature_raw)
            if verbose and alt.calibration_coefficients:
                coeffs = ", ".join(str(c) for c in alt.calibration_coefficients)
                print_row("MS5611 Kalib. koef.", coeffs)
        except Exception as e:
            if verbose:
                print_row("MS5611", f"Chyba: {e}")

    # ─── I2C adresy ───
    if verbose:
        print_header("📍 I2C Adresy (konfigurace)")
        print_row("RTC (PCF8563)", f"0x{hw.addr.rtc:02X}")
        print_row("Charger (BQ25180)", f"0x{hw.addr.charger:02X}")
        print_row("Fuel gauge (MAX17048)", f"0x{hw.addr.gauge:02X}")
        print_row("SHT BATDATUNIT", f"0x{hw.addr.sht:02X}")
        print_row("SHT USTSIPIN", f"0x{hw.addr.an_sht:02X}")
        print_row("MS5611", f"0x{hw.addr.altimet:02X}")
        print_row("I2C Switch", f"0x{hw.addr.switch:02X}")
        print_row("EEPROM data", f"0x{hw.addr.eeprom:02X}")
        print_row("EEPROM SN", f"0x{hw.addr.eeprom_sn:02X}")
        print_row("AN EEPROM data", f"0x{hw.addr.an_eeprom:02X}")
        print_row("AN EEPROM SN", f"0x{hw.addr.an_eeprom_sn:02X}")

    # ─── I2C Scan ───
    if verbose:
        print_header("🔍 I2C Scan")
        try:
            found = hw.scan_i2c_bus()
            if found:
                addrs_str = ", ".join(f"0x{a:02X}" for a in sorted(found))
                print(f"  Nalezená zařízení: {addrs_str}")
            else:
                print("  Žádná zařízení nenalezena")
        except Exception as e:
            print(f"  Chyba při skenování: {e}")

    # ─── EEPROM Dump ───
    if verbose:
        print_header("💾 EEPROM Obsah (prvních 512 bajtů)")
        try:
            eeprom_data = hw.read_eeprom(512, start_address=0)
            # Hexdump formát
            for offset in range(0, len(eeprom_data), 16):
                chunk = eeprom_data[offset:offset+16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                # ASCII část (tisknutelné znaky, jinak '.')
                ascii_part = "".join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                print(f"  {offset:04X}: {hex_part:<48} |{ascii_part}|")
        except Exception as e:
            print(f"  Chyba při čtení EEPROM: {e}")

    print()
    print("=" * 50)
    print("  ✅ Hotovo")
    print("=" * 50)
    print()


if __name__ == "__main__":
    main()
