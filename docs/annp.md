# Fonte ANNP

A integração ANNP é um adapter para o mesmo pipeline usado pela FPN. Produz
`list[Match]`; os exporters JSON/ICS, validação, staging, deteção de duplicados,
publicação atómica, rollback, logging e exit codes são partilhados.

## Fonte HTTP

A página pública carrega fragmentos HTML server-side por jQuery. Não foi
encontrado um endpoint JSON público. O cliente de produção usa `httpx`, sem
browser, nestes endpoints físicos:

- `GET /provas{YYZZ}/polo/competicoes.php?opcao=1`
- `GET /provas{YYZZ}/polo/calendario.php?competicao={id}&temjogos={0|1}`

O primeiro endpoint fornece os IDs e nomes reais das competições. O segundo
fornece data, hora, local, equipas, resultado e estado em cartões HTML. A CLI
aceita o nome real com `--category` ou, preferencialmente, o ID estável com
`--competition-id`.

```console
uv run python -m waterpolo.main publish annp \
  --season 2627 \
  --team FOCA \
  --competition-id 1 \
  --json-output data/published_calendars/annp-2627-juniores-foca.json \
  --ics-output data/published_calendars/annp-2627-juniores-foca.ics
```

Cada execução seleciona exatamente uma competição, pelo que os escalões não são
misturados. O calendário completo dessa competição é obtido uma vez, o filtro
de equipa é aplicado localmente e a normalização também ocorre uma vez.

## Identidade e estados

O HTML público não expõe o ID interno do jogo. O `external_id` ANNP é portanto
um identificador substituto determinístico baseado em época, ID da competição,
equipas casa/fora e número da ocorrência entre as mesmas equipas. Não inclui
data, hora, local, resultado ou estado, mantendo-se estável quando esses campos
mudam. Uma alteração da ordem relativa de duas partidas repetidas com as mesmas
equipas e orientação é a limitação residual deste método.

Os estados observados são mapeados para a enumeração partilhada:

- `Não iniciado`, `Agendado`, `Por realizar` → `SCHEDULED`;
- `Finalizado`, `Terminado`, `Concluído` → `COMPLETED`;
- `Adiado` → `POSTPONED`;
- `Cancelado`, `Anulado` → `CANCELLED`;
- outros → `UNKNOWN`.

O UID ICS é sempre `ANNP-{external_id}@waterpolo`.

Na ANNP, `00:00` é um valor de apresentação que significa que a hora ainda não
foi definida. O adapter converte exclusivamente esse valor ANNP para
`Match.time=None`; horas reais permanecem intactas e a regra não é aplicada à
FPN. O JSON contém `"time": null` e o ICS comum produz um VEVENT de data
(`DTSTART;VALUE=DATE` e `DTEND;VALUE=DATE` no dia seguinte), preservando o mesmo
UID quando a fonte publicar posteriormente uma hora real.

## Época lógica e source path

`--season` representa a época lógica do jogo e é a única época usada no JSON,
no `external_id` e no UID. O diretório físico da ANNP é apenas routing HTTP e
nunca participa na identidade.

Para a época lógica `2627`, o cliente tenta por ordem:

1. `/provas2627/polo/`;
2. `/provas2526/polo/`, fallback conhecido enquanto a ANNP mantiver os dados
   2026/27 no diretório anterior.

Se a ANNP corrigir o diretório, os mesmos jogos mantêm `external_id` e UID. Só o
`source_url` passa a refletir o novo path realmente usado.

## Proteção de época

Uma época lógica `YYZZ` corresponde ao intervalo inclusivo de 1 de julho do
primeiro ano a 30 de junho do segundo. Para `2627`, apenas datas entre
`2026-07-01` e `2027-06-30` são aceites, independentemente do source path. Datas
fora desse intervalo são rejeitadas como resposta inválida.
