"""Docker sandbox supervisor (Docker SDK). Sandboxes are network-isolated by default."""
from __future__ import annotations

from typing import Iterator

import docker
from docker.errors import DockerException, NotFound

LABEL = "closed-claw.sandbox"


class DockerManager:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def available(self) -> bool:
        try:
            return bool(self.client.ping())
        except DockerException:
            return False

    def spawn(self, image: str = "python:3.11-slim", name: str | None = None, cpus: float = 1.0,
              mem: str = "1g", network: bool = False) -> dict:
        c = self.client.containers.run(
            image, command="sleep infinity", detach=True, name=name, labels={LABEL: "1"},
            nano_cpus=int(cpus * 1e9), mem_limit=mem, network_disabled=not network,
            security_opt=["no-new-privileges"], cap_drop=["ALL"], read_only=False)
        return self._describe(c)

    def list(self) -> list[dict]:
        return [self._describe(c) for c in self.client.containers.list(all=True, filters={"label": LABEL})]

    def _describe(self, c) -> dict:
        c.reload()
        hc = c.attrs.get("HostConfig", {})
        stats = {}
        if c.status == "running":
            try:
                s = c.stats(stream=False)
                cpu_d = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
                sys_d = s["cpu_stats"].get("system_cpu_usage", 0) - s["precpu_stats"].get("system_cpu_usage", 0)
                ncpu = s["cpu_stats"].get("online_cpus", 1)
                stats = {"cpu_percent": round(cpu_d / sys_d * ncpu * 100, 2) if sys_d > 0 else 0.0,
                         "mem_usage_mb": round(s["memory_stats"].get("usage", 0) / 2**20, 1)}
            except (KeyError, DockerException):
                pass
        return {"id": c.short_id, "name": c.name, "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "status": c.status, "cpu_limit": (hc.get("NanoCpus") or 0) / 1e9,
                "mem_limit_mb": round((hc.get("Memory") or 0) / 2**20), **stats}

    def exec(self, container_id: str, command: str, timeout_note: str = "") -> dict:
        c = self.client.containers.get(container_id)
        if LABEL not in c.labels:
            raise PermissionError("refusing to exec in a container not created by Apollo")
        res = c.exec_run(["sh", "-lc", command], demux=True)
        out, err = res.output if res.output else (b"", b"")
        return {"container_id": container_id, "exit_code": res.exit_code,
                "stdout": (out or b"").decode(errors="replace")[-20000:],
                "stderr": (err or b"").decode(errors="replace")[-20000:]}

    def stream(self, container_id: str, command: str) -> Iterator[str]:
        c = self.client.containers.get(container_id)
        if LABEL not in c.labels:
            raise PermissionError("not a Apollo sandbox")
        res = c.exec_run(["sh", "-lc", command], stream=True)
        for chunk in res.output:
            yield chunk.decode(errors="replace")

    def attach_shell(self, container_id: str):
        """Open an interactive TTY bash/sh session; returns the raw socket for streaming."""
        c = self.client.containers.get(container_id)
        if LABEL not in c.labels:
            raise PermissionError("not an Apollo sandbox")
        api = self.client.api
        ex = api.exec_create(c.id, ["sh", "-c", "command -v bash >/dev/null && exec bash || exec sh"],
                             stdin=True, tty=True, environment={"TERM": "xterm-256color"})
        return api.exec_start(ex["Id"], tty=True, socket=True)

    def remove(self, container_id: str) -> bool:
        try:
            c = self.client.containers.get(container_id)
        except NotFound:
            return False
        if LABEL not in c.labels:
            raise PermissionError("not a Apollo sandbox")
        c.remove(force=True)
        return True
