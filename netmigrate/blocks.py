"""
Block-aware configuration parser.

Turns raw configuration text into a tree of ConfigBlock objects. This is the
front end: it understands *structure* only, not command meaning. Vendor rule
modules walk the resulting tree and populate the IR.

Why a tree and not a line list
------------------------------
The meaning of a line depends on its enclosing block -- ``description UPLINK``
means one thing under an interface and another under a VLAN. A flat line list
throws that away, and the class-S OSPF transformation becomes inexpressible.

Nesting is derived from indentation, which both IOS-XE and VRP ``display`` /
``show running-config`` output use consistently. Explicit block terminators
(``exit``, ``quit``, ``end``, ``return``) are recognised and consumed, but
indentation is authoritative -- some configs omit terminators entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Comment markers: Cisco uses '!', Huawei uses '#'. Both appear as bare
# separators too, which we treat as blank for counting purposes.
COMMENT_MARKERS = ("!", "#")

# Commands that close the current context. Consumed, not emitted as children.
BLOCK_TERMINATORS = {"exit", "quit"}

# Commands that return all the way to the top level.
ROOT_TERMINATORS = {"end", "return"}


@dataclass
class ConfigBlock:
    """One configuration line, plus anything nested under it."""

    text: str = ""            # stripped command text
    line_no: int = 0          # 1-based line number in the source file
    indent: int = 0           # leading whitespace count
    children: list["ConfigBlock"] = field(default_factory=list)
    is_comment: bool = False
    raw: str = ""             # original line, untouched

    @property
    def keyword(self) -> str:
        """First token, lowercased. Used for rule dispatch."""
        return self.text.split()[0].lower() if self.text else ""

    @property
    def args(self) -> list[str]:
        """Tokens after the first."""
        return self.text.split()[1:]

    def child_with_keyword(self, keyword: str) -> "ConfigBlock | None":
        for c in self.children:
            if c.keyword == keyword:
                return c
        return None

    def children_with_keyword(self, keyword: str) -> list["ConfigBlock"]:
        return [c for c in self.children if c.keyword == keyword]

    def walk(self):
        """Depth-first over self and all descendants."""
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class ParsedConfig:
    """Result of parsing: top-level blocks plus line accounting."""

    blocks: list[ConfigBlock] = field(default_factory=list)
    total_lines: int = 0
    significant_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0

    def walk(self):
        for b in self.blocks:
            yield from b.walk()

    def blocks_with_keyword(self, keyword: str) -> list[ConfigBlock]:
        return [b for b in self.blocks if b.keyword == keyword]


def _is_comment(stripped: str) -> bool:
    return bool(stripped) and stripped[0] in COMMENT_MARKERS


def parse_blocks(text: str) -> ParsedConfig:
    """Parse configuration text into a block tree.

    Blank lines and comment lines are counted but not added to the tree --
    renderers regenerate separators for the target vendor, so carrying source
    comments into the tree would mean emitting the wrong marker.
    """
    result = ParsedConfig()

    # Stack of (indent, block). The block at the top receives new children.
    # A sentinel root with indent -1 keeps the loop uniform.
    root = ConfigBlock(text="<root>", indent=-1)
    stack: list[ConfigBlock] = [root]

    for idx, raw in enumerate(text.splitlines(), start=1):
        result.total_lines += 1

        stripped = raw.strip()

        if not stripped:
            result.blank_lines += 1
            continue

        if _is_comment(stripped):
            result.comment_lines += 1
            continue

        lowered = stripped.lower()

        # Explicit terminators adjust the stack but produce no node.
        if lowered in ROOT_TERMINATORS:
            result.significant_lines += 1
            del stack[1:]
            continue

        if lowered in BLOCK_TERMINATORS:
            result.significant_lines += 1
            if len(stack) > 1:
                stack.pop()
            continue

        result.significant_lines += 1

        indent = len(raw) - len(raw.lstrip())

        # Pop until the top of the stack is a valid parent for this indent.
        while len(stack) > 1 and indent <= stack[-1].indent:
            stack.pop()

        block = ConfigBlock(
            text=stripped,
            line_no=idx,
            indent=indent,
            is_comment=False,
            raw=raw,
        )
        stack[-1].children.append(block)
        stack.append(block)

    result.blocks = root.children
    return result


def dump_tree(blocks: list[ConfigBlock], depth: int = 0) -> str:
    """Human-readable tree, for debugging and for report figures."""
    out = []
    for b in blocks:
        out.append(f"{'  ' * depth}[{b.line_no:>3}] {b.text}")
        if b.children:
            out.append(dump_tree(b.children, depth + 1))
    return "\n".join(out)
