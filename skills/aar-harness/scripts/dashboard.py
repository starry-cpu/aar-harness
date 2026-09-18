#!/usr/bin/env python3
"""dashboard.py -- render or serve the run observatory for one aar-harness run.

The page is a derived view: it is rebuilt from the run directory on demand and it
decides nothing (rundata.py delegates every verdict to aar_lib).  The output is a single
self-contained HTML file -- no CDN, no chart library, no fetch -- because the DSH sidebar
preview renders it in a sandboxed Blob iframe without same-origin.

  render  writes <run>/reports/dashboard.html and <run>/reports/dashboard.data.json
  serve   serves that same page on 127.0.0.1:<port>, re-rendering on every request and
          refreshing the same two files, so static and live are one artifact and the
          live page only needs location.reload()

  python scripts/dashboard.py render --run R [--reference-file ref.json] [--title T]
  python scripts/dashboard.py serve  --run R [--port 8787] [--interval 30]

--top N (default 200) caps how many findings are inlined into the page; the data file
always carries all of them.  --no-integrity skips the slow held-out tree scan.
"""

from __future__ import annotations

import argparse
import errno
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import aar_lib as A          # noqa: E402
import rundata as RD         # noqa: E402

TEMPLATE = HERE / "dashboard" / "template.html"
PLACEHOLDER = "__AAR_DASHBOARD_DATA__"
TITLE_PLACEHOLDER = "__AAR_TITLE__"
DEFAULT_TOP = 200
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_INTERVAL = 30
PORT_IN_USE = (errno.EADDRINUSE, errno.EACCES)


def say(text=""):
    """Print immediately: a backgrounded serve would otherwise sit in the pipe buffer."""
    print(text, flush=True)


def load_template(path=TEMPLATE):
    text = A.read_text(path)
    for placeholder in (PLACEHOLDER, TITLE_PLACEHOLDER):
        if placeholder not in text:
            raise ValueError("template has no " + placeholder + " placeholder: " + str(path))
    return text


def bundle_json(bundle):
    """Inline-safe JSON: a </script> inside a string can never close the data block."""
    return json.dumps(bundle, ensure_ascii=False, indent=2).replace("</", "<\\/")


def page_view(bundle, top):
    """The page inlines at most top findings; the data file always carries all of them."""
    rows = bundle.get("findings") or []
    if not top or top >= len(rows):
        return bundle
    view = dict(bundle)
    view["findings"] = rows[:top]
    return view


def render_page(bundle, template=None):
    title = str((bundle.get("run") or {}).get("title") or "AAR 运行")
    text = (template or load_template()).replace(PLACEHOLDER, bundle_json(bundle))
    return text.replace(TITLE_PLACEHOLDER, html.escape(title, quote=True))


def output_paths(run_dir, out=None, data_out=None):
    run = Path(run_dir)
    html = Path(out) if out else run / "reports" / "dashboard.html"
    # named after the page, so --out to a scratch path cannot clobber the canonical
    # dashboard.data.json next to the default page
    data = Path(data_out) if data_out else html.with_name(html.stem + ".data.json")
    return html, data


def write_outputs(run_dir, bundle, top=None, out=None, data_out=None):
    html, data = output_paths(run_dir, out, data_out)
    A.atomic_write_text(html, render_page(page_view(bundle, top)))
    A.atomic_write_json(data, bundle)
    return html, data


def summarize(bundle):
    w = bundle.get("winner") or {}
    s = bundle.get("status") or {}
    agg = w.get("aggregate")
    return ("%d 条 finding（内联 %d）· 冠军 %s aggregate=%s · 通过闸门 %s · 被排除 %s"
            % (bundle.get("findings_total", 0), len(bundle.get("findings") or []),
               w.get("method_id") or "—", "—" if agg is None else "%.6f" % agg,
               s.get("gates_pass"), s.get("excluded")))


def build(args, refresh=None):
    reference = RD.load_reference(getattr(args, "reference_file", None))
    return RD.build_bundle(args.run, title=getattr(args, "title", None), reference=reference,
                           integrity=not args.no_integrity, refresh=refresh)


# ------------------------------------------------------------------- render

