"""A tiny product to film — stdlib only, no network beyond localhost.

`capture-kit` exists so that "vidkit can film a real download" is a claim a
machine can check. It is the smallest thing that behaves like a product page:

* a table that is **empty when the page loads** and fills in after a beat, so a
  capture that does not wait records the wrong state — which is the point;
* a date filter that changes the numbers, so an action script has something real
  to do;
* two download endpoints serving real bytes — a CSV of the very rows on screen
  and a one-page PDF — so an ``artifact:`` capture has something real to film.

Nothing here is a mock of a product; it *is* a small product, and every number it
renders is computed from the same rows the CSV contains.

    python3 examples/capture-kit/server.py --port 8765
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROWS: list[dict[str, object]] = [
    {"day": "2026-09-07", "channel": "search", "visits": 1840, "signups": 96},
    {"day": "2026-09-14", "channel": "search", "visits": 1962, "signups": 104},
    {"day": "2026-09-21", "channel": "direct", "visits": 1204, "signups": 71},
    {"day": "2026-09-28", "channel": "direct", "visits": 1130, "signups": 66},
    {"day": "2026-10-05", "channel": "partner", "visits": 880, "signups": 58},
]

_PERIODS = {"30": 3, "60": 5}

INDEX = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>capture-kit — usage</title><style>
  body { margin:0; background:#f6f7f9; color:#1b1f24;
         font:15px/1.5 ui-sans-serif, system-ui, sans-serif }
  header { background:#fff; border-bottom:1px solid #e3e6ea; padding:16px 28px }
  h1 { margin:0; font-size:18px }
  main { padding:22px 28px; max-width:900px }
  .bar { display:flex; gap:16px; align-items:center; margin-bottom:18px }
  label { color:#5b6570; font-size:13px }
  select, button, a.button { font:inherit; font-size:14px; padding:6px 10px;
         border:1px solid #ccd2d9; border-radius:6px; background:#fff;
         color:#1b1f24; text-decoration:none; cursor:pointer }
  table { border-collapse:collapse; background:#fff; width:100%; font-size:14px }
  th, td { border:1px solid #e3e6ea; padding:7px 11px; text-align:left }
  th { background:#eef1f4 }
  #summary { margin-top:14px; color:#5b6570; font-size:13px }
  #empty { color:#8a929b; font-size:13px }
</style></head><body>
<header><h1>capture-kit — usage</h1></header>
<main>
  <div class="bar">
    <label for="period">Period</label>
    <select id="period">
      <option value="30">Last 30 days</option>
      <option value="60">Last 60 days</option>
    </select>
    <button id="apply">Apply</button>
    <a class="button" id="csv" href="/downloads/usage.csv">Download CSV</a>
    <a class="button" id="pdf" href="/downloads/summary.pdf">Download PDF</a>
  </div>
  <table id="usage">
    <thead><tr><th>Day</th><th>Channel</th><th>Visits</th><th>Signups</th></tr></thead>
    <tbody></tbody>
  </table>
  <div id="empty">loading …</div>
  <div id="summary" class="summary"></div>
</main>
<script>
  async function load() {
    const period = document.getElementById('period').value;
    const res = await fetch('/api/usage?days=' + period);
    const data = await res.json();
    const body = document.querySelector('#usage tbody');
    body.innerHTML = data.rows.map(r =>
      `<tr><td>${r.day}</td><td>${r.channel}</td>` +
      `<td>${r.visits}</td><td>${r.signups}</td></tr>`).join('');
    // Guarded: Apply can be pressed again, and a page that throws on the
    // second render is a broken page, not a fixture.
    const empty = document.getElementById('empty');
    if (empty) empty.remove();
    document.getElementById('summary').textContent =
      `${data.rows.length} rows · ${data.totals.visits} visits · ` +
      `${data.totals.signups} signups`;
    document.getElementById('csv').href = '/downloads/usage.csv?days=' + period;
  }
  document.getElementById('apply').addEventListener('click', load);
  // The beat: the table is deliberately not there yet when the page paints.
  setTimeout(load, 700);
</script>
</body></html>
"""


def _rows(days: int) -> list[dict[str, object]]:
    take = _PERIODS.get(str(days), len(ROWS))
    return ROWS[-take:]


def _csv(rows: list[dict[str, object]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["day", "channel", "visits", "signups"],
                       lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _totals(rows: list[dict[str, object]]) -> dict[str, int]:
    return {"visits": sum(int(r["visits"]) for r in rows),
            "signups": sum(int(r["signups"]) for r in rows)}


def _pdf(rows: list[dict[str, object]]) -> bytes:
    """A real, one-page PDF that poppler and Ghostscript both accept."""
    lines = ["capture-kit usage summary", ""]
    lines += [f"{r['day']}  {r['channel']}  {r['visits']} visits  {r['signups']} signups"
              for r in rows]
    totals = _totals(rows)
    lines += ["", f"total  {totals['visits']} visits  {totals['signups']} signups"]
    text = "".join(f"BT /F1 12 Tf 60 {740 - i * 22} Td ({ln}) Tj ET\n"
                   for i, ln in enumerate(lines))
    content = text.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{start}\n%%EOF\n").encode()
    return bytes(out)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # keep the CI log readable
        pass

    def _send(self, body: bytes, ctype: str, *, filename: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _days(self) -> int:
        if "?" not in self.path:
            return len(ROWS)
        import urllib.parse
        q = urllib.parse.parse_qs(self.path.split("?", 1)[1])
        try:
            return int(q.get("days", [len(ROWS)])[0])
        except ValueError:
            return len(ROWS)

    def do_GET(self) -> None:  # noqa: N802 - http.server's spelling
        path = self.path.split("?", 1)[0]
        rows = _rows(self._days())
        if path == "/":
            self._send(INDEX.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/usage":
            payload = json.dumps({"rows": rows, "totals": _totals(rows)})
            self._send(payload.encode("utf-8"), "application/json")
        elif path == "/downloads/usage.csv":
            self._send(_csv(rows), "text/csv", filename="usage.csv")
        elif path == "/downloads/summary.pdf":
            self._send(_pdf(rows), "application/pdf", filename="summary.pdf")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


def serve(port: int = 0, host: str = "127.0.0.1") -> tuple[ThreadingHTTPServer, str]:
    """Start the site on a background thread; return the server and its URL."""
    import threading

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://{host}:{httpd.server_address[1]}/"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print(f"capture-kit on http://{args.host}:{httpd.server_address[1]}/  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
