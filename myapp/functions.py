from datetime import datetime
import re
import copy
import json
import time
import logging
import os
import yaml
from concurrent.futures import ThreadPoolExecutor
import pytz
import asyncio
import aiohttp
from dotenv import load_dotenv
import pymongo
from github import Github
import requests
from myapp.models import treenode, dependencies


logging.basicConfig(level=logging.DEBUG, filename="logs.log", format="%(asctime)s - %(message)s", datefmt='%d-%b-%y %H:%M:%S')
load_dotenv()
client = pymongo.MongoClient(os.getenv("MONGODB_CONNECTION_STRING"))
db = client.get_database('myDB')
records = db['Images']
github_client = Github(os.getenv("GITHUB_ACCESS_TOKEN"))
old_to_mirror = {}                                      # dictionary to map the upgraded nodes with their sibling.
next_id = records.count_documents({}) + 1


def create_docker_graph(array_id, data, node_to_array_id):
    children = []
    for child_node_id in data[array_id]["children"]:
        child_node = create_docker_graph(node_to_array_id[child_node_id], data, node_to_array_id)
        children.append(child_node)
    children = sorted(children, key=lambda x: x['img_name'])
    data[array_id]["children"] = children
    return data[array_id]


def parse_script(shell_script):
    components = {}
    current_component = None
    shell_script = shell_script.splitlines()
    for line in shell_script:
        line = line.strip()
        # Check for component name
        component_match = re.match(r'(\S+)\)\s*$', line)
        if component_match:
            current_component = component_match.group(1)
            continue
        # Check for Dockerfile path
        dockerfile_match = re.match(r'DOCKERFILE_PATH=(.*?)\s*$', line)
        if dockerfile_match and current_component:
            dockerfile_path = dockerfile_match.group(1)
            components[current_component] = dockerfile_path
            current_component = None
    return components


def parse_dockerfile(dockerfile):
    parent = None
    # requirements_path = None
    requirements_path_list = []
    dockerfile = dockerfile.splitlines()
    for lines in dockerfile:
        if lines.startswith('FROM'):
            parent = lines.split()[1]
            if parent.find(':') == -1:
                parent = parent + ':1.0'
        # match = re.match(r'COPY\s+([^\s]+/requirements.txt)\s+\.', lines)     # requirements.txt path
        match = re.match(r'COPY\s+((\S+/)?.*requirements.*\.txt)\s+\.', lines)        # requirements.txt path
        if match:
            requirements_path = match.group(1)
            requirements_path_list.append(requirements_path)
    # return parent, requirements_path
    return parent, requirements_path_list


def convert_to_indian_time(utc_time_zone):
    india_timezone = pytz.timezone('Asia/Kolkata')
    india_time = pytz.utc.localize(utc_time_zone).astimezone(india_timezone)
    india_time = india_time.strftime('%Y-%m-%d %H:%M:%S')
    india_time = datetime.strptime(india_time, '%Y-%m-%d %H:%M:%S')    # datetime object
    return india_time


def build_image(parameter):
    if "repo_name" in parameter.keys():
        img_name = f'''poojan23/docker-bakery-system_{parameter["component_name"]}'''
        try:
            response = requests.post("http://127.0.0.1:9000/build_updated", data=parameter)
            if response.status_code != 200:
                logging.error(f"Failed to build Image {img_name}")
                return "Failed"
        except requests.exceptions.RequestException as e:
            logging.error('Failed to establish connection to build API')
            return "Failed"
    else:
        img_name = parameter["img_name"]
        try:
            response = requests.post("http://127.0.0.1:9000/build_no_component", data=parameter)
            if response.status_code != 200:
                logging.error(f"Failed to build Image: {img_name}")
                return "Failed"
        except requests.exceptions.RequestException as e:
            logging.error('Failed to establish connection to build API')
            return "Failed"
    json_response = response.json()
    if response.status_code != 200 or "job_id" not in json_response:
        logging.error("API for Docker build failed, status: " + str(response.status_code) + ", image:" + img_name)
        return "Failed"
    status = poll_for_docker_build(img_name, json_response["job_id"])
    return status


def poll_for_docker_build(img_name, job_id):
    parameter = {"job_id": job_id}
    while True:
        response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
        response = response.json()
        if response["status"] == "Success" or response["status"] == "Failed":
            logging.info(f'''Build Status of image: {img_name} --> Rebuild {response["status"]}''')
            return response["status"]
        time.sleep(5)


