import re, pytz, copy, json, time, os
from datetime import datetime
from dotenv import load_dotenv
import pymongo
from myapp.models import treenode, dependencies
from github import Github
import requests


load_dotenv()
# client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
client = pymongo.MongoClient(os.getenv("MONGODB_CONNECTION_STRING"))
db = client.get_database('myDB')
records = db['Images']
root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'
my_git = Github(os.getenv("GITHUB_ACCESS_TOKEN"))
old_to_mirror = {}                                      # dictionary to map the upgraded nodes with their sibling.
next_id = records.count_documents({}) + 1


def create_hierarchy(data, parent_id=None):     # to create hierarchy
    hierarchy = []
    for item in data:
        if item["parent"] == parent_id:
            children = create_hierarchy(data, parent_id=item["_id"])
            item["children"] = children
            hierarchy.append(item)
    return hierarchy


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
    requirements_path = None
    dockerfile = dockerfile.splitlines()
    for lines in dockerfile:
        if lines.startswith('FROM'):
            parent = lines.split()[1]
            if parent.find(':') == -1:
                parent = parent + ':1.0'
        match = re.match(r'COPY\s+([^\s]+/requirements.txt)\s+\.', lines)  # requirements.txt path
        if match:
            requirements_path = match.group(1)
    return requirements_path


def convert_to_indian_time(utc_time_zone):
    india_timezone = pytz.timezone('Asia/Kolkata')
    india_time = pytz.utc.localize(utc_time_zone).astimezone(india_timezone)
    india_time = india_time.strftime('%Y-%m-%d %H:%M:%S')
    india_time = datetime.strptime(india_time, '%Y-%m-%d %H:%M:%S')    # datetime object
    return india_time


def build_image(parameter):
    if "repo_name" in parameter.keys():
        response = requests.post("http://127.0.0.1:9000/build_updated", data=parameter)
    else:
        response = requests.post("http://127.0.0.1:9000/build_no_component", data=parameter)
    response = response.json()
    print(response)
    # polling every 10 seconds
    parameter = {"job_id": response["job_id"]}
    while True:
        response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
        response = response.json()
        if response["status"] == "Success" or response["status"] == "Failed":
            return response["status"]
        time.sleep(5)


def delete_image(parameter):
    response = requests.post("http://127.0.0.1:9000/delete_node_api", data=parameter)
    response = response.json()
    if response["status"] == "Success":
        return "Success"
    else:
        return "Failed"


