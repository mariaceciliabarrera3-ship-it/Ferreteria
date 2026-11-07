#!/usr/bin/env python3
"""FerreGest AR — control previo al commit (ETAPA 2 y ETAPA 7).

Verifica que la carpeta que se va a subir a GitHub no contenga secretos, bases
de datos locales, copias de seguridad ni credenciales de demostración.

Uso:
    python3 tools/check_repo.py                # revisa el árbol de trabajo
    python3 tools/check_repo.py --staged       # revisa lo que está en `git add`

Códigos de salida:
    0 -> limpio
    1 -> se encontraron archivos prohibidos
    2 -> se encontraron posibles secretos embebidos en el código
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Extensiones/nombres que jamás deben publicarse (ARQ-07).
FORBIDDEN_PATTERNS = [
    "*.db", "*.sqlite", "*.sqlite3", "*-wal", "*-shm", "*-journal",
    ".secret", ".license_key", ".env", ".env.*",
    "licencias_emitidas.jsonl",
    "ferregest.db", "tmp_ferregest_test.db",
    "*.bak", "*.dump", "backup_*.zip",
]
ALLOWED = {".env.example"}

# Directorios que nunca se recorren.
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
             ".pytest_cache", "var", "instance", "backups", "uploads"}

# Texto que delata una credencial o clave embebida en el código fuente.
SECRET_HINTS = [
    (re.compile(r"LICENSE_SIGNING_KEY\s*=\s*[\"'][^\"']{8,}"), "clave de licencia embebida"),
    (re.compile(r"FERREGEST_SECRET\s*=\s*[\"'][^\"']{8,}"), "secreto de sesión embebido"),
    (re.compile(r"password\s*=\s*[\"'](admin123|vendedor123|deposito123|12345678)[\"']",
                re.IGNORECASE), "contraseña fija conocida"),
]
SCAN_EXT = (".py", ".js", ".html", ".css", ".md", ".sql", ".txt", ".cfg", ".ini")
SKIP_SCAN_NAMES = {"check_repo.py", ".env.example", "CHANGELOG.md"}

# Valores que delatan un ejemplo de documentación, no una credencial real.
PLACEHOLDER = re.compile(
    r"(clave|secreta?|ejemplo|example|changeme|cambiar|placeholder|xxxx|"
    r"prueba|test|tu[-_]|demo)", re.IGNORECASE)


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def staged_files() -> list[str] | None:
    try:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"],
                             cwd=BASE, capture_output=True, text=True, check=True)
    except Exception:
        return None
    return [f for f in out.stdout.split("\0") if f]


def ignored_by_git(files: list[str]) -> set[str]:
    """Archivos que Git ignora (.gitignore): no se van a commitear, no molestan."""
    try:
        proc = subprocess.run(["git", "check-ignore", "--stdin", "-z"],
                              cwd=BASE, input="\0".join(files),
                              capture_output=True, text=True)
    except Exception:
        return set()
    return {f for f in proc.stdout.split("\0") if f}


def is_forbidden(rel: str) -> str | None:
    base = os.path.basename(rel)
    if base in ALLOWED:
        return None
    for pattern in FORBIDDEN_PATTERNS:
        if fnmatch.fnmatch(base, pattern) or fnmatch.fnmatch(rel, pattern):
            return pattern
    return None


def check_files(files: list[str]) -> int:
    ignorados = ignored_by_git(files)
    problems = 0
    for rel in files:
        if rel in ignorados:
            continue   # Git ya lo excluye: no llegará al commit
        hit = is_forbidden(rel)
        if hit:
            print(f"  [PROHIBIDO] {rel}  (coincide con {hit})")
            problems += 1
    return problems


def check_secrets(files: list[str]) -> int:
    problems = 0
    for rel in files:
        if not rel.endswith(SCAN_EXT) or os.path.basename(rel) in SKIP_SCAN_NAMES:
            continue
        path = os.path.join(BASE, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rx, motivo in SECRET_HINTS:
                m = rx.search(line)
                if not m or line.strip().startswith("#"):
                    continue
                valor = m.group(0)
                if PLACEHOLDER.search(valor):
                    continue   # es documentación: "LICENSE_SIGNING_KEY=\"clave-secreta\""
                print(f"  [SECRETO] {rel}:{lineno}: {motivo}")
                problems += 1
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    use_staged = "--staged" in argv

    if use_staged:
        files = staged_files()
        if files is None:
            print("No se pudo leer el índice de Git (¿es un repositorio?). "
                  "Se revisa el árbol de trabajo.")
            files = None
    else:
        files = None

    if files is None:
        files = [os.path.relpath(p, BASE) for p in iter_files(BASE)]

    print(f"Revisando {len(files)} archivo(s) en {BASE}\n")
    problems = check_files(files)
    problems += check_secrets(files)

    print()
    if problems:
        print(f"RESULTADO: FIX — {problems} problema(s). No haga commit todavía.")
        return 1
    print("RESULTADO: CONTINUE — no se detectaron secretos, bases ni respaldos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
