import re,pytz,copy, json, time, os
from datetime import datetime
import pymongo
from myapp.models import treenode, dependencies
from github import Github
import requests


client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('myDB')
records = db['Images']

root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'


def create_hierarchy(data, parent_id=None):     # to create hierarchy
    hierarchy = []
    for item in data:
        if item["parent"] == parent_id:
            children = create_hierarchy(data, parent_id=item["_id"])
            item["children"] = children
            hierarchy.append(item)
    return hierarchy


def parse_script(script_path):
    components = {}
    current_component = None
    with open(script_path, 'r') as script_file:
        for line in script_file:
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


def parse_dockerfile(dockerfile_path):
    parent = None
    requirements_path = None
    file = open(dockerfile_path, 'r')  # reading the dockerfile
    for lines in file:
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


old_to_mirror = {}
next_id = records.count_documents({}) + 1


def build_component(parameter):
    response = requests.post("http://127.0.0.1:9000/build", data=parameter)
    response = response.json()
    print(response)
    # polling every 10 seconds
    parameter = {"job_id": response["job_id"]}
    while True:
        response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
        response = response.json()
        if response["status"] == "Success" or response["status"] == "Failed":
            print(response["status"])
            break
        time.sleep(5)


def dfs_newnode(old_child_id, old_par_node, new_par_node):       # building the whole tree structure.
    old_child_node = records.find_one({"_id": old_child_id})
    new_child_node = copy.deepcopy(old_child_node)
    global next_id
    new_child_node["_id"] = next_id               # assigned id to the new child
    next_id += 1
    old_to_mirror[old_child_id] = new_child_node["_id"]
    # updating the dockerfile
    f = open(new_child_node["dockerfile_local_path"], 'r')
    content = f.readlines()
    line_num = -1
    cnt = 0
    print(content)
    for line in content:
        if line.__contains__("FROM"):
            line_num = cnt
        cnt += 1
    if line_num != -1:
        old_par_name = content[line_num].split()[1]
        new_par_name = new_par_node["img_name"] + ':' + str(new_par_node["tag"])
        content[line_num] = content[line_num].replace(old_par_name, new_par_name)
    f.close()
    f = open(new_child_node["dockerfile_local_path"], 'w')

    f.writelines(content)
    print(content)
    f.close()

    os.system(f''' cd {root_path}/{new_child_node["repo_name"]}
                   git add .
                   git commit -m "upgraded Image"
                   git push -u origin main
            ''')

    new_child_node["parent"] = new_par_node["_id"]             # assigned parent to the new child node
    new_par_node["children"].append(new_child_node["_id"])     # appending child to the new parent node
    highest_tag_node = records.find_one({"img_name": new_child_node["img_name"]}, sort=[("tag", -1)], limit=1)
    highest_tag = highest_tag_node["tag"]
    print(type(highest_tag))
    new_child_node["tag"] = round(highest_tag + 0.1, 10)
    print(new_child_node["tag"])
    new_child_node["children"].clear()
    # building image
    parameter = {
        "repo_name": new_child_node["repo_name"],
        "component_name": new_child_node["component_name"],
        "tag": new_child_node["tag"],
    }
    build_component(parameter)
    # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
    # response = response.json()
    # print(response)
    # # polling every 10 seconds
    # parameter = {"job_id": response["job_id"]}
    # while True:
    #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
    #     response = response.json()
    #     if response["status"] == "Success" or response["status"] == "Failed":
    #         print(response["status"])
    #         break
    #     time.sleep(10)

    new_child_node["created_time"] = new_child_node["last_synced_time"] = new_child_node["last_updated_time"] = str(datetime.now().replace(microsecond=0))
    for child in old_child_node["children"]:
        dfs_newnode(child, old_child_node, new_child_node)
    print(new_child_node["sibling"])
    first_mirror_img = True
    if new_child_node["sibling"] and not first_mirror_img:
        new_child_node["sibling"] = old_to_mirror[new_child_node["sibling"]]                # establishing parent child relation in new images
    else:
        new_child_node["sibling"] = highest_tag_node["_id"]
        first_mirror_img = False
    records.insert_one(new_child_node)


