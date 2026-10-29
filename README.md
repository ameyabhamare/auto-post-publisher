# Auto Post Publisher

A web app that turns your notes and photos into a blog post written in your voice,
lets you review and revise it, and then opens a pull request on GitHub with the post and images.
Several people can share one install: each signs in and has their own style, examples, drafts
and (optionally) their own posts repo.

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

### 2. Create the posts repo on GitHub

1. Go to <https://github.com/new>, name it (e.g. `posts`), and **tick "Add a README file"**.
   A pull request needs a branch with at least one commit.
2. Create a **fine-grained personal access token** at
   <https://github.com/settings/personal-access-tokens/new>:
   - Repository access: **Only select repositories** → your posts repo
   - Permissions: **Contents: Read and write**, **Pull requests: Read and write**

A team can share one repo (set it in `.env`), or each person can use their own (set on their
**Account** page).

### 3. Configure

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, plus `GITHUB_TOKEN` and
`GITHUB_REPO` (`username/posts`) for the shared default repo. Set `SECRET_KEY` to a long random
string, and `SECURE_COOKIES=true` if the app is served over HTTPS.

### 4. Create accounts

```powershell
python -m app.users add alice --display "Alice Example"
```

You'll be asked for a password. Other commands: `passwd NAME`, `list`, `remove NAME`.

- Users on the shared `.env` repo publish into their own folder, `posts/<name>/`, so their posts
  and examples never mix. Pass `--repo owner/name` (and optionally `--posts-dir`) to point
  someone at their own repo instead; they can also change it later on the Account page.
- **Upgrading from the single-user version?** Add yourself with `--import-existing`. That moves
  `skill.md`, `examples/` and `data/` into `users/<name>/`, and you keep publishing to `posts/`.

### 5. Run

```powershell
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000> and sign in. To let others on your network reach it, add
`--host 0.0.0.0`; put it behind HTTPS before exposing it to the internet.

### 6. Add your style

Open **Style**, then either:

- **Generate it.** Claude reads your published posts (plus your hand-picked examples and anything
  you paste in) and proposes a style file you edit before saving.
- **Or write your own** in the editor there. `skill.example.md` shows what it can contain.

Your most recent published posts are sent as examples automatically. To pin specific posts
instead, put them in `users/<name>/examples/` as `.md` files; they always come first.

## How it works

- **Accounts** (`app/users.py`): each user is a folder, `users/<name>/`, holding `user.json`
  (settings, a scrypt password hash, and their GitHub token if they set one), `skill.md`,
  `examples/` and `data/`. Sign-in uses a signed session cookie; changing a password signs out
  that user's other sessions. Every page and file is scoped to the signed-in user.
- **Drafting** (`app/drafter.py`): one Claude request with your `skill.md` and examples in a
  cached system prompt, the images attached, and a JSON schema for the output (title, slug,
  summary, tags, body). Revisions append your feedback to the same conversation, and if you edited
  the draft by hand Claude is shown your version and builds on it.
- **Review** (`app/main.py`): edit the markdown, see a rendered preview, ask for revisions,
  or approve.
- **Publishing** (`app/publisher.py`): approving creates one commit on a new branch
  `post/<user>/<slug>-<id>` containing `<posts folder>/<date>-<slug>/post.md` plus its images,
  and opens a PR.
  Merging the PR publishes the post.

- **Style** (`app/style.py`, the *Style* page):
  - *Examples*: every draft gets up to `EXAMPLE_COUNT` example posts, hand-picked `examples/` first,
    then your newest posts from your posts folder. Published posts are cached in `data/style/` and
    re-checked on GitHub at most every 10 minutes, so the prompt cache keeps hitting.
  - *Generate*: one Claude request reads up to `STYLE_SOURCE_COUNT` past posts and proposes a full
    `skill.md`, keeping rules you already wrote unless your posts contradict them.
  - *Learn from edits*: after you approve a post, Claude compares its first draft and your revision
    feedback with what you shipped and suggests up to three new rules. Nothing changes until you
    accept a suggestion; you can reword it first. Saving over `skill.md` keeps the old one as
    `skill.md.bak`.

All user data is stored locally in `users/` (git-ignored). `user.json` can contain a GitHub
token, so keep that folder private and back it up like any other secret.
