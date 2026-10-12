"""Publishes an approved post as a pull request.

The post and its images go into a single commit on a new branch (Git Data API:
blobs -> tree -> commit -> ref), so a post is never half-published.
"""

import base64
from datetime import date

from github import Auth, Github, GithubException, InputGitTreeElement

from . import store
from .config import GITHUB_BASE_BRANCH, GITHUB_REPO, GITHUB_TOKEN, POSTS_DIR_IN_REPO


class PublishError(Exception):
    pass


def open_pull_request(post_id: str) -> str:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise PublishError("Set GITHUB_TOKEN and GITHUB_REPO in .env before publishing.")

    meta = store.load_meta(post_id)
    folder = f"{POSTS_DIR_IN_REPO}/{date.today().isoformat()}-{meta['slug']}"
    branch = f"post/{meta['slug']}-{post_id[:6]}"

    files: list[tuple[str, bytes]] = [(f"{folder}/post.md", store.load_markdown(post_id).encode("utf-8"))]
    files += [(f"{folder}/{img.name}", img.read_bytes()) for img in store.list_images(post_id)]

    try:
        repo = Github(auth=Auth.Token(GITHUB_TOKEN)).get_repo(GITHUB_REPO)
        base_sha = repo.get_branch(GITHUB_BASE_BRANCH).commit.sha
        base_commit = repo.get_git_commit(base_sha)

        tree_items = []
        for path, data in files:
            blob = repo.create_git_blob(base64.b64encode(data).decode("ascii"), "base64")
            tree_items.append(InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha))
        tree = repo.create_git_tree(tree_items, base_tree=base_commit.tree)

        commit = repo.create_git_commit(f"Add post: {meta['title']}", tree, [base_commit])
        repo.create_git_ref(ref=f"refs/heads/{branch}", sha=commit.sha)

        pr = repo.create_pull(
            title=f"New post: {meta['title']}",
            body=f"{meta.get('summary', '')}\n\nPreview: [`{folder}/post.md`]({repo.html_url}/blob/{branch}/{folder}/post.md)",
            head=branch,
            base=GITHUB_BASE_BRANCH,
        )
    except GithubException as e:
        message = e.data.get("message") if isinstance(e.data, dict) else str(e)
        raise PublishError(f"GitHub error {e.status}: {message}") from e

    store.update_meta(post_id, status="pr_open", pr_url=pr.html_url, branch=branch, error=None)
    return pr.html_url
