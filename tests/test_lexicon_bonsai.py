"""The Bonsai AST lexicon extractor, on synthetic add-on modules (no Bonsai source is committed)."""

from __future__ import annotations

import json
import textwrap

import pytest

from bonsai_help.doc_snapshot import CheckFailed
from bonsai_help.doc_sources import privacy_matches
from bonsai_help.lexicon_bonsai import extract

HEADER = "# Synthetic header. Contact: maintainer@example.invalid\n"
TEMPLATE = textwrap.dedent(
    """
    class Entry:
        @property
        def enable_op(self):
            return f"bim.enable_editing_{self.name}"
    """
)


def module(source: str) -> bytes:
    return (HEADER + textwrap.dedent(source)).encode()


def lexicon(files: dict[str, str], template: bool = True) -> dict:
    data = {path: module(text) for path, text in files.items()}
    if template:
        data["tool/parametric.py"] = TEMPLATE.encode()
    return extract(data)


def line_of(path: str, needle: str) -> int:
    """1-based line of the first occurrence of needle in a synthetic module."""
    text = module(FILES[path]).decode()
    return text[: text.index(needle)].count("\n") + 1


def entry(result: dict, kind: str, identifier: str) -> dict:
    (found,) = [e for e in result["entries"] if e["kind"] == kind and e["id"] == identifier]
    return found


OPERATORS = """
import bpy
from bpy.types import Operator
import bonsai.tool as tool

class AddWall(bpy.types.Operator):
    bl_idname = "bim.add_wall"
    bl_label = "Add Wall"

class AddSlab(Operator):
    bl_idname = "bim.add_slab"
    bl_label = "Add Slab"

class EditWall(bpy.types.Operator, tool.Ifc.Operator):
    bl_idname: str = "bim.edit_wall"
    bl_label = "Edit Wall"

class BaseFilter(bpy.types.Operator):
    bl_label = "Filter"

class ActivateFilter(BaseFilter):
    bl_idname = "bim.activate_filter"

class Dynamic(bpy.types.Operator):
    bl_idname = tool.Blender.name()
    bl_label = "Dynamic"

def fallback():
    class OpenUri(bpy.types.Operator):
        bl_idname = "bim.open_uri"
        bl_label = "Open URI"
    return OpenUri

class OpenUri(bpy.types.Operator):
    bl_idname = "bim.open_uri"
    bl_label = "Open URI"

class Unused(bpy.types.Operator):
    bl_idname = "bim.unused"
    bl_label = "Add Wall"
"""

UI = """
import bpy

class BIM_PT_walls(bpy.types.Panel):
    bl_label = "Walls"
    bl_idname = "BIM_PT_walls"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_parent_id = "BIM_PT_tab_geometry"
    bim_tab_name = "GEOMETRY"

    def draw(self, context):
        self.layout.operator("bim.edit_wall", text="Save Wall")
        self.layout.operator("bim.add_wall", text="Add Wall")
        self.layout.operator("bim.add_wall", text=label_for(context))
        self.layout.operator("bim.add_slab")
        self.layout.operator("bim.add_slab", text="")
        self.layout.operator("mesh.primitive_cube_add", text="Cube")

class BIM_PT_unnamed(bpy.types.Panel):
    bl_label = "Unnamed"

class BIM_MT_menu(bpy.types.Menu):
    bl_idname = "BIM_MT_menu"
    bl_label = "Menu"

class WallTool(bpy.types.WorkSpaceTool):
    bl_idname = "bim.wall_tool"
    bl_label = "Wall"

class BIM_UL_rows(bpy.types.UIList):
    pass

class Helper:
    pass

def use():
    bpy.ops.bim.add_wall()
    bpy.ops.bim.removed_operator()
    return ["bim.wall_tool", "bim.ghost", f"bim.add_{kind}"]
"""

INIT = """
from . import operator, ui
classes = (operator.AddWall, operator.AddSlab, operator.EditWall, operator.ActivateFilter,
           operator.OpenUri, ui.BIM_PT_walls, ui.BIM_MT_menu)
classes += (EnableEditingRoof,)
"""

LIFECYCLE = """
import bonsai.tool as tool
EnableEditingRoof, FinishEditingRoof, CancelEditingRoof = tool.Parametric.build_edit_lifecycle(
    "roof", object, labels=(("Enable Editing Roof", ""), ("Finish Editing Roof", ""), ("Cancel Editing Roof", "")),
)
A, B, C = tool.Parametric.build_edit_lifecycle(name_of(), object, labels=LABELS)
"""

FILES = {
    "bim/module/model/operator.py": OPERATORS,
    "bim/module/model/ui.py": UI,
    "bim/module/model/__init__.py": INIT,
    "bim/module/model/roof.py": LIFECYCLE,
}


@pytest.fixture(scope="module")
def result() -> dict:
    return lexicon(FILES)


def test_operator_base_forms_and_annotated_assignment(result):
    for identifier, label in (
        ("bim.add_wall", "Add Wall"),
        ("bim.add_slab", "Add Slab"),
        ("bim.edit_wall", "Edit Wall"),
    ):
        found = entry(result, "operator", identifier)
        assert found["label"] == label and found["file"] == "bim/module/model/operator.py"


def test_kind_and_label_resolve_through_a_local_base(result):
    found = entry(result, "operator", "bim.activate_filter")
    assert found["label"] == "Filter" and found["label_inherited"] is True
    assert not [e for e in result["entries"] if e["class"] == "BaseFilter"]
    assert result["summary"]["abstract_classes_without_idname"] == 1