def sync_new_node(node, repo_name):
    repo_url = f"Poojan230103/{repo_name}"
    my_repo = my_git.get_repo(repo_url)
    var = node["dockerfile_repo_path"]  # check for dockerfile
    commits = my_repo.get_commits(path=var)
    flag = False
    utc_time = commits[0].commit.committer.date
    t = convert_to_indian_time(utc_time)
    last_sync_time = node["last_synced_time"]  # in string format
    last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
    last_sync_time = convert_to_indian_time(last_sync_time)
    print("dockerfile", t, last_sync_time)
    if t > last_sync_time:
        flag = True
    for dep in node["files"]:  # check for requirements.txt
        var = dep["deps_repo_path"]
        commits = my_repo.get_commits(path=var)
        utc_time = commits[0].commit.committer.date
        t = convert_to_indian_time(utc_time)
        last_sync_time = node["last_synced_time"]  # in string format
        last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
        last_sync_time = convert_to_indian_time(last_sync_time)
        print("requirements.txt", t, last_sync_time)
        if t > last_sync_time:
            flag = True
    if flag:                                # the files have changed, so we need to rebuild.
        new_node = copy.deepcopy(node)
        file = my_repo.get_contents(new_node["dockerfile_repo_path"])  # storing the contents of dockerfile
        response = requests.get(file.download_url)
        contents = response.content
        contents = str(contents, 'UTF-8')
        new_node["dockerfile_content"] = contents
        contents = contents.splitlines()
        parent = None
        for line in contents:
            if line.__contains__("FROM"):
                parent = line.split()[1]
        repo_parent_node = records.find_one({"img_name": parent.split(':')[0], "tag": float(parent.split(':')[1])})
        if repo_parent_node is None:
            return 1
        new_node["files"].clear()
        for dep in node["files"]:
            file = my_repo.get_contents(dep["deps_repo_path"])   # updating the contents of requirements.txt
            response = requests.get(file.download_url)
            contents = response.content
            contents = str(contents, 'UTF-8')
            dep["dependency_content"] = contents
            new_node["files"].append(dep)
        new_node["created_time"] = new_node["last_synced_time"] = new_node["last_updated_time"] = str(datetime.now().replace(microsecond=0))
        element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
        new_node["_id"] = element_with_highest_id["_id"] + 1
        global next_id
        next_id = new_node["_id"] + 1
        old_to_mirror[node["_id"]] = new_node["_id"]
        new_node["tag"] = round(node["tag"] + 0.1, 10)          # updating the tag of the image
        parameter = {                                           # building new docker image
            "repo_name": new_node["repo_name"],
            "dockerfile": new_node["dockerfile_content"], "dockerfile_path": new_node["dockerfile_repo_path"],
            "component_name": new_node["component_name"], "tag": new_node["tag"]}
        build_image(parameter)
        # -------------------------------------- call redeploy_component function here --------------------------------- #
        redeploy_components(new_node)
        # --------------------------------------  --------------------------------- #
        new_node["sibling"] = node["_id"]                           # assigning sibling
        # parent_node = records.find_one({"_id": node["parent"]})
        parent_node = repo_parent_node
        parent_node["children"].append(new_node["_id"])            # adding the new child to parent
        new_node["parent"] = parent_node["_id"]
        commits = my_repo.get_commits(sha=my_repo.default_branch)[0]
        new_node["commit_id"] = commits.sha                                 # storing the commit sha of the commit.
        new_node["children"].clear()
        for children in node["children"]:  # recursively building the children
            dfs_new_node(children, node, new_node)
        records.insert_one(new_node)
        records.replace_one({"_id": parent_node["_id"]}, parent_node)
    node["last_synced_time"] = str(datetime.now().replace(microsecond=0))
    records.replace_one({"_id": node["_id"]}, node)
    return 0


def sync_same_node(node, repo_name):
    repo_url = f"Poojan230103/{repo_name}"
    my_repo = my_git.get_repo(repo_url)
    var = node["dockerfile_repo_path"]  # check for dockerfile
    commits = my_repo.get_commits(path=var)
    flag = False
    utc_time = commits[0].commit.committer.date
    t = convert_to_indian_time(utc_time)
    last_sync_time = node["last_synced_time"]  # in string format
    last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
    last_sync_time = convert_to_indian_time(last_sync_time)
    print(t, last_sync_time)
    if t > last_sync_time:
        flag = True
    # check for requirements.txt
    for dep in node["files"]:
        var = dep["deps_repo_path"]
        commits = my_repo.get_commits(path=var)
        utc_time = commits[0].commit.committer.date
        t = convert_to_indian_time(utc_time)
        last_sync_time = node["last_synced_time"]  # in string format
        last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
        last_sync_time = convert_to_indian_time(last_sync_time)
        if t > last_sync_time:
            flag = True
    if flag:
        file = my_repo.get_contents(node["dockerfile_repo_path"])  # storing the contents of dockerfile
        response = requests.get(file.download_url)
        contents = response.content
        contents = str(contents, 'UTF-8')
        node["dockerfile_content"] = contents
        contents = contents.splitlines()
        parent = None
        for line in contents:
            if line.__contains__("FROM"):
                parent = line.split()[1]
        repo_parent_node = records.find_one({"img_name": parent.split(':')[0], "tag": float(parent.split(':')[1])})
        if repo_parent_node is None:
            return 1
        if repo_parent_node["_id"] != node["parent"]:           # if the parent has changed in the new version of the dockerfile and the new parent exists
            old_parent_node = records.find_one({"_id": node["parent"]})
            old_parent_node["children"].erase(node["_id"])
            repo_parent_node["children"].append(node["_id"])
            records.replace_one({"_id": old_parent_node["_id"]}, old_parent_node)
            records.replace_one({"_id": repo_parent_node["_id"]}, repo_parent_node)
        updated_dependency = []
        for dep in node["files"]:
            file = my_repo.get_contents(dep["deps_repo_path"])   # updating the contents of requirements.txt
            response = requests.get(file.download_url)
            contents = response.content
            contents = str(contents, 'UTF-8')
            dep["dependency_content"] = contents
            updated_dependency.append(dep)
        node["files"].clear()
        node["files"] = updated_dependency
        parameter = {"repo_name": node["repo_name"], "dockerfile": node["dockerfile_content"], "dockerfile_path": node["dockerfile_repo_path"], "component_name": node["component_name"], "tag": node["tag"]}
        build_image(parameter)
        # -------------------------------------- call redeploy_component function here --------------------------------- #
        redeploy_components(node)
        # --------------------------------------  --------------------------------- #
        commits = my_repo.get_commits(sha=my_repo.default_branch)[0]
        node["commit_id"] = commits.sha                                     # updating the commit sha of the node.
        for ids in node["children"]:
            dfs_same_node(ids)
        node["last_updated_time"] = str(datetime.now().replace(microsecond=0))
    node["last_synced_time"] = str(datetime.now().replace(microsecond=0))
    records.replace_one({"_id": node["_id"]}, node)
    return 0


