import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
META = ROOT / "data" / "repos.json"
SELF = "readme-rag-eval"


def gh(path):
    out = subprocess.run(["gh", "api", "--paginate", "--slurp", path], capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="replace")[:200])
    return [item for page in json.loads(out.stdout) for item in page]


def public_repos(user):
    repos = gh(f"users/{user}/repos?type=owner&per_page=100")
    return sorted((r for r in repos
                   if not r["private"] and not r["fork"] and r["name"] != SELF),
                  key=lambda r: r["name"].lower())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Fetch the READMEs of all public repositories of a GitHub user.")
    parser.add_argument("--user", default="donghyeoni")
    args = parser.parse_args()

    DOCS.mkdir(exist_ok=True)
    META.parent.mkdir(exist_ok=True)
    for old in DOCS.glob("*.md"):
        old.unlink()

    meta = []
    for r in public_repos(args.user):
        out = subprocess.run(
            ["gh", "api", f"repos/{args.user}/{r['name']}/readme",
             "-H", "Accept: application/vnd.github.raw"], capture_output=True)
        has_readme = out.returncode == 0
        if has_readme:
            (DOCS / f"{r['name']}.md").write_bytes(out.stdout)
        meta.append(dict(name=r["name"], language=r["language"], description=r["description"],
                         topics=r.get("topics", []), created=r["created_at"][:10],
                         pushed=r["pushed_at"][:10], stars=r["stargazers_count"],
                         readme=has_readme))
        print(f"{r['name']:<32} {len(out.stdout) if has_readme else 0:>7,} bytes")

    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(meta)} repos, {sum(m['readme'] for m in meta)} READMEs -> {DOCS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
