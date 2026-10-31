import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parent
SCHEMA = json.loads((ROOT / "schema" / "tasks.schema.json").read_text(encoding="utf-8"))

SYSTEM = f"""You are a business analyst who turns customer requirements into development tasks.
Reply with one JSON object and nothing else. It must satisfy this JSON Schema:

{json.dumps(SCHEMA, indent=2)}

Rules:
- One task per distinct deliverable. Ids are T-01, T-02, ... in order.
- priority: "high" = the customer calls it mandatory or the product is unusable without it,
  "medium" = wanted but not blocking, "low" = nice to have.
- source_quote must be copied word for word from the requirements text.
- depends_on lists ids of tasks that must be finished first; use [] when there are none.
- Do not invent requirements. Put anything vague or missing (amounts, dates, providers) in open_questions."""


class ConversionError(Exception):
    pass


def extract_json(reply):
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found in the reply")
    return json.loads(reply[start:end + 1])


def normalize(text):
    return " ".join(text.lower().split())


def validate(data, source):
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in Draft202012Validator(SCHEMA).iter_errors(data)
    ]
    if errors:
        return errors
    tasks = data["tasks"]
    ids = [t["id"] for t in tasks]
    errors += [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    text = normalize(source)
    for t in tasks:
        errors += [f"{t['id']}: depends on unknown task {d}" for d in t["depends_on"] if d not in ids]
        if normalize(t["source_quote"]) not in text:
            errors.append(f"{t['id']}: source_quote is not in the requirements text")
    remaining = {t["id"]: set(t["depends_on"]) for t in tasks}
    while remaining:
        ready = [i for i, deps in remaining.items() if not deps & remaining.keys()]
        if not ready:
            errors.append(f"dependency cycle among {sorted(remaining)}")
            break
        for i in ready:
            del remaining[i]
    return errors


def log_failure(log_path, attempt, kind, errors, reply):
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attempt": attempt,
        "kind": kind,
        "errors": errors,
        "reply": reply[:2000],
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def convert(source, complete, log_path, max_attempts=3):
    """Ask the model for tasks, validate, and feed validation errors back until it gets them right."""
    messages = [{"role": "user", "content": f"Requirements:\n\n{source}"}]
    for attempt in range(1, max_attempts + 1):
        try:
            reply = complete(SYSTEM, messages)
        except Exception as exc:
            log_failure(log_path, attempt, "api_error", [str(exc)], "")
            raise ConversionError(f"model call failed: {exc}") from exc
        try:
            data = extract_json(reply)
            errors, kind = validate(data, source), "validation"
        except ValueError as exc:
            errors, kind = [str(exc)], "invalid_json"
        if not errors:
            return data, attempt
        log_failure(log_path, attempt, kind, errors, reply)
        feedback = "Your reply was rejected:\n- " + "\n- ".join(errors) + "\nReturn the corrected JSON object only."
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": feedback}]
    raise ConversionError(f"model output still invalid after {max_attempts} attempts: {errors[0]}")
