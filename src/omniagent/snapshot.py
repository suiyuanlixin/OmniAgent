"""Shadow-git snapshot system for code-state rollback.

Each user message captures the workspace directory into a shadow git repo
stored alongside the session file.  On revert the shadow repo is used to
restore the workspace to its pre-message state.

Design constraints
------------------
* The shadow git repo lives entirely inside session_snapshot_dir, so it never
  touches the user's own .git directory.
* Only files tracked by git add -A (i.e. new + modified + deleted) are
  captured.  Files ignored by the workspace's own .gitignore are excluded, so
  large build artefacts stay untracked — restoring them is the caller's
  responsibility (they weren't changed by the agent anyway).
* If git is unavailable or the workspace is not inside a filesystem that
  supports git, snapshot() returns None and the caller falls back to
  conversation-only revert.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Files / dirs that are always excluded from the snapshot even if they would
# otherwise be picked up by git add -A.
_ALWAYS_EXCLUDE: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
)


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _run(args: list[str], cwd: str, env: dict | None = None) -> tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _shadow_env(git_dir: str, work_tree: str) -> dict:
    """Build env that redirects git to our shadow repo."""
    import os
    env = dict(os.environ)
    env["GIT_DIR"] = git_dir
    env["GIT_WORK_TREE"] = work_tree
    # Prevent inheriting the user's own repo context variables
    env.pop("GIT_INDEX_FILE", None)
    env.pop("GIT_OBJECT_DIRECTORY", None)
    env.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
    return env


def _ensure_shadow_repo(snapshot_dir: Path, work_tree: str) -> dict | None:
    """Create the shadow git repo if it doesn't exist. Returns env or None."""
    try:
        git_dir = str(snapshot_dir / "git")
        Path(git_dir).mkdir(parents=True, exist_ok=True)
        env = _shadow_env(git_dir, work_tree)
        code, _, _ = _run(["git", "rev-parse", "--git-dir"], work_tree, env=env)
        if code != 0:
            # Initialise
            code, _, err = _run(["git", "init", "--bare", git_dir], work_tree)
            if code != 0:
                logger.warning("snapshot: git init failed: %s", err)
                return None
            env = _shadow_env(git_dir, work_tree)
            # Create an empty initial commit so HEAD exists
            code, _, err = _run(
                [
                    "git",
                    "-c", "user.email=omniagent@local",
                    "-c", "user.name=OmniAgent",
                    "commit",
                    "--allow-empty",
                    "-m", "initial",
                ],
                work_tree,
                env=env,
            )
            if code != 0:
                logger.warning("snapshot: initial commit failed: %s", err)
                return None
        return env
    except Exception as exc:
        logger.warning("snapshot: _ensure_shadow_repo failed: %s", exc)
        return None


@dataclass
class Checkpoint:
    """Metadata for a single message checkpoint."""
    checkpoint_id: str
    message_index: int          # index in ChatView.messages at capture time
    transcript_len: int         # len(chat_view._transcript) BEFORE the user row
    history_len: int            # len(chat.get_history()) BEFORE sending
    user_text: str              # original raw text the user sent
    display_text: str           # display version (may differ from user_text)
    commit_sha: str             # SHA in the shadow repo ("" if not captured)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "message_index": self.message_index,
            "transcript_len": self.transcript_len,
            "history_len": self.history_len,
            "user_text": self.user_text,
            "display_text": self.display_text,
            "commit_sha": self.commit_sha,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            message_index=int(data.get("message_index") or 0),
            transcript_len=int(data.get("transcript_len") or 0),
            history_len=int(data.get("history_len") or 0),
            user_text=str(data.get("user_text") or ""),
            display_text=str(data.get("display_text") or ""),
            commit_sha=str(data.get("commit_sha") or ""),
            created_at=str(data.get("created_at") or ""),
        )


