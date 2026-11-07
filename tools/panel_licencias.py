#!/usr/bin/env python3
"""PANEL CENTRAL DE LICENCIAS — FerreGest AR (herramienta de la PROPIETARIA).

Este script NO forma parte de la instalación del comercio: se ejecuta en la
computadora de la desarrolladora para emitir, renovar y revocar licencias.

Requiere la variable de entorno LICENSE_SIGNING_KEY (NUNCA la suba al repo).

Uso:
  export LICENSE_SIGNING_KEY="clave-secreta-larga"
  python3 tools/panel_licencias.py crear --instalacion FER-XXXX --cliente "Ferretería X" --dias 365
  python3 tools/panel_licencias.py listar            # (evidencia local de emisiones)
  python3 tools/panel_licencias.py emitir-desde-json licencia.json

Estados que luego refleja la instalación (derivados localmente):
  activa → por_vencer (aviso) → vencida_gracia → suspendida → reactivada (con licencia nueva)

La suspensión NUNCA borra datos del comercio: solo bloquea operaciones
comerciales y deja disponibles consulta, informes y exportación.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def cmd_crear(args):
    from app.license import sign_license

    payload = {
        "license_id": args.licencia or "LIC-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "install_id": args.instalacion,
        "client": args.cliente,
        "issued_at": date.today().isoformat(),
        "expires_at": (date.today() + timedelta(days=args.dias)).isoformat(),
        "grace_days": args.gracia,
        "warn_days": args.aviso,
        "status": "activada",
    }
    blob = sign_license(payload)
    registro = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "licencias_emitidas.jsonl")
    with open(registro, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"emitida": datetime.now().isoformat(), "payload": payload},
                            ensure_ascii=False) + "\n")
    print("=== LICENCIA EMITIDA ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nArchivo para el cliente (entregar por el medio acordado):\n")
    print(blob)


def cmd_listar(_args):
    registro = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "licencias_emitidas.jsonl")
    if not os.path.exists(registro):
        print("Sin licencias emitidas todavía.")
        return
    with open(registro, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            p = row["payload"]
            print(f"{row['emitida']}  {p['license_id']}  instalación={p['install_id']}  "
                  f"cliente={p['client']}  vence={p['expires_at']}")


def cmd_desde_json(args):
    from app.license import sign_license

    with open(args.archivo, encoding="utf-8") as fh:
        payload = json.load(fh)
    print(sign_license(payload))


def main():
    ap = argparse.ArgumentParser(description="Panel central de licencias FerreGest AR")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear", help="Emitir una licencia firmada")
    c.add_argument("--instalacion", required=True, help="ID de instalación del comercio")
    c.add_argument("--cliente", required=True)
    c.add_argument("--dias", type=int, default=365)
    c.add_argument("--gracia", type=int, default=7)
    c.add_argument("--aviso", type=int, default=15)
    c.add_argument("--licencia", default=None)
    c.set_defaults(func=cmd_crear)
    l = sub.add_parser("listar", help="Historial local de emisiones")
    l.set_defaults(func=cmd_listar)
    j = sub.add_parser("emitir-desde-json", help="Firmar un payload existente")
    j.add_argument("archivo")
    j.set_defaults(func=cmd_desde_json)
    args = ap.parse_args()
    if not os.environ.get("LICENSE_SIGNING_KEY"):
        print("ERROR: defina LICENSE_SIGNING_KEY antes de usar el panel.", file=sys.stderr)
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
