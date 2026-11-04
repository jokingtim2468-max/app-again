from .. import config  # noqa: F401  (adds repo root to sys.path)
from backend.src.containers.docker_manager import DockerManager

_mgr = DockerManager()


def inspect_containers() -> dict:
    if not _mgr.available():
        return {"docker": "unavailable", "containers": []}
    return {"docker": "ok", "containers": _mgr.list()}


def execute_container_command(container_id: str, command: str) -> dict:
    return _mgr.exec(container_id, command)
