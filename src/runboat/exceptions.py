class ClientError(Exception):
    pass


class RepoNotFound(ClientError):
    pass


class BranchNotFound(ClientError):
    pass


class NotFoundOnGithub(ClientError):
    pass


class BranchNotSupported(ClientError):
    pass
