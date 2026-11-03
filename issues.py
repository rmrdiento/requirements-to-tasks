import json
import re
import urllib.error
import urllib.request

REPO = re.compile(r"^(?!\.+/)[A-Za-z0-9_.-]+/(?!\.+$)[A-Za-z0-9_.-]+$")


def issue_payload(task):
    lines = [task["description"], "", "Acceptance criteria:", *[f"- [ ] {c}" for c in task["acceptance_criteria"]]]
    if task["depends_on"]:
        lines += ["", "Depends on: " + ", ".join(task["depends_on"])]
    lines += ["", f"> {task['source_quote']}"]
    return {
        "title": f"{task['id']} {task['title']}",
        "body": "\n".join(lines),
        "labels": [f"priority:{task['priority']}"],
    }


def create_issues(tasks, repo, token, urlopen=None):
    """Create one GitHub issue per task and return their URLs. Stops at the first failure."""
    urlopen = urlopen or urllib.request.urlopen
    urls = []
    for task in tasks:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/issues",
            data=json.dumps(issue_payload(task)).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                urls.append(json.load(response)["html_url"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"GitHub returned {exc.code} for {task['id']} after {len(urls)} issues were created: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"cannot reach GitHub for {task['id']} after {len(urls)} issues were created: {exc.reason}") from exc
    return urls
