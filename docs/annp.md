# Fonte ANNP

A integração ANNP é um adapter para o modelo `Match` partilhado. A CLI, o
production runner e os exporters JSON/ICS continuam a usar o mesmo contrato.

## Plataforma atual

A época lógica `2627` corresponde a `/polo/20262027/`. A resolução é genérica:
`2526 → 20252026`, `2627 → 20262027`, `2728 → 20272028`.

O cliente consulta apenas:

- `GET /polo/{YYYYYYYY}/calendario`, para descobrir os IDs e nomes;
- `GET /polo/{YYYYYYYY}/calendario/{competition_id}`, para os jogos.

Na consulta de 25 de outubro de 2026, a navegação publicou:

| ID | Competição | Categoria | Género |
| --- | --- | --- | --- |
| 1 | Juniores Masculinos | Juniores | Masculino |
| 2 | Juvenis Masculinos | Juvenis | Masculino |
| 3 | Infantis Mistos | Infantis | Misto |
| 4 | Cadetes Mistos | Cadetes | Misto |
| 7 | Benjamins Mistos | Benjamins | Misto |

A página inicial liga a Calendário, Resultados e Classificações. O calendário é
HTML renderizado no servidor. O JavaScript faz navegação progressiva por
`?formato=parcial`, que devolve o mesmo painel HTML. Não foi observada uma API
JSON. Os cartões e o HTML parcial não publicam um ID canónico de jogo, jornada
ou fase. A tabela de Resultados publica a jornada e um número não único.

O parser confirma que o link ativo em `nav.competicoes` tem o ID, URL e nome
esperados. Lê `section.seccao-calendario`, os grupos `.dia` e
`.dia-titulo`, e cada `article.cartao`. Em cada cartão usa
`.cartao-topo .hora`, `.cartao-topo .local`, `.equipas > .equipa`,
`.equipas > .resultado` e `.estado`. Datas explícitas incluem o ano; a
validação restringe os jogos a julho–junho da época solicitada.

O único marcador de hora indefinida observado foi `----`. Hora ausente ou
vazia também resulta em `time=None`; valores numéricos `H:M`, `H:MM`,
`HH:M` e `HH:MM` são normalizados pelo modelo. `00:00`, se publicado, é
interpretado como meia-noite real. O local `-----` torna-se `location=None`.
O score `:` significa ausência de resultado; `0 : 0` é válido quando o
estado é `Finalizado`, como observado em Cadetes.

Em Benjamins, há cartões ainda publicados com `-----` em ambas as equipas.
São incompletos e o parser rejeita-os explicitamente. A página de Resultados
inclui colunas `Jorn.` e `N.º`, mas os cartões de Calendário não as incluem.
O `N.º` repete-se em jogos distintos de Juniores e Cadetes; em Benjamins todos
os jogos têm `0`. Não serve como identificador canónico único.

Os estados observados são `Agendado → SCHEDULED` e
`Finalizado → COMPLETED`. Um estado novo, score incompatível, cartão incompleto,
HTML inesperado, HTTP 404/5xx ou erro de rede faz a execução falhar.

## CLI e contrato

```console
uv run python -m waterpolo.main publish annp \
  --season 2627 \
  --team FOCA \
  --competition-id 1 \
  --json-output /tmp/juniores.json \
  --ics-output /tmp/juniores.ics
```

O filtro de equipa compara nomes completos após normalização de maiúsculas,
acentos e espaços. O resultado é convertido em `list[Match]`. O JSON mantém os
campos e tipos do modelo comum; uma hora ausente é `null`. O exporter ICS comum
gera nesse caso um VEVENT de data inteira.

Sem ID canónico público, `external_id` usa o algoritmo existente: época lógica,
ID da competição, nomes de casa/fora normalizados e número da ocorrência para
essa orientação. Data, hora, local, score e estado não entram na identidade.
O UID ICS continua a ser `ANNP-{external_id}@waterpolo`. Se a ordem relativa
de dois jogos com as mesmas equipas e orientação mudar, os números de ocorrência
podem mudar de associação; a plataforma não fornece um identificador para
resolver esse risco sem rever o contrato.

## Ações de Benjamins

A competição 7 publica uma sequência de ações com equipas `-----`. Estes
cartões não geram `Match` e não entram no import de calendários do WP Stats.
O comando separado lê a página atual, confirma a competição e gera
`BenjaminsScheduleEntry`:

```console
uv run python -m waterpolo.main publish annp-schedule \
  --season 2627 \
  --competition-id 7 \
  --json-output /tmp/benjamins.json \
  --ics-output /tmp/benjamins.ics
```

`--ics-output` é opcional. O JSON contém `source`, `season`,
`competition_id`, `competition_name`, `entry_count` e `entries`. Cada
entrada contém apenas `external_id`, `date`, `time` e `venue`; hora e
local ausentes são `null`. A hora é serializada como `HH:MM`. O ICS usa
`SUMMARY:Ação de Benjamins`, omite `LOCATION` quando não há local e cria um
evento de data inteira quando não há hora.

Não há ID canónico único na página pública. A identidade de ação é
`{season}-7-{YYYYMMDD}-{occurrence}`, com a ocorrência contada por data na
ordem dos cartões. Alterações de hora ou local mantêm o ID; uma mudança de data
cria outro ID. A troca de ordem entre ações da mesma data pode trocar os seus
números de ocorrência.
