export const releaseViewTemplate = `
<section class="panel">
  <h2>解笼拨付</h2>
  <p class="hint">仅核验通过的笼可拨付。默认把可用额全额拨给受益人，也可部分解笼。账户余额与冻结同步扣减。</p>
  <p class="hint auth-hint" v-if="shadowNote">{{ shadowNote }}</p>
  <div class="grid-2">
    <div>
      <div class="form-row">
        <div>
          <label>通过态笼</label>
          <select v-model.number="releaseForm.cage_id">
            <option :value="0">请选择</option>
            <option v-for="c in passCages" :key="c.id" :value="c.id">
              {{ c.cage_code }} · 可用 {{ fmt(c.available) }}
            </option>
          </select>
        </div>
        <div>
          <label>金额（空=全额）</label>
          <input type="number" v-model.number="releaseForm.amount" min="0" step="1000" placeholder="全额"/>
        </div>
        <div>
          <label>收款方（空=受益人）</label>
          <input v-model="releaseForm.payee"/>
        </div>
      </div>
      <div class="actions">
        <button v-if="canDirectWithdraw" class="ok" @click="doRelease">解笼拨付</button>
        <button v-else class="secondary" @click="requestDecision('release')">提交审批影子单</button>
      </div>
      <div class="approval-box" v-if="pendingReleases.length">
        <h3>待审批影子单</h3>
        <table>
          <thead><tr><th>#</th><th>类型</th><th>笼</th><th>金额</th><th>申请人</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="a in pendingReleases" :key="'ra'+a.id">
              <td>{{ a.id }}</td>
              <td>{{ a.kind === 'release' ? '解笼拨付' : '罚没' }}</td>
              <td>{{ a.cage_code }}</td>
              <td>{{ a.amount == null ? '全额' : fmt(a.amount) }}</td>
              <td>{{ a.requested_by }}<small v-if="a.requested_role"> · {{ a.requested_role }}</small></td>
              <td v-if="isAdmin">
                <button class="ok" @click="decideApproval(a,'approve')">批准</button>
                <button class="danger" @click="decideApproval(a,'reject')">驳回</button>
              </td>
              <td v-else><span class="badge frozen">待管理员</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div>
      <table>
        <thead>
          <tr><th>凭证</th><th>笼</th><th>金额</th><th>收款方</th><th>笼代</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in releases" :key="r.id">
            <td>{{ r.release_ref }}</td>
            <td>{{ r.cage_code }}</td>
            <td>{{ fmt(r.amount) }}</td>
            <td>{{ r.payee }}</td>
            <td>{{ r.cage_generation }}</td>
            <td>{{ r.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
