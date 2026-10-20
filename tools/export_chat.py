"""Export a Claude Code session transcript (.jsonl) to a readable Markdown chat history.

Keeps user and assistant messages verbatim; lists tool calls one line each; drops tool
output, system reminders and internal metadata; redacts known secret formats.

Usage (from the repo root):
    .venv\\Scripts\\python tools\\export_chat.py [TRANSCRIPT.jsonl] [OUTPUT.md]

With no transcript, the newest transcript of this project is used. With no output, the
file in docs/chat-history/ that already carries this session's ID is updated; if there
is none, a new one is named after the session's first day.

Paragraphs and tool calls matching any regex in tools/chat-exclude.local.txt (one per
line, not committed) are left out, for material that belongs to other projects.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "docs" / "chat-history"
TRANSCRIPTS = Path.home() / ".claude" / "projects" / "C--Users-dbarb-Projects-daily-life"
TZ = ZoneInfo("Europe/London")
REDACT = [
    (re.compile(r"ADMIN_PASSWORD=\S{8,}"), "ADMIN_PASSWORD=[redacted]"),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "[redacted bot token]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[redacted GitHub token]"),
    (re.compile(r"hc-ping\.com/[0-9a-f-]{36}"), "hc-ping.com/[redacted]"),
]
STRIP = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.S),
]


def load_exclude() -> re.Pattern | None:
    f = ROOT / "tools" / "chat-exclude.local.txt"
    if not f.exists():
        return None
    lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()]
    pats = [ln for ln in lines if ln and not ln.startswith("#")]
    return re.compile("|".join(pats), re.I) if pats else None


EXCLUDE = load_exclude()

# Literal strings (one per line, not committed) to redact wherever they appear, e.g. a
# password pasted into the chat by mistake.
_secrets = ROOT / "tools" / "chat-redact.local.txt"
if _secrets.exists():
    for _s in _secrets.read_text(encoding="utf-8").splitlines():
        if _s.strip() and not _s.startswith("#"):
            REDACT.append((re.compile(re.escape(_s.strip())), "[redacted]"))


def excluded(text: str) -> bool:
    return bool(EXCLUDE and EXCLUDE.search(text))


def redact(text: str) -> str:
    for rx, repl in REDACT:
        text = rx.sub(repl, text)
    return text


def clean(text: str) -> str:
    for rx in STRIP:
        text = rx.sub("", text)
    # Pasted terminal output -> fenced block.
    text = re.sub(
        r"<pasted_content[^>]*>\s*(.*?)\s*</pasted_content[^>]*>",
        lambda m: "\n```\n" + m.group(1).strip() + "\n```\n",
        text,
        flags=re.S,
    )
    # Slash commands and shell-mode input.
    text = re.sub(r"<command-name>(.*?)</command-name>\s*", r"`\1` ", text, flags=re.S)
    text = re.sub(r"<command-message>.*?</command-message>\s*", "", text, flags=re.S)
    text = re.sub(r"<command-args>\s*</command-args>\s*", "", text, flags=re.S)
    text = re.sub(r"<command-args>(.*?)</command-args>", r"\1", text, flags=re.S)
    text = re.sub(r"<local-command-stdout>(.*?)</local-command-stdout>", r"\n> \1\n", text, flags=re.S)
    text = re.sub(r"<bash-input>(.*?)</bash-input>", r"\n```\n$ \1\n```\n", text, flags=re.S)
    for tag in ("bash-stdout", "bash-stderr"):
        text = re.sub(
            rf"<{tag}>(.*?)</{tag}>",
            lambda m: ("\n```\n" + m.group(1).strip() + "\n```\n") if m.group(1).strip() else "",
            text,
            flags=re.S,
        )
    text = redact(text)
    text = "\n\n".join(p for p in re.split(r"\n\s*\n", text) if not excluded(p))
    return text.strip()


def tool_line(block: dict) -> str:
    name = block.get("name", "tool")
    inp = block.get("input", {}) or {}
    if name in ("Write", "Edit", "Read"):
        detail = inp.get("file_path", "").replace(str(ROOT) + "\\", "")
    elif name in ("PowerShell", "Bash"):
        detail = inp.get("description") or (inp.get("command", "")[:80])
    elif name == "AskUserQuestion":
        detail = "; ".join(q.get("question", "") for q in inp.get("questions", []))
    elif name in ("Grep", "Glob"):
        detail = inp.get("pattern", "")
    elif name in ("WebFetch", "WebSearch"):
        detail = inp.get("url") or inp.get("query", "")
    elif name == "Artifact":
        detail = inp.get("action", "publish")
    elif name == "Skill":
        detail = inp.get("skill", "")
    else:
        detail = ""
    return f"- *{name}*" + (f": {redact(detail)}" if detail else "")


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)


def tools_block(tools: list[str]) -> list[str]:
    return ["<details><summary>Tool calls</summary>", ""] + tools + ["", "</details>", ""]


def export(src: Path) -> tuple[list[str], list[datetime]]:
    body: list[str] = []
    days: list[datetime] = []
    pending: list[str] = []
    last_role = None
    with open(src, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") not in ("user", "assistant") or rec.get("isMeta") or rec.get("isSidechain"):
                continue
            content = rec.get("message", {}).get("content")
            if "<task-notification>" in json.dumps(content or ""):
                continue
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])

            texts, tools, answers = [], [], []
            for b in blocks:
                t = b.get("type")
                if t == "text":
                    c = clean(b.get("text", ""))
                    if c:
                        texts.append(f"*{c}*" if c.startswith("[Request interrupted") else c)
                elif t == "tool_use":
                    line_ = tool_line(b)
                    if not excluded(line_ + json.dumps(b.get("input", {}))):
                        tools.append(line_)
                elif t == "tool_result" and rec["type"] == "user":
                    # Keep the user's answers to AskUserQuestion; skip all other tool output.
                    out = b.get("content")
                    out = out if isinstance(out, str) else " ".join(
                        x.get("text", "") for x in (out or []) if isinstance(x, dict))
                    if out.lstrip().startswith(("Your questions have been answered", "The user answered", "User has answered")):
                        m = re.search(r"answered:? (.*?)(?:\. You can now continue|\. Read the answers)", out, re.S)
                        a = clean(m.group(1) if m else out)
                        if a:
                            answers.append(a)

            ts = rec.get("timestamp")
            if ts and (texts or answers):
                dt = local(ts)
                if not days or dt.date() != days[-1].date():
                    if pending:
                        body += tools_block(pending)
                        pending = []
                    body += [f"# {dt.strftime('%A %d %B %Y')}", ""]
                    days.append(dt)
                    last_role = None
            stamp = local(ts).strftime("%H:%M") if ts else ""
            if rec["type"] == "assistant":
                pending += tools
                if texts:
                    if pending:
                        body += tools_block(pending)
                        pending = []
                    if last_role != "assistant":
                        body += [f"## Claude · {stamp}", ""]
                    body += ["\n\n".join(texts), ""]
                    last_role = "assistant"
            else:
                if not (texts or answers):
                    continue
                if pending:
                    body += tools_block(pending)
                    pending = []
                if answers and not texts:
                    body += [f"> **Answers:** {a}" for a in answers] + [""]
                    continue
                body += [f"## You · {stamp}", ""]
                body += ["\n\n".join(texts + [f"**Answers:** {a}" for a in answers]), ""]
                last_role = "user"
    if pending:
        body += tools_block(pending)
    return body, days


def main() -> None:
    args = sys.argv[1:]
    src = Path(args[0]) if args else max(TRANSCRIPTS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    session = src.stem
    body, days = export(src)
    if not days:
        sys.exit(f"{src}: no messages")

    if len(args) > 1:
        dst = Path(args[1])
    else:
        dst = next((p for p in sorted(HISTORY.glob("*.md")) if session in p.read_text(encoding="utf-8")), None)
        dst = dst or HISTORY / f"{days[0]:%Y-%m-%d}_session.md"

    months = sorted({(d.year, d.month) for d in days})
    if len(months) == 1:
        span = ", ".join(str(d.day) for d in days[:-1])
        span = (f"{span} and {days[-1].day}" if span else str(days[-1].day)) + f" {days[-1]:%B %Y}"
    else:
        span = ", ".join(f"{d.day} {d:%B %Y}" for d in days)
    head = [
        "# la-vie_db: session chat history",
        "",
        f"Claude Code session `{session}`, {span} (times are UK local). Exported from the session transcript",
        "by `tools/export_chat.py`: user and assistant messages are verbatim; tool calls are listed one per line;",
        "tool output, system notes and secrets are omitted.",
        "",
    ]
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head + body).rstrip() + "\n")
    print(f"wrote {dst.relative_to(ROOT) if dst.is_relative_to(ROOT) else dst}: {len(head) + len(body)} lines, last message {days[-1]:%Y-%m-%d}")


if __name__ == "__main__":
    main()
