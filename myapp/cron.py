from myapp.functions import autosync_samenode, auto_sync_newnode

root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'


def auto_sync():
    f = open('static/repos.txt', 'r')
    for repo_name in f:
        auto_sync_newnode(repo_name.strip())
