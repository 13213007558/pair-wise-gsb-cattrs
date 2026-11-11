"""Regression tests for branch selection when structuring unions.

A union payload being structured into the wrong member is a silent
corruption, so every sample in this file declares its expected branch
(or error) explicitly instead of deriving it from the implementation.

Both selection strategies are covered, always end-to-end through
``Converter.structure`` (never the disambiguator helper directly), so
custom hooks, validation and error aggregation are exercised too:

* automatic disambiguation (unique keys / literal discriminators)
* explicit tags via `configure_tagged_union`
"""

from typing import List, Literal, Union

import pytest
from attrs import define

from cattrs import Converter
from cattrs.errors import (
    ClassValidationError,
    ForbiddenExtraKeysError,
    IterableValidationError,
)
from cattrs.strategies import configure_tagged_union


@define
class ReadFile:
    op: Literal["read"]
    path: str


@define
class WriteFile:
    op: Literal["write"]
    path: str
    mode: str = "0644"


FileOp = Union[ReadFile, WriteFile]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"op": "read", "path": "/a"}, ReadFile("read", "/a")),
        (
            {"op": "write", "path": "/b", "mode": "0777"},
            WriteFile("write", "/b", "0777"),
        ),
        # `mode` is missing, but the WriteFile default fills it in.
        ({"op": "write", "path": "/b"}, WriteFile("write", "/b")),
        # The discriminator wins over the foreign `mode` key; the
        # conflicting key is silently dropped without forbid_extra_keys.
        ({"op": "read", "path": "/a", "mode": "0777"}, ReadFile("read", "/a")),
    ],
    ids=["read", "write", "write-default-mode", "conflicting-mode-dropped"],
)
def test_auto_literal_branch_selection(converter, payload, expected):
    """Literal discriminators pick the branch written next to each sample."""
    assert converter.structure(payload, FileOp) == expected


def test_auto_missing_discriminator(converter):
    """A missing discriminator key raises `KeyError` for that key."""
    with pytest.raises(KeyError, match="op"):
        converter.structure({"path": "/a"}, FileOp)


def test_auto_unknown_discriminator(converter):
    """An unknown discriminator value raises `KeyError` for that value."""
    with pytest.raises(KeyError, match="chmod"):
        converter.structure({"op": "chmod", "path": "/a"}, FileOp)


def test_auto_conflict_error_names_selected_branch():
    """When the payload conflicts with the selected branch, the
    aggregated error identifies the branch that was actually chosen."""
    c = Converter(detailed_validation=True)

    # `op` selects ReadFile, but the required `path` is missing.
    with pytest.raises(ClassValidationError) as exc_info:
        c.structure({"op": "read", "mode": "0777"}, FileOp)
    assert exc_info.value.cl is ReadFile

    # Same for the other branch.
    with pytest.raises(ClassValidationError) as exc_info:
        c.structure({"op": "write", "mode": "0777"}, FileOp)
    assert exc_info.value.cl is WriteFile


def test_auto_conflict_error_non_detailed():
    """Without detailed validation the conflict surfaces as the raw
    `KeyError` for the selected branch's missing key."""
    c = Converter(detailed_validation=False)

    with pytest.raises(KeyError, match="path"):
        c.structure({"op": "read"}, FileOp)


@define
class FlagSet:
    flag: Literal[1]


@define
class FlagClear:
    flag: Literal[0]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"flag": 1}, FlagSet(1)),
        ({"flag": 0}, FlagClear(0)),
        # Counterexamples: `True == 1` and `1.0 == 1`, so these
        # near-literal values select the `Literal[1]` branch.
        ({"flag": True}, FlagSet(1)),
        ({"flag": False}, FlagClear(0)),
        ({"flag": 1.0}, FlagSet(1)),
    ],
    ids=["int-1", "int-0", "bool-true", "bool-false", "float-1.0"],
)
def test_auto_similar_literal_values(converter, payload, expected):
    """Values equal-but-not-identical to a literal still select its branch."""
    assert converter.structure(payload, Union[FlagSet, FlagClear]) == expected


