import { defineStore } from 'pinia'

export interface Actor {
  id: string
  name: string
  team: string
  role: string
  permissions: string[]
  permissionLabels: string[]
  readonly: boolean
}

const STORAGE_KEY = 'ops.operatorId'

export const useSessionStore = defineStore('session', {
  state: () => ({
    operatorId: localStorage.getItem(STORAGE_KEY) || 'P101',
    shiftLabel: '白班 08:00-20:00',
    scope: '光伏电站运维管理平台',
    actor: null as Actor | null,
    roster: [] as Actor[],
  }),
  getters: {
    operator: (state) => state.actor?.name ?? state.operatorId,
    team: (state) => state.actor?.team ?? '未备案',
    role: (state) => state.actor?.role ?? '未知',
    canOperate: (state) => Boolean(state.actor && !state.actor.readonly),
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setOperator(id: string) {
      this.operatorId = id
      localStorage.setItem(STORAGE_KEY, id)
      void this.fetchMe()
    },
    can(permission: string): boolean {
      return Boolean(this.actor?.permissions.includes(permission))
    },
    async hydrate() {
      await this.fetchRoster()
      await this.fetchMe()
    },
    async fetchMe() {
      try {
        const response = await fetch(`/api/identity/me`, {
          headers: { 'X-Operator-Id': this.operatorId },
        })
        if (response.ok) {
          this.actor = (await response.json()) as Actor
        } else {
          this.actor = null
        }
      } catch {
        this.actor = null
      }
    },
    async fetchRoster() {
      try {
        const response = await fetch('/api/identity/roster')
        if (response.ok) {
          const payload = await response.json()
          this.roster = (payload.items ?? []) as Actor[]
        }
      } catch {
        this.roster = []
      }
    },
  },
})
