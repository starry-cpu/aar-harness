"""agent_run.py -- shared helpers for driving dsh headless sessions as judges.

Used by orchestrator.py (in-loop monitors) and review.py (post-hoc review).  Kept in
one place because a second copy of the process-tree kill logic is how you get a
headless grandchild that survives a timeout and hangs the parent forever.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import threading

from pathlib import Path

NL = chr(10)


def resolve_dsh():
    """Windows cannot CreateProcess a .cmd directly, so route shims through cmd.exe."""
    exe = shutil.which("dsh") or shutil.which("dsh.cmd")
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe]
    return [exe]


def _drain(stream, buf):
    try:
        for line in iter(stream.readline, ""):
            buf.append(line)
    except (ValueError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def kill_tree(pid):
    """Kill the whole tree: killing only the direct child leaves the node grandchild
    alive holding the pipes open, which hangs the reader forever."""
    if os.name == "nt":
        with contextlib.suppress(Exception):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)
    else:
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(pid), 9)


def run_headless(argv, cwd, timeout):
    """Run a child with streamed capture so a timeout still yields partial output."""
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", creationflags=flags)
    out_buf, err_buf = [], []
    t_out = threading.Thread(target=_drain, args=(proc.stdout, out_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, err_buf), daemon=True)
    t_out.start()
    t_err.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
    t_out.join(timeout=15)
    t_err.join(timeout=15)
    return (124 if timed_out else proc.returncode), "".join(out_buf), "".join(err_buf)


def ask(prompt_path, workdir, timeout):
    """Hand one prompt file to a fresh headless session and collect its answer."""
    prefix = resolve_dsh()
    if prefix is None:
        raise RuntimeError("dsh CLI not found on PATH")
    task = "Read " + str(prompt_path) + " and do exactly what it says. Do not ask questions."
    return run_headless(prefix + ["--profile", "headless", task], str(workdir), timeout)


def extract_template(prompts_path, name):
    """First fenced block following the heading that contains `name`."""
    text = Path(prompts_path).read_text(encoding="utf-8")
    lines = text.split(NL)
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and name in ln:
            start = i
            break
    if start is None:
        raise KeyError("no heading containing " + name + " in " + str(prompts_path))
    block = []
    inside = False
    for ln in lines[start:]:
        if ln.strip().startswith("```"):
            if not inside:
                inside = True
                continue
            break
        if inside:
            block.append(ln)
    if not block:
        raise ValueError("no fenced block after heading " + name)
    return NL.join(block)


def fill(template, values):
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def parse_json_object(text):
    """Last balanced JSON object in the text, tolerating prose around it."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
