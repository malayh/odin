"""HTTP client (httpx) that talks to the Odin API; the CLI is a thin wrapper over it."""

from pathlib import Path
from typing import Any

import httpx

from odin_cli.config import Config


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message", body))
        if "detail" in body:
            return str(body["detail"])
    return str(body)


class Client:
    def __init__(self, config: Config) -> None:
        headers = {}
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        self._http = httpx.Client(base_url=config.server_url, headers=headers, timeout=300.0)

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.RequestError as e:
            raise ApiError(0, f"cannot reach Odin server at {self._http.base_url}: {e}") from e
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def health(self) -> Any:
        return self._request("GET", "/health")

    def whoami(self) -> Any:
        return self._request("GET", "/auth/whoami")

    def create_user(self, email: str, display_name: str | None = None) -> Any:
        return self._request(
            "POST", "/admin/users", json={"email": email, "display_name": display_name}
        )

    def create_token(self, user_id: str, name: str | None = None) -> Any:
        return self._request("POST", f"/admin/users/{user_id}/tokens", json={"name": name})

    def ingest(self, path: Path, key: str) -> Any:
        with path.open("rb") as fh:
            files = {"file": (path.name, fh)}
            data = {"key": key}
            return self._request("POST", "/ingest", files=files, data=data)

    def get_job(self, job_id: str) -> Any:
        return self._request("GET", f"/jobs/{job_id}")

    def search(self, query: str, top_k: int) -> Any:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        return self._request("POST", "/search", json=payload)

    def ask(self, question: str, history: list[Any] | None = None) -> Any:
        payload: dict[str, Any] = {"question": question}
        if history:
            payload["history"] = history
        return self._request("POST", "/ask", json=payload)

    def find_entities(self, q: str) -> Any:
        return self._request("GET", "/graph/entities", params={"q": q})

    def list_entities(
        self, type_: str | None = None, limit: int = 50, offset: int = 0
    ) -> Any:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if type_ is not None:
            params["type"] = type_
        return self._request("GET", "/graph/entities", params=params)

    def get_entity(self, key: str, depth: int = 1) -> Any:
        return self._request("GET", f"/graph/entities/{key}", params={"depth": depth})

    def entity_history(self, key: str) -> Any:
        return self._request("GET", f"/graph/entities/{key}/history")

    def add_entity(self, type_: str, name: str, dry_run: bool = False) -> Any:
        return self._request(
            "POST",
            "/graph/entities",
            json={"type": type_, "name": name},
            params={"dry_run": dry_run},
        )

    def rename_entity(self, key: str, new_name: str, dry_run: bool = False) -> Any:
        return self._request(
            "PATCH",
            f"/graph/entities/{key}",
            json={"new_name": new_name},
            params={"dry_run": dry_run},
        )

    def drop_entity(self, key: str, dry_run: bool = False) -> Any:
        return self._request(
            "DELETE", f"/graph/entities/{key}", params={"dry_run": dry_run}
        )

    def add_edge(
        self, subject_key: str, predicate: str, object_key: str, dry_run: bool = False
    ) -> Any:
        return self._request(
            "POST",
            "/graph/edges",
            json={"subject_key": subject_key, "predicate": predicate, "object_key": object_key},
            params={"dry_run": dry_run},
        )

    def remove_edge(
        self, subject_key: str, predicate: str, object_key: str, dry_run: bool = False
    ) -> Any:
        return self._request(
            "DELETE",
            "/graph/edges",
            params={
                "subject_key": subject_key,
                "predicate": predicate,
                "object_key": object_key,
                "dry_run": dry_run,
            },
        )

    def add_objective(self, text: str, dry_run: bool = False) -> Any:
        return self._request(
            "POST", "/graph/objectives", json={"text": text}, params={"dry_run": dry_run}
        )

    def list_objectives(self) -> Any:
        return self._request("GET", "/graph/objectives")

    def drop_objective(self, objective_id: str, dry_run: bool = False) -> Any:
        return self._request(
            "DELETE", f"/graph/objectives/{objective_id}", params={"dry_run": dry_run}
        )
