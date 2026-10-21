"""Internacionalización mínima con gettext.

La UI se escribe con `_()` desde el primer día para poder traducir sin
reordenar cadenas. Español e inglés van incluidos; el resto de idiomas se
añaden con un .po en po/ y un .mo compilado en share/locale/.
"""

from __future__ import annotations

import gettext
import locale
import os

from . import paths

DOMAIN = "kabe"
_translation: gettext.NullTranslations = gettext.NullTranslations()


def init(language: str = "") -> gettext.NullTranslations:
    """Prepara las traducciones. Idioma explícito > LC_ALL > LC_MESSAGES > LANG."""
    global _translation

    candidates: list[str] = []
    if language:
        candidates.append(language)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        raw = os.environ.get(var, "")
        if raw and raw not in ("C", "POSIX"):
            candidates.append(raw.split(":")[0].split(".")[0])
    if not candidates:
        try:
            loc = locale.getlocale()[0]
            if loc:
                candidates.append(loc)
        except ValueError:
            pass

    tried: set[str] = set()
    for lang in candidates:
        if not lang or lang in tried:
            continue
        tried.add(lang)
        try:
            localedir = str(paths.locale_dir())
            trans = gettext.translation(
                DOMAIN, localedir=localedir, languages=[lang], fallback=True
            )
        except OSError:
            continue
        if trans is not None and getattr(trans, "_catalog", None):
            _translation = trans
            break
    return _translation


def gettext_(message: str) -> str:
    return _translation.gettext(message)


def ngettext_(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


# Atajos de uso: el decorador _ traduce una cadena en el momento de escribirla.
_ = gettext_
N_ = ngettext_
