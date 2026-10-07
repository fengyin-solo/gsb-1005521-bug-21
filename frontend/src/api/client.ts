/** 统一请求封装：拼后端地址、带操作人身份、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const OPERATOR_STORAGE_KEY = 'ops.operatorId'

function buildHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  // 后端按最近一次备案判定归属队组与角色；未登录时默认运维一队监护人，便于联调
  const operatorId = localStorage.getItem(OPERATOR_STORAGE_KEY) || 'P101'
  headers.set('X-Operator-Id', operatorId)
  return headers
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: buildHeaders(init),
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

/** 读取后端结构化错误里的可读说明与缺失授权项。 */
export async function readError(response: Response): Promise<{ message: string; missing: string[] }> {
  try {
    const detail = await response.json()
    const body = detail?.detail ?? detail
    if (body && typeof body === 'object') {
      const labels = body.missing_permission_labels ?? []
      const fields = body.missing_fields ?? []
      const missing = [...labels, ...fields.map((field: string) => `缺少字段：${field}`)]
      return { message: body.message ?? '操作未被接受', missing }
    }
    return { message: typeof body === 'string' ? body : '操作未被接受', missing: [] }
  } catch {
    return { message: `接口返回 ${response.status}，操作未生效`, missing: [] }
  }
}
