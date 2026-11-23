/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 同期群运营圈选：实际入群成员行，逐行标注回访状态与采用的回访批次。 */
export type CohortMemberRow = {
  用户ID: string
  群组编号: string
  入群渠道: string
  平台: string
  年龄层: string
  价值等级: string
  是否已回访?: boolean
  回访批次: string
}

export type CohortActualResult = {
  群组编号: string
  观察日: number
  渠道: string
  回访批次: string
  成员基数: number
  已回访人数: number
  未回访人数: number
  成员行: CohortMemberRow[]
}

export type CohortAbsentResult = {
  群组编号: string
  观察日: number
  渠道: string
  回访批次: string
  已回访人数: number
  批次已回访人数: number
  候选人数: number
  候选行: CohortMemberRow[]
}

export type CohortClaim = {
  领取编号: string
  群组编号: string
  观察日: number
  渠道: string
  回访批次: string
  已回访人数: number
  候选用户: string[]
  状态: string
  名单编号: string | null
  领取时间: string
}

export type CohortOplist = {
  名单编号: string
  来源领取编号: string
  群组编号: string
  观察日: number
  渠道: string
  回访批次: string
  圈选条件: Record<string, string>
  候选用户: string[]
  名单成员: string[]
  成员数: number
  状态: string
  生成时间: string
}

export type CohortOplistSource = CohortOplist & {
  批次已回访人数: number
  回算候选: string[]
  回算成员: string[]
  回算一致: boolean
}

export type CohortOpsReply<T> = {
  ok: boolean
  message: string
  entry: T | null
}
