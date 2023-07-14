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
old_img_to_new_img = {}                                      # dictionary to map the upgraded nodes with their sibling.
next_id = records.count_documents({}) + 1


'''
Explanation for create_docker_graph function:
This function takes input array_index: the index of root image node in the image_list, image_list: list of image nodes, node_id_to_array_index: dictionary that maps the id of image node in mongoDB database to index of image node in the image list.
The function creates a hierarchy by recursively appending the child image node object inside the parent image-node's children array.
It stores the child image-nodes in the sorted order of their name.
Returns the image_list in the hierarchical format.
See, /static/data.json file for clarification.
'''


def create_docker_graph(array_index, image_list, node_id_to_array_index):
    children = []
    for child_node_id in image_list[array_index]["children"]:
        child_node = create_docker_graph(node_id_to_array_index[child_node_id], image_list, node_id_to_array_index)
        children.append(child_node)
    children = sorted(children, key=lambda x: x['img_name'])
    image_list[array_index]["children"] = children
    return image_list[array_index]


'''
Explanation for parse_script function:
This function takes input build-component.sh shell script and parses it and returns a dictionary that maps component-name with the path of its associated dockerfile in the repository.
The component-name and dockerfile path are found using the regular expressions.
'''


def parse_script(shell_script):
    component_name_to_dockerfile_path = {}
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
            component_name_to_dockerfile_path[current_component] = dockerfile_path
            current_component = None
    return component_name_to_dockerfile_path


'''
Explanation for parse_dockerfile function:
This function takes input dockerfile contents.
The function parses the dockerfile to find the parent image name and the list of repository paths of requirements.txt files that are required to build that image.
Returns the parent image name along with its tag and list of paths of requirements.txt files.
The function also takes care of the Multi-stage docker build by taking the parent name from the last line containing the 'FROM' statement.
'''


def parse_dockerfile(dockerfile):
    parent = None
    requirements_path_list = []
    dockerfile = dockerfile.splitlines()
    for lines in dockerfile:
        if lines.startswith('FROM'):
            parent = lines.split()[1]
            if parent.find(':') == -1:
                parent = parent + ':1.0'
        match = re.match(r'COPY\s+((\S+/)?.*requirements.*\.txt)\s+\.', lines)        # requirements.txt path
        if match:
            requirements_path = match.group(1)
            requirements_path_list.append(requirements_path)
    return parent, requirements_path_list


'''
Explanation for convert_to_indian_time function:

This function takes an date-time object in the UTC time-zone.
Returns a date-time object in Indian time zone.
'''


def convert_to_indian_time(utc_time_zone):
    india_timezone = pytz.timezone('Asia/Kolkata')
    india_time = pytz.utc.localize(utc_time_zone).astimezone(india_timezone)
    india_time = india_time.strftime('%Y-%m-%d %H:%M:%S')
    india_time = datetime.strptime(india_time, '%Y-%m-%d %H:%M:%S')    # datetime object
    return india_time


'''
Explanation for build_image function:

This function takes input a dictionary parameter and passes it as an argument to the API to build the docker image.
If the image has a repository of which it is a part of, then build_component_image_api is called. Else, build_non_component_image_api is called.
The API returns a dictionary which contains a job_id, which is used by the poll_for_docker_build function to poll and get the status of the docker build process getting executed on the API server.
The function along handles the exception when the connection to the API server fails.
This functions takes the status(success or failed) of the docker build process from the poll_for_docker_build process and returns it. 
'''


def build_image(parameter):
    if "repo_name" in parameter.keys():
        img_name = f'''{os.getenv('REPO_BASE')}/docker-bakery-system_{parameter["component_name"]}'''
        try:
            response = requests.post("http://127.0.0.1:9000/build_component_image_api", data=parameter)
            if response.status_code != 200:
                logging.error(f"Failed to build Image {img_name}")
                return "Failed"
        except requests.exceptions.RequestException as e:
            logging.error('Failed to establish connection to build API')
            return "Failed"
    else:
        img_name = parameter["img_name"]
        try:
            response = requests.post("http://127.0.0.1:9000/build_non_component_image_api", data=parameter)
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


