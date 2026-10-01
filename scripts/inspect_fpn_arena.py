"""Save raw ArenaDisplay competition and selected-game diagnostics.

Example:
    uv run python scripts/inspect_fpn_arena.py --domain po02_25-26 \
        --game-number 21 --output data/debug/fpn_po02_game21.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

API_BASE_URL = "https://api-web.arenadisplay.live"
DETAIL_PATHS = (
    "/api/game/GetById/{game_id}",
    "/api/game/Get/{game_id}",
    "/api/game/{game_id}",
)
LOCATION_PATHS = (
    "/api/location/{location_id}",
    "/api/location/Get/{location_id}",
    "/api/location/GetById/{location_id}",
    "/api/locations/{location_id}",
    "/api/venue/{location_id}",
    "/api/venue/Get/{location_id}",
    "/api/venue/GetById/{location_id}",
)
LOCATION_FILTERED_PATHS = (
    "/api/location/GetFiltered/",
    "/api/locations/GetFiltered/",
    "/api/venue/GetFiltered/",
    "/api/venues/GetFiltered/",
)
MAX_LOCATION_RESPONSE_BYTES = 50_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    lookup = parser.add_mutually_exclusive_group(required=True)
    lookup.add_argument("--game-id")
    lookup.add_argument("--game-number", type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def find_game(
    competition_raw: dict[str, Any], *, game_id: str | None, game_number: int | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    entity = competition_raw.get("entity")
    if not isinstance(entity, dict):
        raise TypeError("GetByDomain não devolveu um objeto entity")

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    phases = entity.get("phases", [])
    if not isinstance(phases, list):
        raise TypeError("entity.phases não é uma lista")
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        games = phase.get("games", [])
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            if (game_id is not None and str(game.get("id")) == game_id) or (
                game_number is not None
                and str(game.get("gameNumber")) == str(game_number)
            ):
                candidates.append((phase, game))

    if not candidates:
        target = f"id {game_id}" if game_id is not None else f"número {game_number}"
        raise ValueError(f"Jogo com {target} não encontrado em entity.phases[].games[]")
    if game_number is not None and len(candidates) > 1:
        descriptions = [
            {
                "id": game.get("id"),
                "gameNumber": game.get("gameNumber"),
                "phaseId": phase.get("id"),
                "phaseName": phase.get("name"),
            }
            for phase, game in candidates
        ]
        raise ValueError(
            f"gameNumber {game_number} é ambíguo; candidatos: "
            f"{json.dumps(descriptions, ensure_ascii=False)}"
        )
    return candidates[0]


def decode_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def attempt_detail(client: httpx.Client, path: str) -> dict[str, Any]:
    endpoint = f"{API_BASE_URL}{path}"
    try:
        response = client.get(path)
        result: dict[str, Any] = {
            "endpoint": endpoint,
            "status_code": response.status_code,
            "ok": response.is_success,
        }
        if response.is_success:
            result["response"] = decode_response(response)
        else:
            result["error"] = response.text[:2000] or response.reason_phrase
        return result
    except httpx.HTTPError as exc:
        return {"endpoint": endpoint, "status_code": None, "ok": False, "error": str(exc)}


def response_keys(value: Any) -> list[str] | None:
    if isinstance(value, dict):
        return sorted(str(key) for key in value)
    if isinstance(value, list):
        keys = {
            str(key)
            for item in value
            if isinstance(item, dict)
            for key in item
        }
        return sorted(keys)
    return None


def attempt_location_post(
    client: httpx.Client, path: str, payload: dict[str, Any]
) -> dict[str, Any]:
    endpoint = f"POST {API_BASE_URL}{path}"
    result: dict[str, Any] = {
        "method": "POST",
        "endpoint": endpoint,
        "payload": payload,
    }
    try:
        response = client.post(path, json=payload)
        result.update(status_code=response.status_code, ok=response.is_success)
        if response.is_success:
            try:
                body = response.json()
            except ValueError:
                result["error"] = "Resposta de sucesso não contém JSON válido"
                result["response_summary"] = response.text[:1000]
            else:
                result["response_keys"] = response_keys(body)
                result["response"] = body
        else:
            result["error"] = response.text[:2000] or response.reason_phrase
        return result
    except httpx.HTTPError as exc:
        result.update(status_code=None, ok=False, error=str(exc))
        return result


def walk_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def location_name(value: dict[str, Any]) -> str | None:
    for key in ("name", "displayName", "locationName", "description"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def finish_location_attempts(
    client: httpx.Client, location_id: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    payloads = [
        {"id": location_id},
        {"locationId": location_id},
        {"ids": [location_id]},
        {
            "filterCollections": [
                {
                    "filterOperation": 0,
                    "filterExpression": 0,
                    "propertyName": "Id",
                    "value": location_id,
                }
            ],
            "orderCollection": [],
        },
        {
            "filterCollections": [
                {
                    "filterOperation": 0,
                    "filterExpression": 0,
                    "propertyName": "LocationId",
                    "value": location_id,
                }
            ],
            "orderCollection": [],
        },
    ]
    for path in LOCATION_FILTERED_PATHS:
        for payload in payloads:
            attempts.append(attempt_location_post(client, path, payload))

    matching_id_count = 0
    matching_location_id_count = 0
    resolved_name: str | None = None
    source_endpoint: str | None = None
    for attempt in attempts:
        body = attempt.get("response")
        for item in walk_objects(body):
            id_matches = str(item.get("id")) == str(location_id)
            location_id_matches = str(item.get("locationId")) == str(location_id)
            if id_matches:
                matching_id_count += 1
            if location_id_matches:
                matching_location_id_count += 1
            name = location_name(item) if id_matches or location_id_matches else None
            if name is not None and resolved_name is None:
                resolved_name = name
                source_endpoint = attempt["endpoint"]

    for attempt in attempts:
        body = attempt.get("response")
        if body is None:
            continue
        serialized = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_LOCATION_RESPONSE_BYTES:
            del attempt["response"]
            attempt["response_truncated"] = True

    summary = {
        "location_id": location_id,
        "resolved": resolved_name is not None,
        "name": resolved_name,
        "source_endpoint": source_endpoint,
        "matching_id_count": matching_id_count,
        "matching_location_id_count": matching_location_id_count,
    }
    return attempts, summary


def inspect(domain: str, game_id: str | None, game_number: int | None) -> dict[str, Any]:
    with httpx.Client(base_url=API_BASE_URL, timeout=20.0) as client:
        competition_response = client.get(f"/api/competition/GetByDomain/{domain}")
        competition_response.raise_for_status()
        competition_raw = competition_response.json()
        phase, base_game = find_game(
            competition_raw, game_id=game_id, game_number=game_number
        )

        entity = competition_raw["entity"]
        game_key = str(base_game["id"])
        competition_id = str(entity.get("id", ""))
        filtered_game: Any = None
        filtered_path = "/api/game/GetFiltered/"
        filtered_body = {
            "filterCollections": [
                {
                    "filterOperation": 0,
                    "filterExpression": 0,
                    "propertyName": "CompetitionId",
                    "value": competition_id,
                }
            ],
            "orderCollection": [
                {"propertyName": "GameDate", "orderType": 0},
                {"propertyName": "GameNumber", "orderType": 0},
            ],
        }
        detail_attempts: list[dict[str, Any]] = []
        try:
            filtered_response = client.post(filtered_path, json=filtered_body)
            if filtered_response.is_success:
                filtered_payload = filtered_response.json()
                filtered_entity = filtered_payload.get("entity", [])
                if isinstance(filtered_entity, list):
                    filtered_game = next(
                        (game for game in filtered_entity
                         if isinstance(game, dict) and str(game.get("id")) == game_key),
                        None,
                    )
                detail_attempts.append(
                    {
                        "endpoint": f"POST {API_BASE_URL}{filtered_path}",
                        "status_code": filtered_response.status_code,
                        "ok": True,
                        "response": filtered_payload,
                    }
                )
            else:
                detail_attempts.append(
                    {
                        "endpoint": f"POST {API_BASE_URL}{filtered_path}",
                        "status_code": filtered_response.status_code,
                        "ok": False,
                        "error": filtered_response.text[:2000]
                        or filtered_response.reason_phrase,
                    }
                )
        except (httpx.HTTPError, ValueError) as exc:
            detail_attempts.append(
                {
                    "endpoint": f"POST {API_BASE_URL}{filtered_path}",
                    "status_code": None,
                    "ok": False,
                    "error": str(exc),
                }
            )

        for path_template in DETAIL_PATHS:
            detail_attempts.append(
                attempt_detail(client, path_template.format(game_id=game_key))
            )

        game_versions = [base_game]
        if isinstance(filtered_game, dict):
            game_versions.insert(0, filtered_game)
        game_versions.extend(
            attempt["response"]
            for attempt in detail_attempts
            if attempt.get("ok") and isinstance(attempt.get("response"), dict)
        )
        location_id = next(
            (
                version.get("locationId")
                for version in game_versions
                if version.get("locationId") is not None
            ),
            None,
        )
        location = next(
            (version.get("location") for version in game_versions if "location" in version),
            None,
        )
        location_attempts: list[dict[str, Any]] = []
        location_summary: dict[str, Any] = {
            "location_id": location_id,
            "resolved": False,
            "name": None,
            "source_endpoint": None,
            "matching_id_count": 0,
            "matching_location_id_count": 0,
        }
        if location_id is not None:
            for path_template in LOCATION_PATHS:
                location_attempts.append(
                    attempt_detail(
                        client,
                        path_template.format(location_id=location_id),
                    )
                )
            post_attempts, location_summary = finish_location_attempts(
                client, location_id
            )
            location_attempts.extend(post_attempts)

            local_sources = [
                (f"GET {API_BASE_URL}/api/competition/GetByDomain/{domain}", competition_raw),
                ("base_game", base_game),
                ("filtered_game", filtered_game),
            ]
            local_sources.extend(
                (str(attempt.get("endpoint", "detail_attempt")), attempt["response"])
                for attempt in detail_attempts
                if attempt.get("ok") and "response" in attempt
            )
            local_sources.extend(
                (str(attempt.get("endpoint", "location_attempt")), attempt["response"])
                for attempt in location_attempts
                if attempt.get("ok") and "response" in attempt
            )
            location_endpoint_sources = {
                str(attempt.get("endpoint"))
                for attempt in location_attempts
                if attempt.get("ok") and "response" in attempt
            }
            location_summary["matching_id_count"] = 0
            location_summary["matching_location_id_count"] = 0
            for source_endpoint, source_value in local_sources:
                for item in walk_objects(source_value):
                    id_matches = str(item.get("id")) == str(location_id)
                    location_id_matches = (
                        str(item.get("locationId")) == str(location_id)
                    )
                    if id_matches:
                        location_summary["matching_id_count"] += 1
                    if location_id_matches:
                        location_summary["matching_location_id_count"] += 1
                    can_resolve = id_matches or (
                        location_id_matches and source_endpoint in location_endpoint_sources
                    )
                    name = location_name(item) if can_resolve else None
                    if name is not None and not location_summary["resolved"]:
                        location_summary.update(
                            resolved=True,
                            name=name,
                            source_endpoint=source_endpoint,
                        )

    return {
        "domain": domain,
        "game_lookup": {"game_id": game_key, "game_number": base_game.get("gameNumber")},
        "competition_summary": {
            "id": entity.get("id"),
            "displayName": entity.get("displayName"),
            "category": entity.get("category"),
            "namespace": entity.get("namespace"),
        },
        "phase": {"id": phase.get("id"), "name": phase.get("name")},
        "competition_id": entity.get("id"),
        "game_id": game_key,
        "game_number": base_game.get("gameNumber"),
        "locationId": location_id,
        "location": location,
        "competition_raw": competition_raw,
        "base_game": base_game,
        "filtered_game": filtered_game,
        "detail_attempts": detail_attempts,
        "location_attempts": location_attempts,
        "location_summary": location_summary,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        diagnostic = inspect(args.domain, args.game_id, args.game_number)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"Erro ao inspecionar API ArenaDisplay: {exc}", file=sys.stderr)
        return 1
    print(f"Diagnóstico guardado em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
