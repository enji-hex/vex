from pathlib import Path
from typing import List, Literal

class FileAccessControl:
    def __init__(self, read_prefixes: List[str], write_prefixes: List[str]):
        self.reconfigure(read_prefixes,write_prefixes)

    def reconfigure(self, read_prefixes: List[str], write_prefixes: List[str]):
        self.all_read = "*" in read_prefixes
        self.all_write = "*" in write_prefixes

        self.read_prefixes = [Path(p).resolve() for p in read_prefixes if p != "*"]
        self.write_prefixes = [Path(p).resolve() for p in write_prefixes if p != "*"]
        
    def _validate(
        self,
        path: str,
        prefixes: List[Path],
        full_access: bool,
        ac_type: Literal["read", "write"],
    ):
        target = Path(path).resolve()
        if full_access:
            return target

        if len(prefixes) == 0:
            raise PermissionError(f"{ac_type.capitalize()} access denied: No {ac_type} prefixes configured")

        if any(target.is_relative_to(prefix) for prefix in prefixes):
            return target

        raise PermissionError(f"{ac_type.capitalize()} access denied for path: {path}")

    def _build_perm(self,full_access:bool,prefixes:List[Path]):
        if full_access:
            return "ALL (*)"
        elif prefixes:
            return ", ".join(p.as_posix() for p in prefixes)
        else:
            return "[NONE]"
        
    def validate_read(self, path: str):
        return self._validate(path, self.read_prefixes,self.all_read,'read')
    
    def validate_write(self, path: str):
        return self._validate(path, self.write_prefixes,self.all_write,'write')

    def build_environment_context(self) -> str:
        cwd = Path.cwd().resolve().as_posix()

        read_perm = self._build_perm(self.all_read,self.read_prefixes)
        write_perm = self._build_perm(self.all_write,self.write_prefixes)

        return f"""
ENVIRONMENT METADATA:
- Current Working Directory (CWD): {cwd}
- Permitted Read Scopes:  {read_perm}
- Permitted Write Scopes: {write_perm}
""".strip()


# initialize fa_control
file_access_control = FileAccessControl(["."],[])