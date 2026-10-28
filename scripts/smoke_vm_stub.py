#!/usr/bin/env python3
"""Serveur local qui rejoue les fixtures BOAMP / TED / DECP de veille-marches (test de fumée, hors ligne).

Usage : smoke_vm_stub.py <dossier des fixtures> <port>

Le script de fumée pointe BOAMP_BASE_URL, TED_BASE_URL et DECP_BASE_URL vers http://127.0.0.1:<port>/{boamp,ted,decp} ;
`vm collect` déroule alors son vrai code (pagination, mapping, filtres CPV) sur les réponses enregistrées dans
apps/veille-marches/tests/fixtures/, sans toucher au réseau.

  GET  /boamp/catalog/datasets/<jeu>/records  -> boamp_records.json
  GET  /decp/catalog/datasets/<jeu>/records   -> decp_records.json
  POST /ted/notices/search                    -> ted_search.json
  GET  /health                                -> {"status": "ok"}

Les dates ISO des fixtures (écrites autour du 27/10/2026) sont décalées du nombre de jours écoulés depuis cette
date : un avis « paru hier » dans la fixture reste paru hier, et sa date limite reste à venir, quel que soit le
jour où le test est lancé. Aucune dépendance hors bibliothèque standard.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FIXTURE_ANCHOR = date(2026, 10, 27)  # jour de référence des fixtures (dates « hier », « dans 32 jours »…)
ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(.*)$", re.DOTALL)
COMPACT_DATE = re.compile(r"^\d{8}$")
ROUTES = {"/boamp/": "boamp_records.json", "/decp/": "decp_records.json", "/ted/": "ted_search.json"}


def shift_dates(value, delta: timedelta):
    """Décale récursivement les chaînes qui commencent par une date ISO (ou AAAAMMJJ) ; le reste est inchangé."""
    if isinstance(value, dict):
        return {k: shift_dates(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [shift_dates(v, delta) for v in value]
    if isinstance(value, str):
        m = ISO_DATE.match(value)
        if m:
            try:
                return (date.fromisoformat(m.group(1)) + delta).isoformat() + m.group(2)
            except ValueError:
                return value  # un identifiant qui ressemble à une date (2026-2169…) n'est pas une date
        if COMPACT_DATE.match(value):
            try:
                return (date(int(value[:4]), int(value[4:6]), int(value[6:])) + delta).strftime("%Y%m%d")
            except ValueError:
                return value
    return value


def load_fixtures(folder: Path) -> dict[str, bytes]:
    delta = date.today() - FIXTURE_ANCHOR
    payloads: dict[str, bytes] = {}
    for prefix, name in ROUTES.items():
        path = folder / name
        if not path.exists():
            raise SystemExit(f"fixture introuvable : {path}")
        data = shift_dates(json.loads(path.read_text(encoding="utf-8")), delta)
        payloads[prefix] = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return payloads


def make_handler(payloads: dict[str, bytes]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "smoke-vm-stub/1.0"

        def _reply(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)  # on ignore la requête (where, query…) : la fixture est renvoyée telle quelle
            if self.path == "/health":
                self._reply(200, b'{"status": "ok"}')
                return
            for prefix, body in payloads.items():
                if self.path.startswith(prefix):
                    self._reply(200, body)
                    return
            self._reply(404, json.dumps({"error": f"route inconnue : {self.path}"}).encode("utf-8"))

        do_GET = _route
        do_POST = _route

        def log_message(self, fmt, *args):  # journal compact sur stderr (repris dans le log de l'étape)
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    return Handler


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    folder, port = Path(argv[1]), int(argv[2])
    server = HTTPServer(("127.0.0.1", port), make_handler(load_fixtures(folder)))
    print(f"stub veille-marches : http://127.0.0.1:{port} (fixtures : {folder})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
