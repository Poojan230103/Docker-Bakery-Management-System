import os, requests, time
from django.shortcuts import render, redirect
import pymongo
import json
from multiprocessing import Process
from django.http import HttpResponse
from datetime import datetime
from github import Github
from myapp.models import treenode, dependencies
from myapp.functions import parse_script, parse_dockerfile, create_hierarchy, sync_new_node, build_image, sync_same_node, dfs_same_node, dfs_new_node, delete_subtree, redeploy_components
from django.contrib import messages


client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('myDB')
records = db['Images']
root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'         # root path --> contains all the repos
my_git = Github("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")


def get_data():     # fetches the data from the database and converts it into hierarchical format to display it in UI
    all_images_cursor = records.find()
    list_cursor = list(all_images_cursor)
    json_data = json.dumps(list_cursor, indent=4)       # converting cursor object returned by mongoDB to json format.
    data = json.loads(json_data)                         # converts json data to python object
    data = sorted(data, key=lambda x: x['img_name'].split()[0])         # sorting the data by img_name
    for img in data:
        if img["sibling"]:
            node = records.find_one({"_id": img["sibling"]})
            img["sibling"] = str(node["img_name"] + ':' + str(node["tag"]))
    hierarchy = create_hierarchy(data)                          # convert the list of documents into hierarchical form
    json_data = json.dumps(hierarchy[0], indent=2)              # converting the hierarchical data into json
    f = open('./static/data.json', 'w')
    f.write(json_data)
    f.close()


def index(request):             # home-page
    get_data()                  # fetches data from DB
    return render(request, 'index.html')