def auto_sync_newnode(repo_name):
    print("hello Poojan")
    repo_url = f"Poojan230103/{repo_name}"  # to be taken from the config file
    mygit = Github("")
    myrepo = mygit.get_repo(repo_url)

    script_path = root_path + '/' + repo_name + '/build-component.sh'
    components = parse_script(script_path)
    for comp in components.keys():
        if records.count_documents({"component_name": comp}) == 0:
            name = 'docker-bakery-system/' + comp + ':1.0'
            new_node = treenode(name)
            new_node._id = records.count_documents({}) + 1
            new_node.repo_name = repo_name  # name of repository
            docker_path = root_path + repo_name + components[comp][1:]  # local path of dockerfile
            new_node.dockerfile_local_path = docker_path
            new_node.dockerfile_repo_path = docker_path.split(repo_name)[1]     # this path is relative to the root path of repo.
            new_node.component_name = comp
            parent = None
            requirements_path = None
            file = open(docker_path, 'r')  # reading the dockerfile
            for lines in file:
                if lines.startswith('FROM'):
                    parent = lines.split()[1]
                    if parent.find(':') == -1:
                        parent = parent + ':1.0'
                match = re.match(r'COPY\s+([^\s]+/requirements.txt)\s+\.', lines)  # requirements.txt path
                if match:
                    requirements_path = match.group(1)
            par_data = parent.split(':')
            par = records.find_one({"img_name": par_data[0], "tag": float(par_data[1])})
            new_node.parent = par["_id"]  # storing the parent
            if requirements_path:  # this path is relative to the .sh file
                new_dep = dependencies("requirements.txt")
                req_currpath = root_path + repo_name + requirements_path[1:]  # requirements.txt local path
                new_dep.deps_local_path = req_currpath
                new_dep.deps_repo_path = req_currpath.split(repo_name)[1]  # requirements.txt path relative to root path of the repo
                new_node.files.append(new_dep)
            par.children.append(new_node._id)  # storing the child
            parameter = {
                "repo_name": new_node.repo_name,
                "component_name": new_node.component_name,
                "tag": new_node.tag,
            }
            build_component(parameter)
            # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
            # response = response.json()
            # print(response)
            # # polling every 10 seconds
            # parameter = {"job_id": response["job_id"]}
            # while True:
            #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
            #     response = response.json()
            #     if response["status"] == "Success" or response["status"] == "Failed":
            #         print(response["status"])
            #         break
            #     time.sleep(10)
            json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
            json_data = json.loads(json_data)
            records.insert_one(json_data)
            records.replace_one({"_id": par["_id"]}, par)

        else:
            node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)
            # node --> the node with the highest tag
            var = node["dockerfile_repo_path"]  # docker file
            commits = myrepo.get_commits(path=var)
            flag = False
            utc_time = commits[0].commit.committer.date
            t = convert_to_indian_time(utc_time)
            last_sync_time = node["last_synced_time"]  # in string format
            last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')  # in datetime format
            last_sync_time = convert_to_indian_time(last_sync_time)
            print("dockerfile",t, last_sync_time)
            if t > last_sync_time:
                flag = True

            # check for requirements.txt
            for dep in node["files"]:
                var = dep["deps_repo_path"]
                commits = myrepo.get_commits(path=var)
                utc_time = commits[0].commit.committer.date
                t = convert_to_indian_time(utc_time)
                last_sync_time = node["last_synced_time"]  # in string format
                last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
                last_sync_time = convert_to_indian_time(last_sync_time)
                print("requirements.txt", t, last_sync_time)
                if t > last_sync_time:
                    flag = True

            if flag:
                os.system(f'''
                        cd {root_path}/{repo_name}
                        git pull origin ''')
                # we now have the updated repo on our local machine
                new_node = copy.deepcopy(node)
                new_node["created_time"] = new_node["last_synced_time"] = new_node["last_updated_time"] = str(datetime.now().replace(microsecond=0))
                global next_id
                new_node["_id"] = next_id
                next_id += 1
                old_to_mirror[node["_id"]] = new_node["_id"]
                highest_tag_node = records.find_one({"img_name": new_node["img_name"]}, sort=[("tag", -1)], limit=1)
                highest_tag = highest_tag_node["tag"]
                new_node["tag"] = round(highest_tag + 0.1, 10)  # updating the tag of the image
                print(new_node["tag"])
                # building new docker image
                parameter = {
                    "repo_name": new_node["repo_name"],
                    "component_name": new_node["component_name"],
                    "tag": new_node["tag"],
                }
                build_component(parameter)
                # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
                # response = response.json()
                # print(response)
                # # polling every 10 seconds
                # parameter = {"job_id": response["job_id"]}
                # while True:
                #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
                #     response = response.json()
                #     if response["status"] == "Success" or response["status"] == "Failed":
                #         print(response["status"])
                #         break
                #     time.sleep(10)

                new_node["sibling"] = node["_id"]  # assigning sibling
                parent_node = records.find_one({"_id": node["parent"]})
                parent_node["children"].append(new_node["_id"])
                new_node["parent"] = parent_node["_id"]
                new_node["children"].clear()

                # recursively building the children
                for children in node["children"]:
                    dfs_newnode(children, node, new_node)
                records.insert_one(new_node)
                records.replace_one({"_id": parent_node["_id"]}, parent_node)
            node["last_synced_time"] = str(datetime.now().replace(microsecond=0))
            records.replace_one({"_id": node["_id"]}, node)


