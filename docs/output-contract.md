# Contrato de output JSON

O exportador devolve um dicionário compatível com `json.dumps`. O envelope contém:

| Campo | Tipo | Descrição |
| --- | --- | --- |
| `generated_at` | `str` | Timestamp UTC ISO 8601, com sufixo `Z` |
| `source` | `str \| null` | Fonte descrita pelo exportador |
| `match_count` | `int` | Número de jogos em `matches` |
| `matches` | `array` | Jogos normalizados |

Cada jogo exporta os campos públicos do modelo: `external_id`, `source`,
`source_url`, `season`, `category`, `competition`, `home`, `away`, `date`, `time`,
`location`, `score_home`, `score_away` e `status`. Enums, datas e horas são
serializados como strings.

## Exemplo

```json
{
  "generated_at": "2026-09-30T15:00:00Z",
  "source": "FPN",
  "match_count": 1,
  "matches": [
    {
      "external_id": "fpn-123",
      "source": "FPN",
      "source_url": "https://example.test/fpn/123",
      "season": "2026/27",
      "category": "U16",
      "competition": "Campeonato Nacional",
      "home": "FOCA",
      "away": "Vitória SC",
      "date": "2026-10-04",
      "time": "15:00:00",
      "location": "Piscina Municipal",
      "score_home": null,
      "score_away": null,
      "status": "SCHEDULED"
    }
  ]
}
```

O campo de auditoria `raw` não é exportado por defeito. Pode ser incluído
explicitamente com `include_raw=True` para diagnóstico.

A aplicação WP Stats deverá consumir este contrato normalizado, e não a estrutura
interna nem os detalhes de scraping deste projeto.
