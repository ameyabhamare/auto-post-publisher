# Auto Post Publisher

Turn rough notes and photos into a finished blog post written in your voice. Review it, ask for
changes, and approve it. The app then opens a pull request on GitHub, and merging that PR
publishes the post.

```
notes + photos ─▶ Claude drafts in your style ─▶ you review ─┬─ revise ─▶ Claude redrafts
                                                             └─ approve ─▶ PR on GitHub ─▶ merge = published
```

## Features

- **Drafts in your voice.** Claude follows your style file (`skill.md`) and a few of your real
  posts as examples. It keeps your facts and opinions and doesn't invent new ones.
- **Review loop.** Edit the Markdown directly, see a live preview, or give feedback and get a new
  version. Claude builds on your hand edits instead of overwriting them.
- **Publishes through pull requests.** Each approved post becomes one commit with its images on a
  new branch, plus a PR. Nothing goes live until you merge.
- **Learns your style over time:**
  - Your most recent published posts are used as examples automatically.
  - It can generate a style file from your past posts.
  - After each post, it suggests new style rules based on what you changed. Nothing is added
    until you accept it.
- **Several people on one install.** Each person signs in and has their own style, examples and
  drafts. They can share one posts repo or use their own.

## Quick start

You need Python 3.10+, a Claude API key, and a GitHub repo for your posts.

```powershell
git clone https://github.com/ameyabhamare/auto-post-publisher.git
cd auto-post-publisher
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env
```

