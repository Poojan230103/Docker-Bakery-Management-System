import os, requests, time
from django.shortcuts import render, redirect
import pymongo
import json
from multiprocessing import Process
from django.http import HttpResponse
from myapp.models import treenode, dependencies
from myapp.functions import parse_script, parse_dockerfile, create_hierarchy, auto_sync_newnode, autosync_samenode, build_component
from django.contrib import messages


client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('myDB')
records = db['Images']

root_path = '/Users/shahpoojandikeshkumar/Desktop/SI/repos'


def get_data():     # fetches the data from the database and converts it into hierarchical format to display it in UI

    all_images_cursor = records.find()
    list_cursor = list(all_images_cursor)
    json_data = json.dumps(list_cursor, indent=4)       # converting cursor object returned by mongoDB to json format.
    data = json.loads(json_data)        # converts json data to python object
    print(type(data))
    data = sorted(data, key=lambda x: x['img_name'].split()[0])
    for img in data:
        if img["sibling"]:
            node = records.find_one({"_id": img["sibling"]})
            img["sibling"] = str(node["img_name"] + ':' + str(node["tag"]))
    hierarchy = create_hierarchy(data)
    json_data = json.dumps(hierarchy[0],indent=2)
    f = open('./static/data.json', 'w')
    f.write(json_data)
    f.close()


def index(request):
    get_data()
    return render(request, 'index.html')


def add_node(request):

    if request.method == "POST":
        if request.POST['source_type'] == "component":
            repo = request.POST['repo_name']
            comp = request.POST['comp_name']
            tag = request.POST['Tag']
            img_name = 'docker-bakery-system/' + comp
            print(repo, comp, tag, img_name)
            if records.count_documents({"img_name": img_name, "tag": float(tag)}):
                messages.error(request, "Image Already Exists")
                return redirect('/add_node')
            else:
                sibling = records.find_one({"img_name": img_name}, sort=[("tag", -1)], limit=1)
                img_tag = img_name + ':' + tag
                new_node = treenode(img_tag)
                new_node.parent = int(request.POST['parent'])
                new_node.component_name = comp
                new_node.repo_name = repo
                script_path = root_path + '/' + repo + '/build-component.sh'
                components = parse_script(script_path)
                path = root_path + '/' + repo + '/' + components[comp]
                new_node.dockerfile_local_path = path
                new_node.dockerfile_repo_path = components[comp]
                requirements_path = parse_dockerfile(path)
                if requirements_path:
                    new_dep = dependencies('requirements.txt')
                    new_dep.deps_repo_path = requirements_path
                    new_dep.deps_local_path = root_path + '/' + repo + '/' + requirements_path
                    new_node.files.append(new_dep)
                if sibling:
                    if float(tag) <= sibling["tag"]:    # throw an error that tag should be incremental
                        messages.error(request, "Tag should be incremental")
                        return redirect('/add_node')
                    else:
                        new_node.sibling = sibling["_id"]
                new_node._id = records.count_documents({}) + 1
                json_data = json.dumps(new_node, default=lambda o: o.__dict__, indent=4)
                json_data = json.loads(json_data)
                records.insert_one(json_data)
                parent_node = records.find_one({"_id": int(request.POST['parent'])})
                parent_node["children"].append(new_node._id)
                records.replace_one({"_id": int(request.POST['parent'])}, parent_node)
                #
                parameter = {
                    "repo_name": new_node.repo_name,
                    "component_name": new_node.component_name,
                    "tag": new_node.tag,
                }
                build_component(parameter)
                # response = requests.post("http://127.0.0.1:9000/build", data=parameter)
                # response = response.json()
                # # print(response)
                # # polling every 10 seconds
                # parameter = {"job_id": response["job_id"]}
                # while True:
                #     response = requests.post("http://127.0.0.1:9000/poll", data=parameter)
                #     response = response.json()
                #     if response["status"] == "Success" or response["status"] == "Failed":
                #         print(response["status"])
                #         break
                #     time.sleep(10)
                messages.success(request, "Component Created Successfully.")
        else:
            repo = request.POST['repo_name']
            parent = request.POST['parent']
            type(parent)
            tag = request.POST['Tag']
            img_name = request.POST['img_name']
            dockerfile_local_path = request.POST['dockerfile_local_path']
            requirements_local_path = request.POST['requirements_local_path']
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
            #
            parameter = {"dockerfile_local_path": new_node.dockerfile_local_path,
                         "img_name": new_node.img_name,
                         "tag": new_node.tag}
            response = requests.post("http://127.0.0.1:9000/build_no_comp", data=parameter)
            response = response.json()
            # print(response)
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

    if request.method == 'POST':
        repo_name = request.POST['repo_name']
        p = Process(target=auto_sync_newnode, args=(repo_name,))
        p.start()
        p.join()
        if p.exitcode == 0:
            messages.success(request, 'Repository Synced Successfully')
        else:
            messages.error(request, 'Sync Failed')
        return redirect('/')


def auto_sync(request):
    repo_name = None
    p = Process(target=auto_sync_newnode, args=(repo_name,))
    messages.info(request, "Auto Sync in Progress")
    p.start()
    p.join()
    messages.info(request, "Auto Sync Completed")
    return redirect('/')




