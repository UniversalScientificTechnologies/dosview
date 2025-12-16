"""
AIRDOS04 Hardware Controller
============================

Qt-nezávislý modul pro ovládání hardware detektoru AIRDOS04 přes I2C.
Podporuje SMBus-kompatibilní rozhraní (např. FT260_I2C, smbus2).

Použití
-------
    from airdos04 import Airdos04Hardware
    
    # i2c_bus = FT260_I2C(...) nebo smbus2.SMBus(...)
    hw = Airdos04Hardware(i2c_bus)
    
    # Vyčtení RTC
    abs_time, elapsed = hw.read_rtc()
    
    # Reset RTC
    hw.reset_rtc()
    
    # Vyčtení senzorů
    status = hw.read_all_sensors()
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple


class I2CBus(Protocol):
    """
    Protokol pro SMBus-kompatibilní I2C rozhraní.
    
    Kompatibilní s:
    - ft260.FT260_I2C
    - smbus2.SMBus
    """
    
    def write_byte(self, address: int, value: int) -> None: ...
    def write_byte_data(self, address: int, register: int, value: int) -> None: ...
    def read_byte_data(self, address: int, register: int) -> int: ...
    def read_word_data(self, address: int, register: int) -> int: ...
    def write_i2c_block(self, address: int, data: List[int]) -> None: ...
    def read_i2c_block(self, address: int, length: int) -> List[int]: ...
    def read_i2c_block_data(self, address: int, register: int, length: int) -> List[int]: ...
    def write_i2c_block_data(self, address: int, register: int, data: List[int]) -> bool: ...


@dataclass
class Airdos04Addresses:
    """I2C adresy jednotlivých komponent AIRDOS04."""
    
    # Hlavní deska (BatDatUnit)
    sht: int = 0x44                 # SHT4x teplotní/vlhkostní senzor
    switch: int = 0x70              # I2C switch (USB/MCU)
    sdcard: int = 0x71              # SD card controller (?)
    charger: int = 0x6A             # BQ25180 nabíječka
    gauge: int = 0x55               # MAX17048 fuel gauge
    rtc: int = 0x51                 # PCF8563 RTC (stopky)
    eeprom: int = 0x50              # AT24CS64 EEPROM data
    eeprom_sn: int = 0x58           # AT24CS64 EEPROM serial number
    altimet: int = 0x77             # MS5611 barometr/výškoměr
    
    # Analogová deska (USTSIPIN)
    an_sht: int = 0x45              # SHT4x na analogové desce
    an_eeprom: int = 0x53           # EEPROM analogové desky
    an_eeprom_sn: int = 0x5B        # EEPROM SN analogové desky


@dataclass
class RTCTime:
    """Struktura pro čas z RTC."""
    absolute_time: datetime.datetime      # Absolutní čas (init_time + elapsed)
    elapsed: datetime.timedelta           # Uplynulý čas z RTC registrů
    start_time: datetime.datetime         # Čas vynulování RTC (init_time)
    
    # Pole s výchozími hodnotami - odpovídají EEPROM struktuře
    init_time: int = 0                    # Unix timestamp kdy RTC bylo na 0
    raw_registers: Tuple[int, ...] = field(default_factory=tuple)  # Surová data z registrů (pro debug)
    sync_time: int = 0                    # Unix timestamp poslední synchronizace
    sync_rtc_seconds: int = 0             # Hodnota RTC v sekundách při synchronizaci


@dataclass
class BatteryStatus:
    """Stav baterie a nabíječky."""
    
    # Nabíječka (BQ25180)
    ibus_adc: float = 0.0       # Vstupní proud [mA]
    ibat_adc: float = 0.0       # Nabíjecí proud [mA]
    vbus_adc: float = 0.0       # Vstupní napětí [V]
    vpmid_adc: float = 0.0      # PMID napětí [V]
    vbat_adc: float = 0.0       # Napětí baterie [V]
    vsys_adc: float = 0.0       # Systémové napětí [V]
    ts_adc: float = 0.0         # Teplota (termistor) [°C]
    tdie_adc: float = 0.0       # Teplota čipu [°C]
    
    # Fuel gauge (MAX17048)
    voltage: int = 0            # Napětí [raw]
    current_avg: int = 0        # Průměrný proud [raw]
    current_now: int = 0        # Okamžitý proud [raw]
    remaining_capacity: int = 0 # Zbývající kapacita [raw]
    full_capacity: int = 0      # Plná kapacita [raw]
    temperature: int = 0        # Teplota [raw]
    state: int = 0              # Stav [raw]


@dataclass
class SHTReading:
    """Čtení z SHT4x senzoru."""
    temperature: float = 0.0    # [°C]
    humidity: float = 0.0       # [%RH]


@dataclass  
class AltimeterReading:
    """Čtení z MS5611 barometru."""
    pressure_raw: int = 0
    temperature_raw: int = 0
    calibration_coefficients: List[int] = field(default_factory=list)


@dataclass
class Airdos04Status:
    """Kompletní stav AIRDOS04 detektoru."""
    
    # Identifikace
    serial_number_batdatunit: str = ""
    serial_number_ustsipin: str = ""
    
    # Čas
    rtc: Optional[RTCTime] = None
    
    # Napájení
    battery: Optional[BatteryStatus] = None
    
    # Senzory
    sht_batdatunit: Optional[SHTReading] = None
    sht_ustsipin: Optional[SHTReading] = None
    altimeter: Optional[AltimeterReading] = None


class Airdos04Hardware:
    """
    Třída pro ovládání hardware AIRDOS04 detektoru přes I2C.
    
    Tato třída je Qt-nezávislá a může být použita samostatně nebo
    jako součást většího systému.
    
    Parameters
    ----------
    i2c_bus : I2CBus
        SMBus-kompatibilní I2C rozhraní (FT260_I2C, smbus2.SMBus, ...)
    addresses : Airdos04Addresses, optional
        Přizpůsobené I2C adresy (výchozí hodnoty pro AIRDOS04)
    switch_callback : callable, optional
        Callback pro přepínání I2C směru (USB/MCU). Signature: (to_usb: bool) -> None
    """
    
    def __init__(
        self,
        i2c_bus: I2CBus,
        addresses: Optional[Airdos04Addresses] = None,
        switch_callback: Optional[Callable[[bool], None]] = None,
    ):
        self.bus = i2c_bus
        self.addr = addresses or Airdos04Addresses()
        self._switch_callback = switch_callback
    
    # =========================================================================
    # I2C Switch Management
    # =========================================================================
    
    def set_i2c_direction(self, to_usb: bool) -> None:
        """
        Přepne I2C switch mezi USB a MCU.
        
        Parameters
        ----------
        to_usb : bool
            True = I2C směřuje k USB (FT260), False = k MCU (ATmega)
        """
        time.sleep(0.05)
        if to_usb:
            # Do USB se přepne tak, že bit[0] a bit[2] mají rozdílné hodnoty
            self.bus.write_byte_data(self.addr.switch, 0x01, 0b011)
        else:
            # I2C do ATMEGA - bit[0] a bit[2] mají stejné hodnoty
            self.bus.write_byte_data(self.addr.switch, 0x01, 0b0000)
        time.sleep(0.05)
        
        if self._switch_callback:
            self._switch_callback(to_usb)
    
    # =========================================================================
    # RTC Operations (PCF8563 ve stopwatch režimu)
    # =========================================================================
    
    def read_rtc_raw(self) -> Tuple[datetime.timedelta, Tuple[int, ...]]:
        """
        Vyčte surový čas z RTC registrů.
        
        Returns
        -------
        Tuple[timedelta, Tuple[int, ...]]
            Uplynulý čas jako timedelta a surové registry.
        """
        # Vyčtení registrů 0x00-0x07
        regs = []
        for reg in range(8):
            regs.append(self.bus.read_byte_data(self.addr.rtc, reg))
        
        # Dekódování BCD hodnot
        r00, r01, r02, r03, r04, r05, r06, r07 = regs
        
        sec100 = (r00 & 0x0F) + ((r00 & 0xF0) >> 4) * 10
        sec = (r01 & 0x0F) + ((r01 & 0x70) >> 4) * 10
        minu = (r02 & 0x0F) + ((r02 & 0x70) >> 4) * 10
        
        # Hodiny jsou rozloženy přes více registrů
        hour = (r03 & 0x0F) + ((r03 & 0xF0) >> 4) * 10
        hour += (r04 & 0x0F) * 100 + ((r04 & 0xF0) >> 4) * 1000
        hour += (r05 & 0x0F) * 10000 + ((r05 & 0xF0) >> 4) * 100000
        
        elapsed = datetime.timedelta(
            hours=hour,
            minutes=minu,
            seconds=sec,
            milliseconds=sec100 * 10
        )
        
        return elapsed, tuple(regs)
    
    def read_rtc(self, eeprom_address: int = None) -> RTCTime:
        """
        Vyčte čas z RTC (PCF8563 ve stopwatch režimu).
        
        Absolutní čas se vypočítá jako init_time + elapsed,
        kde init_time je Unix timestamp kdy bylo RTC na 0 (z EEPROM).
        
        Parameters
        ----------
        eeprom_address : int, optional
            I2C adresa EEPROM (výchozí: addr.eeprom)
        
        Returns
        -------
        RTCTime
            Struktura s absolutním časem, uplynulým časem a startovním časem.
        """
        # Vyčtení RTC registrů
        elapsed, raw_regs = self.read_rtc_raw()
        
        # Vyčtení RTC sync dat z EEPROM
        init_time = 0
        sync_time = 0
        sync_rtc_seconds = 0
        
        try:
            rtc_sync = self.get_rtc_sync_data(eeprom_address)
            if rtc_sync:
                init_time, sync_time, sync_rtc_seconds = rtc_sync
        except Exception:
            # Pokud se nepodaří vyčíst EEPROM, použijeme fallback
            pass
        
        # Výpočet absolutního času
        # Preferujeme sync_time (přesnější kalibrace), fallback na init_time
        reference_time = sync_time if sync_time > 0 else init_time
        
        if reference_time > 0:
            # reference_time je Unix timestamp času kdy RTC bylo na 0
            start_time = datetime.datetime.fromtimestamp(reference_time, tz=datetime.timezone.utc)
            absolute_time = start_time + elapsed
        else:
            # Fallback - použijeme systémový čas
            absolute_time = datetime.datetime.now(datetime.timezone.utc)
            start_time = absolute_time - elapsed
        
        return RTCTime(
            absolute_time=absolute_time,
            elapsed=elapsed,
            start_time=start_time,
            init_time=init_time,
            raw_registers=raw_regs,
            sync_time=sync_time,
            sync_rtc_seconds=sync_rtc_seconds
        )
    
    def get_rtc_sync_data(self, eeprom_address: int = None) -> Optional[Tuple[int, int, int]]:
        """
        Vyčte RTC synchronizační data z EEPROM.
        
        Vrací:
        - init_time: Unix timestamp kdy RTC bylo na 0
        - sync_time: Unix timestamp poslední synchronizace
        - sync_rtc_seconds: Hodnota RTC v sekundách při synchronizaci
        
        Returns
        -------
        Optional[Tuple[int, int, int]]
            (init_time, sync_time, sync_rtc_seconds) nebo None pokud nejsou platná data
        """
        from .eeprom_schema import unpack_record, TOTAL_SIZE
        
        if eeprom_address is None:
            eeprom_address = self.addr.eeprom
        
        try:
            data = self.read_eeprom(TOTAL_SIZE, start_address=0, eeprom_address=eeprom_address)
            record = unpack_record(data, verify_crc=False)
            
            init_time = record.init_time
            sync_time = record.sync_time
            sync_rtc_seconds = record.sync_rtc_seconds
            
            if init_time > 0 or sync_time > 0:
                return (init_time, sync_time, sync_rtc_seconds)
            
            return None
        except Exception:
            return None
    
    def sync_rtc(self, eeprom_address: int = None) -> datetime.datetime:
        """
        Synchronizuje RTC čas se systémovým časem (pouze zápis do EEPROM).
        
        Nemění nic v RTC čipu! Pouze zapíše kalibrační bod do EEPROM:
        - init_time: NEMĚNÍ SE (zůstává původní)
        - sync_time: aktuální timestamp - aktuální RTC hodnota (čas kdy RTC bylo 0)
        - sync_rtc_seconds: aktuální RTC hodnota v sekundách
        
        Parameters
        ----------
        eeprom_address : int, optional
            I2C adresa EEPROM (výchozí: addr.eeprom)
        
        Returns
        -------
        datetime.datetime
            Čas synchronizace (UTC).
        """
        from .eeprom_schema import unpack_record, pack_record, TOTAL_SIZE
        
        if eeprom_address is None:
            eeprom_address = self.addr.eeprom
        
        print("[sync_rtc] Začátek synchronizace RTC")
        
        # Vyčti aktuální RTC hodnotu
        elapsed, _ = self.read_rtc_raw()
        sync_rtc_seconds = int(elapsed.total_seconds())
        print(f"[sync_rtc] RTC elapsed: {elapsed}, v sekundách: {sync_rtc_seconds}")
        
        # Aktuální timestamp
        now = datetime.datetime.now(datetime.timezone.utc)
        current_timestamp = int(now.timestamp())
        print(f"[sync_rtc] Aktuální čas UTC: {now}, timestamp: {current_timestamp}")
        
        # sync_time = čas kdy RTC bylo 0 = aktuální timestamp - RTC hodnota
        sync_time = current_timestamp - sync_rtc_seconds
        print(f"[sync_rtc] Vypočtený sync_time: {sync_time} (UTC: {datetime.datetime.fromtimestamp(sync_time, tz=datetime.timezone.utc)})")
        
        # Vyčti aktuální EEPROM záznam
        try:
            print(f"[sync_rtc] Čtení EEPROM z adresy 0x{eeprom_address:02X}")
            data = self.read_eeprom(TOTAL_SIZE, start_address=0, eeprom_address=eeprom_address)
            print(f"[sync_rtc] EEPROM data vyčteno, velikost: {len(data)} bytů")
            record = unpack_record(data, verify_crc=False)
            print(f"[sync_rtc] init_time (NEMĚNÍ SE): {record.init_time}")
        except Exception as e:
            # Pokud se nepodaří vyčíst, vytvoříme nový záznam
            print(f"[sync_rtc] Chyba při čtení EEPROM: {e}, vytváříme nový záznam")
            from .eeprom_schema import EepromRecord
            record = EepromRecord()
        
        # Aktualizace RTC sync dat (init_time se NEMĚNÍ!)
        record.sync_time = sync_time
        record.sync_rtc_seconds = sync_rtc_seconds
        print(f"[sync_rtc] Záznam aktualizován: sync_time={sync_time}, sync_rtc_seconds={sync_rtc_seconds}")
        
        # Zápis do EEPROM
        print(f"[sync_rtc] Zápis do EEPROM na adresu 0x{eeprom_address:02X}")
        payload = pack_record(record, with_crc=True)
        success = self.write_eeprom(payload, start_address=0, eeprom_address=eeprom_address)
        
        if not success:
            print("[sync_rtc] CHYBA: Nepodařilo se zapsat RTC sync do EEPROM")
            raise IOError("Nepodařilo se zapsat RTC sync do EEPROM")
        
        print(f"[sync_rtc] Synchronizace úspěšná! Čas: {now}")
        return now
    
    def reset_rtc(self, eeprom_address: int = None) -> datetime.datetime:
        """
        Resetuje RTC stopky na nulu a zapíše timestamp do EEPROM.
        
        1. Vynuluje RTC čítač v čipu
        2. Zapíše do EEPROM:
           - init_time: aktuální timestamp (čas vynulování)
           - sync_time: aktuální timestamp (stejný, protože RTC=0)
           - sync_rtc_seconds: 0
        
        Parameters
        ----------
        eeprom_address : int, optional
            I2C adresa EEPROM (výchozí: addr.eeprom)
        
        Returns
        -------
        datetime.datetime
            Čas, kdy byl reset proveden (UTC).
        """
        from .eeprom_schema import unpack_record, pack_record, TOTAL_SIZE
        
        if eeprom_address is None:
            eeprom_address = self.addr.eeprom
        
        reset_time = datetime.datetime.now(datetime.timezone.utc)
        reset_timestamp = int(reset_time.timestamp())
        
        # Vynulování registrů 0x00-0x07 v RTC čipu
        for reg in range(8):
            self.bus.write_byte_data(self.addr.rtc, reg, 0)
        
        # Vyčti aktuální EEPROM záznam
        try:
            data = self.read_eeprom(TOTAL_SIZE, start_address=0, eeprom_address=eeprom_address)
            record = unpack_record(data, verify_crc=False)
        except Exception:
            from .eeprom_schema import EepromRecord
            record = EepromRecord()
        
        # Zápis timestampu resetu do EEPROM
        record.init_time = reset_timestamp
        record.sync_time = reset_timestamp  # Při resetu je RTC=0, takže sync_time = init_time
        record.sync_rtc_seconds = 0
        
        # Zápis do EEPROM
        payload = pack_record(record, with_crc=True)
        success = self.write_eeprom(payload, start_address=0, eeprom_address=eeprom_address)
        
        if not success:
            raise IOError("Nepodařilo se zapsat RTC reset do EEPROM")
        
        return reset_time
    
    def read_rtc_register(self, register: int) -> int:
        """Vyčte jeden registr z RTC."""
        return self.bus.read_byte_data(self.addr.rtc, register)
    
    def write_rtc_register(self, register: int, value: int) -> None:
        """Zapíše jeden registr do RTC."""
        self.bus.write_byte_data(self.addr.rtc, register, value)
    
    # =========================================================================
    # Battery & Charger Operations
    # =========================================================================
    
    def read_battery_status(self) -> BatteryStatus:
        """
        Vyčte stav baterie z nabíječky (BQ25180) a fuel gauge (MAX17048).
        
        Returns
        -------
        BatteryStatus
            Kompletní stav baterie a nabíječky.
        """
        # BQ25180 nabíječka
        ibus_adc = (self.bus.read_byte_data(self.addr.charger, 0x28) >> 1) * 2
        ibat_adc = (self.bus.read_byte_data(self.addr.charger, 0x2A) >> 2) * 4
        vbus_adc = (self.bus.read_byte_data(self.addr.charger, 0x2C) >> 2) * 3.97 / 1000
        vpmid_adc = (self.bus.read_byte_data(self.addr.charger, 0x2E) >> 2) * 3.97 / 1000
        vbat_adc = (self.bus.read_word_data(self.addr.charger, 0x30) >> 1) * 1.99 / 1000
        vsys_adc = (self.bus.read_word_data(self.addr.charger, 0x32) >> 1) * 1.99 / 1000
        ts_adc = (self.bus.read_word_data(self.addr.charger, 0x34) >> 0) * 0.0961
        tdie_adc = (self.bus.read_word_data(self.addr.charger, 0x36) >> 0) * 0.5
        
        # MAX17048 fuel gauge
        g_voltage = self.bus.read_word_data(self.addr.gauge, 0x08)
        g_cur_avg = self.bus.read_word_data(self.addr.gauge, 0x0A)
        g_cur_now = self.bus.read_word_data(self.addr.gauge, 0x10)
        g_rem_cap = self.bus.read_word_data(self.addr.gauge, 0x04)
        g_ful_cap = self.bus.read_word_data(self.addr.gauge, 0x06)
        g_temp = self.bus.read_word_data(self.addr.gauge, 0x0C)
        g_state = self.bus.read_word_data(self.addr.gauge, 0x02)
        
        return BatteryStatus(
            ibus_adc=ibus_adc,
            ibat_adc=ibat_adc,
            vbus_adc=vbus_adc,
            vpmid_adc=vpmid_adc,
            vbat_adc=vbat_adc,
            vsys_adc=vsys_adc,
            ts_adc=ts_adc,
            tdie_adc=tdie_adc,
            voltage=g_voltage,
            current_avg=g_cur_avg,
            current_now=g_cur_now,
            remaining_capacity=g_rem_cap,
            full_capacity=g_ful_cap,
            temperature=g_temp,
            state=g_state,
        )
    
    def set_charger_config(self, register: int, value: int) -> None:
        """Nastaví konfigurační registr nabíječky."""
        self.bus.write_byte_data(self.addr.charger, register, value)
    
    def enable_charging(self) -> None:
        """Povolí nabíjení (výchozí konfigurace)."""
        self.bus.write_byte_data(self.addr.charger, 0x18, 0b00011000)
    
    def disable_charging_and_poweroff(self) -> None:
        """Zakáže nabíjení a vypne napájení."""
        self.bus.write_byte_data(self.addr.charger, 0x18, 0b00011010)
    
    # =========================================================================
    # SHT4x Temperature/Humidity Sensor
    # =========================================================================
    
    def read_sht(self, address: int, command: List[int] = None) -> SHTReading:
        """
        Vyčte teplotu a vlhkost z SHT4x senzoru.
        
        Parameters
        ----------
        address : int
            I2C adresa SHT senzoru (0x44 nebo 0x45)
        command : list, optional
            Příkaz pro měření (výchozí: high precision [0x24, 0x0B])
        
        Returns
        -------
        SHTReading
            Teplota a vlhkost.
        """
        if command is None:
            command = [0x24, 0x0B]  # High precision, no heater
        
        # Odeslání příkazu
        self.bus.write_i2c_block(address, command)
        time.sleep(0.02)  # Čekání na měření
        
        # Vyčtení dat (6 bytů: 2B temp + CRC + 2B hum + CRC)
        data = self.bus.read_i2c_block(address, 6)
        
        if len(data) < 6:
            return SHTReading(temperature=0.0, humidity=0.0)
        
        raw_temperature = (data[0] << 8) + data[1]
        raw_humidity = (data[3] << 8) + data[4]
        
        temperature = -45 + 175 * (raw_temperature / 65535.0)
        humidity = 100 * (raw_humidity / 65535.0)
        
        return SHTReading(temperature=temperature, humidity=humidity)
    
    def read_sht_batdatunit(self) -> SHTReading:
        """Vyčte SHT4x na BatDatUnit desce."""
        return self.read_sht(self.addr.sht)
    
    def read_sht_ustsipin(self) -> SHTReading:
        """Vyčte SHT4x na USTSIPIN (analogové) desce."""
        return self.read_sht(self.addr.an_sht)
    
    def read_sht_serial_number(self, address: int) -> int:
        """Vyčte sériové číslo SHT4x senzoru."""
        self.bus.write_i2c_block(address, [0x89])
        time.sleep(0.01)
        data = self.bus.read_i2c_block(address, 6)
        serial_number = (data[0] << 24) | (data[1] << 16) | (data[3] << 8) | data[4]
        return serial_number
    
    # =========================================================================
    # MS5611 Barometer/Altimeter
    # =========================================================================
    
    def read_altimeter(self) -> AltimeterReading:
        """
        Vyčte data z MS5611 barometru/výškoměru.
        
        Returns
        -------
        AltimeterReading
            Tlak, teplota a kalibrační koeficienty.
        """
        # Vyčtení kalibračních koeficientů z PROM
        cal_coefs = []
        for addr in range(0xA0, 0xAE, 2):
            self.bus.write_byte(self.addr.altimet, addr)
            time.sleep(0.1)
            data = self.bus.read_i2c_block(self.addr.altimet, 2)
            time.sleep(0.1)
            if len(data) >= 2:
                coef = (data[0] << 8) | data[1]
                cal_coefs.append(coef)
            else:
                cal_coefs.append(0)
        
        time.sleep(0.2)
        
        # Spuštění konverze tlaku (OSR=4096)
        self.bus.write_byte(self.addr.altimet, 0b01001000)
        time.sleep(0.2)
        self.bus.write_byte(self.addr.altimet, 0)
        time.sleep(0.2)
        pressure_data = self.bus.read_i2c_block(self.addr.altimet, 3)
        if len(pressure_data) < 3:
            pressure_data = (pressure_data + [0, 0, 0])[:3]
        time.sleep(0.2)
        
        # Spuštění konverze teploty (OSR=4096)
        self.bus.write_byte(self.addr.altimet, 0b01011000)
        time.sleep(0.2)
        self.bus.write_byte(self.addr.altimet, 0)
        time.sleep(0.2)
        temp_data = self.bus.read_i2c_block(self.addr.altimet, 3)
        if len(temp_data) < 3:
            temp_data = (temp_data + [0, 0, 0])[:3]
        
        pressure_raw = (int(pressure_data[0]) << 16) | (int(pressure_data[1]) << 8) | int(pressure_data[2])
        temp_raw = (int(temp_data[0]) << 16) | (int(temp_data[1]) << 8) | int(temp_data[2])
        
        return AltimeterReading(
            pressure_raw=pressure_raw,
            temperature_raw=temp_raw,
            calibration_coefficients=cal_coefs
        )
    
    # =========================================================================
    # EEPROM Operations
    # =========================================================================
    
    def read_serial_number(self, eeprom_sn_address: int = None) -> int:
        """
        Vyčte sériové číslo z EEPROM (AT24CS64).
        
        AT24CS64 má 128-bit SN na speciální adrese 0x0800.
        Čtení vyžaduje 2-byte word address (MSB first).
        
        Parameters
        ----------
        eeprom_sn_address : int, optional
            Adresa SN EEPROM (výchozí: addr.eeprom_sn = 0x58)
        
        Returns
        -------
        int
            Sériové číslo jako 128-bit integer.
        """
        if eeprom_sn_address is None:
            eeprom_sn_address = self.addr.eeprom_sn
        
        # Nastavení word address 0x0800 (MSB first: 0x08, 0x00)
        self.bus.write_i2c_block(eeprom_sn_address, [0x08, 0x00])
        
        # Čtení 16 bajtů SN
        data = self.bus.read_i2c_block(eeprom_sn_address, 16)
        
        result = 0
        for byte in data:
            result = (result << 8) | byte
        
        return result
    
    def read_serial_number_hex(self, eeprom_sn_address: int = None) -> str:
        """Vyčte sériové číslo jako hex string."""
        return hex(self.read_serial_number(eeprom_sn_address))
    
    def read_serial_number_batdatunit(self) -> str:
        """Vyčte SN hlavní desky (BatDatUnit)."""
        return self.read_serial_number_hex(self.addr.eeprom_sn)
    
    def read_serial_number_ustsipin(self) -> str:
        """Vyčte SN analogové desky (USTSIPIN)."""
        return self.read_serial_number_hex(self.addr.an_eeprom_sn)
    
    def read_eeprom(
        self,
        length: int,
        start_address: int = 0,
        eeprom_address: int = None
    ) -> bytes:
        """
        Vyčte data z EEPROM.
        
        Parameters
        ----------
        length : int
            Počet bytů k vyčtení.
        start_address : int
            Počáteční adresa v EEPROM (2-byte word address).
        eeprom_address : int, optional
            I2C adresa EEPROM (výchozí: addr.eeprom)
        
        Returns
        -------
        bytes
            Vyčtená data.
        """
        if eeprom_address is None:
            eeprom_address = self.addr.eeprom
        
        PAGE_SIZE = 32
        total = bytearray()
        offset = start_address
        
        while len(total) < length:
            to_read = min(PAGE_SIZE, length - len(total))
            # Nastavení pointeru (big-endian pro AT24CS64)
            addr_hi = (offset >> 8) & 0xFF
            addr_lo = offset & 0xFF
            self.bus.write_i2c_block(eeprom_address, [addr_hi, addr_lo])
            chunk = self.bus.read_i2c_block(eeprom_address, to_read)
            if not chunk:
                break
            total.extend(chunk[:to_read])
            offset += len(chunk[:to_read])
        
        return bytes(total)
    
    def write_eeprom(
        self,
        data: bytes,
        start_address: int = 0,
        eeprom_address: int = None,
        max_retries: int = 100,
        verify: bool = True
    ) -> bool:
        """
        Zapíše data do EEPROM AT24CS64.
        
        EEPROM má stránky o velikosti 32 bajtů. Zápis nesmí překročit
        hranici stránky, jinak dojde k zacyklení na začátek stránky.
        
        Parameters
        ----------
        data : bytes
            Data k zápisu.
        start_address : int
            Počáteční adresa v EEPROM (0x0000-0x1FFF).
        eeprom_address : int, optional
            I2C adresa EEPROM (výchozí: addr.eeprom = 0x50)
        max_retries : int
            Maximální počet pokusů pro ACK polling (výchozí: 100).
        verify : bool
            Ověřit zapsaná data zpětným čtením (výchozí: True).
        
        Returns
        -------
        bool
            True pokud zápis proběhl úspěšně.
            
        Notes
        -----
        Po každém zápisu stránky probíhá interní programovací cyklus (~5 ms),
        během kterého EEPROM neodpovídá na I2C. Používáme ACK polling
        pro detekci dokončení.
        
        Příklad
        -------
        >>> hw.write_eeprom(b"Hello World!", start_address=0x100)
        True
        """
        if eeprom_address is None:
            eeprom_address = self.addr.eeprom
        
        PAGE_SIZE = 32
        MAX_WRITE_SIZE = 16  # Bezpečná velikost pro jeden zápis (FT260 limit)
        
        data = bytes(data)
        addr = start_address
        offset = 0
        
        while offset < len(data):
            # Kolik místa zbývá do konce aktuální stránky
            page_offset = addr % PAGE_SIZE
            page_remaining = PAGE_SIZE - page_offset
            
            # Kolik dat zapíšeme v tomto cyklu
            bytes_to_write = min(page_remaining, MAX_WRITE_SIZE, len(data) - offset)
            
            chunk = list(data[offset:offset + bytes_to_write])
            
            # Sestavení I2C zprávy: [ADDR_MSB, ADDR_LSB, DATA...]
            addr_hi = (addr >> 8) & 0xFF
            addr_lo = addr & 0xFF
            payload = [addr_hi, addr_lo] + chunk
            
            # Zápis do EEPROM
            self.bus.write_i2c_block(eeprom_address, payload)
            
            # ACK polling - čekání na dokončení programovacího cyklu
            # EEPROM neodpovídá během interního zápisu (~5 ms)
            write_complete = False
            for _ in range(max_retries):
                time.sleep(0.001)  # 1 ms mezi pokusy
                try:
                    # Pokus o čtení - pokud EEPROM odpoví, zápis je dokončen
                    self.bus.read_i2c_block(eeprom_address, 1)
                    write_complete = True
                    break
                except Exception:
                    continue
            
            if not write_complete:
                return False  # Timeout - EEPROM neodpověděla
            
            # Verifikace zapsaných dat
            if verify:
                readback = self._eeprom_read_chunk(eeprom_address, addr, bytes_to_write)
                if readback != chunk:
                    return False  # Data se neshodují
            
            addr += bytes_to_write
            offset += bytes_to_write
        
        return True
    
    def _eeprom_read_chunk(self, eeprom_address: int, addr: int, n: int) -> List[int]:
        """Pomocná metoda pro čtení EEPROM chunku."""
        addr_hi = (addr >> 8) & 0xFF
        addr_lo = addr & 0xFF
        self.bus.write_i2c_block(eeprom_address, [addr_hi, addr_lo])
        return list(self.bus.read_i2c_block(eeprom_address, n))
    
    # =========================================================================
    # High-Level Status Reading
    # =========================================================================
    
    def read_all_sensors(self) -> Airdos04Status:
        """
        Vyčte kompletní stav všech senzorů AIRDOS04.
        
        Returns
        -------
        Airdos04Status
            Kompletní stav detektoru.
        """
        status = Airdos04Status()
        
        # Sériová čísla
        try:
            status.serial_number_batdatunit = self.read_serial_number_batdatunit()
        except Exception:
            pass
        
        try:
            status.serial_number_ustsipin = self.read_serial_number_ustsipin()
        except Exception:
            pass
        
        # RTC
        try:
            status.rtc = self.read_rtc()
        except Exception:
            pass
        
        # Baterie
        try:
            status.battery = self.read_battery_status()
        except Exception:
            pass
        
        # SHT senzory
        try:
            status.sht_batdatunit = self.read_sht_batdatunit()
        except Exception:
            pass
        
        try:
            status.sht_ustsipin = self.read_sht_ustsipin()
        except Exception:
            pass
        
        # Výškoměr
        try:
            status.altimeter = self.read_altimeter()
        except Exception:
            pass
        
        return status
    
    def to_dict(self, status: Airdos04Status = None) -> Dict[str, Any]:
        """
        Převede stav do slovníku (kompatibilní s původním API).
        
        Parameters
        ----------
        status : Airdos04Status, optional
            Stav k převodu (pokud None, vyčte aktuální).
        
        Returns
        -------
        dict
            Slovník se stavem detektoru.
        """
        if status is None:
            status = self.read_all_sensors()
        
        result = {
            'sn_batdatunit': status.serial_number_batdatunit,
            'sn_ustsipin': status.serial_number_ustsipin,
        }
        
        if status.rtc:
            result['RTC'] = {
                'sys_time': status.rtc.elapsed,
                'abs_time': status.rtc.absolute_time,
                'sys_begin_time': status.rtc.start_time,
            }
        
        if status.battery:
            result['CHARGER'] = {
                'IBUS_ADC': status.battery.ibus_adc,
                'IBAT_ADC': status.battery.ibat_adc,
                'VBUS_ADC': status.battery.vbus_adc,
                'VPMID_ADC': status.battery.vpmid_adc,
                'VBAT_ADC': status.battery.vbat_adc,
                'VSYS_ADC': status.battery.vsys_adc,
                'TS_ADC': status.battery.ts_adc,
                'TDIE_ADC': status.battery.tdie_adc,
            }
            result['GAUGE'] = {
                'VOLTAGE': status.battery.voltage,
                'CUR_AVG': status.battery.current_avg,
                'CUR_NOW': status.battery.current_now,
                'REM_CAP': status.battery.remaining_capacity,
                'FUL_CAP': status.battery.full_capacity,
                'TEMP': status.battery.temperature,
                'STATE': status.battery.state,
            }
        
        if status.sht_batdatunit:
            result['SHT'] = {
                'temperature': status.sht_batdatunit.temperature,
                'humidity': status.sht_batdatunit.humidity,
            }
        
        if status.sht_ustsipin:
            result['AIRDOS_SHT'] = {
                'temperature': status.sht_ustsipin.temperature,
                'humidity': status.sht_ustsipin.humidity,
            }
        
        if status.altimeter:
            result['ALTIMET'] = {
                'calcoef': status.altimeter.calibration_coefficients,
                'altitude': status.altimeter.pressure_raw,
                'temperature': status.altimeter.temperature_raw,
            }
        
        return result

    def scan_i2c_bus(self, start: int = 0x03, end: int = 0x77) -> list[int]:
        """Skenuje I2C sběrnici a vrací seznam nalezených adres.
        
        Args:
            start: Počáteční adresa (default 0x03)
            end: Koncová adresa (default 0x77)
            
        Returns:
            Seznam nalezených I2C adres
        """
        found = []
        for addr in range(start, end + 1):
            try:
                # Pokus o čtení 1 bajtu z adresy
                data = self.bus.read_i2c_block_data(addr, 0, 1)
                if data is not None:
                    found.append(addr)
            except Exception:
                # Zařízení na této adrese neodpovědělo
                pass
        return found
