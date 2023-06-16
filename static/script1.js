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

// function createNode(name, levelCode) {
//     const treeview__level = document.createElement('div');
//     treeview__level.classList.add('treeview__level');
//     treeview__level.setAttribute('data-level', levelCode);
//
//     const level_title = document.createElement('span');
//     level_title.classList.add('level-title');
//     const text = document.createTextNode(name);
//     level_title.appendChild(text);
//
//     const treeview__level_btns = document.createElement('div');
//     treeview__level_btns.classList.add('treeview__level-btns');
//
//     const level_add = document.createElement('div');
//     level_add.classList.add('btn', 'btn-default', 'btn-sm', 'level-add');
//     const fa_plus = document.createElement('span');
//     fa_plus.classList.add('fa', 'fa-plus');
//     level_add.appendChild(fa_plus);
//
//     const level_remove = document.createElement('div');
//     level_remove.classList.add('btn', 'btn-default', 'btn-sm', 'level-remove');
//     const fa_trash = document.createElement('span');
//     fa_trash.classList.add('fa', 'fa-trash', 'text-danger');
//     level_remove.appendChild(fa_trash);
//
//     const level_same = document.createElement('div');
//     level_same.classList.add('btn', 'btn-default', 'btn-sm', 'level-same');
//     const same_level = document.createElement('span');
//     same_level.appendChild(document.createTextNode('Add same level'));
//     level_same.appendChild(same_level);
//
//     const level_sub = document.createElement('div');
//     level_sub.classList.add('btn', 'btn-default', 'btn-sm', 'level-sub');
//     const sub_level = document.createElement('span');
//     sub_level.appendChild(document.createTextNode('Add sub level'));
//     level_sub.appendChild(sub_level);
//
//     treeview__level_btns.appendChild(level_add);
//     treeview__level_btns.appendChild(level_remove);
//     treeview__level_btns.appendChild(level_same);
//     treeview__level_btns.appendChild(level_sub);
//
//     treeview__level.appendChild(level_title);
//     treeview__level.appendChild(treeview__level_btns);
//
//     return treeview__level;
// }
//
// function parentFunction(jsondata){
//     const treeview = document.getElementsByClassName('treeview js-treeview')[0];
//     const ul = treeview.firstElementChild;
//     if(jsondata.length > 1) {
//         for(rootnode of jsondata) {
//             ul.appendChild(createGeneration(rootnode, '1'));
//         }
//     } else {
//         ul.appendChild(createGeneration(jsondata, '1'));
//     }
// }
//
// function createGeneration(jsondata, level) {
//     const name = jsondata.img_name + ':' + jsondata.tag + ' ' + `( ${jsondata.sibling==null? '' : jsondata.sibling})`;
//     const node = createNode(name, level);
//     const li = document.createElement('li');
//     li.appendChild(node);
//     const ul = document.createElement('ul');
//     if(jsondata.children.length != 0) {
//         for(child of jsondata.children) {
//             ul.appendChild(createGeneration(child, `${+level + 1}`));
//         }
//     }
//     li.appendChild(ul);
//     return li;
// }

function createNode(name, levelCode) {
    const treeview__level = document.createElement('div');
    treeview__level.addEventListener('click', (event) => hideChildren(event));
    treeview__level.classList.add('treeview__level');
    treeview__level.setAttribute('data-level', levelCode);

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

    const level_same = document.createElement('div');
    level_same.classList.add('btn', 'btn-default', 'btn-sm', 'level-same');
    const same_level = document.createElement('span');
    same_level.appendChild(document.createTextNode('Sync'));
    level_same.appendChild(same_level);

    const level_sub = document.createElement('div');
    level_sub.classList.add('btn', 'btn-default', 'btn-sm', 'level-sub');
    const sub_level = document.createElement('span');
    sub_level.appendChild(document.createTextNode('Add Child'));
    level_sub.appendChild(sub_level);

    treeview__level_btns.appendChild(level_add);
    treeview__level_btns.appendChild(level_remove);
    treeview__level_btns.appendChild(level_same);
    treeview__level_btns.appendChild(level_sub);

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

function parentFunction(jsondata){
    const treeview = document.getElementsByClassName('treeview js-treeview')[0];
    const ul = treeview.firstElementChild;
    if(jsondata.length > 1) {
        for(rootnode of jsondata) {
            ul.appendChild(createGeneration(rootnode, '1'));
        }
    } else {
        ul.appendChild(createGeneration(jsondata, '1'));
    }
    //treeview.appendChild(details);
}

function createGeneration(jsondata, level) {
    const name = jsondata.img_name + ':' + jsondata.tag + ' ' + `(${jsondata.sibling==null? '' : jsondata.sibling})`;
    const node = createNode(name, level);
    const li = document.createElement('li');
    li.appendChild(node);
    const ul = document.createElement('ul');
    if(jsondata.children.length != 0) {
        for(child of jsondata.children) {
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
        <div class="btn btn-default btn-sm level-same"><span>Add Same Level</span></div>
        <div class="btn btn-default btn-sm level-sub"><span>Add Sub Level</span></div>
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
                <div class="btn btn-default btn-sm level-same"><span>Add Same Level</span></div>
                <div class="btn btn-default btn-sm level-sub"><span>Add Sub Level</span></div>
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
                <div class="btn btn-default btn-sm level-same"><span>Add Same Level</span></div>
                <div class="btn btn-default btn-sm level-sub"><span>Add Sub Level</span></div>
            </div>
        </div>
    </li>
</ul>





*/