def cmd_render(args):
    bundle = build(args)
    page, data = write_outputs(args.run, bundle, args.top, args.out, args.data_out)
    say("渲染完成：" + summarize(page_view(bundle, args.top)))
    say("  页面 " + str(page) + "  (" + str(page.stat().st_size) + " bytes)")
    say("  数据 " + str(data))
    return 0


# -------------------------------------------------------------------- serve

class Handler(BaseHTTPRequestHandler):
    server_version = "aar-dashboard/1"

    def do_GET(self):
        path = self.path.split("?")[0]
        if path not in ("/", "/index.html", "/data.json"):
            self.send_error(404, "only / and /data.json are served")
            return
        try:
            page_text, summary, bundle = self.server.render()
        except Exception as exc:            # a broken run must not kill the server
            body = ("dashboard render failed: " + type(exc).__name__ + ": " + str(exc)).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.server.log_line("render failed: " + str(exc))
            return
        if path == "/data.json":
            # The live bundle: the same object that was just written to
            # reports/dashboard.data.json.  One extraction per request, exactly like the
            # page, and deliberately no cache -- a cache here would go stale behind the
            # caller.  Polling this route costs what polling the page costs.
            body = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            self.server.log_line("served /data.json (" + str(len(body)) + " bytes)")
            return
        body = page_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.server.log_line("served / (" + str(len(body)) + " bytes) " + summary)

    def log_message(self, fmt, *args):      # keep the console for our own lines
        return


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second socket steal a busy port, which would turn
    # "port already in use" into a silent hijack; the handoff requires a loud failure.
    allow_reuse_address = False

    def __init__(self, addr, render):
        self.render = render
        super().__init__(addr, Handler)

    def log_line(self, text):
        say("[dashboard] " + text)


def port_error(exc, host, port):
    code = getattr(exc, "winerror", None) or exc.errno
    if code in (10048, 10013) or exc.errno in PORT_IN_USE:
        return ("错误：%s:%d 已被占用（或被系统保留）。换一个端口再试，例如 --port %d；"
                "本脚本不会静默换端口。" % (host, port, port + 1))
    return None


def cmd_serve(args):
    def render():
        """The served bytes and the file on disk are the same string from one bundle."""
        bundle = build(args, refresh=args.interval)
        view = page_view(bundle, args.top)
        page_text = render_page(view)
        page, data = output_paths(args.run, args.out, args.data_out)
        A.atomic_write_text(page, page_text)
        A.atomic_write_json(data, bundle)
        return page_text, summarize(view), bundle

    page, summary, _ = render()
    try:
        server = Server((args.host, args.port), render)
    except OSError as exc:
        message = port_error(exc, args.host, args.port)
        if message is None:
            raise
        say(message)
        return 1
    url = "http://%s:%d/" % (args.host, server.server_address[1])
    say("运行观测台已启动：" + url)
    say("  " + summary)
    say("  每 %d 秒整页重载一次；页面与静态 render 是同一份产物。" % args.interval)
    say("  按 Ctrl+C 停止（后台任务用 job_kill）。")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        say("")
    finally:
        server.server_close()
    return 0


# --------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="dashboard.py", description="render or serve the aar-harness run observatory")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(q):
        q.add_argument("--run", required=True, help="run directory")
        q.add_argument("--reference-file", default=None, help='optional {"name","per_bench","aggregate"} comparison entry')
        q.add_argument("--title", default=None, help="fallback title when run_config carries none")
        q.add_argument("--top", type=int, default=DEFAULT_TOP, help="findings inlined into the page (data file stays complete)")
        q.add_argument("--no-integrity", action="store_true", help="skip verify_forum and the held-out tree scan")
        q.add_argument("--out", default=None, help="HTML path (default <run>/reports/dashboard.html)")
        q.add_argument("--data-out", default=None, help="data JSON path (default next to the HTML)")

    q = sub.add_parser("render", help="write the static page and its data file")
    common(q)
    q.set_defaults(func=cmd_render)

    q = sub.add_parser("serve", help="serve the page on 127.0.0.1 and re-render on every request")
    common(q)
    q.add_argument("--host", default=DEFAULT_HOST)
    q.add_argument("--port", type=int, default=DEFAULT_PORT)
    q.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="seconds between whole-page reloads")
    q.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        say("错误：找不到 run 目录或文件：" + str(exc))
        return 1
    except ValueError as exc:
        say("错误：" + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
