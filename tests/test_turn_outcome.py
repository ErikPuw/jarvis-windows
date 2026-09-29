"""Tests for engine.core.learning.outcome_for_turn. Run: python tests/test_turn_outcome.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.learning import outcome_for_turn


class Session:
    pass


def test_no_agent_ran_ever():
    assert outcome_for_turn(Session(), time.time()) == (None, None)


def test_outcome_from_this_turn_is_returned():
    s = Session()
    turn_started = time.time()
    s.last_agent_outcome_id = 42
    s.last_agent_outcome_status = "success"
    s.last_agent_outcome_at = turn_started + 0.5
    assert outcome_for_turn(s, turn_started) == (42, "success")


def test_outcome_from_an_earlier_turn_is_ignored():
    """The log showed a history question re-validating the previous turn's
    check_project workflow because the stale id was passed to learning."""
    s = Session()
    s.last_agent_outcome_id = 13
    s.last_agent_outcome_status = "success"
    s.last_agent_outcome_at = time.time() - 60
    assert outcome_for_turn(s, time.time()) == (None, None)


def test_legacy_session_without_timestamp_is_ignored():
    """An id without a timestamp cannot be attributed to this turn."""
    s = Session()
    s.last_agent_outcome_id = 7
    assert outcome_for_turn(s, time.time()) == (None, None)


def test_failed_status_is_carried_through():
    s = Session()
    turn_started = time.time()
    s.last_agent_outcome_id = 9
    s.last_agent_outcome_status = "failed"
    s.last_agent_outcome_at = turn_started
    assert outcome_for_turn(s, turn_started) == (9, "failed")


if __name__ == "__main__":
    test_no_agent_ran_ever()
    test_outcome_from_this_turn_is_returned()
    test_outcome_from_an_earlier_turn_is_ignored()
    test_legacy_session_without_timestamp_is_ignored()
    test_failed_status_is_carried_through()
    print("OK: all turn outcome tests passed")
