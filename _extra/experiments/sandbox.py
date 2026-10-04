import os
import subprocess
from pathlib import Path
from typing import Optional
import anyio

class Sandbox:
    def __init__(self,sandbox_id:str) -> None:
        self.id = sandbox_id
        self.path = Path("/tmp/vex-sandboxes") / sandbox_id
        self.path.mkdir(parents=True,exist_ok=True)
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        self.process = subprocess.Popen([
            "unshare",
            "--mount",
            # "--net",
            "--pid",
            "--fork",
            "--mount-proc",
            "sleep",
            "infinity",
        ])
        (self.path / "pid").write_text(str(self.process.pid))

    @property
    def pid(self):
        if self.process:
            return self.process.pid 
        return None

    async def exec(self,command,args):
        process =  await anyio.open_process([
            "nsenter",
            "--target", str(self.pid),
            "--mount",
            # "--net",
            "--pid",
            command,
            *args,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
        )
        return process

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process.wait()