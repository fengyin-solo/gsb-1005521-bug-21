<template>
  <section class="page" data-module="maintenance">
    <header class="page-head">
      <div>
        <h2>检修计划管理</h2>
        <p class="page-desc">维护检修计划，围绕计划编号、检修设备、检修类别、计划开始做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修计划</button>
        <button class="btn" type="button" @click="exportRows">导出检修计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="todo-block">
      <header class="todo-head">
        <h3>安全措施签发待办</h3>
        <span class="muted-text">安全措施票签发后，签发结论自动落到这里（仅显示 {{ store.team }} 的待办）</span>
        <button class="btn ghost" type="button" @click="reloadTodos">刷新待办</button>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>措施票编号</th>
            <th>涉及设备</th>
            <th>关联检修计划</th>
            <th>签发结论</th>
            <th>签发人</th>
            <th>登记日期</th>
            <th>待办状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="todo in todos" :key="String(todo.id)">
            <td>{{ todo['来源票编号'] ?? '—' }}</td>
            <td>{{ todo['涉及设备'] ?? '—' }}</td>
            <td>{{ todo['关联计划编号'] ?? '未匹配到计划' }}</td>
            <td>{{ todo['签发结论'] ?? '—' }}</td>
            <td>{{ todo['签发人'] ?? '—' }}</td>
            <td>{{ todo['登记日期'] ?? '—' }}</td>
            <td>{{ todo['status'] ?? '—' }}</td>
          </tr>
          <tr v-if="!todos.length">
            <td colspan="7" class="empty-state">暂无待处理的安全措施签发待办</td>
          </tr>
        </tbody>
      </table>
      <p v-if="todoError" class="error-text">{{ todoError }}</p>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无检修计划数据，可先登记检修计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>

const store = useSessionStore()

const ENDPOINT = '/api/maintenance'
const columns = ["计划编号", "检修设备", "检修类别", "计划开始", "计划结束", "责任人", "安全措施", "计划状态"]
const actions = ["提交审批", "开始执行", "确认完工"]
const statuses = ["待审批", "已批复", "执行中", "已完工"]
const stats = [{"label": "待审批计划", "value": 0}, {"label": "执行中计划", "value": 0}, {"label": "本月完工数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const todos = ref<Row[]>([])
const todoError = ref('')

async function reloadTodos() {
  todoError.value = ''
  try {
    const response = await request('/api/maintenance/todos?status=待办')
    if (!response.ok) {
      throw new Error('安全措施签发待办读取失败')
    }
    const payload = await response.json()
    todos.value = payload.items ?? []
  } catch (error) {
    todoError.value = error instanceof Error ? error.message : '安全措施签发待办读取失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检修计划登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('检修计划动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('检修计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修计划列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadTodos()
})
</script>
