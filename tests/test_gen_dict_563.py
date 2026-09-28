"""gen tests under PEP 563 (stringified annotations)."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field

from attrs import define

from cattrs import Converter
from cattrs.gen import make_dict_structure_fn, make_dict_unstructure_fn


# These need to be at the top level for `attr.resolve_types` to work.
@define
class Inner:
    a: int


@define
class Outer:
    inner: Inner


@define
class InnerB:
    a: int


@define
class OuterB:
    inner: InnerB


@dataclass
class InnerDataclass:
    a: int


@dataclass
class OuterDataclass:
    inner: InnerDataclass


@dataclass
class DataclassWithInitVar:
    a: int
    ctx: InitVar[int] = 5
    derived: int = field(init=False, default=0)

    def __post_init__(self, ctx: int):
        self.derived = self.a + ctx


def test_roundtrip():
    converter = Converter()

    fn = make_dict_unstructure_fn(Outer, converter)

    inst = Outer(Inner(1))

    converter.register_unstructure_hook(Outer, fn)

    res_actual = converter.unstructure(inst)

    assert {"inner": {"a": 1}} == res_actual

    converter.register_structure_hook(OuterB, make_dict_structure_fn(OuterB, converter))

    assert converter.structure({"inner": {"a": 1}}, OuterB) == OuterB(InnerB(1))


def test_roundtrip_dc():
    converter = Converter()

    fn = make_dict_unstructure_fn(OuterDataclass, converter)
    converter.register_unstructure_hook(OuterDataclass, fn)

    inst = OuterDataclass(InnerDataclass(1))

    res_actual = converter.unstructure(inst)

    assert {"inner": {"a": 1}} == res_actual

    converter.register_structure_hook(
        OuterDataclass, make_dict_structure_fn(OuterDataclass, converter)
    )

    assert converter.structure({"inner": {"a": 1}}, OuterDataclass) == OuterDataclass(
        InnerDataclass(1)
    )


def test_initvar_dc():
    """Stringified InitVar annotations are resolved and unwrapped."""
    converter = Converter()

    converter.register_structure_hook(
        DataclassWithInitVar, make_dict_structure_fn(DataclassWithInitVar, converter)
    )

    inst = converter.structure({"a": "1", "ctx": "2"}, DataclassWithInitVar)

    assert inst == DataclassWithInitVar(1, 2)
    assert inst.derived == 3

    converter.register_unstructure_hook(
        DataclassWithInitVar, make_dict_unstructure_fn(DataclassWithInitVar, converter)
    )

    assert converter.unstructure(inst) == {"a": 1}