def test_nested_class_and_duplicate_ids_keep_both_locations(result):
    found = [e for e in result["entries"] if e["id"] == "bim.open_uri"]
    assert len(found) == 2
    assert result["summary"]["duplicate_ids"] == ["operator bim.open_uri"]


def test_non_constant_id_is_unresolved_not_guessed(result):
    assert not [e for e in result["entries"] if e["class"] == "Dynamic"]
    (item,) = [u for u in result["unresolved"] if u["attr"] == "bl_idname"]
    assert item == {
        "file": "bim/module/model/operator.py",
        "line": line_of("bim/module/model/operator.py", "bl_idname = tool.Blender"),
        "class": "Dynamic",
        "attr": "bl_idname",
        "expr": "tool.Blender.name()",
    }


def test_panels_menus_and_tools(result):
    panel = entry(result, "panel", "BIM_PT_walls")
    assert panel["parent"] == "BIM_PT_tab_geometry" and panel["bim_tab_name"] == "GEOMETRY"
    assert (panel["space"], panel["region"], panel["context"]) == ("PROPERTIES", "WINDOW", "scene")
    unnamed = entry(result, "panel", "BIM_PT_unnamed")
    assert unnamed["id_origin"] == "class_name" and unnamed["registered"] is False
    assert entry(result, "menu", "BIM_MT_menu")["label"] == "Menu"
    assert entry(result, "tool", "bim.wall_tool")["label"] == "Wall"
    assert result["summary"]["counted_only"] == {"UIList": 1}
    assert result["summary"]["classes_without_kind"] == 2  # Entry (template) and Helper


def test_lifecycle_ids_are_derived_and_a_non_literal_call_is_unresolved(result):
    labels = {
        e["id"]: (e["label"], e["registered"], e["template"])
        for e in result["entries"]
        if e["id_origin"] == "derived:build_edit_lifecycle"
    }
    assert labels == {
        "bim.enable_editing_roof": ("Enable Editing Roof", True, "tool/parametric.py:5"),
        "bim.finish_editing_roof": ("Finish Editing Roof", False, "tool/parametric.py:5"),
        "bim.cancel_editing_roof": ("Cancel Editing Roof", False, "tool/parametric.py:5"),
    }
    assert [u["attr"] for u in result["unresolved"]].count("build_edit_lifecycle") == 1
    assert result["summary"]["bim_operator_ids_derived"] == 3


def test_lifecycle_without_its_template_fails():
    with pytest.raises(CheckFailed, match="no id template"):
        lexicon({"bim/module/model/roof.py": LIFECYCLE}, template=False)


def test_registration_comes_from_classes_tuples(result):
    assert entry(result, "operator", "bim.add_wall")["registered"] is True
    assert entry(result, "operator", "bim.unused")["registered"] is False
    line = line_of("bim/module/model/operator.py", "class Unused")
    assert (
        f"bim.unused bim/module/model/operator.py:{line}"
        in result["summary"]["operator_classes_not_registered"]
    )


def test_button_texts_are_kept_beside_labels(result):
    assert result["ui_texts"] == [
        {
            "id": "bim.add_wall",
            "text": "Add Wall",
            "differs_from_label": False,
            "file": "bim/module/model/ui.py",
            "line": line_of("bim/module/model/ui.py", 'text="Add Wall"'),
        },
        {
            "id": "bim.edit_wall",
            "text": "Save Wall",
            "differs_from_label": True,
            "file": "bim/module/model/ui.py",
            "line": line_of("bim/module/model/ui.py", 'text="Save Wall"'),
        },
    ]
    assert result["summary"]["buttons"] == {
        "calls": 5,
        "constant_text": 2,
        "dynamic_text": 1,
        "empty_text": 1,
        "label_text": 1,
        "other_operator": 1,
        "text_differs_from_label": 1,
    }
    (text,) = [u for u in result["unresolved"] if u["attr"] == "text"]
    assert text["class"] == "BIM_PT_walls" and text["expr"] == "label_for(context)"


def test_shared_labels_are_listed_as_collisions(result):
    assert result["summary"]["label_collisions"] == {"Add Wall": ["bim.add_wall", "bim.unused"]}


def test_references_that_resolve_to_no_entry_are_reported(result):
    ui = "bim/module/model/ui.py"
    assert result["summary"]["unresolved_references"] == [
        f"bim.ghost {ui}:{line_of(ui, 'bim.ghost')}",
        f"bim.removed_operator {ui}:{line_of(ui, 'bim.removed_operator')}",
    ]
    # f"bim.add_{kind}" in ui.py and the lifecycle template are prefixes, not references.
    assert result["summary"]["reference_fragments_in_fstrings"] == 2


def test_syntax_error_names_the_file():
    with pytest.raises(CheckFailed, match="bim/broken.py: cannot be parsed"):
        extract({"bim/broken.py": b"class (:\n"})


def test_no_comment_docstring_or_header_text_reaches_the_output(result):
    text = json.dumps(result)
    assert privacy_matches(text) == {}
    assert "Synthetic header" not in text and "Contact" not in text


def test_output_is_sorted_and_independent_of_file_order():
    forward = lexicon(FILES)
    backward = lexicon(dict(reversed(list(FILES.items()))))
    assert forward == backward
    keys = [(e["kind"], e["id"], e["file"], e["line"]) for e in forward["entries"]]
    assert keys == sorted(keys)
