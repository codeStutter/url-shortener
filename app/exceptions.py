class AliasConflictError(Exception):
    """Raised when a requested custom alias is already taken."""

    def __init__(self, alias: str):
        self.alias = alias
        super().__init__(f"Alias '{alias}' is already in use")
