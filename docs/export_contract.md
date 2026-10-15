# Contrato JSON para consumidores externos

O JSON é a interface pública entre este scraper e qualquer aplicação que consuma
os calendários. A aplicação deve consumir apenas este contrato: não deve chamar a
FPN/ANNP nem depender da estrutura das fontes, de categorias brutas ou de detalhes
do scraper. Os exporters recebem `list[Match]`; FPN e ANNP produzem o mesmo modelo
e este mesmo JSON.

## Gerar

Para gerar JSON e ICS a partir de uma única recolha:

```console
uv run python -m waterpolo.main publish fpn \
  --domain po01_26-27 \
  --team FOCA \
  --json-output data/published_calendars/fpn_po01_26-27_foca.json \
  --ics-output data/published_calendars/foca-seniores-a1.ics
```

O comando individual `export fpn --format json` continua disponível quando só
é necessário o JSON. O fluxo de produção rejeita uma resposta sem jogos e só
substitui os dois outputs depois de validar ambos.

ANNP usa o mesmo fluxo:

```console
uv run python -m waterpolo.main publish annp \
  --season 2627 \
  --team FOCA \
  --competition-id 1 \
  --json-output data/published_calendars/annp-2627-juniores-foca.json \
  --ics-output data/published_calendars/annp-2627-juniores-foca.ics
```

O envelope contém a hora UTC de geração, a fonte, a contagem e a lista de jogos:

```json
{
  "generated_at": "2026-10-02T12:00:00Z",
  "source": "FPN",
  "match_count": 1,
  "matches": [
    {
      "external_id": "12345",
      "source": "FPN",
      "source_url": null,
      "season": "S2627",
      "category": "Seniores",
      "competition": "Campeonato ...",
      "home": "FOCA",
      "away": "Equipa adversária",
      "date": "2026-10-04",
      "time": "15:00:00",
      "location": "Felgueiras",
      "score_home": null,
      "score_away": null,
      "status": "SCHEDULED"
    }
  ]
}
```

`match_count` corresponde ao tamanho de `matches`. Datas e horas conhecidas são
strings ISO (`YYYY-MM-DD` e `HH:MM:SS`); `time` é `null` quando a data é conhecida
mas a hora ainda não foi definida. `generated_at` é ISO 8601 UTC terminado em `Z`.
Para FPN, `season` contém o identificador da época da app (`SYYZZ`), extraído do
domain técnico: por exemplo `po01_26-27` resulta em `S2627`. O domain continua a
ser usado para consultar a FPN e não é copiado para `Match.season`.
`source_url`, `time` e `location` podem ser `null`; o local é resolvido quando os
dados disponíveis permitem fazê-lo. Os dois scores são `null` enquanto não há
resultado e são preenchidos em conjunto quando existe resultado.

## Campos e valores

Cada jogo inclui `external_id`, `source`, `source_url`, `season`, `category`,
`competition`, `home`, `away`, `date`, `time`, `location`, `score_home`,
`score_away` e `status`. O campo interno de auditoria `raw` não é exportado.

As categorias canónicas são `Seniores`, `Sub-18`, `Sub-16`, `Sub-14`, `Sub-12`
e `Unknown`. A normalização comum a todas as fontes converte `Juniores` em
`Sub-18`, `Juvenis` em `Sub-16`, `Infantis` em `Sub-14` e `Cadetes` em `Sub-12`;
`Seniores` permanece `Seniores`. Categorias brutas recebidas da API não fazem
parte deste contrato. O texto de `competition` é preservado sem alterações.

`status` é serializado a partir do estado normalizado. Os valores suportados são
`SCHEDULED`, `COMPLETED`, `POSTPONED`, `CANCELLED` e `UNKNOWN`. Para o FPN, os
rótulos textuais correspondentes são mapeados explicitamente. Os valores
numéricos `"1"` e `"2"` foram observados nos payloads existentes, mas não têm
semântica documentada neste repositório; continuam a usar o fallback histórico
de resultado/data. Outros valores não reconhecidos resultam em `UNKNOWN`, sem
transformar estados de cancelamento ou adiamento em `SCHEDULED`.

O envelope identifica a fonte de cada export (`FPN` ou `ANNP`). Os exporters
comuns aceitam qualquer lista de `Match` sem alterar a estrutura dos objetos.
