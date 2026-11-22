export const forfeitViewTemplate = `
<section class="panel">
  <h2>罚没册</h2>
  <p class="hint">仅核验违约的笼可罚没。资金离开当事人账户，进入罚没册，不再回到可用余额。</p>
  <p class="hint auth-hint" v-if="shadowNote">{{ shadowNote }}</p>
  <div class="grid-2">
    <div>
      <div class="form-row">
        <div>
          <label>违约态笼</label>
          <select v-model.number="forfeitForm.cage_id">
            <option :value="0">请选择</option>
            <option v-for="c in failCages" :key="c.id" :value="c.id">
              {{ c.cage_code }} · 可用 {{ fmt(c.available) }}
            </option>
          </select>
        </div>
        <div>
          <label>金额（空=全额）</label>
          <input type="number" v-model.number="forfeitForm.amount" min="0" step="1000" placeholder="全额"/>
        </div>
        <div style="grid-column:1/-1">
          <label>原因</label>
          <input v-model="forfeitForm.reason"/>
        </div>
      </div>
      <div class="actions">
        <button v-if="canDirectWithdraw" class="danger" @click="doForfeit">执行罚没</button>
        <button v-else class="secondary" @click="requestDecision('forfeit')">提交审批影子单</button>
      </div>
      <div class="approval-box" v-if="pendingForfeits.length">
        <h3>待审批影子单</h3>
        <table>
          <thead><tr><th>#</th><th>类型</th><th>笼</th><th>金额</th><th>申请人</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="a in pendingForfeits" :key="'fa'+a.id">
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
          <tr><th>凭证</th><th>笼</th><th>金额</th><th>原因</th><th>笼代</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="f in forfeits" :key="f.id">
            <td>{{ f.forfeit_ref }}</td>
            <td>{{ f.cage_code }}</td>
            <td>{{ fmt(f.amount) }}</td>
            <td>{{ f.reason }}</td>
            <td>{{ f.cage_generation }}</td>
            <td>{{ f.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
