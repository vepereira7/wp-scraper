# Water Polo Calendar Scraper

Projeto Python independente para recolher calendários de polo aquático de fontes
como FPN e ANNP, normalizar jogos e produzir outputs estáveis. Este repositório é
separado da aplicação WP Stats e não depende dela.

O projeto define um modelo e um contrato JSON normalizados. A integração FPN usa
diretamente a API pública do ArenaDisplay; a ANNP usa os fragmentos HTML dos
endpoints públicos sazonais. Nenhuma das integrações usa browser em runtime ou
depende de serviços externos da aplicação WP Stats.

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

Um `Match` identifica a fonte, época e competição; contém equipas, data e hora; e
pode conter local, resultado, estado, URL de origem e dados brutos de auditoria.
O local é opcional e permanece `null` quando a fonte não o fornece.
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

O contrato técnico está em [docs/output-contract.md](docs/output-contract.md). O
contrato para consumidores externos, com exemplo de export FPN, está em
[docs/export_contract.md](docs/export_contract.md).

## Fluxo de produção JSON + ICS

O comando de produção faz uma única recolha do calendário selecionado, uma única
normalização e gera os dois ficheiros a partir do mesmo snapshot de `Match`:

```console
uv run python -m waterpolo.main publish fpn \
  --domain po01_26-27 \
  --team FOCA \
  --json-output data/published_calendars/fpn_po01_26-27_foca.json \
  --ics-output data/published_calendars/foca-seniores-a1.ics
```

ANNP usa o mesmo comando e o mesmo pipeline, selecionando uma competição por
nome real ou ID:

```console
uv run python -m waterpolo.main publish annp \
  --season 2627 \
  --team FOCA \
  --competition-id 1 \
  --json-output data/published_calendars/annp-2627-juniores-foca.json \
  --ics-output data/published_calendars/annp-2627-juniores-foca.ics
```

O script compatível `scripts/update_calendars.sh` executa este comando e aceita
`CALENDAR_OUTPUT_DIR` para escolher o diretório de destino. Os nomes previstos
para FOCA são `fpn_po01_26-27_foca.json` e `foca-seniores-a1.ics`.

Antes da publicação, ambos os artefactos são escritos em staging e validados.
Só depois são movidos para os destinos finais com `rename`; se a geração ou a
validação falhar, os outputs anteriores ficam intactos. A publicação dos dois
ficheiros usa backups temporários e rollback para não deixar um artefacto novo
ao lado de outro antigo quando uma operação de rename falha.

Um snapshot vazio é erro operacional por omissão: o comando termina com exit
code diferente de zero e não substitui a última geração válida. O exit code é
`0` apenas quando ambos os ficheiros foram validados e publicados. Erros são
impressos no stderr e registados pelo `RunLogger`.

O JSON exige envelope válido, contagem consistente, campos essenciais e
`external_id` único. O ICS exige um `VEVENT` e um UID único por jogo, com a
mesma contagem e os mesmos identificadores do JSON. O UID mantém a forma
`{source}-{external_id}@waterpolo`, por exemplo `FPN-...` ou `ANNP-...`.

Os comandos individuais `export fpn --format json` e `export fpn --format ics`
continuam disponíveis para diagnóstico e uso isolado.

## Cliente FPN ArenaDisplay

O cliente mantém uma ligação `httpx` reutilizável, resolve a competição pelo
domínio ArenaDisplay e normaliza os jogos. O filtro do FOCA descobre primeiro a
identidade devolvida pela API; nenhum UUID de equipa está fixo no código.

```python
from waterpolo.scraper.fpn import FPNArenaClient

with FPNArenaClient() as client:
    competition = client.get_competition("po02_25-26")
    games = client.get_games(competition.id)
    foca_games = client.get_team_games(domain="po02_25-26", team="FOCA")
```

O código de produção não depende do script de diagnóstico. Para guardar a
resposta bruta da competição e inspecionar um jogo específico:

```console
uv run python scripts/inspect_fpn_arena.py --domain po02_25-26 \\
  --game-number 21 --output data/debug/fpn_po02_game21.json
```

Também é possível selecionar diretamente com `--game-id`. O script tenta
`POST /api/game/GetFiltered/` e três variantes GET de detalhe (`GetById/{id}`,
`Get/{id}` e `/{id}`); resultados e falhas ficam registados no JSON debug.

### Localizações FPN

Quando a API não fornece um local, o conversor FPN consulta
[`fpn_venues.json`](src/waterpolo/scraper/fpn/fpn_venues.json). O ficheiro aceita
`team_venues` para piscinas habituais por equipa e `match_overrides` para jogos
específicos. Uma localização real da API tem precedência sobre overrides; um
override tem precedência sobre a piscina da equipa da casa. A configuração inicial
contém apenas FOCA → Felgueiras, confirmado pelo
[Município de Felgueiras](https://cm-felgueiras.pt/viver/desporto-e-lazer/oferta-desportiva/).
Equipas ainda não verificadas ficam sem localização até serem adicionadas ao
ficheiro. Esta resolução é exclusiva do fluxo FPN.

## Cliente ANNP

O adapter ANNP está em `src/waterpolo/scraper/annp/` e usa `httpx` para consultar
`competicoes.php` e `calendario.php`. O site não expõe uma API JSON nem um ID de
jogo no HTML público; a integração documenta e testa o identificador substituto
estável usado nesse caso. Consulte [docs/annp.md](docs/annp.md) para endpoints,
mapeamento de estados, seleção de escalão e limitações.

A época lógica é independente do diretório da fonte. Para `2627`, o cliente tenta
primeiro `provas2627` e usa temporariamente `provas2526` como fallback conhecido,
validando sempre as datas como 2026/27.

## Roadmap

1. Modelo `Match` e contrato de output.
2. Fetch de HTML.
3. Parser de HTML.
4. Fixtures e testes das fontes.
5. Export JSON, CSV e ICS.
6. SQLite e histórico.
7. Automatização com systemd timer ou cron.
8. Integração futura com WP Stats através do output normalizado.
