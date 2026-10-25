from __future__ import annotations

import asyncio
import fnmatch
import pathspec
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config import Settings


class FileAccessControl:
    def __init__(self):
        self.reconfigure()
        self.write_locks: defaultdict[Path,asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_write_lock(self,path:Path) -> asyncio.Lock:
        return self.write_locks[path.resolve()]


    def reconfigure(self, settings: Settings | None = None):
        """Configures file access permissions.

        - ['*'] grants full access (unrestricted system-wide).
        - [] denies all access.
        - Standard glob patterns (e.g. '**/*', 'src/**/*.py') 
        are scoped to CWD unless absolute.
        """

        if settings and settings.chat.get('custom_cwd'):
            base_dir = Path(settings.chat['custom_cwd']).resolve()
        else:
            base_dir = Path.cwd().resolve()

        self.base_dir = base_dir
        self.cwd      = base_dir.as_posix()
        
        read_patterns  = []
        write_patterns = []
        patterns = []
        self.all_read  = False
        self.all_write = False

        if settings is not None:
            # reconfigure path
            patterns = settings.permissions.get('patterns',[])

        # parse patterns
        for obj in patterns:
            perm,pat = obj.split()
            if 'r' in perm and self.all_read is False: 
                if pat == '*': 
                    self.all_read = True
                else:
                    read_patterns.append(pat)

            if 'w' in perm and self.all_write is False: 
                if pat == '*': 
                    self.all_write = True
                else:
                    write_patterns.append(pat)

        # Check patterns
        self.read_patterns  = self._strip_rel(read_patterns)
        self.write_patterns = self._strip_rel(write_patterns)
                
    def _strip_rel(self, lst: list[str]) -> list[str]:
        res = []
        for l in lst:
            cleaned = l[2:] if l.startswith('./') or l.startswith('.\\') else l

            if cleaned in ("", ".", "/", "\\"):
                raise ValueError(
                f'Invalid scope pattern "{l}": Bare "." or "./" matches only the directory node, '
                'not its files. Did you mean "./*" (immediate files) or "./**" (recursive)?'
                )
            elif cleaned.endswith(('/','\\')):
                cleaned = cleaned.rstrip('/\\') + '/*'

            res.append(cleaned)
        return res

    def _is_glob_match(self, target:Path, pattern:str) -> bool:
        try:
            rel_path = target.relative_to(self.base_dir)
            rel_str  = rel_path.as_posix()

            if pattern in ("**/*","**"):
                return True

            # folder recursive wildcard
            if pattern.endswith("/**"):
                prefix = pattern[:-3]
                return rel_path == prefix or rel_str.startswith(f"{prefix}/")
            
            return pathspec.PathSpec.from_lines("gitwildmatch",
                [pattern]).match_file(rel_str)
        except ValueError:
            is_abs_pattern = pattern.startswith("/") or (
                len(pattern) > 1 and pattern[1] == ":"
            )
            if is_abs_pattern:
                return fnmatch.fnmatch(target.as_posix(),pattern)
            return False
    
    def _validate(
        self,
        path: str,
        patterns: list[str],
        full_access: bool,
        ac_type: Literal["read", "write"],
    ):
        target = Path(path)
        if not target.is_absolute():
            target = Path(self.cwd) / target
        target = target.resolve()
        
        if full_access:
            return target

        if len(patterns) == 0:
            raise PermissionError(f"{ac_type.capitalize()} access denied: No {ac_type} prefixes configured")

        if any(self._is_glob_match(target,pattern) for pattern in patterns):
            return target

        raise PermissionError(f"{ac_type.capitalize()} access denied for path: {path}")

    def _build_perm(self,full_access:bool,patterns:list[str]):
        if full_access:
            return "ALL (*)"
        elif patterns:
            return ", ".join(patterns)
        else:
            return "[NONE]"
        
    def validate_read(self, path: str):
        return self._validate(path, self.read_patterns,self.all_read,'read')
    
    def validate_write(self, path: str):
        return self._validate(path, self.write_patterns,self.all_write,'write')

    def build_environment_context(self) -> str:
        read_perm  = self._build_perm(self.all_read,self.read_patterns)
        write_perm = self._build_perm(self.all_write,self.write_patterns)

        return f"""
ENVIRONMENT METADATA:
- Current Working Directory (CWD): {self.cwd}
- Permitted Read Scopes:  {read_perm}
- Permitted Write Scopes: {write_perm}
""".strip()

# initialize fa_control
file_access_control = FileAccessControl()