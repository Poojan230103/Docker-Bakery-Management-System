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
from myapp.functions import parse_script, parse_dockerfile, create_docker_graph, sync_upgrade_node, build_image, sync_update_node, dfs_update_node, delete_subtree, make_redeployments, store_in_mongodb, get_data_from_repository, get_parameters, get_parameters_from_treenode, get_dependencies, multiple_docker_build, get_k8s_deployments, can_process_node, can_be_deleted


logging.basicConfig(level=logging.DEBUG, filename="logs.log", filemode="w", format="%(asctime)s - %(message)s", datefmt='%d-%b-%y %H:%M:%S')
load_dotenv()
client = pymongo.MongoClient(os.getenv("MONGODB_CONNECTION_STRING"))
db = client.get_database('myDB')
records = db['Images']
github_client = Github(os.getenv("GITHUB_ACCESS_TOKEN"))


'''
Explanation for get_data_from_mongodb function:

This function brings the data of all the nodes from  the mongodb database, converts them to hierarchical format using make_docker_graph function and then instead of storing the sibling's id we replace it with sibling's name and tag and store it in a file ./static/data.json from which the UI get the data. 
'''


def get_data_from_mongodb():                                 # fetches the data from the database and converts it into hierarchical format to display it in UI
    all_images_cursor_object = records.find()
    images_list = list(all_images_cursor_object)
    root_id = -1
    node_to_array_id = {}
    for idx in range(len(images_list)):
        node_to_array_id[images_list[idx]["_id"]] = idx
        if images_list[idx]["parent"] is None:
            root_id = idx
    for node_data in images_list:
        if node_data["sibling"]:                                                        # if sibling exists
            node = records.find_one({"_id": node_data["sibling"]})                      # finding the sibling node
            node_data["sibling"] = str(node["img_name"] + ':' + str(node["tag"]))
    docker_graph = create_docker_graph(root_id, images_list, node_to_array_id)           # convert the list of documents into hierarchical form
    json_data = json.dumps(docker_graph, indent=2)                                      # converting the hierarchical data into json
    with open('./static/data.json', 'w') as f:                                          # storing the data into file, so that it can be accessed using UI.
        f.write(json_data)


'''
Explanation for homepage_view function:

This function first creates a list of image names that are associated with some repository, by fetching data from mongoDB.
This list of images are the ones, the user can sync.
Then it calls the get_data_from_mongodb function, which will store the data in hierarchical format in ./static/data.json file.
Then it renders the homepage and passes the list of images as parameter.
'''


def homepage_view(request):             # home-page of website
    image_list = records.find({"repo_name": {"$ne": None}})          # providing user a list of images which he/she can sync
    image_options = []
    for image in image_list:
        if image["img_name"] not in image_options:
            image_options.append(image["img_name"])
    get_data_from_mongodb()                                                                      # fetches data from DB
    return render(request, 'index.html', {"dropdown_options": image_options})


'''
Explanation for add_child_view function:

This function takes argument parent_id from the UI and renders a html form to add new child node.
'''


def add_child_view(request):
    if request.method == 'GET':
        parent_node_id = request.GET.get('node_id')
        parent_node = records.find_one({"_id": parent_node_id})
        can_add_child, image_name = can_process_node(parent_node)
        if can_add_child:
            return render(request, 'add_node_form.html', {"parent_id": int(request.GET.get('node_id'))})
        else:
            messages.info(request, f"Cannot Add the child because the ancestor {image_name} is already locked")
            return redirect('/')


'''
Explanation for add_child_component function:

If the request method is POST, then the function will receive the following inputs: component_name, parent_id, tag and repo_name and builds a new component image and stores the metadata in the mongodb.
The function takes care of multiple edge-cases like if Image already exists, if the tag is incremental or not, if the repository exist or not, does the component exist or not, does the parent image mentioned in the dockerfile matches the  with the one he/she wants to make this new node child of.
'''


def add_child_component(request):                  # addition of new node through UI
    if request.method == "POST":
        component_name = request.POST['component_name']
        parent_id = int(request.POST['parent'])
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
            except FileNotFoundError:
                messages.error(request, "Repository does not exist")
                return redirect('/')
            shell_script = get_data_from_repository(repository, '/build-component.sh')
            component_name_to_dockerfile_path = parse_script(shell_script)
            if component_name not in component_name_to_dockerfile_path.keys():
                messages.error(request, "Component does not exist")
                return redirect('/')
            new_node = make_new_component_node(repository, request.POST['repo_name'], img_name, request.POST['Tag'], parent_id, component_name, component_name_to_dockerfile_path[component_name][1:])  # making new tree-node
            if not if_parent_matches(parent_id, new_node.dockerfile_content):
                messages.error(request, "Parent does not Match")
                return redirect('/')
            parent_node = records.find_one({"_id": parent_id})
            can_add_child, image_name = can_process_node(parent_node)
            if can_add_child:
                status = build_new_image_util(new_node, parent_node)
                if status == "Success":
                    messages.success(request, "Image Created Successfully.")
                else:
                    messages.error(request, "Failed to create the image.")
                records.update_one({"_id": parent_id}, {"$set": {"is_locked": False}})
            else:
                messages.error(request, f"Failed to add new Child as the ancestor {image_name} is already locked.")
        return redirect('/')


