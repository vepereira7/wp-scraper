# Water Polo Calendar Scraper

Projeto Python independente para recolher calendários de polo aquático de fontes
como FPN e ANNP, normalizar jogos e produzir outputs estáveis. Este repositório é
separado da aplicação WP Stats e não depende dela.

Nesta fase, o projeto define o modelo e o contrato JSON. Ainda não executa scraping
real nem integra com serviços externos.

## Estrutura

```text
src/waterpolo/
├── models/      # Modelos normalizados
├── scraper/     # Fetch, seletores e parsing
├── services/    # Exportadores e serviços de output
├── storage/     # Persistência futura
├── config.py
└── main.py
tests/           # Testes e fixtures locais
docs/            # Modelo e contratos públicos
```

## Desenvolvimento

O projeto requer Python 3.11 ou superior e usa `uv`.

```console
uv run pytest
uv run ruff check .
uv run python -m waterpolo.main
```

## Modelo normalizado

Um `Match` identifica a fonte, época e competição; contém equipas, data, hora e
local; e pode conter resultado, estado, URL de origem e dados brutos de auditoria.
As fontes, categorias e estados conhecidos são enums. Competições continuam como
texto livre para acomodar alterações das fontes.

Mais detalhes em [docs/model.md](docs/model.md).

## Output JSON

```json
{
  "generated_at": "2026-09-30T15:00:00Z",
  "source": "FPN",
  "match_count": 1,
  "matches": [
    {
      "external_id": "fpn-123",
      "source": "FPN",
      "category": "U16",
      "home": "FOCA",
      "away": "Vitória SC",
      "date": "2026-10-04",
      "time": "15:00:00",
      "status": "SCHEDULED"
    }
  ]
}
```

O contrato completo está em [docs/output-contract.md](docs/output-contract.md).

## Roadmap

1. Modelo `Match` e contrato de output.
2. Fetch de HTML.
3. Parser de HTML.
4. Fixtures e testes das fontes.
5. Export JSON, CSV e ICS.
6. SQLite e histórico.
7. Automatização com systemd timer ou cron.
8. Integração futura com WP Stats através do output normalizado.
