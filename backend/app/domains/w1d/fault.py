"""Fault-injection seam for contract transaction rollback tests."""

from __future__ import annotations

_fault_point: str | None = None


def set_fault_point(label: str | None) -> None:
    global _fault_point
    _fault_point = label


def install(label: str | None) -> None:
    set_fault_point(label)


def get_fault_point() -> str | None:
    return _fault_point


def clear_fault_point() -> None:
    set_fault_point(None)


def raise_if(label: str) -> None:
    if _fault_point == label:
        raise RuntimeError(f"W1D_FAULT:{label}")


def maybe_fault(label: str) -> None:
    """Canonical production fault seam (same behavior as raise_if)."""
    raise_if(label)
