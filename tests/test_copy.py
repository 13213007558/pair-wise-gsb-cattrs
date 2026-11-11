from collections import OrderedDict
from copy import deepcopy
from typing import Callable

from attr import define
from hypothesis import given
from hypothesis.strategies import just, one_of
from pytest import raises

from cattrs import BaseConverter, Converter, UnstructureStrategy
from cattrs.errors import ClassValidationError, ForbiddenExtraKeysError

from . import unstructure_strats


@define
class Simple:
    a: int


@define
class Node:
    val: int
    child: "Node | None" = None


def _raises_forbidden_extra_keys(fn) -> bool:
    """Run `fn`, returning whether it raised a `ForbiddenExtraKeysError`.

    The error may be wrapped in (possibly nested) `ClassValidationError`
    exception groups when detailed validation is on.
    """
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001
        queue = [exc]
        while queue:
            exc = queue.pop()
            if isinstance(exc, ForbiddenExtraKeysError):
                return True
            if isinstance(exc, BaseExceptionGroup):
                queue.extend(exc.exceptions)
        return False
    return False


@given(strat=unstructure_strats, detailed_validation=..., prefer_attrib=...)
def test_deepcopy(
    converter_cls: type[BaseConverter],
    strat: UnstructureStrategy,
    prefer_attrib: bool,
    detailed_validation: bool,
):
    c = converter_cls(
        unstruct_strat=strat,
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
    )

    copy = deepcopy(c)

    assert c is not copy

    assert c.unstructure(Simple(1)) == copy.unstructure(Simple(1))
    assert c.detailed_validation == copy.detailed_validation
    assert c._prefer_attrib_converters == copy._prefer_attrib_converters


@given(
    strat=unstructure_strats,
    detailed_validation=...,
    prefer_attrib=...,
    dict_factory=one_of(just(dict), just(OrderedDict)),
)
def test_copy(
    converter_cls: type[BaseConverter],
    strat: UnstructureStrategy,
    prefer_attrib: bool,
    detailed_validation: bool,
    dict_factory: Callable,
):
    c = converter_cls(
        unstruct_strat=strat,
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
        dict_factory=dict_factory,
    )

    copy = c.copy()

    assert c is not copy

    assert c.unstructure(Simple(1)) == copy.unstructure(Simple(1))
    assert c.detailed_validation == copy.detailed_validation
    assert c._prefer_attrib_converters == copy._prefer_attrib_converters
    assert c._dict_factory == copy._dict_factory


@given(
    strat=unstructure_strats,
    detailed_validation=...,
    prefer_attrib=...,
    dict_factory=one_of(just(dict), just(OrderedDict)),
    omit_if_default=...,
)
def test_copy_converter(
    strat: UnstructureStrategy,
    prefer_attrib: bool,
    detailed_validation: bool,
    dict_factory: Callable,
    omit_if_default: bool,
):
    """cattrs.Converter can be copied, and keeps its attributes."""
    c = Converter(
        unstruct_strat=strat,
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
        dict_factory=dict_factory,
        omit_if_default=omit_if_default,
    )

    copy = c.copy()

    assert c is not copy

    assert c.unstructure(Simple(1)) == copy.unstructure(Simple(1))
    assert c.detailed_validation == copy.detailed_validation
    assert c._prefer_attrib_converters == copy._prefer_attrib_converters
    assert c._dict_factory == copy._dict_factory
    assert c.omit_if_default == copy.omit_if_default

    another_copy = c.copy(omit_if_default=not omit_if_default)
    assert c.omit_if_default != another_copy.omit_if_default


@given(
    strat=unstructure_strats,
    detailed_validation=...,
    prefer_attrib=...,
    dict_factory=one_of(just(dict), just(OrderedDict)),
)
def test_copy_hooks(
    converter_cls: type[BaseConverter],
    strat: UnstructureStrategy,
    prefer_attrib: bool,
    detailed_validation: bool,
    dict_factory: Callable,
):
    """Un/structure hooks are copied over."""
    c = converter_cls(
        unstruct_strat=strat,
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
        dict_factory=dict_factory,
    )

    c.register_unstructure_hook(Simple, lambda s: s.a)
    c.register_structure_hook(Simple, lambda v, _: Simple(v))

    assert c.unstructure(Simple(1)) == 1
    assert c.structure(1, Simple) == Simple(1)

    copy = c.copy()

    assert c is not copy

    assert c.unstructure(Simple(1)) == copy.unstructure(Simple(1))
    assert copy.structure(copy.unstructure(Simple(1)), Simple) == Simple(1)
    assert c.detailed_validation == copy.detailed_validation
    assert c._prefer_attrib_converters == copy._prefer_attrib_converters
    assert c._dict_factory == copy._dict_factory