'''
Explanation for poll_for_docker_build function:

The function takes input the image name and the job_id using which it calls the poll_build_image_api.
The API returns the status of docker build process. i.e. Success/Failed/In Progress.
The API is called every 5 seconds until it returns the status Success or Failed.
'''


def poll_for_docker_build(img_name, job_id):
    parameter = {"job_id": job_id}
    while True:
        response = requests.post("http://127.0.0.1:9000/poll_build_image_api", data=parameter)
        response = response.json()
        if response["status"] == "Success" or response["status"] == "Failed":
            logging.info(f'''Build Status of image: {img_name} --> Rebuild {response["status"]}''')
            return response["status"]
        time.sleep(5)


'''
Explanation for delete_image function: 

Input: a dictionary parameter which contains image name and tag.
It calls the delete_node_api and passes the dictionary parameter to it and checks whether the status code of the API response is 200 or not. If it is not 200 then it means that the deletion of image 
failed. The API returns a dictionary as response containing the status of the delete-image request. 
This function also handles the exception if the API server is down or it fails to establish connection with it.
'''


def delete_image(parameter):
    try:
        response = requests.post("http://127.0.0.1:9000/delete_node_api", data=parameter)
        if response.status_code != 200:
            logging.error(f'''Failed to delete Image: {parameter["img_name"]}''')
            return "Failed"
    except requests.exceptions.RequestException as e:
        logging.error('Failed to establish connection to Delete Node API')
        return "Failed"
    response = response.json()
    if response["status"] == "Success":
        logging.info(f'''Status of deletion of image: {parameter["img_name"]} --> {response["status"]}''')
        return "Success"
    else:
        logging.info(f'''Status of deletion of image: {parameter["img_name"]} --> {response["status"]}''')
        return "Failed"


'''
Explanation for should_rebuild_image_and_sync function:

This function takes input the image node which is to be synced and repo name of the repository to which this image belongs to. It checks if the last sync time of the image node is less than the last commit time of dockerfile or last commit time of requirements.txt file. If yes it returns True else it returns False.
'''


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


'''
Explanation for get_parameters function:
This function takes input the image node and returns the parameters that will be passed to the API to build the image.
If the image is built from a repository, the parameters: repo_name, dockerfile, component_name, tag, repo path of the dockerfile are returned.
If the image is not built from repository, then the parameters: dockerfile, image name, tag and requirements.txt file are returned
'''


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


'''
Explanation for get_commits_sha function:

The function takes the argument repository object which is used to access the github repository.
Returns the commit sha of the latest commit.
'''


def get_commits_sha(repository):
    commits = repository.get_commits(sha=repository.default_branch)[0]
    return commits.sha


'''
Explanation for can_process_node function:

This function takes input the image node, and checks whether itself or any of its ancestor till the root node, are already locked.
If YES, then we cannot process the node now and we will return False & image name of the image node which is locked.
Else if will return True.
'''


def can_process_node(node):                # returns false if the ancestor is already locked. Also returns the image name of the locked node.
    while node is not None:
        if node["is_locked"]:
            img_name = node["img_name"] + ':' + str(node["tag"])
            return False, img_name
        node = records.find_one({"_id": node["parent"]})
    return True, None


'''
Explanation for sync_update_node function:

This function takes the input an image node and the repo_name of the image of which it is a part of.
First it checks whether the image is can be synced or not by checking whether any of its ancestor is being processed currently by some other user. If yes we cannot sync the image now and throw an error. This is to avoid the race condition.
If the image can be synced, then it is checked whether should we rebuild the image by comparing the last-sync-time with the last commit time using the function should_rebuild_image_and_sync function.
It parses the dockerfile and checks whether the parent of the image has changed. If it has changed, then we first check whether the changed parent image exists or not. If it exists then the image node is shifted from old parent to the new parent node.
If yes then the node is first locked so that other user cannot update/edit/delete it and then the dockerfile and requirements.txt files are fetched from repo and the image is rebuilt. If the status of rebuild of image is success, then its deployments are re-deployed and then its child images are rebuilt asynchronously.
After rebuilding the child images asynchronously, dfs_update_node function is called for each child node.
At the end the lock is released to avoid deadlock.
'''


