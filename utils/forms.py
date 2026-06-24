from fastapi import HTTPException


def safe_float(value: str, field: str = "value") -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid number for {field}: {value!r}")
