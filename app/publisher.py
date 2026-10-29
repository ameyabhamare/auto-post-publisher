"""Publishes an approved post as a pull request.

The post and its images go into a single commit on a new branch (Git Data API:
blobs -> tree -> commit -> ref), so a post is never half-published.
"""

import base64
from datetime import date

from github import Auth, Github, GithubException, InputGitTreeElement

from . import store
from .users import User


class PublishError(Exception):
    pass


def get_repo(user: User):
    if not user.token or not user.repo:
        raise PublishError("Set a GitHub repo and token on the Account page before publishing.")
    return Github(auth=Auth.Token(user.token)).get_repo(user.repo)


def open_pull_request(user: User, post_id: str) -> str:
    meta = store.load_meta(user, post_id)
    folder = f"{user.repo_posts_dir}/{date.today().isoformat()}-{meta['slug']}"
    branch = f"post/{user.name}/{meta['slug']}-{post_id[:6]}"

    files: list[tuple[str, bytes]] = [(f"{folder}/post.md", store.load_markdown(user, post_id).encode("utf-8"))]
    files += [(f"{folder}/{img.name}", img.read_bytes()) for img in store.list_images(user, post_id)]

    try:
        repo = get_repo(user)
        base_sha = repo.get_branch(user.base_branch).commit.sha
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
            base=user.base_branch,
        )
    except GithubException as e:
        message = e.data.get("message") if isinstance(e.data, dict) else str(e)
        raise PublishError(f"GitHub error {e.status}: {message}") from e

    store.update_meta(user, post_id, status="pr_open", pr_url=pr.html_url, branch=branch, error=None)
    return pr.html_url
