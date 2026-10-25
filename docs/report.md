# Relatório HTML/PDF de calendários

O comando independente `waterpolo.report` combina calendários que cumpram o
contrato JSON público do projeto. Este fluxo apenas lê ficheiros locais: não
executa scrapers nem faz pedidos de rede.

```console
uv run python -m waterpolo.report \
  --calendar "Seniores=data/exports/fpn_po01_26-27_foca.json" \
  --calendar "Juniores=data/exports/annp_2627_juniores_foca.json" \
  --calendar "Juvenis=data/exports/annp_2627_juvenis_foca.json" \
  --calendar "Infantis=data/exports/annp_2627_infantis_foca.json" \
  --schedule "Benjamins=data/exports/annp_2627_benjamins_schedule.json" \
  --html data/reports/calendario-foca-2627.html \
  --pdf data/reports/calendario-foca-2627.pdf
```

`--calendar` usa o formato `LABEL=PATH` e pode ser repetido. `--schedule`
aceita o JSON próprio das ações de Benjamins, também no formato `LABEL=PATH`.
O relatório ordena jogos e ações cronologicamente, com horas indefinidas após
horas conhecidas do mesmo dia. Quando há schedules, a tabela apresenta
`Data | Escalão | Jogo | Hora | Local`; nas linhas de Benjamins, a coluna
`Jogo` apresenta apenas `-`, sem equipas fictícias. Sem schedules, o layout atual dos
jogos é preservado. Hora ou local indefinido continua a aparecer como
`Por definir`.

É obrigatório
indicar pelo menos um calendário e um output. `--html` e `--pdf` podem ser usados
em conjunto ou separadamente. Quando ambos são pedidos, o PDF é convertido a
partir do mesmo ficheiro HTML acabado de escrever.

O HTML é standalone: inclui o CSS versionado e o logótipo local do FOCA como
data URI.

## Preparar a conversão PDF

O PDF é gerado por WeasyPrint 70.0 dentro de uma imagem Docker própria. Esta
imagem tem de ser construída uma vez:

```console
docker build \
  --tag waterpolo-report-weasyprint:70.0 \
  --file docker/report.Dockerfile \
  docker
```

A construção inicial descarrega a imagem Python, Pango e WeasyPrint. A execução
normal do relatório usa apenas a imagem local, com `--pull=never`, rede desativada,
filesystem read-only e apenas os mounts do HTML de entrada e diretório PDF de
saída. Gerar apenas HTML não requer Docker.
