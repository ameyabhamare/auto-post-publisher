import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# One folder per user with their style file, examples and drafts (see users.py).
USERS_DIR = ROOT / "users"
# Signs login cookies. Set it in .env; otherwise one is generated and kept in users/.secret_key.
SECRET_KEY = os.getenv("SECRET_KEY", "")
# Send the login cookie only over HTTPS. Turn on when the app is served behind TLS.
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "").lower() in ("1", "true", "yes")

# Example posts sent with every draft: hand-picked ones in EXAMPLES_DIR first, then the most
# recent posts published to GITHUB_REPO fill the remaining slots.
EXAMPLE_COUNT = int(os.getenv("EXAMPLE_COUNT", "3"))
# How many published posts the style-file generator reads.
STYLE_SOURCE_COUNT = int(os.getenv("STYLE_SOURCE_COUNT", "10"))

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("CLAUDE_EFFORT", "medium")

# Defaults for users who haven't set their own repo and token on the Account page.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # "owner/name"
GITHUB_BASE_BRANCH = os.getenv("GITHUB_BASE_BRANCH", "main")
POSTS_DIR_IN_REPO = os.getenv("POSTS_DIR_IN_REPO", "posts")

AUTHOR_NAME = os.getenv("AUTHOR_NAME", "")

# Longest image edge sent to Claude and committed to the repo.
MAX_IMAGE_EDGE = 1568