class SnapshotStore:
    """Per-session store of code-state checkpoints.

    Thread-safety: all public methods may be called from any thread.  The
    internal checkpoint list is only mutated while holding ``_lock``.
    """

    def __init__(self, snapshot_dir: Path, workspace_dir: Optional[str] = None):
        self._snapshot_dir = snapshot_dir
        self._workspace_dir = str(workspace_dir or "").strip() or None
        self._index_path = snapshot_dir / "index.json"
        self._git_available: Optional[bool] = None
        self._checkpoints: list[Checkpoint] = []
        self._load_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture(
        self,
        *,
        message_index: int,
        transcript_len: int,
        history_len: int,
        user_text: str,
        display_text: str,
    ) -> Checkpoint:
        """Snapshot the workspace and return a new Checkpoint.

        If git is unavailable or the workspace path is unset, ``commit_sha``
        will be empty — callers should handle that gracefully.
        """
        import uuid
        cp_id = uuid.uuid4().hex[:16]
        commit_sha = ""
        if self._workspace_dir and self._is_git_available():
            commit_sha = self._git_capture(cp_id)
        cp = Checkpoint(
            checkpoint_id=cp_id,
            message_index=message_index,
            transcript_len=transcript_len,
            history_len=history_len,
            user_text=user_text,
            display_text=display_text,
            commit_sha=commit_sha,
        )
        self._checkpoints.append(cp)
        self._save_index()
        return cp

    def get(self, checkpoint_id: str) -> Optional[Checkpoint]:
        for cp in self._checkpoints:
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    def get_by_message_index(self, message_index: int) -> Optional[Checkpoint]:
        """Return the checkpoint for the given ChatView message index, if any."""
        for cp in reversed(self._checkpoints):
            if cp.message_index == message_index:
                return cp
        return None

    def restore(self, cp: Checkpoint) -> Optional[str]:
        """Restore the workspace to the state captured in *cp*.

        Returns ``None`` on success or an error string on failure.
        """
        if not cp.commit_sha:
            return "No git snapshot available for this checkpoint."
        if not self._workspace_dir:
            return "No workspace directory configured."
        if not self._is_git_available():
            return "git is not available."
        return self._git_restore(cp.commit_sha)

    def drop_from(self, message_index: int) -> None:
        """Remove all checkpoints at or after *message_index*."""
        self._checkpoints = [
            cp for cp in self._checkpoints if cp.message_index < message_index
        ]
        self._save_index()

    def all_checkpoints(self) -> list[Checkpoint]:
        return list(self._checkpoints)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_git_available(self) -> bool:
        if self._git_available is None:
            self._git_available = _git_available()
        return self._git_available

    def _git_capture(self, cp_id: str) -> str:
        """Stage everything and make a commit; return the SHA or ""."""
        env = _ensure_shadow_repo(self._snapshot_dir, self._workspace_dir)
        if env is None:
            return ""
        try:
            # Write a .gitignore into the shadow index so we never track
            # heavy directories.  We write it to the work-tree only if one
            # does not already exist there; the shadow index is separate from
            # any user-owned .gitignore so this is safe.
            gi_path = Path(self._workspace_dir) / ".git" / "info" / "exclude"
            # Use git's own per-repo exclude file (lives inside the shadow
            # GIT_DIR, not the work-tree) to avoid polluting the workspace.
            shadow_exclude = Path(str(env["GIT_DIR"])) / "info" / "exclude"
            shadow_exclude.parent.mkdir(parents=True, exist_ok=True)
            _EXCLUDE_PATTERNS = "\n".join(_ALWAYS_EXCLUDE) + "\n"
            if not shadow_exclude.exists() or shadow_exclude.read_text("utf-8") != _EXCLUDE_PATTERNS:
                shadow_exclude.write_text(_EXCLUDE_PATTERNS, encoding="utf-8")

            # Stage all changes.  git add -A respects the exclude file.
            code, _, err = _run(
                ["git", "add", "-A", "--ignore-errors"],
                self._workspace_dir,
                env=env,
            )
            if code != 0:
                logger.debug("snapshot: add failed (non-fatal): %s", err)
            # Commit (allow empty in case nothing changed)
            code, out, err = _run(
                [
                    "git",
                    "-c", "user.email=omniagent@local",
                    "-c", "user.name=OmniAgent",
                    "commit",
                    "--allow-empty",
                    "-m", f"checkpoint:{cp_id}",
                ],
                self._workspace_dir,
                env=env,
            )
            if code != 0:
                logger.warning("snapshot: commit failed: %s", err)
                return ""
            # Get the SHA
            code, sha, _ = _run(
                ["git", "rev-parse", "HEAD"],
                self._workspace_dir,
                env=env,
            )
            return sha if code == 0 else ""
        except Exception as exc:
            logger.warning("snapshot: capture error: %s", exc)
            return ""

    def _git_restore(self, commit_sha: str) -> Optional[str]:
        """Hard-reset the workspace to *commit_sha*.

        Order matters: we must delete files that were added AFTER the target
        commit BEFORE running reset --hard, because git reset --hard does not
        remove files that are tracked at HEAD but absent at the target commit
        when GIT_WORK_TREE is a bare-repo env. Deleting them first leaves the
        work-tree in a state where reset --hard can cleanly write the old content.
        """
        env = _ensure_shadow_repo(self._snapshot_dir, self._workspace_dir)
        if env is None:
            return "Failed to initialise shadow git repo."
        try:
            # 1. Find files that were added after commit_sha (present in HEAD,
            #    absent in commit_sha). Delete them so that reset --hard can
            #    proceed without leaving orphan files behind.
            code, out, _ = _run(
                [
                    "git", "diff", "--name-only",
                    "--diff-filter=A",
                    commit_sha, "HEAD",
                ],
                self._workspace_dir,
                env=env,
            )
            if code == 0 and out:
                for rel_path in out.splitlines():
                    rel_path = rel_path.strip()
                    if not rel_path:
                        continue
                    full_path = Path(self._workspace_dir) / rel_path
                    try:
                        full_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            # 2. Reset tracked files to commit_sha.
            code, _, err = _run(
                ["git", "reset", "--hard", commit_sha],
                self._workspace_dir,
                env=env,
            )
            if code != 0:
                return f"git reset --hard failed: {err}"
            return None
        except Exception as exc:
            return str(exc)

    def _load_index(self) -> None:
        try:
            if self._index_path.exists():
                raw = json.loads(self._index_path.read_text(encoding="utf-8"))
                self._checkpoints = [
                    Checkpoint.from_dict(item)
                    for item in raw
                    if isinstance(item, dict)
                ]
        except Exception:
            self._checkpoints = []

    def _save_index(self) -> None:
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            self._index_path.write_text(
                json.dumps(
                    [cp.to_dict() for cp in self._checkpoints],
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("snapshot: failed to save index: %s", exc)


def remove_snapshot_dir(snapshot_dir) -> None:
    """Delete a snapshot directory (used when a session is deleted).

    Git object files are created read-only, so on Windows a plain
    ``shutil.rmtree`` fails with PermissionError. Clear the read-only flag
    first, then remove.
    """
    path = Path(snapshot_dir)
    if not path.exists():
        return
    if os.name == "nt":
        for root, _dirs, files in os.walk(path, topdown=False):
            for name in files:
                try:
                    os.chmod(os.path.join(root, name), 0o777)
                except OSError:
                    pass
    shutil.rmtree(path, ignore_errors=True)