def sync_update_node(node, repo_name):
    can_sync, image_name = can_process_node(node)
    if can_sync:
        repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
        if should_rebuild_image_and_sync(node, repo_name):
            records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": True}})
            node["dockerfile_content"] = get_data_from_repository(repository, node["dockerfile_repo_path"])
            parent_img_name, requirements_list = parse_dockerfile(node["dockerfile_content"])
            parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
            if parent_node is None:                        # if the parent node does not exist
                logging.error(f'''Failed to sync image: {node["img_name"]}:{node["tag"]}. Error: Parent Not Found''')
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                return 1
            node["files"] = get_dependencies(repository, requirements_list)
            parameter = get_parameters(node)
            status = build_image(parameter)
            if status == "Success":
                make_redeployments(node)                                               # redeploying the deployments
                if parent_node["_id"] != node["parent"]:  # if the parent has changed in the new version of the dockerfile and the new parent exists
                    old_parent_node = records.find_one({"_id": node["parent"]})
                    old_parent_node["children"].erase(node["_id"])
                    parent_node["children"].append(node["_id"])
                    records.replace_one({"_id": old_parent_node["_id"]}, old_parent_node)
                    records.replace_one({"_id": parent_node["_id"]}, parent_node)
                node["commit_id"] = get_commits_sha(repository)                                         # updating the commit sha of the node.
                child_node_to_status = asyncio.run(multiple_docker_build(node["children"]))     # rebuilding all its children.
                for child_id in node["children"]:
                    dfs_update_node(child_id, child_node_to_status)
                node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
            else:
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                return 1
        node["is_locked"] = False
        node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
        records.replace_one({"_id": node["_id"]}, node)
        return 0
    else:
        return 2, image_name


'''
Explanation for add_new_component function:

The function takes input the repo_name and a dictionary component_name_to_dockerfile_path which maps the component-name to its associated dockerfile path.
It checks whether there exists any component whose image does not exist. If Yes, it rebuilds its image and stores its meta-data in the mongoDB database.
Also, takes care of the edge cases like if the parent node of that image does not exist. In such case the component cannot be built.
'''


def add_new_component(repo_name, component_name_to_dockerfile_path):          # components_dictionary --> dictionary which maps component_name to dockerfile_repo_path
    for component in component_name_to_dockerfile_path.keys():
        if records.count_documents({"component_name": component}) == 0:
            repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
            name = 'poojan23/docker-bakery-system_' + component + ':1.0'
            new_node = treenode(name)
            element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
            new_node._id = element_with_highest_id["_id"] + 1
            new_node.repo_name = repo_name
            new_node.dockerfile_repo_path = component_name_to_dockerfile_path[component][1:]                              # this path is relative to the root path of repo.
            new_node.component_name = component
            new_node.dockerfile_content = get_data_from_repository(repository, new_node.dockerfile_repo_path)
            parent_name, requirements_list = parse_dockerfile(new_node.dockerfile_content)
            parent_data = parent_name.split(':')                                                     # parent_data-->list with 0th element image-name and 1st element tag
            parent_node = records.find_one({"img_name": parent_data[0], "tag": float(parent_data[1])})
            if parent_node is None:
                logging.info("Can't Add the Component! Parent does not Exist")
                continue
            new_node.parent = parent_node["_id"]        # storing the parent
            new_node.files = get_dependencies(repository, requirements_list)
            parent_node["children"].append(new_node._id)                            # storing the child
            new_node.commit_id = get_commits_sha(repository)                                        # storing the commit sha of the commit.
            parameter = get_parameters_from_treenode(new_node)
            status = build_image(parameter)
            if status == "Success":
                store_in_mongodb(new_node)
                records.replace_one({"_id": parent_node["_id"]}, parent_node)
            else:
                logging.error("Failed to add new component:", component)


