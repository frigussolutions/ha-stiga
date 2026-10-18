import pytest
from custom_components.stiga.config_flow import _blocks_from_input
from custom_components.stiga.coordinator import blocks_from_options
from custom_components.stiga.protocol import DEFAULT_BLOCKS, ScheduleBlock


def form(*blocks):
    d = {}
    for i, (n, s, e) in enumerate(blocks, 1):
        d.update({f"block_{i}_name": n, f"block_{i}_start": s, f"block_{i}_end": e})
    return d


def test_defaults_match_previous_fixed_blocks():
    assert [b.slots for b in DEFAULT_BLOCKS] == [range(18, 26), range(26, 34)]
    assert blocks_from_options({}) == DEFAULT_BLOCKS
    assert blocks_from_options({"blocks": []}) == ()


def test_valid():
    r = _blocks_from_input(form(("Morning", "09:00:00", "13:00:00"), ("Late evening", "20:30:00", "00:00:00")))
    assert r == [{"key": "morning", "name": "Morning", "start": "09:00", "end": "13:00"},
                 {"key": "late_evening", "name": "Late evening", "start": "20:30", "end": "24:00"}]
    assert ScheduleBlock(**r[1]).slots == range(41, 48)
    assert _blocks_from_input(form(("", "09:00:00", "10:00:00"))) == []


@pytest.mark.parametrize("blocks,err", [
    ((("A", "09:15:00", "10:00:00"),), "half_hour"),
    ((("A", "10:00:00", "09:00:00"),), "end_before_start"),
    ((("A", "09:00:00", None),), "missing_time"),
    ((("A", "09:00:00", "12:00:00"), ("a", "13:00:00", "14:00:00")), "duplicate_name"),
    ((("A", "09:00:00", "12:00:00"), ("B", "11:30:00", "14:00:00")), "overlap"),
])
def test_invalid(blocks, err):
    with pytest.raises(ValueError, match=err):
        _blocks_from_input(form(*blocks))
