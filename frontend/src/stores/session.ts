import { defineStore } from 'pinia'

/** 与后端 app/identity.py 备案台账保持一致的演示账号。 */
export interface OperatorAccount {
  name: string
  team: string
  role: '监护人' | '执行人' | '只读'
  note: string
}

export const OPERATOR_ACCOUNTS: OperatorAccount[] = [
  { name: '张护', team: '运维一队', role: '监护人', note: '一队监护人，可签发/终结本队票' },
  { name: '李行', team: '运维一队', role: '执行人', note: '一队执行人，只能执行指派给他的票' },
  { name: '王护', team: '运维二队', role: '监护人', note: '二队监护人，对一队票只读' },
  { name: '赵行', team: '运维二队', role: '执行人', note: '二队执行人' },
  { name: '陈兼', team: '运维一队', role: '监护人', note: '先后在二队、一队备案，按最近备案归一队' },
  { name: '周看', team: '运维一队', role: '只读', note: '只读账号，能看不能改' },
]

const STORAGE_KEY = 'safety.operator'

export const useSessionStore = defineStore('session', {
  state: () => {
    const savedName = localStorage.getItem(STORAGE_KEY) ?? '张护'
    const account = OPERATOR_ACCOUNTS.find((item) => item.name === savedName) ?? OPERATOR_ACCOUNTS[0]
    return {
      operator: account.name,
      team: account.team,
      role: account.role,
      shiftLabel: '白班 08:00-20:00',
      scope: '光伏电站运维管理平台',
    }
  },
  getters: {
    canOperate: (state) => state.role !== '只读',
    isGuardian: (state) => state.role === '监护人',
    isReadonly: (state) => state.role === '只读',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setOperator(name: string) {
      const account = OPERATOR_ACCOUNTS.find((item) => item.name === name)
      if (!account) {
        return
      }
      this.operator = account.name
      this.team = account.team
      this.role = account.role
      localStorage.setItem(STORAGE_KEY, account.name)
    },
  },
})