@define
class StrCode:
    code: Literal["1"]


@define
class IntCode:
    code: Literal[1]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"code": "1"}, StrCode("1")),
        ({"code": 1}, IntCode(1)),
    ],
    ids=["str-1", "int-1"],
)
def test_auto_lookalike_literal_types(converter, payload, expected):
    """`"1"` and `1` look alike but select different branches."""
    assert converter.structure(payload, Union[StrCode, IntCode]) == expected


@define
class NamedRequest:
    request_id: str


@define
class CatchallRequest:
    note: str = "unspecified"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"request_id": "r-1"}, NamedRequest("r-1")),
        # Counterexample: `request_id` is missing, but every field of
        # CatchallRequest has a default, so the payload silently
        # structures into the fallback branch.
        ({}, CatchallRequest()),
        # A typo'd key is masked the same way.
        ({"requestid": "r-1"}, CatchallRequest()),
    ],
    ids=["named", "missing-key-masked", "typo-key-masked"],
)
def test_auto_default_fields_mask_missing_input(converter, payload, expected):
    """A branch whose fields all have defaults becomes the fallback and
    masks input missing the other branch's required keys."""
    assert converter.structure(payload, Union[NamedRequest, CatchallRequest]) == expected


def test_auto_forbid_extra_keys_applies_to_selected_branch():
    """`forbid_extra_keys` reports extra keys against the branch that
    was actually selected, not the union."""
    c = Converter(forbid_extra_keys=True, detailed_validation=True)

    # The discriminator key itself is consumed, not reported as extra.
    assert c.structure({"op": "read", "path": "/a"}, FileOp) == ReadFile("read", "/a")

    with pytest.raises(ClassValidationError) as exc_info:
        c.structure({"op": "read", "path": "/a", "junk": 1}, FileOp)
    exc = exc_info.value
    assert exc.cl is ReadFile
    (inner,) = exc.exceptions
    assert isinstance(inner, ForbiddenExtraKeysError)
    assert inner.cl is ReadFile
    assert inner.extra_fields == {"junk"}

    # The other branch is named when it is the one selected.
    with pytest.raises(ClassValidationError) as exc_info:
        c.structure({"op": "write", "path": "/a", "junk": 1}, FileOp)
    assert exc_info.value.cl is WriteFile


def test_auto_forbid_extra_keys_non_detailed():
    """Without detailed validation the `ForbiddenExtraKeysError` of the
    selected branch is raised directly."""
    c = Converter(forbid_extra_keys=True, detailed_validation=False)

    with pytest.raises(ForbiddenExtraKeysError) as exc_info:
        c.structure({"op": "read", "path": "/a", "junk": 1}, FileOp)
    assert exc_info.value.cl is ReadFile
    assert exc_info.value.extra_fields == {"junk"}


def test_custom_hook_applies_after_auto_branch_selection(converter):
    """A custom hook registered for a member runs once that branch is
    selected; the suite must not stop at the disambiguator helper."""
    seen = []

    def hook(val, _):
        seen.append(val)
        return ReadFile("read", val["path"].upper())

    converter.register_structure_hook(ReadFile, hook)

    res = converter.structure({"op": "read", "path": "/tmp/x"}, FileOp)
    assert res == ReadFile("read", "/TMP/X")
    assert seen == [{"op": "read", "path": "/tmp/x"}]

    # The other branch is unaffected.
    assert converter.structure({"op": "write", "path": "/y"}, FileOp) == WriteFile(
        "write", "/y"
    )


def test_aggregated_error_identifies_selected_branch(genconverter):
    """Structuring a sequence of union payloads aggregates errors that
    still identify which branch each bad element was routed to."""
    payload = [{"op": "read", "path": "/a"}, {"op": "write"}]

    if genconverter.detailed_validation:
        with pytest.raises(IterableValidationError) as exc_info:
            genconverter.structure(payload, List[FileOp])
        (inner,) = exc_info.value.exceptions
        # The second element selected WriteFile, then failed on `path`.
        assert isinstance(inner, ClassValidationError)
        assert inner.cl is WriteFile
    else:
        with pytest.raises(KeyError, match="path"):
            genconverter.structure(payload, List[FileOp])


