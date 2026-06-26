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

    def create_org(self, name: str) -> Any:
        return self._request("POST", "/admin/orgs", json={"name": name})

    def add_member(self, org_id: str, user_id: str, role: str) -> Any:
        return self._request(
            "POST", f"/admin/orgs/{org_id}/members", json={"user_id": user_id, "role": role}
        )

    def create_token(self, user_id: str, name: str | None = None) -> Any:
        return self._request("POST", f"/admin/users/{user_id}/tokens", json={"name": name})

    def ingest(self, path: Path, key: str, scope: str) -> Any:
        with path.open("rb") as fh:
            files = {"file": (path.name, fh)}
            data = {"key": key, "scope": scope}
            return self._request("POST", "/ingest", files=files, data=data)

    def get_job(self, job_id: str) -> Any:
        return self._request("GET", f"/jobs/{job_id}")

    def search(self, query: str, scope: str | None, top_k: int) -> Any:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if scope:
            payload["scope"] = scope
        return self._request("POST", "/search", json=payload)

    def ask(self, question: str, scope: str | None, history: list[Any] | None = None) -> Any:
        payload: dict[str, Any] = {"question": question}
        if scope:
            payload["scope"] = scope
        if history:
            payload["history"] = history
        return self._request("POST", "/ask", json=payload)

    def find_entities(self, q: str) -> Any:
        return self._request("GET", "/graph/entities", params={"q": q})

    def get_entity(self, key: str) -> Any:
        return self._request("GET", f"/graph/entities/{key}")

    def entity_history(self, key: str) -> Any:
        return self._request("GET", f"/graph/entities/{key}/history")