def delete_image(parameter):
    try:
        response = requests.post("http://127.0.0.1:9000/delete_node_api", data=parameter)
        if response.status_code != 200:
            logging.error(f'''Failed to delete Image: {parameter["img_name"]}''')
            return "Failed"
    except requests.exceptions.RequestException as e:
        logging.error('Failed to establish connection to Delete API')
        return "Failed"
    response = response.json()
    if response["status"] == "Success":
        logging.info(f'''Status of deletion of image: {parameter["img_name"]} --> {response["status"]}''')
        return "Success"
    else:
        logging.info(f'''Status of deletion of image: {parameter["img_name"]} --> {response["status"]}''')
        return "Failed"


def should_rebuild_image_and_sync(node, repo_name):         # returns true if any of the dockerfile or requirements.txt is modified
    repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
    dockerfile_repo_path = node["dockerfile_repo_path"]                         # check for dockerfile
    dockerfile_commits = repository.get_commits(path=dockerfile_repo_path)
    dockerfile_last_commit_time = convert_to_indian_time(dockerfile_commits[0].commit.committer.date)
    last_sync_time = convert_to_indian_time(datetime.strptime(node["last_synced_time"], '%Y-%m-%d %H:%M:%S'))  # converting both times in INDIA timezone to avoid any confusion.
    if dockerfile_last_commit_time > last_sync_time:
        return True
    for dependency in node["files"]:                                            # check for requirements.txt
        dependency_repo_path = dependency["dependency_repo_path"]
        dependency_file_commits = repository.get_commits(path=dependency_repo_path)
        dependency_last_commit_time = convert_to_indian_time(dependency_file_commits[0].commit.committer.date)
        if dependency_last_commit_time > last_sync_time:
            return True
    return False


def get_parameters(node):
    if node["repo_name"]:
        parameter = {
            "repo_name": node["repo_name"],
            "dockerfile": node["dockerfile_content"], "dockerfile_path": node["dockerfile_repo_path"],
            "component_name": node["component_name"], "tag": node["tag"]
        }
    else:
        requirements = None
        for dependency in node["files"]:                        # in case the image does not contain any repo, then the list node["files"] will contain atmost 1 element.
            requirements = dependency["dependency_content"]
        parameter = {
            "dockerfile": node["dockerfile_content"], "img_name": node["img_name"],
            "tag": node["tag"], "requirements": requirements
        }
    return parameter


def sync_new_node(node, repo_name):
    repo_url = f"{os.getenv('REPO_BASE')}/{repo_name}"
    repository = github_client.get_repo(repo_url)
    if should_rebuild_image_and_sync(node, repo_name):                                # the files have changed, so we need to rebuild.
        new_node = copy.deepcopy(node)
        new_node["dockerfile_content"] = get_data_from_repository(repository, new_node["dockerfile_repo_path"])
        parent_img_name, requirements_list = parse_dockerfile(new_node["dockerfile_content"])
        parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
        if parent_node is None:
            logging.error(f'''Failed to sync image: {node["img_name"]}:{node["tag"]}. Error: Parent Not Found''')
            return 1
        new_node["files"] = get_dependencies(repository, requirements_list)
        new_node["created_time"] = new_node["last_synced_time"] = new_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
        new_node["_id"] = element_with_highest_id["_id"] + 1
        global next_id
        next_id = new_node["_id"] + 1
        old_to_mirror[node["_id"]] = new_node["_id"]
        new_node["tag"] = round(node["tag"] + 0.1, 10)          # updating the tag of the image
        parameter = get_parameters(new_node)
        status = build_image(parameter)
        if status == "Success":
            redeploy_components(new_node)                               # redeploying the deployments
            new_node["sibling"] = node["_id"]                           # assigning sibling
            parent_node = parent_node
            parent_node["children"].append(new_node["_id"])            # adding the new child to parent
            new_node["parent"] = parent_node["_id"]
            commits = repository.get_commits(sha=repository.default_branch)[0]
            new_node["commit_id"] = commits.sha                                 # storing the commit sha of the commit.
            new_node["children"].clear()
            for children in node["children"]:                   # recursively building the children
                dfs_new_node(children, node, new_node)
            records.insert_one(new_node)
            records.replace_one({"_id": parent_node["_id"]}, parent_node)
        else:
            return 1
        node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
        records.replace_one({"_id": node["_id"]}, node)                                         # to be asked
    return 0


