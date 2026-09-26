<template>
  <section class="page" data-module="disease">
    <header class="page-head">
      <div>
        <h2>病害登记管理</h2>
        <p class="page-desc">维护病害记录，围绕病害编号、所在设施、病害类型、病害位置做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记病害记录</button>
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

    <section v-if="selectedIds.length" class="batch-panel">
      <header class="batch-head">
        <strong>批量定级（已选 {{ selectedIds.length }} 条）</strong>
        <label class="batch-no">
          <span>批次号</span>
          <input v-model="batchNo" placeholder="同一批次号重复提交不会产生重复记录" />
        </label>
      </header>
      <div class="batch-fill">
        <select v-model="quickSeverity">
          <option value="">严重等级（批量填充）</option>
          <option v-for="level in severityLevels" :key="level" :value="level">{{ level }}</option>
        </select>
        <input v-model="quickConclusion" placeholder="定级结论（批量填充）" />
        <button class="btn" type="button" @click="applyQuickFill">填充到所选</button>
        <button class="btn primary" type="button" :disabled="submitting" @click="submitBatchGrade">
          {{ submitting ? '提交中…' : '提交批量定级' }}
        </button>
        <button class="btn ghost" type="button" @click="clearSelection">清空选择</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>病害编号</th>
            <th>所在设施</th>
            <th>严重等级</th>
            <th>定级结论</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in selectedRows" :key="String(row.id)">
            <td>{{ row['病害编号'] ?? row.id }}</td>
            <td>{{ row['所在设施'] ?? '—' }}</td>
            <td>
              <select v-model="gradeForms[Number(row.id)].severity">
                <option value="">请选择</option>
                <option v-for="level in severityLevels" :key="level" :value="level">{{ level }}</option>
              </select>
            </td>
            <td><input v-model="gradeForms[Number(row.id)].conclusion" placeholder="填写定级结论" /></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="receipts.length" class="receipt-panel">
      <header class="batch-head">
        <strong>批量定级回执</strong>
        <span class="page-desc">{{ batchMessage }}</span>
      </header>
      <ul class="receipt-list">
        <li v-for="receipt in receipts" :key="`${receipt.entry_id}-${receipt.result}`">
          <span class="receipt-code">{{ receipt['病害编号'] ?? `记录 ${receipt.entry_id}` }}</span>
          <span class="tag" :class="receipt.result === '已定级' ? 'tag-ok' : 'tag-reject'">{{ receipt.result }}</span>
          <span>{{ receipt.message }}</span>
        </li>
      </ul>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              :checked="allSelectableChecked"
              title="全选可定级病害（已闭环、已挂起不可批量改动）"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              type="checkbox"
              :checked="selectedIds.includes(Number(row.id))"
              :disabled="!canGrade(row)"
              :title="canGrade(row) ? '选择参与批量定级' : '已闭环或已挂起的病害不能批量改动'"
              @change="toggleRow(row)"
            />
          </td>
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
type Receipt = { entry_id: number | null; result: string; message: string } & Row

const ENDPOINT = '/api/disease'
const columns = ["病害编号", "所在设施", "病害类型", "病害位置", "严重等级", "定级结论", "发现日期", "登记人员", "病害状态"]
const actions = ["确认定级", "提交闭环", "挂起病害"]
const statuses = ["待定级", "已定级", "处置中", "已闭环", "已挂起"]
const severityLevels = ["轻微", "一般", "较重", "严重"]
const protectedStatuses = ["已闭环", "已挂起"]
const stats = [{"label": "待定级病害", "value": 0}, {"label": "处置中病害", "value": 0}, {"label": "超期未闭环", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedIds = ref<number[]>([])
const gradeForms = ref<Record<number, { severity: string; conclusion: string }>>({})
const quickSeverity = ref('')
const quickConclusion = ref('')
const batchNo = ref(newBatchNo())
const submitting = ref(false)
const receipts = ref<Receipt[]>([])
const batchMessage = ref('')

const selectedRows = computed(() => rows.value.filter((row) => selectedIds.value.includes(Number(row.id))))
const selectableRows = computed(() => rows.value.filter(canGrade))
const allSelectableChecked = computed(
  () => selectableRows.value.length > 0 && selectableRows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)

function newBatchNo() {
  return `BG-${Date.now()}-${Math.floor(Math.random() * 1000)}`
}

function canGrade(row: Row) {
  return !protectedStatuses.includes(String(row.status ?? ''))
}

function toggleRow(row: Row) {
  if (!canGrade(row)) {
    return
  }
  const id = Number(row.id)
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((item) => item !== id)
    delete gradeForms.value[id]
  } else {
    selectedIds.value = [...selectedIds.value, id]
    gradeForms.value[id] = { severity: '', conclusion: '' }
  }
}

function toggleAll() {
  if (allSelectableChecked.value) {
    for (const row of selectableRows.value) {
      const id = Number(row.id)
      selectedIds.value = selectedIds.value.filter((item) => item !== id)
      delete gradeForms.value[id]
    }
    return
  }
  for (const row of selectableRows.value) {
    const id = Number(row.id)
    if (!selectedIds.value.includes(id)) {
      selectedIds.value = [...selectedIds.value, id]
      gradeForms.value[id] = { severity: '', conclusion: '' }
    }
  }
}

function clearSelection() {
  selectedIds.value = []
  gradeForms.value = {}
}

function applyQuickFill() {
  for (const id of selectedIds.value) {
    const form = gradeForms.value[id]
    if (!form) {
      continue
    }
    if (quickSeverity.value) {
      form.severity = quickSeverity.value
    }
    if (quickConclusion.value) {
      form.conclusion = quickConclusion.value
    }
  }
}

async function submitBatchGrade() {
  if (!selectedIds.value.length || submitting.value) {
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const items = selectedIds.value.map((id) => ({
      entry_id: id,
      严重等级: gradeForms.value[id]?.severity ?? '',
      定级结论: gradeForms.value[id]?.conclusion ?? '',
    }))
    const response = await request(`${ENDPOINT}/batch-grade`, {
      method: 'POST',
      body: JSON.stringify({ batch_no: batchNo.value, items }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '批量定级提交失败')
    }
    receipts.value = payload.receipts ?? []
    batchMessage.value = payload.message ?? ''
    clearSelection()
    batchNo.value = newBatchNo()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量定级提交失败'
  } finally {
    submitting.value = false
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
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '病害登记动作未生效，请稍后重试')
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
