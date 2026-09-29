"""Show RAW replies where the text mentions ask_user but ASK_RE found no well-formed tag (the PARSE column of
prompt_ablation). Decides whether PARSE is a parser bug (regex too strict) or the model writing the tag wrong.
Uses prompt variant B (spec §6). Run: PYTHONIOENCODING=utf-8 python .../parse_inspect.py [runs] [--gemma]
"""
import asyncio, os, re, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_ablation.py")
src = open(p, encoding="utf-8").read().replace("asyncio.run(main())", "")
ns = {"__file__": p, "__name__": "abl"}
exec(compile(src, p, "exec"), ns)


async def main():
    from engine.server.llm_server import call_llm
    system = ns["build_variants"]()["B"]
    found = 0
    for kind, text, _ in ns["CASES"]:
        for _ in range(ns["RUNS"]):
            r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                               stream=False, thinking=False)
            body = r.choices[0].message.content or ""
            if "ask_user" in body.lower() and not ns["ASK_RE"].search(body):
                found += 1
                tags = re.findall(r"</?\s*ask_user[^>]*>|\[/?ask_user\]|ask_user\s*[:=]", body, re.I)
                print(f"--- {kind} {text!r} finish={r.choices[0].finish_reason} tags={tags}")
                print("    TAIL:", repr(body[-260:]))
    print(f"\nmalformed/unparsed replies: {found}")

asyncio.run(main())
