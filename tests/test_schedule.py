import pytest

from schedule import build_scheduler
from screens.registry import ScreenDefinition


def make_registry(availability):
    return {
        sid: ScreenDefinition(id=sid, render=lambda sid=sid: sid, available=available)
        for sid, available in availability.items()
    }


def collect_sequence(scheduler, registry, length):
    results = []
    for _ in range(length):
        definition = scheduler.next_available(registry)
        results.append(definition.id if definition is not None else None)
    return results


def collect_played_ids(scheduler, registry, iterations):
    results = []
    for _ in range(iterations):
        definition = scheduler.next_available(registry)
        if definition is not None:
            results.append(definition.id)
    return results


def test_build_scheduler_from_config():
    config = {
        "screens": {
            "date": 1,
            "travel": 2,
            "inside": 1,
        }
    }
    scheduler = build_scheduler(config)
    assert scheduler.node_count == 3
    assert scheduler.requested_ids == {"date", "travel", "inside"}


def test_scheduler_with_alternate_screen():
    config = {
        "screens": {
            "date": {
                "frequency": 1,
                "alt": {"screen": "travel", "frequency": 2},
            }
        }
    }
    scheduler = build_scheduler(config)
    assert scheduler.requested_ids == {"date", "travel"}

    registry = make_registry({"date": True, "travel": True})
    sequence = [scheduler.next_available(registry).id for _ in range(6)]
    assert sequence == [
        "date",
        "travel",
        "date",
        "travel",
        "date",
        "travel",
    ]


def test_build_scheduler_rejects_unknown_screen():
    config = {"screens": {"missing": 1}}
    with pytest.raises(ValueError):
        build_scheduler(config)


def test_scheduler_respects_frequency():
    config = {"screens": {"date": 1, "travel": 2}}
    scheduler = build_scheduler(config)
    registry = make_registry({"date": True, "travel": True})

    sequence = collect_sequence(scheduler, registry, 6)
    assert sequence == ["date", "travel", "date", "date", "travel", "date"]


def test_scheduler_frequency_interval_matches_configuration():
    config = {"screens": {"date": 1, "travel": 4}}
    scheduler = build_scheduler(config)
    registry = make_registry({"date": True, "travel": True})

    sequence = collect_sequence(scheduler, registry, 12)
    # ``travel`` should insert four other screens between each appearance.
    assert sequence == [
        "date",
        "travel",
        "date",
        "date",
        "date",
        "date",
        "travel",
        "date",
        "date",
        "date",
        "date",
        "travel",
    ]


def test_scheduler_skips_unavailable_screen():
    config = {"screens": {"travel": 1}}
    scheduler = build_scheduler(config)
    registry = make_registry({"travel": False})
    assert scheduler.next_available(registry) is None


def test_invalid_configuration_shapes():
    with pytest.raises(ValueError):
        build_scheduler({})
    with pytest.raises(ValueError):
        build_scheduler({"screens": []})
    with pytest.raises(ValueError):
        build_scheduler({"screens": {"date": -1}})
    with pytest.raises(ValueError):
        build_scheduler({"screens": {"date": "oops"}})
    with pytest.raises(ValueError):
        build_scheduler(
            {"screens": {"date": {"frequency": 1, "alt": {"screen": "travel"}}}}
        )
    with pytest.raises(ValueError):
        build_scheduler(
            {
                "screens": {
                    "date": {
                        "frequency": 1,
                        "alt": {"screen": "travel", "frequency": 0},
                    }
                }
            }
        )


def test_zero_frequency_entries_are_skipped():
    config = {"screens": {"date": 0, "time": 2}}
    scheduler = build_scheduler(config)
    registry = make_registry({"date": True, "time": True})

    played = collect_played_ids(scheduler, registry, 6)
    assert played
    assert set(played) == {"time"}


def test_all_zero_frequencies_raise_error():
    config = {"screens": {"date": 0, "time": 0}}

    with pytest.raises(ValueError):
        build_scheduler(config)
