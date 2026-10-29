"""Everything that teaches Claude the author's voice, beyond the hand-written skill.md.

    example_posts()        hand-picked examples/ plus recent posts from the user's posts repo
    generate_proposal()    drafts a whole skill.md from past posts, for the author to review
    learn_from_post()      after approval, compares Claude's first draft with what the author
                           shipped and proposes new skill.md rules

Each user's data lives under users/<name>/data/style/:

    published/manifest.json   last check time, last posts commit, cached folder names
    published/<folder>.md     cached published posts, frontmatter stripped
    proposal.json             the latest generated skill.md proposal
    suggestions.json          pending rule suggestions learned from edits
"""

import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from github import GithubException

from . import llm, publisher, store
from .config import EXAMPLE_COUNT, ROOT, STYLE_SOURCE_COUNT
from .users import User

log = logging.getLogger(__name__)


# Ask GitHub for new posts at most this often; drafts in between reuse the cache, which also
# keeps the system prompt byte-identical so prompt caching keeps working.
CHECK_INTERVAL = 600
POST_FOLDER = re.compile(r"\d{4}-\d{2}-\d{2}-.+")
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n+", re.S)

_locks: dict[str, threading.Lock] = {}


def _lock(user: User) -> threading.Lock:
    """Guards read-modify-write of one user's JSON files and skill.md."""
    return _locks.setdefault(user.name, threading.Lock())


def _published_dir(user: User) -> Path:
    return user.style_dir / "published"


def _manifest(user: User) -> Path:
    return _published_dir(user) / "manifest.json"


def _proposal(user: User) -> Path:
    return user.style_dir / "proposal.json"


def _suggestions(user: User) -> Path:
    return user.style_dir / "suggestions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, data) -> None:
    _write(path, json.dumps(data, indent=2))


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER.sub("", text.replace("\r\n", "\n"), count=1)


# ---------------------------------------------------------------- published posts


def _sync_published(user: User, force: bool = False) -> None:
    """Refresh the local cache of published posts if the posts folder changed on GitHub."""
    published = _published_dir(user)
    manifest = _read_json(_manifest(user), {})
    source = f"{user.repo}@{user.base_branch}:{user.repo_posts_dir}"
    if manifest.get("source") != source:
        # Repo or folder changed on the Account page: start over.
        for stale in published.glob("*.md"):
            stale.unlink()
        manifest, force = {"source": source}, True
    if not force and time.time() - manifest.get("checked", 0) < CHECK_INTERVAL:
        return
    posts_dir = user.repo_posts_dir
    try:
        repo = publisher.get_repo(user)
        latest = next(iter(repo.get_commits(sha=user.base_branch, path=posts_dir)), None)
        head = latest.sha if latest else None
        if head and (force or head != manifest.get("head")):
            entries = repo.get_contents(posts_dir, ref=head)
            folders = sorted(
                (e.name for e in entries if e.type == "dir" and POST_FOLDER.fullmatch(e.name)), reverse=True
            )[: max(EXAMPLE_COUNT, STYLE_SOURCE_COUNT)]
            kept = []
            for folder in folders:
                cached = published / f"{folder}.md"
                if not cached.exists():
                    try:
                        raw = repo.get_contents(f"{posts_dir}/{folder}/post.md", ref=head)
                    except GithubException as e:
                        if e.status == 404:
                            continue
                        raise
                    _write(cached, strip_frontmatter(raw.decoded_content.decode("utf-8")))
                kept.append(folder)
            for stale in published.glob("*.md"):
                if stale.stem not in kept:
                    stale.unlink()
            manifest["posts"] = kept
        elif not head:
            manifest["posts"] = []
        manifest["head"] = head
        manifest.pop("error", None)
    except (publisher.PublishError, GithubException, OSError) as e:
        # Offline or not configured: keep drafting with whatever is cached.
        manifest["error"] = str(e)
        log.warning("Could not refresh published posts: %s", e)
    manifest["checked"] = time.time()
    _write_json(_manifest(user), manifest)


def published_posts(user: User, limit: int, force: bool = False) -> list[tuple[str, str]]:
    """Most recent published posts as (name, markdown without frontmatter), newest first."""
    with _lock(user):
        _sync_published(user, force)
        folders = _read_json(_manifest(user), {}).get("posts", [])
    out = []
    for folder in folders[:limit]:
        path = _published_dir(user) / f"{folder}.md"
        if path.exists():
            out.append((f"{folder}.md", path.read_text(encoding="utf-8")))
    return out


def published_status(user: User) -> dict:
    manifest = _read_json(_manifest(user), {})
    checked = manifest.get("checked")
    return {
        "count": len(manifest.get("posts", [])),
        "checked": datetime.fromtimestamp(checked, timezone.utc).isoformat(timespec="seconds") if checked else None,
        "error": manifest.get("error"),
    }


