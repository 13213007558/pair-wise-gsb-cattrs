"""Cattrs validation."""

from typing import Callable, Union

from .errors import (
    ClassValidationError,
    ForbiddenExtraKeysError,
    IterableValidationError,
)

__all__ = [
    "format_exception",
    "safe_format_exception",
    "transform_error",
    "transform_error_safe",
]


def _type_name(type: Union[type, None]) -> Union[str, None]:
    """Return a stable, safe name for a type, or None if there isn't one."""
    return getattr(type, "__name__", None)


def format_exception(exc: BaseException, type: Union[type, None]) -> str:
    """The default exception formatter, handling the most common exceptions.

    The following exceptions are handled specially:

    * `KeyErrors` (`required field missing`)
    * `ValueErrors` (`invalid value for type, expected <type>` or just `invalid value`)
    * `TypeErrors` (`invalid value for type, expected <type>` and a couple special
      cases for iterables)
    * `cattrs.ForbiddenExtraKeysError`
    * some `AttributeErrors` (special cased for structing mappings)
    """
    if isinstance(exc, KeyError):
        res = "required field missing"
    elif isinstance(exc, ValueError):
        if type is not None:
            tn = type.__name__ if hasattr(type, "__name__") else repr(type)
            res = f"invalid value for type, expected {tn}"
        else:
            res = "invalid value"
    elif isinstance(exc, TypeError):
        if type is None:
            if exc.args[0].endswith("object is not iterable"):
                res = "invalid value for type, expected an iterable"
            else:
                res = f"invalid type ({exc})"
        else:
            tn = type.__name__ if hasattr(type, "__name__") else repr(type)
            res = f"invalid value for type, expected {tn}"
    elif isinstance(exc, ForbiddenExtraKeysError):
        res = f"extra fields found ({', '.join(sorted(exc.extra_fields))})"
    elif isinstance(exc, AttributeError) and exc.args[0].endswith(
        "object has no attribute 'items'"
    ):
        # This was supposed to be a mapping (and have .items()) but it something else.
        res = "expected a mapping"
    else:
        res = f"unknown error ({exc})"

    return res


def safe_format_exception(exc: BaseException, type: Union[type, None]) -> str:
    """A conservative exception formatter, safe for returning to API clients.

    Unlike :func:`format_exception`, this formatter:

    * never interpolates exception messages or arguments into the output
    * never calls ``repr``/``str`` on input values, types or exceptions, so
      custom ``__repr__`` implementations of input objects are never invoked
    * renders unknown exceptions (for example, exceptions raised by custom
      hooks) as the constant string ``unknown error``

    The trade-off is less detail; the original exception is untouched and
    remains available server-side for logging and debugging.

    .. versionadded:: 25.2.0
    """
    if isinstance(exc, KeyError):
        res = "required field missing"
    elif isinstance(exc, ValueError):
        tn = _type_name(type)
        res = f"invalid value for type, expected {tn}" if tn else "invalid value"
    elif isinstance(exc, TypeError):
        if type is None:
            if (
                exc.args
                and isinstance(exc.args[0], str)
                and exc.args[0].endswith("object is not iterable")
            ):
                res = "invalid value for type, expected an iterable"
            else:
                res = "invalid type"
        else:
            tn = _type_name(type)
            res = f"invalid value for type, expected {tn}" if tn else "invalid value"
    elif isinstance(exc, ForbiddenExtraKeysError):
        # Only the count is exposed; the extra keys themselves are user input.
        res = f"extra fields found ({len(exc.extra_fields)})"
    elif (
        isinstance(exc, AttributeError)
        and exc.args
        and isinstance(exc.args[0], str)
        and exc.args[0].endswith("object has no attribute 'items'")
    ):
        # This was supposed to be a mapping (and have .items()) but is something else.
        res = "expected a mapping"
    else:
        res = "unknown error"

    return res


def transform_error(
    exc: Union[ClassValidationError, IterableValidationError, BaseException],
    path: str = "$",
    format_exception: Callable[
        [BaseException, Union[type, None]], str
    ] = format_exception,
) -> list[str]:
    """Transform an exception into a list of error messages.

    To get detailed error messages, the exception should be produced by a converter
    with `detailed_validation` set.

    By default, the error messages are in the form of `{description} @ {path}`.

    While traversing the exception and subexceptions, the path is formed:

    * by appending `.{field_name}` for fields in classes
    * by appending `[{int}]` for indices in iterables, like lists
    * by appending `[{str}]` for keys in mappings, like dictionaries

    :param exc: The exception to transform into error messages.
    :param path: The root path to use.
    :param format_exception: A callable to use to transform `Exceptions` into
        string descriptions of errors.

    .. versionadded:: 23.1.0
    """
    errors = []
    if isinstance(exc, IterableValidationError):
        with_notes, without = exc.group_exceptions()
        for exc, note in with_notes:
            p = f"{path}[{note.index!r}]"
            if isinstance(exc, (ClassValidationError, IterableValidationError)):
                errors.extend(transform_error(exc, p, format_exception))
            else:
                errors.append(f"{format_exception(exc, note.type)} @ {p}")
        for exc in without:
            errors.append(f"{format_exception(exc, None)} @ {path}")
    elif isinstance(exc, ClassValidationError):
        with_notes, without = exc.group_exceptions()
        for exc, note in with_notes:
            p = f"{path}.{note.name}"
            if isinstance(exc, (ClassValidationError, IterableValidationError)):
                errors.extend(transform_error(exc, p, format_exception))
            else:
                errors.append(f"{format_exception(exc, note.type)} @ {p}")
        for exc in without:
            errors.append(f"{format_exception(exc, None)} @ {path}")
    else:
        errors.append(f"{format_exception(exc, None)} @ {path}")
    return errors


def transform_error_safe(
    exc: Union[ClassValidationError, IterableValidationError, BaseException],
    path: str = "$",
    format_exception: Callable[
        [BaseException, Union[type, None]], str
    ] = safe_format_exception,
) -> list[str]:
    """Transform an exception into a list of error messages safe for clients.

    Paths are formed exactly as in :func:`transform_error` (nested class
    fields, sequence indices, mapping keys and union branches are all
    preserved), but individual errors are described by
    :func:`safe_format_exception`, so no raw input values, exception texts or
    custom ``__repr__`` output end up in the messages.

    The exception is only read, never modified, so it can still be logged
    server-side with full detail.

    Callers can layer their own vetted error mappings on top by passing a
    `format_exception` callable which falls back to
    :func:`safe_format_exception`.

    .. versionadded:: 25.2.0
    """
    return transform_error(exc, path, format_exception)
