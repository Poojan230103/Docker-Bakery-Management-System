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

    addSameLevel: function(target) {
      let ulElm = target.closest("ul");
      let sameLevelCodeASCII = target
        .closest("[data-level]")
        .attr("data-level")
      ulElm.append($("#levelMarkup").html());
      ulElm
        .children("li:last-child")
        .find("[data-level]")
        .attr("data-level", sameLevelCodeASCII);
    },
    addSubLevel: function(target) {
      let liElm = target.closest("li");
      let nextLevelCodeASCII = `${+liElm.find("[data-level]").attr("data-level") + 1}`;
      liElm.children("ul").append($("#levelMarkup").html());
      liElm.children("ul").find("[data-level]")
        .attr("data-level", nextLevelCodeASCII);
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

  // Add same level
  $(".js-treeview").on("click", ".level-same", function() {
    treeview.addSameLevel($(this));
    treeview.resetBtnToggle();
  });

  // Add sub level
  $(".js-treeview").on("click", ".level-sub", function() {
    treeview.addSubLevel($(this));
    treeview.resetBtnToggle();
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
