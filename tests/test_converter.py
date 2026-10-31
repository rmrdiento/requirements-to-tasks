import copy
import json

import pytest

import main
from converter import ROOT, SYSTEM, ConversionError, convert, extract_json, validate

SOURCE = (ROOT / "examples" / "requirements.txt").read_text(encoding="utf-8")
SAMPLE = json.loads((ROOT / "examples" / "tasks.json").read_text(encoding="utf-8"))


def scripted(*replies):
    """A fake model that returns the given replies in order and records what it was sent."""
    calls = []

    def complete(system, messages):
        calls.append(copy.deepcopy(messages))
        return replies[len(calls) - 1]

    complete.calls = calls
    return complete


def broken(change):
    data = copy.deepcopy(SAMPLE)
    change(data)
    return data


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_sample_response_is_valid_for_sample_requirements():
    assert validate(SAMPLE, SOURCE) == []


def test_system_prompt_embeds_the_schema():
    assert '"source_quote"' in SYSTEM


@pytest.mark.parametrize("reply", [json.dumps(SAMPLE), "```json\n" + json.dumps(SAMPLE) + "\n```", "Here you go:\n" + json.dumps(SAMPLE)])
def test_json_is_extracted_from_fences_and_prose(reply):
    assert extract_json(reply) == SAMPLE


def test_valid_reply_needs_one_attempt_and_writes_no_log(tmp_path):
    log = tmp_path / "errors.log"
    data, attempts = convert(SOURCE, scripted(json.dumps(SAMPLE)), log)
    assert (data, attempts) == (SAMPLE, 1)
    assert not log.exists()


def test_invalid_reply_is_logged_and_fed_back_to_the_model(tmp_path):
    log = tmp_path / "errors.log"
    model = scripted("sorry, no JSON", json.dumps(SAMPLE))
    _, attempts = convert(SOURCE, model, log)
    assert attempts == 2
    entries = read_log(log)
    assert [e["kind"] for e in entries] == ["invalid_json"]
    assert entries[0]["reply"] == "sorry, no JSON"
    feedback = model.calls[1][-1]["content"]
    assert "rejected" in feedback and "no JSON object" in feedback


def test_gives_up_after_max_attempts_and_logs_each_one(tmp_path):
    log = tmp_path / "errors.log"
    with pytest.raises(ConversionError, match="after 3 attempts"):
        convert(SOURCE, scripted("a", "b", "c"), log)
    assert [e["attempt"] for e in read_log(log)] == [1, 2, 3]


def test_api_failure_is_logged_and_raised(tmp_path):
    def down(system, messages):
        raise TimeoutError("connection timed out")

    log = tmp_path / "errors.log"
    with pytest.raises(ConversionError, match="connection timed out"):
        convert(SOURCE, down, log)
    assert read_log(log)[0]["kind"] == "api_error"


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda d: d["tasks"][0].update(priority="urgent"), "priority"),
        (lambda d: d["tasks"][0].pop("title"), "title"),
        (lambda d: d["tasks"][0].update(estimate="3d"), "estimate"),
        (lambda d: d["tasks"][0].update(id="task-1"), "id"),
        (lambda d: d["tasks"].clear(), "tasks"),
        (lambda d: d["tasks"][1].update(id="T-01"), "duplicate id T-01"),
        (lambda d: d["tasks"][1].update(depends_on=["T-99"]), "unknown task T-99"),
        (lambda d: d["tasks"][0].update(depends_on=["T-02"]), "dependency cycle"),
        (lambda d: d["tasks"][0].update(depends_on=["T-01"]), "dependency cycle"),
        (lambda d: d["tasks"][0].update(source_quote="Patients want a mobile app"), "source_quote"),
    ],
)
def test_validation_rejects_bad_output(change, expected):
    errors = validate(broken(change), SOURCE)
    assert errors and any(expected in e for e in errors)


def test_quote_check_ignores_case_and_whitespace():
    data = broken(lambda d: d["tasks"][0].update(source_quote="PATIENTS should  be able to\nbook, move and cancel their own appointments from the website without calling us"))
    assert validate(data, SOURCE) == []


def test_markdown_groups_by_priority_and_lists_open_questions():
    md = main.render_markdown(SAMPLE)
    assert md.index("## High priority") < md.index("## Medium priority") < md.index("## Low priority")
    assert "### T-08 - Waiting list for freed-up slots" in md
    assert "Depends on: T-01, T-02" in md
    assert "## Open questions for the customer" in md
