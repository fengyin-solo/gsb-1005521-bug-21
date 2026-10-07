/** 统一请求封装：拼后端地址、带上经办人身份、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export function operatorHeader(): Record<string, string> {
  // HTTP 头只接受 Latin-1，中文姓名按 UTF-8 百分号编码后发送（后端解码）。
  const session = useSessionStore()
  return { 'X-Operator': encodeURIComponent(session.operator) }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json', ...operatorHeader(), ...(init?.headers ?? {}) },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

/** 读取后端结构化错误：detail 可能是 {reason, required_permission,...} 对象，也可能是字符串。 */
export async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    const detail = payload?.detail
    if (detail && typeof detail === 'object') {
      const required = detail.required_permission ? `（缺少授权项：${detail.required_permission}）` : ''
      return `${detail.reason ?? fallback}${required}`
    }
    if (typeof detail === 'string' && detail) {
      return detail
    }
  } catch {
    /* 响应体不是 JSON 时用兜底文案 */
  }
  return fallback
}
