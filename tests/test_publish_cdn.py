"""Rama de respaldo: qué se publica y cuándo se da por al día."""
import subprocess

import pytest

from scripts import publish_cdn as pc


def run(repo, *args, stdin=None):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, input=stdin).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repositorio con main y un origin local, para publicar de verdad sin red."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    run(work, "config", "user.name", "prueba")
    run(work, "config", "user.email", "prueba@example.com")
    run(work, "remote", "add", "origin", str(origin))
    for name, content in {"README.md": "x", "data/status.json": "{}", "data/processed/COL.json": "{}",
                          "data/raw/COL/crudo.xlsx": "pesado", "data/raw/_regional/otro.xlsx": "pesado"}.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf8")
    run(work, "add", ".")
    run(work, "commit", "-qm", "inicial")
    run(work, "push", "-q", "origin", "main")
    monkeypatch.chdir(work)
    return work


def commit_file(repo, name, content):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")
    run(repo, "add", ".")
    run(repo, "commit", "-qm", f"cambia {name}")
    run(repo, "push", "-q", "origin", "main")
    run(repo, "fetch", "-q", "origin")


def test_light_tree_has_only_data_without_raw(repo):
    tree = pc.light_tree("main")
    assert set(pc.list_blobs(tree)) == {"data/status.json", "data/processed/COL.json"}


def test_new_contract_files_are_published_without_listing_them(repo):
    commit_file(repo, "data/processed/nuevo.json", "{}")
    assert "data/processed/nuevo.json" in pc.list_blobs(pc.light_tree("main"))


def test_publish_creates_then_fast_forwards_and_reports_changes(repo):
    run(repo, "fetch", "-q", "origin")
    _, changed = pc.publish()
    assert set(changed) == {"data/status.json", "data/processed/COL.json"}
    first = run(repo, "ls-remote", "--heads", "origin", pc.BRANCH).split()[0]

    assert pc.publish()[1] == []
    assert run(repo, "ls-remote", "--heads", "origin", pc.BRANCH).split()[0] == first

    commit_file(repo, "data/status.json", '{"a": 1}')
    commit_file(repo, "data/raw/COL/otro.xlsx", "no se publica")
    _, changed = pc.publish()
    assert changed == ["data/status.json"]
    second = run(repo, "ls-remote", "--heads", "origin", pc.BRANCH).split()[0]
    run(repo, "fetch", "-q", "origin", pc.BRANCH)
    assert run(repo, "rev-parse", f"{second}^") == first


def test_publish_refuses_a_branch_jsdelivr_would_reject(repo, monkeypatch):
    run(repo, "fetch", "-q", "origin")
    monkeypatch.setattr(pc, "MAX_BYTES", 1)
    with pytest.raises(SystemExit):
        pc.publish()
    assert run(repo, "ls-remote", "--heads", "origin", pc.BRANCH) == ""


def test_blob_sha_matches_git(repo):
    content = "población\n".encode("utf8")
    assert pc.blob_sha(content) == run(repo, "hash-object", "--stdin", stdin=content.decode("utf8"))


def test_sync_purges_changes_even_if_they_look_current():
    purged = []
    behind = pc.sync({"a": "1"}, ["a", "borrado"], waits=(0,), state=lambda p: "1", purge_one=purged.append, sleep=lambda s: None)
    assert behind == {} and purged == ["a", "borrado"]


def test_sync_retries_until_the_cdn_catches_up():
    answers = iter(["viejo", "HTTP 403", "1"])
    purged = []
    behind = pc.sync({"a": "1"}, [], waits=(0, 0, 0), state=lambda p: next(answers), purge_one=purged.append, sleep=lambda s: None)
    assert behind == {} and purged == ["a", "a"]


def test_sync_reports_what_stays_behind():
    behind = pc.sync({"a": "1", "b": "2"}, [], waits=(0, 0), state=lambda p: "1" if p == "a" else "HTTP 403",
                     purge_one=lambda p: None, sleep=lambda s: None)
    assert behind == {"b": "HTTP 403"}
