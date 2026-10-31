import argparse
import json
import os
import sys
from pathlib import Path

from converter import ROOT, ConversionError, convert

DEFAULT_MODEL = "claude-sonnet-5-5"
DEMO_RESPONSE = ROOT / "examples" / "tasks.json"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
PRIORITY_TITLES = {"high": "High priority", "medium": "Medium priority", "low": "Low priority"}


def claude(model):
    import anthropic

    client = anthropic.Anthropic()

    def complete(system, messages):
        reply = client.messages.create(model=model, max_tokens=8000, system=system, messages=messages)
        return reply.content[0].text

    return complete


def render_markdown(data):
    lines = ["# Task list", "", data["project_summary"], ""]
    tasks = sorted(data["tasks"], key=lambda t: (PRIORITY_ORDER[t["priority"]], t["id"]))
    for priority, title in PRIORITY_TITLES.items():
        group = [t for t in tasks if t["priority"] == priority]
        if not group:
            continue
        lines += [f"## {title}", ""]
        for t in group:
            lines += [f"### {t['id']} - {t['title']}", "", t["description"], "", "Acceptance criteria:"]
            lines += [f"- {c}" for c in t["acceptance_criteria"]]
            if t["depends_on"]:
                lines += ["", "Depends on: " + ", ".join(t["depends_on"])]
            lines += ["", f"> {t['source_quote']}", ""]
    if data["open_questions"]:
        lines += ["## Open questions for the customer", ""]
        lines += [f"- {q}" for q in data["open_questions"]]
        lines.append("")
    return "\n".join(lines)


def format_summary(data):
    tasks = sorted(data["tasks"], key=lambda t: (PRIORITY_ORDER[t["priority"]], t["id"]))
    width = max(len(t["title"]) for t in tasks)
    rows = [f"{'ID':<6}{'Priority':<10}Title", f"{'-' * 5} {'-' * 9} {'-' * width}"]
    rows += [f"{t['id']:<6}{t['priority']:<10}{t['title']}" for t in tasks]
    return "\n".join(rows)


def main(argv=None, complete=None):
    parser = argparse.ArgumentParser(description="Turn customer requirements into a validated task list.")
    parser.add_argument("requirements", help="text file with the customer requirements")
    parser.add_argument("-o", "--out-dir", default="output", help="where tasks.json and tasks.md go (default: %(default)s)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Claude model id (default: %(default)s)")
    parser.add_argument("--max-attempts", type=int, default=3, help="model calls before giving up (default: %(default)s)")
    parser.add_argument("--log", default="errors.log", help="JSON-lines log of rejected model replies (default: %(default)s)")
    parser.add_argument("--demo", action="store_true", help="replay examples/tasks.json instead of calling the API")
    args = parser.parse_args(argv)

    if complete is None:
        if args.demo:
            demo_reply = DEMO_RESPONSE.read_text(encoding="utf-8")
            complete = lambda system, messages: demo_reply
        elif os.environ.get("ANTHROPIC_API_KEY"):
            complete = claude(args.model)
        else:
            parser.error("set ANTHROPIC_API_KEY, or use --demo to run without the API")

    source = Path(args.requirements).read_text(encoding="utf-8")
    try:
        data, attempts = convert(source, complete, args.log, args.max_attempts)
    except ConversionError as exc:
        print(f"error: {exc}\nrejected replies are logged in {args.log}", file=sys.stderr)
        return 1

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tasks.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "tasks.md").write_text(render_markdown(data), encoding="utf-8")
    print(f"{args.requirements}: {len(data['tasks'])} tasks, {len(data['open_questions'])} open questions "
          f"(valid after {attempts} attempt{'s' if attempts > 1 else ''})\n")
    print(format_summary(data))
    print(f"\nWrote {out / 'tasks.json'} and {out / 'tasks.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
