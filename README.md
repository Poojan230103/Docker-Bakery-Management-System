# Docker-Bakery-Management-System

## Project Description

This system incorporates a global image bakery for publishing base images and creating a hierarchical structure among Docker images and visualizing them using UI. The system automates the re-deployments on Kubernetes upon any change in the component Images.
This is a version control type of system where we can use the sibling nodes to compare what changed in new version of an image.


## Features of the Project:

1) Visualization of parent-child and sibling relationship between images through UI.
2) Functionality to automatically sync the image and its sub-tree with the global image bakery.
3) Manually sync a node to its latest version by upgrading or updating the node.
4) Adding a new node with the help of UI.
5) We can edit the dockerfile of any node and re-build it and its sub-tree using its updated dockerfile.
6) Deleting any image along with its dependent children images.