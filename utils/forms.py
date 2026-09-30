from fastapi import HTTPException


def safe_float(value: str, field: str = "value") -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid number for {field}: {value!r}")


def percent_value(value: float, field: str = "value") -> float:
    """A percentage must be 0-100; anything else would over-deduct or overpay."""
    if not 0 <= value <= 100:
        raise HTTPException(status_code=422, detail=f"{field} must be between 0 and 100")
    return value