def add_new_component(repo_name, components):
    for comp in components.keys():
        if records.count_documents({"component_name": comp}) == 0:
            my_repo = my_git.get_repo(f"Poojan230103/{repo_name}")
            name = 'poojan23/docker-bakery-system_' + comp + ':1.0'
            new_node = treenode(name)
            element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)             # finding the highest id
            new_node._id = element_with_highest_id["_id"] + 1
            new_node.repo_name = repo_name  # name of repository
            docker_path = root_path + '/' + repo_name + components[comp][1:]  # local path of dockerfile
            new_node.dockerfile_local_path = docker_path
            new_node.dockerfile_repo_path = docker_path.split(repo_name)[1]  # this path is relative to the root path of repo.
            new_node.component_name = comp
            file = my_repo.get_contents(new_node.dockerfile_repo_path)  # storing the contents of dockerfile
            response = requests.get(file.download_url)
            dockerfile_contents = response.content
            dockerfile_contents = str(dockerfile_contents, 'UTF-8')
            new_node.dockerfile_content = dockerfile_contents
            parent = None
            requirements_path = None
            dockerfile_contents = dockerfile_contents.splitlines()
            # file = open(docker_path, 'r')  # reading the dockerfile
            for lines in dockerfile_contents:
                if lines.startswith('FROM'):
                    parent = lines.split()[1]
                    if parent.find(':') == -1:
                        parent = parent + ':1.0'
                match = re.match(r'COPY\s+([^\s]+/requirements.txt)\s+\.', lines)  # requirements.txt path
                if match:
                    requirements_path = match.group(1)
            par_data = parent.split(':')
            par = records.find_one({"img_name": par_data[0], "tag": float(par_data[1])})
            if par is None:
                continue
            new_node.parent = par["_id"]  # storing the parent
            if requirements_path:  # this path is relative to the .sh file
                new_dep = dependencies("requirements.txt")
                req_curr_path = root_path + repo_name + requirements_path[1:]  # requirements.txt local path
                new_dep.deps_local_path = req_curr_path
                new_dep.deps_repo_path = req_curr_path.split(repo_name)[1]     # requirements.txt path relative to root path of the repo
                file = my_repo.get_contents(new_dep.deps_repo_path)             # storing the contents of requirements.txt
                response = requests.get(file.download_url)
                contents = response.content
                contents = str(contents, 'UTF-8')
                new_dep.dependency_content = contents
                new_node.files.append(new_dep)
            par["children"].append(new_node._id)  # storing the child
            commits = my_repo.get_commits(sha=my_repo.default_branch)[0]
            new_node.commit_id = commits.sha  # storing the commit sha of the commit.
            parameter = {
                "repo_name": new_node.repo_name,
                "dockerfile": new_node.dockerfile_content, "dockerfile_path": new_node.dockerfile_repo_path,
                "component_name": new_node.component_name, "tag": new_node.tag}
            build_image(parameter)
            json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
            json_data = json.loads(json_data)
            records.insert_one(json_data)
            records.replace_one({"_id": par["_id"]}, par)


