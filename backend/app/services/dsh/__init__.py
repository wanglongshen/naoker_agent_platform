from app.services.dsh.instance_manager import DshInstanceManager

_manager: DshInstanceManager | None = None


def get_manager() -> DshInstanceManager:
    global _manager
    if _manager is None:
        _manager = DshInstanceManager()
    return _manager