'''
Explanation for add_child_image function:

This function is invoked when the user adds a child image by entering the dockerfile and requirements.txt in the form to add a new node.
The function takes input: parent_id, dockerfile content, requirements.txt content if entered by user and then it builds this new non_component image and store its metadata in the database.
The function takes care of multiple edge-cases like if Image already exists, if the tag is incremental or not, is the dockerfile empty, if the user has specified the parent image in the dockerfile or not or if the parent name matches with the one he/she wants to make this new node child of.
in the below function, it is assumed that dockerfile and requirements.txt are in the same path
'''


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
        if (parent_from_user is None) or (parent_id != parent_from_user["_id"]):       # checking whether the parent in the dockerfile matches the one in the form.
            messages.error(request, "Parent Name did not Match.")
            return redirect('/')
        new_node = make_new_non_component_node(request.POST['img_name'], request.POST['Tag'], parent_id, dockerfile, requirements)
        if sibling:
            new_node.sibling = sibling["_id"]
        can_add_child, image_name = can_process_node(parent_node)
        if can_add_child:
            status = build_new_image_util(new_node, parent_node)
            if status == "Success":
                messages.success(request, "Image Created Successfully.")
            else:
                messages.error(request, "Failed to create the image.")
            records.update_one({"_id": parent_id}, {"$set": {"is_locked": False}})
        else:
            messages.error(request, f"Cannot add the image as the ancestor {image_name} is already locked.")
    return redirect('/')


'''
Explanation for build_new_image_util:

This function takes two arguments a node and its parent node.
It first locks the node, and then builds its docker image using build_image function.
then if the status of build image is Success, then it stores its metadata in mongoDB and returns the status Success or Failed depending upon whether the image is created successfully or Failed.
'''


def build_new_image_util(new_node, parent_node):
    parent_node["is_locked"] = True
    records.update_one({"_id": parent_node["_id"]}, {"$set": {"is_locked": True}})
    parameter = get_parameters_from_treenode(new_node)
    status = build_image(parameter)
    if status == "Success":
        store_in_mongodb(new_node)
        parent_node["children"].append(new_node._id)
        records.replace_one({"_id": parent_node["_id"]}, parent_node)
    return status


'''
Explanation for manual_sync_on_image function:

The function takes input the image name. If the node does not contains any repo then we give an error that we can't sync the image without repository.
The function searches for the node with the same name but with the highest tag. If the sync_type == 0, it means that the user wants to upgrade the node, else the user wants to update the node. The respective parameters are passed to the functions based on the type of sync the user wants. The return_code will be a single integer if the image is synced successfully or Failed. However, when the sync operation is denied because some of its ancestor is already locked and is under process, then the return value will be a tuple with the 1st element the return code 2 and the 2nd element: the image name which is already locked. 
'''


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
        return_code = sync_upgrade_node(node, repo_name)
    else:                                           # Update Node
        return_code = sync_update_node(node, repo_name)
    if (type(return_code) is int) and return_code == 0:
        messages.success(request, 'Image Synced Successfully')
    elif (type(return_code) is tuple) and return_code[0] == 2:
        messages.info(request, f'''Cannot Sync Node as image {return_code[1]} is already locked''')
    else:
        messages.error(request, 'Sync Failed')
    return redirect('/')


'''
Explanation for manual_sync_on_node function:

The function takes input the node_id of the node the user wants to sync. If the node does not contains any repo then we give an error that we can't sync the image without repository.
The function searches for the node with the same name but with the highest tag. If the sync_type == 0, it means that the user wants to upgrade the node, else the user wants to update the node. The respective parameters are passed to the functions based on the type of sync the user wants. The return_code will be a single integer if the image is synced successfully or Failed. However, when the sync operation is denied because some of its ancestor is already locked and is under process, then the return value will be a tuple with the 1st element the return code 2 and the 2nd element: the image name which is already locked. 
'''


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
        return_code = sync_upgrade_node(selected_node, repo_name)
    else:               # Update Node
        return_code = sync_update_node(selected_node, repo_name)
    if (type(return_code) is int) and return_code == 0:
        messages.success(request, 'Image Synced Successfully')
    elif (type(return_code) is tuple) and return_code[0] == 2:
        messages.info(request, f'''Cannot Sync Node as image {return_code[1]} is already locked''')
    else:
        messages.error(request, 'Sync Failed')
    return redirect('/')


'''
Explanation for edit_node function:

If the request method is GET, then the function returns the node_id and the content of the dockerfile to the user. 
If the request method is POST, then the function takes input the node_id and the updated content of the dockerfile from the user.
It first checks whether the node can be processed or not, by checking whether any of its ancestor are locked or not.
If the node can be processed, then we first apply the lock on the node and rebuild its image. If the image is built successfully, then it will redeploy the deployments that were made using that node on k8s. Then it will re-build the images of its children asynchronously using dfs_update_node function.
'''


