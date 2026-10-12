# Auto Post Publisher

A local web app that turns your notes and photos into a blog post written in your voice,
lets you review and revise it, and then opens a pull request on GitHub with the post and images.

```
content + images ─▶ Claude drafts (using skill.md) ─▶ you review ─┬─ revise ─▶ Claude redrafts
                                                                  └─ approve ─▶ PR on GitHub ─▶ you merge
```

## Setup

### 1. Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Add your style

- Copy your `skill.md` into the project root. `skill.example.md` shows what it can contain.
- Optional but strongly recommended: put 2–3 of your past posts in `examples/` as `.md` files.
  Examples teach the voice better than any description.

### 3. Create the posts repo on GitHub

1. Go to <https://github.com/new>, name it (e.g. `posts`), and **tick "Add a README file"**.
   A pull request needs a branch with at least one commit.
2. Create a **fine-grained personal access token** at
   <https://github.com/settings/personal-access-tokens/new>:
   - Repository access: **Only select repositories** → your posts repo
   - Permissions: **Contents: Read and write**, **Pull requests: Read and write**

### 4. Configure

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, and `GITHUB_REPO` (`username/posts`).

### 5. Run

```powershell
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

## How it works

- **Drafting** (`app/drafter.py`): one Claude request with your `skill.md` and examples in a
  cached system prompt, the images attached, and a JSON schema for the output (title, slug,
  summary, tags, body). Revisions append your feedback to the same conversation, and if you edited
  the draft by hand Claude is shown your version and builds on it.
- **Review** (`app/main.py`): edit the markdown, see a rendered preview, ask for revisions,
  or approve.
- **Publishing** (`app/publisher.py`): approving creates one commit on a new branch
  `post/<slug>-<id>` containing `posts/<date>-<slug>/post.md` plus its images, and opens a PR.
  Merging the PR publishes the post.

Drafts are stored locally in `data/posts/<id>/` (git-ignored).
