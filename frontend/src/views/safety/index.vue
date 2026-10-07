<template>
  <section class="page" data-module="safety">
    <header class="page-head">
      <div>
        <h2>安全措施管理</h2>
        <p class="page-desc">
          措施编号、措施类型、涉及设备为必填；仅本队监护人可签发/终结，外队组只读。
          当前身份：<strong>{{ session.actor?.name ?? '—' }}</strong>（{{ session.team }}·{{ session.role }}）
          <em v-if="session.actor?.readonly" class="readonly-flag">只读账号：仅可查看</em>
        </p>
      </div>
      <div class="page-actions">
        <button
          v-if="session.can('safety:create')"
          class="btn primary"
          type="button"
          @click="openCreate"
        >
          登记安全措施票
        </button>
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
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-if="nextAction(row)"
              class="link"
              type="button"
              @click="runAction(nextAction(row)!, row)"
            >
              {{ actionLabel(nextAction(row)!.action) }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">查看</button>
            <span v-if="!canModify(row)" class="muted-text">仅可查看</span>
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
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal-card">
        <h3>登记安全措施票（归属：{{ session.team }}）</h3>
        <p class="muted-text">措施编号、措施类型、涉及设备缺一项不许保存。执行人与签发人不可为同一人。</p>
        <form class="modal-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key">
            <span>{{ field.label }}<i v-if="field.required">*</i></span>
            <input v-model="createForm[field.key]" :placeholder="field.placeholder" />
          </label>
          <div class="modal-actions">
            <button class="btn" type="button" @click="showCreate = false">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情弹窗：与列表同一接口口径，监护人两处对得上 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <h3>安全措施票详情 · {{ detail['措施编号'] }}</h3>
        <dl class="detail-grid">
          <div v-for="column in detailColumns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] || '—' }}</dd>
          </div>
        </dl>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
          <button
            v-if="nextAction(detail)"
            class="btn primary"
            type="button"
            @click="runAction(nextAction(detail)!, detail)"
          >
            {{ actionLabel(nextAction(detail)!.action) }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { readError, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null | boolean>

const ENDPOINT = '/api/safety'
const columns = ["措施编号", "措施类型", "涉及设备", "归属队组", "签发人", "执行人", "监护人", "有效期至", "措施状态"]
const detailColumns = ["措施编号", "措施类型", "涉及设备", "归属队组", "措施状态", "签发人", "执行人", "监护人", "有效期至"]
const statuses = ["待签发", "已签发", "已执行", "已终结"]

// 当前状态 → 下一步动作（严格顺序流转，只暴露下一步）
const NEXT_ACTION: Record<string, { action: string; permission: string }> = {
  待签发: { action: '签发措施', permission: 'safety:issue' },
  已签发: { action: '执行措施', permission: 'safety:execute' },
  已执行: { action: '终结措施', permission: 'safety:close' },
}
const ACTION_LABEL: Record<string, string> = {
  签发措施: '签发措施',
  执行措施: '执行措施',
  终结措施: '终结措施',
}

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const stats = computed(() => {
  const count = (status: string) => rows.value.filter((row) => row['措施状态'] === status).length
  return [
    { label: '待签发票', value: count('待签发') },
    { label: '执行中票', value: count('已签发') + count('已执行') },
    { label: '已终结票', value: count('已终结') },
  ]
})

const showCreate = ref(false)
const detail = ref<Row | null>(null)

const createFields = [
  { key: '措施编号', label: '措施编号', required: true, placeholder: '如 SAFE-0101' },
  { key: '措施类型', label: '措施类型', required: true, placeholder: '如 停电、验电' },
  { key: '涉及设备', label: '涉及设备', required: true, placeholder: '如 1号逆变器' },
  { key: '执行人', label: '执行人', required: false, placeholder: '执行人姓名（须本队组）' },
  { key: '监护人', label: '监护人', required: false, placeholder: '可留空，签发时由监护人落名' },
  { key: '有效期至', label: '有效期至', required: false, placeholder: 'YYYY-MM-DD' },
]
const createForm = reactive<Record<string, string>>({
  措施编号: '',
  措施类型: '',
  涉及设备: '',
  执行人: '',
  监护人: '',
  有效期至: '',
})

function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action
}

function canModify(row: Row): boolean {
  // 只读账号不可改；外队组票不可改
  if (session.actor?.readonly) return false
  return session.team === String(row['归属队组'] ?? '')
}

function nextAction(row: Row | null): { action: string; permission: string } | null {
  if (!row || !canModify(row)) return null
  const step = NEXT_ACTION[String(row['措施状态'])]
  if (!step) return null
  return session.can(step.permission) ? step : null
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  // 带身份头由后端代理不便用 window.open，改为取数后下载文件
  void downloadExport()
}

async function downloadExport() {
  try {
    const response = await request(`${ENDPOINT}/export`)
    if (!response.ok) {
      throw new Error('导出失败')
    }
    const payload = await response.json()
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'safety-export.json'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    if (!response.ok) {
      const { message, missing } = await readError(response)
      throw new Error(missing.length ? `${message}（${missing.join('、')}）` : message)
    }
    showCreate.value = false
    Object.keys(createForm).forEach((key) => {
      createForm[key] = ''
    })
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('安全措施票详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '详情读取失败'
  }
}

async function runAction(step: { action: string }, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: step.action } }),
    })
    if (!response.ok) {
      const { message, missing } = await readError(response)
      throw new Error(missing.length ? `${message}（缺少授权：${missing.join('、')}）` : message)
    }
    const payload = await response.json()
    if (detail.value && String(detail.value.id) === String(row.id) && payload.entry) {
      detail.value = payload.entry as Row
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全措施操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('安全措施票列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全措施列表读取失败'
  }
}

onMounted(reload)

// 顶栏切换身份后，按新队组/角色重算可见动作
watch(
  () => session.actor?.id,
  () => {
    detail.value = null
    void reload()
  },
)
</script>

<style scoped>
.readonly-flag {
  color: #b42318;
  font-style: normal;
  margin-left: 8px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 20px 22px;
}
.modal-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}
.modal-form label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-form label i {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.modal-form input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  box-sizing: border-box;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
  margin: 12px 0 0;
}
.detail-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.detail-grid dd {
  margin: 2px 0 0;
}
</style>
