from dataclasses import dataclass


@dataclass(
    slots=True
)
class AIResult:

    ok: bool

    text: str | None = None

    provider: str = ""

    model: str = ""

    status_code: int | None = None

    error_type: str | None = None

    error: str | None = None