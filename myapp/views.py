import os, requests, time
from django.shortcuts import render, redirect
import pymongo
import json
from multiprocessing import Process
from django.http import HttpResponse
from datetime import datetime
from myapp.models import treenode, dependencies
from myapp.functions import parse_script, parse_dockerfile, create_hierarchy, sync_new_node, build_image, sync_same_node,dfs_same_node,dfs_new_node
from django.contrib import messages


client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('myDB')
records = db['Images']
root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'         # root path --> contains all the repos


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
    hierarchy = create_hierarchy(data)
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
            img_name = 'docker-bakery-system/' + component_name
            if records.count_documents({"img_name": img_name, "tag": float(tag)}):      # check whether the img already exists
                messages.error(request, "Image Already Exists")
                return redirect('/add_node')
            else:
                sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)     # image with the same name and latest tag.
                img_plus_tag = img_name + ':' + tag
                new_node = treenode(img_plus_tag)
                new_node.parent = int(request.POST['parent'])
                new_node.component_name = component_name
                new_node.repo_name = repo
                script_path = root_path + '/' + repo + '/build-component.sh'
                components = parse_script(script_path)
                dockerfile_path = root_path + '/' + repo + '/' + components[component_name][1:]
                new_node.dockerfile_local_path = dockerfile_path
                new_node.dockerfile_repo_path = dockerfile_path.split(repo)[1]
                requirements_path = parse_dockerfile(dockerfile_path)
                if requirements_path:
                    new_dep = dependencies('requirements.txt')
                    new_dep.deps_repo_path = requirements_path[1:]
                    new_dep.deps_local_path = root_path + '/' + repo + '/' + requirements_path[1:]
                    new_node.files.append(new_dep)
                if sibling:
                    if float(tag) <= sibling["tag"]:    # throw an error that tag should be incremental
                        messages.error(request, "Tag should be incremental")
                        return redirect('/add_node')
                    else:
                        new_node.sibling = sibling["_id"]
                new_node._id = records.count_documents({}) + 1
                json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)        # converting tree object to json
                json_data = json.loads(json_data)                                               # converting json to python dictionary
                records.insert_one(json_data)

                parent_node = records.find_one({"_id": int(request.POST['parent'])})
                parent_node["children"].append(new_node._id)                                # assigning new child to the parent.
                records.replace_one({"_id": int(request.POST['parent'])}, parent_node)
                #
                parameter = {                                               # building image
                    "repo_name": new_node.repo_name,
                    "component_name": new_node.component_name,
                    "tag": new_node.tag,
                }
                build_image(parameter)
                messages.success(request, "Component Created Successfully.")
        else:                                                                   # if the image is not a component
            repo = request.POST['repo_name']
            parent = request.POST['parent']
            print("parent data type", type(parent))
            tag = request.POST['Tag']
            img_name = request.POST['img_name']
            dockerfile_local_path = request.POST['Dockerfile']
            requirements_local_path = request.POST['Requirements']
            if records.find_one({"img_name": img_name, "tag": float(tag)}):    # throw an error that the image already exists
                messages.error(request, "Image Already Exists")
                return redirect('/add_node')
            sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
            if sibling:
                if float(tag) <= sibling["tag"]:        # throw an error that tag should be incremental
                    messages.error(request, "Tag should be incremental")
                    return redirect('/add_node')
            new_node = treenode(img_name + ':' + tag)
            new_node.parent = int(parent)
            new_node.dockerfile_local_path = dockerfile_local_path
            new_node.dockerfile_repo_path = dockerfile_local_path.split(repo)[1]
            if requirements_local_path:
                new_dep = dependencies('requirements.txt')
                new_dep.deps_local_path = requirements_local_path
                new_dep.deps_repo_path = requirements_local_path.split(repo)[1]
                new_node.files.append(new_dep)
            if sibling:
                new_node.sibling = sibling["_id"]
            new_node._id = records.count_documents({}) + 1
            json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
            json_data = json.loads(json_data)
            records.insert_one(json_data)
            parent_node = records.find_one({"_id": int(parent)})
            parent_node["children"].append(new_node._id)
            records.replace_one({"_id": int(parent)}, parent_node)

            parameter = {"dockerfile_local_path": new_node.dockerfile_local_path,           # building the image.
                         "img_name": new_node.img_name,
                         "tag": new_node.tag}
            response = requests.post("http://127.0.0.1:9000/build_no_comp", data=parameter)
            response = response.json()
            # polling every 10 seconds
            parameter = {"job_id": response["job_id"]}
            while True:
                response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
                response = response.json()
                if response["status"] == "Success" or response["status"] == "Failed":
                    print(response["status"])
                    break
                time.sleep(10)
            messages.success(request, "Image Created Successfully.")
    return render(request, 'add_node_form.html')


def manual_sync(request):

    if request.method == 'POST':                # Manual Sync using Image Name
        img_name = request.POST['img_name']
        sync_type = int(request.POST['sync_type'])
        node = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
        if node == None:
            messages.error(request, "Image Does Not Exist")
            return redirect('/')
        repo_name = node["repo_name"]
        print(node["last_synced_time"])
        if sync_type == 0:
            p = Process(target=sync_new_node, args=(node,repo_name,))
        else:
            p = Process(target=sync_same_node, args=(node,repo_name,))
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


def force_rebuild(request):
    node_id = int(request.GET.get('node_id'))
    node = records.find_one({"_id": node_id})

    if "repo_name" not in node.keys():                      # we can only force build images with repository.
        messages.error("Cannot Force Build this Image.")
        return redirect('/')

    repo_name = node["repo_name"]
    os.system(f''' cd {root_path}/{repo_name}
                        git pull origin ''')
    # UPDATE THE PARENT OF THE NODE
    f = open(node["dockerfile_local_path"], 'r')
    content = f.readlines()
    line_num = -1
    cnt = 0
    for line in content:
        if line.__contains__("FROM"):
            line_num = cnt
        cnt += 1
    new_parent = content[line_num].split()          # new_parent --> list with first element as image name and 2nd element as tag
    new_parent_node = records.find_one({"img_name": new_parent[0], "tag": float(new_parent[1])})
    new_parent_node["children"].append(node["_id"])  # appending node to its new parent
    old_parent_node = records.find_one({"_id": node["parent"]})  # removing the old parent
    old_parent_node["children"].remove(node["_id"])
    node["parent"] = new_parent_node["_id"]
    records.replace_one({"_id": new_parent_node["_id"]}, new_parent_node)
    records.replace_one({"_id": old_parent_node["_id"]}, old_parent_node)

    # LOOK FOR SIBLING

    parameter = {
        "repo_name": node["repo_name"],
        "component_name": node["component_name"],
        "tag": node["tag"],
    }
    build_image(parameter)
    for ids in node["children"]:
        dfs_same_node(ids)
    records.update_one({"_id": node["_id"]}, {"$set": {"last_updated_time": str(datetime.now().replace(microsecond=0))}})
    records.update_one({"_id": node["_id"]}, {"$set": {"last_synced_time": str(datetime.now().replace(microsecond=0))}})


