"""Rama de respaldo: qué se publica, cómo se apunta y cuándo se da por al día."""
import json
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
                          "data/raw/COL/crudo.xlsx": "pesado", "data/raw/_global/otro.gz": "pesado"}.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf8")
    run(work, "add", ".")
    run(work, "commit", "-qm", "inicial")
    run(work, "push", "-q", "origin", "main")
    run(work, "fetch", "-q", "origin")
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


def branch_tip(repo):
    return run(repo, "ls-remote", "--heads", "origin", pc.BRANCH).split()[0]


def test_light_tree_has_only_data_without_raw(repo):
    assert set(pc.list_blobs(pc.light_tree("main"))) == {"data/status.json", "data/processed/COL.json"}


def test_new_contract_files_are_published_without_listing_them(repo):
    commit_file(repo, "data/processed/region.json", "{}")
    assert "data/processed/region.json" in pc.list_blobs(pc.light_tree("main"))


def test_publish_pins_data_commit_and_points_to_it(repo):
    data_commit, pointer_sha, new = pc.publish()
    tip = branch_tip(repo)
    run(repo, "fetch", "-q", "origin", pc.BRANCH)
    assert new is True
    assert run(repo, "rev-parse", f"{tip}^") == data_commit
    pointer = json.loads(run(repo, "show", f"{tip}:{pc.POINTER}"))
    assert pointer == {"commit": data_commit, "main": run(repo, "rev-parse", "origin/main")}
    assert run(repo, "rev-parse", f"{tip}:{pc.POINTER}") == pointer_sha
    assert set(pc.list_blobs(data_commit)) == {"data/status.json", "data/processed/COL.json"}


def test_publish_is_idempotent_and_ignores_changes_in_raw(repo):
    data_commit, pointer_sha, _ = pc.publish()
    tip = branch_tip(repo)
    commit_file(repo, "data/raw/COL/otro.xlsx", "no se publica")
    assert pc.publish() == (data_commit, pointer_sha, False)
    assert branch_tip(repo) == tip


def test_publish_fast_forwards_when_data_changes(repo):
    pc.publish()
    first = branch_tip(repo)
    commit_file(repo, "data/status.json", '{"a": 1}')
    data_commit, _, new = pc.publish()
    run(repo, "fetch", "-q", "origin", pc.BRANCH)
    assert new is True and run(repo, "rev-parse", f"{data_commit}^") == first


def test_publish_adds_pointer_to_a_branch_without_one(repo):
    tree = pc.light_tree("origin/main")
    old = run(repo, "commit-tree", tree, "-m", "sin puntero")
    run(repo, "push", "-q", "origin", f"{old}:refs/heads/{pc.BRANCH}")
    data_commit, _, new = pc.publish()
    run(repo, "fetch", "-q", "origin", pc.BRANCH)
    assert new is True and run(repo, "rev-parse", f"{data_commit}^") == old


def test_publish_refuses_a_branch_jsdelivr_would_reject(repo, monkeypatch):
    monkeypatch.setattr(pc, "MAX_BYTES", 1)
    with pytest.raises(SystemExit):
        pc.publish()
    assert run(repo, "ls-remote", "--heads", "origin", pc.BRANCH) == ""


def test_blob_sha_matches_git(repo):
    content = "población\n".encode("utf8")
    assert pc.blob_sha(content) == run(repo, "hash-object", "--stdin", stdin=content.decode("utf8"))


def test_check_files_retries_and_reports():
    answers = iter(["HTTP 403", "HTTP 403", "1", "HTTP 403"])  # primera vuelta a y b; en la segunda, a ya coincide
    wrong = pc.check_files("c", {"a": "1", "b": "2"}, waits=(0, 0), state=lambda c, p: next(answers), sleep=lambda s: None)
    assert wrong == {"b": "HTTP 403"}


def fake_pointer(answers, resets=()):
    answers, resets = iter(answers), iter(resets)
    calls = {"purges": 0, "sleeps": []}

    def purge():
        calls["purges"] += 1
        return next(resets, 0)

    return dict(state=lambda r, p: next(answers), purge_one=purge, sleep=calls["sleeps"].append), calls


def test_pointer_unchanged_is_not_purged():
    kw, calls = fake_pointer(["ok"])
    assert pc.sync_pointer("ok", new=False, waits=(1,), **kw) is None
    assert calls["purges"] == 0


def test_new_publication_purges_even_if_it_looks_current():
    kw, calls = fake_pointer(["ok", "ok"])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1), **kw) is None
    assert calls["purges"] == 1


def test_pointer_purges_again_after_catching_up():
    kw, calls = fake_pointer(["viejo", "ok", "ok"])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1, 1), **kw) is None
    assert calls["purges"] == 2


def test_pointer_waits_for_throttle_reset():
    kw, calls = fake_pointer(["viejo", "ok", "ok"], resets=[100, 0])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1, 1), **kw) is None
    assert calls["sleeps"][0] == 105


def test_pointer_does_not_wait_for_a_throttled_confirmation():
    kw, calls = fake_pointer(["viejo", "ok"], resets=[0, 3000])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1, 1), **kw) is None
    assert calls["purges"] == 2 and calls["sleeps"] == [1]


def test_new_publication_waits_until_one_purge_goes_through():
    kw, calls = fake_pointer(["ok", "ok", "ok"], resets=[100, 0])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1, 1), **kw) is None
    assert calls["purges"] == 2 and calls["sleeps"][0] == 105


def test_pointer_gives_up_when_throttle_exceeds_limit():
    kw, calls = fake_pointer(["viejo"], resets=[9999])
    assert pc.sync_pointer("ok", new=True, waits=(1,), limit=600, **kw) == "viejo"
    assert calls["purges"] == 1


def test_pointer_reports_what_stays_behind():
    kw, _ = fake_pointer(["viejo", "viejo", "HTTP 403"])
    assert pc.sync_pointer("ok", new=True, waits=(1, 1), **kw) == "HTTP 403"
