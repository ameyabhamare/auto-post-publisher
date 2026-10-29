import re
import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import markdown as md
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import drafter, publisher, store, style, users
from .config import SECRET_KEY, SECURE_COOKIES, USERS_DIR
from .users import User

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _secret_key() -> str:
    if SECRET_KEY:
        return SECRET_KEY
    path = USERS_DIR / ".secret_key"
    if not path.exists():
        USERS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


app = FastAPI(title="Auto Post Publisher")
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key(),
    session_cookie="pp_session",
    max_age=30 * 24 * 3600,
    same_site="lax",  # cross-site form posts arrive without the cookie
    https_only=SECURE_COOKIES,
)


# ---------------------------------------------------------------- sign-in


class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
def _to_login(request: Request, exc: LoginRequired):
    target = request.url.path if request.method == "GET" else "/"
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


def _session_tag(user: User) -> str:
    # Changes when the password does, which signs out the user's other sessions.
    return user.password_hash[-16:]


def current_user(request: Request) -> User:
    user = users.get(request.session.get("user", ""))
    if not user or request.session.get("tag") != _session_tag(user):
        request.session.clear()
        raise LoginRequired()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def _page(request: Request, template: str, user: User | None, context: dict) -> HTMLResponse:
    return templates.TemplateResponse(request, template, {"user": user, **context})


def _safe_next(target: str) -> str:
    return target if target.startswith("/") and not target.startswith("//") else "/"


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return _page(request, "login.html", None, {"next": _safe_next(next), "error": None,
                                                "no_users": not users.all_users()})


