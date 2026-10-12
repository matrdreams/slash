"""Parse a uiautomator dump and compress it to a short, stable node list."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass
class UINode:
    element_id: int
    class_name: str
    text: str
    desc: str
    resource_id: str
    package: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    long_clickable: bool
    enabled: bool
    checkable: bool = False
    checked: bool = False
    hint: str = ""
    focused: bool = False
    label: str = ""

    @property
    def editable(self) -> bool:
        return "EditText" in self.class_name or "AutoCompleteTextView" in self.class_name

    @property
    def interesting(self) -> bool:
        return bool(
            self.text or self.desc or self.clickable or self.long_clickable or self.checkable or self.editable
        )


def _flag(value: str | None) -> bool:
    return (value or "").lower() == "true"


def _bounds(value: str | None) -> tuple[int, int, int, int]:
    if not value:
        return (0, 0, 0, 0)
    cleaned = value.replace("][", ",").replace("[", "").replace("]", "")
    parts = [int(item) for item in cleaned.split(",") if item]
    if len(parts) != 4:
        return (0, 0, 0, 0)
    return parts[0], parts[1], parts[2], parts[3]


def parse_hierarchy(xml_text: str) -> list[UINode]:
    if not xml_text or "<hierarchy" not in xml_text:
        return []
    start = xml_text.find("<hierarchy")
    try:
        root = ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return []
    found: list[UINode] = []

    def walk(element: ET.Element) -> None:
        if element.tag != "node":
            for child in element:
                walk(child)
            return
        left, top, right, bottom = _bounds(element.attrib.get("bounds"))
        visible = right > left and bottom > top and _flag(element.attrib.get("enabled", "true"))
        if visible:
            found.append(
                UINode(
                    element_id=0,
                    class_name=element.attrib.get("class") or "node",
                    text=(element.attrib.get("text") or "").strip(),
                    desc=(element.attrib.get("content-desc") or "").strip(),
                    resource_id=(element.attrib.get("resource-id") or "").strip(),
                    package=(element.attrib.get("package") or "").strip(),
                    bounds=(left, top, right, bottom),
                    clickable=_flag(element.attrib.get("clickable")),
                    long_clickable=_flag(element.attrib.get("long-clickable")),
                    enabled=True,
                    checkable=_flag(element.attrib.get("checkable")),
                    checked=_flag(element.attrib.get("checked")),
                    hint=(element.attrib.get("hint") or "").strip(),
                    focused=_flag(element.attrib.get("focused")),
                )
            )
        for child in element:
            walk(child)

    walk(root)
    _label_edits(found)
    interesting = [node for node in found if node.interesting]
    for index, node in enumerate(interesting, start=1):
        node.element_id = index
    return interesting


def _rid_words(resource_id: str) -> str:
    name = resource_id.rsplit("/", 1)[-1]
    return name.replace("_", " ").strip()


def _label_edits(nodes: list[UINode]) -> None:
    """Give each EditText a human label: hint, else nearest text label above/left, else id words."""
    for index, node in enumerate(nodes):
        if not node.editable:
            continue
        if node.hint:
            node.label = node.hint
            continue
        left, top, right, bottom = node.bounds
        best = ""
        best_score = None
        for other in nodes[max(0, index - 12) : index]:
            if other.editable or not (other.text or other.desc):
                continue
            o_left, o_top, o_right, o_bottom = other.bounds
            same_row = o_top < bottom and o_bottom > top and o_right <= left + 20
            above = o_bottom <= top + 10 and top - o_bottom < 160 and o_left < right and o_right > left
            if same_row or above:
                score = abs(top - o_top) + abs(left - o_left)
                if best_score is None or score < best_score:
                    best, best_score = other.text or other.desc, score
        node.label = best or node.desc or _rid_words(node.resource_id)


def compress(nodes: list[UINode], limit: int = 80) -> tuple[list[UINode], str]:
    """Keep ids assigned by parse_hierarchy. Drop non-clickable nodes first when over the limit."""
    if len(nodes) > limit:
        clickable = [node for node in nodes if node.clickable or node.long_clickable or node.editable]
        others = [node for node in nodes if node not in clickable]
        room = max(limit - len(clickable), 0)
        chosen = clickable[:limit] + others[:room]
        # Restore document order so the list still reads top to bottom.
        order = {node.element_id: index for index, node in enumerate(nodes)}
        nodes = sorted(chosen, key=lambda node: order[node.element_id])
    lines = [_format_node(node) for node in nodes]
    return nodes, "\n".join(lines)


def _format_node(node: UINode) -> str:
    parts = [f"[{node.element_id}] {node.class_name}"]
    if node.text:
        parts.append(f'"{node.text}"')
    if node.desc:
        parts.append(f'desc="{node.desc}"')
    if node.editable:
        parts.append("editable")
        if node.label and node.label != node.text:
            parts.append(f'label="{node.label}"')
        if node.focused:
            parts.append("focused")
    if node.resource_id:
        parts.append(f"id={node.resource_id}")
    if node.checkable:
        # Switch/checkbox state is what most settings goals are judged on.
        parts.append(f"checked={'true' if node.checked else 'false'}")
    left, top, right, bottom = node.bounds
    parts.append(f"bounds=[{left},{top}][{right},{bottom}]")
    return " ".join(parts)


def find_node(nodes: list[UINode], element_id: int) -> UINode | None:
    for node in nodes:
        if node.element_id == element_id:
            return node
    return None


def center(node: UINode) -> tuple[int, int]:
    left, top, right, bottom = node.bounds
    return (left + right) // 2, (top + bottom) // 2