@define
class AllowAction:
    actor: str


@define
class DenyAction:
    actor: str
    reason: str


Action = Union[AllowAction, DenyAction]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"_type": "AllowAction", "actor": "root"}, AllowAction("root")),
        (
            {"_type": "DenyAction", "actor": "root", "reason": "policy"},
            DenyAction("root", "policy"),
        ),
        # The tag wins over the foreign `reason` key; without
        # forbid_extra_keys the conflicting key is silently dropped.
        (
            {"_type": "AllowAction", "actor": "root", "reason": "policy"},
            AllowAction("root"),
        ),
    ],
    ids=["allow", "deny", "conflicting-reason-dropped"],
)
def test_tagged_branch_selection(converter, payload, expected):
    """Explicit tags pick the branch written next to each sample."""
    configure_tagged_union(Action, converter)

    assert converter.structure(payload, Action) == expected


def test_tagged_missing_tag(converter):
    """A missing tag raises `KeyError` for the tag name when no default
    member is configured."""
    configure_tagged_union(Action, converter)

    with pytest.raises(KeyError, match="_type"):
        converter.structure({"actor": "root"}, Action)


def test_tagged_unknown_tag(converter):
    """An unknown tag raises `KeyError` for the tag value when no
    default member is configured."""
    configure_tagged_union(Action, converter)

    with pytest.raises(KeyError, match="AuditAction"):
        converter.structure({"_type": "AuditAction", "actor": "root"}, Action)


@pytest.mark.parametrize(
    "payload",
    [
        {"actor": "root"},  # missing tag
        {"_type": "AuditAction", "actor": "root"},  # unknown tag
    ],
    ids=["missing-tag", "unknown-tag"],
)
def test_tagged_default_member_masks_bad_tags(converter, payload):
    """Counterexample: with a default member configured, missing and
    unknown tags silently structure into the default branch."""
    configure_tagged_union(Action, converter, default=AllowAction)

    assert converter.structure(payload, Action) == AllowAction("root")


def test_tagged_forbid_extra_keys_applies_to_selected_branch():
    """With `forbid_extra_keys`, the tag is consumed and leftover keys
    are reported against the branch the tag selected."""
    c = Converter(forbid_extra_keys=True, detailed_validation=True)
    configure_tagged_union(Action, c)

    # The tag key itself is not an extra key.
    assert c.structure({"_type": "AllowAction", "actor": "root"}, Action) == AllowAction(
        "root"
    )

    with pytest.raises(ClassValidationError) as exc_info:
        c.structure(
            {"_type": "DenyAction", "actor": "root", "reason": "r", "junk": 1}, Action
        )
    exc = exc_info.value
    assert exc.cl is DenyAction
    (inner,) = exc.exceptions
    assert isinstance(inner, ForbiddenExtraKeysError)
    assert inner.cl is DenyAction
    assert inner.extra_fields == {"junk"}


def test_tagged_conflict_error_names_selected_branch():
    """A payload conflicting with the tagged branch produces an error
    identifying that branch."""
    c = Converter(detailed_validation=True)
    configure_tagged_union(Action, c)

    # The tag selects DenyAction, but `reason` is missing.
    with pytest.raises(ClassValidationError) as exc_info:
        c.structure({"_type": "DenyAction", "actor": "root"}, Action)
    assert exc_info.value.cl is DenyAction


def test_custom_hook_applies_after_tagged_branch_selection(converter):
    """A custom hook registered for a member runs once its tag selects
    it; the suite must not stop at the tag dispatch."""
    converter.register_structure_hook(
        AllowAction, lambda val, _: AllowAction(val["actor"].strip())
    )
    configure_tagged_union(Action, converter)

    assert converter.structure(
        {"_type": "AllowAction", "actor": "  root  "}, Action
    ) == AllowAction("root")

    # The other branch is unaffected.
    assert converter.structure(
        {"_type": "DenyAction", "actor": "root", "reason": "r"}, Action
    ) == DenyAction("root", "r")