def sync_same_node(node, repo_name):
    repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
    if should_rebuild_image_and_sync(node, repo_name):
        node["dockerfile_content"] = get_data_from_repository(repository, node["dockerfile_repo_path"])
        parent_img_name, requirements_list = parse_dockerfile(node["dockerfile_content"])
        parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
        # parent_node = check_if_new_parent_exists(node["dockerfile_content"])
        if parent_node is None:                        # if the parent node does not exist
            logging.error(f'''Failed to sync image: {node["img_name"]}:{node["tag"]}. Error: Parent Not Found''')
            return 1
        if parent_node["_id"] != node["parent"]:           # if the parent has changed in the new version of the dockerfile and the new parent exists
            old_parent_node = records.find_one({"_id": node["parent"]})
            old_parent_node["children"].erase(node["_id"])
            parent_node["children"].append(node["_id"])
            records.replace_one({"_id": old_parent_node["_id"]}, old_parent_node)
            records.replace_one({"_id": parent_node["_id"]}, parent_node)
        node["files"] = get_dependencies(repository, requirements_list)
        parameter = get_parameters(node)
        status = build_image(parameter)
        if status == "Success":
            redeploy_components(node)                                               # redeploying the deployments
            commits = repository.get_commits(sha=repository.default_branch)[0]
            node["commit_id"] = commits.sha                                         # updating the commit sha of the node.
            child_node_to_status = asyncio.run(multiple_docker_build(node["children"]))     # rebuilding all its children.
            for child_id in node["children"]:
                # dfs_same_node(child_id)
                dfs_same_node(child_id, child_node_to_status)
            node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        else:
            return 1
    node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
    records.replace_one({"_id": node["_id"]}, node)
    return 0


def add_new_component(repo_name, components_dictionary):          # components_dictionary --> dictionary which maps component_name to dockerfile_repo_path
    for component in components_dictionary.keys():
        if records.count_documents({"component_name": component}) == 0:
            repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
            name = 'poojan23/docker-bakery-system_' + component + ':1.0'
            new_node = treenode(name)
            element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
            new_node._id = element_with_highest_id["_id"] + 1
            new_node.repo_name = repo_name
            new_node.dockerfile_repo_path = components_dictionary[component][1:]                              # this path is relative to the root path of repo.
            new_node.component_name = component
            new_node.dockerfile_content = get_data_from_repository(repository, new_node.dockerfile_repo_path)
            parent_name, requirements_list = parse_dockerfile(new_node.dockerfile_content)
            parent_data = parent_name.split(':')                                                                # parent_data-->list with 0th element image-name and 1st element tag
            parent_node = records.find_one({"img_name": parent_data[0], "tag": float(parent_data[1])})
            if parent_node is None:
                continue
            new_node.parent = parent_node["_id"]        # storing the parent
            new_node.files = get_dependencies(repository, requirements_list)
            parent_node["children"].append(new_node._id)                            # storing the child
            commits = repository.get_commits(sha=repository.default_branch)[0]
            new_node.commit_id = commits.sha                                        # storing the commit sha of the commit.
            parameter = get_parameters_from_treenode(new_node)
            status = build_image(parameter)
            if status == "Success":
                store_in_mongodb(new_node)
                records.replace_one({"_id": parent_node["_id"]}, parent_node)
            else:
                logging.error("Failed to add new component:",component)


'''
Explanation for dfs_new_node function

       a            after upgrading node b                a                 
       b         --------------------------->        b        e            
     c   d                                         c   d    f   g          
when we upgrade node b, sibling node(node -> e) will be created and similarly its subtree will be created recursively.
I am just making a copy of subtree rooted at b by mapping the nodes of subtree of b with the nodes of subtree of its sibling(e).
So the new subtree is build in the following order, b is mapped to e ->  c is mapped to f -> d is mapped to g. Basically it's just DFS.
I am also maintaining a dictionary(old_to_mirror) to establish the siblings relationship between mapped nodes. 
'''


