/* 招聘背调授权与结果封存系统 —— 前端逻辑（Vue 3，本地模拟登录 X-User-Id） */
const { createApp } = Vue;

const STATUS = {
  granted: "授权有效", withdrawn: "已撤回", expired: "已到期", position_cancelled: "岗位已取消",
  pending: "待回传", received: "已回传", sealed: "已封存",
  approved: "已批准", rejected: "已驳回",
};

const SAMPLE = {
  identity: { name: "李明", id_no: "110101199001011234", match: "人证一致" },
  education: { school: "示例理工大学", degree: "硕士", graduation: "正常毕业", student_id: "20120001" },
  employment: { employer: "华跃科技有限公司", period: "2019.07-2024.06", title: "高级工程师",
                leaving_reason: "个人职业规划", salary: "26000" },
  credit: { summary: "无重大失信记录", overdue_count: "0", debt_detail: "信用卡负债 3.2 万", account_no: "6222 **** **** 8801" },
  criminal: { result: "未发现相关记录", record_detail: "（渠道明细，含查询编号与辖区信息）" },
};

const app = createApp({
  data() {
    return {
      userId: null,
      users: [],
      catalog: {},
      agencies: [],
      consents: [],
      checks: [],
      anomalies: [],
      corrections: [],
      accessLogs: [],
      notifications: [],
      showTab: "audit",
      forms: { consent: null, initiate: null, submit: null, result: null, anomaly: null,
               correction: null, timeline: null, notif: false },
      resultView: "masked",
      resultData: null,
      resultError: "",
      timeline: [],
      toast: null,
      initiateScopeError: "",
    };
  },
  computed: {
    me() { return this.users.find(u => u.id === this.userId) || { role: "" }; },
    candidateUsers() { return this.users.filter(u => u.role === "candidate"); },
    staffUsers() { return this.users.filter(u => u.role === "compliance" || u.role === "recruiter"); },
    pendingAnomalies() { return this.anomalies.filter(a => a.status === "pending"); },
    pendingCorrections() { return this.corrections.filter(r => r.status === "pending"); },
    unreadCount() { return this.notifications.filter(n => !n.read).length; },
  },
  async mounted() {
    this.users = await this.api("/users");
    this.userId = this.users[0]?.id ?? null;
    [this.catalog, this.agencies] = await Promise.all([
      this.api("/catalog"), this.api("/agencies").catch(() => []),
    ]);
    await this.refreshAll();
    setInterval(() => this.loadNotifications(true), 15000);
  },
  methods: {
    // ------------------------------------------------------------ API
    async api(path, opts = {}) {
      const res = await fetch("/api" + path, {
        ...opts,
        headers: { "Content-Type": "application/json", "X-User-Id": String(this.userId),
                   ...(opts.headers || {}) },
      });
      const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data.error ? `${data.error.message}（${data.error.code}）` : `请求失败 ${res.status}`;
        const err = new Error(msg);
        err.code = data.error?.code;
        throw err;
      }
      return data;
    },
    async loadBase() {
      this.users = await this.api("/users");
    },
    async refreshAll() {
      this.initiateScopeError = "";
      await Promise.all([
        this.loadConsents(), this.loadChecks(), this.loadNotifications(true),
        this.me.role === "compliance" ? this.loadCompliance() : Promise.resolve(),
        this.me.role === "candidate" ? this.loadCorrections() : Promise.resolve(),
      ]);
    },
    async loadConsents() { this.consents = await this.api("/consents"); },
    async loadChecks() { this.checks = await this.api("/checks"); },
    async loadAnomalies() { this.anomalies = await this.api("/anomalies"); },
    async loadCorrections() { this.corrections = await this.api("/corrections"); },
    async loadAccessLogs() { this.accessLogs = await this.api("/access-logs"); },
    async loadNotifications(silent) {
      try { this.notifications = await this.api("/notifications"); }
      catch (e) { if (!silent) this.flash(e.message, "error"); }
    },
    async loadCompliance() {
      await Promise.all([this.loadAnomalies(), this.loadCorrections(), this.loadAccessLogs()]);
    },
    async switchUser() {
      this.forms = { consent: null, initiate: null, submit: null, result: null, anomaly: null,
                     correction: null, timeline: null, notif: false };
      this.showTab = "audit";
      this.agencies = await this.api("/agencies").catch(() => []);
      await this.refreshAll();
    },

    // ------------------------------------------------------------ 标签
    roleLabel(r) { return { candidate: "候选人", recruiter: "招聘专员", compliance: "合规人员", agency: "合作机构" }[r] || r; },
    statusLabel(s) { return STATUS[s] || s; },
    checkStatusLabel(s) { return STATUS[s] || s; },
    anomalyLabel(s) { return STATUS[s] || s; },
    corrLabel(s) { return { pending: "待处理", approved: "已批准更正", rejected: "已驳回" }[s] || s; },
    targetLabel(t) {
      return { masked_result: "脱敏结果", full_material: "完整材料", raw_receipt: "原始回执" }[t] || t;
    },
    fmt(ts) {
      if (!ts) return "—";
      const d = new Date(ts);
      const p = n => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    },
    fieldLabel(path) {
      const [item, field] = path.split(".");
      const it = this.catalog[item];
      if (!it) return path;
      return field ? `${it.label}·${it.fields[field]?.label || field}` : it.label;
    },
    timelineLabel(t) {
      return {
        consent_granted: "授权生效", check_initiated: "发起背调", result_received: "机构回传结果",
        result_duplicate: "机构重复回传（原结果保留）", anomaly_raised: "登记异常结论",
        anomaly_decided: "异常结论审批", correction_requested: "候选人申请更正",
        correction_approved: "更正获批并生效", correction_rejected: "更正被驳回",
        consent_withdrawn: "候选人撤回授权", position_cancelled: "岗位取消",
        check_sealed: "结果封存",
      }[t] || t;
    },
    detailText(e) {
      const d = e.detail || {};
      switch (e.type) {
        case "check_initiated": return `调查项目：${(d.items || []).map(i => this.catalog[i]?.label).join("、")}`;
        case "consent_withdrawn":
        case "position_cancelled": return `原因：${d.reason || "—"}`;
        case "check_sealed": return `封存原因：${d.reason}`;
        case "result_duplicate": return `备注：${d.note || "—"}；原始结果 #${d.kept_original_result_id} 未覆盖`;
        case "anomaly_decided": return `决定：${d.decision === "approved" ? "批准" : "驳回"}；处理结果：${d.resolution || "—"}；意见：${d.note || "—"}`;
        case "correction_approved": return `${this.fieldLabel(d.field_path)}：${d.old_value} → ${d.new_value}`;
        case "correction_rejected": return `驳回意见：${d.note || "—"}`;
        case "anomaly_raised": return `标题：${d.title}`;
        case "result_received": return `结果 #${d.result_id}`;
        default: return "";
      }
    },
    canViewFullId(id) {
      const chk = this.checks.find(c => c.id === id);
      return chk && (chk.viewer_ids || []).includes(this.userId);
    },
    flash(text, kind = "") {
      this.toast = { text, kind };
      setTimeout(() => (this.toast = null), 3200);
    },

    // ------------------------------------------------------------ 授权
    openConsentForm() {
      this.forms.consent = {
        candidate_id: this.candidateUsers[0]?.id, position: "",
        approved_items: ["identity", "education"], viewer_ids: [this.userId],
        valid_days: 30, consent_text: "本人已被明确告知调查项目、结果可见范围及授权期限，并同意在上述范围内开展背景调查。",
      };
    },
    async submitConsent() {
      const f = this.forms.consent;
      if (!f.position.trim()) return this.flash("请填写岗位名称", "error");
      if (!f.approved_items.length) return this.flash("至少选择一个调查项目", "error");
      try {
        await this.api("/consents", { method: "POST", body: JSON.stringify({
          candidate_id: f.candidate_id, recruiter_id: this.userId, position: f.position,
          approved_items: f.approved_items, viewer_ids: f.viewer_ids,
          valid_days: f.valid_days, consent_text: f.consent_text,
        }) });
        this.forms.consent = null;
        this.flash("授权已生成（视为候选人已同意并签署）", "ok");
        await this.refreshAll();
      } catch (e) { this.flash(e.message, "error"); }
    },
    async withdraw(c) {
      const reason = prompt("请填写撤回原因：", "暂不考虑该机会");
      if (reason === null) return;
      try {
        await this.api(`/consents/${c.id}/withdraw`, { method: "POST", body: JSON.stringify({ reason }) });
        this.flash("授权已撤回，已有结果已封存，新查询被阻止", "ok");
        await this.refreshAll();
      } catch (e) { this.flash(e.message, "error"); }
    },
    async cancelPosition(c) {
      const reason = prompt("请填写岗位取消原因：", "招聘 HC 冻结");
      if (reason === null) return;
      try {
        await this.api(`/consents/${c.id}/cancel-position`, {
          method: "POST", body: JSON.stringify({ reason }),
        });
        this.flash("岗位已取消，相关调查结果封存", "ok");
        await this.refreshAll();
      } catch (e) { this.flash(e.message, "error"); }
    },

    // ------------------------------------------------------------ 发起背调
    openInitiate(c) {
      this.initiateScopeError = "";
      this.forms.initiate = {
        code: c.code, id: c.id, candidate: c.candidate, position: c.position,
        approved_items: c.approved_items,
        agency_id: this.agencies[0]?.id, requested_items: [...c.approved_items],
      };
    },
    async submitInitiate() {
      const f = this.forms.initiate;
      const over = f.requested_items.filter(i => !f.approved_items.includes(i));
      if (over.length) { this.initiateScopeError = "超范围项目被拦截：" + over.join("、"); return; }
      try {
        await this.api("/checks", { method: "POST", body: JSON.stringify({
          consent_id: f.id, agency_id: f.agency_id, requested_items: f.requested_items,
        }) });
        this.forms.initiate = null;
        this.flash("背调单已下发给承办机构", "ok");
        await this.refreshAll();
      } catch (e) { this.initiateScopeError = e.message; }
    },

    // ------------------------------------------------------------ 机构回传
    openSubmit(check) {
      const payload = {};
      check.requested_items.forEach(k => { payload[k] = {}; });
      this.forms.submit = { check, payload, raw_receipt: "" };
    },
    fillSample() {
      const f = this.forms.submit;
      f.check.requested_items.forEach(k => { f.payload[k] = { ...SAMPLE[k] }; });
      f.raw_receipt = `【${this.me.display_name}】原始回执编号 RC-${String(Date.now()).slice(-8)}；\n` +
        `本回执为机构渠道原始报文，含数据源、查询时间戳与经办人信息，仅限合规人员查阅。`;
    },
    async submitResult() {
      const f = this.forms.submit;
      try {
        const r = await this.api("/checks/result", { method: "POST", body: JSON.stringify({
          check_code: f.check.code, payload: f.payload, raw_receipt: f.raw_receipt,
        }) });
        this.forms.submit = null;
        this.flash(r.duplicate ? "重复回传已登记，原始结果保留未覆盖" : "结果回传成功", r.duplicate ? "" : "ok");
        await this.refreshAll();
      } catch (e) { this.flash(e.message, "error"); }
    },

    // ------------------------------------------------------------ 结果查看（三级）
    openResult(check, view = "masked") {
      this.forms.result = { check };
      this.resultData = null;
      this.resultError = "";
      this.resultView = view;
      this.loadResult(view);
    },
    async loadResult(view) {
      this.resultView = view;
      this.resultData = null;
      this.resultError = "";
      const chk = this.forms.result.check;
      try {
        this.resultData = await this.api(`/checks/${chk.id}/result?view=${view}`);
      } catch (e) { this.resultError = e.message; }
    },

    // ------------------------------------------------------------ 异常
    openAnomaly(check) {
      this.forms.anomaly = { code: check.code, check_id: check.id,
                             title: "", conclusion: "", basis: "", evidence_ref: "" };
    },
    async submitAnomaly() {
      const f = this.forms.anomaly;
      if (!f.title || !f.conclusion || !f.basis) return this.flash("标题、结论、依据均为必填", "error");
      try {
        await this.api("/anomalies", { method: "POST", body: JSON.stringify({ ...f }) });
        this.forms.anomaly = null;
        this.flash("异常已登记，等待另一名合规人员批准", "ok");
        if (this.me.role === "compliance") await this.loadAnomalies();
      } catch (e) { this.flash(e.message, "error"); }
    },
    async decideAnomaly(a, approve) {
      const note = prompt(approve ? "请填写批准意见与依据：" : "请填写驳回理由：",
                          approve ? "经复核，证据链完整" : "证据不足");
      if (note === null) return;
      let resolution = "";
      if (approve) {
        resolution = prompt("请填写处理结果（随记录保留）：", "维持不予录用建议") || "";
      }
      try {
        await this.api(`/anomalies/${a.id}/decision`, {
          method: "POST", body: JSON.stringify({ approve, decision_note: note, resolution }),
        });
        this.flash(approve ? "已批准" : "已驳回", "ok");
        await this.loadAnomalies();
      } catch (e) { this.flash(e.message, "error"); }
    },

    // ------------------------------------------------------------ 更正
    openCorrection(check) {
      const firstItem = check.requested_items[0];
      const firstField = this.catalog[firstItem] ? Object.keys(this.catalog[firstItem].fields)[0] : "";
      this.forms.correction = { check, field_path: `${firstItem}.${firstField}`,
                                claimed_value: "", reason: "" };
    },
    async submitCorrection() {
      const f = this.forms.correction;
      if (!f.field_path.includes(".") || f.field_path.endsWith(".")) return this.flash("请选择字段", "error");
      if (!f.claimed_value) return this.flash("请填写主张的正确内容", "error");
      try {
        await this.api("/corrections", { method: "POST", body: JSON.stringify({
          check_id: f.check.id, field_path: f.field_path,
          claimed_value: f.claimed_value, reason: f.reason,
        }) });
        this.forms.correction = null;
        this.flash("更正申请已提交，等待合规核实", "ok");
        await this.loadCorrections();
      } catch (e) { this.flash(e.message, "error"); }
    },
    async decideCorrection(r, approve) {
      const note = prompt(approve ? "核实情况 / 依据：" : "驳回理由：",
                          approve ? "已向数据源核实并取得证明" : "无法证实");
      if (note === null) return;
      let corrected_value = "";
      if (approve) corrected_value = prompt("确认更正后的内容（默认采用候选人主张值）：", r.claimed_value) || r.claimed_value;
      try {
        await this.api(`/corrections/${r.id}/decision`, {
          method: "POST", body: JSON.stringify({ approve, decision_note: note, corrected_value }),
        });
        this.flash(approve ? "更正已生效，原始结果保留" : "已驳回", "ok");
        await this.loadCorrections();
      } catch (e) { this.flash(e.message, "error"); }
    },

    // ------------------------------------------------------------ 时间线 / 通知
    async openTimeline(check) {
      this.forms.timeline = check;
      this.timeline = await this.api(`/checks/${check.id}/timeline`);
    },
    async openNotifications() {
      this.forms.notif = true;
      await this.loadNotifications();
      this.notifications.filter(n => !n.read).forEach(n =>
        this.api(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => {}));
    },
  },
});

