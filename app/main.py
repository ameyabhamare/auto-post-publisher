import re
from pathlib import Path

import markdown as md
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import drafter, publisher, store, style
from .config import GITHUB_REPO, SKILL_PATH

app = FastAPI(title="Auto Post Publisher")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _run(post_id: str, fn, *args) -> None:
    """Run a drafting step in the background and record failures on the post."""
    try:
        fn(post_id, *args)
    except Exception as e:  # surface every failure on the review page
        has_draft = bool(store.load_markdown(post_id))
        store.update_meta(post_id, status="in_review" if has_draft else "failed", error=str(e))


def _meta_or_404(post_id: str) -> dict:
    try:
        return store.load_meta(post_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Post not found")


def _render_preview(post_id: str, text: str) -> str:
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    html = md.markdown(body, extensions=["extra", "sane_lists"])
    # Relative image paths point at the post folder; serve them from this app.
    return re.sub(r'src="(?!https?://|/)([^"]+)"', rf'src="/posts/{post_id}/images/\1"', html)


def _redirect(post_id: str) -> RedirectResponse:
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "posts": store.list_posts(),
        "skill_missing": not SKILL_PATH.exists(),
        "repo": GITHUB_REPO,
        "suggestion_count": len(style.suggestions()["items"]),
    })


@app.post("/posts")
async def create(background: BackgroundTasks, content: str = Form(...), images: list[UploadFile] = File(default=[])):
    uploads = [(f.filename, await f.read()) for f in images if f.filename]
    try:
        post_id = store.create_post(content, uploads)
    except Exception as e:
        raise HTTPException(400, f"Could not read an image: {e}")
    background.add_task(_run, post_id, drafter.draft)
    return _redirect(post_id)


@app.get("/posts/{post_id}", response_class=HTMLResponse)
def view(request: Request, post_id: str):
    meta = _meta_or_404(post_id)
    text = store.load_markdown(post_id)
    return templates.TemplateResponse(request, "post.html", {
        "meta": meta,
        "markdown": text,
        "preview": _render_preview(post_id, text) if text else "",
        "images": [p.name for p in store.list_images(post_id)],
        "revisions": sum(1 for m in store.load_messages(post_id) if m["role"] == "assistant"),
    })


@app.get("/posts/{post_id}/images/{name}")
def image(post_id: str, name: str):
    _meta_or_404(post_id)
    path = store.post_dir(post_id) / "images" / Path(name).name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


def _require_status(meta: dict, *allowed: str) -> None:
    if meta["status"] not in allowed:
        raise HTTPException(409, f"Post is '{meta['status']}'; this action needs {' or '.join(allowed)}.")


@app.post("/posts/{post_id}/revise")
def revise(post_id: str, background: BackgroundTasks, feedback: str = Form(""), markdown: str = Form(...)):
    _require_status(_meta_or_404(post_id), "in_review")
    store.save_markdown(post_id, markdown)
    edited = store.load_markdown(post_id) if store.has_human_edits(post_id) else None
    store.update_meta(post_id, status="drafting", error=None)
    background.add_task(_run, post_id, drafter.revise, feedback, edited)
    return _redirect(post_id)


@app.post("/posts/{post_id}/save")
def save(post_id: str, markdown: str = Form(...)):
    _require_status(_meta_or_404(post_id), "in_review")
    store.save_markdown(post_id, markdown)
    return _redirect(post_id)


@app.post("/posts/{post_id}/retry")
def retry(post_id: str, background: BackgroundTasks):
    _require_status(_meta_or_404(post_id), "failed")
    store.update_meta(post_id, status="drafting", error=None)
    background.add_task(_run, post_id, drafter.draft)
    return _redirect(post_id)


@app.post("/posts/{post_id}/approve")
def approve(post_id: str, background: BackgroundTasks, markdown: str = Form(...)):
    _require_status(_meta_or_404(post_id), "in_review")
    store.save_markdown(post_id, markdown)
    try:
        publisher.open_pull_request(post_id)
    except publisher.PublishError as e:
        store.update_meta(post_id, error=str(e))
    else:
        # Compare Claude's first draft with what shipped and propose skill.md rules.
        background.add_task(style.learn_from_post, post_id)
    return _redirect(post_id)


# ---------------------------------------------------------------- style


def _style_redirect() -> RedirectResponse:
    return RedirectResponse("/style", status_code=303)


@app.get("/style", response_class=HTMLResponse)
def style_page(request: Request):
    examples = style.local_examples()
    return templates.TemplateResponse(request, "style.html", {
        "skill": style.read_skill(),
        "skill_path": SKILL_PATH.name,
        "proposal": style.proposal(),
        "suggestions": style.suggestions(),
        "hand_picked": [name for name, _ in examples],
        "drafting_examples": [name for name, _ in style.example_posts()],
        "published": style.published_status(),
        "repo": GITHUB_REPO,
    })


@app.post("/style/skill")
def style_save(skill: str = Form(...)):
    style.save_skill(skill)
    return _style_redirect()


@app.post("/style/generate")
def style_generate(background: BackgroundTasks, pasted: str = Form("")):
    if style.proposal().get("status") != "generating":
        style.start_proposal()
        background.add_task(style.generate_proposal, pasted)
    return _style_redirect()


@app.post("/style/proposal/accept")
def style_proposal_accept(skill: str = Form(...)):
    style.save_skill(skill)
    style.discard_proposal()
    return _style_redirect()


@app.post("/style/proposal/discard")
def style_proposal_discard():
    style.discard_proposal()
    return _style_redirect()


@app.post("/style/suggestions/{suggestion_id}")
def style_suggestion(suggestion_id: str, action: str = Form(...), rule: str = Form("")):
    style.resolve_suggestion(suggestion_id, accept=action == "accept", rule=rule)
    return _style_redirect()


@app.post("/style/suggestions-error/dismiss")
def style_dismiss_error():
    style.dismiss_error()
    return _style_redirect()


@app.post("/style/refresh")
def style_refresh():
    style.published_posts(0, force=True)
    return _style_redirect()