def dfs_samenode(node_id):         # recursively re-building the subtree on update of the parent node
    childnode = records.find_one({"_id": node_id})
    if childnode["component_name"]:
        parameter = {"repo_name": childnode["repo_name"], "component_name": childnode["component_name"], "tag": childnode["tag"]}
        build_component(parameter)
        # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
        # response = response.json()
        # print(response)
        # parameter = {"job_id": response["job_id"]}
        # while True:
        #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
        #     response = response.json()
        #     if response["status"] == "Success" or response["status"] == "Failed":
        #         print(response["status"])
        #         break
        #     time.sleep(10)

        for ids_child in childnode["children"]:
            dfs_samenode(ids_child)
    else:
        parameter = {"dockerfile_local_path": childnode["dockerfile_local_path"],
                     "img_name": childnode["img_name"],
                     "tag": childnode["tag"]}
        response = requests.post("http://127.0.0.1:9000/build_no_comp", data=parameter)
        response = response.json()
        print(response)
        parameter = {"job_id": response["job_id"]}
        while True:
            response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
            response = response.json()
            if response["status"] == "Success" or response["status"] == "Failed":
                print(response["status"])
                break
            time.sleep(10)
        for ids_child in childnode["children"]:
            dfs_samenode(ids_child)

    records.update_one(
        {"_id": childnode["_id"]}, {"$set": {"last_updated_time": str(datetime.now().replace(microsecond=0))}}
    )
    records.update_one(
        {"_id": childnode["_id"]}, {"$set": {"last_synced_time": str(datetime.now().replace(microsecond=0))}}
    )


