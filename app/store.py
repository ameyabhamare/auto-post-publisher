"""File-backed storage: one folder per post under data/posts/<id>/.

    meta.json      status, title, slug, tags, summary, pr_url, timestamps
    messages.json  the full Claude conversation (append-only)
    post.md        the current draft, including frontmatter
    images/        resized images, committed alongside post.md
"""

import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from .config import DATA_DIR, MAX_IMAGE_EDGE

# Statuses: drafting -> in_review -> pr_open  (or failed)
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, fallback: str = "post") -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or fallback


def post_dir(post_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", post_id):
        raise ValueError("bad post id")
    return DATA_DIR / post_id


def create_post(content: str, uploads: list[tuple[str, bytes]]) -> str:
    post_id = uuid.uuid4().hex[:12]
    d = post_dir(post_id)
    (d / "images").mkdir(parents=True)
    (d / "content.txt").write_text(content, encoding="utf-8")

    used: set[str] = set()
    for original_name, raw in uploads:
        name = _save_image(d / "images", original_name, raw, used)
        used.add(name)

    save_meta(post_id, {"id": post_id, "status": "drafting", "created": _now(), "updated": _now()})
    return post_id


def _save_image(folder: Path, original_name: str, raw: bytes, used: set[str]) -> str:
    img = Image.open(BytesIO(raw))
    fmt = img.format if img.format in SUPPORTED_FORMATS else "JPEG"
    img = ImageOps.exif_transpose(img)  # respect phone camera rotation
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}[fmt]
    base = slugify(Path(original_name).stem, fallback="image")
    name, n = f"{base}.{ext}", 2
    while name in used:
        name, n = f"{base}-{n}.{ext}", n + 1
    img.save(folder / name, format=fmt)
    return name


def list_images(post_id: str) -> list[Path]:
    return sorted((post_dir(post_id) / "images").iterdir())


def media_type(path: Path) -> str:
    return {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}[path.suffix[1:]]


def load_meta(post_id: str) -> dict:
    return json.loads((post_dir(post_id) / "meta.json").read_text(encoding="utf-8"))


def save_meta(post_id: str, meta: dict) -> None:
    meta["updated"] = _now()
    (post_dir(post_id) / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def update_meta(post_id: str, **fields) -> dict:
    meta = load_meta(post_id)
    meta.update(fields)
    save_meta(post_id, meta)
    return meta


def load_messages(post_id: str) -> list:
    p = post_dir(post_id) / "messages.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_messages(post_id: str, messages: list) -> None:
    (post_dir(post_id) / "messages.json").write_text(json.dumps(messages), encoding="utf-8")


def load_markdown(post_id: str) -> str:
    p = post_dir(post_id) / "post.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def save_markdown(post_id: str, text: str, generated: bool = False) -> None:
    """Save the current draft. generated=True also records it as Claude's latest version,
    which is how human edits are detected later."""
    text = text.replace("\r\n", "\n")
    (post_dir(post_id) / "post.md").write_text(text, encoding="utf-8")
    if generated:
        (post_dir(post_id) / "generated.md").write_text(text, encoding="utf-8")


def has_human_edits(post_id: str) -> bool:
    p = post_dir(post_id) / "generated.md"
    generated = p.read_text(encoding="utf-8") if p.exists() else ""
    return load_markdown(post_id).strip() != generated.strip()


def list_posts() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    metas = [json.loads(p.read_text(encoding="utf-8")) for p in DATA_DIR.glob("*/meta.json")]
    return sorted(metas, key=lambda m: m["created"], reverse=True)
