"""The public health page, generated from the record and nothing else.

    python -m harness.site --out _site

Writes one self-contained HTML page (no JavaScript, no external assets) that
says how often the lab passes, how long it takes, which checks are flaky, and
what each recorded run did. GitHub Pages publishes it after every nightly run.

Every figure comes from `health/health.jsonl` through `report.summarize` and
`tolerance.assess`, the same functions that write HEALTH.md and the README
block, so the page cannot disagree with them. There is no hand-written number
on it. The one hand-written part, a note explaining a run, comes from
`health/notes.json` and is labelled as a note wherever it appears. This project has watched hand-kept claims about its own record go stale
within three runs; a page that quotes the record must be generated from it.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

from harness import report, tolerance

ROOT = Path(__file__).resolve().parents[1]
#: The repository the page links to. In GitHub Actions, GITHUB_REPOSITORY names
#: whichever repository is running, so a copy of this project links to itself
#: rather than to the original. Run locally, it falls back to the original.
REPO = "https://github.com/" + os.environ.get("GITHUB_REPOSITORY", "johnallred/coldlab")

#: Columns in the per-check grid. Older runs stay in the runs table and in the
#: record; the grid is for spotting a pattern, and a pattern is recent.
GRID_RUNS = 30

STYLE = """
:root { color-scheme: light dark; --ok: #1a7f37; --bad: #cf222e; --muted: #6e7781; }
body { font: 16px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; margin: 0 auto;
       max-width: 72rem; padding: 2rem 1rem 4rem; }
h1 { margin-bottom: .25rem; } .lede { color: var(--muted); margin-top: 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
         gap: 1rem; margin: 1.5rem 0; }
.tile { border: 1px solid #d0d7de; border-radius: 8px; padding: .75rem 1rem; }
.tile b { display: block; font-size: 1.6rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1.5rem; font-size: .9rem; }
caption { text-align: left; color: var(--muted); padding-bottom: .25rem; }
th, td { border-bottom: 1px solid #d0d7de; padding: .35rem .5rem; text-align: left;
         vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: var(--ok); } .bad { color: var(--bad); } .na { color: var(--muted); }
.grid td { text-align: center; } code { font-size: .85em; }
tr.note td { border-top: 0; padding-top: 0; color: inherit; font-size: .85rem; }
footer { color: var(--muted); font-size: .85rem; margin-top: 3rem; }
"""


def load_notes(path: str | Path) -> dict[str, str]:
    """Hand-written notes keyed by a run's started_at. Missing file, no notes."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: str(v) for k, v in raw.items() if not k.startswith("_")}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def first_line(text: str | None, limit: int = 140) -> str:
    """The error's first line, shortened. The full text is in the record."""
    if not text:
        return ""
    line = text.strip().splitlines()[0]
    return line if len(line) <= limit else line[: limit - 1] + "…"


def failing(record: dict) -> list[dict]:
    return [c for c in record.get("checks", []) if not c.get("ok")]


def mark(ok: bool | None) -> str:
    """A symbol and a word, so the meaning never rests on colour alone."""
    if ok is None:
        return '<span class="na" title="did not run">–<span hidden> not run</span></span>'
    if ok:
        return '<span class="ok" title="passed">✓<span hidden> passed</span></span>'
    return '<span class="bad" title="failed">✗<span hidden> failed</span></span>'


def tiles(summary: dict, records: list[dict]) -> list[str]:
    last = max(records, key=lambda r: r["started_at"])
    median = summary["median_seconds"]
    flaky = sum(1 for c in summary["checks"].values() if c["flaky"])
    cells = [
        ("Runs recorded", f"{summary['runs']}"),
        ("Pass rate", f"{summary['pass_rate'] * 100:.0f}%"
                      f" <small>({summary['passed']} of {summary['runs']})</small>"),
        ("Median duration", f"{median:.0f}s" if median is not None else "n/a"),
        ("Flaky checks", f"{flaky}"),
        ("Last run", ('<span class="ok">passed</span>' if last.get("passed")
                      else '<span class="bad">failed</span>')
                     + f" <small>{esc(last['started_at'][:16].replace('T', ' '))} UTC</small>"),
    ]
    out = ['<div class="tiles">']
    out += [f'<div class="tile">{label}<b>{value}</b></div>' for label, value in cells]
    out.append("</div>")
    return out


def flaky_section(summary: dict) -> list[str]:
    flaky = sorted(n for n, c in summary["checks"].items() if c["flaky"])
    out = ["<h2>Flaky checks</h2>"]
    if not flaky:
        return out + ["<p>No check has both passed and failed yet.</p>"]
    out.append("<p>These have both passed and failed. A check that sometimes fails is "
               "worse than one that always does, because the second gets fixed and the "
               "first gets blamed on the learner. Each is a defect in the lab, the "
               "harness or an assumption about eventual consistency.</p><ul>")
    for name in flaky:
        c = summary["checks"][name]
        kind = "gating" if c["gating"] else "advisory"
        out.append(f"<li><code>{esc(name)}</code>: {c['failures']} of {c['runs']} runs "
                   f"failed ({kind})</li>")
    return out + ["</ul>"]


def tolerance_section(records: list[dict]) -> list[str]:
    assessment = tolerance.assess(records)
    if not assessment.observations:
        return []
    out = ["<h2>Redrive timing</h2>",
           f"<p>The redrive check is advisory until the record can set its tolerance. "
           f"Verdict: <b>{esc(assessment.verdict)}</b>; "
           + esc("; ".join(assessment.reasons)) + ".</p>"]
    if assessment.band:
        low, high = assessment.band
        out.append(f"<p>Band the record supports: {low:.0f} to {high:.0f} seconds.</p>")
    seen = ", ".join(f"{o.seconds:.0f}s" for o in assessment.observations)
    return out + [f"<p>Observed: {esc(seen)}.</p>"]


def runs_table(records: list[dict], notes: dict[str, str] | None = None) -> list[str]:
    notes = notes or {}
    out = ["<h2>Every run</h2>", "<table>",
           "<caption>Newest first. Failing advisory checks are listed but do not "
           "fail a run. Notes are written by hand in "
           f'<a href="{REPO}/blob/main/health/notes.json">health/notes.json</a>; '
           "everything else is generated.</caption>",
           "<thead><tr><th scope=col>Started (UTC)</th><th scope=col>Result</th>"
           "<th scope=col>Duration</th><th scope=col>Redrive</th>"
           "<th scope=col>Failed checks</th><th scope=col>Stopped by</th></tr></thead><tbody>"]
    for r in sorted(records, key=lambda r: r["started_at"], reverse=True):
        result = ('<span class="ok">✓ passed</span>' if r.get("passed")
                  else '<span class="bad">✗ failed</span>')
        redrive = (r.get("measurements") or {}).get("redrive_seconds")
        checks = ", ".join(
            f"<code>{esc(c['name'])}</code>" + ("" if c.get("gating", True) else " (advisory)")
            for c in failing(r)) or ("none" if r.get("passed")
                                     else "none; it stopped before the lab's checks ran")
        seconds = r.get("seconds")
        out.append(
            f"<tr><td>{esc(r['started_at'][:16].replace('T', ' '))}</td><td>{result}</td>"
            f"<td class=n>{'' if seconds is None else f'{seconds:.0f}s'}</td>"
            f"<td class=n>{'' if redrive is None else f'{redrive:.0f}s'}</td>"
            f"<td>{checks}</td><td>{esc(first_line(r.get('error')))}</td></tr>")
        note = notes.get(r["started_at"])
        if note:
            out.append(f'<tr class=note><td></td><td colspan=5><b>What happened</b> '
                       f'<small>(note, written by hand)</small>: {esc(note)}</td></tr>')
    return out + ["</tbody></table>"]


def grid(records: list[dict]) -> list[str]:
    recent = sorted(records, key=lambda r: r["started_at"])[-GRID_RUNS:]
    names = sorted({c["name"] for r in recent for c in r.get("checks", [])})
    gating = {c["name"]: c.get("gating", True) for r in recent for c in r.get("checks", [])}
    head = "".join(f"<th scope=col>{esc(r['started_at'][5:10])}<br>"
                   f"{esc(r['started_at'][11:16])}</th>" for r in recent)
    out = ["<h2>Each check, run by run</h2>", '<table class="grid">',
           f"<caption>The last {len(recent)} runs, oldest on the left. – means the "
           "check did not run, because the run stopped before it.</caption>",
           f"<thead><tr><th scope=col>Check</th>{head}</tr></thead><tbody>"]
    for name in names:
        cells = []
        for r in recent:
            found = next((c for c in r.get("checks", []) if c["name"] == name), None)
            cells.append(f"<td>{mark(None if found is None else bool(found['ok']))}</td>")
        label = f"<code>{esc(name)}</code>" + ("" if gating[name] else " <small>advisory</small>")
        out.append(f"<tr><th scope=row>{label}</th>{''.join(cells)}</tr>")
    return out + ["</tbody></table>"]


def render(records: list[dict], notes: dict[str, str] | None = None) -> str:
    summary = report.summarize(records)
    body = [
        "<h1>coldlab lab health</h1>",
        '<p class="lede">One hands-on AWS lab, provisioned, run, checked and torn down '
        "every night, with every run recorded.</p>",
        f'<p>The harness deploys the lab with the AWS CDK, runs the commands '
        f'<a href="{REPO}/blob/main/lab/sqs-retry/lab.md">the lab document</a> tells a '
        "student to type, asserts on what AWS actually did, tears the stack down and "
        "proves nothing was left behind. This page is generated from "
        f'<a href="{REPO}/blob/main/health/health.jsonl">the record</a> after each run; '
        "nothing on it is written by hand. What it does not prove, including account "
        f'vending and a catalogue of labs, is listed in <a href="{REPO}#what-it-deliberately-does-not-prove">'
        "the README</a>.</p>",
    ]
    if not records:
        body.append("<p>No runs recorded yet.</p>")
    else:
        body += tiles(summary, records)
        body += flaky_section(summary)
        body += tolerance_section(records)
        body += runs_table(records, notes)
        body += grid(records)
        first = min(r["started_at"] for r in records)[:10]
        last = max(r["started_at"] for r in records)[:16].replace("T", " ")
        body.append(f"<footer>Generated by <code>python -m harness.site</code> from "
                    f"{summary['runs']} records, {esc(first)} to {esc(last)} UTC. "
                    f'Source: <a href="{REPO}">{esc(REPO)}</a>.</footer>')
    return ("<!DOCTYPE html>\n<html lang=en>\n<head>\n<meta charset=utf-8>\n"
            '<meta name=viewport content="width=device-width, initial-scale=1">\n'
            "<title>coldlab lab health</title>\n"
            '<meta name=description content="Nightly health of a hands-on AWS lab: '
            'pass rate, duration, flaky checks and every recorded run.">\n'
            f"<style>{STYLE}</style>\n</head>\n<body>\n<main>\n"
            + "\n".join(body) + "\n</main>\n</body>\n</html>\n")


def build(records: list[dict], out: str | Path,
          notes: dict[str, str] | None = None) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    page.write_text(render(records, notes), encoding="utf-8")
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", default=str(ROOT / "health" / "health.jsonl"))
    parser.add_argument("--notes", default=str(ROOT / "health" / "notes.json"))
    parser.add_argument("--out", default=str(ROOT / "_site"))
    args = parser.parse_args(argv)
    page = build(report.load_records(args.record), args.out, load_notes(args.notes))
    print(f"wrote {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
