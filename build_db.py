import json
import pathlib
import re
import sqlite3
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent
DB = ROOT / "meta.db"
DOCS = ROOT / "docs"
META = ROOT / "data" / "repos.json"

SCHEMA = """
DROP TABLE IF EXISTS cells;
DROP TABLE IF EXISTS repos;
CREATE TABLE repos (
  name TEXT PRIMARY KEY, language TEXT, description TEXT, topics TEXT,
  created TEXT, pushed TEXT,
  started TEXT, ended TEXT, duration_days INTEGER
);
CREATE TABLE cells (
  repo TEXT REFERENCES repos(name),
  section TEXT, table_no INTEGER, row_no INTEGER,
  row_label TEXT, col TEXT, value TEXT, number REAL
);
"""

PERIOD = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s*[–-]\s*(\d{4})\.(\d{2})\.(\d{2})")
NUMBER = re.compile(r"(?:(?<![\w)\]])[-+])?(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
PIPE = re.compile(r"(?<!\\)\|")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BOLD_TITLE = re.compile(r"^\*\*(.+?)\*\*")


def period(text):
    head = "\n".join(text.splitlines()[:12])
    spans = [(date(int(a), int(b), int(c)), date(int(d), int(e), int(f)))
             for a, b, c, d, e, f in PERIOD.findall(head)]
    if not spans:
        return None, None, None
    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    return start.isoformat(), end.isoformat(), (end - start).days


def clean(cell):
    return re.sub(r"[*`]", "", cell).strip()


def split_row(line):
    return [clean(c).replace("\\|", "|") for c in PIPE.split(line.strip().strip("|"))]


def number(value):
    m = NUMBER.search(value.replace("−", "-"))
    return float(m.group().replace(",", "")) if m else None


def tables(text):
    lines = text.splitlines()
    section, found, i = "", [], 0
    while i < len(lines):
        line = lines[i]
        h = HEADING.match(line)
        b = BOLD_TITLE.match(line)
        if h:
            section = clean(h.group(2))
        elif b and not line.startswith("|"):
            section = clean(b.group(1))
        if (line.startswith("|") and i + 1 < len(lines)
                and re.fullmatch(r"\|?\s*:?-{3,}.*", lines[i + 1].strip())):
            header = split_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            found.append((section, header, rows))
            continue
        i += 1
    return found


def main() -> None:
    meta = json.loads(META.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    for m in meta:
        path = DOCS / f"{m['name']}.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        con.execute("INSERT INTO repos VALUES (?,?,?,?,?,?,?,?,?)",
                    (m["name"], m["language"], m["description"], ",".join(m["topics"]),
                     m["created"], m["pushed"], *period(text)))
        for t, (section, header, rows) in enumerate(tables(text), 1):
            for r, row in enumerate(rows, 1):
                label = row[0] if row else ""
                for col, value in zip(header[1:], row[1:]):
                    con.execute("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)",
                                (m["name"], section, t, r, label, col, value, number(value)))
    con.commit()
    n_repo = con.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    n_cell = con.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
    n_num = con.execute("SELECT COUNT(*) FROM cells WHERE number IS NOT NULL").fetchone()[0]
    con.close()
    print(f"{DB.name}: repos={n_repo} cells={n_cell} numeric={n_num}")


if __name__ == "__main__":
    main()
