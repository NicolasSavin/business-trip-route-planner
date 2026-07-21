class BrowserInfrastructureError(RuntimeError):
    pass


class BrowserDisabledError(BrowserInfrastructureError):
    pass


class BrowserPoolExhaustedError(BrowserInfrastructureError):
    pass
