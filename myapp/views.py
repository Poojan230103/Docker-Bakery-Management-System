import time
import json
import os
import logging
import asyncio
from dotenv import load_dotenv
from django.shortcuts import render, redirect
from django.contrib import messages
import pymongo
from github import Github
from myapp.models import treenode, dependencies
from myapp.functions import parse_script, parse_dockerfile, create_docker_graph, sync_new_node, build_image, sync_same_node, dfs_same_node, delete_subtree, redeploy_components, store_in_mongodb, get_data_from_repository, get_parameters, get_parameters_from_treenode, get_dependencies, multiple_docker_build, get_k8s_deployments, redeploy_using_latest_img


logging.basicConfig(level=logging.DEBUG, filename="logs.log", filemode="w", format="%(asctime)s - %(message)s", datefmt='%d-%b-%y %H:%M:%S')
load_dotenv()
client = pymongo.MongoClient(os.getenv("MONGODB_CONNECTION_STRING"))
db = client.get_database('myDB')
records = db['Images']
root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'         # root path --> contains all the repos
github_client = Github(os.getenv("GITHUB_ACCESS_TOKEN"))


def get_data():                                 # fetches the data from the database and converts it into hierarchical format to display it in UI
    all_images_cursor_object = records.find()
    nodes_list = list(all_images_cursor_object)
    root_id = -1
    node_to_array_id = {}
    for idx in range(len(nodes_list)):
        node_to_array_id[nodes_list[idx]["_id"]] = idx
        if nodes_list[idx]["parent"] is None:
            root_id = idx
    for node_data in nodes_list:
        if node_data["sibling"]:                                                           # if sibling exists
            node = records.find_one({"_id": node_data["sibling"]})                         # finding the sibling node
            node_data["sibling"] = str(node["img_name"] + ':' + str(node["tag"]))
    docker_graph = create_docker_graph(root_id, nodes_list, node_to_array_id)             # convert the list of documents into hierarchical form
    json_data = json.dumps(docker_graph, indent=2)                                           # converting the hierarchical data into json
    with open('./static/data.json', 'w') as f:                                            # storing the data into file, so that it can be accessed using UI.
        f.write(json_data)


def index(request):             # home-page
    dropdown_list = records.find({"repo_name": {"$ne": None}})          # providing user a list of images which he/she can sync
    dropdown_options = []
    for list_item in dropdown_list:
        if list_item["img_name"] not in dropdown_options:
            dropdown_options.append(list_item["img_name"])
    get_data()                                                                      # fetches data from DB
    return render(request, 'index.html', {"dropdown_options": dropdown_options})


def add_child_component(request):                  # addition of new node through UI
    if request.method == 'GET':
        return render(request, 'add_node_form.html', {"parent_id": int(request.GET.get('node_id'))})
    if request.method == "POST":
        component_name = request.POST['component_name']
        parent = int(request.POST['parent'])
        img_name = 'poojan23/docker-bakery-system_' + request.POST['component_name']
        if records.count_documents({"img_name": img_name, "tag": float(request.POST['Tag'])}):      # check whether the img already exists
            messages.error(request, "Image Already Exists")
            return redirect('/')
        else:
            sibling_node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)     # image with the same name and latest tag.
            if sibling_node:                                                # checking whether the tag is incremental
                if float(request.POST['Tag']) <= sibling_node["tag"]:       # throw an error that tag should be incremental
                    messages.error(request, "Tag should be incremental")
                    return redirect('/')
            try:
                repository = github_client.get_repo(f"{os.getenv('REPO_BASE')}/{request.POST['repo_name']}")
            except Exception:
                messages.error(request, "Repository does not exist")
                return redirect('/')
            shell_script = get_data_from_repository(repository, '/build-component.sh')
            components = parse_script(shell_script)
            if component_name not in components.keys():
                messages.error(request, "Component does not exist")
                return redirect('/')
            new_node = make_new_component_node(repository, request.POST['repo_name'], img_name, request.POST['Tag']
                                               , request.POST['parent'], request.POST['component_name'], components[component_name][1:])   # making new tree-node
            if not if_parent_matches(parent, new_node.dockerfile_content):
                messages.error(request, "Parent does not Match")
                return redirect('/')
            parameter = get_parameters_from_treenode(new_node)
            status = build_image(parameter)
            if status == "Success":
                store_in_mongodb(new_node)                                               # storing in mongodb
                parent_node = records.find_one({"_id": parent})
                parent_node["children"].append(new_node._id)                             # assigning new child to the parent.
                records.replace_one({"_id": parent}, parent_node)
                messages.success(request, "Component Added Successfully.")
            else:
                messages.error(request, "Failed to add new Component")
        return redirect('/')


