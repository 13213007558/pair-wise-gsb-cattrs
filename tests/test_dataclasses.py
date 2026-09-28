import dataclasses
from dataclasses import InitVar
from typing import Generic, List, TypeVar

import attr
import pytest

from cattrs import BaseConverter, Converter
from cattrs.errors import ClassValidationError

from ._compat import is_py310_plus


@dataclasses.dataclass
class Foo:
    bar: str


@attr.define
class Container:
    foos: List[Foo]


def test_dataclasses_in_attrs(converter: BaseConverter):
    struct = Container([Foo("bar")])

    unstruct = {"foos": [{"bar": "bar"}]}

    assert converter.unstructure(struct) == unstruct
    assert converter.structure(unstruct, Container) == struct


def test_dataclasses_in_container(converter: BaseConverter):
    struct = [Foo("bar"), Foo("bat")]

    unstruct = [{"bar": "bar"}, {"bar": "bat"}]

    assert converter.unstructure(struct) == unstruct
    assert converter.structure(unstruct, List[Foo]) == struct


def test_dataclasses(converter: BaseConverter):
    struct = Foo("bar")

    unstruct = {"bar": "bar"}

    assert converter.unstructure(struct) == unstruct
    assert converter.structure(unstruct, Foo) == struct


@pytest.mark.skipif(not is_py310_plus, reason="kwonly fields are Python 3.10+")
def test_kw_only_propagation(converter: BaseConverter):
    """KW-only args work.

    Reproducer from https://github.com/python-attrs/cattrs/issues/637.
    """

    @dataclasses.dataclass
    class PartialKeywords:
        a1: str = "Default"
        a2: str = dataclasses.field(kw_only=True)

    assert converter.structure({"a2": "Value"}, PartialKeywords) == PartialKeywords(
        a1="Default", a2="Value"
    )


def test_initvar_structuring(converter: BaseConverter):
    """InitVars are converted using their annotations and passed to __init__."""

    @dataclasses.dataclass
    class WithInitVar:
        a: int
        ctx: InitVar[int]
        derived: int = dataclasses.field(init=False, default=0)

        def __post_init__(self, ctx: int):
            self.derived = self.a + ctx

    res = converter.structure({"a": "1", "ctx": "2"}, WithInitVar)

    assert res.a == 1
    # "2" was converted to an int before __post_init__ ran.
    assert res.derived == 3


def test_initvar_post_init_called_once(converter: BaseConverter):
    """__post_init__ runs exactly once, after all constructor args are converted."""
    calls = []

    @dataclasses.dataclass
    class WithInitVar:
        a: int
        ctx: InitVar[int] = 0

        def __post_init__(self, ctx: int):
            calls.append(ctx)

    converter.structure({"a": 1, "ctx": "5"}, WithInitVar)
    assert calls == [5]

    # The InitVar default is used when the key is missing.
    converter.structure({"a": 1}, WithInitVar)
    assert calls == [5, 0]


def test_initvar_not_unstructured(converter: BaseConverter):
    """InitVars only exist on the input side.

    The class-level default of an InitVar must not be mistaken for an
    instance field when unstructuring.
    """

    @dataclasses.dataclass
    class WithInitVar:
        a: int
        ctx: InitVar[int] = 5

        def __post_init__(self, ctx: int):
            self.total = self.a + ctx

    inst = WithInitVar(1)

    # The class-level default exists, but is not an instance field.
    assert WithInitVar.ctx == 5
    assert converter.unstructure(inst) == {"a": 1}


def test_initvar_inheritance(converter: BaseConverter):
    """InitVars work across inheritance, alongside init=False derived fields."""
    calls = []

    @dataclasses.dataclass
    class Base:
        a: int
        ctx: InitVar[int] = 10
        derived: int = dataclasses.field(init=False, default=0)

        def __post_init__(self, ctx: int):
            calls.append(("base", ctx))
            self.derived = self.a + ctx

    @dataclasses.dataclass
    class Child(Base):
        extra: InitVar[str] = "x"
        b: str = "b"

        def __post_init__(self, ctx: int, extra: str):
            calls.append(("child", extra))
            super().__post_init__(ctx)

    res = converter.structure({"a": 1, "ctx": "2", "extra": "e", "b": "c"}, Child)

    assert res.derived == 3
    # Each __post_init__ ran exactly once, with converted arguments.
    assert calls == [("child", "e"), ("base", 2)]

    # The unstructured output contains only real fields, no InitVars.
    unstructured = converter.unstructure(res)
    assert "ctx" not in unstructured
    assert "extra" not in unstructured
    assert unstructured["a"] == 1
    assert unstructured["b"] == "c"

    # The output can be structured again, using the InitVar defaults.
    # (BaseConverter also unstructures init=False fields, which its own
    # structuring cannot handle; that is unrelated to InitVars.)
    if isinstance(converter, Converter):
        assert converter.structure(unstructured, Child) == Child(a=1, b="c")


@pytest.mark.skipif(not is_py310_plus, reason="kw_only is Python 3.10+")
def test_initvar_kw_only(converter: BaseConverter):
    """Keyword-only InitVars are passed to __init__ as keyword arguments."""

    @dataclasses.dataclass
    class WithKwOnlyInitVar:
        a: int
        ctx: InitVar[int] = dataclasses.field(kw_only=True)

        def __post_init__(self, ctx: int):
            self.total = self.a + ctx

    res = converter.structure({"a": 1, "ctx": 2}, WithKwOnlyInitVar)

    assert res.total == 3


def test_initvar_generic(converter: BaseConverter):
    """InitVars support generic type variable substitution."""
    T = TypeVar("T")

    @dataclasses.dataclass
    class GenericWithInitVar(Generic[T]):
        x: InitVar[T]
        y: T = None

        def __post_init__(self, x: T):
            self.y = x

    res = converter.structure({"x": "1"}, GenericWithInitVar[int])

    assert res.y == 1
    assert isinstance(res.y, int)


def test_initvar_error_notes(converter: BaseConverter):
    """Errors raised while structuring InitVars keep the InitVar name."""

    @dataclasses.dataclass
    class WithInitVar:
        a: int
        ctx: InitVar[int]

        def __post_init__(self, ctx: int):
            pass

    if converter.detailed_validation and isinstance(converter, Converter):
        with pytest.raises(ClassValidationError) as exc_info:
            converter.structure({"a": 1, "ctx": "bad"}, WithInitVar)

        exc = exc_info.value
        assert exc.cl is WithInitVar
        names = [
            note.name
            for subexc in exc.exceptions
            for note in getattr(subexc, "__notes__", [])
        ]
        assert "ctx" in names
    else:
        with pytest.raises((ClassValidationError, ValueError)):
            converter.structure({"a": 1, "ctx": "bad"}, WithInitVar)
