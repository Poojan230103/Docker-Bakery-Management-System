$(function() {
  let treeview = {
    resetBtnToggle: function() {
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

    removeLevel: function(target) {
      target.closest("li").remove();
    }
  };

  // Treeview Functions
  $(".js-treeview").on("click", ".level-add", function() {
    $(this).find("span").toggleClass("fa-ellipsis-v").toggleClass("fa-times text-danger");
    $(this).siblings().toggleClass("in");
  });

  // Upgrade Node
  $(".js-treeview").on("click", ".upgrade-node", function() {
    target = $(this);
    let liElm = target.closest("li");
    let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
    let url = '/manual_sync?sync_type=0&node_id=' + node_id
    window.location.replace(url)
  });

  // Update Node
  $(".js-treeview").on("click", ".update-node", function() {
    target = $(this);
    let liElm = target.closest("li");
    let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
    // console.log("hello from update " + node_id)
    let url = '/manual_sync?sync_type=1&node_id=' + node_id
    window.location.replace(url)
  });

  // Add new Node
  $(".js-treeview").on("click", ".add-child", function() {
    target = $(this);
    let liElm = target.closest("li");
    let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
    let url = '/add_node?node_id=' + node_id
    // window.location.replace(url)
    window.location.href = url
  });

    // Edit Node
  $(".js-treeview").on("click", ".edit-node", function() {
    target = $(this);
    let liElm = target.closest("li");
    let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
    let url = '/edit_node?node_id=' + node_id
    window.location.href = url
  });

  $(".js-treeview").on("click", ".delete-node", function() {
    target = $(this);
    let liElm = target.closest("li");
    let node_id = `${+liElm.find("[data-node_id]").attr("data-node_id")}`;
    let url = '/delete_node?node_id=' + node_id
    window.location.href = url
  });


    // Remove Level
  $(".js-treeview").on("click", ".level-remove", function() {
    treeview.removeLevel($(this));
  });

  // Selected Level
  $(".js-treeview").on("click", ".level-title", function() {
    let isSelected = $(this).closest("[data-level]").hasClass("selected");
    !isSelected && $(this).closest(".js-treeview").find("[data-level]").removeClass("selected");
    $(this).closest("[data-level]").toggleClass("selected");
  });
});
