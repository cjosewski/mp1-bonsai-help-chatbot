"""Git plumbing for pinned, partial documentation fetches.

Only trees and the selected blobs are downloaded (`--filter=blob:none`, then one explicit
blob fetch). Bytes are read from the object store, never from a working tree, so no
line-ending, attribute or LFS conversion applies. Lazy fetching is disabled everywhere.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from bonsai_help.doc_sources import OBJECT_ID, ConfigError, FetchError, PinMismatch, Repository

TIMEOUT_SECONDS = 600
GIT_OPTIONS = (
    "-c",
    "protocol.version=2",
    "-c",
    "core.autocrlf=false",
    "-c",
    "http.followRedirects=false",
    "-c",
    "fetch.writeCommitGraph=false",
)
PASS_THROUGH = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "GIT_SSL_CAINFO",
    "GIT_SSL_CAPATH",
)
REGULAR_MODES = ("100644", "100755")


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[list[str], Path | None, dict[str, str], bytes | None, float], Result]


def subprocess_runner(
    argv: list[str], cwd: Path | None, env: dict[str, str], stdin: bytes | None, timeout: float
) -> Result:
    try:
        done = subprocess.run(
            argv, cwd=cwd, env=env, input=stdin, capture_output=True, check=False, timeout=timeout
        )
    except FileNotFoundError:
        raise FetchError("git is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        raise FetchError(f"git {_subcommand(argv)} timed out after {timeout:.0f} s") from None
    return Result(done.returncode, done.stdout, done.stderr)


def _subcommand(argv: list[str]) -> str:
    index = 1
    while index < len(argv) and argv[index] in ("-c", "-C", "--no-lazy-fetch"):
        index += 1 if argv[index] == "--no-lazy-fetch" else 2
    return argv[index] if index < len(argv) else ""


def git_environment(allow_protocol: str = "https") -> dict[str, str]:
    """A fresh environment: no user or system config, no prompts, no LFS, no lazy fetch."""
    env = {name: os.environ[name] for name in PASS_THROUGH if name in os.environ}
    env.update(
        PATH=os.environ.get("PATH", "/usr/bin:/bin"),
        LC_ALL="C",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        SSH_ASKPASS="",
        GIT_LFS_SKIP_SMUDGE="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_ALLOW_PROTOCOL=allow_protocol,
    )
    return env


class Git:
    def __init__(self, runner: Runner = subprocess_runner, *, allow_protocol: str = "https"):
        self.runner = runner
        self.env = git_environment(allow_protocol)

    def run(
        self, *args: str, cwd: Path | None = None, stdin: bytes | None = None, check: bool = True
    ) -> Result:
        argv = ["git", "--no-lazy-fetch", *GIT_OPTIONS, *args]
        result = self.runner(argv, cwd, self.env, stdin, TIMEOUT_SECONDS)
        if check and result.returncode != 0:
            tail = " ".join(result.stderr[-500:].decode("utf-8", "replace").split())
            raise FetchError(f"git {args[0]} failed (exit {result.returncode}): {tail}")
        return result

    def require_feature(self) -> str:
        """Feature probe: `--no-lazy-fetch` (Git 2.44 or newer) must be understood."""
        result = self.runner(["git", "--no-lazy-fetch", "version"], None, self.env, None, 60)
        if result.returncode != 0:
            raise FetchError("git does not support --no-lazy-fetch; Git 2.44 or newer is needed")
        return result.stdout.decode("utf-8", "replace").strip()


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def parse_ls_remote(raw: bytes) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line:
            continue
        obj, sep, ref = line.partition("\t")
        if not sep or not OBJECT_ID.fullmatch(obj):
            raise FetchError(f"unexpected ls-remote line: {line[:120]!r}")
        refs[ref] = obj
    return refs


@dataclass(frozen=True)
class RefObservation:
    kind: str
    name: str
    object: str | None
    peeled: str | None
    matches: bool
    problem: str | None

    def record(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "object": self.object,
            "peeled": self.peeled,
            "matches_pin": self.matches,
        }


def resolve_ref(git: Git, cache: Path, repository: Repository) -> RefObservation:
    """Look the declared ref up by exact name (ls-remote patterns match ref tails)."""
    ref = repository.ref
    if ref.kind == "tag":
        full = f"refs/tags/{ref.name}"
        refs = parse_ls_remote(git.run("ls-remote", "origin", full, full + "^{}", cwd=cache).stdout)
        obj, peeled = refs.get(full), refs.get(full + "^{}")
        if obj is None:
            problem = f"tag {ref.name} not found upstream"
        elif ref.tag_object is None and (obj != repository.commit or peeled is not None):
            problem = (
                f"tag {ref.name} is {'annotated' if peeled else 'lightweight'} at "
                f"{peeled or obj}, pinned as lightweight at {repository.commit}"
            )
        elif ref.tag_object is not None and (obj != ref.tag_object or peeled != repository.commit):
            problem = (
                f"tag {ref.name} object {obj} peels to {peeled}; pinned tag object "
                f"{ref.tag_object} peeling to {repository.commit}"
            )
        else:
            problem = None
        return RefObservation("tag", ref.name, obj, peeled, problem is None, problem)
    full = f"refs/heads/{ref.name}"
    head = parse_ls_remote(git.run("ls-remote", "origin", full, cwd=cache).stdout).get(full)
    if head is None:
        problem = f"branch {ref.name} not found upstream"
    elif head != repository.commit:
        problem = (
            f"branch {ref.name} has moved to {head}; the pinned commit {repository.commit} governs"
        )
    else:
        problem = None
    return RefObservation("branch", ref.name, head, None, problem is None, problem)


def ensure_cache(git: Git, cache: Path, url: str, shown: str) -> None:
    """Create or reuse a bare partial-clone cache that belongs to exactly this URL."""
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        git.run("init", "-q", "--bare", str(cache))
        git.run("remote", "add", "origin", url, cwd=cache)
        return
    result = git.run("remote", "get-url", "origin", cwd=cache, check=False)
    if result.returncode != 0 or result.stdout.decode().strip() != url:
        raise ConfigError(f"cache {shown} is incomplete or belongs to another URL; remove it")


def has_object(git: Git, cache: Path, spec: str) -> bool:
    return git.run("cat-file", "-e", spec, cwd=cache, check=False).returncode == 0


def ensure_commit(git: Git, cache: Path, commit: str) -> None:
    """Fetch the pinned commit's history-free trees, never blobs."""
    if has_object(git, cache, commit + "^{commit}"):
        return
    git.run(
        "fetch",
        "-q",
        "--depth",
        "1",
        "--filter=blob:none",
        "--no-tags",
        "origin",
        commit,
        cwd=cache,
    )
    fetched = git.run("rev-parse", "--verify", "FETCH_HEAD^{commit}", cwd=cache).stdout
    if fetched.decode().strip() != commit:
        raise PinMismatch(f"fetching {commit} gave {fetched.decode().strip()}")


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    type: str
    oid: str
    path: str