def dfs_new_node(old_child_id, sibling_parent_node, new_parent_node):                 # building the whole tree structure.
    old_child_node = records.find_one({"_id": old_child_id})
    new_child_node = copy.deepcopy(old_child_node)                          # making the copy of the old node
    if new_child_node["repo_name"]:
        repository = github_client.get_repo(f'''{os.getenv('REPO_BASE')}/{new_child_node["repo_name"]}''')
        dockerfile_content = get_data_from_repository(repository, new_child_node["dockerfile_repo_path"])           # taking data from GitHub repository
        parent_img_name, requirements_list = parse_dockerfile(dockerfile_content)
        parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
        new_child_node["files"] = get_dependencies(repository, requirements_list)
        if parent_node is None:
            return
        if parent_node["_id"] != sibling_parent_node["_id"]:
            new_parent_node = parent_node
        new_child_node["dockerfile_content"] = dockerfile_content
    global next_id
    new_child_node["_id"] = next_id               # assigned id to the new child
    next_id += 1
    old_to_mirror[old_child_id] = new_child_node["_id"]
    new_child_node["dockerfile_content"] = update_parent_in_dockerfile(new_child_node, new_parent_node)             # updating the dockerfile
    if new_child_node["repo_name"]:
        repository = github_client.get_repo(f'''{os.getenv('REPO_BASE')}/{new_child_node["repo_name"]}''')
        file = repository.get_contents(new_child_node["dockerfile_repo_path"])                 # updating the dockerfile in GitHub repo
        repository.update_file(file.path, "updated Dockerfile", new_child_node["dockerfile_content"], file.sha)
        # time.sleep(1)
        commits = repository.get_commits(sha=repository.default_branch)[0]
        new_child_node["commit_id"] = commits.sha                                   # storing the commit sha of the node.
    new_child_node["parent"] = new_parent_node["_id"]                               # assigned parent to the new child node
    new_parent_node["children"].append(new_child_node["_id"])                       # appending child to the new parent node
    highest_tag_node = records.find_one({"img_name": new_child_node["img_name"]}, sort=[("tag", -1)], limit=1)
    highest_tag = highest_tag_node["tag"]
    new_child_node["tag"] = round(highest_tag + 0.1, 10)            # incrementing the minor tag
    new_child_node["children"].clear()
    # building image
    parameter = get_parameters(new_child_node)
    status = build_image(parameter)
    if status == "Success":
        redeploy_components(new_child_node)                 # redeploying the components
        new_child_node["created_time"] = new_child_node["last_synced_time"] = new_child_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        for child in old_child_node["children"]:
            dfs_new_node(child, old_child_node, new_child_node)
        first_mirror_img = True
        if new_child_node["sibling"] and not first_mirror_img:
            new_child_node["sibling"] = old_to_mirror[new_child_node["sibling"]]                # establishing parent child relation in new images
        else:
            new_child_node["sibling"] = highest_tag_node["_id"]
            first_mirror_img = False
        records.insert_one(new_child_node)


# def dfs_same_node(node_id, to_update_last_sync_time=True):             # recursively re-building the subtree on update of the parent node
#     # variable to_update_last_sync_time is kept because we will use this function for edit node functionality too.
#     child_node = records.find_one({"_id": node_id})
#     parameter = get_parameters(child_node)
#     status = build_image(parameter)
#     if status == "Success":
#         redeploy_components(child_node)                 # redeploying the deployments
#         for child_id in child_node["children"]:
#             dfs_same_node(child_id, to_update_last_sync_time)
#         child_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
#         if to_update_last_sync_time:
#             child_node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
#             records.replace_one({"_id": child_node["_id"]}, child_node)


def autosync_new_node(repo_name):
    repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
    shell_script = get_data_from_repository(repository, '/build-component.sh')
    components = parse_script(shell_script)
    add_new_component(repo_name, components)        # checking and building new components are added
    for comp in components.keys():
        node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)     # node --> the node with the highest tag
        sync_new_node(node, repo_name)


def autosync_same_node(repo_name):
    repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
    shell_script = get_data_from_repository(repository, '/build-component.sh')
    components = parse_script(shell_script)
    add_new_component(repo_name, components)        # checking and building if new components are added
    for comp in components.keys():
        node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)      # finding the node with highest tag.
        sync_same_node(node, repo_name)             # syncing each component in the repository


