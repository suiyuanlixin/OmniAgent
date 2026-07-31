import os
import re
from dataclasses import dataclass
from pathlib import Path


REFERENCE_PATTERN = re.compile(r"\[@(file|folder):([^\[\]\r\n]+)\]")


@dataclass(frozen=True)
class Reference:
    kind: str
    source: str
    path: Path
    start: int
    end: int
    display: str = ""

    @property
    def syntax(self):
        return f"[@{self.kind}:{self.source}]"


def resolve_references(text, base_dir=None):
    base = Path(base_dir).resolve() if base_dir is not None else None
    references = []
    for match in REFERENCE_PATTERN.finditer(str(text or "")):
        kind = match.group(1)
        source = match.group(2).strip()
        if not source:
            continue
        source_path = Path(source).expanduser()
        if source_path.is_absolute():
            candidate = source_path
        elif base is not None:
            candidate = base / source_path
        else:
            continue
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if kind == "file" and not path.is_file():
            continue
        if kind == "folder" and not path.is_dir():
            continue
        references.append(Reference(kind, source, path, match.start(), match.end()))
    displays = shortest_unique_displays(references)
    return [
        Reference(item.kind, item.source, item.path, item.start, item.end, display)
        for item, display in zip(references, displays)
    ]


def shortest_unique_displays(references):
    if not references:
        return []
    depths = [1] * len(references)
    parts = [reference.path.parts for reference in references]
    while True:
        values = []
        for index, reference in enumerate(references):
            count = min(depths[index], len(parts[index]))
            value = "/".join(parts[index][-count:])
            if reference.kind == "folder":
                value += "/"
            values.append(value)
        groups = {}
        for index, value in enumerate(values):
            groups.setdefault(os.path.normcase(value), []).append(index)
        collisions = [indices for indices in groups.values() if len(indices) > 1]
        if not collisions:
            return values
        changed = False
        for indices in collisions:
            distinct_paths = {
                os.path.normcase(str(references[index].path)) for index in indices
            }
            if len(distinct_paths) == 1:
                continue
            for index in indices:
                if depths[index] < len(parts[index]):
                    depths[index] += 1
                    changed = True
        if not changed:
            return values


def reference_path_key(path):
    return os.path.normcase(str(Path(path).resolve(strict=False)))