'''
Explanation for dfs_upgrade_node function:

The function takes three arguments: one is the old_child_id --> id of the child node before upgrading the image, old_parent_node --> parent node of the old child, upgraded_parent_node --> upgraded version of the old_parent_node

       a            after upgrading node b                a                 
       b         --------------------------->        b        e            
     c   d                                         c   d    f   g               
when we upgrade node b, sibling node(node -> e) will be created and similarly its subtree will be created recursively.
I am just making a copy of subtree rooted at b by mapping the nodes of subtree of b with the nodes of subtree of its sibling(e).
So the new subtree is build in the following order, b is mapped to e ->  c is mapped to f -> d is mapped to g. Basically it's just DFS.
I am also maintaining a dictionary(old_img_to_new_img) to establish the siblings relationship between mapped nodes. 
The function takes care of the case, when the parent in the updated dockerfile does not exist.
'''


def dfs_upgrade_node(child_id, old_parent_node, upgraded_parent_node):                 # building the whole tree structure.
    old_child_node = records.find_one({"_id": child_id})
    new_child_node = copy.deepcopy(old_child_node)                          # making the copy of the old node
    repository = None
    if new_child_node["repo_name"]:
        repository = github_client.get_repo(f'''{os.getenv('REPO_BASE')}/{new_child_node["repo_name"]}''')
        dockerfile_content = get_data_from_repository(repository, new_child_node["dockerfile_repo_path"])           # taking data from GitHub repository
        parent_img_name, requirements_list = parse_dockerfile(dockerfile_content)
        parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
        new_child_node["files"] = get_dependencies(repository, requirements_list)
        if parent_node is None:
            return
        if parent_node["_id"] != old_parent_node["_id"]:
            upgraded_parent_node = parent_node
        new_child_node["dockerfile_content"] = dockerfile_content
    global next_id
    new_child_node["_id"] = next_id               # assigned id to the new child
    next_id += 1
    old_img_to_new_img[child_id] = new_child_node["_id"]
    new_child_node["dockerfile_content"] = update_parent_in_dockerfile(new_child_node, upgraded_parent_node)             # updating the dockerfile
    if new_child_node["repo_name"]:
        file = repository.get_contents(new_child_node["dockerfile_repo_path"])                 # updating the dockerfile in GitHub repo
        repository.update_file(file.path, "updated Dockerfile", new_child_node["dockerfile_content"], file.sha)
        new_child_node["commit_id"] = get_commits_sha(repository)                                   # storing the commit sha of the node.
    new_child_node["parent"] = upgraded_parent_node["_id"]                               # assigned parent to the new child node
    upgraded_parent_node["children"].append(new_child_node["_id"])                       # appending child to the new parent node
    highest_tag_node = records.find_one({"img_name": new_child_node["img_name"]}, sort=[("tag", -1)], limit=1)
    highest_tag = highest_tag_node["tag"]
    new_child_node["tag"] = round(highest_tag + 0.1, 10)            # incrementing the minor tag
    new_child_node["children"].clear()
    status = build_image(get_parameters(new_child_node))                 # building image
    if status == "Success":
        make_redeployments(new_child_node)                 # redeploying the components
        new_child_node["created_time"] = new_child_node["last_synced_time"] = new_child_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        for child_id in old_child_node["children"]:
            dfs_upgrade_node(child_id, old_child_node, new_child_node)
        new_child_node["sibling"] = highest_tag_node["_id"]
        records.insert_one(new_child_node)


'''
Explanation for sync_upgrade_node function:

This function takes the input an image node and the repo_name of the image of which it is a part of.
First it checks whether the image is can be synced or not by checking whether any of its ancestor is being processed currently by some other user. If yes we cannot sync the image now and throw an error. This is to avoid the race condition.
If the image can be synced, then it is checked whether should we rebuild the image by comparing the last-sync-time with the last commit time using the function should_rebuild_image_and_sync function.
If yes, the image is first locked to avoid race condition, then a new image is created which is the copy of the old image node but with different tag and updated dockerfile and requirements.txt content.
Then it parses the dockerfile and checks whether the parent of the image has changed. If it has changed, then we first check whether the changed parent image exists or not. If it exists then the newly created image node is assigned as child to the new parent node.
Then the image is rebuilt. If the status of rebuild of image is success, then its deployments are re-deployed and then its child images are rebuilt recursively using dfs_upgrade_node function.
At the end the lock is released to avoid deadlock.
'''


