<template>
  <section class="ops-panel" data-testid="cohort-ops-panel">
    <header class="page-head">
      <div>
        <h3>未回访成员回查与运营圈选</h3>
        <p class="page-desc">
          从实际入群成员按观察日和渠道回查缺席者，领取未回访范围后按用户属性圈选生成运营名单；
          已回访人数与候选行都标出采用的回访批次，名单可按批次和渠道回算来源。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="queryAbsent">
      <label class="filter-item">
        <span>群组编号</span>
        <input v-model="cohortId" data-testid="ops-cohort-id" placeholder="COHO-0001" />
      </label>
      <label class="filter-item">
        <span>观察日</span>
        <input v-model.number="observationDay" data-testid="ops-day" type="number" min="1" />
      </label>
      <label class="filter-item">
        <span>渠道</span>
        <input v-model="channel" data-testid="ops-channel" placeholder="活动渠道" />
      </label>
      <button class="btn" data-testid="ops-query-members" type="button" @click="queryMembers">
        查询实际成员
      </button>
      <button class="btn primary" data-testid="ops-query-absent" type="submit">
        回查未回访成员
      </button>
    </form>

    <div v-if="actualResult" class="ops-block" data-testid="ops-actual-result">
      <p class="status-legend">
        <span class="legend-item">回访批次：{{ actualResult.回访批次 || '—' }}</span>
        <span class="legend-item">成员基数：{{ actualResult.成员基数 }}</span>
        <span class="legend-item">已回访人数：{{ actualResult.已回访人数 }}</span>
        <span class="legend-item">未回访人数：{{ actualResult.未回访人数 }}</span>
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>用户ID</th><th>入群渠道</th><th>平台</th><th>年龄层</th>
            <th>价值等级</th><th>是否已回访</th><th>回访批次</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in actualResult.成员行" :key="row.用户ID">
            <td>{{ row.用户ID }}</td>
            <td>{{ row.入群渠道 }}</td>
            <td>{{ row.平台 }}</td>
            <td>{{ row.年龄层 }}</td>
            <td>{{ row.价值等级 }}</td>
            <td>{{ row.是否已回访 ? '已回访' : '未回访' }}</td>
            <td>{{ row.回访批次 || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="absentResult" class="ops-block" data-testid="ops-absent-result">
      <p class="status-legend">
        <span class="legend-item">采用回访批次：{{ absentResult.回访批次 || '—' }}</span>
        <span class="legend-item">已回访人数：{{ absentResult.已回访人数 }}</span>
        <span class="legend-item">未回访候选：{{ absentResult.候选人数 }} 人</span>
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>用户ID</th><th>入群渠道</th><th>平台</th><th>年龄层</th>
            <th>价值等级</th><th>回访批次</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in absentResult.候选行" :key="row.用户ID" :data-testid="`absent-${row.用户ID}`">
            <td>{{ row.用户ID }}</td>
            <td>{{ row.入群渠道 }}</td>
            <td>{{ row.平台 }}</td>
            <td>{{ row.年龄层 }}</td>
            <td>{{ row.价值等级 }}</td>
            <td>{{ row.回访批次 || '—' }}</td>
          </tr>
          <tr v-if="!absentResult.候选行.length">
            <td colspan="6" class="empty-state">该观察日与渠道下没有未回访成员</td>
          </tr>
        </tbody>
      </table>
      <div class="page-actions">
        <button class="btn primary" data-testid="ops-claim" type="button" @click="claimScope">
          领取未回访范围
        </button>
      </div>
    </div>

    <div v-if="claim" class="ops-block" data-testid="ops-claim-result">
      <p class="status-legend">
        <span class="legend-item">领取编号：{{ claim.领取编号 }}</span>
        <span class="legend-item">领取边界批次：{{ claim.回访批次 }}</span>
        <span class="legend-item">候选用户：{{ claim.候选用户.join('、') || '—' }}</span>
        <span class="legend-item">状态：{{ claim.状态 }}</span>
      </p>
      <form class="filter-bar" @submit.prevent="generateList">
        <label v-for="field in attributeFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="conditions[field]" :data-testid="`ops-cond-${field}`" :placeholder="`按${field}圈选，可留空`" />
        </label>
        <button class="btn primary" data-testid="ops-generate" type="submit" :disabled="claim.状态 === '已生成名单'">
          生成运营名单
        </button>
      </form>
    </div>

    <div class="ops-block">
      <form class="filter-bar" @submit.prevent="reportLate">
        <label class="filter-item">
          <span>迟到回访用户（逗号分隔）</span>
          <input v-model="lateUserIds" data-testid="ops-late-users" placeholder="如：B" />
        </label>
        <button class="btn" data-testid="ops-report" type="submit">补送回访</button>
        <button class="btn" data-testid="ops-confirm" type="button" @click="confirmLate">
          确认回访
        </button>
      </form>
    </div>

    <div class="ops-block" data-testid="ops-oplists">
      <p class="status-legend">
        <span class="legend-item">运营名单：{{ oplists.length }} 份</span>
        <button class="btn ghost" data-testid="ops-refresh-lists" type="button" @click="loadOplists">
          刷新名单
        </button>
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>名单编号</th><th>来源领取</th><th>观察日</th><th>渠道</th>
            <th>回访批次</th><th>圈选条件</th><th>名单成员</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="oplist in oplists" :key="oplist.名单编号" :data-testid="`oplist-${oplist.名单编号}`">
            <td>{{ oplist.名单编号 }}</td>
            <td>{{ oplist.来源领取编号 }}</td>
            <td>第 {{ oplist.观察日 }} 日</td>
            <td>{{ oplist.渠道 }}</td>
            <td>{{ oplist.回访批次 }}</td>
            <td>{{ formatConditions(oplist.圈选条件) }}</td>
            <td>{{ oplist.名单成员.join('、') || '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`source-${oplist.名单编号}`" @click="showSource(oplist.名单编号)">
                来源回查
              </button>
            </td>
          </tr>
          <tr v-if="!oplists.length">
            <td colspan="8" class="empty-state">暂无运营名单，请先领取未回访范围并生成</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="source" class="ops-block" data-testid="ops-source-result">
      <p class="status-legend">
        <span class="legend-item">名单：{{ source.名单编号 }}</span>
        <span class="legend-item">来源领取：{{ source.来源领取编号 }}</span>
        <span class="legend-item">采用批次：{{ source.回访批次 }}</span>
        <span class="legend-item">批次已回访人数：{{ source.批次已回访人数 }}</span>
        <span class="legend-item">回算候选：{{ source.回算候选.join('、') || '—' }}</span>
        <span class="legend-item">回算成员：{{ source.回算成员.join('、') || '—' }}</span>
        <span class="legend-item">回算一致：{{ source.回算一致 ? '是' : '否' }}</span>
      </p>
    </div>

    <p v-if="message" class="ops-message" data-testid="ops-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="ops-error">{{ errorMessage }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  claimCohortScope,
  confirmCohortRevisits,
  fetchCohortAbsentMembers,
  fetchCohortActualMembers,
  fetchCohortOplistSource,
  fetchCohortOplists,
  generateCohortOplist,
  reportCohortRevisits,
} from '@/api/backend-service'
import type {
  CohortAbsentResult,
  CohortActualResult,
  CohortClaim,
  CohortOplist,
  CohortOplistSource,
} from '@/data/types'

const attributeFields = ['平台', '年龄层', '价值等级']

const cohortId = ref('COHO-0001')
const observationDay = ref(2)
const channel = ref('活动渠道')
const conditions = ref<Record<string, string>>({ 平台: '', 年龄层: '', 价值等级: '' })
const lateUserIds = ref('')

const actualResult = ref<CohortActualResult | null>(null)
const absentResult = ref<CohortAbsentResult | null>(null)
const claim = ref<CohortClaim | null>(null)
const oplists = ref<CohortOplist[]>([])
const source = ref<CohortOplistSource | null>(null)
const message = ref('')
const errorMessage = ref('')

function formatConditions(value: Record<string, string>): string {
  const parts = Object.entries(value).map(([field, expected]) => `${field}=${expected}`)
  return parts.length ? parts.join('，') : '全部候选'
}

function resetError() {
  errorMessage.value = ''
}

async function guard(task: () => Promise<void>) {
  resetError()
  try {
    await task()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function queryMembers() {
  await guard(async () => {
    actualResult.value = await fetchCohortActualMembers(
      cohortId.value, observationDay.value, channel.value)
  })
}

async function queryAbsent() {
  await guard(async () => {
    absentResult.value = await fetchCohortAbsentMembers(
      cohortId.value, observationDay.value, channel.value)
    message.value = ''
  })
}

async function claimScope() {
  await guard(async () => {
    const result = await claimCohortScope(cohortId.value, observationDay.value, channel.value)
    if (!result.ok || !result.entry) throw new Error(result.message)
    claim.value = result.entry
    message.value = result.message
  })
}

async function generateList() {
  if (!claim.value) return
  await guard(async () => {
    const result = await generateCohortOplist(claim.value!.领取编号, conditions.value)
    message.value = result.message
    if (!result.ok) return
    claim.value = { ...claim.value!, 状态: '已生成名单', 名单编号: result.entry?.名单编号 ?? null }
    await loadOplists()
  })
}

async function reportLate() {
  await guard(async () => {
    const userIds = lateUserIds.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean)
    const result = await reportCohortRevisits(cohortId.value, observationDay.value, userIds)
    message.value = result.message
    if (!result.ok) throw new Error(result.message)
  })
}

async function confirmLate() {
  await guard(async () => {
    const result = await confirmCohortRevisits(cohortId.value, observationDay.value)
    message.value = result.message
    if (!result.ok) throw new Error(result.message)
  })
}

async function loadOplists() {
  await guard(async () => {
    oplists.value = await fetchCohortOplists()
  })
}

async function showSource(listId: string) {
  await guard(async () => {
    source.value = await fetchCohortOplistSource(listId)
  })
}

onMounted(loadOplists)
</script>

<style scoped>
.ops-panel {
  margin-top: 16px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
.ops-block {
  margin-bottom: 12px;
}
.ops-message {
  color: var(--brand);
  font-size: 13px;
}
</style>
