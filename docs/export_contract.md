# Contrato JSON para consumidores externos

O JSON é a interface pública entre este scraper e qualquer aplicação que consuma
os calendários. A aplicação deve consumir apenas este contrato: não deve chamar a
FPN nem depender da estrutura da API, de categorias brutas ou de detalhes do
scraper. Os exporters recebem `list[Match]`; uma futura fonte ANNP deverá produzir
o mesmo modelo e este mesmo JSON.

## Gerar

```console
uv run python -m waterpolo.main export fpn \
  --domain po01_26-27 \
  --team FOCA \
  --format json \
  --output data/exports/fpn_po01_26-27_foca.json
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

`match_count` corresponde ao tamanho de `matches`. Datas e horas são strings ISO
(`YYYY-MM-DD` e `HH:MM:SS`). `generated_at` é ISO 8601 UTC terminado em `Z`.
Para FPN, `season` contém o identificador da época da app (`SYYZZ`), extraído do
domain técnico: por exemplo `po01_26-27` resulta em `S2627`. O domain continua a
ser usado para consultar a FPN e não é copiado para `Match.season`.
`source_url` e `location` podem ser `null`; o local é resolvido quando os dados
disponíveis permitem fazê-lo. Os dois scores são `null` enquanto não há resultado
e são preenchidos em conjunto quando existe resultado.

## Campos e valores

Cada jogo inclui `external_id`, `source`, `source_url`, `season`, `category`,
`competition`, `home`, `away`, `date`, `time`, `location`, `score_home`,
`score_away` e `status`. O campo interno de auditoria `raw` não é exportado.

As categorias legíveis normalizadas incluem `Seniores`, `Juniores`, `Juvenis`,
`Infantis` e `Unknown`. O modelo também admite os rótulos de escalão `U12`, `U14`,
`U16` e `U18`; consumidores devem aceitar estes valores para manter compatibilidade
com todos os jogos normalizados. Categorias brutas recebidas da API não fazem
parte deste contrato.

`status` é serializado a partir do estado normalizado. Os valores atualmente
previstos neste contrato de calendário são `SCHEDULED` e `COMPLETED`.

O envelope atualmente identifica a fonte de cada export (`FPN`). A arquitetura
permite que exporters comuns aceitem qualquer lista de `Match`; uma fonte futura
deve usar `ANNP` sem alterar a estrutura dos objetos.
