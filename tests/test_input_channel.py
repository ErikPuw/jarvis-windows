"""Tests for the WebUI/Telegram input-channel handover in server.py.

Exercises the arbitration functions in isolation — no server is started.
Run: python tests/test_input_channel.py
"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_arbiter():
    """Load just the channel-arbitration code without importing all of server.py.

    server.py boots FastAPI, the LLM clients and the whole engine at import
    time, which a unit test has no business doing.
    """
    import ast
    source = (Path(__file__).parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_funcs = {
        "register_channel_release_hook", "_run_channel_release_hook",
        "try_acquire_input_channel", "release_input_channel",
        "_get_input_channel_free",
    }
    wanted_assigns = {
        "_active_input_channel", "_active_input_owner", "_input_channel_lock",
        "_input_channel_free", "_previous_input_channel", "_channel_release_hooks",
    }
    kept = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted_funcs:
            kept.append(node)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & wanted_assigns:
                kept.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in wanted_assigns:
                kept.append(node)

    module = types.ModuleType("jarvis_channel_arbiter")
    module.__dict__.update(
        asyncio=asyncio, os=__import__("os"),
        log=__import__("logging").getLogger("test.arbiter"),
        Any=object,
    )
    exec(compile(ast.Module(body=kept, type_ignores=[]), "<arbiter>", "exec"), module.__dict__)
    return module


ARB = _load_arbiter()


def _reset():
    ARB._active_input_channel = None
    ARB._active_input_owner = None
    ARB._previous_input_channel = None
    ARB._channel_release_hooks.clear()
    # Each test runs its own event loop; drop the cached Event so it rebinds.
    ARB._input_channel_free = None
    ARB._input_channel_lock = asyncio.Lock()


def test_first_caller_acquires():
    async def scenario():
        _reset()
        return await ARB.try_acquire_input_channel("webui", wait_seconds=0)
    assert asyncio.run(scenario()) is not None


def test_second_channel_waits_then_gets_it_when_the_turn_ends():
    """It used to fail instantly, so talking on one channel mid-turn on the
    other just produced 'try again later'."""
    async def scenario():
        _reset()
        owner = await ARB.try_acquire_input_channel("telegram", wait_seconds=0)

        async def finish_turn():
            await asyncio.sleep(0.1)
            await ARB.release_input_channel("telegram", owner)

        asyncio.create_task(finish_turn())
        return await ARB.try_acquire_input_channel("webui", wait_seconds=5)
    assert asyncio.run(scenario()) is not None, "webui never got the channel after telegram finished"


def test_gives_up_after_the_wait_budget():
    async def scenario():
        _reset()
        await ARB.try_acquire_input_channel("telegram", wait_seconds=0)
        return await ARB.try_acquire_input_channel("webui", wait_seconds=0.2)
    assert asyncio.run(scenario()) is None


def test_handover_frees_the_outgoing_channel_buffers():
    async def scenario():
        _reset()
        freed = []
        ARB.register_channel_release_hook("telegram", lambda: freed.append("telegram"))
        owner = await ARB.try_acquire_input_channel("telegram", wait_seconds=0)
        await ARB.release_input_channel("telegram", owner)
        await ARB.try_acquire_input_channel("webui", wait_seconds=0)
        return freed
    assert asyncio.run(scenario()) == ["telegram"], "outgoing channel kept its cached session state"


def test_same_channel_twice_does_not_free_its_own_buffers():
    async def scenario():
        _reset()
        freed = []
        ARB.register_channel_release_hook("webui", lambda: freed.append("webui"))
        owner = await ARB.try_acquire_input_channel("webui", wait_seconds=0)
        await ARB.release_input_channel("webui", owner)
        await ARB.try_acquire_input_channel("webui", wait_seconds=0)
        return freed
    assert asyncio.run(scenario()) == [], "a channel wiped its own history between its own turns"


def test_a_failing_release_hook_does_not_block_the_handover():
    async def scenario():
        _reset()
        def boom():
            raise RuntimeError("hook exploded")
        ARB.register_channel_release_hook("telegram", boom)
        owner = await ARB.try_acquire_input_channel("telegram", wait_seconds=0)
        await ARB.release_input_channel("telegram", owner)
        return await ARB.try_acquire_input_channel("webui", wait_seconds=0)
    assert asyncio.run(scenario()) is not None


def test_release_by_a_stale_owner_is_ignored():
    async def scenario():
        _reset()
        await ARB.try_acquire_input_channel("webui", wait_seconds=0)
        await ARB.release_input_channel("webui", object())  # not the real owner
        return await ARB.try_acquire_input_channel("telegram", wait_seconds=0.2)
    assert asyncio.run(scenario()) is None, "a stale owner released someone else's channel"


if __name__ == "__main__":
    test_first_caller_acquires()
    test_second_channel_waits_then_gets_it_when_the_turn_ends()
    test_gives_up_after_the_wait_budget()
    test_handover_frees_the_outgoing_channel_buffers()
    test_same_channel_twice_does_not_free_its_own_buffers()
    test_a_failing_release_hook_does_not_block_the_handover()
    test_release_by_a_stale_owner_is_ignored()
    print("OK: all input channel handover tests passed")
