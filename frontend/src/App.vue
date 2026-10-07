<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">光伏电站运维管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向光伏组件、逆变器、汇流箱、变压器、储能与升压站运行监视的集中式电站运维后台。</span>
        <span class="head-user">
          当前值班：
          <select
            class="operator-select"
            :value="store.operatorId"
            @change="onChangeOperator(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="person in store.roster" :key="person.id" :value="person.id">
              {{ person.name }}｜{{ person.team }}｜{{ person.role }}
            </option>
          </select>
          <em class="head-meta">{{ store.team }} · {{ store.role }}</em>
        </span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "光伏阵列", path: "/pv_array" }, { label: "逆变器监视", path: "/inverter" }, { label: "汇流箱检测", path: "/combiner_box" }, { label: "变压器监视", path: "/transformer" }, { label: "储能电池组", path: "/energy_storage" }, { label: "升压站监视", path: "/boosting_station" }, { label: "关口计量", path: "/meter" }, { label: "环境监测站", path: "/environment" }, { label: "组件清洗", path: "/cleaning" }, { label: "巡视检查", path: "/patrol" }, { label: "缺陷管理", path: "/defect" }, { label: "检修计划", path: "/maintenance" }, { label: "备品备件", path: "/spare_parts" }, { label: "告警事件", path: "/alarm" }, { label: "调度指令", path: "/dispatch" }, { label: "安全措施", path: "/safety" }, { label: "运维合同", path: "/contract" }, { label: "运行月报", path: "/report" }]

function onChangeOperator(id: string) {
  store.setOperator(id)
}

onMounted(() => {
  void store.hydrate()
})
</script>

<style scoped>
.operator-select {
  margin: 0 6px;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
}
.head-meta {
  font-style: normal;
  color: var(--muted);
  font-size: 12px;
  margin-left: 6px;
}
</style>
