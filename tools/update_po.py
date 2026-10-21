#!/usr/bin/env python3
"""Actualiza los catálogos .po de Kabe (sustituto mínimo de xgettext).

    python3 tools/update_po.py          → actualiza po/es.po y po/en.po

Escanea el código en busca de `_("…")`, `N_("…")` y las listas de opciones
marcadas con `# i18n:` y actualiza los .po sin perder las traducciones
existentes.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGUAGES = ("es", "en")

STRING_RE = re.compile(r'(?:_|N_)\(\s*("(?:[^"\\]|\\.)*"(?:\s*\n\s*"(?:[^"\\]|\\.)*")*)\s*\)')
OPTION_RE = re.compile(r'^\s*\("([^"]+)",\s*"([^"]+)"\),\s*(#\s*i18n:.*)?$')


def extract() -> list[tuple[str, str]]:
    """Devuelve [(referencia, texto)]."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for base, _dirs, files in os.walk(os.path.join(ROOT, "kabe")):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            rel = os.path.relpath(path, ROOT)
            with open(path, "r", encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    match = STRING_RE.search(line)
                    if match:
                        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))
                        text = "".join(parts).replace('\\"', '"').replace("\\n", "\n")
                        if text and text not in seen:
                            seen.add(text)
                            found.append((f"{rel}:{number}", text))
                    else:
                        option = OPTION_RE.match(line)
                        if option and option.group(3):
                            text = option.group(2)
                            if text not in seen:
                                seen.add(text)
                                found.append((f"{rel}:{number}", text))
    return found


def read_po(path: str) -> dict[str, str]:
    """Lee un .po simple: {msgid: msgstr}."""
    catalog: dict[str, str] = {}
    if not os.path.exists(path):
        return catalog
    msgid: list[str] = []
    msgstr: list[str] = []
    mode = None
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("msgid "):
                if mode == "msgstr":
                    catalog["".join(msgid)] = "".join(msgstr)
                msgid, msgstr, mode = [_unquote(line[6:])], [], "msgid"
            elif line.startswith("msgstr "):
                msgstr = [_unquote(line[7:])]
                mode = "msgstr"
            elif line.startswith('"'):
                chunk = _unquote(line)
                if mode == "msgid":
                    msgid.append(chunk)
                elif mode == "msgstr":
                    msgstr.append(chunk)
    if mode == "msgstr":
        catalog["".join(msgid)] = "".join(msgstr)
    return catalog


def _unquote(text: str) -> str:
    text = text.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return text.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")


def write_po(path: str, language: str, entries: list[tuple[str, str]],
             existing: dict[str, str]) -> None:
    lines = [
        "# Kabe — catálogo de traducción",
        f"msgid \"\"",
        f"msgstr \"\"",
        f"\"Language: {language}\\n\"",
        "\"Content-Type: text/plain; charset=UTF-8\\n\"",
        "\"Content-Transfer-Encoding: 8bit\\n\"",
        "",
    ]
    for reference, text in entries:
        lines.append(f"#: {reference}")
        lines.append(f"msgid {_quote(text)}")
        translation = existing.get(text, "")
        if translation:
            lines.append(f"msgstr {_quote(translation)}")
        else:
            lines.append('msgstr ""')
        lines.append("")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def main() -> int:
    entries = extract()
    print(f"{len(entries)} cadenas encontradas")
    for language in LANGUAGES:
        path = os.path.join(ROOT, "po", f"{language}.po")
        existing = read_po(path)
        write_po(path, language, entries, existing)
        print(f"  po/{language}.po actualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
