<template>
  <section class="page" data-module="disease">
    <header class="page-head">
      <div>
        <h2>病害登记管理</h2>
        <p class="page-desc">维护病害记录，围绕病害编号、所在设施、病害类型、病害位置做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记病害记录</button>
        <button class="btn" type="button" @click="openBatch">批量定级</button>
        <button class="btn" type="button" @click="exportRows">导出病害登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="batchVisible" class="panel">
      <h3 class="panel-title">批量定级（已选 {{ selectedIds.length }} 条病害）</h3>
      <form class="filter-bar" @submit.prevent="submitBatch">
        <label class="filter-item">
          <span>批次号</span>
          <input v-model="batchNo" placeholder="同一批次号重复提交不会重复定级" />
        </label>
        <label class="filter-item">
          <span>严重等级</span>
          <select v-model="gradeLevel">
            <option value="">请选择</option>
            <option v-for="level in levels" :key="level" :value="level">{{ level }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>定级结论</span>
          <input v-model="gradeConclusion" placeholder="填写本次验收的统一定级结论" />
        </label>
        <button class="btn primary" type="submit">提交批量定级</button>
        <button class="btn ghost" type="button" @click="batchVisible = false">取消</button>
      </form>
    </section>

    <section v-if="receipts.length" class="panel">
      <h3 class="panel-title">
        批量定级回执<template v-if="batchMessage">：{{ batchMessage }}</template>
      </h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>病害编号</th>
            <th>处理结果</th>
            <th>不合格项</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="receipt in receipts" :key="`${receipt.entry_id}-${receipt.病害编号}`">
            <td>{{ receipt.病害编号 ?? '—' }}</td>
            <td :class="receipt.result === '已定级' ? 'tag-success' : 'tag-danger'">{{ receipt.result }}</td>
            <td>{{ receipt.不合格项 ?? '—' }}</td>
            <td>{{ receipt.message }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="detail" class="panel">
      <h3 class="panel-title">病害记录详情 #{{ detail.id }}</h3>
      <table class="data-table">
        <tbody>
          <tr v-for="field in detailFields" :key="field">
            <th>{{ field }}</th>
            <td>{{ detail[field] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="panel-foot">
        <button class="btn ghost" type="button" @click="detail = null">关闭详情</button>
      </p>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              type="checkbox"
              :disabled="!selectable(row)"
              :checked="selectedIds.includes(Number(row.id))"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看</button>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无病害登记数据，可先登记病害记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条病害登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Receipt = {
  entry_id: number | null
  病害编号: string | null
  result: string
  不合格项: string | null
  message: string
}

const ENDPOINT = '/api/disease'
const columns = ["病害编号", "所在设施", "病害类型", "病害位置", "严重等级", "发现日期", "登记人员", "病害状态"]
const actions = ["确认定级", "提交闭环", "挂起病害"]
const statuses = ["待定级", "已定级", "处置中", "已闭环", "已挂起"]
const stats = [{"label": "待定级病害", "value": 0}, {"label": "处置中病害", "value": 0}, {"label": "超期未闭环", "value": 0}]
// 已闭环、已挂起的病害不允许批量改动；严重等级取值与后端保持一致
const lockedStatuses = ["已闭环", "已挂起"]
const levels = ["轻微", "一般", "较重", "严重"]
const detailFields = [...columns, "定级结论", "定级批次", "定级日期", "退回原因"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedIds = ref<number[]>([])
const batchVisible = ref(false)
const batchNo = ref('')
const gradeLevel = ref('')
const gradeConclusion = ref('')
const receipts = ref<Receipt[]>([])
const batchMessage = ref('')
const detail = ref<Row | null>(null)

function selectable(row: Row) {
  return !lockedStatuses.includes(String(row.status ?? ''))
}

function toggleRow(row: Row) {
  const id = Number(row.id)
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter(item => item !== id)
    : [...selectedIds.value, id]
}

const allSelected = computed(() => {
  const eligible = rows.value.filter(selectable).map(row => Number(row.id))
  return eligible.length > 0 && eligible.every(id => selectedIds.value.includes(id))
})

function toggleAll() {
  const eligible = rows.value.filter(selectable).map(row => Number(row.id))
  selectedIds.value = allSelected.value ? [] : eligible
}

function openBatch() {
  if (!selectedIds.value.length) {
    errorMessage.value = '请先勾选要批量定级的病害记录'
    return
  }
  errorMessage.value = ''
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  batchNo.value = `PLDJ-${stamp}-${String(Date.now()).slice(-4)}`
  batchVisible.value = true
}

async function submitBatch() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch-grade`, {
      method: 'POST',
      body: JSON.stringify({
        batch_no: batchNo.value,
        items: selectedIds.value.map(id => ({
          entry_id: id,
          严重等级: gradeLevel.value,
          定级结论: gradeConclusion.value,
        })),
      }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error('批量定级提交失败，请稍后重试')
    }
    receipts.value = payload.receipts ?? []
    batchMessage.value = payload.message ?? ''
    if (payload.ok) {
      batchVisible.value = false
      selectedIds.value = []
      await reload()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量定级提交失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('病害记录详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '病害记录详情读取失败'
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
  errorMessage.value = '病害记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('病害登记动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '病害登记操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('病害记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '病害登记列表读取失败'
  }
}

onMounted(reload)
</script>
