import os
import time
from uuid import *
import uuid as _stdlib_uuid


def uuid7() -> _stdlib_uuid.UUID:
    """Pure-Python UUIDv7 fallback compatible with uuid_utils."""
    timestamp_ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)
    high = (timestamp_ms << 16) | 0x7000 | (
        int.from_bytes(rand_bytes[:2], "big") & 0x0FFF
    )
    low = (0x8000 << 48) | (
        int.from_bytes(rand_bytes[2:], "big") & 0x3FFFFFFFFFFFFFFF
    )
    return _stdlib_uuid.UUID(int=(high << 64) | low)