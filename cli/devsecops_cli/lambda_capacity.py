"""Deterministic Lambda capacity decisions shared by diagnostics and runners."""
from __future__ import annotations

from typing import Any

from .models import ConfigValidationError

DEFAULT_RESERVED_EXECUTIONS = 10
MIN_UNRESERVED_POOL = 100


def evaluate_capacity(limits: Any, requested: int, current_reserved: int = 0, *,
                      allow_unreserved: bool = False) -> dict[str, Any]:
    """Check reservation changes, including the function's existing allocation.

    AWS requires 100 units to remain unreserved when allocating reservations.
    Unchanged/decreased existing reservations do not consume additional units.
    -1 is the provider's shared-pool setting, allowed only by explicit lab policy.
    It removes a function reservation; the account quota still applies.
    """
    if type(requested) is not int or not (1 <= requested <= 1000 or requested == -1 and allow_unreserved):
        raise ConfigValidationError("Reserved concurrency must be an integer from 1 to 1000; shared-pool mode is available only in the dev lab.")
    if not isinstance(limits, dict):
        raise ConfigValidationError("AWS returned no Lambda account capacity limits.")
    total, unreserved = limits.get("ConcurrentExecutions"), limits.get("UnreservedConcurrentExecutions")
    if (type(total) is not int or type(unreserved) is not int or type(current_reserved) is not int
            or total <= 0 or unreserved < 0 or unreserved > total
            or current_reserved < 0 or current_reserved > total - unreserved):
        raise ConfigValidationError("AWS returned missing/inconsistent Lambda capacity values; recheck account and function concurrency before proceeding.")
    available = unreserved + current_reserved
    maximum = max(0, available - MIN_UNRESERVED_POOL)
    detail = f"Account quota={total}, unreserved={unreserved}, current function reservation={current_reserved}"
    if requested == -1:
        if available <= 0:
            raise ConfigValidationError(detail + "; no shared capacity is available. Release capacity or request a quota increase.")
        message = detail + f". Explicit dev shared-pool mode: {available} units available after releasing this function's reservation; no dedicated function cap or guarantee."
    elif requested > current_reserved and requested > maximum:
        raise ConfigValidationError(detail + f"; requested reservation={requested}, maximum allocatable={maximum}. "
                                    f"AWS requires leaving {MIN_UNRESERVED_POOL} unreserved. Request a quota increase for production; "
                                    "a separate dev lab can explicitly select `lab concurrency NAME --mode unreserved`.")
    else:
        message = detail + f"; requested reservation={requested}. Capacity check passed; AWS revalidates allocation during apply."
    return {"account_quota": total, "unreserved": unreserved, "current_reserved": current_reserved,
            "requested_reserved": requested, "mode": "unreserved" if requested == -1 else "reserved",
            "minimum_unreserved_pool": MIN_UNRESERVED_POOL, "maximum_reservation": maximum,
            "available_after_release": available, "message": message}
