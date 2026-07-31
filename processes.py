from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class TerminationResult:
    return_code: int | None
    status: str
    detail: str = ""


def process_group_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_process_tree(
    process: subprocess.Popen,
    *,
    wait_seconds: float = 3.0,
) -> TerminationResult:
    """Terminate a process tree and bound all waits."""
    if process.poll() is not None:
        return TerminationResult(process.returncode, "already-exited")

    detail = ""
    tree_ok = False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            tree_ok = completed.returncode == 0 or process.poll() is not None
            detail = f"taskkill exited with code {completed.returncode}"
        except Exception as error:
            detail = f"taskkill failed: {error}"
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            tree_ok = True
            detail = "process group kill requested"
        except ProcessLookupError:
            tree_ok = True
            detail = "process already exited"
        except Exception as error:
            detail = f"process group kill failed: {error}"

    try:
        return TerminationResult(
            process.wait(timeout=wait_seconds),
            "terminated" if tree_ok else "terminated-after-tree-error",
            detail,
        )
    except Exception as error:
        detail = f"{detail}; wait failed: {error}"

    try:
        process.kill()
    except Exception as error:
        detail = f"{detail}; force-kill failed: {error}"
    try:
        return TerminationResult(
            process.wait(timeout=wait_seconds),
            "force-killed",
            detail,
        )
    except Exception as error:
        return TerminationResult(
            process.poll(),
            "unconfirmed",
            f"{detail}; exit could not be confirmed: {error}",
        )
