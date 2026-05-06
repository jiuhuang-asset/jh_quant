from enum import Enum


class Frequency(Enum):
    DAILY = "1d"
    MINUTE_1 = "1min"
    MINUTE_5 = "5min"
    MINUTE_15 = "15min"
    MINUTE_30 = "30min"
    MINUTE_60 = "60min"
    HOUR_1 = "1hour"

    @classmethod
    def from_value(cls, value: "Frequency | str | None") -> "Frequency":
        if isinstance(value, cls):
            return value

        mapping = {
            None: cls.DAILY,
            "daily": cls.DAILY,
            "day": cls.DAILY,
            "1day": cls.DAILY,
            "1d": cls.DAILY,
            "1min": cls.MINUTE_1,
            "1m": cls.MINUTE_1,
            "5min": cls.MINUTE_5,
            "5m": cls.MINUTE_5,
            "15min": cls.MINUTE_15,
            "15m": cls.MINUTE_15,
            "30min": cls.MINUTE_30,
            "30m": cls.MINUTE_30,
            "60min": cls.MINUTE_60,
            "60m": cls.MINUTE_60,
            "1hour": cls.HOUR_1,
            "1h": cls.HOUR_1,
        }
        normalized = mapping.get(str(value).lower() if value is not None else None)
        if normalized is None:
            raise ValueError(f"Unsupported frequency: {value}")
        return normalized
