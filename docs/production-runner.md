# Runner de produção

O ficheiro `scripts/run_production_update.py` orquestra a publicação dos
calendários sem conter lógica de scraping. Para cada entrada chama o comando
existente `python -m waterpolo.main publish`, valida novamente os dois
artefactos, instala o JSON para consumo pelo WP Stats, executa o import e só
depois promove o snapshot interno e publica o ICS servido por HTTP.

## Configuração dos calendários

Por omissão, o runner lê `/etc/waterpolo-calendar/calendars.json`. A raiz é um
objeto com uma lista não vazia `calendars`. `calendar_id` e `ics_filename` têm
de ser nomes simples, sem componentes de path; IDs e nomes ICS duplicados são
rejeitados.

FPN:

```json
{
  "calendars": [
    {
      "source": "fpn",
      "calendar_id": "fpn_po01_26-27_foca",
      "ics_filename": "foca-seniores-a1.ics",
      "params": {
        "domain": "po01_26-27",
        "team": "FOCA"
      }
    }
  ]
}
```

ANNP:

```json
{
  "calendars": [
    {
      "source": "annp",
      "calendar_id": "annp_2627_juniores_foca",
      "ics_filename": "foca-juniores-annp.ics",
      "params": {
        "season": "2627",
        "team": "FOCA",
        "competition_id": "1"
      }
    }
  ]
}
```

As duas fontes percorrem o mesmo pipeline. Apenas os argumentos passados a
`publish` diferem. O runner não implementa parsing FPN ou ANNP.

## Ambiente e paths

O ficheiro de ambiente por omissão é
`/etc/waterpolo-calendar/wp-stats.env`. Valores já presentes no ambiente do
processo têm precedência sobre o ficheiro. São obrigatórias:

- `WP_STATS_EMAIL`
- `WP_STATS_PASSWORD`

`WP_STATS_BASE_URL` é configurável e opcional. Quando não está definida, o
runner usa o default atual de produção: `https://129.146.159.13`.

O login é feito uma vez, quando o primeiro calendário validado chega à fase de
import, através de `POST /api/v1/auth/login`. O token recebido é enviado como
Bearer token nos imports. O runner nunca desativa a validação TLS e usa timeout
explícito de 30 segundos.

Os defaults de produção são:

| Argumento | Default |
| --- | --- |
| `--config` | `/etc/waterpolo-calendar/calendars.json` |
| `--env-file` | `/etc/waterpolo-calendar/wp-stats.env` |
| `--wp-stats-calendar-dir` | `/opt/wp-stats/data/calendars` |
| `--staging-dir` | `/var/lib/waterpolo/staging` |
| `--current-dir` | `/var/lib/waterpolo/current` |
| `--public-ics-dir` | `/var/www/waterpolo-calendars` |
| `--lock-file` | `/var/lib/waterpolo/calendar-update.lock` |
| `--timeout` | `30` segundos |

Todos estes paths e o timeout podem ser substituídos por argumentos, o que
permite testes inteiramente em diretórios temporários.

## Validação e atomicidade

O JSON tem de ter raiz objeto, fonte e época esperadas, `match_count` positivo
e consistente, `matches` como lista e `external_id` únicos. Todos os jogos têm
de pertencer à fonte e à época pedidas. O ICS tem de ter envelope VCALENDAR,
um VEVENT por jogo e UIDs únicos que correspondam aos IDs do JSON.

O JSON validado é copiado para
`<wp-stats-calendar-dir>/<calendar_id>.json` através de um ficheiro temporário
no mesmo filesystem e `os.replace()`. A versão anterior fica em backup local
até o import e a publicação terminarem.

Depois de um import validado, `--current-dir` recebe o snapshot interno completo
do último processamento bem-sucedido: `<calendar_id>.json` e `<ics_filename>`.
`--public-ics-dir` tem uma responsabilidade diferente: recebe exclusivamente
`<ics_filename>`, que fica disponível em `/calendars/<ics_filename>` através do
Caddy. Nenhum JSON é copiado para este diretório público.

As promoções usam sempre um ficheiro temporário no mesmo filesystem e
`os.replace()`. Se a geração, validação ou import falhar, o snapshot interno e
o ICS público anteriores não são alterados. Uma falha de publicação pública
também faz a execução falhar, sem expor um ficheiro parcial, e restaura o
snapshot interno anterior.

O POST de import é enviado sem body para
`/api/v1/calendars/{calendar_id}/import`. A resposta tem de seguir diretamente
o contrato do WP Stats, com `calendar_id`, as contagens inteiras não negativas
`matches_found`, `created`, `updated`, `unchanged`, `mapped` e `unresolved`,
`resolution_status` e a lista `resolution_reasons`. O import só é aceite quando
o calendário corresponde ao pedido, `matches_found` corresponde ao JSON,
`created + updated + unchanged == matches_found`,
`mapped + unresolved == matches_found`, todos os jogos estão mapeados, não há
jogos por resolver e `resolution_status == "MAPPED"`.

## Concorrência e falhas

Um `fcntl.flock` não bloqueante cobre toda a execução. Se o lock já estiver
ocupado, o runner não processa calendários e termina com exit code `2`.

Os calendários são processados sequencialmente. Uma falha é isolada à entrada
afetada e as restantes continuam; no fim, qualquer falha produz exit code `1`.
Assim, uma fonte indisponível não impede calendários independentes, sem ocultar
uma execução parcialmente falhada.
