class ClientError(Exception):
    pass


class RepoNotSupported(ClientError):
    pass


class BranchNotFound(ClientError):
    pass


class NotFoundOnGitHub(ClientError):
    pass


class RepoOrBranchNotSupported(ClientError):
    pass
