import os
import subprocess

INSTALL_DIR = "/opt/ghostlink-mini"

def _run(args, cwd=INSTALL_DIR, interactive=False):
    kwargs = {
        "cwd": cwd,
        "text": True,
    }
    if not interactive:
        kwargs.update({
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
        })

    result = subprocess.run(args, **kwargs)
    if interactive:
        output = ""
    else:
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return output, result.returncode

def _sudo_args(args):
    if os.geteuid() == 0:
        return args
    return ["sudo"] + args

def update_ghostlink():
    if not os.path.isdir(INSTALL_DIR):
        return {"status": "error", "message": f"Installation directory {INSTALL_DIR} does not exist."}

    if not os.path.exists(os.path.join(INSTALL_DIR, ".git")):
        return {"status": "error", "message": f"Installation directory {INSTALL_DIR} is not a git repository."}

    if not os.path.exists(os.path.join(INSTALL_DIR, "setup.sh")):
        return {"status": "error", "message": f"Missing setup.sh in {INSTALL_DIR}."}

    out, code = _run(["git", "fetch", "origin"])
    if code != 0:
        return {"status": "error", "message": "Failed to fetch from remote.", "log": out}

    out, code = _run(["git", "pull", "origin", "main"])
    if code != 0:
        return {"status": "error", "message": "Failed to pull latest changes.", "log": out}

    out, code = _run(_sudo_args(["./setup.sh", "--update"]), interactive=True)
    if code != 0:
        return {
            "status": "error",
            "message": "Update setup failed. Run `sudo ./setup.sh --update` from /opt/ghostlink-mini for details.",
            "log": out,
        }

    out, code = _run(["ghostlink", "-diag"], cwd="/")
    if code != 0:
        return {"status": "error", "message": "Update installed, but ghostlink -diag failed.", "log": out}

    return {"status": "success", "message": "Successfully updated Ghostlink-Mini."}