def sync_upgrade_node(node, repo_name):
    can_sync, image_name = can_process_node(node)
    if can_sync:
        repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
        if should_rebuild_image_and_sync(node, repo_name):                                # the files have changed, so we need to rebuild.
            new_node = copy.deepcopy(node)
            records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": True}})
            new_node["dockerfile_content"] = get_data_from_repository(repository, new_node["dockerfile_repo_path"])
            parent_img_name, requirements_list = parse_dockerfile(new_node["dockerfile_content"])
            parent_node = records.find_one({"img_name": parent_img_name.split(':')[0], "tag": float(parent_img_name.split(':')[1])})
            if parent_node is None:
                logging.error(f'''Failed to sync image: {node["img_name"]}:{node["tag"]}. Error: Parent Not Found''')
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                return 1
            new_node["files"] = get_dependencies(repository, requirements_list)
            new_node["created_time"] = new_node["last_synced_time"] = new_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
            element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
            new_node["_id"] = element_with_highest_id["_id"] + 1
            global next_id
            next_id = new_node["_id"] + 1
            old_img_to_new_img[node["_id"]] = new_node["_id"]
            new_node["tag"] = round(node["tag"] + 0.1, 10)          # updating the tag of the image by 0.1
            status = build_image(get_parameters(new_node))
            if status == "Success":
                make_redeployments(new_node)                               # redeploying the deployments
                new_node["sibling"] = node["_id"]                           # assigning sibling
                parent_node["children"].append(new_node["_id"])            # adding the new child to parent
                new_node["parent"] = parent_node["_id"]
                new_node["commit_id"] = get_commits_sha(repository)                                 # storing the commit sha of the commit.
                new_node["children"].clear()
                for child_id in node["children"]:                   # recursively building the children
                    dfs_upgrade_node(child_id, node, new_node)
                records.insert_one(new_node)
                records.replace_one({"_id": parent_node["_id"]}, parent_node)
            else:
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                return 1
            node["is_locked"] = False
            node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
            records.replace_one({"_id": node["_id"]}, node)
        return 0
    else:
        return 2, image_name


'''
Explanation for autosync_update_node function: 

The function takes the input the name of the repository that is to be synced.
The function first adds any new component that is present in the repository but not present in our image hierarchy.
Then the sync_update_node function is called for each component in the repository. The image node that is passed as parameter to dfs_update_node function is the image node with the latest tag.
'''


def autosync_update_node(repo_name):
    repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{repo_name}")
    shell_script = get_data_from_repository(repository, '/build-component.sh')
    component_name_to_dockerfile_path = parse_script(shell_script)
    add_new_component(repo_name, component_name_to_dockerfile_path)        # checking and building if new components are added
    for comp in component_name_to_dockerfile_path.keys():
        node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)      # finding the node with highest tag.
        sync_update_node(node, repo_name)             # syncing each component in the repository


'''
Explanation for delete_subtree function:

This function takes input the node_id of the image node whose subtree the user wants to delete.
It recursively deletes the images in the subtree of the node user wants to delete.
Also, when the image is deleted, the deployments that were made using that image are re-deployed using the latest version of that image.
'''


