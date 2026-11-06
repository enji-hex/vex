import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# +----------+
# Template for Arbitrary Shell Executor (ASE) linux only, bwarp as engine
# +----------+

@dataclass
class AseResponse:
    exit_code: int
    stdout: str
    stderr: str
    def __repr__(self) -> str:
        return f"[{self.exit_code}] \n=stdout=\n{self.stdout}\n=stderr=\n{self.stderr}"

# Agent sees sandbox in ASE same as as standard ENV data tree,
# to fully align with provided project map
def execute_isolated(cmd: str, sandbox_dir: str = ".", timeout: int = 10) -> AseResponse:
    sandbox = Path(sandbox_dir).resolve()
    if not sandbox.exists():
        return AseResponse(126, "", f"PathError: '{sandbox}' does not exist.")

    bwrap = shutil.which("bwrap")
    if not bwrap:
        return AseResponse(127, "", "EnvironmentError: 'bwrap' (bubblewrap) is required.")

    s_str = str(sandbox)
    cmd_args = [
        bwrap,
        # "--share-net",
        "--unshare-all",            # Isolate all namespaces (pid, net, ipc, user, mount)
        "--tmpfs", "/",             # Ephemeral empty root filesystem
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
    ]
    if Path("/lib64").exists():
        cmd_args.extend(["--ro-bind", "/lib64", "/lib64"])

    cmd_args.extend([
        "--dir", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
    ])

    curr = Path("/")
    # create sandbox path
    for part in Path(s_str).parts[1:-1]:
        curr = curr / part
        cmd_args.extend(["--dir",str(curr)])
    cmd_args.extend([
        "--bind", s_str,s_str,
        "sh","-c",cmd
    ])

    try:
        proc = subprocess.run(cmd_args, shell=False,capture_output=True, text=True, timeout=timeout)
        return AseResponse(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired:
        return AseResponse(124, "", f"TimeoutError: Exceeded {timeout}s threshold")
    except Exception as e:
        return AseResponse(1, "", f"ExecutionError: {str(e)}")

if __name__ == '__main__':
    import sys
    r = execute_isolated(sys.argv[1],sandbox_dir='./sandbox')
    print(r)