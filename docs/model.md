# Modelo `Match`

`Match` representa um jogo de polo aquático normalizado. O modelo isola os
consumidores das diferenças entre fontes e é independente da aplicação WP Stats.

## Campos

| Grupo | Campo | Tipo | Obrigatório | Notas |
| --- | --- | --- | --- | --- |
| Identificação | `external_id` | `str` | Sim | Identificador global, por exemplo `fpn-123` |
| Identificação | `source` | `MatchSource` | Sim | Fonte conhecida pelo parser |
| Identificação | `source_url` | `str \| None` | Não | URL original do jogo |
| Classificação | `season` | `str` | Sim | Pode ser derivada pelo scraper |
| Classificação | `category` | `MatchCategory` | Sim | Escalão normalizado |
| Classificação | `competition` | `str` | Sim | Texto livre para permitir novas competições |
| Equipas | `home` | `str` | Sim | Equipa da casa |
| Equipas | `away` | `str` | Sim | Equipa visitante |
| Horário | `date` | `date` | Sim | Data do jogo |
| Horário | `time` | `time` | Sim | Hora do jogo |
| Horário | `location` | `str \| None` | Não | Local do jogo; pode faltar na fonte |
| Resultado | `score_home` | `int \| None` | Não | Resultado da equipa da casa |
| Resultado | `score_away` | `int \| None` | Não | Resultado da equipa visitante |
| Estado | `status` | `MatchStatus` | Não | Por omissão, `SCHEDULED` |
| Auditoria | `raw` | `dict[str, Any] \| None` | Não | Dados originais para diagnóstico |

## Enums

- `MatchSource`: `FPN`, `ANNP`.
- `MatchCategory`: `U12`, `U14`, `U16`, `U18`, `SENIOR`, `UNKNOWN`.
- `MatchStatus`: `SCHEDULED`, `COMPLETED`, `POSTPONED`, `CANCELLED`, `UNKNOWN`.

`UNKNOWN` permite processar valores ainda não mapeados sem alargar prematuramente
os enums.

## Decisões e validações

- `competition` é texto livre porque as competições podem variar e crescer.
- `external_id` identifica globalmente a fonte e o registo; a convenção inicial é
  `<fonte>-<id-da-fonte>`.
- A fonte é fornecida pelo parser ou função e não tem de existir no HTML.
- A época pode ser derivada pelo scraper, mas é obrigatória no modelo.
- Data e hora são obrigatórias nesta fase. O local é opcional porque a API
  ArenaDisplay pode devolvê-lo como `null` ou omiti-lo.
- Quando o local não é fornecido pela fonte, mantém-se `None`; não é inventado
  um valor substituto.
- Campos textuais obrigatórios rejeitam texto vazio ou apenas espaços e removem
  espaços exteriores.
- Scores não podem ser negativos e têm de estar ambos ausentes ou ambos presentes.
