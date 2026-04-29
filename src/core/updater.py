import os
import subprocess
from .network import run_cmd, run_cmd_no_check

def update_ghostlink():
    # We assume we are running inside the cloned git repository directory
    # since we are executing the global `ghostlink` command which is a wrapper/symlink to this script.
    # Wait, the requirements state: "Pull/update latest project version from configured repository."
    
    # Check if we are in a git repository
    # Actually, we should change to the installation directory first.
    # Setup.sh will clone or move this to /opt/ghostlink-mini
    install_dir = "/opt/ghostlink-mini"
    
    if not os.path.exists(os.path.join(install_dir, ".git")):
        return {"status": "error", "message": f"Installation directory {install_dir} is not a git repository."}
        
    try:
        # Fetch latest
        out, code = run_cmd_no_check(f"cd {install_dir} && git fetch origin")
        if code != 0:
            return {"status": "error", "message": "Failed to fetch from remote.", "log": out}
            
        # Pull
        out, code = run_cmd_no_check(f"cd {install_dir} && git pull origin main")
        if code != 0:
            return {"status": "error", "message": "Failed to pull latest changes.", "log": out}
            
        # Run setup script update mode
        out, code = run_cmd_no_check(f"cd {install_dir} && sudo ./setup.sh --update")
        if code != 0:
            return {"status": "error", "message": "Update setup failed.", "log": out}
            
        return {"status": "success", "message": "Successfully updated Ghostlink-Mini."}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
