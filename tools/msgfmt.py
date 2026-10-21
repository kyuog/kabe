#!/usr/bin/env python3
"""Compilador .po → .mo en Python puro.

Los sistemas no siempre traen las herramientas de gettext instaladas
(msgfmt), así que Kabe incluye este compilador mínimo: entiende el formato
PO habitual (msgid, msgstr, continuaciones multilínea, msgctxt, plural) y
genera un catálogo binario válido para el módulo `gettext` de Python.

    python3 tools/msgfmt.py po/es.po share/locale/es/LC_MESSAGES/kabe.mo
"""

from __future__ import annotations

import array
import re
import struct
import sys

MAGIC = 0x950412DE


def parse_po(text: str) -> dict[tuple[str, str], str]:
    """Devuelve {(msgctxt, msgid): msgstr}."""
    catalog: dict[tuple[str, str], str] = {}
    msgctxt: str | None = None
    msgid: list[str] = []
    msgstr: list[str] = []
    mode: str | None = None
    fuzzy = False
    pending_plural: str | None = None

    def flush() -> None:
        nonlocal msgid, msgstr, mode, fuzzy, pending_plural, msgctxt
        if mode == "msgstr" and (msgid or msgstr):
            if not fuzzy:
                key = (msgctxt or "", "".join(msgid))
                value = "".join(msgstr)
                if pending_plural is not None:
                    key = (key[0], key[1] + "\x00" + pending_plural)
                catalog[key] = value
        msgid, msgstr = [], []
        mode = None
        fuzzy = False
        pending_plural = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        if line.startswith("msgctxt "):
            flush()
            msgctxt = _unquote(line[len("msgctxt "):])
            mode = "msgctxt"
            continue
        if line.startswith("msgid_plural "):
            pending_plural = _unquote(line[len("msgid_plural "):])
            mode = "msgid"
            continue
        if line.startswith("msgid "):
            if mode == "msgstr":
                flush()
            msgid = [_unquote(line[len("msgid "):])]
            mode = "msgid"
            continue
        if line.startswith("msgstr["):
            index = int(line[7])
            if index == 0:
                msgstr = [_unquote(line[line.index("]") + 2:])]
                mode = "msgstr"
            else:
                # Plural: se guarda la primera forma; gettext la usa como fallback.
                if not msgstr:
                    msgstr = [_unquote(line[line.index("]") + 2:])]
            continue
        if line.startswith("msgstr "):
            msgstr = [_unquote(line[len("msgstr "):])]
            mode = "msgstr"
            continue
        if line.startswith('"'):
            chunk = _unquote(line)
            if mode == "msgid":
                msgid.append(chunk)
            elif mode == "msgstr":
                msgstr.append(chunk)
            continue
    flush()
    return catalog


def _unquote(text: str) -> str:
    text = text.strip()
    if not text.startswith('"'):
        return ""
    text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    text = text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
    text = text.replace("\\\\", "\\")
    return text


def make_mo(catalog: dict[tuple[str, str], str], metadata: str) -> bytes:
    """Genera el catálogo binario (.mo)."""
    entries: list[tuple[bytes, bytes]] = []
    header = (
        "Project-Id-Version: kabe\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        "Language: %s\n" % metadata
    )
    entries.append((b"", header.encode("utf-8")))
    for (ctx, msgid), msgstr in catalog.items():
        if msgid == "" or not msgstr:
            # Las entradas sin traducir se omiten: gettext devuelve el
            # msgid original (el idioma de los textos fuente).
            continue
        key = msgid.encode("utf-8") if not ctx else (ctx + "\x04" + msgid).encode("utf-8")
        entries.append((key, msgstr.encode("utf-8")))

    entries.sort(key=lambda pair: pair[0])
    count = len(entries)

    original_table = 7 * 4                       # cabecera (28 bytes)
    translation_table = original_table + count * 8
    data_start = translation_table + count * 8

    key_offsets: list[int] = []
    value_offsets: list[int] = []
    offset = data_start
    for key, _value in entries:
        key_offsets.append(offset)
        offset += len(key) + 1
    for _key, value in entries:
        value_offsets.append(offset)
        offset += len(value) + 1

    header_bytes = struct.pack(
        "<Iiiiiii",
        MAGIC,             # magic
        0,                 # revision
        count,             # número de entradas
        original_table,    # tabla de cadenas originales
        translation_table, # tabla de traducciones
        0,                 # tamaño de la tabla hash
        0,                 # offset de la tabla hash
    )

    original_blob = b"".join(
        struct.pack("<ii", len(key), key_offsets[index])
        for index, (key, _value) in enumerate(entries)
    )
    translation_blob = b"".join(
        struct.pack("<ii", len(value), value_offsets[index])
        for index, (_key, value) in enumerate(entries)
    )
    keys_blob = b"".join(key + b"\x00" for key, _value in entries)
    values_blob = b"".join(value + b"\x00" for _key, value in entries)

    return header_bytes + original_blob + translation_blob + keys_blob + values_blob


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    po_path, mo_path = argv[1], argv[2]
    with open(po_path, "r", encoding="utf-8") as fh:
        catalog = parse_po(fh.read())
    language = po_path.rsplit("/", 1)[-1].removesuffix(".po")
    data = make_mo(catalog, language)
    with open(mo_path, "wb") as fh:
        fh.write(data)
    print(f"{po_path} → {mo_path} ({len(catalog)} entradas)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