# in the below function, it is assumed that dockerfile and requirements.txt are in the same path
def add_child_image(request):                  # addition of new node through UI
    if request.method == "POST":
        parent_id = int(request.POST['parent'])
        dockerfile = request.POST['Dockerfile']
        if not dockerfile.strip():
            messages.error(request, "Dockerfile cannot be Emtpy")
            return redirect('/')
        requirements = request.POST.get('Requirements')
        if records.find_one({"img_name": request.POST['img_name'], "tag": float(request.POST['Tag'])}):    # throw an error that the image already exists
            messages.error(request, "Image Already Exists")
            return redirect('/')
        sibling = records.find_one({"img_name": request.POST['img_name']}, sort=[("tag", -1)], limit=1)
        if sibling:
            if float(request.POST['Tag']) <= sibling["tag"]:        # throw an error that tag should be incremental
                messages.error(request, "Tag should be incremental")
                return redirect('/')
        parent_name, requirements_path = parse_dockerfile(dockerfile)           # parsing the dockerfile
        if parent_name is None:
            messages.error(request, "Parent not specified")
            return redirect('/')
        parent_node = records.find_one({"_id": parent_id})
        parent_from_user = records.find_one({"img_name": parent_name.split(':')[0], "tag": float(parent_name.split(':')[1])})
        if (parent_from_user is None) or (parent_id != parent_from_user["_id"]):            # checking whether the parent in the dockerfile matches the one in the form.
            messages.error(request, "Parent Name did not Match.")
            return redirect('/')
        new_node = make_new_image_node(request.POST['img_name'], request.POST['Tag'], parent_id, dockerfile, requirements)
        if sibling:
            new_node.sibling = sibling["_id"]
        parameter = get_parameters_from_treenode(new_node)
        status = build_image(parameter)
        if status == "Success":
            store_in_mongodb(new_node)
            parent_node["children"].append(new_node._id)
            records.replace_one({"_id": parent_id}, parent_node)
            messages.success(request, "Image Created Successfully.")
        else:
            messages.error(request, "Failed to create the image.")
    return redirect('/')


def manual_sync_on_image(request):                  # manual sync by entering the image name in UI.
    img_name = request.POST.get('img_name')
    logging.info(img_name)
    sync_type = int(request.POST['sync_type'])
    node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
    if node is None:
        messages.error(request, "Image Does Not Exist")
        return redirect('/')
    if node["repo_name"] is None:
        messages.error(request, "Cannot Sync Image without Repository")
        return redirect('/')
    get_k8s_deployments()
    repo_name = node["repo_name"]
    if sync_type == 0:                              # Upgrade Node
        return_code = sync_new_node(node, repo_name)
    else:                                           # Update Node
        return_code = sync_same_node(node, repo_name)
    if return_code == 0:
        messages.success(request, 'Image Synced Successfully')
    else:
        messages.error(request, 'Sync Failed')
    return redirect('/')


def manual_sync_on_node(request):                   # manual sync by right-clicking on a node
    node_id = int(request.GET.get('node_id'))
    selected_node = records.find_one({"_id": node_id})
    if selected_node["repo_name"] is None:                                  # check whether the node has a repo or not
        messages.error(request, "Cannot Sync Image without Repository")
        return redirect('/')
    max_tag_node = records.find_one({"img_name": selected_node["img_name"]}, sort=[("tag", -1)], limit=1)
    if selected_node["tag"] != max_tag_node["tag"]:                 # checking whether it is the latest node or not. Sync only if it is the latest node.
        messages.info(request, 'Not the latest Image.')
        return redirect('/')
    get_k8s_deployments()
    repo_name = selected_node["repo_name"]
    sync_type = int(request.GET.get('sync_type'))
    if sync_type == 0:  # Upgrade Node
        return_code = sync_new_node(selected_node, repo_name)
    else:               # Update Node
        return_code = sync_same_node(selected_node, repo_name)
    if return_code == 0:
        messages.success(request, 'Image Synced Successfully')
    else:
        messages.error(request, 'Sync Failed')
    return redirect('/')


