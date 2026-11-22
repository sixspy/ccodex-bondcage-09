export const auditViewTemplate = `
<section class="panel">
  <h2>审计争用</h2>
  <p class="hint">写动作落审计；后到争用只记 contention，不写业务。无出金写权的出金尝试只留「越权偏航」。</p>
  <div class="grid-2">
    <div>
      <h3>审计</h3>
      <table>
        <thead><tr><th>时间</th><th>人</th><th>动作</th><th>目标</th><th>载荷</th></tr></thead>
        <tbody>
          <tr v-for="a in audits" :key="a.id">
            <td>{{ a.created_at }}</td>
            <td>{{ a.actor }}</td>
            <td>{{ a.action }}</td>
            <td>{{ a.target }}</td>
            <td><code style="font-size:11px">{{ a.payload }}</code></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div>
      <h3>持锁</h3>
      <table>
        <thead><tr><th>键</th><th>持有者</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="l in locks" :key="l.lock_key">
            <td>{{ l.lock_key }}</td>
            <td>{{ l.holder }}</td>
            <td>{{ l.acquired_at }}</td>
          </tr>
        </tbody>
      </table>
      <h3 style="margin-top:14px">争用</h3>
      <table>
        <thead><tr><th>时间</th><th>键</th><th>人</th><th>动作</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-for="c in contention" :key="c.id">
            <td>{{ c.created_at }}</td>
            <td>{{ c.lock_key }}</td>
            <td>{{ c.actor }}</td>
            <td>{{ c.action }}</td>
            <td>{{ c.detail }}</td>
          </tr>
        </tbody>
      </table>
      <h3 style="margin-top:14px">审批影子单</h3>
      <table>
        <thead><tr><th>#</th><th>类型</th><th>笼</th><th>金额</th><th>申请人</th><th>状态</th><th>正式凭证</th></tr></thead>
        <tbody>
          <tr v-for="a in approvals" :key="'au'+a.id">
            <td>{{ a.id }}</td>
            <td>{{ a.kind === 'release' ? '解笼拨付' : '罚没' }}</td>
            <td>{{ a.cage_code }}</td>
            <td>{{ a.amount == null ? '全额' : fmt(a.amount) }}</td>
            <td>{{ a.requested_by }}<small v-if="a.requested_role"> · {{ a.requested_role }}</small></td>
            <td><span class="badge" :class="a.status==='已批准'?'pass':(a.status==='已驳回'?'fail':'frozen')">{{ a.status }}</span></td>
            <td>{{ a.resulting_ref || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
