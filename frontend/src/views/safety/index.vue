<template>
  <section class="page" data-module="safety">
    <header class="page-head">
      <div>
        <h2>安全措施管理</h2>
        <p class="page-desc">
          维护安全措施票，状态按 待签发 → 已签发 → 已执行 → 已终结 顺序流转；
          当前经办人 {{ store.operator }}（{{ store.team }}·{{ store.role }}），外队组票据仅可查看。
        </p>
      </div>
      <div class="page-actions">
        <button v-if="!store.isReadonly" class="btn primary" type="button" @click="openCreate">登记安全措施票</button>
        <button class="btn" type="button" @click="exportRows">导出安全措施清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>措施编号</span>
        <input v-model="keyword" placeholder="按措施编号检索" />
      </label>
      <label class="filter-item">
        <span>措施状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '措施编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-if="row['可执行动作']"
              class="link"
              type="button"
              @click="runAction(String(row['可执行动作']), row)"
            >
              {{ row['可执行动作'] }}
            </button>
            <span v-else class="muted-text" :title="String(row['缺少授权项'] ?? '')">
              {{ row['不可操作原因'] || '已终结' }}
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无安全措施数据，可先登记安全措施票</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条安全措施记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记弹窗 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <h3>登记安全措施票</h3>
        <p class="modal-hint">归属队组按经办人最近一次备案自动记为「{{ store.team }}」；标 * 项缺一不可。</p>
        <form class="modal-form" @submit.prevent="submitCreate">
          <label v-for="field in formFields" :key="field.name" class="modal-field">
            <span>{{ field.label }}<i v-if="field.required">*</i></span>
            <input v-model="form[field.name]" :placeholder="field.placeholder" />
          </label>
          <p class="modal-hint">规则：执行人与签发人互斥；监护人须为本队组成员。</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="creating = false">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情弹窗：直接展示 GET 详情，和列表同源，监护人两处必然一致 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>安全措施票 {{ detail['措施编号'] }}</h3>
        <table class="detail-table">
          <tbody>
            <tr v-for="field in detailFields" :key="field">
              <th>{{ field }}</th>
              <td>{{ detail[field] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <h4>操作记录</h4>
        <ul v-if="opLogs.length" class="op-log">
          <li v-for="(log, index) in opLogs" :key="index">
            {{ log.at }} · {{ log.operator }} · {{ log.action }}<template v-if="log['结论']"> · 结论：{{ log['结论'] }}</template>
          </li>
        </ul>
        <p v-else class="muted-text">暂无操作记录</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { readError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>
interface OpLog {
  action: string
  operator: string
  at: string
  结论?: string
}

const store = useSessionStore()

const ENDPOINT = '/api/safety'
const columns = ['措施编号', '措施类型', '涉及设备', '归属队组', '签发人', '执行人', '监护人', '有效期至', '措施状态']
const statuses = ['待签发', '已签发', '已执行', '已终结']

const formFields = [
  { name: '措施编号', label: '措施编号', required: true, placeholder: '如 SAFE-0101' },
  { name: '措施类型', label: '措施类型', required: true, placeholder: '如 停电检修' },
  { name: '涉及设备', label: '涉及设备', required: true, placeholder: '如 1号逆变器' },
  { name: '执行人', label: '执行人', required: false, placeholder: '本队组执行人姓名' },
  { name: '监护人', label: '监护人', required: false, placeholder: '本队组监护人姓名' },
  { name: '有效期至', label: '有效期至', required: false, placeholder: 'YYYY-MM-DD' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const creating = ref(false)
const form = reactive<Record<string, string>>({})
const detail = ref<Row | null>(null)

const opLogs = computed<OpLog[]>(() => {
  const raw = detail.value?.['操作记录']
  return Array.isArray(raw) ? (raw as OpLog[]) : []
})

const stats = computed(() => [
  { label: '待签发票', value: rows.value.filter((r) => r['措施状态'] === '待签发').length },
  { label: '已签发票', value: rows.value.filter((r) => r['措施状态'] === '已签发').length },
  { label: '已执行票', value: rows.value.filter((r) => r['措施状态'] === '已执行').length },
  { label: '已终结票', value: rows.value.filter((r) => r['措施状态'] === '已终结').length },
])

const detailFields = [...columns]

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  // 导出链接带不上自定义头，用 query 把经办人带给后端认人。
  const query = new URLSearchParams({ operator: store.operator }).toString()
  window.open(`${ENDPOINT}/export?${query}`, '_blank')
}

function openCreate() {
  Object.keys(form).forEach((key) => delete form[key])
  errorMessage.value = ''
  creating.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  const values: Record<string, string> = {}
  formFields.forEach((field) => {
    values[field.name] = (form[field.name] ?? '').trim()
  })
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error(await readError(response, '安全措施票登记失败'))
    }
    const payload = await response.json()
    creating.value = false
    errorMessage.value = payload.message ?? '安全措施票已登记'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全措施票登记失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error(await readError(response, '措施票详情读取失败'))
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '措施票详情读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const conclusion =
    action === '签发措施' ? window.prompt('请填写签发结论（落到检修计划待办）', '同意签发') : null
  if (action === '签发措施' && conclusion === null) {
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, conclusion } }),
    })
    if (!response.ok) {
      // 越权（403）、跳状态（400）等都由后端给出结构化原因，直接展示给经办人。
      throw new Error(await readError(response, '安全措施动作未生效'))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全措施操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error(await readError(response, '安全措施票列表读取失败'))
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全措施列表读取失败'
  }
}

onMounted(reload)
</script>
