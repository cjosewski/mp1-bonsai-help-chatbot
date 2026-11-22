"""The RST role lexicon over section records (synthetic RST)."""

from __future__ import annotations

import textwrap

import pytest
from doc_remotes import source_config

from bonsai_help import docs_index as di
from bonsai_help import lexicon_rst as lr
from bonsai_help.doc_sources import Source


def records(text: str, path: str = "docs/page.rst") -> list[dict]:
    source = Source.model_validate(source_config())
    return di.split_page(
        source,
        "pin",
        "0" * 40,
        path,
        textwrap.dedent(text).encode(),
        frozenset({path}),
        di.Diagnostics(),
    )


def found(text: str, kind: str | None = None) -> list[tuple]:
    out = []
    for record in records(text):
        hits, _ = lr.extract_record(record)
        out += [hit[:3] for hit in hits if kind is None or hit[0] == kind]
    return out


def test_operator_target_on_a_title():
    text = """
    .. _bpy.ops.mesh.merge:

    Merge
    =====

    Merges vertices.
    """
    assert found(text, "blender_operator") == [("blender_operator", "mesh.merge", "Merge")]


def test_operator_target_on_a_definition_term_strips_roles():
    text = """
    Page
    ====

    .. _bpy.ops.object.paths_clear:

    :bl-icon:`x` Clear Paths :kbd:`Alt-P`
       Clears paths.
    """
    assert found(text, "blender_operator") == [
        ("blender_operator", "object.paths_clear", "Clear Paths")
    ]
    assert ("hotkey", "Alt-P", ":kbd:`Alt-P`") in found(text)


def test_indented_targets_are_found_at_their_own_indent():
    text = """
    Page
    ====

    Update Paths
       Updates the path.

       .. _bpy.ops.pose.paths_clear:
       .. _bpy.ops.object.paths_clear:

       :bl-icon:`x` (Clear Paths)
          Clears paths.

          .. _bpy.ops.pose.paths_range_update:

    .. _bpy.types.AnimVizMotionPaths.range:

    Calculation Range
       The range.
    """
    assert found(text, "blender_operator") == [
        ("blender_operator", "pose.paths_clear", "(Clear Paths)"),
        ("blender_operator", "object.paths_clear", "(Clear Paths)"),
        ("blender_operator", "pose.paths_range_update", None),
    ]
    lexicon = lr.extract(records(text))
    assert lexicon["summary"]["counts"]["operator_targets_indented"] == 3
    assert lexicon["summary"]["counts"]["bpy_types_targets"] == 1


def test_wildcard_targets_and_operator_refs():
    text = """
    .. _bpy.ops.*.select_box:

    Box Select
    ==========

    See :ref:`Box Select <bpy.ops.*.select_box>` and :ref:`bpy.ops.mesh.gone`.
    Also :ref:`bpy.types.Mesh` and :ref:`Other <other-label>`.
    """
    lexicon = lr.extract(records(text))
    assert lexicon["summary"]["operator_ids_wildcard"] == 1
    assert lexicon["summary"]["dangling_refs"] == ["mesh.gone"]
    refs = [(e["value"], e["label"]) for e in lexicon["entries"] if e["kind"] == "operator_ref"]
    assert refs == [("*.select_box", "Box Select"), ("mesh.gone", None)]


def test_reference_block_fields_are_parsed_at_their_own_indent():
    text = """
    Merge
    =====

    .. reference::

       :Mode:      Edit Mode
       :Menu:      :menuselection:`Mesh --> Merge`,
                   :menuselection:`Context Menu
                   --> Merge`
       :Panel:     Sidebar
                   :Not a field: continuation
       :Shortcut:  :kbd:`M`
       :Header:    Header text
    """
    fields = [hit[1] for hit in found(text, "reference_field")]
    assert fields == [
        "Mode: Edit Mode",
        "Panel: Sidebar :Not a field: continuation",
        "Header: Header text",
    ]
    menus = [hit[1] for hit in found(text, "menu_path")]
    assert menus == ["Mesh --> Merge", "Context Menu --> Merge"]
    summary = lr.extract(records(text))["summary"]
    assert summary["counts"]["reference_fields_covered_by_roles"] == 2
    assert summary["counts"]["reference_blocks"] == 1


