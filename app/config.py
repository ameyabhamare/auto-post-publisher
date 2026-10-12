import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data" / "posts"
SKILL_PATH = ROOT / os.getenv("SKILL_PATH", "skill.md")
EXAMPLES_DIR = ROOT / os.getenv("EXAMPLES_DIR", "examples")

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("CLAUDE_EFFORT", "medium")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # "owner/name"
GITHUB_BASE_BRANCH = os.getenv("GITHUB_BASE_BRANCH", "main")
POSTS_DIR_IN_REPO = os.getenv("POSTS_DIR_IN_REPO", "posts")

AUTHOR_NAME = os.getenv("AUTHOR_NAME", "")

# Longest image edge sent to Claude and committed to the repo.
MAX_IMAGE_EDGE = 1568