def dfs_new_node(old_child_id, old_par_node, new_par_node):       # building the whole tree structure.
    old_child_node = records.find_one({"_id": old_child_id})
    new_child_node = copy.deepcopy(old_child_node)
    if new_child_node["repo_name"]:
        child_repo = my_git.get_repo(f'''Poojan230103/{new_child_node["repo_name"]}''')
        file = child_repo.get_contents(new_child_node["dockerfile_repo_path"])
        response = requests.get(file.download_url)
        dockerfile_contents = response.content
        contents = str(dockerfile_contents, 'UTF-8')
        contents = contents.splitlines()
        parent = None
        for line in contents:
            if line.__contains__("FROM"):
                parent = line.split()[1]
        repo_parent_node = records.find_one({"img_name": parent.split(':')[0], "tag": float(parent.split(':')[1])})
        if repo_parent_node is None:
            return
        elif repo_parent_node["_id"] != old_par_node["_id"]:
            new_par_node = repo_parent_node
        new_child_node["dockerfile_content"] = '\n'.join(contents)
    global next_id
    new_child_node["_id"] = next_id               # assigned id to the new child
    next_id += 1
    old_to_mirror[old_child_id] = new_child_node["_id"]
    # updating the dockerfile
    content = new_child_node["dockerfile_content"].splitlines()
    line_num = -1
    cnt = 0
    for line in content:
        if line.__contains__("FROM"):
            line_num = cnt
        cnt += 1
    if line_num != -1:
        old_par_name = content[line_num].split()[1]
        new_par_name = new_par_node["img_name"] + ':' + str(new_par_node["tag"])
        content[line_num] = content[line_num].replace(old_par_name, new_par_name)
    content = '\n'.join(content)
    new_child_node["dockerfile_content"] = content
    if new_child_node["repo_name"]:
        my_repo = my_git.get_repo(f'''Poojan230103/{new_child_node["repo_name"]}''')
        file = my_repo.get_contents(new_child_node["dockerfile_repo_path"])                 # updating the dockerfile in Github repo
        my_repo.update_file(file.path, "updated Dockerfile", content, file.sha)
        time.sleep(5)
        commits = my_repo.get_commits(sha=my_repo.default_branch)[0]
        new_child_node["commit_id"] = commits.sha  # storing the commit sha of the node.
    new_child_node["parent"] = new_par_node["_id"]             # assigned parent to the new child node
    new_par_node["children"].append(new_child_node["_id"])     # appending child to the new parent node
    highest_tag_node = records.find_one({"img_name": new_child_node["img_name"]}, sort=[("tag", -1)], limit=1)
    highest_tag = highest_tag_node["tag"]
    new_child_node["tag"] = round(highest_tag + 0.1, 10)
    new_child_node["children"].clear()
    # building image
    if new_child_node["repo_name"]:
        parameter = {"repo_name": new_child_node["repo_name"], "dockerfile": new_child_node["dockerfile_content"], "dockerfile_path": new_child_node["dockerfile_repo_path"], "component_name": new_child_node["component_name"], "tag": new_child_node["tag"]}
    else:
        requirements = None
        for dep in new_child_node["files"]:
            if dep["name"] == "requirements.txt":
                requirements = dep["dependency_content"]
        parameter = {"dockerfile": new_child_node["dockerfile_content"], "img_name": new_child_node["img_name"], "tag": new_child_node["tag"], "requirements": requirements}
    build_image(parameter)
    # -------------------------------------- call redeploy_component function here --------------------------------- #
    redeploy_components(new_child_node)
    # --------------------------------------  --------------------------------- #
    new_child_node["created_time"] = new_child_node["last_synced_time"] = new_child_node["last_updated_time"] = str(datetime.now().replace(microsecond=0))
    for child in old_child_node["children"]:
        dfs_new_node(child, old_child_node, new_child_node)
    first_mirror_img = True
    if new_child_node["sibling"] and not first_mirror_img:
        new_child_node["sibling"] = old_to_mirror[new_child_node["sibling"]]                # establishing parent child relation in new images
    else:
        new_child_node["sibling"] = highest_tag_node["_id"]
        first_mirror_img = False
    records.insert_one(new_child_node)


