from django.shortcuts import render
import pymongo
import json
from django.http import HttpResponse


class treenode:

    def __init__(self,data):
        self.__dict__ = data

    _id = None
    img_name = None
    tag = None
    children = []
    parent = None
    sibling = None
    dockerfile_local_path = None
    dockerfile_repo_path = None
    repo_name = None
    created_time = None
    last_updated_time = None
    last_synced_time = None
    component_name = None
    architecture = None
    files = []


client = pymongo.MongoClient("mongodb+srv://admin:me_Poojan23@cluster0.z9bxxjw.mongodb.net/?retryWrites=true&w=majority")
db = client.get_database('myDB')
records = db['Images']


def create_hierarchy(data, parent_id=None):     # to create hierarchy
    hierarchy = []
    for item in data:
        if item["parent"] == parent_id:
            children = create_hierarchy(data, parent_id=item["_id"])
            item["children"] = children
            hierarchy.append(item)
    return hierarchy


def get_data():     # fetches the data from the database and converts it into hierarchical format to display it in UI

    all_images_cursor = records.find()
    list_cursor = list(all_images_cursor)
    json_data = json.dumps(list_cursor, indent=4)       # converting cursor object returned by mongoDB to json format.

    # with open('./static/data.json', 'w') as file:
    #     file.write(json_data)

    data = json.loads(json_data)        # converts json data to python object
    print(type(data))
    data = sorted(data, key=lambda x: x['img_name'].split()[0])
    for img in data:
        if img["sibling"]:
            node = records.find_one({"_id": img["sibling"]})
            img["sibling"] = str(node["img_name"] + ':' + node["tag"])
    hierarchy = create_hierarchy(data)
    # print(hierarchy)
    json_data = json.dumps(hierarchy[0],indent=2)
    # print(json_data)
    f = open('./static/data.json', 'w')
    f.write(json_data)
    f.close()


def index(request):
    get_data()
    return render(request,'index.html')


def add_node(request):
    return HttpResponse("<h1> Hii </h1>")