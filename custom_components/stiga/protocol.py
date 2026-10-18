"""STIGA A-series robot MQTT protocol: schemaless protobuf codec and status model.

Field numbers and code tables are ported from the reverse-engineered stiga-api project
(https://github.com/matthewgream/stiga-api, CC BY-NC-SA 4.0) and verified against an A6v.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import struct
from typing import Any

# CMD_ROBOT command ids. Command 10 is deliberately absent: upstream confirmed it
# permanently bricks the robot. Never send ids that are not listed here.
CMD_STOP = 0
CMD_START = 1
CMD_GO_HOME = 4
CMD_SETTINGS_REQUEST = 17
CMD_SETTINGS_UPDATE = 18
CMD_CALIBRATE_BLADES = 26
CMD_SCHEDULING_SETTINGS_REQUEST = 19
CMD_SCHEDULING_SETTINGS_UPDATE = 20
CMD_STATUS_REQUEST = 28

ACK_OK = 1

# Selects battery, mowing, location and network sub-blocks in the status reply.
STATUS_REQUEST_ALL = {1: 1, 2: 1, 3: 1, 4: 1}

STATUS_TYPES = {
    0: "WAITING_FOR_COMMAND",
    1: "MOWING",
    2: "GOING_HOME",
    3: "CHARGING",
    4: "DOCKED",
    5: "UPDATING",
    6: "BLOCKED",
    8: "LID_OPEN",
    13: "GOING_HOME",
    17: "PERIMETER_RETRACE",
    18: "CALIBRATION",
    20: "BLADES_CALIBRATION",
    25: "DOCKING_CALIBRATION",
    27: "STORING_DATA",
    28: "PLANNING_ONGOING",
    29: "REACHING_FIRST_POINT",
    30: "NAVIGATING_TO_AREA",
    32: "CUTTING_BORDER",
    252: "STARTUP_REQUIRED",
    255: "ERROR",
}
MOWING_TYPES = {1, 17, 27, 28, 29, 30, 32}
RETURNING_TYPES = {2, 13}
HOME_TYPES = {3, 4}
CALIBRATION_TYPES = {18, 20, 25}
ERROR_TYPES = {6, 8, 252, 255}

# Status field 4: (code1, code2) tuple.
ERROR_MESSAGES = {
    (1, 28): "Blades not calibrated",
    (1, 30): "High grass (going home)",
    (1, 31): "High grass (at home)",
    (2, 18): "Navigation initialising",
    (2, 20): "GPS searching",
    (2, 22): "Stuck",
}
# Reported under status type ERROR while leaving the dock; not faults.
TRANSIENT_ERRORS = {(2, 18), (2, 20)}

# Status field 10.1: the specific cause.
INFO_RAIN_SENSOR = 0x01A9
INFO_CODES = {
    0x0064: "Low battery",
    0x00DA: "Blade motor trouble",
    0x0191: "Blocked",
    0x01A2: "Lid sensor",
    INFO_RAIN_SENSOR: "Rain sensor",
    0x01AE: "Robot rollover",
    0x01B0: "Lift sensor",
    0x01B1: "Bump sensor",
    0x01B2: "Slope sensor",
    0x01B3: "Trapped",
    0x01FA: "Docking error",
    0x0389: "Wheel trouble",
    0x03EF: "Surface too slippery",
    0x03F0: "Out of perimeter",
}

RAIN_DELAY_HOURS = {0: 4, 1: 8, 2: 12}

# Settings field 4.2: cutting height index, 20-60 mm in 5 mm steps (absent = 45 mm).
CUTTING_HEIGHT_MIN = 20
CUTTING_HEIGHT_MAX = 60
CUTTING_HEIGHT_STEP = 5
CUTTING_HEIGHT_DEFAULT_INDEX = 5



def time_slot(value: str) -> int:
    """'HH:MM' (on a half hour; '24:00' allowed) to a half-hour slot index 0-48."""
    hours, minutes = (int(part) for part in value.split(":")[:2])
    return hours * 2 + minutes // 30


@dataclass(frozen=True)
class ScheduleBlock:
    """A named part of the day, switched on or off per weekday."""

    key: str
    name: str
    start: str
    end: str

    @property
    def slots(self) -> range:
        """Half-hour slots covered by the block."""
        return range(time_slot(self.start), time_slot(self.end))

    def as_dict(self) -> dict[str, str]:
        """Plain dict, for options and attributes."""
        return {"key": self.key, "name": self.name, "start": self.start, "end": self.end}


DEFAULT_BLOCKS = (
    ScheduleBlock("morning", "Morning", "09:00", "13:00"),
    ScheduleBlock("afternoon", "Afternoon", "13:00", "17:00"),
)

ACTIVITY_HOME = "home"
ACTIVITY_MOWING = "mowing"
ACTIVITY_RETURNING = "returning"
ACTIVITY_RAIN_PAUSE = "rain_pause"
ACTIVITY_PAUSED = "paused"
ACTIVITY_ERROR = "error"
ACTIVITY_UPDATING = "updating"
ACTIVITY_CALIBRATING = "calibrating"
ACTIVITIES = [
    ACTIVITY_HOME,
    ACTIVITY_MOWING,
    ACTIVITY_RETURNING,
    ACTIVITY_RAIN_PAUSE,
    ACTIVITY_PAUSED,
    ACTIVITY_ERROR,
    ACTIVITY_UPDATING,
    ACTIVITY_CALIBRATING,
]


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, pos


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def pb_decode(buf: bytes) -> dict[int, Any]:
    """Decode protobuf without a schema.

    Length-delimited fields become a str when printable, else a nested dict when they
    parse as a message, else a hex string. Repeated fields become lists.
    """
    out: dict[int, Any] = {}
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            break
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 1:
            value = buf[pos : pos + 8].hex()
            pos += 8
        elif wire == 5:
            value = struct.unpack("<f", buf[pos : pos + 4])[0]
            pos += 4
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            raw = buf[pos : pos + length]
            pos += length
            value = _decode_bytes(raw)
        else:
            raise ValueError(f"unsupported wire type {wire}")
        if field in out:
            if not isinstance(out[field], list):
                out[field] = [out[field]]
            out[field].append(value)
        else:
            out[field] = value
    return out


def _decode_bytes(raw: bytes) -> Any:
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        text = ""
    if text and all(c.isspace() or " " <= c <= "~" for c in text):
        return text
    try:
        return pb_decode(raw) or raw.hex()
    except (ValueError, IndexError, struct.error):
        return raw.hex()


def _is_varint_tree(value: Any) -> bool:
    """Value round-trips through pb_encode unchanged (ints and messages of ints only)."""
    if isinstance(value, dict):
        return all(_is_varint_tree(item) for item in value.values())
    return isinstance(value, int)


def pb_encode(obj: dict[int, Any]) -> bytes:
    """Encode a {field: int | bytes | dict} mapping; None values are skipped."""
    out = bytearray()
    for field, value in obj.items():
        if value is None:
            continue
        if isinstance(value, int):
            out += _encode_varint(field << 3) + _encode_varint(value)
        else:
            raw = pb_encode(value) if isinstance(value, dict) else value
            out += _encode_varint(field << 3 | 2) + _encode_varint(len(raw)) + raw
    return bytes(out)


def pb_raw_field(buf: bytes, wanted: int) -> bytes | None:
    """Return the raw bytes of the first length-delimited `wanted` field, undecoded."""
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, pos = _read_varint(buf, pos)
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            if field == wanted:
                return buf[pos : pos + length]
            pos += length
        else:
            raise ValueError(f"unsupported wire type {wire}")
    return None


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _slot_time(slot: int) -> str:
    return f"{slot // 2:02d}:{slot % 2 * 30:02d}"


def decode_schedule_bytes(raw: bytes) -> list[int]:
    """Weekly schedule bitmap: 7 days x 6 bytes (48 half-hour slots, LSB first), packed as varints."""
    values: list[int] = []
    pos = 0
    while pos < len(raw):
        value, pos = _read_varint(raw, pos)
        values.append(value & 0xFF)
    if len(values) != 42:
        raise ValueError(f"unexpected schedule length {len(values)}")
    return values


def encode_schedule_bytes(values: list[int]) -> bytes:
    """Inverse of decode_schedule_bytes. Upstream writes raw bytes, which breaks any byte >= 0x80."""
    return b"".join(_encode_varint(value) for value in values)


def _slot_set(values: list[int], day: int, slot: int) -> bool:
    return bool(values[day * 6 + slot // 8] >> (slot % 8) & 1)


def schedule_block_enabled(values: list[int], day: int, slots: range) -> bool:
    """Every half-hour slot of the block is scheduled."""
    return all(_slot_set(values, day, slot) for slot in slots)


def with_schedule_block(values: list[int], day: int, slots: range, enabled: bool) -> list[int]:
    """Copy of the bitmap with the block set or cleared; other slots untouched."""
    new = list(values)
    for slot in slots:
        index, mask = day * 6 + slot // 8, 1 << (slot % 8)
        new[index] = new[index] | mask if enabled else new[index] & ~mask
    return new


def decode_schedule(raw: bytes) -> dict[str, list[str]]:
    """Weekly schedule as mowing time ranges per weekday."""
    return schedule_times(decode_schedule_bytes(raw))


def schedule_times(values: list[int]) -> dict[str, list[str]]:
    """Turn the bitmap into time ranges per weekday."""
    schedule: dict[str, list[str]] = {}
    for day, name in enumerate(WEEKDAYS):
        bits = [_slot_set(values, day, slot) for slot in range(48)] + [False]
        blocks: list[str] = []
        start = None
        for slot, bit in enumerate(bits):
            if bit and start is None:
                start = slot
            elif not bit and start is not None:
                blocks.append(f"{_slot_time(start)}–{_slot_time(slot)}")
                start = None
        schedule[name] = blocks
    return schedule


def summarize_schedule(schedule: dict[str, list[str]]) -> str:
    """Group consecutive days with identical times, e.g. 'Mon–Fri 13:00–17:00'."""
    groups: list[tuple[int, int, list[str]]] = []
    for day, name in enumerate(WEEKDAYS):
        blocks = schedule.get(name, [])
        if groups and groups[-1][2] == blocks and groups[-1][1] == day - 1:
            groups[-1] = (groups[-1][0], day, blocks)
        else:
            groups.append((day, day, blocks))
    parts = []
    for first, last, blocks in groups:
        if not blocks:
            continue
        days = WEEKDAYS[first][:3].capitalize()
        if last != first:
            days += f"–{WEEKDAYS[last][:3].capitalize()}"
        parts.append(f"{days} {', '.join(blocks)}")
    return "; ".join(parts)[:255] or "No mowing times"


def encode_command(command: int, fields: dict[int, Any] | None = None) -> bytes:
    """Build a CMD_ROBOT payload; field 3 echoes the command as the app does."""
    return pb_encode({1: command, 2: fields, 3: command})


@dataclass
class StigaState:
    """Last known state of one robot, merged from LOG/* messages."""

    status_type: int | None = None
    error: tuple[int, int] | None = None
    info_code: int | None = None
    intervention_required: bool = False
    docked: bool = False
    battery: int | None = None
    zone: int | None = None
    zone_completed: int | None = None
    garden_completed: int | None = None
    rain_sensor_enabled: bool | None = None
    rain_delay_hours: int | None = None
    schedule_enabled: bool | None = None
    schedule_bytes: list[int] | None = None
    blocks: tuple[ScheduleBlock, ...] = DEFAULT_BLOCKS
    settings: dict[int, Any] | None = None
    scheduling_settings: dict[int, Any] | None = None
    status_updated: datetime | None = None

    def apply_status(self, decoded: dict[int, Any], now: datetime) -> None:
        """Apply LOG/STATUS. Top-level fields are always sent; sub-blocks only on request."""
        self.status_type = decoded.get(3, 0)
        error = decoded.get(4)
        self.error = (error.get(1, 0), error.get(2, 0)) if isinstance(error, dict) else None
        info = decoded.get(10)
        self.info_code = info.get(1) if isinstance(info, dict) else None
        self.intervention_required = bool(decoded.get(12))
        self.docked = bool(decoded.get(13))
        if isinstance(battery := decoded.get(17), dict):
            self.battery = battery.get(2, 0)
        if isinstance(mowing := decoded.get(18), dict):
            self.zone = mowing.get(1)
            self.zone_completed = mowing.get(2, 0)
            self.garden_completed = mowing.get(3, 0)
        self.status_updated = now

    def apply_settings(self, decoded: dict[int, Any]) -> None:
        """Apply LOG/SETTINGS."""
        self.settings = decoded
        rain = decoded.get(1)
        rain = rain if isinstance(rain, dict) else {}
        self.rain_sensor_enabled = rain.get(1) == 1
        self.rain_delay_hours = RAIN_DELAY_HOURS.get(rain.get(2, 0))

    def apply_scheduling_settings(self, decoded: dict[int, Any], payload: bytes) -> None:
        """Apply LOG/SCHEDULING_SETTINGS; field 2 is read raw, the schemaless decode mangles it."""
        self.scheduling_settings = decoded
        self.schedule_enabled = decoded.get(1) == 1
        raw = pb_raw_field(payload, 2)
        self.schedule_bytes = decode_schedule_bytes(raw) if raw else [0] * 42

    @property
    def schedule(self) -> dict[str, list[str]] | None:
        """Mowing time ranges per weekday."""
        return None if self.schedule_bytes is None else schedule_times(self.schedule_bytes)

    @property
    def cutting_height(self) -> int | None:
        """Cutting height in mm."""
        if self.settings is None:
            return None
        height = self.settings.get(4)
        index = height.get(2, 0) if isinstance(height, dict) else CUTTING_HEIGHT_DEFAULT_INDEX
        return CUTTING_HEIGHT_MIN + index * CUTTING_HEIGHT_STEP

    def settings_with_cutting_height(self, height_mm: int) -> dict[int, Any]:
        """Full settings echo with only the cutting height changed.

        The robot reports every setting; sending them all back means nothing else can be
        reset by a partial update. Refuses when the report holds anything but varints.
        """
        if self.settings is None:
            raise ValueError("settings not received yet")
        if not all(_is_varint_tree(value) for value in self.settings.values()):
            raise ValueError(f"settings contain non-varint fields: {self.settings}")
        index = (height_mm - CUTTING_HEIGHT_MIN) // CUTTING_HEIGHT_STEP
        if not 0 <= index <= (CUTTING_HEIGHT_MAX - CUTTING_HEIGHT_MIN) // CUTTING_HEIGHT_STEP:
            raise ValueError(f"cutting height {height_mm} mm out of range")
        settings = dict(self.settings)
        height = settings.get(4)
        settings[4] = {**(height if isinstance(height, dict) else {1: 1}), 2: index}
        return settings

    def scheduling_with_bytes(self, values: list[int]) -> dict[int, Any]:
        """Full scheduling settings echo with a new bitmap."""
        if self.scheduling_settings is None:
            raise ValueError("schedule not received yet")
        scheduling: dict[int, Any] = {
            field: value
            for field, value in self.scheduling_settings.items()
            if field != 2 and _is_varint_tree(value)
        }
        scheduling[2] = encode_schedule_bytes(values)
        return dict(sorted(scheduling.items()))

    @property
    def schedule_summary(self) -> str | None:
        """One-line schedule, or Off when the schedule is disabled."""
        if self.schedule is None:
            return None
        if not self.schedule_enabled:
            return "Off"
        return summarize_schedule(self.schedule)

    @property
    def robot_state(self) -> str | None:
        """Raw robot status name."""
        if self.status_type is None:
            return None
        return STATUS_TYPES.get(self.status_type, f"UNKNOWN_{self.status_type}")

    @property
    def rain_detected(self) -> bool:
        """Rain sensor is the reported cause."""
        return self.info_code == INFO_RAIN_SENSOR

    @property
    def activity(self) -> str | None:
        """Collapse the robot state into one of ACTIVITIES."""
        status = self.status_type
        if status is None:
            return None
        if self.rain_detected and status not in MOWING_TYPES:
            return ACTIVITY_RAIN_PAUSE
        if status == 255 and self.error in TRANSIENT_ERRORS and not self.intervention_required:
            return ACTIVITY_HOME if self.docked else ACTIVITY_MOWING
        if status in ERROR_TYPES or self.intervention_required:
            return ACTIVITY_ERROR
        if status in MOWING_TYPES:
            return ACTIVITY_MOWING
        if status in RETURNING_TYPES:
            return ACTIVITY_RETURNING
        if status == 5:
            return ACTIVITY_UPDATING
        if status in CALIBRATION_TYPES:
            return ACTIVITY_CALIBRATING
        if status in HOME_TYPES or self.docked:
            return ACTIVITY_HOME
        return ACTIVITY_PAUSED

    @property
    def is_active(self) -> bool:
        """Robot is out in the garden."""
        return self.activity in (ACTIVITY_MOWING, ACTIVITY_RETURNING)

    @property
    def error_message(self) -> str | None:
        """Human-readable error, or None when the robot is not in error."""
        if self.activity != ACTIVITY_ERROR:
            return None
        parts: list[str] = []
        if self.error is not None:
            parts.append(ERROR_MESSAGES.get(self.error, f"Error {self.error[0]}/{self.error[1]}"))
        elif self.status_type in (6, 8, 252):
            parts.append(self.robot_state.replace("_", " ").capitalize())
        if self.info_code is not None:
            parts.append(INFO_CODES.get(self.info_code, f"code 0x{self.info_code:04X}"))
        if not parts:
            parts.append("Intervention required" if self.intervention_required else "Unknown error")
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]}: {parts[1].lower()}"
