#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

OUTPUT_DIR="${CALENDAR_OUTPUT_DIR:-data/published_calendars}"
mkdir -p "$OUTPUT_DIR"

publish_calendar() {
  local domain="$1"
  local team="$2"
  local filename="$3"
  local destination="$OUTPUT_DIR/$filename"
  local temporary_dir
  local temporary
  temporary_dir="$(mktemp -d "$OUTPUT_DIR/.${filename}.XXXXXX")"
  temporary="$temporary_dir/$filename"
  trap 'rm -f "$temporary"; rmdir "$temporary_dir" 2>/dev/null || true' RETURN

  uv run python -m waterpolo.main export fpn \
    --domain "$domain" \
    --team "$team" \
    --format ics \
    --output "$temporary"
  mv -f "$temporary" "$destination"
  rmdir "$temporary_dir"
  trap - RETURN
  printf 'Publicado: %s\n' "$destination"
}

# Adicione calendários chamando publish_calendar(domain, team, nome-do-ficheiro).
publish_calendar "po01_26-27" "FOCA" "foca-seniores-a1.ics"
# Exemplo histórico opcional: retire o comentário se a época continuar disponível.
# publish_calendar "po12_25-26" "FOCA" "foca-juvenis.ics"