def local_examples(user: User) -> list[tuple[str, str]]:
    files = sorted(user.examples_dir.glob("*.md")) if user.examples_dir.exists() else []
    return [(p.name, p.read_text(encoding="utf-8")) for p in files]


def example_posts(user: User) -> list[tuple[str, str]]:
    """Examples sent with every draft: all hand-picked ones, then recent published posts
    until EXAMPLE_COUNT is reached."""
    examples = local_examples(user)
    room = EXAMPLE_COUNT - len(examples)
    if room > 0:
        examples += published_posts(user, room)
    return examples


# ---------------------------------------------------------------- skill.md


def read_skill(user: User) -> str:
    return user.skill_path.read_text(encoding="utf-8") if user.skill_path.exists() else ""


def save_skill(user: User, text: str) -> None:
    """Overwrite skill.md, keeping the previous version as skill.md.bak."""
    text = text.replace("\r\n", "\n").strip() + "\n"
    with _lock(user):
        if user.skill_path.exists():
            user.skill_path.with_name(user.skill_path.name + ".bak").write_text(read_skill(user), encoding="utf-8")
        _write(user.skill_path, text)


def add_rule(user: User, section: str, rule: str) -> None:
    """Add a bullet to the `## section` of skill.md, creating the section if needed."""
    rule = rule.strip().removeprefix("- ").strip()
    if not rule:
        return
    with _lock(user):
        text = read_skill(user) or "# Writing style\n"
        lines = text.rstrip("\n").split("\n")
        start = next(
            (i for i, line in enumerate(lines) if re.fullmatch(rf"##\s+{re.escape(section.strip())}\s*", line, re.I)),
            None,
        )
        if start is None:
            lines += ["", f"## {section.strip()}", f"- {rule}"]
        else:
            end = next((i for i in range(start + 1, len(lines)) if re.match(r"#{1,2}\s", lines[i])), len(lines))
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            lines.insert(end, f"- {rule}")
        _write(user.skill_path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------- generating skill.md

GENERATE_INSTRUCTIONS = """You analyse an author's past blog posts and write their style file: \
a skill.md that another writer (Claude) will follow to ghostwrite new posts in their voice.

Describe how this author actually writes, based only on the posts you are given. Be specific \
and checkable ("opens with a concrete moment, never a definition"; "paragraphs of 2-4 \
sentences"; "spells it 'summarise'") rather than vague ("engaging", "clear"). Only state a \
habit if it shows up in most of the posts; note real variation instead of forcing a rule. \
Include phrases and patterns the author avoids when the posts make that clear.

Follow the section layout of the template below. Drop sections you have no evidence for, and \
add one if the posts show something important it doesn't cover. Write the file in plain \
Markdown with bullet points; do not quote long passages from the posts.

If the author already has a style file, keep its rules unless the posts clearly contradict \
them: the author wrote those deliberately."""

GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "skill_markdown": {"type": "string", "description": "The complete skill.md file."},
        "notes": {
            "type": "string",
            "description": "Brief notes for the author: what was inferred with low confidence, or what "
            "would improve the file (e.g. more posts). Empty if none.",
        },
    },
    "required": ["skill_markdown", "notes"],
    "additionalProperties": False,
}


def proposal(user: User) -> dict:
    return _read_json(_proposal(user), {})


def start_proposal(user: User) -> None:
    _write_json(_proposal(user), {"status": "generating", "started": _now()})


def discard_proposal(user: User) -> None:
    _proposal(user).unlink(missing_ok=True)


def generate_proposal(user: User, pasted: str) -> None:
    """Background job: write a proposed skill.md from past posts into proposal.json."""
    try:
        sources = local_examples(user) + published_posts(user, STYLE_SOURCE_COUNT)
        if pasted.strip():
            sources.append(("pasted.md", pasted.strip()))
        if not sources:
            raise llm.ClaudeError(
                "No past posts to learn from. Publish a post, add files to examples/, or paste some posts."
            )

        template = (ROOT / "skill.example.md").read_text(encoding="utf-8")
        posts = "\n\n".join(f'<post name="{name}">\n{text}\n</post>' for name, text in sources)
        current = read_skill(user)
        parts = [f"<posts>\n{posts}\n</posts>"]
        if current:
            parts.append(f"<current_style_file>\n{current}\n</current_style_file>")
        parts.append("Write the style file.")

        result, _ = llm.call_json(
            [{"type": "text", "text": GENERATE_INSTRUCTIONS},
             {"type": "text", "text": f"<template>\n{template}\n</template>"}],
            [{"role": "user", "content": "\n\n".join(parts)}],
            GENERATE_SCHEMA,
        )
        _write_json(_proposal(user), {
            "status": "ready",
            "created": _now(),
            "skill_markdown": result["skill_markdown"],
            "notes": result["notes"],
            "sources": [name for name, _ in sources],
        })
    except Exception as e:  # surface every failure on the style page
        _write_json(_proposal(user), {"status": "failed", "error": str(e)})


