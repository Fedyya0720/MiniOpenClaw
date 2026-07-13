"""最小消融：有/无 system-prompt 两组样本轨迹的成功率对比。"""
from eval.tasks import SAMPLE_TASKS
from eval.metrics import success_rate, token_count

GROUP_WITH_SYS = [
    {"task": "read-config",
     "steps": [{"tool_calls": [{"name": "read", "arguments": {"path": "config.json"}}],
                "raw": '<tool_call>{"name":"read","arguments":{"path":"config.json"}}</tool_call>',
                "prompt_tokens": 330, "completion_tokens": 22}],
     "final": "config.json 里 timeout = 30 秒。"},
    {"task": "list-dir",
     "steps": [{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}],
                "raw": '<tool_call>{"name":"bash","arguments":{"command":"ls"}}</tool_call>',
                "prompt_tokens": 300, "completion_tokens": 18}],
     "final": "当前目录有：main.py config.json README.md"},
    {"task": "read-code",
     "steps": [{"tool_calls": [{"name": "read", "arguments": {"path": "main.py"}}],
                "raw": '<tool_call>{"name":"read","arguments":{"path":"main.py"}}</tool_call>',
                "prompt_tokens": 340, "completion_tokens": 25}],
     "final": "main.py 里有一个 greet 函数，功能是打印问候语。"},
]

GROUP_NO_SYS = [
    {"task": "read-config",
     "steps": [{"tool_calls": [], "raw": "timeout 应该是个常见的默认值。",
                "prompt_tokens": 120, "completion_tokens": 14}],
     "final": "timeout 应该是个常见的默认值。"},
    {"task": "list-dir",
     "steps": [{"tool_calls": [], "raw": "你可以自己用 ls 看看。",
                "prompt_tokens": 110, "completion_tokens": 12}],
     "final": "你可以自己用 ls 看看。"},
    {"task": "read-code",
     "steps": [{"tool_calls": [], "raw": "我不知道 main.py 里有什么。",
                "prompt_tokens": 100, "completion_tokens": 10}],
     "final": "我不知道 main.py 里有什么。"},
]

def summarize(name, recs):
    sr = success_rate(SAMPLE_TASKS, recs)
    avg_tok = sum(token_count(r) for r in recs) / len(recs)
    print(f"{name:16s} 成功率={sr:.2f}  平均token={avg_tok:.0f}")
    return sr

if __name__ == "__main__":
    print("=== 消融：有/无 system-prompt ===")
    a = summarize("有 system-prompt", GROUP_WITH_SYS)
    b = summarize("无 system-prompt", GROUP_NO_SYS)
    print(f"结论：system-prompt 使成功率 {b:.2f} -> {a:.2f}（Δ={a-b:+.2f}）")

    # -- PACS B3 ablation: serial vs parallel (Phase 5) --
    from eval.metrics import PACS_ABLATION_RUNS as runs, pacs_attempt_count, pacs_t_success
    serial = [r for r in runs if r.get("mode") == "serial"]
    parallel = [r for r in runs if r.get("mode") == "parallel"]
    if serial and parallel:
        s, p = serial[0], parallel[0]
        s_att, p_att = pacs_attempt_count(s), pacs_attempt_count(p)
        print()
        print("=== PACS 消融：串行 vs 并行（B3）===")
        print(f"串行基线 N_attempts  = {s_att}  ({s.get('t_success')}s)")
        print(f"并行搜索 N_attempts  = {p_att}  ({p.get('t_success')}s)")
        print(f"结论：并行减少 {s_att - p_att} 次尝试"
              f"（Δ={s_att - p_att}，减少 {(s_att - p_att) / max(s_att, 1) * 100:.0f}%）")