def delete_subtree(node_id, delete_siblings):                                # this function deletes a node and its subtree.
    node = records.find_one({"_id": node_id})
    for child_id in node["children"]:                           # recursively deleting the children
        delete_subtree(child_id, delete_siblings)
    parameters = {"img_name": node["img_name"], "tag": node["tag"]}
    status = delete_image(parameters)
    if status == "Success":                            # the node is deleted from the database only if the has been successfully deleted
        if delete_siblings == 0:
            redeploy_using_latest_img(node)
        next_sibling_node = records.find_one({"sibling": node["_id"]})
        if next_sibling_node is not None:
            next_sibling_node["sibling"] = node["sibling"]
            records.replace_one({"_id": next_sibling_node["_id"]}, next_sibling_node)
        parent_node = records.find_one({"_id": node["parent"]})
        parent_node["children"].remove(node["_id"])
        records.replace_one({"_id": parent_node["_id"]}, parent_node)
        records.delete_one({"_id": node["_id"]})
    return status


def redeploy_using_latest_img(node):
    list_of_deployments = node["deployments"]
    latest_sibling_node = records.find_one({"img_name": node["img_name"]}, sort=[("tag", -1)], limit=1)  # re-deploying using the latest sibling node.
    if latest_sibling_node is not None:
        ''' copying the deployments that were made using older image into latest sibling's deployments.
            Then re-deploying those deployments using the latest sibling
            After re-deploying, appending the deployments that were actually made by the latest sibling node prior to deletion of the node.'''
        latest_sibling_deployments = latest_sibling_node["deployments"]
        latest_sibling_node["deployments"] = list_of_deployments
        redeploy_components(latest_sibling_node)
        for element in latest_sibling_deployments:
            if element not in latest_sibling_node["deployments"]:
                latest_sibling_node.append(element)
        records.replace_one({"_id": latest_sibling_node["_id"]}, latest_sibling_node)


# def get_k8s_deployments():                      # function to get the deployments using each image under the environment-prod
#     parameters = {"env": "prod"}
#     response = requests.post("http://127.0.0.1:9000/get_deployments", data=parameters)     # calls an API which returns a dictionary {'img_name': {'deployment_name', 'env'}
#     dict_string = response.content.decode('utf-8')
#     dictionary = eval(dict_string)
#     for image in dictionary.keys():
#         img_name = image.split(':')[0]
#         tag = float(image.split(':')[1])
#         node = records.find_one({"img_name": img_name, "tag": tag})
#         node["deployments"] = dictionary[image]
#         records.replace_one({"img_name": img_name, "tag": tag}, node)


def replace_document(node, dictionary):
    img_name_with_tag = node["img_name"] + ':' + str(node["tag"])
    if img_name_with_tag in dictionary.keys():
        node["deployments"] = dictionary[img_name_with_tag]
        records.replace_one({"_id": node["_id"]}, node)


def get_k8s_deployments():                      # function to get the deployments using each image under the environment-prod
    parameters = {"env": "prod"}
    try:
        response = requests.post("http://127.0.0.1:9000/get_deployments", data=parameters)     # calls an API which returns a dictionary {'img_name': {'deployment_name', 'env'}
        if response.status_code != 200:
            logging.error("Failed to fetch deployments")
            return
    except requests.exceptions.RequestException as e:
        logging.error('Failed to establish connection to get deployments API')
        return
    dict_string = response.content.decode('utf-8')
    dictionary = eval(dict_string)
    list_nodes = list(records.find({}))
    # num_threads = 10
    # replacing the node-data in DB concurrently
    executor = ThreadPoolExecutor(max_workers=None)
    futures = [executor.submit(replace_document, node, dictionary) for node in list_nodes]
    # Wait for all futures to complete
    for future in futures:
        future.result()
    executor.shutdown()


def redeploy_components(node):                          # this function re-deploy all the deployments that were made using this node(image).
    for deployment in node["deployments"]:
        parameters = {"image_name": node["img_name"], "tag": node["tag"], "component_name": node["component_name"], "deployment_name": deployment["deployment_name"]}
        response = requests.post("http://127.0.0.1:9000/deploy_component", data=parameters)
        response_dictionary = response.json()
        if response_dictionary["status"] == "Success":
            print("hello from redeploy_components")
        if response.status_code == 200:
            print("hii from redeploy_components")
        if (response.status_code == 200) and (response_dictionary["status"] == "Success"):
            logging.info(f''' Deployment: {deployment["deployment_name"]} deployed Successfully using Image: {node["img_name"]}:{node["tag"]}''')
        else:
            logging.info(f'''Failed to re-deploy {deployment["deployment_name"]}''')


