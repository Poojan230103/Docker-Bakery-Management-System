from myapp.functions import autosync_new_node, autosync_same_node, get_k8s_deployments
import requests

root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'


def auto_sync():
    f = open('static/repos.txt', 'r')
    for repo_name in f:
        autosync_same_node(repo_name.strip())
    get_k8s_deployments()







