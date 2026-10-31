import json
import os
import subprocess
import sys

import main
from converter import ROOT

REQUIREMENTS = str(ROOT / "examples" / "requirements.txt")


def test_demo_run_writes_valid_json_and_markdown(tmp_path, capsys):
    out = tmp_path / "out"
    code = main.main([REQUIREMENTS, "--demo", "-o", str(out), "--log", str(tmp_path / "e.log")])
    assert code == 0
    assert len(json.loads((out / "tasks.json").read_text(encoding="utf-8"))["tasks"]) == 8
    assert "# Task list" in (out / "tasks.md").read_text(encoding="utf-8")
    assert "T-01" in capsys.readouterr().out


def test_invalid_model_output_gives_exit_code_1_and_no_files(tmp_path, capsys):
    out = tmp_path / "out"
    code = main.main(
        [REQUIREMENTS, "-o", str(out), "--log", str(tmp_path / "e.log")],
        complete=lambda system, messages: "not json",
    )
    assert code == 1
    assert not out.exists()
    assert (tmp_path / "e.log").exists()
    assert "still invalid" in capsys.readouterr().err


def test_missing_api_key_is_a_usage_error(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), REQUIREMENTS],
        cwd=tmp_path, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"},
    )
    assert proc.returncode == 2
    assert "ANTHROPIC_API_KEY" in proc.stderr


def test_demo_command_end_to_end(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), REQUIREMENTS, "--demo"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "output" / "tasks.json").exists()
