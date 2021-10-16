def on_pr_open_or_update():
    # find Repo
    # find image from target branch (exit if not found)
    # find or create Branch
    # create Build
    # start build (enqueue)
    ...


def on_pr_close_or_merge():
    # find Repo, Branch
    # delete branch (enqueue)
    ...


def on_push():
    # find Repo, branch
    # find image from target branch (exit if not found)
    # find or create Branch
    # create Build
    # start build (enqueue)
    ...