def delete_subtree(node_id):                                # this function deletes a node and its subtree.
    node = records.find_one({"_id": node_id})
    for child_id in node["children"]:                           # recursively deleting the children
        status = delete_subtree(child_id)
        if status == "Failed":
            return "Failed"
    parameters = {"img_name": node["img_name"], "tag": node["tag"]}
    status = delete_image(parameters)
    if status == "Success":                            # the node is deleted from the database only if the has been successfully deleted
        list_of_deployments = node["deployments"]
        img_name = node["img_name"]
        next_sibling_node = records.find_one({"sibling": node["_id"]})
        if next_sibling_node is not None:
            next_sibling_node["sibling"] = node["sibling"]
            records.replace_one({"_id": next_sibling_node["_id"]}, next_sibling_node)
        parent_node = records.find_one({"_id": node["parent"]})
        parent_node["children"].remove(node["_id"])
        records.replace_one({"_id": parent_node["_id"]}, parent_node)
        records.delete_one({"_id": node["_id"]})
        redeploy_using_latest_img(list_of_deployments, img_name)
    return status


'''
Explanation for redeploy_using_latest_img function:
This function is called when the User wants to delete an image and its deployments are to be re-deployed using the latest version of that image.
The function takes input the deployments_list that were made using the image the user wants to delete. Also, it takes input the image name.
The function finds the image with same image name and with latest tag and re-deploy the deployments_list using that version of image. 
'''


def redeploy_using_latest_img(deployments_list, img_name):
    latest_sibling_node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)  # re-deploying using the latest sibling node.
    if latest_sibling_node is not None:
        ''' copying the deployments that were made using older image into latest sibling's deployments.
            Then re-deploying those deployments using the latest sibling
            After re-deploying, appending the deployments that were actually made by the latest sibling node prior to deletion of the node.'''
        latest_sibling_deployments = latest_sibling_node["deployments"]
        latest_sibling_node["deployments"] = deployments_list
        make_redeployments(latest_sibling_node)
        for element in latest_sibling_deployments:
            if element not in latest_sibling_node["deployments"]:
                latest_sibling_node["deployments"].append(element)
        records.replace_one({"_id": latest_sibling_node["_id"]}, latest_sibling_node)


'''
This function takes input an image-node and a dictionary: image_name_to_deployments_list and updates the list of deployments using an image in the mongo-db database.
'''


def replace_document(node, image_name_to_deployments_list):
    node["deployments"].clear()
    img_name_with_tag = node["img_name"] + ':' + str(node["tag"])
    if img_name_with_tag in image_name_to_deployments_list.keys():
        node["deployments"] = image_name_to_deployments_list[img_name_with_tag]
    records.replace_one({"_id": node["_id"]}, node)


'''
Explanation for get_k8s_deployments function:

This function calls the API get_deployments and passes the argument: a dictionary with env as prod.
The API returns a dictionary which that maps the image name to the list of deployments that were made using that image in the env: prod
The function also does the required exception handling if the connection to API server fails.
Using the dictionary returned by API, the function updates the data in the database using ThreadPoolExecutor which helps to speed-up the process of updating it in the database.
'''


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
    # replacing the node-data in DB concurrently
    executor = ThreadPoolExecutor(max_workers=None)
    futures = [executor.submit(replace_document, node, dictionary) for node in list_nodes]
    # Wait for all futures to complete
    for future in futures:
        future.result()
    executor.shutdown()


'''
Explanation for make_redeployments function:

The function takes input the image-node whose deployments are to be re-deployed.
It calls an API deploy_component by passing the required parameters.
The API re-deploys the deployments using Helm-Chart. The API returns a dictionary containing the status of the re-deployment of the deployment.
The function returns the status of the re-deployment.
'''


def make_redeployments(node):                          # this function re-deploy all the deployments that were made using this node(image).
    for deployment in node["deployments"]:
        parameters = {"image_name": node["img_name"], "tag": node["tag"], "component_name": node["component_name"], "deployment_name": deployment["deployment_name"]}
        response = requests.post("http://127.0.0.1:9000/deploy_component", data=parameters)
        response_dictionary = response.json()
        if (response.status_code == 200) and (response_dictionary["status"] == "Success"):
            logging.info(f''' Deployment: {deployment["deployment_name"]} deployed Successfully using Image: {node["img_name"]}:{node["tag"]}''')
        else:
            logging.info(f'''Failed to re-deploy {deployment["deployment_name"]}''')