def edit_node(request):
    if request.method == 'POST':
        node_id = int(request.POST['node_id'])
        node = records.find_one({"_id": node_id})
        updated_dockerfile_content = request.POST['dockerfile']
        if not updated_dockerfile_content.strip():
            messages.error(request, "Dockerfile cannot be Emtpy")
            return redirect('/')
        if not if_parent_matches(node["parent"], updated_dockerfile_content):       # check if the parent image entered by user matches with node's parent
            messages.error(request, "Parent did not Match.")
            return redirect('/')
        node["dockerfile_content"] = updated_dockerfile_content
        # do not make this change in GitHub repository.
        # re-build this image and recursively re-build children without changing the tag.
        get_k8s_deployments()
        parameter = get_parameters(node)
        status = build_image(parameter)
        if status == "Success":
            redeploy_components(node)                       # re-deploying the deployments
            child_node_to_status = asyncio.run(multiple_docker_build(node["children"]))     # asynchronously rebuilding the children.
            for child_id in node["children"]:
                dfs_same_node(child_id, child_node_to_status, False)
            # for child_id in node["children"]:
            #     dfs_same_node(child_id, False)
            records.replace_one({"_id": node_id}, node)
            messages.success(request, "Edited Successfully")
        else:
            messages.success(request, "Failed")
        return redirect('/')
    else:
        node_id = int(request.GET.get('node_id'))
        node = records.find_one({"_id": node_id})
        dockerfile_contents = node["dockerfile_content"]
        return render(request, 'edit_node.html', {"dockerfile_contents": dockerfile_contents, "node_id": node_id})


def delete_node(request):
    get_k8s_deployments()
    delete_siblings = int(request.GET.get('delete_siblings'))           # delete_siblings = 1 ==> to delete all the siblings as well.
    node_id = int(request.GET.get('node_id'))
    node = records.find_one({"_id": node_id})
    if delete_siblings:
        nodes_list = list(records.find({"img_name": node["img_name"]}))
        nodes_list = json.dumps(nodes_list, indent=4)      # converting cursor object returned by mongoDB to json format.
        nodes_list = json.loads(nodes_list)               # converts json data to python object
        for node in nodes_list:
            delete_subtree(node["_id"], delete_siblings)
    else:
        status = delete_subtree(node_id, delete_siblings)
        ''' copying the deployments that were made using older image into latest sibling's deployments.
            Then re-deploying those deployments using the latest sibling
            After re-deploying, appending the deployments that were actually made by the latest sibling node prior to deletion of the node.'''
        if status == "Success":
            redeploy_using_latest_img(node)
            messages.success(request, "Image Deleted Successfully")
        else:
            messages.error(request, "Failed to Delete Image")
    return redirect('/')


def if_parent_matches(parent_node_id, updated_dockerfile):              # for editing node using UI
    updated_dockerfile = updated_dockerfile.splitlines()
    parent_name = None
    line_num = -1
    cnt = 0
    for line in updated_dockerfile:
        if line.__contains__("FROM"):
            line_num = cnt
        cnt += 1
    if line_num != -1:
        parent_name = updated_dockerfile[line_num].split()[1]
    parent_from_user = records.find_one({"img_name": parent_name.split(':')[0], "tag": float(parent_name.split(':')[1])})
    if (parent_from_user is None) or (parent_node_id != parent_from_user["_id"]):
        return False
    return True


def make_new_component_node(repository, repo_name, img_name, tag, parent, component_name, dockerfile_repo_path):
    img_name_plus_tag = img_name + ':' + tag
    new_node = treenode(img_name_plus_tag)
    new_node.parent = int(parent)
    new_node.component_name = component_name
    new_node.repo_name = repo_name
    commits = repository.get_commits(sha=repository.default_branch)[0]
    new_node.commit_id = commits.sha                                        # storing the commit sha of the node.
    new_node.dockerfile_repo_path = dockerfile_repo_path
    new_node.dockerfile_content = get_data_from_repository(repository, new_node.dockerfile_repo_path)  # storing the contents of dockerfile
    parent, requirements_list = parse_dockerfile(new_node.dockerfile_content)
    new_node.files = get_dependencies(repository, requirements_list)
    sibling_node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)    # image with the same name and latest tag.
    if sibling_node:
        new_node.sibling = sibling_node["_id"]                    # assigning sibling
    element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)   # finding the highest id
    new_node._id = element_with_highest_id["_id"] + 1             # assigning id
    return new_node


def make_new_image_node(img_name, tag, parent_id, dockerfile, requirements):    # makes a new node for image without repository
    new_node = treenode(img_name + ':' + tag)
    new_node.parent = int(parent_id)
    new_node.dockerfile_content = dockerfile
    if requirements:
        dependency = dependencies('requirements.txt')
        dependency.dependency_content = requirements
        new_node.files.append(dependency)
    sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
    if sibling:
        new_node.sibling = sibling["_id"]
    element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)  # finding the highest id
    new_node._id = element_with_highest_id["_id"] + 1
    return new_node