def store_in_mongodb(node):                               # to be used to store the tree-node object in mongodb.
    json_data = json.dumps(node, default=lambda o: o.__dict__, indent=4)  # converting tree object to json
    json_data = json.loads(json_data)  # converting json to python dictionary
    records.insert_one(json_data)


def get_data_from_repository(repository, file_path):        # fetches the data from github repository from the provided file_path
    file = repository.get_contents(file_path)  # storing the contents of Dockerfile
    response = requests.get(file.download_url)
    content = str(response.content, 'UTF-8')
    return content


# def check_if_new_parent_exists(dockerfile_content):      # this function checks whether the parent image specified in the dockerfile exists in our hierarchy or not.
#     parent = None
#     dockerfile_content = dockerfile_content.splitlines()
#     for line in dockerfile_content:                         # Takes into account the multi-stage docker build
#         if line.__contains__("FROM"):
#             parent = line.split()[1]
#     parent_node = records.find_one({"img_name": parent.split(':')[0], "tag": float(parent.split(':')[1])})
#     return parent_node


def update_parent_in_dockerfile(new_child_node, new_parent_node):           # modifies the parent image in the dockerfile and returns the updated dockerfile
    content = new_child_node["dockerfile_content"].splitlines()
    line_num = -1
    cnt = 0
    for line in content:                        # taking into account multi-stage docker build by picking the last FROM statement
        if line.__contains__("FROM"):
            line_num = cnt
        cnt += 1
    if line_num != -1:
        old_par_name = content[line_num].split()[1]
        new_par_name = new_parent_node["img_name"] + ':' + str(new_parent_node["tag"])
        content[line_num] = content[line_num].replace(old_par_name, new_par_name)
    return '\n'.join(content)


def get_parameters_from_treenode(tree_node):
    if tree_node.repo_name:
        parameter = {"repo_name": tree_node.repo_name, "dockerfile": tree_node.dockerfile_content,
                     "dockerfile_path": tree_node.dockerfile_repo_path, "component_name": tree_node.component_name,
                     "tag": tree_node.tag
                     }
    else:                                           # if tree_node does not contain repository then it will have at-most 1 Requirements.txt
        requirements = None
        for dependency in tree_node.files:
            if dependency["name"] == "requirements.txt":
                requirements = dependency["dependency_content"]
        parameter = {"dockerfile": tree_node.dockerfile_content,
                     "img_name": tree_node.img_name,
                     "tag": tree_node.tag,
                     "requirements": requirements}
    return parameter


def get_dependencies(repository, requirements_path_list):
    list_of_dependency = []
    for requirements_path in requirements_path_list:
        new_dependency = dependencies("requirements.txt")                       # naming all requirements.txt the same.
        new_dependency.dependency_repo_path = requirements_path[1:]             # requirements.txt path relative to path of the build-component.sh
        new_dependency.dependency_content = get_data_from_repository(repository, new_dependency.dependency_repo_path)  # storing the contents of requirements.txt
        list_of_dependency.append(new_dependency)
    dependencies_str = json.dumps([dependency.__dict__ for dependency in list_of_dependency])       # json string
    list_of_dependency = json.loads(dependencies_str)                                               # list of dictionaries
    return list_of_dependency


async def build_image_async(session, parameter):
    if "repo_name" in parameter.keys():
        img_name = f'''poojan23/docker-bakery-system_{parameter["component_name"]}'''
        response = await session.post("http://127.0.0.1:9000/build_updated", data=parameter)
    else:
        img_name = parameter["img_name"]
        response = await session.post("http://127.0.0.1:9000/build_no_component", data=parameter)

    json_response = await response.json()

    if (response.status != 200) or ("job_id" not in json_response):
        logging.error(
            "API for Docker build failed, status: " + str(response.status) + ", image:", img_name)
        return "Failed"
    status = poll_for_docker_build(img_name, json_response["job_id"])
    return status


async def multiple_docker_build(node_ids):
    tasks = []
    node_id_to_status = {}
    async with aiohttp.ClientSession() as session:
        for node_id in node_ids:
            node = records.find_one({"_id": node_id})
            parameter = get_parameters(node)
            tasks.append(asyncio.create_task(build_image_async(session, parameter)))
        responses = await asyncio.gather(*tasks)
    for index in range(len(node_ids)):
        node_id_to_status[node_ids[index]] = responses[index]
    return node_id_to_status