def autosync_samenode(repo_name):

    repo_url = f"Poojan230103/{repo_name}"  # to be taken from the config file
    mygit = Github("")
    myrepo = mygit.get_repo(repo_url)

    script_path = root_path + '/' + repo_name + '/build-component.sh'
    components = parse_script(script_path)
    for comp in components.keys():
        if records.count_documents({"component_name": comp}) == 0:          # adding new component if any
            name = 'docker-bakery-system/' + comp + ':1.0'
            new_node = treenode(name)
            next_id = records.count_documents({})
            new_node._id = next_id
            next_id += 1
            new_node.repo_name = repo_name  # name of repository
            docker_path = root_path + repo_name + components[comp][1:]  # local path of dockerfile
            new_node.dockerfile_local_path = docker_path
            new_node.dockerfile_repo_path = components[comp]  # this path is relative to the root path of repo.
            new_node.component_name = comp
            parent = None
            requirements_path = None
            file = open(docker_path, 'r')  # reading the dockerfile
            for lines in file:
                if lines.startswith('FROM'):
                    parent = lines.split()[1]
                    if parent.find(':') == -1:
                        parent = parent + ':1.0'
                match = re.match(r'COPY\s+([^\s]+/requirements.txt)\s+\.', lines)  # requirements.txt path
                if match:
                    requirements_path = match.group(1)
            par_data = parent.split(':')
            par = records.find_one({"img_name": par_data[0], "tag": float(par_data[1])})
            new_node.parent = par["_id"]  # storing the parent
            if requirements_path:  # this path is relative to the .sh file
                new_dep = dependencies("requirements.txt")
                req_currpath = root_path + repo_name + requirements_path[1:]  # requirements.txt local path
                new_dep.deps_local_path = req_currpath
                new_dep.deps_repo_path = req_currpath.split(repo_name)[1]  # requirements.txt path relative to root path of the repo
                new_node.files.append(new_dep)
            par.children.append(new_node._id)  # storing the child
            parameter = {
                "repo_name": new_node.repo_name,
                "component_name": new_node.component_name,
                "tag": new_node.tag,
            }
            build_component(parameter)
            # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
            # response = response.json()
            # print(response)
            # # polling every 10 seconds
            # parameter = {"job_id": response["job_id"]}
            # while True:
            #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
            #     response = response.json()
            #     if response["status"] == "Success" or response["status"] == "Failed":
            #         print(response["status"])
            #         break
            #     time.sleep(10)
            json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
            json_data = json.loads(json_data)
            records.insert_one(json_data)
            records.replace_one({"_id": par["_id"]}, par)

        else:
            node = records.find_one({"repo_name": repo_name, "component_name": comp}, sort=[("tag", -1)], limit=1)
            var = node["dockerfile_repo_path"]            # docker file
            commits = myrepo.get_commits(path=var)
            flag = False
            utc_time = commits[0].commit.committer.date
            t = convert_to_indian_time(utc_time)
            last_sync_time = node["last_synced_time"]  # in string format
            last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
            last_sync_time = convert_to_indian_time(last_sync_time)

            if t > last_sync_time:
                flag = True

            # check for requirements.txt
            for dep in node["files"]:
                var = dep["deps_repo_path"]
                commits = myrepo.get_commits(path=var)
                utc_time = commits[0].commit.committer.date
                t = convert_to_indian_time(utc_time)
                last_sync_time = node["last_synced_time"]  # in string format
                last_sync_time = datetime.strptime(last_sync_time, '%Y-%m-%d %H:%M:%S')
                last_sync_time = convert_to_indian_time(last_sync_time)

                if t > last_sync_time:
                    flag = True

            if flag:
                os.system(f''' cd {root_path}/{repo_name}
                            git pull origin''')

                parameter = {"repo_name": node["repo_name"],
                             "component_name": node["component_name"],
                             "tag": node["tag"]
                             }
                build_component(parameter)
                # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
                # response = response.json()
                # print(response)
                # parameter = {"job_id": response["job_id"]}
                # while True:
                #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
                #     response = response.json()
                #     if response["status"] == "Success" or response["status"] == "Failed":
                #         print(response["status"])
                #         break
                #     time.sleep(5)

                for ids in node["children"]:
                    dfs_samenode(ids)
                records.update_one(
                    {"_id": node["_id"]}, {"$set": {"last_updated_time": str(datetime.now().replace(microsecond=0))}}
                )
            records.update_one({"_id": node["_id"]},
                               {"$set": {"last_synced_time": str(datetime.now().replace(microsecond=0))}})