def add_node(request):                  # addition of new node through UI
    if request.method == 'GET':
        parent_id = int(request.GET.get('node_id'))
        return render(request, 'add_node_form.html', {"parent_id": parent_id})
    if request.method == "POST":
        if request.POST['source_type'] == "component":          # if the image is a component
            repo = request.POST['repo_name']
            component_name = request.POST['comp_name']
            tag = request.POST['Tag']
            img_name = 'poojan23/docker-bakery-system_' + component_name
            if records.count_documents({"img_name": img_name, "tag": float(tag)}):      # check whether the img already exists
                messages.error(request, "Image Already Exists")
                return redirect('/')
            else:
                sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)     # image with the same name and latest tag.
                img_plus_tag = img_name + ':' + tag
                new_node = treenode(img_plus_tag)
                new_node.parent = int(request.POST['parent'])
                new_node.component_name = component_name
                new_node.repo_name = repo
                my_repo = my_git.get_repo(f"Poojan230103/{repo}")
                file = my_repo.get_contents('/build-component.sh')
                response = requests.get(file.download_url)
                shell_script = str(response.content, 'UTF-8')
                components = parse_script(shell_script)
                if component_name not in components.keys():
                    messages.error(request, "Component does not exist")
                    return redirect('/')
                my_repo = my_git.get_repo(f'''Poojan230103/{repo}''')
                commits = my_repo.get_commits(sha=my_repo.default_branch)[0]
                new_node.commit_id = commits.sha                                     # storing the commit sha of the node.
                new_node.dockerfile_repo_path = components[component_name][1:]
                file = my_repo.get_contents(new_node.dockerfile_repo_path)              # storing the contents of Dockerfile
                response = requests.get(file.download_url)
                contents = response.content
                contents = str(contents, 'UTF-8')
                new_node.dockerfile_content = contents
                requirements_path = parse_dockerfile(contents)
                if requirements_path:
                    new_dep = dependencies('requirements.txt')
                    new_dep.deps_repo_path = requirements_path[1:]
                    new_dep.deps_local_path = root_path + '/' + repo + '/' + requirements_path[1:]
                    file = my_repo.get_contents(new_dep.deps_repo_path)                                 # storing the contents of requirements.txt
                    response = requests.get(file.download_url)
                    contents = response.content
                    contents = str(contents, 'UTF-8')
                    new_dep.dependency_content = contents
                    new_node.files.append(new_dep)
                if sibling:
                    if float(tag) <= sibling["tag"]:    # throw an error that tag should be incremental
                        messages.error(request, "Tag should be incremental")
                        return redirect('/')
                    else:
                        new_node.sibling = sibling["_id"]
                # -----------------------------------------------------------------------------------------------
                element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)        # finding the highest id
                new_node._id = element_with_highest_id["_id"] + 1                                   # assigning id
                json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)        # converting tree object to json
                json_data = json.loads(json_data)                                               # converting json to python dictionary
                records.insert_one(json_data)
                parent_node = records.find_one({"_id": int(request.POST['parent'])})
                parent_node["children"].append(new_node._id)                                # assigning new child to the parent.
                records.replace_one({"_id": int(request.POST['parent'])}, parent_node)
                parameter = {"repo_name": new_node.repo_name, "dockerfile": new_node.dockerfile_content, "dockerfile_path": new_node.dockerfile_repo_path, "component_name": new_node.component_name, "tag": new_node.tag}
                build_image(parameter)
                messages.success(request, "Component Created Successfully.")
        else:                                                                   # if the image is not a component
            parent = int(request.POST['parent'])
            tag = request.POST['Tag']
            img_name = request.POST['img_name']
            dockerfile = request.POST['Dockerfile']
            requirements = request.POST['Requirements']
            if records.find_one({"img_name": img_name, "tag": float(tag)}):    # throw an error that the image already exists
                messages.error(request, "Image Already Exists")
                return redirect('/')
            sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
            if sibling:
                if float(tag) <= sibling["tag"]:        # throw an error that tag should be incremental
                    messages.error(request, "Tag should be incremental")
                    return redirect('/')
            # checking whether the parent in the dockerfile matches the one in the form.
            parent_name = None
            dockerfile_contents = dockerfile.splitlines()
            line_num = -1
            cnt = 0
            for line in dockerfile_contents:
                if line.__contains__("FROM"):
                    line_num = cnt
                cnt += 1
            if line_num != -1:
                parent_name = dockerfile_contents[line_num].split()[1]
            print(parent_name)
            parent_node = records.find_one({"_id": parent})
            parent_from_user = records.find_one({"img_name": parent_name.split(':')[0], "tag": float(parent_name.split(':')[1])})
            if (parent_from_user is None) or (parent != parent_from_user["_id"]):
                messages.error(request, "Parent Name did not Match.")
                return redirect('/')
            new_node = treenode(img_name + ':' + tag)
            new_node.parent = int(parent)
            new_node.dockerfile_content = dockerfile
            if requirements:
                new_dep = dependencies('requirements.txt')
                new_dep.dependency_content = requirements
                new_node.files.append(new_dep)
            if sibling:
                new_node.sibling = sibling["_id"]
            parameter = {"dockerfile": new_node.dockerfile_content, "img_name": new_node.img_name, "tag": new_node.tag, "requirements": requirements}
            build_image(parameter)
            element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)  # finding the highest id
            new_node._id = element_with_highest_id["_id"] + 1
            json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
            json_data = json.loads(json_data)
            records.insert_one(json_data)
            parent_node["children"].append(new_node._id)
            records.replace_one({"_id": int(parent)}, parent_node)
            messages.success(request, "Image Created Successfully.")
    return redirect('/')


def manual_sync(request):
    if request.method == 'POST':                # Manual Sync using Image Name
        img_name = request.POST['img_name']
        sync_type = int(request.POST['sync_type'])
        node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
        if node is None:
            messages.error(request, "Image Does Not Exist")
            return redirect('/')
        if node["repo_name"] is None:
            # print("hello ")
            messages.error(request, "Cannot Sync Image without Repository")
            return redirect('/')
        repo_name = node["repo_name"]
        if sync_type == 0:                              # Upgrade Node
            p = Process(target=sync_new_node, args=(node, repo_name,))
        else:                                           # Update Node
            p = Process(target=sync_same_node, args=(node, repo_name,))
        p.start()
        p.join()
        if p.exitcode == 0:
            messages.success(request, 'Repository Synced Successfully')
        else:
            messages.error(request, 'Sync Failed')
        return redirect('/')
    else:                                           # Manual Sync by right-clicking on the Node
        node_id = int(request.GET.get('node_id'))
        selected_node = records.find_one({"_id": node_id})
        if selected_node["repo_name"] is None:
            messages.error(request, "Cannot Sync Image without Repository")
            return redirect('/')
        max_tag_node = records.find_one({"img_name": selected_node["img_name"]}, sort=[("tag", -1)], limit=1)
        if selected_node["tag"] != max_tag_node["tag"]:         # checking whether it is the latest node or not. Sync only if it is the latest node.
            messages.info(request, 'Not the latest Image.')
            return redirect('/')
        repo_name = selected_node["repo_name"]
        sync_type = int(request.GET.get('sync_type'))
        if sync_type == 0:                              # Upgrade Node
            p = Process(target=sync_new_node, args=(selected_node, repo_name,))
        else:                                          # Update Node
            p = Process(target=sync_same_node, args=(selected_node, repo_name,))
        p.start()
        p.join()
        if p.exitcode == 0:
            messages.success(request, 'Image Synced Successfully')
        else:
            messages.error(request, 'Sync Failed')
        return redirect('/')


