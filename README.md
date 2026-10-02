# Water Polo Calendar Scraper

Projeto Python independente para recolher calendários de polo aquático de fontes
como FPN e ANNP, normalizar jogos e produzir outputs estáveis. Este repositório é
separado da aplicação WP Stats e não depende dela.

O projeto define um modelo e um contrato JSON normalizados. A integração FPN usa
diretamente a API pública do ArenaDisplay, sem automação de browser, e não integra
com serviços externos da aplicação WP Stats.

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

## Publicar calendários ICS num servidor

O script `scripts/update_calendars.sh` gera calendários ICS para publicação. Por
omissão grava em `data/published_calendars`; no servidor configure
`CALENDAR_OUTPUT_DIR=/var/www/waterpolo-calendars`. O script escreve primeiro um
ficheiro temporário e move-o para o nome final após um export bem-sucedido.

Sirva cada ficheiro no mesmo URL ao longo do tempo. Os utilizadores devem
subscrever esse URL como calendário, em vez de importar o ficheiro manualmente;
assim a aplicação de calendário pode procurar atualizações no URL fixo. Um
servidor pode servir por IP público, sem domínio, por exemplo:

```text
http://<IP_PUBLICO>/calendars/foca-seniores-a1.ics
```

Exemplo de configuração Nginx:

```nginx
location /calendars/ {
    alias /var/www/waterpolo-calendars/;
    types {
        text/calendar ics;
    }
    default_type text/calendar;
    add_header Cache-Control "public, max-age=300";
}
```

Exemplo de cron para atualizar de seis em seis horas:

```cron
0 */6 * * * /opt/waterpolo/scripts/update_calendars.sh >> /var/log/waterpolo-calendar.log 2>&1
```

O URL permanece fixo, mas as alterações não aparecem instantaneamente: dependem
da frequência de atualização da aplicação de calendário. O UID estável ajuda a
atualizar os eventos existentes. O `SEQUENCE` fica em zero enquanto não existir
histórico para comparar exports.

Localmente, pode escolher outro destino:

```console
CALENDAR_OUTPUT_DIR=data/published_calendars ./scripts/update_calendars.sh
```

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

## Roadmap

1. Modelo `Match` e contrato de output.
2. Fetch de HTML.
3. Parser de HTML.
4. Fixtures e testes das fontes.
5. Export JSON, CSV e ICS.
6. SQLite e histórico.
7. Automatização com systemd timer ou cron.
8. Integração futura com WP Stats através do output normalizado.
