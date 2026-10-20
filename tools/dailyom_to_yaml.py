"""Turn scraped DailyOM course data into a private routines file for la-vie.

Input: one JSON file per course (dailyom_*.json), as saved from the DailyOM course player
while signed in: {slug, name, url, chapters, items: [{id, chapter, name, url, pre, post, lis, videos}]}.
Output: a YAML file in the `routines:` format of app/content.py. It holds paid course text, so
it goes in the NAS data folder (data/content/), never in the repo.

Usage: python tools/dailyom_to_yaml.py <folder with dailyom_*.json> <output.yaml>
"""

import json
import re
import sys
from pathlib import Path

import yaml

# Movement courses, in the order they're offered. moves=True: the lesson's bullet list before
# the video is the list of movements.
COURSES = [
    ("the-one-and-done-fat-burning-workout", True),
    ("psoas-stretches-to-relieve-lower-back-pain", False),
    ("next-level-fascia-miracle-the-lymphatic-secret", True),
    ("the-parasympathetic-nervous-system-fix", False),
    ("next-level-somatic-mastery-deepen-trauma-release-and-cellular-renewal", False),
]
SKIP = {"introduction", "conclusion"}


def tidy(text: str) -> str:
    """One line per paragraph or list item; Telegram shows blank lines as wasted space."""
    return re.sub(r"\n\s*\n+", "\n", text or "").strip()


def lessons(course: dict, moves: bool) -> list[dict]:
    first_in_chapter: dict[str, str] = {}
    for it in course["items"]:
        first_in_chapter.setdefault(it["chapter"], it["url"])
    out: list[dict] = []
    for it in course["items"]:
        name = it["name"].strip()
        if "homework" in name.lower() and out:
            # Homework pages follow their lesson: add them to its after-video text.
            extra = f"{name}:\n{tidy(it.get('pre') or it.get('post') or '')}".strip()
            out[-1]["outro"] = f"{out[-1].get('outro', '')}\n\n{extra}".strip()
            continue
        if name.lower() in SKIP or not it.get("videos"):
            continue
        lesson = {
            "key": f"dailyom-{it['id']}",
            "title": name,
            "url": it["url"],
            "section": it["chapter"].strip(),
            "section_url": first_in_chapter[it["chapter"]],
        }
        pre, post = tidy(it.get("pre", "")), tidy(it.get("post", ""))
        if moves:
            found = [x for x in it.get("lis", []) if x in pre and x not in post]
            if found:
                lesson["moves"] = found
                # The moves are listed in the message already: drop them (and their heading) here.
                listed = set(found)
                lines = [ln for ln in pre.split("\n") if ln.strip() not in listed]
                while lines and lines[-1].rstrip().endswith(":"):
                    lines.pop()
                pre = "\n".join(lines).strip()
        if pre:
            lesson["intro"] = pre
        if post:
            lesson["outro"] = post
        out.append(lesson)
    return out


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    by_slug = {}
    for f in src.glob("dailyom_*.json"):
        c = json.loads(f.read_text(encoding="utf-8"))
        by_slug[c["slug"]] = c
    routines = []
    for slug, moves in COURSES:
        c = by_slug[slug]
        routines.append({"key": f"dailyom-{c['id']}", "name": c["name"], "url": c["url"], "lessons": lessons(c, moves)})
    header = "# DailyOM movement lessons (paid content): private, keep out of the repo.\n"
    dst.write_text(header + yaml.safe_dump({"routines": routines}, allow_unicode=True, sort_keys=False, width=110),
                   encoding="utf-8")
    for r in routines:
        print(f"{r['name']}: {len(r['lessons'])} lessons, {sum(len(x.get('moves', [])) for x in r['lessons'])} moves")


if __name__ == "__main__":
    main()