def dfs_same_node(node_id, node_id_to_status, to_update_last_sync_time=True):             # recursively re-building the subtree on update of the parent node
    # All the nodes that are at the same level are build asynchronously.
    # variable to_update_last_sync_time is kept because we will use this function for edit node functionality too.
    child_node = records.find_one({"_id": node_id})
    if node_id_to_status[node_id] == "Success":
        redeploy_components(child_node)                 # redeploying the deployments

        child_node_id_to_status = asyncio.run(multiple_docker_build(child_node["children"]))            # asyncronous re-building images.

        for child_id in child_node["children"]:
            dfs_same_node(child_id, child_node_id_to_status, to_update_last_sync_time)
        child_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        if to_update_last_sync_time:
            child_node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
            records.replace_one({"_id": child_node["_id"]}, child_node)


def update_dictionary(dict1, dict2):            # this function overwrites the values of keys that are common from dict2 into dict1.
    for key, value in dict2.items():
        if key in dict1:
            if isinstance(dict1[key], dict) and isinstance(value, dict):
                update_dictionary(dict1[key], value)
            elif isinstance(dict1[key], list) and isinstance(value, list):
                dict1[key].extend([v for v in value if v not in dict1[key]])
            else:
                dict1[key] = value
        else:
            dict1[key] = value
    return dict1


def get_deployments_from_repo():
    # This function parses the helm-repository and returns the dictionary { img_name --> [{deployment_name, env}] }
    image_to_deployment = {}
    helm_repository = github_client.get_repo("Poojan230103/helm-repository")
    helm_charts = helm_repository.get_contents('')
    for helm_chart in helm_charts:
        if helm_chart.name != '.DS_Store':
            file = helm_repository.get_contents(f"{helm_chart.name}/values.yaml")
            response = requests.get(file.download_url)
            helm_chart_dictionary = yaml.safe_load(str(response.content, 'UTF-8'))      # values.yaml file present in the root directory.
            releases = helm_repository.get_contents(f"{helm_chart.name}/releases")
            for release in releases:
                if release.name == '.DS_Store':
                    continue
                file = helm_repository.get_contents(f"{helm_chart.name}/releases/{release.name}/values.yaml")
                response = requests.get(file.download_url)
                release_dictionary = yaml.safe_load(str(response.content, 'UTF-8'))         # values.yaml file present in the release directory inside releases dir.
                helm_chart_dictionary = update_dictionary(helm_chart_dictionary, release_dictionary)
                envs = helm_repository.get_contents(f"{helm_chart.name}/releases/{release.name}/env")
                for env in envs:
                    if env.name == '.DS_Store':
                        continue
                    file = helm_repository.get_contents(f"{helm_chart.name}/releases/{release.name}/env/{env.name}")         # e.g. prod0-values.yaml
                    response = requests.get(file.download_url)
                    env_dictionary = yaml.safe_load(str(response.content, 'UTF-8'))
                    helm_chart_dictionary = update_dictionary(helm_chart_dictionary, env_dictionary)
                    if helm_chart_dictionary["deployment"]["image"] not in image_to_deployment.keys():
                        image_to_deployment[helm_chart_dictionary["deployment"]["image"]] = [{"deployment_name": f"{helm_chart.name}-{release.name}", "env": env.name.split('-')[0]}]
                    else:
                        image_to_deployment[helm_chart_dictionary["deployment"]["image"]].append({"deployment_name": f"{helm_chart.name}-{release.name}", "env": env.name.split('-')[0]})
    # for image in image_to_deployment.keys():
    #     img_name = image.split(':')[0]
    #     tag = float(image.split(':')[1])
    #     node = records.find_one({"img_name": img_name, "tag": tag})
    #     node["deployments"] = image_to_deployment[image]
    #     records.replace_one({"img_name": img_name, "tag": tag}, node)
    executor = ThreadPoolExecutor(max_workers=None)
    list_nodes = list(records.find({}))
    futures = [executor.submit(replace_document, node, image_to_deployment) for node in list_nodes]
    # Wait for all futures to complete
    for future in futures:
        future.result()
    executor.shutdown()
