"""Session smoothness (0-100): execution quality, scored separately from the outcome.

A run can submit successfully and still be rough (retry storms, loops, drift), which
predicts the next failure. Silna scores sessions this way and routes low scores to
human review. The penalties below are explicit so they can be argued with and tuned.
"""
from __future__ import annotations

PENALTIES = {
    "retry": 4,            # each tool retry after a transient error
    "guard": 2,            # each time a guard had to clear an overlay
    "drift": 8,            # page did not change the way the action expected
    "loop": 25,            # same action on the same page state, repeatedly
    "invalid_action": 10,  # model asked for a tool outside the allow-list or bad JSON
    "credential_swap": 6,  # had to change credentials mid-run
    "extra_step": 1,       # each step beyond the playbook's expected count
    "timeout": 30,
    "verification_mismatch": 40,
    "validator_block": 12,  # turn validator stopped an action (phantom element, unsourced value, off-domain)
    "validator_warn": 3,    # stated reason and action disagree
}


def smoothness(counts: dict, steps: int, expected_steps: int) -> float:
    s = 100.0
    for k, w in PENALTIES.items():
        if k == "extra_step":
            s -= w * max(0, steps - expected_steps)
        else:
            s -= w * counts.get(k, 0)
    return max(0.0, round(s, 1))