// ------------------------------------------------------------ 弹窗组件
app.component("modal", {
  props: { wide: Boolean },
  template: `
    <div class="modal-mask" @click.self="$emit('close')">
      <div class="modal" :class="{wide}"><slot /></div>
    </div>`,
});

// ------------------------------------------------------------ 背调列表组件
app.component("check-table", {
  props: ["checks", "me", "canViewFullId"],
  emits: ["result", "timeline"],
  methods: {
    checkStatusLabel(s) { return STATUS[s] || s; },
  },
  template: `
    <table class="tbl" v-if="checks.length">
      <tr><th>背调单号</th><th>候选人/岗位</th><th>调查项目</th><th>机构</th><th>状态</th><th>操作</th></tr>
      <tr v-for="c in checks" :key="c.id">
        <td>{{ c.code }}
          <div v-if="c.duplicate_count" class="muted">重复回传 ×{{ c.duplicate_count }}</div></td>
        <td>{{ c.candidate_name }}<div class="muted">{{ c.position }}</div></td>
        <td>{{ c.requested_item_labels.join('、') }}</td>
        <td>{{ c.agency.name }}</td>
        <td>
          <span :class="'st st-'+c.status">{{ checkStatusLabel(c.status) }}</span>
          <span v-if="c.pending_anomalies" class="tag tag-sens">待处理异常×{{ c.pending_anomalies }}</span>
        </td>
        <td class="ops">
          <button class="btn" :disabled="!c.has_result" @click="$emit('result', c, 'masked')">脱敏结果</button>
          <button class="btn" :disabled="!c.has_result"
                  :title="canViewFullId(c.id) ? '您在授权可见人名单中' : '完整材料需在授权可见人名单内'"
                  @click="$emit('result', c, 'full')">
            完整材料{{ canViewFullId(c.id) || me.role==='compliance' ? '' : '（无权限）' }}
          </button>
          <button class="btn" v-if="me.role==='compliance'" :disabled="!c.has_result"
                  @click="$emit('result', c, 'raw')">原始回执</button>
          <button class="btn" @click="$emit('timeline', c)">时间线</button>
        </td>
      </tr>
    </table>
    <div v-else class="empty">暂无背调单</div>`,
});

app.mount("#app");
