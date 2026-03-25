    (function () {
    const Vue = window.Vue;
    const naive = window.naive;
    if (!Vue || !naive) {
      if (window.__codexRenderFail) {
        window.__codexRenderFail("资源加载失败", "未能加载 Vue / Naive UI 资源，请检查网络后重试。");
      }
      return;
    }

    const {
      darkTheme,
      NConfigProvider,
      NLayout,
      NLayoutSider,
      NLayoutHeader,
      NLayoutContent,
      NMenu,
      NCard,
      NButton,
      NForm,
      NFormItem,
      NInput,
      NInputNumber,
      NSelect,
      NSwitch,
      NSpace,
      NTag,
      NProgress,
      NAlert,
      NDataTable,
      NScrollbar,
      NModal
    } = naive;

    const { message } = naive.createDiscreteApi(["message"]);

    const App = {
      components: {
        NConfigProvider,
        NLayout,
        NLayoutSider,
        NLayoutHeader,
        NLayoutContent,
        NMenu,
        NCard,
        NButton,
        NForm,
        NFormItem,
        NInput,
        NInputNumber,
        NSelect,
        NSwitch,
        NSpace,
        NTag,
        NProgress,
        NAlert,
        NDataTable,
        NScrollbar,
        NModal
      },
      setup() {
__GUI_FRONTEND_APP_SETUP__
      },
      template: `
__GUI_FRONTEND_APP_TEMPLATE__

      `
    };

    Vue.createApp(App).mount("#app");
    window.__codexMounted = true;
    })();
