from datetime import datetime, UTC
from custom_components.stiga.protocol import StigaState, pb_decode, pb_encode, encode_command

NOW = datetime.now(UTC)
# Real A6v LOG/STATUS (docked, charging), re-expressed as decoded dict
REAL = {1: 1, 2: 1, 3: 3, 13: 1, 17: {1: 2000, 2: 66, 3: 28}, 18: {1: 1, 4: {2: 90}, 5: "01"}}


def st(d):
    s = StigaState(); s.apply_status(d, NOW); return s


def test_roundtrip():
    assert pb_decode(encode_command(28, {1: 1, 2: 1, 3: 1, 4: 1})) == {1: 28, 2: {1: 1, 2: 1, 3: 1, 4: 1}, 3: 28}
    assert encode_command(0) == bytes([0x08, 0x00, 0x18, 0x00])
    assert pb_decode(pb_encode({18: {1: 1, 5: b"\x01"}})) == {18: {1: 1, 5: "01"}}


def test_real_docked():
    s = st(REAL)
    assert (s.activity, s.battery, s.zone, s.zone_completed, s.garden_completed, s.error_message) == ("home", 66, 1, 0, 0, None)


def test_mowing_partial_keeps_battery():
    s = st(REAL); s.apply_status({1: 1, 3: 1, 18: {1: 2, 2: 40, 3: 15}}, NOW)
    assert (s.activity, s.battery, s.zone, s.zone_completed, s.garden_completed) == ("mowing", 66, 2, 40, 15)


def test_rain():
    assert st({3: 4, 13: 1, 10: {1: 0x1A9}}).activity == "rain_pause"
    assert st({3: 2, 10: {1: 0x1A9}}).activity == "rain_pause"
    assert st({3: 1, 10: {1: 0x1A9}}).activity == "mowing"


def test_errors():
    s = st({3: 255, 4: {1: 2, 2: 22}, 10: {1: 0x1B3}, 12: 1})
    assert (s.activity, s.error_message) == ("error", "Stuck: trapped")
    assert st({3: 255, 4: {1: 2, 2: 20}}).activity == "mowing"
    assert st({3: 8}).error_message == "Lid open"
    assert st({3: 255, 4: {1: 1, 2: 30}}).error_message == "High grass (going home)"
    assert st({3: 255, 4: {1: 9, 2: 9}}).error_message == "Error 9/9"


def test_settings():
    s = StigaState(); s.apply_settings({1: {1: 1}, 4: {1: 1, 2: 5}}); s.apply_scheduling_settings({1: 1}, bytes([0x08, 0x01]))
    assert (s.rain_sensor_enabled, s.rain_delay_hours, s.schedule_enabled) == (True, 4, True)


def test_schedule_real():
    from custom_components.stiga.protocol import pb_encode
    raw = bytes.fromhex("000000fc010300000000fc010300000000fc010300000000fc010300000000fc010300000000000000000000000000")
    payload = pb_encode({1: 1, 2: raw})
    s = StigaState(); s.apply_scheduling_settings(pb_decode(payload), payload)
    assert s.schedule["monday"] == ["13:00–17:00"] and s.schedule["saturday"] == []
    assert s.schedule_summary == "Mon–Fri 13:00–17:00"
    s.schedule_enabled = False
    assert s.schedule_summary == "Off"


def test_schedule_edges():
    from custom_components.stiga.protocol import decode_schedule, summarize_schedule
    # Monday 00:00-00:30 and 23:30-24:00; Sunday same as Monday (non-consecutive -> separate)
    day = [0x01, 0, 0, 0, 0, 0x80]
    vals = day + [0] * 30 + day
    raw = b"".join(bytes([v]) if v < 0x80 else bytes([v, 0x01]) for v in vals)
    sched = decode_schedule(raw)
    assert sched["monday"] == ["00:00–00:30", "23:30–24:00"] == sched["sunday"]
    assert summarize_schedule(sched) == "Mon 00:00–00:30, 23:30–24:00; Sun 00:00–00:30, 23:30–24:00"


REAL_SCHED = bytes.fromhex("000000fc010300000000fc010300000000fc010300000000fc010300000000fc010300000000000000000000000000")
REAL_SETTINGS = {1: {1: 1}, 4: {1: 1, 2: 5}, 7: 1, 8: {1: 4}, 9: 1, 11: 110, 14: {1: 1}, 15: {1: 1}}


def _sched_state():
    payload = pb_encode({1: 1, 2: REAL_SCHED})
    s = StigaState(); s.apply_scheduling_settings(pb_decode(payload), payload); return s


def test_schedule_bytes_roundtrip_matches_robot_encoding():
    from custom_components.stiga.protocol import decode_schedule_bytes, encode_schedule_bytes
    assert encode_schedule_bytes(decode_schedule_bytes(REAL_SCHED)) == REAL_SCHED


def test_schedule_blocks():
    from custom_components.stiga.protocol import DEFAULT_BLOCKS, schedule_block_enabled as on, with_schedule_block as w, schedule_times
    B = {b.key: b.slots for b in DEFAULT_BLOCKS}
    s = _sched_state(); v = s.schedule_bytes
    assert on(v, 0, B["afternoon"]) and not on(v, 0, B["morning"]) and not on(v, 5, B["afternoon"])
    v2 = w(v, 5, B["morning"], True)
    assert schedule_times(v2)["saturday"] == ["09:00–13:00"] and schedule_times(v2)["monday"] == ["13:00–17:00"]
    v3 = w(v2, 0, B["morning"], True)
    assert schedule_times(v3)["monday"] == ["09:00–17:00"]
    assert w(w(v, 5, B["morning"], True), 5, B["morning"], False) == v
    # echo payload: full message, varint-packed bitmap
    msg = s.scheduling_with_bytes(v)
    assert pb_encode(msg) == pb_encode({1: 1, 2: REAL_SCHED})


def test_scheduling_echo_refuses_what_it_cannot_send_back():
    import pytest
    payload = pb_encode({1: 1, 2: REAL_SCHED, 3: b"\x01\x02"})
    s = StigaState(); s.apply_scheduling_settings(pb_decode(payload), payload)
    with pytest.raises(ValueError):
        s.scheduling_with_bytes(s.schedule_bytes)


def test_settings_echo():
    s = StigaState(); s.apply_settings(REAL_SETTINGS)
    assert s.cutting_height == 45
    assert pb_encode(s.settings_with_cutting_height(45)) == pb_encode(REAL_SETTINGS)
    new = s.settings_with_cutting_height(30)
    assert new[4] == {1: 1, 2: 2} and {k: v for k, v in new.items() if k != 4} == {k: v for k, v in REAL_SETTINGS.items() if k != 4}
    s.apply_settings(new); assert s.cutting_height == 30
    import pytest
    with pytest.raises(ValueError):
        s.settings_with_cutting_height(65)
    s2 = StigaState(); s2.apply_settings({1: "weird"})
    with pytest.raises(ValueError):
        s2.settings_with_cutting_height(40)


def test_calibrating():
    assert st({3: 20, 13: 1}).activity == "calibrating"
    assert st({3: 255, 4: {1: 1, 2: 28}, 13: 1}).error_message == "Blades not calibrated"
