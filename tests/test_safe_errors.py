"""Tests for the safe error rendering entry points (`cattrs.v.transform_error_safe`)."""

from typing import ClassVar, Dict, List, Optional, Union

from attrs import define
from pytest import fixture, raises

from cattrs import Converter, transform_error, transform_error_safe
from cattrs.errors import ClassValidationError
from cattrs.gen import make_dict_structure_fn
from cattrs.v import safe_format_exception

SECRET = "SECRET-TOKEN-testsecret"


class ReprRecorder:
    """An input object whose `__repr__` leaks a secret and records calls."""

    repr_calls: ClassVar[int] = 0

    def __repr__(self) -> str:
        ReprRecorder.repr_calls += 1
        return f"ReprRecorder({SECRET})"


class Token:
    """A target type structured by a custom hook."""


class TokenError(Exception):
    """An error raised by the custom hook, unknown to cattrs."""


@define
class Inner:
    token: Token
    count: int


@define
class BranchA:
    a: int


@define
class BranchB:
    b: str


@define
class Outer:
    inner: Inner
    nums: List[int]
    u: Union[BranchA, BranchB]
    o: Optional[int] = None


def quiet_token_hook(v, _) -> Token:
    """A hook which fails without touching the value."""
    raise TokenError("bad token")


def leaky_token_hook(v, _) -> Token:
    """A hook which leaks the raw value into the exception message."""
    raise TokenError(f"bad token: {v!r}")


def leaf_errors(exc: BaseException) -> List[BaseException]:
    """Collect the non-group leaves of an exception group."""
    if hasattr(exc, "exceptions"):
        return [leaf for sub in exc.exceptions for leaf in leaf_errors(sub)]
    return [exc]


@fixture
def c() -> Converter:
    conv = Converter(detailed_validation=True)
    conv.register_structure_hook(Token, quiet_token_hook)
    return conv


def test_safe_errors_do_not_call_repr(c: Converter) -> None:
    """Rendering safe errors must not invoke `__repr__` on input objects."""
    ReprRecorder.repr_calls = 0
    payload = {
        "inner": {"token": ReprRecorder(), "count": 1},
        "nums": [1],
        "u": {"b": "ok"},
    }

    with raises(ClassValidationError) as exc_info:
        c.structure(payload, Outer)

    assert transform_error_safe(exc_info.value) == ["unknown error @ $.inner.token"]
    assert ReprRecorder.repr_calls == 0

    # The default transformer doesn't call `__repr__` on the value either.
    assert transform_error(exc_info.value) == ["unknown error (bad token) @ $.inner.token"]
    assert ReprRecorder.repr_calls == 0


def test_safe_errors_do_not_leak_secrets(c: Converter) -> None:
    """Secrets embedded in hook exceptions must not reach safe messages."""
    c.register_structure_hook(Token, leaky_token_hook)
    ReprRecorder.repr_calls = 0
    payload = {
        "inner": {"token": ReprRecorder(), "count": 1},
        "nums": [1],
        "u": {"b": "ok"},
    }

    with raises(ClassValidationError) as exc_info:
        c.structure(payload, Outer)

    calls_after_structuring = ReprRecorder.repr_calls

    # The default transformer leaks the secret from the exception message.
    detailed = transform_error(exc_info.value)
    assert any(SECRET in msg for msg in detailed)

    # The safe transformer does not, and doesn't add any `__repr__` calls.
    safe = transform_error_safe(exc_info.value)
    assert safe == ["unknown error @ $.inner.token"]
    assert all(SECRET not in msg for msg in safe)
    assert ReprRecorder.repr_calls == calls_after_structuring

    # The original exception is intact for server-side debugging.
    leaves = leaf_errors(exc_info.value)
    assert any(isinstance(e, TokenError) and SECRET in str(e) for e in leaves)