Fill in `.env` (see [Configuration](#configuration)), then create your account and start the app:

```powershell
python -m app.users add yourname --display "Your Name"
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>, sign in, and go to **Style** to set up your style file.

## Setup in detail

### 1. Posts repo and token

1. Create a repo for your posts at <https://github.com/new> and **tick "Add a README file"**
   (a pull request needs a branch with at least one commit). This can be the app's own repo,
   as it is here.
2. Create a **fine-grained personal access token** at
   <https://github.com/settings/personal-access-tokens/new>:
   - Repository access: **Only select repositories** → your posts repo
   - Permissions: **Contents: Read and write**, **Pull requests: Read and write**

Put the repo and token in `.env` to make them the default for everyone, or let each person set
their own on their **Account** page.

### 2. Accounts

Accounts are created on the machine running the app:

```powershell
python -m app.users add alice --display "Alice Example"   # asks for a password
python -m app.users list
python -m app.users passwd alice
python -m app.users remove alice
```

- People sharing the default repo each publish into their own folder, `posts/<name>/`, so their
  posts and examples never mix.
- To point someone at their own repo, pass `--repo owner/name` and optionally `--posts-dir`.
  They can also change this later on their Account page.

### 3. Your style

Open **Style** and either:

- **Generate a style file.** Claude reads your published posts, your hand-picked examples and
  anything you paste in, then proposes a `skill.md` for you to edit before saving.
- **Or write your own** in the editor there. [`skill.example.md`](skill.example.md) shows what
  it can contain.

To always use particular posts as examples, put them in `users/<name>/examples/` as `.md`
files. They come before your recent published posts.

### 4. Sharing it with others

By default the app only listens on your own computer. To let others on your network use it, run
`uvicorn app.main:app --host 0.0.0.0`. Before exposing it to the internet, serve it over HTTPS
and set `SECRET_KEY` and `SECURE_COOKIES=true` in `.env`.

## Using the app

| Page | What you do there |
| --- | --- |
| **Home** | Paste notes or a rough draft, add photos, and start a draft. See all your posts and their status. |
| **Post** | Edit the Markdown, preview it, ask for a revision, save, or approve. Approving opens the PR. |
| **Style** | Edit your style file, generate one from past posts, review suggested rules, see which example posts are in use. |
| **Account** | Set your display name, author name, posts repo, folder, branch and token. Change your password. |

## Configuration

Set these in `.env`. Only `ANTHROPIC_API_KEY` is required to draft. Publishing also needs a repo
and token, either here or on each person's Account page.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | | Claude API key. Can be left unset after `ant auth login`. |
| `SECRET_KEY` | generated | Signs login cookies. If unset, one is created in `users/.secret_key`. |
| `SECURE_COOKIES` | `false` | Send the login cookie over HTTPS only. Turn on behind TLS. |
| `GITHUB_TOKEN` | | Default token for people who haven't set their own. |
| `GITHUB_REPO` | | Default posts repo, `owner/name`. |
| `GITHUB_BASE_BRANCH` | `main` | Branch that PRs target. |
| `POSTS_DIR_IN_REPO` | `posts` | Folder in the repo for posts. |
| `AUTHOR_NAME` | | Author name for people who haven't set one. |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model used for drafting and style work. |
| `CLAUDE_EFFORT` | `medium` | How hard Claude thinks: `low` to `max`. |
| `EXAMPLE_COUNT` | `3` | Example posts sent with each draft. |
| `STYLE_SOURCE_COUNT` | `10` | Published posts read when generating a style file. |

## Upgrading from the single-user version

Earlier versions kept `skill.md`, `examples/` and `data/` in the project root and had no sign-in.
After pulling the latest code, run:

```powershell
pip install -r requirements.txt
python -m app.users add yourname --display "Your Name" --import-existing
```

`--import-existing` moves those files into `users/yourname/`, and you keep publishing to the same
`posts/` folder.

## How it works

- **Drafting** (`app/drafter.py`): one Claude request, with your style file and example posts in
  a cached system prompt, your photos attached, and a JSON schema for the output (title, slug,
  summary, tags, body). Each revision is added to the same conversation, so earlier context is
  reused instead of resent.
- **Publishing** (`app/publisher.py`): approving creates a single commit on a new branch,
  `post/<name>/<slug>-<id>`, containing `<posts folder>/<date>-<slug>/post.md` and its images,
  then opens a PR. A post is never half-published.
- **Style** (`app/style.py`):
  - Published posts are copied locally and checked on GitHub for changes at most every 10
    minutes, which keeps the prompt identical between drafts so caching keeps working.
  - Generating a style file is one request over your past posts. Rules you already wrote are
    kept unless your posts contradict them.
  - After you approve a post, Claude compares its first draft and your feedback with what you
    published and suggests up to three rules. Saving over `skill.md` keeps the old version as
    `skill.md.bak`.
- **Accounts** (`app/users.py`, `app/main.py`): sign-in uses a signed session cookie, and every
  page, post and image is limited to the signed-in person. Changing a password signs out that
  person's other sessions.

```
app/
  main.py        web routes, sign-in, account settings
  drafter.py     drafting and revising posts
  style.py       examples, style file generation, learning from edits
  publisher.py   commits and pull requests on GitHub
  users.py       accounts and the `python -m app.users` command
  store.py       drafts on disk
  llm.py         the shared Claude request
  templates/     HTML pages
users/<name>/    each person's user.json, skill.md, examples/ and data/ (not committed)
posts/           published posts (in this repo, the author's own blog)
```

## Security notes

- `users/<name>/user.json` holds a password hash and, if set, a GitHub token in plain text. The
  `users/` folder is git-ignored. On macOS and Linux the file is readable only by the account
  running the app; on Windows it relies on your user folder's permissions. Keep it private and
  back it up like any other secret.
- Use fine-grained tokens limited to the posts repo.
- There's no limit on login attempts beyond the deliberately slow password hashing. Keep the
  app on a trusted network, or behind HTTPS and a reverse proxy, if others can reach it.

## Published posts

Posts published with this app live in [`posts/`](posts/):

- [What Is an n8n Workflow? A Quick Tour of the Building Blocks](posts/2026-10-29-what-is-an-n8n-workflow/post.md)
- [From Prompt Engineering to Context Engineering](posts/2026-10-07-prompt-engineering-to-context-engineering/post.md)
