# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Set

from backend.schemas import ControlsState, FocusMode


_controls_state = ControlsState()


def _copy_state(state: ControlsState) -> ControlsState:
    return ControlsState.model_validate(state.model_dump(by_alias=True))


def get_controls() -> ControlsState:
    """Return the current control state used by the policy engine."""
    return _copy_state(_controls_state)


def set_controls(state: ControlsState) -> ControlsState:
    """Replace the active control state and return the stored copy."""
    global _controls_state
    _controls_state = _copy_state(state)
    return get_controls()


def update_focus_mode(focus_mode: FocusMode) -> ControlsState:
    """Update only the focus mode on the stored state and return a copy."""
    global _controls_state
    updated = _copy_state(_controls_state).model_copy(update={"focus_mode": focus_mode})
    _controls_state = updated
    return get_controls()


def get_blocked_app_ids() -> Set[str]:
    """Return the set of canonical app identifiers that are currently blocked."""
    return set(_controls_state.blocked_app_ids or [])


def reset() -> None:
    """Reset the in-memory policy store (used by tests)."""
    global _controls_state
    _controls_state = ControlsState()
