from django.db import models
from datetime import datetime


class treenode:
    def __init__(self, img_name):
        self._id = None
        self.img_name = img_name.split(':')[0]
        self.tag = float(img_name.split(':')[1])
        self.children = []
        self.parent = None
        self.sibling = None
        self.dockerfile_local_path = None
        self.dockerfile_repo_path = None
        self.repo_name = None
        self.created_time = self.last_updated_time = self.last_synced_time = str(datetime.now().replace(microsecond=0))
        self.component_name = None
        self.architecture = "arm" if "arm" in img_name else "intel"
        self.files = []


class dependencies:
    def __init__(self, name):
        self.name = name
        self.deps_local_path = None
        self.deps_repo_path = None


