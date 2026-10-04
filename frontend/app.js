/* 企业招聘背调授权与结果封存系统 —— 前端(Vue 3,无构建步骤) */
const { createApp, ref, reactive, computed, onMounted } = Vue;

/* ---------------- API ---------------- */
const store = {
  token: localStorage.getItem("bgc_token") || "",
  user: JSON.parse(localStorage.getItem("bgc_user") || "null"),
};

async function req(method, url, body, extraHeaders) {
  const headers = { ...(extraHeaders || {}) };
  if (store.token) headers["Authorization"] = "Bearer " + store.token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const resp = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 空响应 */ }
  if (!resp.ok) {
    const err = new Error((data && data.detail) || `请求失败(${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  return data;
}
const get = (u) => req("GET", u);
const post = (u, b) => req("POST", u, b);

const ROLE_NAMES = { recruiter: "招聘专员", compliance: "合规人员", candidate: "候选人", agency: "背调机构" };
const CHECK_STATUS = { pending: "待回传", completed: "已完成", cancelled: "已取消" };
const EVENT_NAMES = {
  authorization_created: "发起授权", candidate_consented: "候选人同意", authorization_revoked: "撤回授权",
  authorization_expired: "授权到期", check_initiated: "发起查询", check_cancelled: "查询取消",
  result_received: "结果回传", duplicate_result_received: "重复回传隔离", raw_receipt_viewed: "查看原始回执",
  anomaly_submitted: "提交异常结论", anomaly_resolved: "异常办结", correction_requested: "更正申请",
  correction_resolved: "更正办结", results_sealed: "结果封存", position_cancelled: "岗位取消",
};

function fmtTime(s) { return s ? s.replace("T", " ").slice(0, 19) : "-"; }
function statusTag(status) {
  const map = {
    pending: "orange", active: "green", revoked: "red", expired: "red", cancelled: "red",
    open: "orange", approved: "green", rejected: "red", resolved: "green",
    normal: "green", abnormal: "red", completed: "green",
  };
  return map[status] || "blue";
}

/* ---------------- 通用组件 ---------------- */

const TimelineModal = {
  props: ["authId", "title"],
  emits: ["close"],
  data: () => ({ events: [], error: "" }),
  async mounted() {
    try { this.events = await get(`/api/authorizations/${this.authId}/timeline`); }
    catch (e) { this.error = e.message; }
  },
  template: `
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <h3>调查与处理时间线 —— {{ title }}</h3>
      <div v-if="error" class="alert error">{{ error }}</div>
      <div class="timeline" v-if="events.length">
        <div class="ev" v-for="e in events" :key="e.id">
          <div><span class="tag blue">{{ EVENT_NAMES[e.event_type] || e.event_type }}</span>
            <span class="muted"> {{ fmtTime(e.created_at) }} · {{ e.actor }}</span></div>
          <div>{{ e.detail }}</div>
        </div>
      </div>
      <p v-else class="muted">暂无事件</p>
      <div style="text-align:right;margin-top:12px"><button class="ghost" @click="$emit('close')">关闭</button></div>
    </div>
  </div>`,
  methods: { fmtTime },
  computed: { EVENT_NAMES() { return EVENT_NAMES; } },
};

const ResultModal = {
  props: ["result", "canRaw"],
  emits: ["close"],
  data: () => ({ rawData: null, error: "", loadingRaw: false }),
  methods: {
    fmtTime,
    async viewRaw() {
      this.loadingRaw = true; this.error = "";
      try {
        this.rawData = await get(`/api/results/${this.result.id}?raw=true`);
      } catch (e) { this.error = e.message; }
      this.loadingRaw = false;
    },
  },
  template: `
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <h3>结果详情 #{{ result.id }} —— {{ result.item_label }}
        <span class="tag" :class="result.conclusion === 'abnormal' ? 'red' : 'green'">{{ result.conclusion === 'abnormal' ? '异常' : '正常' }}</span>
        <span v-if="result.sealed" class="tag orange">已封存</span>
      </h3>
      <p class="muted">回传机构:{{ result.agency_name }} · {{ fmtTime(result.created_at) }} · 当前视图:脱敏(敏感字段已隐藏)</p>
      <pre class="payload">{{ JSON.stringify(result.payload, null, 2) }}</pre>

      <div v-if="canRaw" style="margin-top:12px">
        <button class="warn" @click="viewRaw" :disabled="loadingRaw">
          {{ loadingRaw ? '加载中…' : '查看原始回执(将记录访问日志)' }}
        </button>
        <div v-if="error" class="alert error" style="margin-top:8px">{{ error }}</div>
        <div v-if="rawData" style="margin-top:10px">
          <p class="tag red">原始回执(完整材料)—— 本次访问已留痕</p>
          <pre class="payload">{{ JSON.stringify(rawData.payload, null, 2) }}</pre>
        </div>
      </div>
      <div style="text-align:right;margin-top:12px"><button class="ghost" @click="$emit('close')">关闭</button></div>
    </div>
  </div>`,
};

/* ---------------- 登录 ---------------- */

const LoginView = {
  emits: ["login"],
  data: () => ({ users: [], username: "", password: "123456", error: "" }),
  async mounted() { this.users = await get("/api/auth/demo-users"); },
  methods: {
    async doLogin() {
      this.error = "";
      try {
        const r = await post("/api/auth/login", { username: this.username, password: this.password });
        this.$emit("login", r);
      } catch (e) { this.error = e.message; }
    },
  },
  template: `
  <div class="login-box">
    <div class="card">
      <h3 style="text-align:center">企业招聘背调授权与结果封存系统</h3>
      <p class="muted" style="text-align:center;margin-bottom:8px">本地演示环境 · 密码均为 123456</p>
      <label>选择账号</label>
      <select v-model="username">
        <option value="" disabled>请选择</option>
        <option v-for="u in users" :key="u.id" :value="u.username">
          {{ u.name }}({{ ROLE_NAMES[u.role] }})
        </option>
      </select>
      <label>密码</label>
      <input v-model="password" type="password" @keyup.enter="doLogin" />
      <div v-if="error" class="alert error" style="margin-top:10px">{{ error }}</div>
      <button style="width:100%;margin-top:14px" @click="doLogin" :disabled="!username">登 录</button>
      <p class="muted" style="margin-top:12px">机构回传请使用「机构模拟控制台」(登录页外,首页可切换)。</p>
    </div>
  </div>`,
  computed: { ROLE_NAMES() { return ROLE_NAMES; } },
};

/* ---------------- 招聘专员 ---------------- */

const RecruiterView = {
  components: { TimelineModal, ResultModal },
  data: () => ({
    tab: "auth",
    positions: [], auths: [], checks: [], results: [], anomalies: [],
    candidates: [], users: [], catalog: [],
    newPos: { title: "", department: "" },
    newAuth: { candidate_id: "", position_id: "", scope: [], viewer_ids: [], purpose: "招聘录用背景调查", expires_at: "" },
    msg: "", err: "",
    timelineFor: null, viewResult: null,
    anomalyFor: null, anomalyForm: { description: "", proposed_conclusion: "" },
  }),
  async mounted() { await this.reload(); },
  methods: {
    fmtTime, statusTag,
    async reload() {
      [this.positions, this.auths, this.checks, this.results, this.anomalies,
       this.candidates, this.users, this.catalog] = await Promise.all([
        get("/api/positions"), get("/api/authorizations"), get("/api/checks"),
        get("/api/results"), get("/api/anomalies"), get("/api/candidates"),
        get("/api/users"), get("/api/catalog/items"),
      ]);
    },
    async run(fn, okMsg) {
      this.err = ""; this.msg = "";
      try { await fn(); this.msg = okMsg; await this.reload(); }
      catch (e) { this.err = e.message; }
    },
    createPosition() {
      this.run(async () => {
        await post("/api/positions", this.newPos);
        this.newPos = { title: "", department: "" };
      }, "岗位已创建");
    },
    cancelPosition(p) {
      if (!confirm(`确认取消岗位「${p.title}」?相关授权将作废,已有结果按权限封存。`)) return;
      this.run(() => post(`/api/positions/${p.id}/cancel`), "岗位已取消,结果已封存");
    },
    createAuth() {
      this.run(async () => {
        await post("/api/authorizations", {
          ...this.newAuth,
          candidate_id: Number(this.newAuth.candidate_id),
          position_id: Number(this.newAuth.position_id),
          viewer_ids: this.newAuth.viewer_ids.map(Number),
          expires_at: new Date(this.newAuth.expires_at).toISOString(),
        });
        this.newAuth.scope = []; this.newAuth.viewer_ids = [];
      }, "授权已发起,等待候选人同意");
    },
    checkOf(authId, item) {
      return this.checks.find((c) => c.authorization_id === authId && c.item === item && c.status !== "cancelled");
    },
    initiate(authId, item) {
      this.run(() => post("/api/checks", { authorization_id: authId, item }), "查询已发起,等待机构回传");
    },
    openAnomaly(result) {
      this.anomalyFor = result;
      this.anomalyForm = { description: "", proposed_conclusion: "" };
    },
    submitAnomaly() {
      this.run(async () => {
        await post("/api/anomalies", { result_id: this.anomalyFor.id, ...this.anomalyForm });
        this.anomalyFor = null;
      }, "异常结论已提交,等待合规审批");
    },
    tryRaw(result) { this.viewResult = result; },
  },
  template: `
  <div>
    <div class="tabs">
      <button :class="{active: tab==='auth'}" @click="tab='auth'">授权管理</button>
      <button :class="{active: tab==='pos'}" @click="tab='pos'">岗位管理</button>
      <button :class="{active: tab==='result'}" @click="tab='result'">结果与异常</button>
    </div>
    <div v-if="err" class="alert error">{{ err }}</div>
    <div v-if="msg" class="alert ok">{{ msg }}</div>

    <!-- 授权管理 -->
    <div v-show="tab==='auth'">
      <div class="card">
        <h3>发起背调授权(候选人同意后方可查询)</h3>
        <div class="grid3">
          <div><label>候选人</label>
            <select v-model="newAuth.candidate_id">
              <option value="" disabled>请选择</option>
              <option v-for="c in candidates" :key="c.id" :value="c.id">{{ c.name }}({{ c.email }})</option>
            </select></div>
          <div><label>岗位</label>
            <select v-model="newAuth.position_id">
              <option value="" disabled>请选择</option>
              <option v-for="p in openPositions" :key="p.id" :value="p.id">{{ p.title }}({{ p.department }})</option>
            </select></div>
          <div><label>授权到期时间</label>
            <input type="datetime-local" v-model="newAuth.expires_at" /></div>
        </div>
        <label>调查项目(授权页面向候选人明示)</label>
        <div class="checks-row">
          <label v-for="it in catalog" :key="it.key">
            <input type="checkbox" :value="it.key" v-model="newAuth.scope" /> {{ it.label }}
          </label>
        </div>
        <label>结果可见人(脱敏结果;原始回执仅合规可调阅并留痕)</label>
        <div class="checks-row">
          <label v-for="u in users" :key="u.id">
            <input type="checkbox" :value="u.id" v-model="newAuth.viewer_ids" /> {{ u.name }}({{ ROLE_NAMES[u.role] || u.role }})
          </label>
        </div>
        <label>调查目的</label>
        <input v-model="newAuth.purpose" />
        <div style="margin-top:12px">
          <button @click="createAuth"
            :disabled="!newAuth.candidate_id || !newAuth.position_id || !newAuth.scope.length || !newAuth.viewer_ids.length || !newAuth.expires_at">
            发起授权
          </button>
        </div>
      </div>

      <div class="card" v-for="a in auths" :key="a.id">
        <div class="row" style="justify-content:space-between">
          <h3>授权 #{{ a.id }} · {{ a.candidate_name }} · {{ a.position_title }}</h3>
          <div class="row">
            <span class="tag" :class="statusTag(a.status)">{{ a.status_label }}</span>
            <button class="ghost" @click="timelineFor = a">时间线</button>
          </div>
        </div>
        <div class="kv">
          <div><b>调查项目</b><span class="tag blue" v-for="s in a.scope" :key="s.key" style="margin-right:4px">{{ s.label }}</span></div>
          <div><b>可见人员</b>{{ a.viewers.map(v => v.name).join('、') }}</div>
          <div><b>到期时间</b>{{ fmtTime(a.expires_at) }} <b style="margin-left:16px">目的</b>{{ a.purpose }}</div>
        </div>
        <div v-if="a.status === 'active'" class="row" style="margin-top:10px">
          <span class="muted">发起查询:</span>
          <template v-for="s in a.scope" :key="s.key">
            <button v-if="!checkOf(a.id, s.key)" @click="initiate(a.id, s.key)">{{ s.label }}</button>
            <span v-else class="tag" :class="checkOf(a.id, s.key).status === 'completed' ? 'green' : 'orange'">
              {{ s.label }} · {{ CHECK_STATUS[checkOf(a.id, s.key).status] }}
            </span>
          </template>
        </div>
        <p v-else-if="a.status === 'pending'" class="muted" style="margin-top:8px">等待候选人同意,暂不能发起查询。</p>
        <p v-else class="muted" style="margin-top:8px">授权已{{ a.status_label }},禁止发起新查询;已有结果按权限封存。</p>
      </div>
    </div>

    <!-- 岗位管理 -->
    <div v-show="tab==='pos'">
      <div class="card">
        <h3>新建岗位</h3>
        <div class="grid2">
          <div><label>岗位名称</label><input v-model="newPos.title" /></div>
          <div><label>部门</label><input v-model="newPos.department" /></div>
        </div>
        <button style="margin-top:10px" @click="createPosition" :disabled="!newPos.title">创建</button>
      </div>
      <div class="card">
        <h3>我的岗位</h3>
        <table>
          <thead><tr><th>ID</th><th>岗位</th><th>部门</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="p in positions" :key="p.id">
              <td>{{ p.id }}</td><td>{{ p.title }}</td><td>{{ p.department }}</td>
              <td><span class="tag" :class="p.status === 'open' ? 'green' : 'red'">{{ p.status === 'open' ? '开放' : '已取消' }}</span></td>
              <td><button v-if="p.status === 'open'" class="danger" @click="cancelPosition(p)">取消岗位</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 结果与异常 -->
    <div v-show="tab==='result'">
      <div class="card">
        <h3>背调结果(默认脱敏;原始回执仅合规人员有权调阅)</h3>
        <table>
          <thead><tr><th>ID</th><th>项目</th><th>结论</th><th>状态</th><th>回传时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in results" :key="r.id">
              <td>{{ r.id }}</td><td>{{ r.item_label }}</td>
              <td><span class="tag" :class="r.conclusion === 'abnormal' ? 'red' : 'green'">{{ r.conclusion === 'abnormal' ? '异常' : '正常' }}</span></td>
              <td><span v-if="r.sealed" class="tag orange">已封存</span><span v-else class="tag green">有效</span></td>
              <td>{{ fmtTime(r.created_at) }}</td>
              <td class="row">
                <button class="ghost" @click="tryRaw(r)">查看详情</button>
                <button v-if="r.conclusion === 'abnormal'" class="warn" @click="openAnomaly(r)">提交异常结论</button>
              </td>
            </tr>
            <tr v-if="!results.length"><td colspan="6" class="muted">暂无结果</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>我提交的异常处理单</h3>
        <table>
          <thead><tr><th>ID</th><th>结果</th><th>说明</th><th>建议结论</th><th>状态</th><th>处理依据</th></tr></thead>
          <tbody>
            <tr v-for="c in anomalies" :key="c.id">
              <td>{{ c.id }}</td><td>#{{ c.result_id }}</td><td>{{ c.description }}</td>
              <td>{{ c.proposed_conclusion }}</td>
              <td><span class="tag" :class="statusTag(c.status)">{{ {open:'待审批',approved:'已批准',rejected:'已驳回'}[c.status] }}</span></td>
              <td>{{ c.resolution_basis || '-' }}<br/><span class="muted">{{ c.resolved_by_name ? '处理人:' + c.resolved_by_name : '' }}</span></td>
            </tr>
            <tr v-if="!anomalies.length"><td colspan="6" class="muted">暂无</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 异常结论提交弹窗 -->
    <div v-if="anomalyFor" class="modal-mask" @click.self="anomalyFor = null">
      <div class="modal">
        <h3>提交异常结论 —— 结果 #{{ anomalyFor.id }}({{ anomalyFor.item_label }})</h3>
        <p class="muted">提交后由合规人员审批;提交人不能批准自己提交的结论(职责分离)。</p>
        <label>异常说明</label>
        <textarea rows="3" v-model="anomalyForm.description"></textarea>
        <label>建议结论</label>
        <textarea rows="2" v-model="anomalyForm.proposed_conclusion"></textarea>
        <div style="text-align:right;margin-top:12px">
          <button class="ghost" @click="anomalyFor = null">取消</button>
          <button @click="submitAnomaly" :disabled="!anomalyForm.description || !anomalyForm.proposed_conclusion">提交</button>
        </div>
      </div>
    </div>

    <TimelineModal v-if="timelineFor" :auth-id="timelineFor.id" :title="'授权 #' + timelineFor.id" @close="timelineFor = null" />
    <ResultModal v-if="viewResult" :result="viewResult" :can-raw="true" @close="viewResult = null" />
  </div>`,
  computed: {
    ROLE_NAMES() { return ROLE_NAMES; },
    openPositions() { return this.positions.filter((p) => p.status === "open"); },
    CHECK_STATUS() { return CHECK_STATUS; },
  },
};

/* ---------------- 候选人 ---------------- */

const CandidateView = {
  components: { TimelineModal, ResultModal },
  data: () => ({
    tab: "auth", auths: [], results: [], corrections: [],
    err: "", msg: "", timelineFor: null, viewResult: null,
    correctionFor: null, correctionContent: "",
  }),
  async mounted() { await this.reload(); },
  methods: {
    fmtTime, statusTag,
    async reload() {
      [this.auths, this.results, this.corrections] = await Promise.all([
        get("/api/authorizations"), get("/api/results"), get("/api/corrections"),
      ]);
    },
    async run(fn, okMsg) {
      this.err = ""; this.msg = "";
      try { await fn(); this.msg = okMsg; await this.reload(); }
      catch (e) { this.err = e.message; }
    },
    consent(a) { this.run(() => post(`/api/authorizations/${a.id}/consent`), "已同意授权"); },
    revoke(a) {
      if (!confirm("确认撤回授权?撤回后企业不得再发起新查询,已有结果将按权限封存。")) return;
      this.run(() => post(`/api/authorizations/${a.id}/revoke`), "授权已撤回,结果已封存");
    },
    openCorrection(r) { this.correctionFor = r; this.correctionContent = ""; },
    submitCorrection() {
      this.run(async () => {
        await post(`/api/results/${this.correctionFor.id}/corrections`, { content: this.correctionContent });
        this.correctionFor = null;
      }, "更正申请已提交,合规人员将处理");
    },
  },
  template: `
  <div>
    <div class="tabs">
      <button :class="{active: tab==='auth'}" @click="tab='auth'">我的授权</button>
      <button :class="{active: tab==='result'}" @click="tab='result'">我的结果与更正</button>
    </div>
    <div v-if="err" class="alert error">{{ err }}</div>
    <div v-if="msg" class="alert ok">{{ msg }}</div>

    <div v-show="tab==='auth'">
      <div class="card" v-for="a in auths" :key="a.id">
        <div class="row" style="justify-content:space-between">
          <h3>授权 #{{ a.id }} · 岗位「{{ a.position_title }}」</h3>
          <div class="row">
            <span class="tag" :class="statusTag(a.status)">{{ a.status_label }}</span>
            <button class="ghost" @click="timelineFor = a">时间线</button>
          </div>
        </div>
        <div class="kv">
          <div><b>调查项目</b>
            <span v-for="s in a.scope" :key="s.key" class="tag blue" style="margin-right:4px" :title="s.description">{{ s.label }}</span>
          </div>
          <div><b>哪些人能看结果</b>{{ a.viewers.map(v => v.name + '(' + (ROLE_NAMES[v.role] || v.role) + ')').join('、') }};原始回执仅合规人员可调阅且全程留痕</div>
          <div><b>授权期限</b>{{ fmtTime(a.created_at) }} 至 {{ fmtTime(a.expires_at) }}</div>
          <div><b>调查目的</b>{{ a.purpose }}</div>
        </div>
        <div class="row" style="margin-top:10px">
          <button v-if="a.status === 'pending'" @click="consent(a)">同意授权</button>
          <button v-if="a.status === 'pending' || a.status === 'active'" class="danger" @click="revoke(a)">撤回授权</button>
          <span v-if="a.status === 'revoked'" class="muted">已撤回:企业不得再发起新查询,已有结果按权限封存。</span>
        </div>
      </div>
      <div v-if="!auths.length" class="card muted">暂无授权记录</div>
    </div>

    <div v-show="tab==='result'">
      <div class="card">
        <h3>我的背调结果(脱敏视图)</h3>
        <table>
          <thead><tr><th>ID</th><th>项目</th><th>结论</th><th>时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in results" :key="r.id">
              <td>{{ r.id }}</td><td>{{ r.item_label }}</td>
              <td><span class="tag" :class="r.conclusion === 'abnormal' ? 'red' : 'green'">{{ r.conclusion === 'abnormal' ? '异常' : '正常' }}</span></td>
              <td>{{ fmtTime(r.created_at) }}</td>
              <td class="row">
                <button class="ghost" @click="viewResult = r">查看</button>
                <button class="warn" @click="openCorrection(r)">申请更正</button>
              </td>
            </tr>
            <tr v-if="!results.length"><td colspan="5" class="muted">暂无结果</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h3>我的更正申请</h3>
        <table>
          <thead><tr><th>ID</th><th>结果</th><th>内容</th><th>状态</th><th>处理说明</th></tr></thead>
          <tbody>
            <tr v-for="c in corrections" :key="c.id">
              <td>{{ c.id }}</td><td>#{{ c.result_id }}</td><td>{{ c.content }}</td>
              <td><span class="tag" :class="statusTag(c.status)">{{ {open:'待处理',resolved:'已更正',rejected:'已驳回'}[c.status] }}</span></td>
              <td>{{ c.resolution_note || '-' }}</td>
            </tr>
            <tr v-if="!corrections.length"><td colspan="5" class="muted">暂无</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="correctionFor" class="modal-mask" @click.self="correctionFor = null">
      <div class="modal">
        <h3>申请更正 —— 结果 #{{ correctionFor.id }}({{ correctionFor.item_label }})</h3>
        <label>更正说明</label>
        <textarea rows="4" v-model="correctionContent" placeholder="请说明哪项内容有误及正确信息"></textarea>
        <div style="text-align:right;margin-top:12px">
          <button class="ghost" @click="correctionFor = null">取消</button>
          <button @click="submitCorrection" :disabled="!correctionContent">提交</button>
        </div>
      </div>
    </div>

    <TimelineModal v-if="timelineFor" :auth-id="timelineFor.id" :title="'授权 #' + timelineFor.id" @close="timelineFor = null" />
    <ResultModal v-if="viewResult" :result="viewResult" :can-raw="false" @close="viewResult = null" />
  </div>`,
  computed: { ROLE_NAMES() { return ROLE_NAMES; } },
};

/* ---------------- 合规人员 ---------------- */

const ComplianceView = {
  components: { TimelineModal, ResultModal },
  data: () => ({
    tab: "anomaly", anomalies: [], corrections: [], logs: [], auths: [], results: [],
    err: "", msg: "", timelineFor: null, viewResult: null,
    resolveFor: null, resolveForm: { decision: "approved", basis: "" },
    correctionFor: null, correctionForm: { decision: "resolved", note: "" },
  }),
  async mounted() { await this.reload(); },
  methods: {
    fmtTime, statusTag,
    async reload() {
      [this.anomalies, this.corrections, this.logs, this.auths, this.results] = await Promise.all([
        get("/api/anomalies"), get("/api/corrections"), get("/api/access-logs"),
        get("/api/authorizations"), get("/api/results"),
      ]);
    },
    async run(fn, okMsg) {
      this.err = ""; this.msg = "";
      try { await fn(); this.msg = okMsg; await this.reload(); }
      catch (e) { this.err = e.message; this.resolveFor = null; this.correctionFor = null; }
    },
    openResolve(c) { this.resolveFor = c; this.resolveForm = { decision: "approved", basis: "" }; },
    submitResolve() {
      const c = this.resolveFor;
      this.run(async () => {
        await post(`/api/anomalies/${c.id}/resolve`, this.resolveForm);
        this.resolveFor = null;
      }, "异常处理单已办结,依据已留痕");
    },
    openCorrection(c) { this.correctionFor = c; this.correctionForm = { decision: "resolved", note: "" }; },
    submitCorrection() {
      const c = this.correctionFor;
      this.run(async () => {
        await post(`/api/corrections/${c.id}/resolve`, this.correctionForm);
        this.correctionFor = null;
      }, "更正申请已办结");
    },
  },
  template: `
  <div>
    <div class="tabs">
      <button :class="{active: tab==='anomaly'}" @click="tab='anomaly'">异常审批</button>
      <button :class="{active: tab==='correction'}" @click="tab='correction'">更正申请</button>
      <button :class="{active: tab==='result'}" @click="tab='result'">结果调阅</button>
      <button :class="{active: tab==='logs'}" @click="tab='logs'">访问记录</button>
      <button :class="{active: tab==='auth'}" @click="tab='auth'">全部授权</button>
    </div>
    <div v-if="err" class="alert error">{{ err }}</div>
    <div v-if="msg" class="alert ok">{{ msg }}</div>

    <div v-show="tab==='anomaly'" class="card">
      <h3>异常结果处理(审批须留依据;不能批准自己提交的单据)</h3>
      <table>
        <thead><tr><th>ID</th><th>结果</th><th>提交人</th><th>说明</th><th>建议结论</th><th>状态</th><th>依据/操作</th></tr></thead>
        <tbody>
          <tr v-for="c in anomalies" :key="c.id">
            <td>{{ c.id }}</td><td>#{{ c.result_id }}</td><td>{{ c.submitted_by_name }}</td>
            <td>{{ c.description }}</td><td>{{ c.proposed_conclusion }}</td>
            <td><span class="tag" :class="statusTag(c.status)">{{ {open:'待审批',approved:'已批准',rejected:'已驳回'}[c.status] }}</span></td>
            <td>
              <button v-if="c.status === 'open'" @click="openResolve(c)">审批</button>
              <span v-else>{{ c.resolution_basis }}<br/><span class="muted">{{ c.resolved_by_name }} · {{ fmtTime(c.resolved_at) }}</span></span>
            </td>
          </tr>
          <tr v-if="!anomalies.length"><td colspan="7" class="muted">暂无异常处理单</td></tr>
        </tbody>
      </table>
    </div>

    <div v-show="tab==='correction'" class="card">
      <h3>候选人更正申请</h3>
      <table>
        <thead><tr><th>ID</th><th>结果</th><th>内容</th><th>状态</th><th>处理</th></tr></thead>
        <tbody>
          <tr v-for="c in corrections" :key="c.id">
            <td>{{ c.id }}</td><td>#{{ c.result_id }}</td><td>{{ c.content }}</td>
            <td><span class="tag" :class="statusTag(c.status)">{{ {open:'待处理',resolved:'已更正',rejected:'已驳回'}[c.status] }}</span></td>
            <td>
              <button v-if="c.status === 'open'" @click="openCorrection(c)">办结</button>
              <span v-else>{{ c.resolution_note }}<br/><span class="muted">{{ c.resolved_by_name }}</span></span>
            </td>
          </tr>
          <tr v-if="!corrections.length"><td colspan="5" class="muted">暂无</td></tr>
        </tbody>
      </table>
    </div>

    <div v-show="tab==='result'" class="card">
      <h3>结果调阅(合规可调阅原始回执,每次访问均记录)</h3>
      <table>
        <thead><tr><th>ID</th><th>项目</th><th>结论</th><th>封存</th><th>时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="r in results" :key="r.id">
            <td>{{ r.id }}</td><td>{{ r.item_label }}</td>
            <td><span class="tag" :class="r.conclusion === 'abnormal' ? 'red' : 'green'">{{ r.conclusion === 'abnormal' ? '异常' : '正常' }}</span></td>
            <td><span v-if="r.sealed" class="tag orange">已封存</span><span v-else>-</span></td>
            <td>{{ fmtTime(r.created_at) }}</td>
            <td><button class="ghost" @click="viewResult = r">查看(可调原始回执)</button></td>
          </tr>
          <tr v-if="!results.length"><td colspan="6" class="muted">暂无结果</td></tr>
        </tbody>
      </table>
    </div>

    <div v-show="tab==='logs'" class="card">
      <h3>原始回执访问记录</h3>
      <table>
        <thead><tr><th>ID</th><th>访问人</th><th>结果</th><th>动作</th><th>说明</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="l in logs" :key="l.id">
            <td>{{ l.id }}</td><td>{{ l.user }}</td><td>#{{ l.result_id }}</td>
            <td><span class="tag red">{{ l.action }}</span></td><td>{{ l.detail }}</td><td>{{ fmtTime(l.created_at) }}</td>
          </tr>
          <tr v-if="!logs.length"><td colspan="6" class="muted">暂无访问记录</td></tr>
        </tbody>
      </table>
    </div>

    <div v-show="tab==='auth'">
      <div class="card" v-for="a in auths" :key="a.id">
        <div class="row" style="justify-content:space-between">
          <h3>授权 #{{ a.id }} · {{ a.candidate_name }} · {{ a.position_title }}</h3>
          <div class="row">
            <span class="tag" :class="statusTag(a.status)">{{ a.status_label }}</span>
            <button class="ghost" @click="timelineFor = a">时间线</button>
          </div>
        </div>
        <div class="kv">
          <div><b>调查项目</b><span class="tag blue" v-for="s in a.scope" :key="s.key" style="margin-right:4px">{{ s.label }}</span>
            <b style="margin-left:16px">可见人</b>{{ a.viewers.map(v => v.name).join('、') }}
            <b style="margin-left:16px">到期</b>{{ fmtTime(a.expires_at) }}</div>
        </div>
      </div>
    </div>

    <!-- 异常审批弹窗 -->
    <div v-if="resolveFor" class="modal-mask" @click.self="resolveFor = null">
      <div class="modal">
        <h3>审批异常处理单 #{{ resolveFor.id }}</h3>
        <p class="kv"><b>说明</b>{{ resolveFor.description }}<br/><b>建议结论</b>{{ resolveFor.proposed_conclusion }}<br/><b>提交人</b>{{ resolveFor.submitted_by_name }}</p>
        <label>审批决定</label>
        <div class="checks-row">
          <label><input type="radio" value="approved" v-model="resolveForm.decision" /> 批准</label>
          <label><input type="radio" value="rejected" v-model="resolveForm.decision" /> 驳回</label>
        </div>
        <label>处理依据(必填,留痕)</label>
        <textarea rows="3" v-model="resolveForm.basis" placeholder="例如:依据《背调异常处理规范》第 X 条……"></textarea>
        <div style="text-align:right;margin-top:12px">
          <button class="ghost" @click="resolveFor = null">取消</button>
          <button @click="submitResolve" :disabled="!resolveForm.basis">提交</button>
        </div>
      </div>
    </div>

    <!-- 更正办结弹窗 -->
    <div v-if="correctionFor" class="modal-mask" @click.self="correctionFor = null">
      <div class="modal">
        <h3>办结更正申请 #{{ correctionFor.id }}</h3>
        <p class="kv"><b>内容</b>{{ correctionFor.content }}</p>
        <label>处理决定</label>
        <div class="checks-row">
          <label><input type="radio" value="resolved" v-model="correctionForm.decision" /> 确认更正</label>
          <label><input type="radio" value="rejected" v-model="correctionForm.decision" /> 驳回</label>
        </div>
        <label>处理说明(必填)</label>
        <textarea rows="3" v-model="correctionForm.note"></textarea>
        <div style="text-align:right;margin-top:12px">
          <button class="ghost" @click="correctionFor = null">取消</button>
          <button @click="submitCorrection" :disabled="!correctionForm.note">提交</button>
        </div>
      </div>
    </div>

    <TimelineModal v-if="timelineFor" :auth-id="timelineFor.id" :title="'授权 #' + timelineFor.id" @close="timelineFor = null" />
    <ResultModal v-if="viewResult" :result="viewResult" :can-raw="true" @close="viewResult = null" />
  </div>`,
};

/* ---------------- 机构模拟控制台 ---------------- */

const PAYLOAD_TEMPLATES = {
  identity: { match: true, name: "张候选", id_number: "110101199501012345", address: "北京市朝阳区望京街道 1 号" },
  education: { match: true, school: "华北理工大学", degree: "本科", major: "计算机科学", student_id: "2013010203", graduated_year: 2017 },
  employment: { match: true, company: "某科技有限公司", title: "高级工程师", referee_phone: "13866667777", reason: "个人发展" },
  certification: { match: true, cert_name: "PMP", valid: true, issued_by: "PMI" },
  criminal: { has_record: false, case_detail: "无在案记录", case_number: "-" },
  credit: { level: "良好", credit_score: "710", loan_detail: "住房贷款正常还款中", bank_card: "6222020200112233" },
};

const AgencyView = {
  data: () => ({
    token: localStorage.getItem("bgc_agency_token") || "local-agency-token",
    tasks: [], err: "", msg: "", submitFor: null,
    form: { conclusion: "normal", payloadText: "" },
  }),
  async mounted() { await this.reload(); },
  methods: {
    fmtTime,
    async reload() {
      this.err = "";
      try {
        this.tasks = await req("GET", "/api/agency/tasks", undefined, { "X-Agency-Token": this.token });
        localStorage.setItem("bgc_agency_token", this.token);
      } catch (e) { this.err = e.message; }
    },
    openSubmit(t) {
      this.submitFor = t;
      this.form = {
        conclusion: "normal",
        payloadText: JSON.stringify(PAYLOAD_TEMPLATES[t.item] || { match: true }, null, 2),
      };
    },
    async submit() {
      this.err = ""; this.msg = "";
      let payload;
      try { payload = JSON.parse(this.form.payloadText); }
      catch (e) { this.err = "回执 JSON 格式错误"; return; }
      try {
        const r = await req("POST", "/api/agency/results",
          { check_id: this.submitFor.check_id, conclusion: this.form.conclusion, payload },
          { "X-Agency-Token": this.token });
        this.msg = r.duplicate ? `已按重复件隔离存档(重复件 #${r.duplicate_id})` : `结果已回传(结果 #${r.result_id})`;
        this.submitFor = null;
        await this.reload();
      } catch (e) { this.err = e.message; }
    },
  },
  template: `
  <div>
    <div class="card">
      <h3>机构模拟控制台(本地模拟外部背调机构接口)</h3>
      <div class="row">
        <label style="margin:0">机构令牌</label>
        <input style="width:280px" v-model="token" />
        <button class="ghost" @click="reload">刷新任务</button>
      </div>
      <p class="muted" style="margin-top:6px">接口:GET /api/agency/tasks · POST /api/agency/results(请求头 X-Agency-Token)</p>
    </div>
    <div v-if="err" class="alert error">{{ err }}</div>
    <div v-if="msg" class="alert ok">{{ msg }}</div>

    <div class="card">
      <h3>待处理调查任务</h3>
      <table>
        <thead><tr><th>查询单</th><th>项目</th><th>候选人</th><th>岗位</th><th>发起时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.check_id">
            <td>#{{ t.check_id }}</td><td>{{ t.item_label }}</td><td>{{ t.candidate_name }}</td>
            <td>{{ t.position_title }}</td><td>{{ fmtTime(t.created_at) }}</td>
            <td><button @click="openSubmit(t)">回传结果</button></td>
          </tr>
          <tr v-if="!tasks.length"><td colspan="6" class="muted">暂无待处理任务</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="submitFor" class="modal-mask" @click.self="submitFor = null">
      <div class="modal">
        <h3>回传结果 —— 查询单 #{{ submitFor.check_id }}({{ submitFor.item_label }})</h3>
        <label>结论</label>
        <div class="checks-row">
          <label><input type="radio" value="normal" v-model="form.conclusion" /> 正常</label>
          <label><input type="radio" value="abnormal" v-model="form.conclusion" /> 异常</label>
        </div>
        <label>原始回执(JSON,含敏感字段;系统向企业侧默认脱敏展示)</label>
        <textarea rows="10" v-model="form.payloadText"></textarea>
        <div style="text-align:right;margin-top:12px">
          <button class="ghost" @click="submitFor = null">取消</button>
          <button @click="submit">提交回传</button>
        </div>
      </div>
    </div>
  </div>`,
};