'''
Explanation for store_in_mongodb function:

This function takes input a treenode object image node. It first converts the treenode object to json and then it converts the json to python dictionary.
This dictionary is then stored in mongoDB.
'''


def store_in_mongodb(node):                               # to be used to store the tree-node object in mongodb.
    json_data = json.dumps(node, default=lambda o: o.__dict__, indent=4)  # converting tree object to json
    json_data = json.loads(json_data)  # converting json to python dictionary
    records.insert_one(json_data)


'''
Explanation for get_data_from-repository:

This function takes input the repository object which is used to access the github repository and the repository path of the file.
The function returns the contents of the file in the string format.
'''


def get_data_from_repository(repository, file_path):        # fetches the data from github repository from the provided file_path
    file = repository.get_contents(file_path)  # storing the contents of Dockerfile
    response = requests.get(file.download_url)
    content = str(response.content, 'UTF-8')
    return content


'''
Explanation for update_parent_in_dockerfile function:

This function takes input child image node and its parent image node.
It updates the parent-image name in the dockerfile of the child image node by parsing the dockerfile.
The function also takes care of the multi-stage docker build by updating the last line containing 'FROM' statement.
Returns the updated dockerfile in string format.
'''


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


'''
Explanation for get_parameters_from_treenode function:

This function takes a image node of treenode object type and returns the parameters that are required to build image.
For the image that is a part of a repository the parameters are: repo_name, dockerfile content, dockerfile_path, component_name and tag.
For the image that is not a part of a repository the parameters are: dockerfile content, img_name, tag and requirements.txt content
'''


def get_parameters_from_treenode(tree_node):
    if tree_node.repo_name:
        parameter = {"repo_name": tree_node.repo_name, "dockerfile": tree_node.dockerfile_content,
                     "dockerfile_path": tree_node.dockerfile_repo_path, "component_name": tree_node.component_name,
                     "tag": tree_node.tag}
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


'''
The function takes input a repository object which is used to access the repository and the list of paths of requirements.txt
It returns a list of dictionary containing dependency_name, dependency_repo_path and content of that file.
'''


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


'''
Explanation for async_build_image function:

This function takes input the aiohttp session and a dictionary parameter returned by get_parameters function.
The 
If the image has a repository of which it is a part of, then build_component_image_api is called. Else, build_non_component_image_api is called.
The API returns a dictionary which contains a job_id, which is used by the poll_for_docker_build function to poll and get the status of the docker build process getting executed on the API server.
The function along handles the exception when the connection to the API server fails.
This functions takes the status(success or failed) of the docker build process from the poll_for_docker_build process and returns it.
'''


async def async_build_image(session, parameter):
    if "repo_name" in parameter.keys():
        img_name = f'''poojan23/docker-bakery-system_{parameter["component_name"]}'''
        response = await session.post("http://127.0.0.1:9000/build_component_image_api", data=parameter)
    else:
        img_name = parameter["img_name"]
        response = await session.post("http://127.0.0.1:9000/build_non_component_image_api", data=parameter)
    json_response = await response.json()
    if (response.status != 200) or ("job_id" not in json_response):
        logging.error(
            "API for Docker build failed, status: " + str(response.status) + ", image:", img_name)
        return "Failed"
    status = poll_for_docker_build(img_name, json_response["job_id"])
    return status


'''
Explanation for multiple_docker_build function:

This function takes argument a list of node-ids whose image the user wants to rebuild.
It creates a list of schedules of build-image tasks that will be executed asynchronously.
It returns a dictionary node_id_to_status which maps the node-id to the status of the docker build of that image.
'''


async def multiple_docker_build(node_ids):
    tasks = []
    node_id_to_status = {}
    async with aiohttp.ClientSession() as session:
        for node_id in node_ids:
            node = records.find_one({"_id": node_id})
            parameter = get_parameters(node)
            tasks.append(asyncio.create_task(async_build_image(session, parameter)))
        responses = await asyncio.gather(*tasks)
    for index in range(len(node_ids)):
        node_id_to_status[node_ids[index]] = responses[index]
    return node_id_to_status


