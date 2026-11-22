"""Bonsai operator, panel, menu and tool lexicon, read by AST from a pinned source snapshot.

The add-on is parsed with the standard library's `ast` and never imported or executed.
Only identifiers, labels, button texts, class names, constant panel fields, file paths
relative to the source root and line numbers are emitted, never comments or docstrings
(the files' headers carry contributors' contact addresses).
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from bonsai_help.doc_snapshot import CheckFailed

SCHEMA = "bonsai-lexicon-v1"
EXTRACTOR = "bonsai-ast-v1"
BPY_KINDS = {
    "Operator": "operator",
    "Macro": "macro",
    "WorkSpaceTool": "tool",
    "Panel": "panel",
    "Menu": "menu",
    "UIList": None,
    "Gizmo": None,
    "GizmoGroup": None,
    "Header": None,
}
NEEDS_IDNAME = {"operator", "macro", "tool"}
PANEL_FIELDS = {
    "parent": "bl_parent_id",
    "space": "bl_space_type",
    "region": "bl_region_type",
    "context": "bl_context",
    "category": "bl_category",
    "bim_tab_name": "bim_tab_name",
}
CLASS_FIELDS = frozenset({"bl_idname", "bl_label", *PANEL_FIELDS.values()})
LIFECYCLE_VERBS = ("enable", "finish", "cancel")
LIFECYCLE_TEMPLATE = ("tool/parametric.py", 'f"bim.enable_editing_{')
BIM_ID = re.compile(r"bim\.[a-z0-9_]+")
EXPR_LIMIT = 80


@dataclass
class ClassInfo:
    file: str
    name: str
    line: int
    bases: list[str]
    attrs: dict[str, tuple[str | None, int, str]]  # field -> (constant or None, line, expr)


def _dotted(node: ast.expr) -> str:
    return ast.unparse(node)


def _expr(node: ast.expr) -> str:
    text = " ".join(ast.unparse(node).split())
    return text if len(text) <= EXPR_LIMIT else text[: EXPR_LIMIT - 3] + "..."


def _constant_str(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _class_info(file: str, node: ast.ClassDef) -> ClassInfo:
    attrs: dict[str, tuple[str | None, int, str]] = {}
    for statement in node.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in CLASS_FIELDS:
            attrs[target.id] = (_constant_str(value), statement.lineno, _expr(value))
    return ClassInfo(file, node.name, node.lineno, [_dotted(b) for b in node.bases], attrs)


@dataclass
class Parsed:
    classes: list[ClassInfo]
    registered: set[str]
    lifecycle_calls: list[dict]
    references: list[tuple[str, str, int]]  # (id, file, line)
    fragments: int
    button_calls: list[dict]
    unresolved: list[dict]
    template: str | None


def _parse(files: Mapping[str, bytes]) -> Parsed:
    parsed = Parsed([], set(), [], [], 0, [], [], None)
    for path in sorted(files):
        try:
            tree = ast.parse(files[path], filename=path)
        except (SyntaxError, ValueError) as error:
            raise CheckFailed(f"{path}: cannot be parsed ({error.__class__.__name__})") from None
        fragment_nodes = {
            id(part)
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            for part in node.values
        }
        enclosing = _enclosing_classes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                parsed.classes.append(_class_info(path, node))
            elif path.rsplit("/", 1)[-1] == "__init__.py" and isinstance(
                node, ast.Assign | ast.AugAssign
            ):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == "classes" for t in targets):
                    if isinstance(node.value, ast.Tuple | ast.List):
                        for item in node.value.elts:
                            if isinstance(item, ast.Attribute):
                                parsed.registered.add(item.attr)
                            elif isinstance(item, ast.Name):
                                parsed.registered.add(item.id)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "build_edit_lifecycle"
                ):
                    parsed.lifecycle_calls.append(_lifecycle(path, node, call, parsed.unresolved))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in fragment_nodes:
                    parsed.fragments += node.value.startswith("bim.")
                elif BIM_ID.fullmatch(node.value):
                    parsed.references.append((node.value, path, node.lineno))
            elif isinstance(node, ast.Attribute) and _dotted(node.value) == "bpy.ops.bim":
                parsed.references.append((f"bim.{node.attr}", path, node.lineno))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "operator"
                and node.args
            ):
                parsed.button_calls.append(_button(path, node, enclosing.get(id(node))))
        if path == LIFECYCLE_TEMPLATE[0]:
            text = files[path].decode("utf-8")
            if LIFECYCLE_TEMPLATE[1] in text:
                line = text[: text.index(LIFECYCLE_TEMPLATE[1])].count("\n") + 1
                parsed.template = f"{path}:{line}"
    return parsed


def _enclosing_classes(tree: ast.AST) -> dict[int, str]:
    found: dict[int, str] = {}

    def visit(node: ast.AST, owner: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.ClassDef) else owner
            if owner is not None:
                found[id(child)] = owner
            visit(child, name)

    visit(tree, None)
    return found


def _lifecycle(path: str, node: ast.Assign, call: ast.Call, unresolved: list[dict]) -> dict:
    name = _constant_str(call.args[0]) if call.args else None
    labels_node = next((k.value for k in call.keywords if k.arg == "labels"), None)
    labels = None
    try:
        value = ast.literal_eval(labels_node) if labels_node is not None else None
        if (
            isinstance(value, tuple | list)
            and len(value) == 3
            and all(isinstance(item, tuple | list) and isinstance(item[0], str) for item in value)
        ):
            labels = [item[0] for item in value]
    except ValueError:
        labels = None
    target = node.targets[0]
    names = (
        [elt.id if isinstance(elt, ast.Name) else None for elt in target.elts]
        if isinstance(target, ast.Tuple) and len(target.elts) == 3
        else [None, None, None]
    )
    if name is None or labels is None:
        unresolved.append(
            {
                "file": path,
                "line": call.lineno,
                "class": None,
                "attr": "build_edit_lifecycle",
                "expr": _expr(call),
            }
        )
        return {}
    return {"name": name, "labels": labels, "classes": names, "file": path, "line": call.lineno}


def _button(path: str, call: ast.Call, owner: str | None) -> dict:
    operator = _constant_str(call.args[0])
    text_node = next((k.value for k in call.keywords if k.arg == "text"), None)
    return {
        "id": operator,
        "id_expr": None if operator is not None else _expr(call.args[0]),
        "has_text": text_node is not None,
        "text": _constant_str(text_node) if text_node is not None else None,
        "text_expr": _expr(text_node) if text_node is not None else None,
        "file": path,
        "line": call.lineno,
        "class": owner,
    }


def _kind_of(info: ClassInfo, by_name: Mapping[str, list[ClassInfo]], seen: frozenset) -> str:
    for base in info.bases:
        last = base.rsplit(".", 1)[-1]
        if last in BPY_KINDS:
            return last
    for base in info.bases:
        last = base.rsplit(".", 1)[-1]
        for parent in by_name.get(last, []):
            key = (parent.file, parent.name, parent.line)
            if key in seen:
                continue
            found = _kind_of(parent, by_name, seen | {key})
            if found:
                return found
    return ""


def _inherited(
    info: ClassInfo, attr: str, by_name: Mapping[str, list[ClassInfo]], seen: frozenset
) -> tuple[tuple[str | None, int, str] | None, ClassInfo | None]:
    if attr in info.attrs:
        return info.attrs[attr], info
    for base in info.bases:
        for parent in by_name.get(base.rsplit(".", 1)[-1], []):
            key = (parent.file, parent.name, parent.line)
            if key in seen:
                continue
            value, owner = _inherited(parent, attr, by_name, seen | {key})
            if value is not None:
                return value, owner
    return None, None


def extract(files: Mapping[str, bytes]) -> dict:
    """The lexicon body (entries, ui_texts, unresolved, summary) of one source snapshot."""
    parsed = _parse(files)
    by_name: dict[str, list[ClassInfo]] = defaultdict(list)
    for info in parsed.classes:
        by_name[info.name].append(info)
    entries: list[dict] = []
    unresolved = list(parsed.unresolved)
    counted: Counter[str] = Counter()
    counted_ids: set[str] = set()
    skipped = abstract = 0
    for info in parsed.classes:
        key = (info.file, info.name, info.line)
        for attr in ("bl_idname", "bl_label"):
            value = info.attrs.get(attr)
            if value is not None and value[0] is None:
                unresolved.append(
                    {
                        "file": info.file,
                        "line": value[1],
                        "class": info.name,
                        "attr": attr,
                        "expr": value[2],
                    }
                )
        bpy_kind = _kind_of(info, by_name, frozenset({key}))
        if not bpy_kind:
            skipped += 1
            continue
        kind = BPY_KINDS[bpy_kind]
        if kind is None:
            counted[bpy_kind] += 1
            own = info.attrs.get("bl_idname")
            counted_ids.add(own[0] if own and own[0] else info.name)
            continue
        own_id = info.attrs.get("bl_idname")
        if own_id is not None and own_id[0] is None:
            continue
        if own_id is None and kind in NEEDS_IDNAME:
            abstract += 1
            continue
        label, owner = _inherited(info, "bl_label", by_name, frozenset({key}))
        entry = {
            "kind": kind,
            "id": own_id[0] if own_id else info.name,
            "id_origin": "bl_idname" if own_id else "class_name",
            "label": label[0] if label else None,
            "label_inherited": owner is not None and owner is not info,
            "class": info.name,
            "file": info.file,
            "line": info.line,
            "registered": info.name in parsed.registered,
        }
        if kind in ("panel", "menu"):
            for name, attr in PANEL_FIELDS.items():
                value, _ = _inherited(info, attr, by_name, frozenset({key}))
                entry[name] = value[0] if value else None
        entries.append(entry)
    calls = [call for call in parsed.lifecycle_calls if call]
    if calls and parsed.template is None:
        raise CheckFailed(
            f"build_edit_lifecycle is called but {LIFECYCLE_TEMPLATE[0]} has no id template"
        )
    for call in calls:
        for verb, label, name in zip(LIFECYCLE_VERBS, call["labels"], call["classes"], strict=True):
            entries.append(
                {
                    "kind": "operator",
                    "id": f"bim.{verb}_editing_{call['name']}",
                    "id_origin": "derived:build_edit_lifecycle",
                    "label": label,
                    "label_inherited": False,
                    "class": name,
                    "file": call["file"],
                    "line": call["line"],
                    "registered": name is not None and name in parsed.registered,
                    "template": parsed.template,
                }
            )
    entries.sort(key=lambda e: (e["kind"], e["id"], e["file"], e["line"]))
    operator_ids = {e["id"] for e in entries if e["kind"] in ("operator", "macro")}
    ui_texts = []
    button_stats: Counter[str] = Counter()
    labels_by_id: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        if entry["kind"] in ("operator", "macro") and entry["label"]:
            labels_by_id[entry["id"]].add(entry["label"])
    for call in parsed.button_calls:
        if call["id"] is None:
            button_stats["dynamic_operator"] += 1
            continue
        if call["id"] not in operator_ids:
            button_stats["other_operator"] += 1
            continue
        button_stats["calls"] += 1
        if not call["has_text"]:
            button_stats["label_text"] += 1
        elif call["text"] is None:
            button_stats["dynamic_text"] += 1
            unresolved.append(
                {
                    "file": call["file"],
                    "line": call["line"],
                    "class": call["class"],
                    "attr": "text",
                    "expr": call["text_expr"],
                }
            )
        elif not call["text"]:
            button_stats["empty_text"] += 1
        else:
            button_stats["constant_text"] += 1
            differs = call["text"] not in labels_by_id[call["id"]]
            button_stats["text_differs_from_label"] += differs
            ui_texts.append(
                {
                    "id": call["id"],
                    "text": call["text"],
                    "differs_from_label": differs,
                    "file": call["file"],
                    "line": call["line"],
                }
            )
    ui_texts.sort(key=lambda u: (u["id"], u["text"], u["file"], u["line"]))
    unresolved.sort(key=lambda u: (u["file"], u["line"], u["attr"]))
    summary = _summary(
        files, parsed, entries, ui_texts, button_stats, counted, skipped, abstract, counted_ids
    )
    return {"entries": entries, "ui_texts": ui_texts, "unresolved": unresolved, "summary": summary}


def _summary(
    files, parsed, entries, ui_texts, button_stats, counted, skipped, abstract, counted_ids
) -> dict:
    operators = [e for e in entries if e["kind"] in ("operator", "macro")]
    bim = [e for e in operators if e["id"].startswith("bim.")]
    static_bim = {e["id"] for e in bim if e["id_origin"] == "bl_idname"}
    by_id = Counter((e["kind"], e["id"]) for e in entries)
    label_ids: dict[str, set[str]] = defaultdict(set)
    for entry in bim:
        if entry["label"]:
            label_ids[entry["label"]].add(entry["id"])
    known = {e["id"] for e in entries} | counted_ids
    references = [ref for ref in parsed.references if ref[0] not in known]
    operator_py = {
        e["id"]
        for e in bim
        if e["id_origin"] == "bl_idname"
        and re.fullmatch(r"bim/module/[^/]+/operator\.py", e["file"])
    }
    return {
        "python_files": len(files),
        "classes": len(parsed.classes),
        "classes_without_kind": skipped,
        "abstract_classes_without_idname": abstract,
        "counted_only": dict(sorted(counted.items())),
        "entries": dict(sorted(Counter(e["kind"] for e in entries).items())),
        "bim_operator_ids": len({e["id"] for e in bim}),
        "bim_operator_ids_static": len(static_bim),
        "bim_operator_ids_derived": len({e["id"] for e in bim} - static_bim),
        "bim_operator_ids_in_module_operator_py": len(operator_py),
        "other_operator_ids": sorted({e["id"] for e in operators} - {e["id"] for e in bim}),
        "operator_labels_unique": len({e["label"] for e in bim if e["label"]}),
        "operators_without_label": sorted({e["id"] for e in bim if not e["label"]}),
        "operator_classes_not_registered": sorted(
            f"{e['id']} {e['file']}:{e['line']}" for e in operators if not e["registered"]
        ),
        "panels_with_parent": sum(1 for e in entries if e["kind"] == "panel" and e["parent"]),
        "duplicate_ids": sorted(
            f"{kind} {name}" for (kind, name), count in by_id.items() if count > 1
        ),
        "label_collisions": {
            label: sorted(ids) for label, ids in sorted(label_ids.items()) if len(ids) > 1
        },
        "references": len(parsed.references),
        "reference_fragments_in_fstrings": parsed.fragments,
        "unresolved_references": sorted({f"{ref[0]} {ref[1]}:{ref[2]}" for ref in references}),
        "buttons": dict(sorted(button_stats.items())),
        "ui_texts": len(ui_texts),
        "ui_texts_unique": len({(u["id"], u["text"]) for u in ui_texts}),
    }
