#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

OUTPUT_DIR="${CALENDAR_OUTPUT_DIR:-data/published_calendars}"
mkdir -p "$OUTPUT_DIR"

# O comando recolhe e normaliza uma única vez e publica os dois artefactos em
# conjunto. Os nomes são parte do contrato operacional deste calendário.
uv run python -m waterpolo.main publish fpn \
  --domain "po01_26-27" \
  --team "FOCA" \
  --json-output "$OUTPUT_DIR/fpn_po01_26-27_foca.json" \
  --ics-output "$OUTPUT_DIR/foca-seniores-a1.ics"
