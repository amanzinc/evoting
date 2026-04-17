import time

from rtc_ds3231 import sync_system_time_from_rtc


def main() -> int:
    # Early-boot I2C devices can appear a little late; retry briefly.
    for attempt in range(1, 6):
        if sync_system_time_from_rtc():
            return 0
        if attempt < 5:
            time.sleep(1.5)

    # Keep boot resilient; app can still start even if RTC sync fails.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
