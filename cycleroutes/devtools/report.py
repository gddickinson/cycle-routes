"""HTML contact sheet for a screenshot run (open report.html in a browser)."""

from html import escape
from pathlib import Path

from cycleroutes.devtools.session import Shot

CSS = """
:root { --bg:#f6f7f5; --card:#fff; --text:#1d2320; --muted:#5d6762; --line:#dde2de;
        --ok:#1a7f37; --bad:#d1343a; }
@media (prefers-color-scheme: dark) { :root { --bg:#141816; --card:#1e2421; --text:#e7ece9;
        --muted:#9aa5a0; --line:#333b38; --ok:#3fb866; --bad:#ff6b6b; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--text);
       font:15px/1.45 system-ui,-apple-system,sans-serif; }
main { max-width:1200px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
.summary { color:var(--muted); margin:0 0 20px; }
.summary b.ok { color:var(--ok); } .summary b.bad { color:var(--bad); }
h2 { font-size:17px; margin:28px 0 10px; text-transform:capitalize; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
figure.fail { border-color:var(--bad); box-shadow:0 0 0 1px var(--bad) inset; }
figure a img { display:block; width:100%; height:auto; max-height:520px; object-fit:contain;
               background:#ddd; border-bottom:1px solid var(--line); }
figcaption { padding:10px 12px; font-size:13.5px; }
.title { font-weight:650; }
ul { list-style:none; margin:6px 0 0; padding:0; font-size:12.5px; }
li { padding:1px 0; } li.ok::before { content:"✓ "; color:var(--ok); }
li.bad { color:var(--bad); } li.bad::before { content:"✗ "; }
li small { color:var(--muted); }
"""


def write_report(out_dir: Path, shots: list[Shot], meta: dict) -> Path:
    failed = [s for s in shots if not s.ok]
    n_checks = sum(len(s.checks) for s in shots)
    groups: dict[str, list[Shot]] = {}
    for s in shots:
        groups.setdefault(s.group, []).append(s)

    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Screenshot Check</title><style>{CSS}</style></head><body><main>",
             "<h1>Cycle Routes — screenshot check</h1>",
             f"<p class='summary'>{escape(meta['started'])} · region <b>{escape(meta['region'])}</b> · "
             f"{len(shots)} screenshots · {n_checks} checks · "
             + (f"<b class='bad'>{len(failed)} screenshot(s) with problems</b>" if failed
                else "<b class='ok'>all checks passed</b>") + "</p>"]
    for group, items in groups.items():
        parts.append(f"<h2>{escape(group)}</h2><div class='grid'>")
        for s in items:
            rows = [f"<li class='{'ok' if c['ok'] else 'bad'}'>{escape(c['label'])}"
                    + (f" <small>{escape(c['detail'])}</small>" if c["detail"] and not c["ok"] else "")
                    + "</li>" for c in s.checks]
            rows += [f"<li class='bad'>{escape(p)}</li>" for p in s.problems]
            parts.append(
                f"<figure class='{'' if s.ok else 'fail'}'><a href='{s.file}' target='_blank'>"
                f"<img src='{s.file}' alt='{escape(s.caption)}' loading='lazy'></a>"
                f"<figcaption><div class='title'>{s.index:02d} · {escape(s.name.replace('_', ' '))}</div>"
                f"{escape(s.caption)}<ul>{''.join(rows)}</ul></figcaption></figure>")
        parts.append("</div>")
    parts.append("</main></body></html>")
    path = out_dir / "report.html"
    path.write_text("".join(parts))
    return path
