$(function () {
    let treeview = {
        resetBtnToggle: function () {
            $(".js-treeview")
                .find(".level-add")
                .find("span")
                .removeClass()
                .addClass("fa fa-ellipsis-v");
            $(".js-treeview")
                .find(".level-add")
                .siblings()
                .removeClass("in");
        },

        removeLevel: function (target) {
            target.closest("li").remove();
        }
    };

    // Treeview Functions
    $(".js-treeview").on("click", ".level-add", function () {
        $(this).find("span").toggleClass("fa-ellipsis-v").toggleClass("fa-times text-danger");
        $(this).siblings().toggleClass("in");
    });

    // Upgrade Node
    $(".js-treeview").on("click", ".upgrade-node", function () {
        target = $(this);
        let liElm = target.closest("li");
        let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
        let url = '/manual_sync_on_node?sync_type=0&node_id=' + node_id
        $(this).siblings().toggleClass("in");
        treeview.resetBtnToggle();
        window.location.href = url;
    });

    // Update Node
    $(".js-treeview").on("click", ".update-node", function () {
        target = $(this);
        let liElm = target.closest("li");
        let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
        let url = '/manual_sync_on_node?sync_type=1&node_id=' + node_id
        $(this).siblings().toggleClass("in");
        treeview.resetBtnToggle();
        window.location.href = url;
    });

    // Add new Node
    $(".js-treeview").on("click", ".add-child", function () {
        target = $(this);
        let liElm = target.closest("li");
        let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
        let url = '/add_child_view?node_id=' + node_id
        $(this).siblings().toggleClass("in");
        treeview.resetBtnToggle();
        window.location.href = url;
    });

    // Edit Node
    $(".js-treeview").on("click", ".edit-node", function () {
        target = $(this);
        let liElm = target.closest("li");
        let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
        let url = '/edit_node?node_id=' + node_id
        $(this).siblings().toggleClass("in");
        treeview.resetBtnToggle();
        window.location.href = url;
    });

    // Delete
    $(".js-treeview").on("click", ".delete-node", function () {
        target = $(this);
        let liElm = target.closest("li");
        let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
        let url = '/delete_node?delete_siblings=0&node_id=' + node_id
        $(this).siblings().toggleClass("in");
        treeview.resetBtnToggle();
        window.location.href = url
    });


    // Selected Level
    $(".js-treeview").on("click", ".level-title", function () {
        let isSelected = $(this).closest("[data-level]").hasClass("selected");
        !isSelected && $(this).closest(".js-treeview").find("[data-level]").removeClass("selected");
        $(this).closest("[data-level]").toggleClass("selected");
    });
});
