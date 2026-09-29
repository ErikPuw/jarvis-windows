"""Only a verified-successful run is saved, and it is reusable by the user's own words.
Isolated temp DB/wiki. Run: python tests/test_workflow_reuse.py"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import learning
from engine.orchestrator import dispatcher

USER_TEXT = "bạn tìm tin tức về nvidia rtx spark có gì nổi bật không?"


def _trace(outcome):
    return {"action_name": "search_news", "args": {"query": "nvidia"}, "outcome": outcome, "timestamp": 1000}


def _engine(tmp):
    learning.MEMORY_DB_PATH = tmp / "jarvis.db"
    learning.WORKFLOWS_WIKI_DIR = tmp / "wf"
    for name in ("PREFERENCES_WIKI_PATH", "LESSONS_WIKI_PATH"):
        setattr(learning, name, tmp / f"{name}.md")
    le = learning.LearningEngine()
    le._init_db()
    return le


def _run(le, traces, outcome_query):
    """record an outcome the way the dispatcher does, then try to learn from it"""
    outcome_id = le.record_agent_outcome(
        "search", outcome_query, "success" if all(t["outcome"] == "success" for t in traces) else "failed",
        "kết quả", traces,
    )

    async def go():
        async def no_llm(*a, **k):
            raise RuntimeError("offline: use fallback metadata")
        import engine.server.llm_server as ls
        orig = ls.call_llm
        ls.call_llm = no_llm
        try:
            return await le.store_validated_workflow(outcome_id)
        finally:
            ls.call_llm = orig
    return asyncio.run(go())


def test_success_is_saved_and_matches_the_users_exact_words():
    le = _engine(Path(tempfile.mkdtemp()))
    assert _run(le, [_trace("success")], USER_TEXT)
    assert len(le.get_exact_workflow_candidates(USER_TEXT)) == 1
    assert le.get_exact_workflow_candidates("tìm tin tức nvidia rtx spark") == [], "rewritten sub-query must not be the key"


def test_failed_or_partial_run_is_not_saved():
    le = _engine(Path(tempfile.mkdtemp()))
    assert not _run(le, [_trace("failed")], USER_TEXT)
    assert not _run(le, [_trace("success"), _trace("no_result")], USER_TEXT)
    assert le.get_exact_workflow_candidates(USER_TEXT) == []


def test_complaint_makes_the_last_route_unlearned_and_stops_the_replay():
    """jarvis.log 2026-09-21: chat sentences ran search/notes without error, were learned as workflows,
    and were replayed by route_agents forever even though the user kept saying 'đó lại gọi agents'."""
    le = _engine(Path(tempfile.mkdtemp()))
    chat = "đang coi vấn đề ở đâu mà sao hoạt động vừa bị lỗi"
    assert _run(le, [_trace("success")], chat)
    assert len(le.get_exact_workflow_candidates(chat)) == 1, "precondition: it was learned"
    assert le.unlearn_last_route("đó lại gọi agents")
    assert le.get_exact_workflow_candidates(chat) == []
    conn = le._get_learning_db()
    assert conn.execute("SELECT status FROM agent_outcomes ORDER BY id DESC LIMIT 1").fetchone()["status"] == "misrouted"
    assert conn.execute("SELECT count(*) c FROM learnings WHERE type='routing_correction'").fetchone()["c"] == 1


def test_forget_sample_only_removes_that_query():
    le = _engine(Path(tempfile.mkdtemp()))
    assert _run(le, [_trace("success")], USER_TEXT)
    other = "tìm tin tức bão số 5"
    assert _run(le, [_trace("success")], other)
    assert le.forget_workflow_sample(USER_TEXT) == 1
    assert le.get_exact_workflow_candidates(USER_TEXT) == []
    assert len(le.get_exact_workflow_candidates(other)) == 1, "other samples of the same workflow stay"


if __name__ == "__main__":
    test_success_is_saved_and_matches_the_users_exact_words()
    test_failed_or_partial_run_is_not_saved()
    test_complaint_makes_the_last_route_unlearned_and_stops_the_replay()
    test_forget_sample_only_removes_that_query()
    print("OK: workflow reuse tests passed")
