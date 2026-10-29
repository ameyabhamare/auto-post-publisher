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

Either:

- **Generate it.** Once the app is running, open **Style** and click *Generate style file*. Claude
  reads your published posts (plus anything in `examples/` or pasted in) and proposes a `skill.md`
  you edit before saving.
- **Or bring your own.** Copy your `skill.md` into the project root. `skill.example.md` shows what
  it can contain.

Your most recent published posts are sent as examples automatically. To pin specific posts
instead, put them in `examples/` as `.md` files; they always come first.

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

- **Style** (`app/style.py`, the *Style* page):
  - *Examples*: every draft gets up to `EXAMPLE_COUNT` example posts, hand-picked `examples/` first,
    then your newest posts from `GITHUB_REPO`. Published posts are cached in `data/style/` and
    re-checked on GitHub at most every 10 minutes, so the prompt cache keeps hitting.
  - *Generate*: one Claude request reads up to `STYLE_SOURCE_COUNT` past posts and proposes a full
    `skill.md`, keeping rules you already wrote unless your posts contradict them.
  - *Learn from edits*: after you approve a post, Claude compares its first draft and your revision
    feedback with what you shipped and suggests up to three new rules. Nothing changes until you
    accept a suggestion; you can reword it first. Saving over `skill.md` keeps the old one as
    `skill.md.bak`.

Drafts and style data are stored locally in `data/` (git-ignored).
