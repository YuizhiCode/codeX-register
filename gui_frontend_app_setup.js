        const activeTab = Vue.ref("dash");
        const menuOptions = [
          { label: "工作台", key: "dash" },
          { label: "数据", key: "data" },
          { label: "邮箱设置", key: "mail" },
          { label: "服务设置", key: "settings" },
          { label: "运行日志", key: "logs" }
        ];

        const themeOverrides = {
          common: {
            fontFamily: "Space Grotesk, PingFang SC, Microsoft YaHei, sans-serif",
            primaryColor: "#3ea6ff",
            primaryColorHover: "#74beff",
            primaryColorPressed: "#2f8bdb",
            infoColor: "#48b5ff",
            successColor: "#45d4af",
            warningColor: "#f7b267",
            errorColor: "#f46b78",
            bodyColor: "#0b1017",
            cardColor: "#111a29",
            modalColor: "#111a29",
            popoverColor: "#121d2d",
            borderColor: "#24344b",
            textColorBase: "#d9e3ef",
            textColor2: "#a9bdd2",
            textColor3: "#8ea3bb"
          },
          Layout: {
            color: "#0d1420",
            siderColor: "#0f1725",
            headerColor: "rgba(9, 15, 24, 0.85)",
            contentColor: "#0c131e",
            borderColor: "#24344b"
          },
          Card: {
            borderRadius: "14px",
            color: "rgba(16, 25, 38, 0.9)",
            titleFontSizeSmall: "15px",
            borderColor: "#2a3a51"
          },
          DataTable: {
            thColor: "#121d2d",
            tdColor: "rgba(16, 25, 38, 0.62)",
            borderColor: "#27384f",
            thTextColor: "#bfd1e4",
            tdTextColor: "#d5e2f0"
          },
          Input: {
            color: "rgba(13, 20, 32, 0.82)",
            colorFocus: "rgba(13, 20, 32, 0.92)",
            border: "1px solid #2a3a51",
            borderHover: "1px solid #3a516e",
            borderFocus: "1px solid #3ea6ff"
          },
          Alert: {
            borderRadius: "10px"
          }
        };

        const status = Vue.reactive({
          running: false,
          status_text: "就绪",
          progress: 0,
          sync_busy: false,
          remote_busy: false,
          remote_test_busy: false,
          run_planned_total: 0,
          run_success_count: 0,
          run_retry_total: 0,
          run_success_rate: 100,
          run_last_retry_reason: "",
          run_retry_reasons_top: [],
          run_elapsed_sec: 0,
          run_avg_success_sec: 0
        });

        const dashForm = Vue.reactive({
          num_accounts: 1,
          num_files: 1,
          concurrency: 1,
          sleep_min: 5,
          sleep_max: 30,
          fast_mode: false,
          proxy: ""
        });

        const settingsForm = Vue.reactive({
          mail_service_provider: "mailfree",
          mail_domain_allowlist: [],
          worker_domain: "",
          freemail_username: "",
          freemail_password: "",
          mailfree_random_domain: true,
          openai_ssl_verify: true,
          skip_net_check: false,
          flclash_enable_switch: false,
          flclash_controller: "127.0.0.1:9090",
          flclash_secret: "",
          flclash_group: "PROXY",
          flclash_switch_policy: "round_robin",
          flclash_switch_wait_sec: 1.2,
          flclash_delay_test_url: "https://www.gstatic.com/generate_204",
          flclash_delay_timeout_ms: 4000,
          flclash_delay_max_ms: 1800,
          flclash_delay_retry: 1,
          remote_test_concurrency: 4,
          remote_test_ssl_retry: 2,
          accounts_sync_api_url: "",
          accounts_sync_bearer_token: "",
          accounts_list_api_base: "",
          accounts_list_timezone: "Asia/Shanghai"
        });

        const loading = Vue.reactive({
          start: false,
          save: false,
          json: false,
          accounts: false,
          sync: false,
          remote: false,
          remote_test: false,
          remote_revive: false,
          remote_delete: false,
          logs: false,
          mail_overview: false,
          mail_generate: false,
          mail_emails: false,
          mail_detail: false,
          mail_delete: false,
          mailbox_delete: false,
          mail_clear: false
        });

        const jsonRows = Vue.ref([]);
        const jsonSelection = Vue.ref([]);
        const jsonNoteDraft = Vue.reactive({});
        const jsonNoteSaving = Vue.reactive({});
        const jsonInfo = Vue.reactive({ file_count: 0, account_total: 0 });

        const accountRows = Vue.ref([]);
        const accountSelection = Vue.ref([]);
        const accountBatchFiles = Vue.ref([]);
        const accountInfo = Vue.reactive({ total: 0, path: "accounts.txt", file_options: [] });

        const remoteRows = Vue.ref([]);
        const remoteSelection = Vue.ref([]);
        const remoteSearch = Vue.ref("");
        const remoteMeta = Vue.reactive({
          total: 0,
          pages: 1,
          loaded: 0,
          ready: false,
          testing: false,
          test_total: 0,
          test_done: 0,
          test_ok: 0,
          test_fail: 0
        });

        const mailProviders = Vue.ref([]);
        const mailDomains = Vue.ref([]);
        const mailboxRows = Vue.ref([]);
        const mailboxSelection = Vue.ref([]);
        const mailboxSearch = Vue.ref("");
        const selectedMailbox = Vue.ref("");
        const mailRows = Vue.ref([]);
        const mailSelection = Vue.ref([]);
        const selectedMailId = Vue.ref("");
        const mailDetail = Vue.reactive({
          id: "",
          from: "",
          subject: "",
          date: "",
          content: ""
        });
        const mailState = Vue.reactive({
          provider: "mailfree",
          loaded: false,
          email_total: 0
        });
        const mailDomainErrors = Vue.reactive({});
        const mailDomainRegistered = Vue.reactive({});
        const showMailModal = Vue.ref(false);

        const logLines = Vue.ref([]);
        const logSince = Vue.ref(0);
        const logScrollbarRef = Vue.ref(null);

        let pollTimer = null;
        let pollTick = 0;

        const progressPercent = Vue.computed(() => {
          const p = Number(status.progress || 0) * 100;
          return Math.max(0, Math.min(100, Math.round(p)));
        });

        const totalPlanCount = Vue.computed(() => {
          const perFile = Math.max(1, Number(dashForm.num_accounts || 1));
          const files = Math.max(1, Number(dashForm.num_files || 1));
          return perFile * files;
        });

        const statusTagType = Vue.computed(() => {
          if (status.running) return "success";
          if ((status.status_text || "").includes("停止")) return "warning";
          return "default";
        });

        const runSuccessRateText = Vue.computed(() => {
          const rate = Number(status.run_success_rate || 100);
          const retry = Number(status.run_retry_total || 0);
          const success = Number(status.run_success_count || 0);
          const planned = Number(status.run_planned_total || 0);
          const elapsed = Number(status.run_elapsed_sec || 0);
          const avgSec = Number(status.run_avg_success_sec || 0);
          const plannedText = planned > 0 ? `${success}/${planned}` : `${success}`;
          return `成功率 ${rate.toFixed(2)}% · 成功 ${plannedText} · 重试 ${retry} 次 · 总耗时 ${elapsed.toFixed(1)}s · 平均 ${avgSec.toFixed(1)}s`;
        });

        const runRetryReasonText = Vue.computed(() => {
          const retry = Number(status.run_retry_total || 0);
          if (retry <= 0) return "重试原因：无";
          const rows = Array.isArray(status.run_retry_reasons_top)
            ? status.run_retry_reasons_top
            : [];
          const txt = rows
            .map((x) => `${String((x && x.reason) || "未知")}×${Number((x && x.count) || 0)}`)
            .join("；");
          if (txt) return `重试原因：${txt}`;
          return `重试原因：${String(status.run_last_retry_reason || "未知")}`;
        });

        const remoteInfoText = Vue.computed(() => {
          if (status.remote_test_busy || loading.remote_test) {
            const t = Number(remoteMeta.test_total || 0);
            const d = Number(remoteMeta.test_done || 0);
            const ok = Number(remoteMeta.test_ok || 0);
            const fail = Number(remoteMeta.test_fail || 0);
            return `批量测试中 · 进度 ${d}/${t} · 成功 ${ok} · 失败 ${fail}`;
          }
          if (status.remote_busy || loading.remote) {
            if (!remoteMeta.loaded) return "正在拉取第 1 页...";
            return `正在拉取中 · 已展示 ${remoteMeta.loaded} 条 · 预计 ${remoteMeta.pages} 页`;
          }
          if (!remoteMeta.loaded) {
            const t = Number(remoteMeta.test_total || 0);
            if (t > 0) {
              return `未加载列表 · 最近测试 成功 ${remoteMeta.test_ok} · 失败 ${remoteMeta.test_fail}`;
            }
            return "未加载";
          }
          const base = `已拉取 ${remoteMeta.pages} 页 · 共 ${remoteMeta.total} 条 · 已显示 ${remoteMeta.loaded} 条`;
          const t = Number(remoteMeta.test_total || 0);
          if (t > 0) {
            return `${base} · 最近测试 成功 ${remoteMeta.test_ok} · 失败 ${remoteMeta.test_fail}`;
          }
          return base;
        });

        const filteredMailboxRows = Vue.computed(() => {
          const kw = String(mailboxSearch.value || "").trim().toLowerCase();
          if (!kw) return mailboxRows.value;
          return mailboxRows.value.filter((row) => String(row.address || "").toLowerCase().includes(kw));
        });

        const mailInfoText = Vue.computed(() => {
          const dom = mailDomains.value.length;
          const box = mailboxRows.value.length;
          const em = Number(mailState.email_total || 0);
          const provider = String(mailState.provider || settingsForm.mail_service_provider || "mailfree");
          const selectedDomains = Array.isArray(settingsForm.mail_domain_allowlist)
            ? settingsForm.mail_domain_allowlist.length
            : 0;
          let regTotal = 0;
          for (const dm of mailDomains.value) {
            regTotal += Number(mailDomainRegistered[String(dm || "").toLowerCase()] || 0);
          }
          return `服务 ${provider} · 域名 ${dom} 个 · 已选域名 ${selectedDomains} 个 · 已注册 ${regTotal} 个 · 邮箱 ${box} 个 · 当前邮件 ${em} 封`;
        });

        const selectedMailLabel = Vue.computed(() => {
          if (!selectedMailId.value) return "-";
          const row = mailRows.value.find((x) => String(x.id || "") === String(selectedMailId.value));
          if (!row) return String(selectedMailId.value);
          return `${row.id} · ${row.subject}`;
        });

        const mailDetailText = Vue.computed(() => {
          const text = String(mailDetail.content || "").trim();
          if (text) return text;
          return "请选择一封邮件查看内容";
        });

        const logText = Vue.computed(() => {
          return logLines.value.join("\n");
        });

        function rowKeyPath(row) {
          return row.path;
        }

        function rowKeyAccount(row) {
          return row.key;
        }

        function rowKeyRemote(row) {
          return row.key;
        }

        function rowKeyMailbox(row) {
          return row.key;
        }

        function rowKeyMail(row) {
          return row.key;
        }

        function fileToneClass(idx) {
          const n = Number(idx);
          if (!Number.isFinite(n) || n < 0) return "";
          return `row-file-tone-${Math.abs(Math.floor(n)) % 12}`;
        }

        function jsonRowClassName(row) {
          return fileToneClass(row && row.file_color_idx);
        }

        function accountRowClassName(row) {
          return fileToneClass(row && row.source_color_idx);
        }

        function setJsonNoteDraft(path, val) {
          const p = String(path || "");
          if (!p) return;
          jsonNoteDraft[p] = String(val || "");
        }

        async function saveJsonNote(path, showSuccess = true) {
          const p = String(path || "");
          if (!p) return;
          const note = String(jsonNoteDraft[p] || "").trim();
          jsonNoteSaving[p] = true;
          try {
            const data = await apiRequest("/api/data/json/note", {
              method: "POST",
              body: { path: p, note }
            });
            const row = jsonRows.value.find((x) => String(x.path || "") === p);
            if (row) row.note = String(data.note || "");
            jsonNoteDraft[p] = String(data.note || "");
            if (showSuccess) {
              const fileName = row ? String(row.name || "") : String(data.name || "");
              message.success(`备注已保存：${fileName || "JSON"}`);
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            jsonNoteSaving[p] = false;
          }
        }

        function normalizeDomainList(values) {
          if (!Array.isArray(values)) return [];
          const out = [];
          const seen = new Set();
          for (const raw of values) {
            const d = String(raw || "").trim().toLowerCase();
            if (!d || d.includes("@") || seen.has(d)) continue;
            seen.add(d);
            out.push(d);
          }
          return out;
        }

        function domainErrorCount(domain) {
          const d = String(domain || "").trim().toLowerCase();
          if (!d) return 0;
          const raw = mailDomainErrors[d];
          const n = Number(raw || 0);
          return Number.isFinite(n) && n > 0 ? n : 0;
        }

        function domainRegisteredCount(domain) {
          const d = String(domain || "").trim().toLowerCase();
          if (!d) return 0;
          const raw = mailDomainRegistered[d];
          const n = Number(raw || 0);
          return Number.isFinite(n) && n > 0 ? n : 0;
        }

        function isDomainSelected(domain) {
          const d = String(domain || "").trim().toLowerCase();
          if (!d) return false;
          const list = normalizeDomainList(settingsForm.mail_domain_allowlist);
          return list.includes(d);
        }

        function setDomainSelection(domains) {
          settingsForm.mail_domain_allowlist = normalizeDomainList(domains);
        }

        function toggleDomain(domain) {
          const d = String(domain || "").trim().toLowerCase();
          if (!d) return;
          const list = normalizeDomainList(settingsForm.mail_domain_allowlist);
          if (list.includes(d)) {
            if (list.length <= 1) {
              message.warning("至少保留 1 个可用域名");
              return;
            }
            setDomainSelection(list.filter((x) => x !== d));
            return;
          }
          list.push(d);
          setDomainSelection(list);
        }

        function applyDomainStats(data) {
          const counts = (data && data.error_counts) || {};
          const registered = (data && data.registered_counts) || {};
          const selected = normalizeDomainList((data && data.selected) || settingsForm.mail_domain_allowlist || []);
          for (const k of Object.keys(mailDomainErrors)) {
            delete mailDomainErrors[k];
          }
          for (const k of Object.keys(mailDomainRegistered)) {
            delete mailDomainRegistered[k];
          }
          if (counts && typeof counts === "object") {
            for (const [k, v] of Object.entries(counts)) {
              const d = String(k || "").trim().toLowerCase();
              if (!d) continue;
              const n = Number(v || 0);
              if (Number.isFinite(n) && n > 0) {
                mailDomainErrors[d] = n;
              }
            }
          }
          if (registered && typeof registered === "object") {
            for (const [k, v] of Object.entries(registered)) {
              const d = String(k || "").trim().toLowerCase();
              if (!d) continue;
              const n = Number(v || 0);
              if (Number.isFinite(n) && n > 0) {
                mailDomainRegistered[d] = n;
              }
            }
          }
          if (selected.length) {
            setDomainSelection(selected);
          }
        }

        function remoteRowClassName(row) {
          const classes = [];
          if (row && row.is_dup) classes.push("row-dup-strong");
          const s = String((row && row.test_status) || "").trim();
          if (s === "封禁") classes.push("row-test-ban");
          else if (s === "Token过期") classes.push("row-test-token");
          else if (s === "429限流") classes.push("row-test-429");
          else if (s === "已复活") classes.push("row-test-revived");
          else if (s && s !== "成功" && s !== "未测试" && s !== "未测") classes.push("row-test-fail");
          return classes.join(" ");
        }

        function statusMeta(code) {
          if (code === "ok") return { type: "success", text: "已同步" };
          if (code === "pending") return { type: "warning", text: "待同步" };
          if (code === "dup") return { type: "error", text: "重复" };
          return { type: "default", text: "-" };
        }

        const flclashPolicyOptions = [
          { label: "轮询切换", value: "round_robin" },
          { label: "随机切换", value: "random" }
        ];

        const jsonColumns = [
          { type: "selection", multiple: true },
          { title: "文件名", key: "name", minWidth: 180, ellipsis: { tooltip: true } },
          { title: "账号数", key: "count", width: 80 },
          { title: "创建时间", key: "created", width: 168 },
          {
            title: "备注",
            key: "note",
            minWidth: 280,
            render(row) {
              const path = String((row && row.path) || "");
              const value = Object.prototype.hasOwnProperty.call(jsonNoteDraft, path)
                ? String(jsonNoteDraft[path] || "")
                : String((row && row.note) || "");
              const saving = !!jsonNoteSaving[path];
              return Vue.h("div", { class: "json-note-cell" }, [
                Vue.h(naive.NInput, {
                  size: "small",
                  value,
                  clearable: true,
                  maxlength: 120,
                  placeholder: "输入备注",
                  onUpdateValue: (v) => setJsonNoteDraft(path, v)
                }),
                Vue.h(
                  naive.NButton,
                  {
                    size: "small",
                    type: "primary",
                    tertiary: true,
                    loading: saving,
                    onClick: () => saveJsonNote(path, true)
                  },
                  { default: () => "保存" }
                )
              ]);
            }
          }
        ];

        const accountColumns = [
          { type: "selection", multiple: true },
          { title: "#", key: "index", width: 56 },
          { title: "来源文件", key: "source", minWidth: 220, ellipsis: { tooltip: true } },
          { title: "邮箱", key: "email", minWidth: 220, ellipsis: { tooltip: true } },
          { title: "密码", key: "password", minWidth: 180, ellipsis: { tooltip: true } },
          {
            title: "同步",
            key: "status",
            width: 90,
            render(row) {
              const meta = statusMeta(row.status);
              return Vue.h(
                naive.NTag,
                { type: meta.type, size: "small", bordered: false },
                { default: () => meta.text }
              );
            }
          }
        ];

        const remoteColumns = [
          { type: "selection", multiple: true },
          { title: "ID", key: "id", width: 64 },
          { title: "名称/邮箱", key: "name", minWidth: 210, ellipsis: { tooltip: true } },
          {
            title: "重复",
            key: "is_dup",
            width: 70,
            render(row) {
              if (!row.is_dup) {
                return Vue.h("span", { style: "color:#6b839f;" }, "-");
              }
              return Vue.h(
                naive.NTag,
                { type: "error", size: "small", bordered: false },
                { default: () => "重复" }
              );
            }
          },
          { title: "平台", key: "platform", width: 70 },
          { title: "类型", key: "type", width: 60 },
          { title: "状态", key: "status", width: 76 },
          { title: "分组", key: "groups", minWidth: 150, ellipsis: { tooltip: true } },
          { title: "5h", key: "u5h", width: 72 },
          { title: "7d", key: "u7d", width: 72 },
          {
            title: "测试",
            key: "test_status",
            width: 86,
            render(row) {
              const s = String(row.test_status || "未测试");
              if (s === "成功") {
                return Vue.h(
                  naive.NTag,
                  { type: "success", size: "small", bordered: false },
                  { default: () => "成功" }
                );
              }
              if (s === "封禁") {
                return Vue.h(
                  naive.NTag,
                  { type: "error", size: "small", bordered: false },
                  { default: () => "封禁" }
                );
              }
              if (s === "Token过期") {
                return Vue.h(
                  naive.NTag,
                  { type: "warning", size: "small", bordered: false },
                  { default: () => "Token过期" }
                );
              }
              if (s === "429限流") {
                return Vue.h(
                  naive.NTag,
                  { type: "info", size: "small", bordered: false },
                  { default: () => "429" }
                );
              }
              if (s === "已复活") {
                return Vue.h(
                  naive.NTag,
                  { type: "success", size: "small", bordered: false },
                  { default: () => "已复活" }
                );
              }
              if (s === "失败") {
                return Vue.h(
                  naive.NTag,
                  { type: "error", size: "small", bordered: false },
                  { default: () => "失败" }
                );
              }
              return Vue.h(
                naive.NTag,
                { type: "default", size: "small", bordered: false },
                { default: () => "未测" }
              );
            }
          }
        ];

        const mailboxColumns = [
          { type: "selection", multiple: true },
          { title: "邮箱地址", key: "address", minWidth: 280, ellipsis: { tooltip: true } },
          { title: "创建时间", key: "created_at", width: 168 },
          { title: "过期时间", key: "expires_at", width: 168 },
          { title: "邮件数", key: "count", width: 80 }
        ];

        const mailColumns = [
          { type: "selection", multiple: true },
          { title: "ID", key: "id", width: 140, ellipsis: { tooltip: true } },
          { title: "发件人", key: "from", minWidth: 180, ellipsis: { tooltip: true } },
          { title: "主题", key: "subject", minWidth: 220, ellipsis: { tooltip: true } },
          { title: "接收时间", key: "date", width: 170, ellipsis: { tooltip: true } }
        ];

        async function apiRequest(path, options = {}) {
          const opts = Object.assign({}, options);
          if (!opts.method) opts.method = "GET";
          if (opts.body && typeof opts.body !== "string") {
            opts.body = JSON.stringify(opts.body);
            opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
          }
          const resp = await fetch(path, opts);
          let payload = null;
          try {
            payload = await resp.json();
          } catch (_e) {
            payload = { ok: false, error: `HTTP ${resp.status}` };
          }
          if (!resp.ok || !payload.ok) {
            throw new Error(payload.error || `HTTP ${resp.status}`);
          }
          return payload.data;
        }

        function assignConfig(cfg) {
          dashForm.num_accounts = Number(cfg.num_accounts || 1);
          dashForm.num_files = Number(cfg.num_files || 1);
          dashForm.concurrency = Number(cfg.concurrency || 1);
          dashForm.sleep_min = Number(cfg.sleep_min || 5);
          dashForm.sleep_max = Number(cfg.sleep_max || 30);
          dashForm.fast_mode = !!cfg.fast_mode;
          dashForm.proxy = String(cfg.proxy || "");

          settingsForm.mail_service_provider = String(cfg.mail_service_provider || "mailfree");
          settingsForm.mail_domain_allowlist = normalizeDomainList(cfg.mail_domain_allowlist || []);
          settingsForm.worker_domain = String(cfg.worker_domain || "");
          settingsForm.freemail_username = String(cfg.freemail_username || "");
          settingsForm.freemail_password = String(cfg.freemail_password || "");
          settingsForm.mailfree_random_domain = cfg.mailfree_random_domain !== false;
          settingsForm.openai_ssl_verify = !!cfg.openai_ssl_verify;
          settingsForm.skip_net_check = !!cfg.skip_net_check;
          settingsForm.flclash_enable_switch = !!cfg.flclash_enable_switch;
          settingsForm.flclash_controller = String(cfg.flclash_controller || "127.0.0.1:9090");
          settingsForm.flclash_secret = String(cfg.flclash_secret || "");
          settingsForm.flclash_group = String(cfg.flclash_group || "PROXY");
          settingsForm.flclash_switch_policy = String(cfg.flclash_switch_policy || "round_robin");
          settingsForm.flclash_switch_wait_sec = Number(cfg.flclash_switch_wait_sec || 1.2);
          settingsForm.flclash_delay_test_url = String(cfg.flclash_delay_test_url || "https://www.gstatic.com/generate_204");
          settingsForm.flclash_delay_timeout_ms = Number(cfg.flclash_delay_timeout_ms || 4000);
          settingsForm.flclash_delay_max_ms = Number(cfg.flclash_delay_max_ms || 1800);
          settingsForm.flclash_delay_retry = Number(cfg.flclash_delay_retry || 1);
          settingsForm.remote_test_concurrency = Number(cfg.remote_test_concurrency || 4);
          settingsForm.remote_test_ssl_retry = Number(cfg.remote_test_ssl_retry || 2);
          settingsForm.accounts_sync_api_url = String(cfg.accounts_sync_api_url || "");
          settingsForm.accounts_sync_bearer_token = String(cfg.accounts_sync_bearer_token || "");
          settingsForm.accounts_list_api_base = String(cfg.accounts_list_api_base || "");
          settingsForm.accounts_list_timezone = String(cfg.accounts_list_timezone || "Asia/Shanghai");
        }

        function buildPayload() {
          return {
            num_accounts: Number(dashForm.num_accounts || 1),
            num_files: Number(dashForm.num_files || 1),
            concurrency: Number(dashForm.concurrency || 1),
            sleep_min: Number(dashForm.sleep_min || 5),
            sleep_max: Number(dashForm.sleep_max || 30),
            fast_mode: !!dashForm.fast_mode,
            proxy: String(dashForm.proxy || "").trim(),
            mail_service_provider: String(settingsForm.mail_service_provider || "mailfree").trim(),
            mail_domain_allowlist: normalizeDomainList(settingsForm.mail_domain_allowlist || []),
            worker_domain: String(settingsForm.worker_domain || "").trim(),
            freemail_username: String(settingsForm.freemail_username || "").trim(),
            freemail_password: String(settingsForm.freemail_password || "").trim(),
            mailfree_random_domain: !!settingsForm.mailfree_random_domain,
            openai_ssl_verify: !!settingsForm.openai_ssl_verify,
            skip_net_check: !!settingsForm.skip_net_check,
            flclash_enable_switch: !!settingsForm.flclash_enable_switch,
            flclash_controller: String(settingsForm.flclash_controller || "").trim(),
            flclash_secret: String(settingsForm.flclash_secret || "").trim(),
            flclash_group: String(settingsForm.flclash_group || "").trim(),
            flclash_switch_policy: String(settingsForm.flclash_switch_policy || "round_robin").trim(),
            flclash_switch_wait_sec: Number(settingsForm.flclash_switch_wait_sec || 1.2),
            flclash_delay_test_url: String(settingsForm.flclash_delay_test_url || "").trim(),
            flclash_delay_timeout_ms: Number(settingsForm.flclash_delay_timeout_ms || 4000),
            flclash_delay_max_ms: Number(settingsForm.flclash_delay_max_ms || 1800),
            flclash_delay_retry: Number(settingsForm.flclash_delay_retry || 1),
            remote_test_concurrency: Number(settingsForm.remote_test_concurrency || 4),
            remote_test_ssl_retry: Number(settingsForm.remote_test_ssl_retry || 2),
            accounts_sync_api_url: String(settingsForm.accounts_sync_api_url || "").trim(),
            accounts_sync_bearer_token: String(settingsForm.accounts_sync_bearer_token || "").trim(),
            accounts_list_api_base: String(settingsForm.accounts_list_api_base || "").trim(),
            accounts_list_timezone: String(settingsForm.accounts_list_timezone || "Asia/Shanghai").trim()
          };
        }

        async function loadConfig() {
          const data = await apiRequest("/api/config");
          assignConfig(data);
        }

        async function saveConfig(showSuccess = true) {
          loading.save = true;
          try {
            const data = await apiRequest("/api/config", {
              method: "POST",
              body: buildPayload()
            });
            assignConfig(data);
            if (showSuccess) message.success("配置已保存");
          } finally {
            loading.save = false;
          }
        }

        async function loadStatus() {
          const data = await apiRequest("/api/status");
          status.running = !!data.running;
          status.status_text = String(data.status_text || "就绪");
          status.progress = Number(data.progress || 0);
          status.sync_busy = !!data.sync_busy;
          status.remote_busy = !!data.remote_busy;
          status.remote_test_busy = !!data.remote_test_busy;
          status.run_planned_total = Number(data.run_planned_total || 0);
          status.run_success_count = Number(data.run_success_count || 0);
          status.run_retry_total = Number(data.run_retry_total || 0);
          status.run_success_rate = Number(data.run_success_rate || 100);
          status.run_last_retry_reason = String(data.run_last_retry_reason || "");
          status.run_retry_reasons_top = Array.isArray(data.run_retry_reasons_top)
            ? data.run_retry_reasons_top
            : [];
          status.run_elapsed_sec = Number(data.run_elapsed_sec || 0);
          status.run_avg_success_sec = Number(data.run_avg_success_sec || 0);
          remoteMeta.test_total = Number(data.remote_test_total || remoteMeta.test_total || 0);
          remoteMeta.test_done = Number(data.remote_test_done || remoteMeta.test_done || 0);
          remoteMeta.test_ok = Number(data.remote_test_ok || remoteMeta.test_ok || 0);
          remoteMeta.test_fail = Number(data.remote_test_fail || remoteMeta.test_fail || 0);
        }

        async function pullLogs() {
          if (loading.logs) return;
          loading.logs = true;
          try {
            const data = await apiRequest(`/api/logs?since=${logSince.value}`);
            const items = Array.isArray(data.items) ? data.items : [];
            if (items.length) {
              for (const it of items) {
                logLines.value.push(String(it.line || ""));
              }
              if (logLines.value.length > 1600) {
                logLines.value.splice(0, logLines.value.length - 1600);
              }
              await Vue.nextTick();
              const sb = logScrollbarRef.value;
              if (sb && typeof sb.scrollTo === "function") {
                sb.scrollTo({ top: 10 ** 9, left: 0 });
              } else {
                const container = document.querySelector(".log-scroll .n-scrollbar-container");
                if (container) {
                  container.scrollTop = container.scrollHeight;
                }
              }
            }
            logSince.value = Number(data.last_id || logSince.value);
          } finally {
            loading.logs = false;
          }
        }

        async function manualPoll() {
          await loadStatus();
          await pullLogs();
        }

        async function clearLogs() {
          await apiRequest("/api/logs/clear", { method: "POST" });
          logLines.value = [];
          logSince.value = 0;
          await pullLogs();
          message.success("日志已清空");
        }

        async function refreshJson(showSuccess = false) {
          loading.json = true;
          try {
            const data = await apiRequest("/api/data/json");
            jsonRows.value = Array.isArray(data.items)
              ? data.items.map((x) => ({
                path: String((x && x.path) || ""),
                name: String((x && x.name) || ""),
                count: Number((x && x.count) || 0),
                created: String((x && x.created) || "-"),
                note: String((x && x.note) || ""),
                file_color_idx: Number((x && x.file_color_idx) || 0)
              })).filter((x) => x.path)
              : [];

            const latestPathSet = new Set(jsonRows.value.map((x) => x.path));
            for (const row of jsonRows.value) {
              if (!Object.prototype.hasOwnProperty.call(jsonNoteDraft, row.path)) {
                jsonNoteDraft[row.path] = String(row.note || "");
              }
              if (!Object.prototype.hasOwnProperty.call(jsonNoteSaving, row.path)) {
                jsonNoteSaving[row.path] = false;
              }
            }
            for (const key of Object.keys(jsonNoteDraft)) {
              if (!latestPathSet.has(key)) {
                delete jsonNoteDraft[key];
                delete jsonNoteSaving[key];
              }
            }

            jsonInfo.file_count = Number(data.file_count || 0);
            jsonInfo.account_total = Number(data.account_total || 0);
            const allowed = new Set(jsonRows.value.map((x) => x.path));
            jsonSelection.value = jsonSelection.value.filter((k) => allowed.has(k));
            if (showSuccess) message.success("JSON 列表已刷新");
          } finally {
            loading.json = false;
          }
        }

        async function refreshAccounts(showSuccess = false) {
          loading.accounts = true;
          try {
            const data = await apiRequest("/api/data/accounts");
            accountRows.value = Array.isArray(data.items)
              ? data.items.map((x) => Object.assign({}, x, {
                source_color_idx: Number((x && x.source_color_idx) || -1)
              }))
              : [];
            accountInfo.total = Number(data.total || 0);
            accountInfo.path = String(data.path || "accounts.txt");
            accountInfo.file_options = Array.isArray(data.file_options)
              ? data.file_options.map((name) => ({ label: String(name), value: String(name) }))
              : [];
            const allowed = new Set(accountRows.value.map((x) => x.key));
            accountSelection.value = accountSelection.value.filter((k) => allowed.has(k));
            const allowedFiles = new Set(accountInfo.file_options.map((x) => x.value));
            accountBatchFiles.value = accountBatchFiles.value.filter((k) => allowedFiles.has(k));
            if (showSuccess) message.success("账号列表已刷新");
          } finally {
            loading.accounts = false;
          }
        }

        async function loadRemoteCache() {
          const data = await apiRequest("/api/remote/cache");
          remoteRows.value = Array.isArray(data.items)
            ? data.items.map((x) => Object.assign({}, x, { is_dup: !!x.is_dup }))
            : [];
          remoteMeta.total = Number(data.total || 0);
          remoteMeta.pages = Number(data.pages || 1);
          remoteMeta.loaded = Number(data.loaded || 0);
          remoteMeta.ready = !!data.ready;
          remoteMeta.testing = !!data.testing;
          remoteMeta.test_total = Number(data.test_total || 0);
          remoteMeta.test_done = Number(data.test_done || 0);
          remoteMeta.test_ok = Number(data.test_ok || 0);
          remoteMeta.test_fail = Number(data.test_fail || 0);
          const allowed = new Set(remoteRows.value.map((x) => x.key));
          remoteSelection.value = remoteSelection.value.filter((k) => allowed.has(k));
          if (typeof data.testing !== "undefined") {
            status.remote_test_busy = !!data.testing;
          }
        }

        async function fetchRemoteAll() {
          loading.remote = true;
          try {
            remoteRows.value = [];
            remoteSelection.value = [];
            remoteMeta.total = 0;
            remoteMeta.pages = 1;
            remoteMeta.loaded = 0;
            remoteMeta.ready = false;
            remoteMeta.testing = false;
            remoteMeta.test_total = 0;
            remoteMeta.test_done = 0;
            remoteMeta.test_ok = 0;
            remoteMeta.test_fail = 0;

            const data = await apiRequest("/api/remote/fetch-all", {
              method: "POST",
              body: { search: remoteSearch.value }
            });
            await loadRemoteCache();
            await refreshAccounts(false);
            message.success(`拉取完成：${Number(data.loaded || remoteMeta.loaded || 0)} 条`);
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.remote = false;
          }
        }

        function remoteSelectAll() {
          remoteSelection.value = remoteRows.value.map((x) => x.key);
        }

        function remoteSelectNone() {
          remoteSelection.value = [];
        }

        function remoteSelectFailed() {
          const keys = remoteRows.value
            .filter((row) => {
              const s = String(row.test_status || "").trim();
              return s === "失败" || s === "封禁" || s === "Token过期" || s === "429限流";
            })
            .map((row) => row.key);
          if (!keys.length) {
            message.warning("没有可选的测试失败账号");
            return;
          }
          remoteSelection.value = Array.from(new Set([...remoteSelection.value, ...keys]));
          message.success(`已勾选失败账号 ${keys.length} 个`);
        }

        function remoteSelectDuplicate() {
          const keys = remoteRows.value
            .filter((row) => !!row.is_dup)
            .map((row) => row.key);
          if (!keys.length) {
            message.warning("当前列表没有重复账号");
            return;
          }
          remoteSelection.value = Array.from(new Set([...remoteSelection.value, ...keys]));
          message.success(`已勾选重复账号 ${keys.length} 个`);
        }

        async function testSelectedRemoteAccounts() {
          if (!remoteSelection.value.length) {
            message.warning("请先勾选服务端账号");
            return;
          }
          loading.remote_test = true;
          try {
            const keySet = new Set(remoteSelection.value);
            const ids = remoteRows.value
              .filter((x) => keySet.has(x.key))
              .map((x) => String(x.id || "").trim())
              .filter((x) => x);
            if (!ids.length) {
              message.warning("所选行缺少账号 ID");
              return;
            }
            const data = await apiRequest("/api/remote/test-batch", {
              method: "POST",
              body: { ids }
            });
            await loadRemoteCache();
            const ok = Number(data.ok || 0);
            const fail = Number(data.fail || 0);
            if (fail === 0) {
              message.success(`批量测试完成：成功 ${ok}`);
            } else {
              message.warning(`批量测试完成：成功 ${ok}，失败 ${fail}`);
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.remote_test = false;
          }
        }

        async function reviveSelectedRemoteAccounts() {
          if (!remoteSelection.value.length) {
            message.warning("请先勾选服务端账号");
            return;
          }
          loading.remote_revive = true;
          try {
            const keySet = new Set(remoteSelection.value);
            const rows = remoteRows.value.filter((x) => keySet.has(x.key));
            const ids = rows
              .map((x) => String(x.id || "").trim())
              .filter((x) => x);
            if (!ids.length) {
              message.warning("所选行缺少账号 ID");
              return;
            }

            const tokenRows = rows.filter((x) => String(x.test_status || "").trim() === "Token过期");
            if (!tokenRows.length) {
              message.warning("所选账号中没有“Token过期”状态");
              return;
            }

            const data = await apiRequest("/api/remote/revive-batch", {
              method: "POST",
              body: { ids: tokenRows.map((x) => String(x.id || "").trim()) }
            });
            await loadRemoteCache();

            const ok = Number(data.ok || 0);
            const fail = Number(data.fail || 0);
            const apis = Array.isArray(data.api_summary)
              ? data.api_summary.slice(0, 2)
                .map((x) => `${String((x && x.api) || "-")}×${Number((x && x.count) || 0)}`)
                .join("；")
              : "";
            if (fail === 0) {
              message.success(
                `复活完成：成功 ${ok}`
                + (apis ? `；接口：${apis}` : "")
                + `；并发 ${Number(data.concurrency || 1)}`
              );
            } else {
              const errs = Array.isArray(data.results)
                ? data.results.filter((x) => !x.success).slice(0, 3)
                : [];
              const detail = errs
                .map((x) => `${String((x && x.id) || "-")}: ${String((x && x.detail) || "未知错误")}`)
                .join("；");
              message.warning(
                `复活完成：成功 ${ok}，失败 ${fail}`
                + (detail ? `；原因：${detail}` : "")
                + (apis ? `；接口：${apis}` : "")
                + `；并发 ${Number(data.concurrency || 1)}`
              );
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.remote_revive = false;
          }
        }

        async function deleteSelectedRemoteAccounts() {
          if (!remoteSelection.value.length) {
            message.warning("请先勾选要删除的账号");
            return;
          }

          const keySet = new Set(remoteSelection.value);
          const rows = remoteRows.value.filter((x) => keySet.has(x.key));
          const ids = rows.map((x) => String(x.id || "").trim()).filter((x) => x);
          if (!ids.length) {
            message.warning("所选行缺少账号 ID");
            return;
          }

          const names = rows
            .map((x) => String(x.name || x.id || ""))
            .slice(0, 10)
            .join("\n");
          const ok = window.confirm(
            `将删除以下服务端账号（共 ${ids.length} 个）：\n\n${names}${ids.length > 10 ? "\n…" : ""}\n\n此操作不可恢复。`
          );
          if (!ok) return;

          loading.remote_delete = true;
          try {
            const data = await apiRequest("/api/remote/delete-batch", {
              method: "POST",
              body: { ids }
            });

            let refreshOk = true;
            try {
              await apiRequest("/api/remote/fetch-all", {
                method: "POST",
                body: { search: remoteSearch.value }
              });
              await loadRemoteCache();
            } catch (_refreshErr) {
              refreshOk = false;
            }
            await refreshAccounts(false);

            if (Number(data.fail || 0) === 0) {
              if (refreshOk) {
                message.success(`删除完成：成功 ${data.ok}，列表已自动刷新`);
              } else {
                message.warning(`删除完成：成功 ${data.ok}，但自动刷新失败，请手动点“获取列表与额度”`);
              }
            } else {
              if (refreshOk) {
                message.warning(`删除完成：成功 ${data.ok}，失败 ${data.fail}，列表已自动刷新`);
              } else {
                message.warning(`删除完成：成功 ${data.ok}，失败 ${data.fail}；自动刷新失败，请手动点“获取列表与额度”`);
              }
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.remote_delete = false;
          }
        }

        function jsonSelectAll() {
          jsonSelection.value = jsonRows.value.map((x) => x.path);
        }

        function jsonSelectNone() {
          jsonSelection.value = [];
        }

        async function deleteSelectedJson() {
          if (!jsonSelection.value.length) {
            message.warning("请先勾选要删除的 JSON");
            return;
          }
          const names = jsonRows.value
            .filter((x) => jsonSelection.value.includes(x.path))
            .map((x) => x.name)
            .slice(0, 12)
            .join("\n");
          const ok = window.confirm(`将永久删除以下 JSON：\n\n${names}${jsonSelection.value.length > 12 ? "\n…" : ""}\n\n此操作不可恢复。`);
          if (!ok) return;

          try {
            const data = await apiRequest("/api/data/json/delete", {
              method: "POST",
              body: { paths: jsonSelection.value }
            });
            jsonSelection.value = [];
            await Promise.all([refreshJson(false), refreshAccounts(false)]);
            message.success(`删除完成：JSON ${data.removed_files} 个，账号行 ${data.removed_lines} 条`);
          } catch (e) {
            message.error(String(e.message || e));
          }
        }

        function acctSelectAll() {
          accountSelection.value = accountRows.value.map((x) => x.key);
        }

        function acctSelectNone() {
          accountSelection.value = [];
        }

        function acctSelectByFiles() {
          if (!accountBatchFiles.value.length) {
            message.warning("请先选择文件名");
            return;
          }
          const selectedFiles = new Set(accountBatchFiles.value.map((x) => String(x)));
          const keys = accountRows.value
            .filter((row) => {
              const files = Array.isArray(row.source_files) ? row.source_files : [];
              return files.some((name) => selectedFiles.has(String(name)));
            })
            .map((row) => row.key);
          if (!keys.length) {
            message.warning("所选文件下没有可勾选账号");
            return;
          }
          accountSelection.value = Array.from(new Set([...accountSelection.value, ...keys]));
          message.success(`已按文件名勾选 ${keys.length} 个账号`);
        }

        async function syncSelectedAccounts() {
          if (!accountSelection.value.length) {
            message.warning("请先勾选账号");
            return;
          }
          loading.sync = true;
          try {
            const keySet = new Set(accountSelection.value);
            const emails = accountRows.value
              .filter((x) => keySet.has(x.key))
              .map((x) => x.email);
            const data = await apiRequest("/api/data/sync", {
              method: "POST",
              body: { emails }
            });
            message.success(`同步结束：成功 ${data.ok}，失败 ${data.fail}`);
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.sync = false;
          }
        }

        function resetMailDetail() {
          selectedMailId.value = "";
          mailDetail.id = "";
          mailDetail.from = "";
          mailDetail.subject = "";
          mailDetail.date = "";
          mailDetail.content = "";
          showMailModal.value = false;
        }

        function applyMailOverview(data) {
          const providers = Array.isArray(data.providers) ? data.providers : [];
          mailProviders.value = providers.map((it) => ({
            label: String((it && it.label) || ""),
            value: String((it && it.value) || "")
          })).filter((it) => it.label && it.value);

          const current = String(data.current || settingsForm.mail_service_provider || "mailfree");
          settingsForm.mail_service_provider = current;
          mailState.provider = current;
          mailDomains.value = Array.isArray(data.domains)
            ? normalizeDomainList(data.domains)
            : [];

          const allowFromApi = normalizeDomainList(data.selected_domains || []);
          const allowFromForm = normalizeDomainList(settingsForm.mail_domain_allowlist || []);
          const domainSet = new Set(mailDomains.value);
          let allow = allowFromApi.length ? allowFromApi : allowFromForm;
          allow = allow.filter((d) => domainSet.has(d));
          if (!allow.length && mailDomains.value.length) {
            allow = [...mailDomains.value];
          }
          setDomainSelection(allow);

          const directCounts = (data && data.domain_error_counts) || {};
          const directRegistered = (data && data.domain_registered_counts) || {};
          const stats = (data && data.domain_stats) || {};
          const merged = {};
          const mergedRegistered = {};
          if (directCounts && typeof directCounts === "object") {
            for (const [k, v] of Object.entries(directCounts)) {
              const d = String(k || "").trim().toLowerCase();
              const n = Number(v || 0);
              if (d && Number.isFinite(n) && n > 0) merged[d] = n;
            }
          }
          if (directRegistered && typeof directRegistered === "object") {
            for (const [k, v] of Object.entries(directRegistered)) {
              const d = String(k || "").trim().toLowerCase();
              const n = Number(v || 0);
              if (d && Number.isFinite(n) && n > 0) mergedRegistered[d] = n;
            }
          }
          if (stats && typeof stats === "object") {
            for (const [k, v] of Object.entries(stats)) {
              const d = String(k || "").trim().toLowerCase();
              const n = Number((v && v.errors) || 0);
              if (d && Number.isFinite(n) && n > 0) merged[d] = n;
              const reg = Number((v && v.registered) || 0);
              if (d && Number.isFinite(reg) && reg > 0) mergedRegistered[d] = reg;
            }
          }
          applyDomainStats({
            error_counts: merged,
            registered_counts: mergedRegistered,
            selected: allow
          });

          mailboxRows.value = Array.isArray(data.mailboxes)
            ? data.mailboxes.map((x) => ({
              key: String((x && x.key) || ((x && x.address) || "")),
              address: String((x && x.address) || ""),
              created_at: String((x && x.created_at) || "-"),
              expires_at: String((x && x.expires_at) || "-"),
              count: Number((x && x.count) || 0)
            })).filter((x) => x.address)
            : [];

          const allowedMailboxKeys = new Set(mailboxRows.value.map((x) => x.key));
          mailboxSelection.value = mailboxSelection.value.filter((k) => allowedMailboxKeys.has(k));

          const addrSet = new Set(mailboxRows.value.map((x) => x.address));
          if (!selectedMailbox.value || !addrSet.has(selectedMailbox.value)) {
            selectedMailbox.value = "";
            mailRows.value = [];
            mailSelection.value = [];
            mailState.email_total = 0;
            resetMailDetail();
          }
          mailState.loaded = true;
        }

        async function loadMailProviders() {
          const data = await apiRequest("/api/mail/providers");
          applyMailOverview({
            providers: data.items || [],
            current: data.current || "mailfree",
            domains: mailDomains.value,
            selected_domains: settingsForm.mail_domain_allowlist,
            domain_error_counts: mailDomainErrors,
            domain_registered_counts: mailDomainRegistered,
            mailboxes: mailboxRows.value
          });
          mailState.loaded = false;
        }

        async function loadMailDomainStats() {
          try {
            const data = await apiRequest("/api/mail/domain-stats");
            applyDomainStats(data || {});
          } catch (_e) {
            // 统计接口失败不影响主流程。
          }
        }

        async function refreshMailOverview(showSuccess = true) {
          loading.mail_overview = true;
          try {
            await saveConfig(false);
            const data = await apiRequest("/api/mail/overview", {
              method: "POST",
              body: { limit: 200, offset: 0 }
            });
            applyMailOverview(data || {});
            await loadMailDomainStats();
            if (selectedMailbox.value) {
              await loadMailboxEmails(selectedMailbox.value, false);
            }
            if (showSuccess) {
              message.success(`邮箱概览已刷新：${mailDomains.value.length} 个域名，${mailboxRows.value.length} 个邮箱`);
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.mail_overview = false;
          }
        }

        function mailboxSelectAll() {
          mailboxSelection.value = filteredMailboxRows.value.map((x) => x.key);
        }

        function mailboxSelectNone() {
          mailboxSelection.value = [];
        }

        async function loadMailboxEmails(mailbox, showError = true) {
          const target = String(mailbox || "").trim();
          if (!target) {
            mailRows.value = [];
            mailSelection.value = [];
            mailState.email_total = 0;
            resetMailDetail();
            return;
          }
          loading.mail_emails = true;
          try {
            const data = await apiRequest("/api/mail/emails", {
              method: "POST",
              body: { mailbox: target }
            });
            selectedMailbox.value = target;
            mailRows.value = Array.isArray(data.items)
              ? data.items.map((x) => ({
                key: String((x && x.key) || ((x && x.id) || "")),
                id: String((x && x.id) || ""),
                from: String((x && x.from) || "-"),
                subject: String((x && x.subject) || "(无主题)"),
                date: String((x && x.date) || "-"),
                preview: String((x && x.preview) || ""),
                mailbox: String((x && x.mailbox) || target)
              })).filter((x) => x.id)
              : [];
            mailState.email_total = Number(data.total || mailRows.value.length || 0);

            const allowed = new Set(mailRows.value.map((x) => x.key));
            mailSelection.value = mailSelection.value.filter((k) => allowed.has(k));
            const selectedRow = mailRows.value.find((x) => x.id === selectedMailId.value);
            if (!selectedRow) {
              resetMailDetail();
            }
          } catch (e) {
            if (showError) message.error(String(e.message || e));
          } finally {
            loading.mail_emails = false;
          }
        }

        async function refreshSelectedMailboxEmails() {
          if (!selectedMailbox.value) {
            message.warning("请先点击一个邮箱账号");
            return;
          }
          await loadMailboxEmails(selectedMailbox.value, true);
          message.success("邮件列表已刷新");
        }

        async function loadMailDetail(mailId, showError = true) {
          const target = String(mailId || "").trim();
          if (!target) {
            resetMailDetail();
            showMailModal.value = false;
            return false;
          }
          loading.mail_detail = true;
          try {
            const data = await apiRequest("/api/mail/email/detail", {
              method: "POST",
              body: { id: target }
            });
            selectedMailId.value = String(data.id || target);
            mailDetail.id = String(data.id || target);
            mailDetail.from = String(data.from || "-");
            mailDetail.subject = String(data.subject || "(无主题)");
            mailDetail.date = String(data.date || "-");
            mailDetail.content = String(data.content || data.text || "");
            return true;
          } catch (e) {
            if (showError) message.error(String(e.message || e));
            return false;
          } finally {
            loading.mail_detail = false;
          }
        }

        async function openMailboxRow(row) {
          if (!row || !row.address) return;
          await loadMailboxEmails(row.address, true);
        }

        function mailboxRowProps(row) {
          return {
            style: row && row.address === selectedMailbox.value
              ? "background: rgba(62,166,255,.12); box-shadow: inset 0 0 0 2px rgba(62,166,255,.55);"
              : "",
            onClick: () => {
              openMailboxRow(row);
            }
          };
        }

        async function openMailRow(row) {
          if (!row || !row.id) return;
          const ok = await loadMailDetail(row.id, true);
          if (ok) {
            showMailModal.value = true;
          }
        }

        function mailRowProps(row) {
          return {
            style: row && row.id === selectedMailId.value
              ? "background: rgba(69,212,175,.14); box-shadow: inset 0 0 0 2px rgba(69,212,175,.55);"
              : "",
            onClick: () => {
              openMailRow(row);
            }
          };
        }

        async function generateMailbox() {
          loading.mail_generate = true;
          try {
            await saveConfig(false);
            const data = await apiRequest("/api/mail/generate", { method: "POST", body: {} });
            const email = String(data.email || "");
            if (!email) throw new Error("生成邮箱失败：返回为空");
            await refreshMailOverview(false);
            selectedMailbox.value = email;
            await loadMailboxEmails(email, false);
            message.success(`已生成邮箱：${email}`);
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.mail_generate = false;
          }
        }

        async function deleteSelectedMailboxes() {
          if (!mailboxSelection.value.length) {
            message.warning("请先勾选要删除的邮箱");
            return;
          }
          const keySet = new Set(mailboxSelection.value);
          const targets = mailboxRows.value.filter((x) => keySet.has(x.key)).map((x) => x.address);
          if (!targets.length) {
            message.warning("所选项不包含有效邮箱地址");
            return;
          }
          const names = targets.slice(0, 10).join("\n");
          const ok = window.confirm(
            `将删除以下邮箱（共 ${targets.length} 个）：\n\n${names}${targets.length > 10 ? "\n…" : ""}\n\n此操作不可恢复。`
          );
          if (!ok) return;

          loading.mailbox_delete = true;
          try {
            const data = await apiRequest("/api/mail/mailboxes/delete", {
              method: "POST",
              body: { addresses: targets }
            });
            mailboxSelection.value = [];
            await refreshMailOverview(false);
            if (selectedMailbox.value && !mailboxRows.value.some((x) => x.address === selectedMailbox.value)) {
              selectedMailbox.value = "";
              mailRows.value = [];
              mailSelection.value = [];
              mailState.email_total = 0;
              resetMailDetail();
            }
            const apis = Array.isArray(data.api_summary)
              ? data.api_summary.slice(0, 2)
                .map((x) => `${String((x && x.api) || "-")}×${Number((x && x.count) || 0)}`)
                .join("；")
              : "";
            if (Number(data.fail || 0) === 0) {
              const msg = `邮箱删除完成：成功 ${data.ok}`
                + (apis ? `；接口：${apis}` : "")
                + `；并发 ${Number(data.concurrency || 1)}`;
              message.success(msg);
            } else {
              const errs = Array.isArray(data.errors) ? data.errors : [];
              const detail = errs
                .slice(0, 3)
                .map((x) => `${String((x && x.address) || "-")}: ${String((x && x.error) || "未知错误")}`)
                .join("；");
              const suffix = errs.length > 3 ? "；..." : "";
              const msg = `邮箱删除完成：成功 ${data.ok}，失败 ${data.fail}`
                + (detail ? `；原因：${detail}${suffix}` : "")
                + (apis ? `；接口：${apis}` : "")
                + `；并发 ${Number(data.concurrency || 1)}`;
              message.warning(msg);
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.mailbox_delete = false;
          }
        }

        async function deleteSelectedEmails() {
          if (!mailSelection.value.length) {
            message.warning("请先勾选要删除的邮件");
            return;
          }
          const keySet = new Set(mailSelection.value);
          const ids = mailRows.value.filter((x) => keySet.has(x.key)).map((x) => x.id);
          if (!ids.length) {
            message.warning("所选项不包含有效邮件 ID");
            return;
          }
          const ok = window.confirm(`将删除已选邮件 ${ids.length} 封，确认继续？`);
          if (!ok) return;

          loading.mail_delete = true;
          try {
            const data = await apiRequest("/api/mail/emails/delete", {
              method: "POST",
              body: { ids }
            });
            mailSelection.value = [];
            if (ids.includes(String(selectedMailId.value || ""))) {
              resetMailDetail();
              showMailModal.value = false;
            }
            await loadMailboxEmails(selectedMailbox.value, false);
            if (Number(data.fail || 0) === 0) {
              message.success(`邮件删除完成：成功 ${data.ok}`);
            } else {
              const errs = Array.isArray(data.errors) ? data.errors : [];
              const detail = errs
                .slice(0, 3)
                .map((x) => `${String((x && x.id) || "-")}: ${String((x && x.error) || "未知错误")}`)
                .join("；");
              const suffix = errs.length > 3 ? "；..." : "";
              const msg = `邮件删除完成：成功 ${data.ok}，失败 ${data.fail}`
                + (detail ? `；原因：${detail}${suffix}` : "");
              message.warning(msg);
            }
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.mail_delete = false;
          }
        }

        async function clearSelectedMailboxEmails() {
          const target = String(selectedMailbox.value || "").trim();
          if (!target) {
            message.warning("请先选择邮箱账号");
            return;
          }
          const ok = window.confirm(`将清空邮箱 ${target} 的全部邮件，确认继续？`);
          if (!ok) return;

          loading.mail_clear = true;
          try {
            const data = await apiRequest("/api/mail/emails/clear", {
              method: "POST",
              body: { mailbox: target }
            });
            await loadMailboxEmails(target, false);
            await refreshMailOverview(false);
            resetMailDetail();
            showMailModal.value = false;
            message.success(`清空完成：删除 ${Number(data.deleted || 0)} 封`);
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.mail_clear = false;
          }
        }

        async function startRun() {
          loading.start = true;
          try {
            await apiRequest("/api/start", {
              method: "POST",
              body: buildPayload()
            });
            await loadStatus();
            message.success("任务已启动");
          } catch (e) {
            message.error(String(e.message || e));
          } finally {
            loading.start = false;
          }
        }

        async function stopRun() {
          try {
            await apiRequest("/api/stop", { method: "POST" });
            await loadStatus();
            message.info("已发出停止指令");
          } catch (e) {
            message.error(String(e.message || e));
          }
        }

        async function initialLoad() {
          await loadConfig();
          await Promise.all([
            refreshJson(false),
            refreshAccounts(false),
            loadRemoteCache(),
            loadMailProviders(),
            loadMailDomainStats(),
            loadStatus(),
            pullLogs()
          ]);
        }

        async function poll() {
          try {
            await loadStatus();
            await pullLogs();
            pollTick += 1;
            if (status.running && pollTick % 4 === 0) {
              await Promise.all([refreshJson(false), refreshAccounts(false)]);
            }
            if (
              activeTab.value === "data" &&
              (
                status.remote_busy ||
                loading.remote ||
                status.remote_test_busy ||
                loading.remote_test ||
                pollTick % 6 === 0
              )
            ) {
              await loadRemoteCache();
            }
            if (activeTab.value === "mail" && pollTick % 6 === 0) {
              await loadMailDomainStats();
            }
          } catch (_e) {
            // 轮询容错，下一轮重试。
          }
        }

        Vue.onMounted(async () => {
          try {
            await initialLoad();
          } catch (e) {
            message.error(String(e.message || e));
          }
          pollTimer = window.setInterval(poll, 1500);
        });

        Vue.watch(activeTab, async (tab) => {
          if (tab !== "mail") return;
          await loadMailDomainStats();
          if (mailState.loaded) return;
          try {
            await refreshMailOverview(false);
          } catch (_e) {
            // 保持静默，用户可手动刷新。
          }
        });

        Vue.onBeforeUnmount(() => {
          if (pollTimer) {
            window.clearInterval(pollTimer);
            pollTimer = null;
          }
        });

        return {
          darkTheme,
          themeOverrides,
          activeTab,
          menuOptions,
          status,
          progressPercent,
          totalPlanCount,
          statusTagType,
          runSuccessRateText,
          runRetryReasonText,
          dashForm,
          settingsForm,
          loading,
          jsonRows,
          jsonSelection,
          jsonInfo,
          accountRows,
          accountSelection,
          accountBatchFiles,
          accountInfo,
          remoteRows,
          remoteSelection,
          remoteSearch,
          remoteMeta,
          remoteInfoText,
          mailProviders,
          mailDomains,
          mailboxRows,
          mailboxSelection,
          mailboxSearch,
          selectedMailbox,
          filteredMailboxRows,
          mailRows,
          mailSelection,
          selectedMailId,
          selectedMailLabel,
          mailDetail,
          mailState,
          mailDomainErrors,
          mailDomainRegistered,
          showMailModal,
          mailInfoText,
          mailDetailText,
          logText,
          logScrollbarRef,
          flclashPolicyOptions,
          jsonColumns,
          accountColumns,
          remoteColumns,
          mailboxColumns,
          mailColumns,
          rowKeyPath,
          rowKeyAccount,
          rowKeyRemote,
          rowKeyMailbox,
          rowKeyMail,
          jsonRowClassName,
          accountRowClassName,
          isDomainSelected,
          toggleDomain,
          domainErrorCount,
          domainRegisteredCount,
          mailboxRowProps,
          mailRowProps,
          remoteRowClassName,
          saveConfig,
          refreshJson,
          refreshAccounts,
          fetchRemoteAll,
          remoteSelectAll,
          remoteSelectNone,
          remoteSelectFailed,
          remoteSelectDuplicate,
          testSelectedRemoteAccounts,
          reviveSelectedRemoteAccounts,
          deleteSelectedRemoteAccounts,
          jsonSelectAll,
          jsonSelectNone,
          deleteSelectedJson,
          acctSelectAll,
          acctSelectNone,
          acctSelectByFiles,
          syncSelectedAccounts,
          refreshMailOverview,
          loadMailDomainStats,
          generateMailbox,
          mailboxSelectAll,
          mailboxSelectNone,
          deleteSelectedMailboxes,
          refreshSelectedMailboxEmails,
          deleteSelectedEmails,
          clearSelectedMailboxEmails,
          startRun,
          stopRun,
          clearLogs,
          manualPoll
        };