@pytest.mark.parametrize(
    "role, value",
    [
        (":kbd:`Ctrl-Shift-A`", "Ctrl-Shift-A"),
        (":kbd:`Ctrl+D`", "Ctrl-D"),
        (":kbd:`R Y Y`", "R Y Y"),
        (":kbd:`Ctrl-NumpadMinus`", "Ctrl-NumpadMinus"),
        (":kbd:`Minus`", "Minus"),
        (":kbd:`Ctrl--`", "Ctrl--"),
        (":kbd:`-`", "-"),
        (":kbd:`Shift` + :kbd:`Spacebar`", "Shift-Spacebar"),
        (":kbd:`Ctrl`\n+ :kbd:`N`", "Ctrl-N"),
        (":kbd:`Shift` + :kbd:`R Y`", "Shift-R Y"),
    ],
)
def test_hotkey_forms(role, value):
    text = f"Keys\n====\n\nPress {role} now.\n"
    (hit,) = found(text, "hotkey")
    assert hit[1] == value and hit[2] == " ".join(role.split())


def test_separate_hotkeys_joined_by_words_stay_separate():
    text = "Keys\n====\n\nPress :kbd:`Ctrl` or :kbd:`Cmd`.\n"
    assert [hit[1] for hit in found(text, "hotkey")] == ["Ctrl", "Cmd"]


def test_wrapped_menuselection_and_guilabel_are_collapsed():
    text = """
    Menus
    =====

    Open :menuselection:`Properties --> Project Overview --> Project
    Info` and click :guilabel:`Create   Project`.
    """
    assert found(text, "menu_path") == [
        ("menu_path", "Properties --> Project Overview --> Project Info", None)
    ]
    assert found(text, "guilabel") == [("guilabel", "Create Project", None)]


def test_default_role_ui_paths_skip_links_literals_and_roles():
    text = """
    Paths
    =====

    Go to `File > New IFC Project` or `Scene Properties >
    Geometry`. Not `a link > here <https://example.invalid>`_, not ``code > x``
    and not :kbd:`A > B`. Not `plain text` either.
    """
    assert [hit[1] for hit in found(text, "ui_path")] == [
        "File > New IFC Project",
        "Scene Properties > Geometry",
    ]


def test_entries_aggregate_with_record_locations_and_restrict_exactly():
    text = """
    One
    ===

    Use :kbd:`M` here.

    Two
    ===

    Use :kbd:`M` again and :menuselection:`Mesh --> Merge`.
    """
    found_records = records(text)
    lexicon = lr.extract(found_records)
    ids = [r["id"] for r in found_records]
    assert lexicon["records"] == sorted(ids)
    (hotkey,) = [e for e in lexicon["entries"] if e["kind"] == "hotkey"]
    assert [lexicon["records"][i] for i in hotkey["locations"]] == sorted(ids)
    second = {found_records[1]["id"]}
    assert lr.restrict(lexicon, second) == lr.resolved(lr.extract(found_records[1:]))


def test_a_field_marker_term_gives_its_name_as_the_label():
    text = """
    Page
    ====

    .. _bpy.ops.ui.eyedropper_color:

    :Material:
       Picks a material color.
    """
    assert found(text, "blender_operator") == [
        ("blender_operator", "ui.eyedropper_color", "Material")
    ]


def test_cross_reference_terms_give_their_title_never_a_target_or_path():
    text = """
    Page
    ====

    .. _bpy.ops.graph.select_box:

    :ref:`Box Select <bpy.ops.*.select_box>` :kbd:`B`
       Selects in a box.

    .. _bpy.ops.object.armature_add:

    :doc:`Armature </animation/armatures/index>`
       Adds an armature.

    .. _bpy.ops.sculpt.project_line_gesture:

    :doc:`/sculpt_paint/sculpting/tools/line_project`
       Projects along a line.
    """
    assert found(text, "blender_operator") == [
        ("blender_operator", "graph.select_box", "Box Select"),
        ("blender_operator", "object.armature_add", "Armature"),
        ("blender_operator", "sculpt.project_line_gesture", None),
    ]
    (record,) = [r for r in records(text) if r["title"] == "Page"]
    assert lr.extract_record(record)[1]["operator_terms_bare_xref"] == 1


def test_markup_shown_as_an_example_is_not_extracted():
    text = """
    Page
    ====

    Write ``:menuselection:`Add --> Mesh` `` or ``:kbd:`LMB` `` inline.

    .. code-block:: rst

       .. _bpy.ops.curve.subdivide:

       :kbd:`Shift-S` and :menuselection:`Curve --> Snap`

    A literal paragraph::

       .. reference::

          :Mode: Edit Mode

    1. In a list item::

          :guilabel:`Shown`

    Back in prose, :kbd:`Ctrl-Z` and :menuselection:`Edit --> Undo` are real.
    """
    assert found(text) == [
        ("menu_path", "Edit --> Undo", None),
        ("hotkey", "Ctrl-Z", ":kbd:`Ctrl-Z`"),
    ]


def test_literal_lines_cover_paragraph_and_directive_bodies():
    lines = ["Text::", "", "   body", "", "Next", ".. code-block:: python", "   x = 1", "After"]
    assert lr.literal_lines(lines) == {2, 6}