def dfs_same_node(node_id, update_time=True):             # recursively re-building the subtree on update of the parent node
    child_node = records.find_one({"_id": node_id})
    if child_node["component_name"]:
        parameter = {"repo_name": child_node["repo_name"], "component_name": child_node["component_name"], "tag": child_node["tag"], "dockerfile": child_node["dockerfile_content"], "dockerfile_path": child_node["dockerfile_repo_path"]}
        status = build_image(parameter)
        for ids_child in child_node["children"]:
            dfs_same_node(ids_child)
    else:
        requirements = None
        for dep in child_node["files"]:
            if dep["name"] == "requirements.txt":
                requirements = dep["dependency_content"]
        parameter = {"dockerfile": child_node["dockerfile_content"], "img_name": child_node["img_name"], "tag": child_node["tag"], "requirements": requirements}
        status = build_image(parameter)
        # -------------------------------------- call redeploy_component function here --------------------------------- #
        redeploy_components(child_node)
        # --------------------------------------  --------------------------------- #
        for ids_child in child_node["children"]:
            dfs_same_node(ids_child)
    if update_time:
        child_node["last_updated_time"] = child_node["last_synced_time"] = str(datetime.now().replace(microsecond=0))
        records.replace_one({"_id": child_node["_id"]}, child_node)


def autosync_new_node(repo_name):
    my_repo = my_git.get_repo(f"Poojan230103/{repo_name}")
    file = my_repo.get_contents('/build-component.sh')
    response = requests.get(file.download_url)
    shell_script = str(response.content, 'UTF-8')
    components = parse_script(shell_script)
    add_new_component(repo_name, components)        # checking and building new components are added
    for comp in components.keys():
        node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)     # node --> the node with the highest tag
        sync_new_node(node, repo_name)


def autosync_same_node(repo_name):
    my_repo = my_git.get_repo(f"Poojan230103/{repo_name}")
    file = my_repo.get_contents('/build-component.sh')
    response = requests.get(file.download_url)
    shell_script = str(response.content, 'UTF-8')
    components = parse_script(shell_script)
    add_new_component(repo_name, components)        # checking and building if new components are added
    for comp in components.keys():
        node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)      # finding the node with highest tag.
        sync_same_node(node, repo_name)


def delete_subtree(node_id):                                # this function deletes a node and its subtree.
    node = records.find_one({"_id": node_id})
    for child_id in node["children"]:
        delete_subtree(child_id)
    parameters = {"img_name": node["img_name"], "tag": node["tag"]}
    status = delete_image(parameters)
    if status == "Success":
        next_sibling_node = records.find_one({"sibling": node["_id"]})
        if next_sibling_node is not None:
            next_sibling_node["sibling"] = node["sibling"]
            records.replace_one({"_id": next_sibling_node["_id"]}, next_sibling_node)
        parent_node = records.find_one({"_id": node["parent"]})
        parent_node["children"].remove(node["_id"])
        records.replace_one({"_id": parent_node["_id"]}, parent_node)
        records.delete_one({"_id": node["_id"]})


def redeploy_components(node):                          # this function re-deploy all the deployments that were made using this image.
    for deployment in node["deployments"]:
        parameters = {"image_name": node["img_name"], "tag": node["tag"], "component_name": node["component_name"], "deployment_name": deployment["deployment_name"]}
        requests.post("http://127.0.0.1:9000/deploy_component", data=parameters)
