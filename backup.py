#!/usr/bin/env python3
"""Copia de seguridad de FerreGest AR.

Uso:  python3 tools/backup.py [salida.zip]

Genera un ZIP con:
  - ferregest.db      (base SQLite, vía sqlite3 .backup → consistente)
  - datos.json        (exportación completa en JSON, legible)
  - README.txt        (procedimiento de restauración)

La exportación JSON también está disponible desde la interfaz
(Licencias → Exportar datos) y funciona incluso con licencia suspendida.
"""
import json
import os
import sqlite3
import sys
import zipfile
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("FERREGEST_DB") or os.path.join(BASE, "ferregest.db")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        BASE, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
    tmp_db = out + ".db.tmp"
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(tmp_db)
    with dst:
        src.backup(dst)          # backup consistente aunque haya escrituras
    src.close()
    dst.close()

    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    data = {"fecha": datetime.now().isoformat(), "tabla": {}}
    for t in tables:
        data["tabla"][t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    conn.close()

    readme = (
        "Copia de seguridad FerreGest AR\n"
        f"Fecha: {datetime.now().isoformat()}\n\n"
        "RESTAURAR:\n"
        "1. Detener la aplicación.\n"
        "2. Reemplazar ferregest.db por el ferregest.db incluido en este ZIP.\n"
        "3. Iniciar la aplicación (las migraciones pendientes se aplican solas).\n"
        "4. datos.json es una exportación legible/legible para migraciones.\n"
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "ferregest.db")
        z.writestr("datos.json", json.dumps(data, ensure_ascii=False, default=str, indent=1))
        z.writestr("README.txt", readme)
    os.remove(tmp_db)
    print(f"✅ Copia de seguridad creada: {out}")


if __name__ == "__main__":
    main()
