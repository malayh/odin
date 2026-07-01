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

    def create_entity(self, body: dict[str, Any], dry_run: bool = False) -> Any:
        return self._request("POST", "/graph/entities", json=body, params={"dry_run": dry_run})

    def update_entity(self, key: str, body: dict[str, Any], dry_run: bool = False) -> Any:
        return self._request(
            "PATCH", f"/graph/entities/{key}", json=body, params={"dry_run": dry_run}
        )

    def delete_entity(self, key: str, dry_run: bool = False) -> Any:
        return self._request("DELETE", f"/graph/entities/{key}", params={"dry_run": dry_run})

    def create_edge(self, body: dict[str, Any], dry_run: bool = False) -> Any:
        return self._request("POST", "/graph/edges", json=body, params={"dry_run": dry_run})

    def delete_edge(
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

    def create_objective(self, body: dict[str, Any], dry_run: bool = False) -> Any:
        return self._request("POST", "/graph/objectives", json=body, params={"dry_run": dry_run})

    def list_objectives(self) -> Any:
        return self._request("GET", "/graph/objectives")

    def get_objective(self, objective_id: str) -> Any:
        return self._request("GET", f"/graph/objectives/{objective_id}")

    def delete_objective(self, objective_id: str, dry_run: bool = False) -> Any:
        return self._request(
            "DELETE", f"/graph/objectives/{objective_id}", params={"dry_run": dry_run}
        )

    def list_documents(
        self,
        state: str | None = None,
        type_: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Any:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if state is not None:
            params["state"] = state
        if type_ is not None:
            params["doc_type"] = type_
        return self._request("GET", "/documents", params=params)

    def get_document(self, doc_id: str) -> Any:
        return self._request("GET", f"/documents/{doc_id}")

    def delete_document(self, doc_id: str, dry_run: bool = False) -> Any:
        return self._request("DELETE", f"/documents/{doc_id}", params={"dry_run": dry_run})

    def list_jobs(self, state: str | None = None, limit: int = 50, offset: int = 0) -> Any:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if state is not None:
            params["state"] = state
        return self._request("GET", "/jobs", params=params)

    def openapi(self) -> Any:
        return self._request("GET", "/openapi.json")

    def consolidate(self) -> Any:
        return self._request("POST", "/consolidate")

    def dream(self) -> Any:
        return self._request("POST", "/dream")

    def consolidate_status(self) -> Any:
        return self._request("GET", "/consolidate/status")

    def dream_status(self) -> Any:
        return self._request("GET", "/dream/status")
