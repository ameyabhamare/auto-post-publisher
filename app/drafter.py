"""Drafts and revises posts with Claude.

The conversation for each post is append-only: the first user turn carries the
raw content and images, each revision appends the reviewer's feedback as a new
user turn, and every assistant turn is stored exactly as returned. Keeping the
prefix unchanged lets the prompt cache and the model's earlier thinking carry
over between revisions.
"""

import base64
import json
from datetime import date

import anthropic

from . import store
from .config import AUTHOR_NAME, EFFORT, EXAMPLES_DIR, MODEL, SKILL_PATH

client = anthropic.Anthropic()

INSTRUCTIONS = """You ghostwrite blog posts for one specific author. The author's skill file \
below describes their voice, tone, structure, and habits; follow it closely. If example \
posts are included, match their voice, rhythm, and formatting more than any generic notion \
of good writing.

You will receive the author's raw content (notes, a rough draft, or bullet points) and \
possibly some images. Write a finished post from it:
- Keep the author's facts, opinions, and specifics. Do not invent experiences, numbers, \
quotes, or claims they did not give you.
- Use the images where they fit the story. Embed each one with Markdown using its exact \
filename and descriptive alt text, e.g. ![A rocky beach at sunset](beach.jpg). You may add \
a short italic caption on the line below an image if the author's style uses captions.
- body_markdown is the post body only: no frontmatter and no top-level title heading.
- slug is lowercase words joined by hyphens, at most six words.

When the author sends feedback on a draft, apply it and return the complete revised post \
in the same format. If they include an edited version, treat their edits as intentional \
and build on that version."""

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "slug": {"type": "string"},
        "summary": {"type": "string", "description": "One or two sentences for previews."},
        "tags": {"type": "array", "items": {"type": "string"}},
        "body_markdown": {"type": "string"},
        "notes_for_reviewer": {
            "type": "string",
            "description": "Brief notes on judgment calls or gaps the author should check. Empty if none.",
        },
    },
    "required": ["title", "slug", "summary", "tags", "body_markdown", "notes_for_reviewer"],
    "additionalProperties": False,
}


class DraftError(Exception):
    pass


def _system_blocks() -> list[dict]:
    if not SKILL_PATH.exists():
        raise DraftError(f"Style file not found: {SKILL_PATH}. Copy your skill.md into the project root.")
    blocks = [
        {"type": "text", "text": INSTRUCTIONS},
        {"type": "text", "text": f"<skill_file>\n{SKILL_PATH.read_text(encoding='utf-8')}\n</skill_file>"},
    ]
    examples = sorted(EXAMPLES_DIR.glob("*.md")) if EXAMPLES_DIR.exists() else []
    if examples:
        joined = "\n\n".join(
            f'<example_post file="{p.name}">\n{p.read_text(encoding="utf-8")}\n</example_post>' for p in examples
        )
        blocks.append({"type": "text", "text": f"<example_posts>\n{joined}\n</example_posts>"})
    # Skill file and examples are identical on every request; cache everything up to here.
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _initial_user_turn(post_id: str) -> dict:
    content: list[dict] = []
    images = store.list_images(post_id)
    for img in images:
        content.append({"type": "text", "text": f"Image file: {img.name}"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": store.media_type(img),
                "data": base64.standard_b64encode(img.read_bytes()).decode("ascii"),
            },
        })
    raw = (store.post_dir(post_id) / "content.txt").read_text(encoding="utf-8")
    content.append({"type": "text", "text": f"<raw_content>\n{raw}\n</raw_content>\n\nWrite the post."})
    return {"role": "user", "content": content}


def _call(messages: list[dict]) -> tuple[dict, dict]:
    """Run one request. Returns (parsed post JSON, assistant message to store)."""
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=_system_blocks(),
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": POST_SCHEMA},
            },
            # If a safety classifier declines, re-run on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIStatusError as e:
        raise DraftError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise DraftError("Could not reach the Claude API. Check your connection.") from e

    if response.stop_reason == "refusal":
        raise DraftError("Claude declined to write this post.")
    if response.stop_reason == "max_tokens":
        raise DraftError("The draft was cut off (max_tokens). Try shorter input or raise max_tokens.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise DraftError("Claude returned no text.")
    assistant_turn = {"role": "assistant", "content": response.to_dict()["content"]}
    return json.loads(text), assistant_turn


def _frontmatter(post: dict) -> str:
    lines = [
        "---",
        f"title: {json.dumps(post['title'], ensure_ascii=False)}",
        f"date: {date.today().isoformat()}",
    ]
    if AUTHOR_NAME:
        lines.append(f"author: {json.dumps(AUTHOR_NAME, ensure_ascii=False)}")
    lines += [
        f"summary: {json.dumps(post['summary'], ensure_ascii=False)}",
        f"tags: {json.dumps(post['tags'], ensure_ascii=False)}",
        "---",
    ]
    return "\n".join(lines)


def _apply(post_id: str, post: dict, messages: list[dict]) -> None:
    markdown = f"{_frontmatter(post)}\n\n# {post['title']}\n\n{post['body_markdown'].strip()}\n"
    store.save_messages(post_id, messages)
    store.save_markdown(post_id, markdown, generated=True)
    store.update_meta(
        post_id,
        status="in_review",
        title=post["title"],
        slug=store.slugify(post["slug"]),
        tags=post["tags"],
        summary=post["summary"],
        notes=post["notes_for_reviewer"],
        error=None,
    )


def draft(post_id: str) -> None:
    messages = [_initial_user_turn(post_id)]
    post, assistant_turn = _call(messages)
    _apply(post_id, post, messages + [assistant_turn])


def revise(post_id: str, feedback: str, edited_markdown: str | None) -> None:
    messages = store.load_messages(post_id)
    parts = []
    if edited_markdown is not None:
        parts.append(f"I edited the draft. This is the current version:\n<edited_post>\n{edited_markdown}\n</edited_post>")
    parts.append(f"<feedback>\n{feedback}\n</feedback>" if feedback.strip() else "Tidy this up and return the full post.")
    messages.append({"role": "user", "content": "\n\n".join(parts)})

    post, assistant_turn = _call(messages)
    _apply(post_id, post, messages + [assistant_turn])