@given(
    strat=unstructure_strats,
    detailed_validation=...,
    prefer_attrib=...,
    dict_factory=one_of(just(dict), just(OrderedDict)),
)
def test_copy_func_hooks(
    converter_cls: type[BaseConverter],
    strat: UnstructureStrategy,
    prefer_attrib: bool,
    detailed_validation: bool,
    dict_factory: Callable,
):
    """Un/structure function hooks are copied over."""
    c = converter_cls(
        unstruct_strat=strat,
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
        dict_factory=dict_factory,
    )

    c.register_unstructure_hook_func(lambda t: t is Simple, lambda s: s.a)
    c.register_structure_hook_func(lambda t: t is Simple, lambda v, _: Simple(v))

    assert c.unstructure(Simple(1)) == 1
    assert c.structure(1, Simple) == Simple(1)

    copy = c.copy()

    assert c is not copy

    assert copy.unstructure(Simple(1)) == 1
    assert copy.structure(copy.unstructure(Simple(1)), Simple) == Simple(1)
    assert c.detailed_validation == copy.detailed_validation
    assert c._prefer_attrib_converters == copy._prefer_attrib_converters
    assert c._dict_factory == copy._dict_factory


@given(prefer_attrib=..., dict_factory=one_of(just(dict), just(OrderedDict)))
def test_detailed_validation(prefer_attrib: bool, dict_factory: Callable):
    """Copies with different detailed validation work correctly."""
    c = Converter(
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=True,
        dict_factory=dict_factory,
    )

    # So the converter gets generated.
    c.structure({"a": 1}, Simple)

    copy = c.copy(detailed_validation=False)

    assert c is not copy
    assert copy.detailed_validation is False

    with raises(ClassValidationError):
        c.structure({}, Simple)

    with raises(KeyError):
        copy.structure({}, Simple)


@given(
    prefer_attrib=...,
    dict_factory=one_of(just(dict), just(OrderedDict)),
    detailed_validation=...,
)
def test_col_overrides(
    prefer_attrib: bool, dict_factory: Callable, detailed_validation: bool
):
    """Copies with different sequence overrides work correctly."""
    c = Converter(
        prefer_attrib_converters=prefer_attrib,
        detailed_validation=detailed_validation,
        dict_factory=dict_factory,
        unstruct_collection_overrides={list: tuple},
    )

    # So the converter gets generated.
    assert c.unstructure([1, 2, 3]) == (1, 2, 3)
    # We also stick a manual hook on there so it gets copied too.
    c.register_unstructure_hook(Simple, lambda s: s.a)

    copy = c.copy(unstruct_collection_overrides={})

    assert c is not copy

    assert c.unstructure([1, 2, 3]) == (1, 2, 3)
    assert copy.unstructure([1, 2, 3]) == [1, 2, 3]

    assert c.unstructure(Simple(1)) == 1
    assert copy.unstructure(Simple(1)) == 1


def test_copy_forbid_extra_keys_cold_cache():
    """A strict copy enforces `forbid_extra_keys`, the original is unaffected."""
    c = Converter()
    strict = c.copy(forbid_extra_keys=True)

    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"a": 1, "x": 1}, Simple)
    )
    assert c.structure({"a": 1, "x": 1}, Simple) == Simple(1)


def test_copy_forbid_extra_keys_hot_cache():
    """Hooks generated by the original before copying are not reused by a strict copy."""
    c = Converter()
    # Warm the original's caches with the same type.
    assert c.structure({"a": 1}, Simple) == Simple(1)

    strict = c.copy(forbid_extra_keys=True)

    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"a": 1, "x": 1}, Simple)
    )
    # The original is not polluted by the strict copy's configuration.
    assert c.structure({"a": 1, "x": 1}, Simple) == Simple(1)


def test_copy_forbid_extra_keys_nested_hot_cache():
    """Nested hooks generated by the original before copying are not reused."""

    @define
    class Outer:
        inner: Simple
        b: int

    c = Converter()
    assert c.structure({"inner": {"a": 1}, "b": 2}, Outer) == Outer(Simple(1), 2)

    strict = c.copy(forbid_extra_keys=True)

    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"inner": {"a": 1, "x": 1}, "b": 2}, Outer)
    )
    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"inner": {"a": 1}, "b": 2, "x": 1}, Outer)
    )
    assert c.structure({"inner": {"a": 1, "x": 1}, "b": 2}, Outer) == Outer(
        Simple(1), 2
    )