def edit_node(request):
    if request.method == 'POST':
        node_id = int(request.POST['node_id'])
        node = records.find_one({"_id": node_id})
        can_edit_node, image_name = can_process_node(node)
        if can_edit_node:
            records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": True}})          # locking the node before performing any operation so as to avoid race condition.
            updated_dockerfile_content = request.POST['dockerfile']
            if not updated_dockerfile_content.strip():
                messages.error(request, "Dockerfile cannot be Emtpy")
                return redirect('/')
            if not if_parent_matches(node["parent"], updated_dockerfile_content):       # check if the parent image entered by user matches with node's parent
                messages.error(request, "Parent did not Match.")
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                return redirect('/')
            node["dockerfile_content"] = updated_dockerfile_content
            status = build_image(get_parameters(node))
            if status == "Success":
                make_redeployments(node)                       # re-deploying the deployments
                child_node_to_status = asyncio.run(multiple_docker_build(node["children"]))     # asynchronously rebuilding the children.
                for child_id in node["children"]:
                    dfs_update_node(child_id, child_node_to_status, False)
                records.replace_one({"_id": node_id}, node)
                messages.success(request, "Edited Successfully")
            else:
                messages.success(request, "Failed")
            records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
        else:
            messages.error(request, f"Cannot edit Node as the ancestor {image_name} is already locked")
        return redirect('/')
    else:
        node_id = int(request.GET.get('node_id'))
        node = records.find_one({"_id": node_id})
        dockerfile_contents = node["dockerfile_content"]
        return render(request, 'edit_node.html', {"dockerfile_contents": dockerfile_contents, "node_id": node_id})


'''
Explanation for delete_node function:

The function first calls the get_k8s_deployments function which will store the metadata about the list of deployments that are made using each image node.
Then we check whether the image node can be deleted or not. In case the image node itself or some of its ancestor node is already locked, then we cannot delete the node as it is already undergoing some process.
If the can_be_deleted function returns true, then it is first locked to avoid the race condition. Then delete_subtree function is called which deletes the subtree recursively and alongside makes re-deployments using the latest-version of the deleted image.
At last the lock is released so as to avoid deadlock.
'''


def delete_node(request):
    get_k8s_deployments()
    node_id = int(request.GET.get('node_id'))
    node = records.find_one({"_id": node_id})
    if can_be_deleted(node):
        can_delete, image_name = can_process_node(node)
        if can_delete:
            node["is_locked"] = True
            records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": True}})
            status = delete_subtree(node_id)
            if status == "Success":
                messages.success(request, "Image Deleted Successfully")
            else:
                node["is_locked"] = False
                records.update_one({"_id": node["_id"]}, {"$set": {"is_locked": False}})
                messages.error(request, "Failed to Delete Image")
        else:
            messages.info(request, f"Cannot Delete Image now as its ancestor {image_name} is already locked")
    else:
        messages.error(request, f"Node cannot be deleted as some deployments are still running")
    return redirect('/')


'''
Explanation for if_parent_matches function:

This function takes input the parent_node_id and the Dockerfile content.
It parses the docker file and checks whether the parent image in the dockerfile matches the one selected by user using UI.
returns true if the parent matches else return False.
'''


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


'''
Explanation for make_new_non_component_node:

This function is used when the image the user wants to add is a part of some repository.
This function takes input repository object which is used to access the repository, repo_name, image name, tag, parent, component_name and repository path of dockerfile
Using this parameters it creates a new treenode object and stores the metadata as well as the parameters passed to the function.
Returns a treenode object --> a new image node.
'''


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
        new_node.sibling = sibling_node["_id"]         # assigning sibling
    element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)   # finding the highest id
    new_node._id = element_with_highest_id["_id"] + 1                             # assigning id
    return new_node


'''
Explanation for make_new_non_component_node:

This function is used when the image the user wants to add is not part of any repository.
This function takes input image name, tag, parent_id, dockerfile content, requirements.txt content
Using this parameters it creates a new treenode object and stores the metadata as well as the parameters passed to the function.
Returns a treenode object --> a new image node.
'''


def make_new_non_component_node(img_name, tag, parent_id, dockerfile, requirements):    # makes a new node for image without any repository
    img_name_plus_tag = img_name + ':' + tag
    new_node = treenode(img_name_plus_tag)
    new_node.parent = int(parent_id)
    new_node.dockerfile_content = dockerfile
    if requirements:                            # check if requirements.txt file exists
        dependency = dependencies('requirements.txt')       # dependencies is a class
        dependency.dependency_content = requirements
        new_node.files.append(dependency)
    sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
    if sibling:
        new_node.sibling = sibling["_id"]
    element_with_highest_id = records.find_one({}, sort=[("_id", -1)], limit=1)     # finding the highest id
    new_node._id = element_with_highest_id["_id"] + 1
    return new_node