def edit_node(request):
    if request.method == 'POST':
        updated_dockerfile_contents = request.POST['dockerfile']
        node_id = int(request.POST['node_id'])
        node = records.find_one({"_id": node_id})
        node["dockerfile_content"] = updated_dockerfile_contents
        # checking whether the parent in the dockerfile matches the one in the form.
        parent_name = None
        updated_dockerfile_contents = updated_dockerfile_contents.splitlines()
        line_num = -1
        cnt = 0
        for line in updated_dockerfile_contents:
            if line.__contains__("FROM"):
                line_num = cnt
            cnt += 1
        if line_num != -1:
            parent_name = updated_dockerfile_contents[line_num].split()[1]
        # print(parent_name)
        parent_from_user = records.find_one({"img_name": parent_name.split(':')[0], "tag": float(parent_name.split(':')[1])})
        if (parent_from_user is None) or (node_id != parent_from_user["_id"]):
            messages.error(request, "Parent Name did not Match.")
            return redirect('/')
        # do not make this change in GitHub repository.
        # re-build this image and recursively re-build children without changing the tag.
        if node["repo_name"]:
            parameter = {"repo_name": node["repo_name"], "component_name": node["component_name"],
                         "tag": node["tag"], "dockerfile": node["dockerfile_content"],
                         "dockerfile_path": node["dockerfile_repo_path"]}
            status = build_image(parameter)
        else:
            parameter = {"dockerfile": node["dockerfile_content"], "img_name": node["img_name"],
                         "tag": node["tag"], "requirements": node}
            status = build_image(parameter)
            # -------------------------------------- call redeploy_component function here --------------------------------- #
            redeploy_components(node)
            # --------------------------------------  --------------------------------- #
        for ids in node["children"]:
            dfs_same_node(ids, False)
        if status == "Success":
            messages.success(request, "Edited Successfully")
        else:
            messages.success(request, "Failed")
        records.replace_one({"_id": node_id}, node)
        return redirect('/')
    else:
        node_id = int(request.GET.get('node_id'))
        node = records.find_one({"_id": node_id})
        dockerfile_contents = node["dockerfile_content"]
        return render(request, 'edit_node.html', {"dockerfile_contents": dockerfile_contents, "node_id": node_id})


def delete_node(request):
    delete_siblings = int(request.GET.get('delete_siblings'))
    print(delete_siblings)
    node_id = int(request.GET.get('node_id'))
    print(node_id)
    node = records.find_one({"_id": node_id})
    if delete_siblings:
        list_of_nodes = list(records.find({"img_name": node["img_name"]}))
        list_of_nodes = json.dumps(list_of_nodes, indent=4)      # converting cursor object returned by mongoDB to json format.
        list_of_nodes = json.loads(list_of_nodes)               # converts json data to python object
        for node in list_of_nodes:
            delete_subtree(node["_id"])
    else:
        delete_subtree(node_id)
    messages.success(request, "Image Deleted Successfully")
    return redirect('/')


def get_k8s_deployments(request):
    parameters = {"env": "prod"}
    response = requests.post("http://127.0.0.1:9000/get_deployments", data=parameters)
    # print(response)

