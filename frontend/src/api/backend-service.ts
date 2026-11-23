import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  CohortAbsentResult,
  CohortActualResult,
  CohortClaim,
  CohortOpsReply,
  CohortOplist,
  CohortOplistSource,
  EntryRow,
  OverviewResult,
  PageResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ============================================================
// 同期群运营圈选：未回访回查、范围领取、名单生成与来源回算
// ============================================================

const COHORT_OPS_BASE = '/api/cohort_analysis/ops'

function opsQuery(cohortId: string, day: number, channel: string): string {
  const params = new URLSearchParams({ 群组编号: cohortId, 观察日: String(day) })
  if (channel.trim()) params.set('渠道', channel.trim())
  return params.toString()
}

async function opsGet<T>(path: string): Promise<T> {
  const response = await request(`${COHORT_OPS_BASE}${path}`)
  if (!response.ok) throw new Error('同期群运营数据读取失败')
  return (await response.json()) as T
}

async function opsPost<T>(path: string, body: unknown): Promise<CohortOpsReply<T>> {
  const response = await request(`${COHORT_OPS_BASE}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()) as CohortOpsReply<T>
}

/** 按观察日和渠道查询实际入群成员。 */
export function fetchCohortActualMembers(
  cohortId: string,
  day: number,
  channel: string,
): Promise<CohortActualResult> {
  return opsGet<CohortActualResult>(`/members?${opsQuery(cohortId, day, channel)}`)
}

/** 回查未回访成员清单：候选行与已回访人数都带回访批次。 */
export function fetchCohortAbsentMembers(
  cohortId: string,
  day: number,
  channel: string,
): Promise<CohortAbsentResult> {
  return opsGet<CohortAbsentResult>(`/absent?${opsQuery(cohortId, day, channel)}`)
}

/** 领取未回访范围：以当前回访批次为领取边界。 */
export function claimCohortScope(
  cohortId: string,
  day: number,
  channel: string,
): Promise<CohortOpsReply<CohortClaim>> {
  return opsPost<CohortClaim>('/claims', { 群组编号: cohortId, 观察日: day, 渠道: channel })
}

/** 在领取范围内按用户属性圈选，组装运营名单（每轮领取限一份）。 */
export function generateCohortOplist(
  claimId: string,
  conditions: Record<string, string>,
): Promise<CohortOpsReply<CohortOplist>> {
  return opsPost<CohortOplist>(`/claims/${claimId}/oplists`, { 圈选条件: conditions })
}

/** 补送迟到回访（待确认）。 */
export function reportCohortRevisits(
  cohortId: string,
  day: number,
  userIds: string[],
): Promise<CohortOpsReply<{ records: unknown[] }>> {
  return opsPost('/revisits', { 群组编号: cohortId, 观察日: day, 用户IDs: userIds })
}

/** 确认待确认回访：回访批次推进。 */
export function confirmCohortRevisits(
  cohortId: string,
  day: number,
): Promise<CohortOpsReply<{ 回访批次: string; 已回访人数: number }>> {
  return opsPost('/revisits/confirm', { 群组编号: cohortId, 观察日: day })
}

/** 运营名单列表。 */
export async function fetchCohortOplists(): Promise<CohortOplist[]> {
  const payload = await opsGet<PageResult & { items: CohortOplist[] }>('/oplists')
  return payload.items
}

/** 回查名单来源：按实际采用的回访批次与渠道回算。 */
export function fetchCohortOplistSource(listId: string): Promise<CohortOplistSource> {
  return opsGet<CohortOplistSource>(`/oplists/${listId}/source`)
}