@app.post("/login")
def login(request: Request, name: str = Form(...), password: str = Form(...), next: str = Form("/")):
    user = users.authenticate(name, password)
    if not user:
        return _page(request, "login.html", None, {"next": _safe_next(next), "error": "Wrong name or password.",
                                                    "no_users": False, "name": name})
    request.session.clear()
    request.session.update(user=user.name, tag=_session_tag(user))
    return RedirectResponse(_safe_next(next), status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- posts


def _run(user: User, post_id: str, fn, *args) -> None:
    """Run a drafting step in the background and record failures on the post."""
    try:
        fn(user, post_id, *args)
    except Exception as e:  # surface every failure on the review page
        has_draft = bool(store.load_markdown(user, post_id))
        store.update_meta(user, post_id, status="in_review" if has_draft else "failed", error=str(e))


def _meta_or_404(user: User, post_id: str) -> dict:
    try:
        return store.load_meta(user, post_id)
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
def index(request: Request, user: CurrentUser):
    return _page(request, "index.html", user, {
        "posts": store.list_posts(user),
        "skill_missing": not user.skill_path.exists(),
        "repo": user.repo,
        "suggestion_count": len(style.suggestions(user)["items"]),
    })


@app.post("/posts")
async def create(user: CurrentUser, background: BackgroundTasks, content: str = Form(...),
                 images: list[UploadFile] = File(default=[])):
    uploads = [(f.filename, await f.read()) for f in images if f.filename]
    try:
        post_id = store.create_post(user, content, uploads)
    except Exception as e:
        raise HTTPException(400, f"Could not read an image: {e}")
    background.add_task(_run, user, post_id, drafter.draft)
    return _redirect(post_id)


@app.get("/posts/{post_id}", response_class=HTMLResponse)
def view(request: Request, user: CurrentUser, post_id: str):
    meta = _meta_or_404(user, post_id)
    text = store.load_markdown(user, post_id)
    return _page(request, "post.html", user, {
        "meta": meta,
        "markdown": text,
        "preview": _render_preview(post_id, text) if text else "",
        "images": [p.name for p in store.list_images(user, post_id)],
        "revisions": sum(1 for m in store.load_messages(user, post_id) if m["role"] == "assistant"),
    })


@app.get("/posts/{post_id}/images/{name}")
def image(user: CurrentUser, post_id: str, name: str):
    _meta_or_404(user, post_id)
    path = store.post_dir(user, post_id) / "images" / Path(name).name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


def _require_status(meta: dict, *allowed: str) -> None:
    if meta["status"] not in allowed:
        raise HTTPException(409, f"Post is '{meta['status']}'; this action needs {' or '.join(allowed)}.")


@app.post("/posts/{post_id}/revise")
def revise(user: CurrentUser, post_id: str, background: BackgroundTasks, feedback: str = Form(""),
           markdown: str = Form(...)):
    _require_status(_meta_or_404(user, post_id), "in_review")
    store.save_markdown(user, post_id, markdown)
    edited = store.load_markdown(user, post_id) if store.has_human_edits(user, post_id) else None
    store.update_meta(user, post_id, status="drafting", error=None)
    background.add_task(_run, user, post_id, drafter.revise, feedback, edited)
    return _redirect(post_id)


@app.post("/posts/{post_id}/save")
def save(user: CurrentUser, post_id: str, markdown: str = Form(...)):
    _require_status(_meta_or_404(user, post_id), "in_review")
    store.save_markdown(user, post_id, markdown)
    return _redirect(post_id)


@app.post("/posts/{post_id}/retry")
def retry(user: CurrentUser, post_id: str, background: BackgroundTasks):
    _require_status(_meta_or_404(user, post_id), "failed")
    store.update_meta(user, post_id, status="drafting", error=None)
    background.add_task(_run, user, post_id, drafter.draft)
    return _redirect(post_id)


@app.post("/posts/{post_id}/approve")
def approve(user: CurrentUser, post_id: str, background: BackgroundTasks, markdown: str = Form(...)):
    _require_status(_meta_or_404(user, post_id), "in_review")
    store.save_markdown(user, post_id, markdown)
    try:
        publisher.open_pull_request(user, post_id)
    except publisher.PublishError as e:
        store.update_meta(user, post_id, error=str(e))
    else:
        # Compare Claude's first draft with what shipped and propose skill.md rules.
        background.add_task(style.learn_from_post, user, post_id)
    return _redirect(post_id)


# ---------------------------------------------------------------- style


def _style_redirect() -> RedirectResponse:
    return RedirectResponse("/style", status_code=303)


@app.get("/style", response_class=HTMLResponse)
def style_page(request: Request, user: CurrentUser):
    examples = style.local_examples(user)
    return _page(request, "style.html", user, {
        "skill": style.read_skill(user),
        "skill_path": f"users/{user.name}/skill.md",
        "examples_path": f"users/{user.name}/examples/",
        "proposal": style.proposal(user),
        "suggestions": style.suggestions(user),
        "hand_picked": [name for name, _ in examples],
        "drafting_examples": [name for name, _ in style.example_posts(user)],
        "published": style.published_status(user),
        "repo": f"{user.repo}/{user.repo_posts_dir}" if user.repo else "",
    })


@app.post("/style/skill")
def style_save(user: CurrentUser, skill: str = Form(...)):
    style.save_skill(user, skill)
    return _style_redirect()


@app.post("/style/generate")
def style_generate(user: CurrentUser, background: BackgroundTasks, pasted: str = Form("")):
    if style.proposal(user).get("status") != "generating":
        style.start_proposal(user)
        background.add_task(style.generate_proposal, user, pasted)
    return _style_redirect()


@app.post("/style/proposal/accept")
def style_proposal_accept(user: CurrentUser, skill: str = Form(...)):
    style.save_skill(user, skill)
    style.discard_proposal(user)
    return _style_redirect()


@app.post("/style/proposal/discard")
def style_proposal_discard(user: CurrentUser):
    style.discard_proposal(user)
    return _style_redirect()


@app.post("/style/suggestions/{suggestion_id}")
def style_suggestion(user: CurrentUser, suggestion_id: str, action: str = Form(...), rule: str = Form("")):
    style.resolve_suggestion(user, suggestion_id, accept=action == "accept", rule=rule)
    return _style_redirect()


@app.post("/style/suggestions-error/dismiss")
def style_dismiss_error(user: CurrentUser):
    style.dismiss_error(user)
    return _style_redirect()


@app.post("/style/refresh")
def style_refresh(user: CurrentUser):
    style.published_posts(user, 0, force=True)
    return _style_redirect()


# ---------------------------------------------------------------- account


def _account(request: Request, user: User, message: str | None = None, error: str | None = None):
    return _page(request, "account.html", user, {"message": message, "error": error})


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: CurrentUser, saved: bool = False):
    return _account(request, user, message="Saved." if saved else None)


@app.post("/account")
def account_save(
    request: Request,
    user: CurrentUser,
    display_name: str = Form(""),
    author_name: str = Form(""),
    github_repo: str = Form(""),
    github_token: str = Form(""),
    clear_token: bool = Form(False),
    github_base_branch: str = Form(""),
    posts_dir: str = Form(""),
):
    repo = github_repo.strip()
    if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return _account(request, user, error="Repo must look like owner/name.")
    user.display_name = display_name.strip()
    user.author_name = author_name.strip()
    user.github_repo = repo
    user.github_base_branch = github_base_branch.strip()
    user.posts_dir = posts_dir.strip().strip("/")
    if clear_token:
        user.github_token = ""
    elif github_token.strip():  # blank keeps the saved token
        user.github_token = github_token.strip()
    user.save()
    return RedirectResponse("/account?saved=1", status_code=303)


@app.post("/account/password")
def account_password(request: Request, user: CurrentUser, current: str = Form(...), new: str = Form(...),
                     repeat: str = Form(...)):
    if not user.check_password(current):
        return _account(request, user, error="Current password is wrong.")
    if len(new) < 8:
        return _account(request, user, error="Use at least 8 characters.")
    if new != repeat:
        return _account(request, user, error="New passwords don't match.")
    user.set_password(new)
    user.save()
    request.session.update(tag=_session_tag(user))  # stay signed in here; other sessions end
    return RedirectResponse("/account?saved=1", status_code=303)
