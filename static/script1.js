fetch('/static/data.json')
.then(function(resp){
    return resp.json();
})
.then(function(data){
   parentFunction(data);
    const uls = document.querySelectorAll('li ul');
    for(ul of uls) ul.classList.add('hide');
    //ul.classList.add('hide');
});


function createNode(name, levelCode, node_id) {
    const treeview__level = document.createElement('div');
    treeview__level.addEventListener('click', (event) => hideChildren(event));
    treeview__level.classList.add('treeview__level');
    treeview__level.setAttribute('data-level', levelCode);
    treeview__level.setAttribute('data-node_id', node_id);

    const level_title = document.createElement('span');
    level_title.classList.add('level-title');
    const text = document.createTextNode(name);
    level_title.appendChild(text);

    const treeview__level_btns = document.createElement('div');
    treeview__level_btns.classList.add('treeview__level-btns');

    const level_add = document.createElement('div');
    level_add.classList.add('btn', 'btn-default', 'btn-sm', 'level-add');
    const fa_ellipsis = document.createElement('span');
    fa_ellipsis.classList.add('fa', 'fa-ellipsis-v');
    level_add.appendChild(fa_ellipsis);

    const level_remove = document.createElement('div');
    level_remove.classList.add('btn', 'btn-default', 'btn-sm', 'level-remove');
    const fa_trash = document.createElement('span');
    fa_trash.classList.add('fa', 'fa-trash', 'text-danger');
    level_remove.appendChild(fa_trash);

    const update_node = document.createElement('div');
    update_node.classList.add('btn', 'btn-default', 'btn-sm', 'update-node');
    const update_span = document.createElement('span');
    update_span.appendChild(document.createTextNode('Update Node'));
    update_node.appendChild(update_span);

    const upgrade_node = document.createElement('div');
    upgrade_node.classList.add('btn', 'btn-default', 'btn-sm', 'upgrade-node');
    const upgrade_span = document.createElement('span');
    upgrade_span.appendChild(document.createTextNode('Upgrade Node'));
    upgrade_node.appendChild(upgrade_span);

    const add_child = document.createElement('div');
    add_child.classList.add('btn', 'btn-default', 'btn-sm', 'add-child');
    const child_span = document.createElement('span');
    child_span.appendChild(document.createTextNode('Add Child'));
    add_child.appendChild(child_span);

    const edit_node = document.createElement('div');
    edit_node.classList.add('btn', 'btn-default', 'btn-sm', 'edit-node');
    const edit_span = document.createElement('span');
    edit_span.appendChild(document.createTextNode('Edit Node'));
    edit_node.appendChild(edit_span);

    treeview__level_btns.appendChild(level_add);
    treeview__level_btns.appendChild(level_remove);
    treeview__level_btns.appendChild(update_node);
    treeview__level_btns.appendChild(upgrade_node);
    treeview__level_btns.appendChild(add_child);
    treeview__level_btns.appendChild(edit_node);

    treeview__level.appendChild(level_title);
    treeview__level.appendChild(treeview__level_btns);

    return treeview__level;
}

function hideChildren(event) {
    let div = event.target.closest('div');
    console.log(div);
    let ul = div.nextElementSibling;
    console.log(ul);
    if(ul.classList.contains('hide')) ul.classList.remove('hide');
    else ul.classList.add('hide');
}

function parentFunction(json_data){
    const treeview = document.getElementsByClassName('treeview js-treeview')[0];
    const ul = treeview.firstElementChild;
    if(json_data.length > 1) {
        for(rootnode of json_data) {
            ul.appendChild(createGeneration(rootnode, '1'));
        }
    } else {
        ul.appendChild(createGeneration(json_data, '1'));
    }
    //treeview.appendChild(details);
}

function createGeneration(json_data, level) {
    const name = json_data.img_name + ':' + json_data.tag + ' ' + `(${json_data.sibling==null? '' : json_data.sibling})`;
    const node = createNode(name, level, json_data._id);
    const li = document.createElement('li');
    li.appendChild(node);
    const ul = document.createElement('ul');
    if(json_data.children.length != 0) {
        for(child of json_data.children) {
            ul.appendChild(createGeneration(child, `${+level + 1}`));
        }
    }
    li.appendChild(ul);
    return li;
}



/*

A node
<div class="treeview__level" data-level="A">
    <span class="level-title">Level A</span>
    <div class="treeview__level-btns">
        <div class="btn btn-default btn-sm level-add"><span class="fa fa-plus"></span></div>
        <div class="btn btn-default btn-sm level-remove"><span class="fa fa-trash text-danger"></span></div>
        <div class="btn btn-default btn-sm update-node"><span>Add Same Level</span></div>
        <div class="btn btn-default btn-sm add-child"><span>Add Sub Level</span></div>
    </div>
</div>

Its child
<ul>

    Child 1
    <li>
        <div class="treeview__level" data-level="B">
            <span class="level-title">Level A</span>
            <div class="treeview__level-btns">
                <div class="btn btn-default btn-sm level-add"><span class="fa fa-plus"></span></div>
                <div class="btn btn-default btn-sm level-remove"><span class="fa fa-trash text-danger"></span></div>
                <div class="btn btn-default btn-sm update-node"><span>Add Same Level</span></div>
                <div class="btn btn-default btn-sm add-child"><span>Add Sub Level</span></div>
            </div>
        </div>
    </li>

    Child 2
    <li>
        <div class="treeview__level" data-level="B">
            <span class="level-title">Level A</span>
            <div class="treeview__level-btns">
                <div class="btn btn-default btn-sm level-add"><span class="fa fa-plus"></span></div>
                <div class="btn btn-default btn-sm level-remove"><span class="fa fa-trash text-danger"></span></div>
                <div class="btn btn-default btn-sm update-node"><span>Add Same Level</span></div>
                <div class="btn btn-default btn-sm add-child"><span>Add Sub Level</span></div>
            </div>
        </div>
    </li>
</ul>





*/