/* ---------------- 根组件 ---------------- */

const App = {
  components: { LoginView, RecruiterView, CandidateView, ComplianceView, AgencyView },
  data: () => ({
    user: store.user,
    notifications: [], showNotify: false, agencyMode: false,
  }),
  async mounted() { if (this.user) await this.loadNotifications(); },
  methods: {
    async onLogin(r) {
      store.token = r.token; store.user = r.user;
      localStorage.setItem("bgc_token", r.token);
      localStorage.setItem("bgc_user", JSON.stringify(r.user));
      this.user = r.user;
      await this.loadNotifications();
    },
    logout() {
      store.token = ""; store.user = null;
      localStorage.removeItem("bgc_token"); localStorage.removeItem("bgc_user");
      this.user = null; this.agencyMode = false;
    },
    async loadNotifications() {
      try { this.notifications = await get("/api/notifications"); } catch (e) { /* 忽略 */ }
    },
    async openNotify() {
      this.showNotify = true;
      await this.loadNotifications();
      await post("/api/notifications/read-all");
    },
    fmtTime,
  },
  computed: {
    unread() { return this.notifications.filter((n) => !n.read).length; },
    ROLE_NAMES() { return ROLE_NAMES; },
    viewComponent() {
      if (this.agencyMode) return "AgencyView";
      return { recruiter: "RecruiterView", compliance: "ComplianceView", candidate: "CandidateView" }[this.user.role];
    },
  },
  template: `
  <div>
    <div class="topbar">
      <h1>背调授权与结果封存系统</h1>
      <div class="who" v-if="user || agencyMode">
        <button v-if="user" class="bell" @click="openNotify">🔔<span v-if="unread" class="n">{{ unread }}</span></button>
        <button class="ghost" v-if="!agencyMode" @click="agencyMode = true">机构模拟控制台</button>
        <button class="ghost" v-else @click="agencyMode = false">返回企业侧</button>
        <template v-if="user">
          <span>{{ user.name }} · {{ ROLE_NAMES[user.role] }}</span>
          <button class="ghost" @click="logout">退出</button>
        </template>
      </div>
    </div>

    <div class="container">
      <LoginView v-if="!user && !agencyMode" @login="onLogin" />
      <component v-else :is="viewComponent" :key="user ? user.id : 'agency'" />
    </div>

    <div v-if="showNotify" class="modal-mask" @click.self="showNotify = false">
      <div class="drawer">
        <h3 style="margin-bottom:12px">通知(本地模拟)</h3>
        <div v-for="n in notifications" :key="n.id" class="card" style="padding:12px">
          <div class="muted">{{ fmtTime(n.created_at) }} · {{ n.type }}</div>
          <div style="font-size:13px">{{ n.message }}</div>
        </div>
        <p v-if="!notifications.length" class="muted">暂无通知</p>
        <button class="ghost" @click="showNotify = false">关闭</button>
      </div>
    </div>
  </div>`,
};

createApp(App).mount("#app");