'''
Explanation for dfs_update_node:
This function takes input a node_id, a dictionary node_id_to_status and a boolean variable to_update_last_sync_time
If the re-build status of the node is Success, then only the function will redeploy the deployments that were made using that image and it will recursively call the same function for its child images.
For the child images, the images are first re-built asynchronously and then the dfs_update_node function is called recursively for child images.
'''


def dfs_update_node(node_id, node_id_to_status, to_update_last_sync_time=True):          # recursively re-building the subtree on update of the parent node
    # All the nodes that are at the same level are build asynchronously.
    # variable to_update_last_sync_time is kept because we will use this function for edit node functionality too.
    child_node = records.find_one({"_id": node_id})
    if node_id_to_status[node_id] == "Success":
        make_redeployments(child_node)                 # redeploying the deployments

        child_node_id_to_status = asyncio.run(multiple_docker_build(child_node["children"]))            # asyncronous re-building images.

        for child_id in child_node["children"]:
            dfs_update_node(child_id, child_node_id_to_status, to_update_last_sync_time)
        child_node["last_updated_time"] = str(datetime.utcnow().replace(microsecond=0))
        if to_update_last_sync_time:
            child_node["last_synced_time"] = str(datetime.utcnow().replace(microsecond=0))
            records.replace_one({"_id": child_node["_id"]}, child_node)


'''
The update_dictionary function takes two parameters: dictionary1 and dictionary2 and recursively overwrites the value of a key that is present in both the dictionary in dictionary1 from dictionary2.
The function takes care of the case that the value of a key itself can be a dictionary. For this the function is called recursively.
'''


def update_dictionary(dictionary1, dictionary2):            # this function overwrites the values of keys that are common from dictionary2 into dictionary1.
    for key, value in dictionary2.items():
        if key in dictionary1:
            if isinstance(dictionary1[key], dict) and isinstance(value, dict):
                update_dictionary(dictionary1[key], value)
            elif isinstance(dictionary1[key], list) and isinstance(value, list):
                dictionary1[key].extend([v for v in value if v not in dictionary1[key]])
            else:
                dictionary1[key] = value
        else:
            dictionary1[key] = value
    return dictionary1


'''
Explanation for get_deployments_from_helm_repo function:

This function parses the helm-repository and makes a map of image-name to list of deployments using that image.
The function creates a dictionary of the values.yaml file present in the root directory of the helm repository.
Then it goes inside the releases folder of the repo and parses all the releases directories.
For each release, it takes its values.yaml file and overwrites the values.yaml file present in the root directory of the repository. Then it goes inside the env directory, takes its values.yaml file and overwrites the values.yaml file present in the root directory.
It then creates a dictionary, which has image name as key and list of dictionary containing deployment names and the environment in which they were deployed. 
It then stores the dictionary for each image in the mongoDB database
'''


def get_deployments_from_helm_repo():        # This function parses the helm-repository and returns the dictionary { img_name --> [{deployment_name, env}] }
    image_to_deployment = {}
    helm_repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/helm-repository")
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
    executor = ThreadPoolExecutor(max_workers=None)
    nodes_list = list(records.find({}))
    futures = [executor.submit(replace_document, node, image_to_deployment) for node in nodes_list]
    # Wait for all futures to complete
    for future in futures:
        future.result()
    executor.shutdown()


'''
Explanation for can_be_deleted function:
This function takes input a node that the user wants to delete and then checks in the subtree of that node, that whether there is any sibling image of each node using which the deployments can be re-deployed. If yes then when the node(image) is deleted, its deployments are redeployed using the latest version of that image.
If a image node does not contain any sibling image, then the subtree cannot be deleted as it still has some deployments running.
'''


def can_be_deleted(node):
    ans = True                      # initializing the ans to True
    if (node["sibling"] is None) and (len(node["deployments"]) != 0):
        return False
    else:
        for child_id in node["children"]:
            child_node = records.find_one({"_id": child_id})
            ans = ans and can_be_deleted(child_node)
    return ans
