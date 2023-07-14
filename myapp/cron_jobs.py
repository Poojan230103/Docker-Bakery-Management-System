from myapp.functions import autosync_update_node, get_k8s_deployments
import logging
from dotenv import load_dotenv


logging.basicConfig(level=logging.DEBUG, filename="logs.log", filemode="w", format="%(asctime)s - %(message)s", datefmt='%d-%b-%y %H:%M:%S')
load_dotenv()


def auto_sync():
    get_k8s_deployments()
    f = open('static/repos.txt', 'r')
    for repo_name in f:
        autosync_update_node(repo_name.strip())


def get_deployments_cronjob():
    get_k8s_deployments()



