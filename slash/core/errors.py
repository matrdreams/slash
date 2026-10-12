"""Errors raised by the control plane. API routes map these to HTTP status codes."""


class SlashError(Exception):
    """Base error for expected failures."""


class NotFoundError(SlashError):
    """The device, task, snapshot, or takeover does not exist."""


class ConflictError(SlashError):
    """The request fights current state (device busy, bad cancel, already exists)."""


class InvalidTransition(SlashError):
    """A task status change is not in the state machine."""


class BootTimeoutError(SlashError):
    """sys.boot_completed did not become 1 before the deadline."""


class SignatureMismatchError(SlashError):
    """APK sha256 or signer certificate does not match the expected pin."""


class PolicyViolation(SlashError):
    """An action was rejected by the safety policy."""


class BudgetExceeded(SlashError):
    """The task spent more than max_cost_cny."""


class ResidencyError(SlashError):
    """The provider is outside the configured data-residency region."""


class AdbError(SlashError):
    """An adb invocation failed."""


class LLMError(SlashError):
    """The model call failed or returned a payload that could not be parsed."""


class TokenError(SlashError):
    """A takeover token is expired, replayed, or signed for another device."""
