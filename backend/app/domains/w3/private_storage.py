"""Digest-addressed private workbook storage outside PostgreSQL and public URLs."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredPrivateContent:
    content_digest: str
    byte_size: int
    storage_locator: str
    created: bool


class W3PrivateStorage:
    def __init__(self, data_root: Path) -> None:
        self._root = data_root.expanduser().resolve() / "w3-private" / "sha256"

    @staticmethod
    def locator_for_digest(content_digest: str) -> str:
        if len(content_digest) != 64 or any(ch not in "0123456789abcdef" for ch in content_digest):
            raise ValueError("content_digest must be lowercase SHA-256")
        return f"w3-private:{content_digest}"

    def _path_for_digest(self, content_digest: str) -> Path:
        self.locator_for_digest(content_digest)
        return self._root / content_digest[:2] / f"{content_digest}.xlsx"

    def store(self, content: bytes) -> StoredPrivateContent:
        content_digest = sha256(content).hexdigest()
        destination = self._path_for_digest(content_digest)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            destination.parent.chmod(0o700)
        except OSError:
            pass

        if destination.exists():
            existing = destination.read_bytes()
            if sha256(existing).hexdigest() != content_digest or existing != content:
                raise OSError("private content digest collision")
            return StoredPrivateContent(
                content_digest=content_digest,
                byte_size=len(content),
                storage_locator=self.locator_for_digest(content_digest),
                created=False,
            )

        temporary = destination.with_name(f".{content_digest}.{secrets.token_hex(8)}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, destination)
            destination.chmod(0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

        return StoredPrivateContent(
            content_digest=content_digest,
            byte_size=len(content),
            storage_locator=self.locator_for_digest(content_digest),
            created=True,
        )

    def verify(self, content_digest: str) -> bool:
        path = self._path_for_digest(content_digest)
        if not path.is_file():
            return False
        return sha256(path.read_bytes()).hexdigest() == content_digest