def test_copy_forbid_extra_keys_recursive_hot_cache():
    """Recursive hooks generated by the original before copying are not reused."""
    c = Converter()
    assert c.structure({"val": 1, "child": None}, Node) == Node(1)

    strict = c.copy(forbid_extra_keys=True)

    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"val": 1, "x": 1, "child": None}, Node)
    )
    assert _raises_forbidden_extra_keys(
        lambda: strict.structure(
            {"val": 1, "child": {"val": 2, "x": 1, "child": None}}, Node
        )
    )
    assert c.structure({"val": 1, "x": 1, "child": None}, Node) == Node(1)


def test_copy_forbid_extra_keys_containers_hot_cache():
    """Collection hooks generated by the original before copying are not reused."""
    c = Converter()
    assert c.structure([{"a": 1}], list[Simple]) == [Simple(1)]
    assert c.structure({"k": {"a": 1}}, dict[str, Simple]) == {"k": Simple(1)}

    strict = c.copy(forbid_extra_keys=True)

    assert _raises_forbidden_extra_keys(
        lambda: strict.structure([{"a": 1, "x": 1}], list[Simple])
    )
    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"k": {"a": 1, "x": 1}}, dict[str, Simple])
    )
    assert c.structure([{"a": 1, "x": 1}], list[Simple]) == [Simple(1)]


def test_copy_reverse_pollution():
    """Hooks generated by a strict copy do not leak into the original."""
    c = Converter()
    strict = c.copy(forbid_extra_keys=True)

    # Warm the strict copy's caches first.
    assert strict.structure({"a": 1}, Simple) == Simple(1)

    assert c.structure({"a": 1, "x": 1}, Simple) == Simple(1)


def test_copy_one_sided_hook_updates():
    """Hooks registered on one converter after copying do not affect the other."""
    c = Converter()
    strict = c.copy(forbid_extra_keys=True)

    c.register_structure_hook(Simple, lambda v, _: Simple(v["a"] + 100))

    assert c.structure({"a": 1}, Simple) == Simple(101)
    # The strict copy falls back to its own generated hook.
    assert strict.structure({"a": 1}, Simple) == Simple(1)
    assert _raises_forbidden_extra_keys(
        lambda: strict.structure({"a": 1, "x": 1}, Simple)
    )

    strict.register_structure_hook(Simple, lambda v, _: Simple(v["a"] + 200))

    assert strict.structure({"a": 1}, Simple) == Simple(201)
    assert c.structure({"a": 1}, Simple) == Simple(101)


def test_copy_hook_factories():
    """Hook factories are shared, but extended factories receive the copy."""

    @define
    class A:
        a: int

    @define
    class B:
        b: int

    c = Converter()
    c.register_structure_hook_factory(
        lambda t: t is A, lambda t: lambda v, _: A(v["a"])
    )

    seen = []

    def extended_factory(t, conv):
        seen.append(conv)
        return lambda v, _: B(v["b"])

    c.register_structure_hook_factory(lambda t: t is B, extended_factory)

    strict = c.copy(forbid_extra_keys=True)

    # Plain factories are shared as-is.
    assert strict.structure({"a": 1}, A) == A(1)
    # Extended factories are given the converter they dispatch on.
    assert strict.structure({"b": 1}, B) == B(1)
    assert seen[-1] is strict
    assert c.structure({"b": 1}, B) == B(1)
    assert seen[-1] is c


def test_copy_fallback_factories(converter_cls: type[BaseConverter]):
    """Custom fallback factories are kept when copying."""
    c = converter_cls(
        unstructure_fallback_factory=lambda t: lambda o: "unstruct-fallback",
        structure_fallback_factory=lambda t: lambda v, _: "struct-fallback",
    )

    copy = c.copy()

    assert copy.structure(1, complex) == "struct-fallback"
    assert copy.unstructure(1j) == "unstruct-fallback"


def test_copy_union_hooks(converter_cls: type[BaseConverter]):
    """Custom union hooks are kept when copying, and stay independent."""

    @define
    class A:
        a: int

    @define
    class B:
        b: int

    c = converter_cls()
    c.register_structure_hook(A | B, lambda v, _: A(-1) if "a" in v else B(-1))

    copy = c.copy()

    assert copy.structure({"a": 5}, A | B) == A(-1)
    assert copy.structure({"b": 5}, A | B) == B(-1)

    # Later registrations on either side don't leak into the other.
    copy.register_structure_hook(A | B, lambda v, _: B(99))
    assert copy.structure({"a": 5}, A | B) == B(99)
    assert c.structure({"a": 5}, A | B) == A(-1)