# ---------------------------------------------------------------- learning from edits

LEARN_INSTRUCTIONS = """You maintain an author's style file (skill.md), which Claude follows when \
ghostwriting their blog posts. You will see Claude's first draft of a post, any feedback the \
author gave while revising it, and the version the author finally published.

Find durable style preferences the changes reveal: how the author wants posts to sound, be \
structured, or be worded in general. Propose each as one short, specific rule for the style \
file.

- Ignore changes that only fix this post's facts or content (a wrong date, an added detail).
- Skip anything the style file already says, unless the draft broke that rule repeatedly; \
then propose a sharper wording of it.
- Skip anything already in the pending suggestions.
- Propose at most 3 rules, strongest first. Return an empty list if nothing generalises: \
that is the common case for small edits.
- section is the style file heading the rule belongs under (e.g. Voice, Structure, Word \
choice); reuse an existing heading where one fits."""

LEARN_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "rule": {"type": "string", "description": "One bullet, without the leading dash."},
                    "evidence": {"type": "string", "description": "What in the edits or feedback shows this."},
                },
                "required": ["section", "rule", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


def suggestions(user: User) -> dict:
    return _read_json(_suggestions(user), {"items": [], "error": None})


def _first_draft(messages: list[dict]) -> str | None:
    first = next((m for m in messages if m["role"] == "assistant"), None)
    if not first:
        return None
    text = next((b["text"] for b in first["content"] if b.get("type") == "text"), None)
    return json.loads(text)["body_markdown"].strip() if text else None


def _feedback(messages: list[dict]) -> list[str]:
    found = []
    for m in messages[1:]:
        if m["role"] == "user" and isinstance(m["content"], str):
            found += [f.strip() for f in re.findall(r"<feedback>\n(.*?)\n</feedback>", m["content"], re.S)]
    return [f for f in found if f]


def _final_body(markdown: str) -> str:
    """Published post without frontmatter or the title heading, to compare with a draft body."""
    return re.sub(r"\A#\s.*\n+", "", strip_frontmatter(markdown), count=1).strip()


def learn_from_post(user: User, post_id: str) -> None:
    """Background job after approval: turn the author's edits and feedback into rule suggestions."""
    try:
        messages = store.load_messages(user, post_id)
        draft = _first_draft(messages)
        feedback = _feedback(messages)
        final = _final_body(store.load_markdown(user, post_id))
        if draft is None or (not feedback and draft == final):
            return  # shipped as drafted: nothing to learn

        pending = suggestions(user)["items"]
        parts = [
            f"<style_file>\n{read_skill(user) or '(none yet)'}\n</style_file>",
            f"<first_draft>\n{draft}\n</first_draft>",
        ]
        if feedback:
            parts.append("<feedback_given>\n" + "\n".join(f"- {f}" for f in feedback) + "\n</feedback_given>")
        parts.append(f"<published_version>\n{final}\n</published_version>")
        if pending:
            parts.append("<pending_suggestions>\n" + "\n".join(f"- {s['rule']}" for s in pending)
                         + "\n</pending_suggestions>")

        result, _ = llm.call_json(
            [{"type": "text", "text": LEARN_INSTRUCTIONS}],
            [{"role": "user", "content": "\n\n".join(parts)}],
            LEARN_SCHEMA,
        )
        meta = store.load_meta(user, post_id)
        new = [
            {**s, "id": uuid.uuid4().hex[:12], "post_id": post_id, "post_title": meta.get("title", ""), "created": _now()}
            for s in result["suggestions"] if s["rule"].strip()
        ]
        with _lock(user):
            state = suggestions(user)
            state["items"] += new
            state["error"] = None
            _write_json(_suggestions(user), state)
    except Exception as e:  # never break publishing; show the failure on the style page
        log.warning("Learning from post %s failed: %s", post_id, e)
        with _lock(user):
            state = suggestions(user)
            state["error"] = f"Could not learn from post {post_id}: {e}"
            _write_json(_suggestions(user), state)


def resolve_suggestion(user: User, suggestion_id: str, accept: bool, rule: str | None = None) -> None:
    with _lock(user):
        state = suggestions(user)
        item = next((s for s in state["items"] if s["id"] == suggestion_id), None)
        state["items"] = [s for s in state["items"] if s["id"] != suggestion_id]
        _write_json(_suggestions(user), state)
    if item and accept:
        add_rule(user, item["section"], rule if rule is not None else item["rule"])


def dismiss_error(user: User) -> None:
    with _lock(user):
        state = suggestions(user)
        state["error"] = None
        _write_json(_suggestions(user), state)
