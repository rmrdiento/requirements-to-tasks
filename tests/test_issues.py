import io
import json
import urllib.error

import pytest

import main
from converter import ROOT
from issues import create_issues, issue_payload

REQUIREMENTS = str(ROOT / "examples" / "requirements.txt")
TASKS = json.loads((ROOT / "examples" / "tasks.json").read_text(encoding="utf-8"))["tasks"]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def recording_urlopen(fail_on=None, status=422):
    sent = []

    def urlopen(request, timeout):
        if fail_on is not None and len(sent) == fail_on:
            raise urllib.error.HTTPError(request.full_url, status, "Unprocessable", {}, io.BytesIO(b'{"message":"bad label"}'))
        sent.append(request)
        return FakeResponse(json.dumps({"html_url": f"https://github.com/o/r/issues/{len(sent)}"}).encode())

    urlopen.sent = sent
    return urlopen


def test_payload_has_checklist_dependencies_quote_and_priority_label():
    payload = issue_payload(TASKS[7])
    assert payload["title"] == "T-08 Waiting list for freed-up slots"
    assert payload["labels"] == ["priority:low"]
    assert "- [ ] A freed-up slot is offered to patients on the waiting list" in payload["body"]
    assert "Depends on: T-01, T-02" in payload["body"]
    assert payload["body"].rstrip().endswith("> It would be nice to have a waiting list that offers freed-up slots to other patients")


def test_issues_are_posted_with_auth_header_to_the_repo():
    urlopen = recording_urlopen()
    urls = create_issues(TASKS, "o/r", "secret", urlopen)
    assert len(urls) == 8 and urls[0].endswith("/issues/1")
    first = urlopen.sent[0]
    assert first.full_url == "https://api.github.com/repos/o/r/issues"
    assert first.get_method() == "POST"
    assert first.get_header("Authorization") == "Bearer secret"
    assert json.loads(first.data)["title"].startswith("T-01")


def test_http_error_stops_and_reports_how_many_were_created():
    with pytest.raises(RuntimeError, match=r"422 for T-03 after 2 issues were created.*bad label"):
        create_issues(TASKS, "o/r", "secret", recording_urlopen(fail_on=2))


def test_cli_creates_issues(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    urlopen = recording_urlopen()
    code = main.main([REQUIREMENTS, "--demo", "-o", str(tmp_path), "--github-issues", "o/r"], urlopen=urlopen)
    assert code == 0 and len(urlopen.sent) == 8
    assert "Created 8 issues in o/r" in capsys.readouterr().out


def test_cli_dry_run_sends_nothing_and_needs_no_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    urlopen = recording_urlopen()
    code = main.main([REQUIREMENTS, "--demo", "-o", str(tmp_path), "--github-issues", "o/r", "--dry-run"], urlopen=urlopen)
    assert code == 0 and urlopen.sent == []
    assert "T-01 Online appointment booking  [priority:high]" in capsys.readouterr().out


def test_cli_github_failure_gives_exit_code_1(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    code = main.main([REQUIREMENTS, "--demo", "-o", str(tmp_path), "--github-issues", "o/r"], urlopen=recording_urlopen(fail_on=0))
    assert code == 1


@pytest.mark.parametrize("args, env_token", [(["--github-issues", "o/r"], False), (["--github-issues", "../etc"], True)])
def test_cli_usage_errors(tmp_path, monkeypatch, args, env_token):
    monkeypatch.setenv("GITHUB_TOKEN", "x") if env_token else monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        main.main([REQUIREMENTS, "--demo", "-o", str(tmp_path), *args])
    assert exc.value.code == 2