def test_safe_paths_nested_lists_and_unions(c: Converter) -> None:
    """Nested classes, list indices, mapping keys and union branches localize."""
    payload = {
        "inner": {"token": ReprRecorder(), "count": "not-an-int"},
        "nums": [1, "oops", 3],
        "u": {"a": "bad"},
        "o": "xx",
    }

    with raises(ClassValidationError) as exc_info:
        c.structure(payload, Outer)

    safe = transform_error_safe(exc_info.value)
    assert "unknown error @ $.inner.token" in safe
    assert "invalid value for type, expected int @ $.inner.count" in safe
    assert "invalid value for type, expected int @ $.nums[1]" in safe
    # Union branch errors are localized inside the branch, at the union's path.
    assert "invalid value for type, expected int @ $.u.a" in safe
    # Optional fields report their annotation name, not the raw value.
    assert "invalid value for type, expected Optional @ $.o" in safe
    assert all(SECRET not in msg for msg in safe)


def test_safe_mapping_key_paths() -> None:
    """Mapping keys still locate errors in safe mode."""

    @define
    class WithMapping:
        m: Dict[str, int]

    conv = Converter(detailed_validation=True)

    with raises(ClassValidationError) as exc_info:
        conv.structure({"m": {"a": "str"}}, WithMapping)

    assert transform_error_safe(exc_info.value) == [
        "invalid value for type, expected int @ $.m['a']"
    ]


def test_safe_extra_keys_do_not_leak_key_names() -> None:
    """Extra key names are user input; only the count is exposed."""

    @define
    class C:
        a: int

    conv = Converter(detailed_validation=True)
    conv.register_structure_hook(
        C, make_dict_structure_fn(C, conv, _cattrs_forbid_extra_keys=True)
    )

    with raises(ClassValidationError) as exc_info:
        conv.structure({"a": 1, SECRET: 2}, C)

    assert transform_error(exc_info.value) == [f"extra fields found ({SECRET}) @ $"]
    assert transform_error_safe(exc_info.value) == ["extra fields found (1) @ $"]


def test_safe_non_detailed_validation() -> None:
    """Non-detailed mode errors also get conservative messages."""
    conv = Converter(detailed_validation=False)
    conv.register_structure_hook(Token, leaky_token_hook)
    ReprRecorder.repr_calls = 0

    with raises(TokenError) as exc_info:
        conv.structure(
            {
                "inner": {"token": ReprRecorder(), "count": 1},
                "nums": [1],
                "u": {"b": "ok"},
            },
            Outer,
        )

    # The raw exception leaks the secret...
    assert SECRET in str(exc_info.value)
    # ...but the safe rendering does not.
    assert transform_error_safe(exc_info.value) == ["unknown error @ $"]

    with raises(KeyError) as exc_info:
        conv.structure({}, Outer)

    assert transform_error_safe(exc_info.value) == ["required field missing @ $"]


def test_safe_format_exception_directly() -> None:
    """`safe_format_exception` covers the common built-in error kinds."""
    assert safe_format_exception(KeyError("a"), None) == "required field missing"
    assert (
        safe_format_exception(ValueError("x"), int)
        == "invalid value for type, expected int"
    )
    assert safe_format_exception(ValueError("x"), None) == "invalid value"
    assert safe_format_exception(TypeError("x"), int) == (
        "invalid value for type, expected int"
    )
    assert safe_format_exception(TypeError("x"), None) == "invalid type"
    assert safe_format_exception(
        TypeError("SECRET object is not iterable"), None
    ) == "invalid value for type, expected an iterable"
    assert (
        safe_format_exception(
            AttributeError("'int' object has no attribute 'items'"), None
        )
        == "expected a mapping"
    )
    # Unknown exceptions are constant, no matter their contents.
    assert safe_format_exception(TokenError(f"leak: {SECRET}"), None) == "unknown error"
    assert safe_format_exception(IndexError(SECRET), List[int]) == "unknown error"


def test_custom_safe_error_mapping(c: Converter) -> None:
    """Callers can layer their own vetted mappings over the safe default."""

    def api_format(exc: BaseException, type) -> str:
        if isinstance(exc, TokenError):
            return "invalid token"
        return safe_format_exception(exc, type)

    payload = {
        "inner": {"token": ReprRecorder(), "count": "not-an-int"},
        "nums": [1],
        "u": {"b": "ok"},
    }

    with raises(ClassValidationError) as exc_info:
        c.structure(payload, Outer)

    assert transform_error_safe(exc_info.value, format_exception=api_format) == [
        "invalid token @ $.inner.token",
        "invalid value for type, expected int @ $.inner.count",
    ]
