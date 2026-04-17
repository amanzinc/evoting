import argparse
import datetime

from rtc_ds3231 import set_rtc_time_explicit, set_rtc_time_from_system


def _parse_time(value: str) -> datetime.datetime:
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Invalid datetime format. Use 'YYYY-MM-DD HH:MM[:SS]' or ISO format")


def main() -> int:
    parser = argparse.ArgumentParser(description="Set DS3231 RTC time over I2C")
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number (default: 1)")
    parser.add_argument("--addr", type=lambda x: int(x, 0), default=0x68, help="I2C address, e.g. 0x68")
    parser.add_argument(
        "--time",
        type=str,
        default=None,
        help="Datetime to set, e.g. '2026-04-17 14:35:00'. If omitted, system time is used.",
    )

    args = parser.parse_args()

    if args.time:
        try:
            dt = _parse_time(args.time)
        except ValueError as exc:
            print(exc)
            return 2
        ok = set_rtc_time_explicit(dt, bus_number=args.bus, address=args.addr)
    else:
        ok = set_rtc_time_from_system(bus_number=args.bus, address=args.addr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
