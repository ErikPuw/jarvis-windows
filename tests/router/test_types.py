import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router.types import NoOpTracker, RouteDecision, TurnContext


def test_turn_context_defaults_to_noop_trackers():
    ctx = TurnContext(ws=object(), send_json=None)
    assert isinstance(ctx.flow_tracker, NoOpTracker) and isinstance(ctx.flow_agents, NoOpTracker)
    assert ctx.conversation_history == []

    async def use():
        async with ctx.flow_tracker.step("x", agent_name="a") as step:
            step.label = "y"  # server.py gán label sau khi định tuyến
        await ctx.flow_agents.track("a")
        await ctx.flow_agents.fail_all_active()
        await ctx.flow_agents.complete_all_active()
    asyncio.run(use())


def test_route_decision_fields():
    d = RouteDecision("agent", "xem thư", "mention", agent="email")
    assert (d.kind, d.query, d.source, d.agent, d.workflow) == ("agent", "xem thư", "mention", "email", None)


if __name__ == "__main__":
    test_turn_context_defaults_to_noop_trackers(); test_route_decision_fields(); print("OK")
