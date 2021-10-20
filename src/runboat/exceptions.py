class ClientError(Exception):
    pass


class RepoNotSupported(ClientError):
    pass


class BranchNotFound(ClientError):
    pass


class NotFoundOnGithub(ClientError):
    pass


class BranchNotSupported(ClientError):
    pass