def list_tree(git: Git, cache: Path, commit: str) -> list[TreeEntry]:
    raw = git.run(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        "--format=%(objectmode) %(objecttype) %(objectname)%x09%(path)",
        commit,
        cwd=cache,
    ).stdout
    entries = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        head, _, path = record.partition(b"\t")
        mode, kind, oid = head.decode().split(" ")
        entries.append(TreeEntry(mode, kind, oid, path.decode("utf-8", "surrogateescape")))
    return entries


def missing_objects(git: Git, cache: Path, oids: Iterable[str]) -> list[str]:
    wanted = sorted(set(oids))
    if not wanted:
        return []
    out = git.run("cat-file", "--batch-check", cwd=cache, stdin="\n".join(wanted).encode() + b"\n")
    return [
        line.split(" ")[0] for line in out.stdout.decode().splitlines() if line.endswith(" missing")
    ]


def fetch_blobs(git: Git, cache: Path, oids: Iterable[str]) -> int:
    """Fetch exactly the missing selected blobs in one request; returns how many were fetched."""
    missing = missing_objects(git, cache, oids)
    if missing:
        git.run(
            "fetch",
            "-q",
            "--no-tags",
            "--no-write-fetch-head",
            "--filter=blob:none",
            "--stdin",
            "origin",
            cwd=cache,
            stdin="\n".join(missing).encode() + b"\n",
        )
        still = missing_objects(git, cache, missing)
        if still:
            raise FetchError(
                f"the server did not send {len(still)} selected blobs, e.g. {still[0]}"
            )
    return len(missing)


def read_blobs(git: Git, cache: Path, oids: Iterable[str]) -> dict[str, bytes]:
    wanted = sorted(set(oids))
    if not wanted:
        return {}
    out = git.run("cat-file", "--batch", cwd=cache, stdin="\n".join(wanted).encode() + b"\n").stdout
    blobs: dict[str, bytes] = {}
    position = 0
    for oid in wanted:
        end = out.index(b"\n", position)
        header = out[position:end].decode().split(" ")
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise FetchError(f"object {oid} is not an available blob: {' '.join(header)}")
        size = int(header[2])
        blobs[oid] = out[end + 1 : end + 1 + size]
        position = end + 1 + size + 1
    return blobs
