"""User accounts. Each user has a folder holding their style, examples, and drafts:

    users/<name>/user.json     settings and password hash (contains a GitHub token: keep private)
    users/<name>/skill.md      their style file
    users/<name>/examples/     hand-picked example posts
    users/<name>/data/posts/   drafts (see store.py)
    users/<name>/data/style/   published-post cache, proposals, suggestions (see style.py)

Accounts are managed from the command line:

    python -m app.users add NAME [--display "Full Name"] [--repo owner/posts] [--import-existing]
    python -m app.users passwd NAME
    python -m app.users list
    python -m app.users remove NAME
"""

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import (
    AUTHOR_NAME,
    GITHUB_BASE_BRANCH,
    GITHUB_REPO,
    GITHUB_TOKEN,
    POSTS_DIR_IN_REPO,
    ROOT,
    USERS_DIR,
)

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


@dataclass
class User:
    name: str
    display_name: str = ""
    author_name: str = ""
    # Empty means "use the value from .env", so a team can share one posts repo.
    github_repo: str = ""
    github_token: str = ""
    github_base_branch: str = ""
    posts_dir: str = ""
    password_hash: str = field(default="", repr=False)

    # Paths
    @property
    def folder(self) -> Path:
        return USERS_DIR / self.name

    @property
    def skill_path(self) -> Path:
        return self.folder / "skill.md"

    @property
    def examples_dir(self) -> Path:
        return self.folder / "examples"

    @property
    def posts_data_dir(self) -> Path:
        return self.folder / "data" / "posts"

    @property
    def style_dir(self) -> Path:
        return self.folder / "data" / "style"

    # Effective settings, falling back to .env
    @property
    def label(self) -> str:
        return self.display_name or self.name

    @property
    def author(self) -> str:
        return self.author_name or self.display_name or AUTHOR_NAME

    @property
    def repo(self) -> str:
        return self.github_repo or GITHUB_REPO

    @property
    def token(self) -> str:
        return self.github_token or GITHUB_TOKEN

    @property
    def base_branch(self) -> str:
        return self.github_base_branch or GITHUB_BASE_BRANCH

    @property
    def repo_posts_dir(self) -> str:
        return self.posts_dir or POSTS_DIR_IN_REPO

    def check_password(self, password: str) -> bool:
        try:
            salt, digest = self.password_hash.split("$", 1)
        except ValueError:
            return False
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt)), digest)

    def set_password(self, password: str) -> None:
        salt = secrets.token_bytes(16)
        self.password_hash = f"{salt.hex()}${_hash(password, salt)}"

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / "user.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)  # holds a password hash and maybe a GitHub token
        tmp.replace(path)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1).hex()


def valid_name(name: str) -> bool:
    return bool(NAME.fullmatch(name))


def get(name: str) -> User | None:
    if not valid_name(name):
        return None
    path = USERS_DIR / name / "user.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return User(**{k: v for k, v in data.items() if k in User.__dataclass_fields__})


def all_users() -> list[User]:
    if not USERS_DIR.exists():
        return []
    return [u for p in sorted(USERS_DIR.iterdir()) if p.is_dir() and (u := get(p.name))]


def authenticate(name: str, password: str) -> User | None:
    user = get(name.strip().lower())
    if user and user.check_password(password):
        return user
    # Spend the same time on unknown names so they can't be told apart.
    _hash(password, b"0" * 16)
    return None


# ---------------------------------------------------------------- command line


def _import_existing(user: User) -> list[str]:
    """Move a single-user install's skill.md, examples/ and data/ into this user's folder."""
    moved = []
    for src, dst in [
        (ROOT / "skill.md", user.skill_path),
        (ROOT / "skill.md.bak", user.folder / "skill.md.bak"),
        (ROOT / "examples", user.examples_dir),
        (ROOT / "data" / "posts", user.posts_data_dir),
        (ROOT / "data" / "style", user.style_dir),
    ]:
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, dst)
            moved.append(str(src.relative_to(ROOT)))
    return moved


def _ask_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        if len(password) < 8:
            print("Use at least 8 characters.")
        elif password != getpass.getpass("Repeat password: "):
            print("Passwords don't match.")
        else:
            return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.users", description="Manage Post Publisher users.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="create a user")
    add.add_argument("name", help="login name: lowercase letters, digits, - and _")
    add.add_argument("--display", default="", help="full name, also used as the post author")
    add.add_argument("--repo", default="", help="their own posts repo (owner/name); default: GITHUB_REPO from .env")
    add.add_argument("--posts-dir", default=None,
                     help="folder in the repo for their posts; default: POSTS_DIR_IN_REPO, or "
                          "POSTS_DIR_IN_REPO/<name> when sharing the .env repo")
    add.add_argument("--import-existing", action="store_true",
                     help="move the current skill.md, examples/ and data/ into this user's folder")

    for cmd, text in [("passwd", "set a user's password"), ("remove", "delete a user and all their drafts")]:
        sub.add_parser(cmd, help=text).add_argument("name")
    sub.add_parser("list", help="list users")

    args = parser.parse_args(argv)

    if args.command == "list":
        for u in all_users():
            print(f"{u.name:20} {u.label:24} {u.repo or '(no repo)'}:{u.repo_posts_dir}")
        return 0

    if args.command == "add":
        name = args.name.lower()
        if not valid_name(name):
            parser.error("name must be 1-32 lowercase letters, digits, - or _")
        if get(name):
            parser.error(f"user {name} already exists")
        user = User(name=name, display_name=args.display, github_repo=args.repo)
        if args.posts_dir is not None:
            user.posts_dir = args.posts_dir.strip("/")
        elif not args.repo and not args.import_existing:
            # Sharing the team repo: keep each person's posts in their own folder. An imported
            # install keeps publishing where it always has.
            user.posts_dir = f"{POSTS_DIR_IN_REPO}/{name}"
        user.set_password(_ask_password())
        user.save()
        if args.import_existing:
            moved = _import_existing(user)
            print("Moved into users/%s/: %s" % (name, ", ".join(moved) if moved else "nothing to move"))
        print(f"Created {name}. Posts go to {user.repo or '(set GITHUB_REPO)'}:{user.repo_posts_dir}.")
        if not user.github_repo:
            print("They can set their own repo and token on the Account page after signing in.")
        return 0

    user = get(args.name.lower())
    if not user:
        parser.error(f"no user named {args.name}")
    if args.command == "passwd":
        user.set_password(_ask_password())
        user.save()
        print("Password updated.")
    elif args.command == "remove":
        if input(f"Delete {user.name} and everything in users/{user.name}/? Type the name to confirm: ") != user.name:
            print("Cancelled.")
            return 1
        shutil.rmtree(user.folder)
        print("Removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
