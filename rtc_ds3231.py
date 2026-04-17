import datetime
import os
import subprocess

try:
    from smbus2 import SMBus
except Exception:
    SMBus = None


DS3231_I2C_ADDR = 0x68
DS3231_REG_TIME_START = 0x00
DS3231_REG_TIME_END = 0x06
DS3231_REG_STATUS = 0x0F
DS3231_OSF_BIT = 0x80


def _bcd_to_int(value: int) -> int:
    return ((value >> 4) * 10) + (value & 0x0F)


def _int_to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _is_linux() -> bool:
    return os.name == "posix"


def _run_date_set(dt: datetime.datetime) -> bool:
    cmd = ["date", "-s", dt.strftime("%Y-%m-%d %H:%M:%S")]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode == 0:
            return True
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        if stderr or stdout:
            print(f"[rtc] Failed to set system time using date: {stderr or stdout}")
        return False
    except Exception as exc:
        print(f"[rtc] Failed to execute date command: {exc}")
        return False


class DS3231RTC:
    def __init__(self, bus_number: int = 1, address: int = DS3231_I2C_ADDR):
        self.bus_number = int(bus_number)
        self.address = int(address)

    def _require_backend(self):
        if SMBus is None:
            raise RuntimeError("smbus2 is not installed")

    def read_datetime(self) -> datetime.datetime:
        self._require_backend()
        with SMBus(self.bus_number) as bus:
            data = bus.read_i2c_block_data(
                self.address,
                DS3231_REG_TIME_START,
                DS3231_REG_TIME_END - DS3231_REG_TIME_START + 1,
            )

        sec = _bcd_to_int(data[0] & 0x7F)
        minute = _bcd_to_int(data[1] & 0x7F)

        hour_reg = data[2]
        if hour_reg & 0x40:
            hour = _bcd_to_int(hour_reg & 0x1F)
            pm = bool(hour_reg & 0x20)
            if pm and hour < 12:
                hour += 12
            if not pm and hour == 12:
                hour = 0
        else:
            hour = _bcd_to_int(hour_reg & 0x3F)

        day = _bcd_to_int(data[4] & 0x3F)
        month = _bcd_to_int(data[5] & 0x1F)
        year = 2000 + _bcd_to_int(data[6])

        return datetime.datetime(year, month, day, hour, minute, sec)

    def set_datetime(self, dt: datetime.datetime) -> None:
        self._require_backend()
        payload = [
            _int_to_bcd(dt.second),
            _int_to_bcd(dt.minute),
            _int_to_bcd(dt.hour),
            _int_to_bcd(dt.isoweekday()),
            _int_to_bcd(dt.day),
            _int_to_bcd(dt.month),
            _int_to_bcd(dt.year - 2000),
        ]

        with SMBus(self.bus_number) as bus:
            bus.write_i2c_block_data(self.address, DS3231_REG_TIME_START, payload)
            status = bus.read_byte_data(self.address, DS3231_REG_STATUS)
            bus.write_byte_data(self.address, DS3231_REG_STATUS, status & (~DS3231_OSF_BIT & 0xFF))

    def is_oscillator_stopped(self) -> bool:
        self._require_backend()
        with SMBus(self.bus_number) as bus:
            status = bus.read_byte_data(self.address, DS3231_REG_STATUS)
        return bool(status & DS3231_OSF_BIT)


def sync_system_time_from_rtc(bus_number: int = 1, address: int = DS3231_I2C_ADDR) -> bool:
    if not _is_linux():
        print("[rtc] Skipping RTC sync: non-Linux platform")
        return False

    try:
        rtc = DS3231RTC(bus_number=bus_number, address=address)
        if rtc.is_oscillator_stopped():
            print("[rtc] DS3231 OSF bit set; RTC time may be invalid")
        dt = rtc.read_datetime()
        ok = _run_date_set(dt)
        if ok:
            print(f"[rtc] System time set from DS3231: {dt.isoformat(sep=' ')}")
        return ok
    except Exception as exc:
        print(f"[rtc] RTC sync failed: {exc}")
        return False


def set_rtc_time_from_system(bus_number: int = 1, address: int = DS3231_I2C_ADDR) -> bool:
    try:
        rtc = DS3231RTC(bus_number=bus_number, address=address)
        now = datetime.datetime.now()
        rtc.set_datetime(now)
        print(f"[rtc] DS3231 updated from system time: {now.isoformat(sep=' ')}")
        return True
    except Exception as exc:
        print(f"[rtc] Failed to update DS3231 from system time: {exc}")
        return False


def set_rtc_time_explicit(dt: datetime.datetime, bus_number: int = 1, address: int = DS3231_I2C_ADDR) -> bool:
    try:
        rtc = DS3231RTC(bus_number=bus_number, address=address)
        rtc.set_datetime(dt)
        print(f"[rtc] DS3231 set to: {dt.isoformat(sep=' ')}")
        return True
    except Exception as exc:
        print(f"[rtc] Failed to set DS3231 time: {exc}")
        return False
