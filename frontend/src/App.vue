<template>
  <div class="app-shell">
    <header class="hero">
      <h1>地震定位教学实验台：波形到时 → 候选源位置</h1>
      <p>Vue 3 + Plotly.js · FastAPI + ObsPy + SciPy · PostgreSQL/PostGIS</p>
    </header>

    <div class="warning-strip">
      <strong>教学限制：</strong>
      本系统仅处理内置合成示例和显式简化速度模型，输出的是带残差、几何覆盖和版本信息的候选解；
      不是地震预警系统，不能作为真实事件应急依据。
    </div>

    <main class="layout">
      <div class="main-column">
        <section class="card">
          <div class="row between">
            <h2>1. 选择合成案例</h2>
            <span v-if="model" class="badge">{{ model.version }}</span>
          </div>
          <div v-if="loading" class="notice">正在加载示例数据……</div>
          <div v-if="error" class="notice bad">{{ error }}</div>
          <div class="scenario-grid">
            <button
              v-for="item in scenarios"
              :key="item.id"
              class="scenario-card"
              :class="{ active: scenario?.id === item.id }"
              @click="selectScenario(item.id)"
            >
              <strong>{{ item.name }}</strong>
              <span class="small">{{ item.description }}</span>
              <span class="small">{{ item.station_count }} 个台站 · {{ item.data_version }}</span>
            </button>
          </div>
        </section>

        <section v-if="scenario" class="card">
          <div class="row between">
            <h2>2. 选择数据、震相和模型参数</h2>
            <label class="row">
              <input v-model="revealTruth" type="checkbox" @change="loadScenario" />
              教学模式：揭示已知合成源
            </label>
          </div>

          <div class="row">
            <div class="field">
              <label>拾取集（原始与人工分开）</label>
              <select v-model.number="selectedPickSetId" @change="onPickSetChange">
                <option
                  v-for="pickSet in scenario.pick_sets"
                  :key="pickSet.id"
                  :value="pickSet.id"
                >
                  {{ pickSet.kind === 'raw' ? '原始' : '人工' }} · {{ pickSet.version }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>只允许单一震相</label>
              <select v-model="phase" @change="loadWaveforms">
                <option value="P">仅 P 波（Vp={{ model?.p_velocity_km_s }} km/s）</option>
                <option value="S">仅 S 波（Vs={{ model?.s_velocity_km_s }} km/s）</option>
              </select>
            </div>
            <div class="field">
              <label>固定深度（km；空=自由深度）</label>
              <input v-model="fixedDepth" type="number" step="0.5" />
            </div>
            <div class="field">
              <label>离群残差阈值（s）</label>
              <input v-model.number="outlierThreshold" type="number" min="0.1" step="0.1" />
            </div>
            <div class="field">
              <label>候选比较</label>
              <label class="row"><input v-model="includeFreeDepth" type="checkbox" />加入自由深度候选</label>
            </div>
            <button :disabled="locating" @click="locate">
              {{ locating ? 'SciPy 拟合中……' : '重新定位并保留可解释记录' }}
            </button>
          </div>

          <p class="small">
            当前拾取集：<span :class="['badge', selectedPickSet?.kind]">{{ selectedPickSet?.version }}</span>
            · 数据版本：<span class="badge">{{ scenario.data_version }}</span>
            · 定位时 P/S 不混用；缺测以空值显式参与记录，但不进入反演。
          </p>
          <p class="small">{{ scenario.expected_teaching_note }}</p>
        </section>

        <section v-if="waveforms" class="card">
          <div class="row between">
            <h2>3. 波形与到时（ObsPy 解析 MiniSEED）</h2>
            <span class="small">蓝/橙三角为所选 {{ phase }} 到时；红色为离群，黄色表示缺测行，绿色虚线为人工修订。点击波形可回填修订时间。</span>
          </div>
          <WaveformPlot
            :traces="waveforms.traces"
            :selected-station="selectedStation"
            @pick-click="onWaveformClick"
          />
        </section>

        <section v-if="scenario" class="card">
          <h2>4. 人工修订（不会覆盖原始拾取）</h2>
          <div class="row" style="margin-bottom:0.7rem">
            <input v-model="revisionNote" placeholder="修订说明，例如：根据 P 初动重新判读 ST02" style="min-width:22rem" />
            <button class="secondary" :disabled="savingRevision" @click="saveRevision">
              {{ savingRevision ? '正在生成新版本……' : `从当前拾取集复制并修订 ${phase}` }}
            </button>
          </div>
          <div class="revision-grid small" style="font-weight:700">
            <span>台站</span><span>{{ phase }} 到时偏移（s；相对发震时刻）</span><span>状态</span><span>缺测/不可用</span>
          </div>
          <div v-for="row in revisionRows" :key="row.station_code" class="revision-grid">
            <span>{{ row.station_code }} · {{ row.station_name }}</span>
            <input v-model="row.arrival_time_offset_s" type="number" step="0.01" :disabled="row.missing" />
            <select v-model="row.status" :disabled="row.missing">
              <option value="revised">人工修订</option>
              <option value="observed">沿用/正常</option>
              <option value="outlier">标记离群</option>
            </select>
            <label><input v-model="row.missing" type="checkbox" /> 缺测</label>
          </div>
        </section>

        <section v-if="run" class="card">
          <div class="row between">
            <h2>5. 定位结论与几何覆盖</h2>
            <span v-if="run.locatable" class="badge good">有候选解，不是唯一精确坐标</span>
            <span v-else class="badge bad">不可定位 / 不给出伪坐标</span>
          </div>
          <div v-if="!run.locatable" class="notice bad">
            <strong>不可定位：</strong>{{ run.reason || '有效到时或几何约束不足。' }}
          </div>
          <div v-if="run.warning" class="notice warn" style="margin-top:0.6rem">
            <strong>几何覆盖警告：</strong>{{ run.warning }}
          </div>
          <MapPlot
            :stations="scenario.stations"
            :truth="revealTruth ? scenario : null"
            :candidates="run.candidates"
            :selected-candidate-id="selectedCandidateId"
          />
          <dl class="kv" style="margin-top:0.7rem">
            <dt>模型版本</dt><dd class="code">{{ run.model_version }}</dd>
            <dt>数据版本</dt><dd class="code">{{ run.data_version }}</dd>
            <dt>拾取版本</dt><dd class="code">{{ run.picks_version }}</dd>
            <dt>输入哈希</dt><dd class="code">{{ run.input_hash }}</dd>
            <dt>震相</dt><dd>{{ run.phase }}（未与另一震相混用）</dd>
            <dt>结果记录 ID</dt><dd>#{{ run.id }} · {{ new Date(run.created_at).toLocaleString() }}</dd>
          </dl>
        </section>

        <section v-if="selectedCandidate" class="card">
          <h2>6. 残差表：缺测、错误拾取和被剔除值都要可见</h2>
          <p class="small">
            RMS = {{ fmt(selectedCandidate.rms_residual_s, 3) }} s；
            最大绝对残差 = {{ fmt(selectedCandidate.max_abs_residual_s, 3) }} s；
            使用 {{ selectedCandidate.used_pick_count }} 个拾取，剔除/不可用
            {{ selectedCandidate.rejected_pick_count }} 个。
          </p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>台站</th><th>震相</th><th>状态</th><th>观测 (s)</th><th>预测 (s)</th>
                  <th>残差 obs-pred (s)</th><th>距离 (km)</th><th>是否入算</th><th>说明</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="residual in selectedCandidate.residuals"
                  :key="residual.pick_id"
                  :class="{ unused: !residual.used && residual.status !== 'missing', missing: residual.status === 'missing' }"
                >
                  <td>{{ residual.station_code }}</td>
                  <td>{{ residual.phase }}</td>
                  <td>{{ statusLabel(residual.status) }}</td>
                  <td>{{ fmt(residual.observed_offset_s, 3) }}</td>
                  <td>{{ fmt(residual.predicted_offset_s, 3) }}</td>
                  <td>{{ fmt(residual.residual_s, 3) }}</td>
                  <td>{{ fmt(residual.distance_km, 2) }}</td>
                  <td>{{ residual.used ? '是' : '否' }}</td>
                  <td>{{ residual.note || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <aside class="side-column">
        <section v-if="model" class="card">
          <h2>简化速度模型</h2>
          <p>{{ model.description }}</p>
          <ul class="small">
            <li v-for="item in model.assumptions" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="scenario" class="card">
          <h2>原始拾取与人工版本</h2>
          <div v-for="pickSet in scenario.pick_sets" :key="pickSet.id" style="margin-bottom:0.8rem">
            <div class="row between">
              <span :class="['badge', pickSet.kind]">{{ pickSet.kind === 'raw' ? '原始' : '人工' }}</span>
              <span class="code small">{{ pickSet.version }}</span>
            </div>
            <p class="small">{{ pickSet.note }}</p>
            <div class="small">
              P: {{ phaseCount(pickSet, 'P') }} 条 ·
              S: {{ phaseCount(pickSet, 'S') }} 条
            </div>
          </div>
        </section>

        <section v-if="run" class="card">
          <h2>候选解比较</h2>
          <div v-if="!run.candidates.length" class="notice bad">无候选坐标。请先查看不可定位原因和几何覆盖。</div>
          <div v-else class="candidate-list">
            <button
              v-for="candidate in run.candidates"
              :key="candidate.id"
              class="candidate-item"
              :class="{ active: candidate.id === selectedCandidateId }"
              @click="selectedCandidateId = candidate.id"
            >
              <strong>{{ candidate.label }}</strong>
              <span class="small">
                ({{ fmt(candidate.x_km, 2) }}, {{ fmt(candidate.y_km, 2) }},
                {{ fmt(candidate.z_km, 2) }}) km
              </span>
              <span class="small">
                RMS {{ fmt(candidate.rms_residual_s, 3) }} s ·
                入算 {{ candidate.used_pick_count }} ·
                剔除 {{ candidate.rejected_pick_count }}
              </span>
              <span :class="['badge', coverageClass(candidate.coverage_rating)]">
                覆盖 {{ coverageLabel(candidate.coverage_rating) }}
              </span>
            </button>
          </div>
        </section>

        <section v-if="selectedCandidate" class="card">
          <h2>选中候选诊断</h2>
          <dl class="kv">
            <dt>发震时刻偏移</dt><dd>{{ fmt(selectedCandidate.origin_time_offset_s, 3) }} s</dd>
            <dt>方位空挡</dt><dd>{{ fmt(selectedCandidate.azimuthal_gap_deg, 1) }}°</dd>
            <dt>水平条件数</dt><dd>{{ fmt(selectedCandidate.condition_number, 2) }}</dd>
            <dt>设计矩阵秩</dt><dd>{{ selectedCandidate.rank ?? '—' }}</dd>
            <dt>1σ 椭圆半轴</dt>
            <dd>{{ fmt(selectedCandidate.uncertainty_semi_major_km, 2) }} / {{ fmt(selectedCandidate.uncertainty_semi_minor_km, 2) }} km</dd>
            <dt>深度处理</dt><dd>{{ selectedCandidate.depth_fixed ? '固定深度' : '自由深度' }}</dd>
          </dl>
          <p v-if="revealTruth && scenario.source_x_km != null" class="small">
            到已知合成源的水平距离：
            {{ fmt(distanceToTruth(selectedCandidate), 2) }} km。
            教学比较用，不代表真实事件误差。
          </p>
        </section>

        <section v-if="historyRuns.length" class="card">
          <h2>历史重算记录</h2>
          <div class="candidate-list">
            <button
              v-for="item in historyRuns"
              :key="item.id"
              class="candidate-item secondary"
              @click="loadRun(item.id)"
            >
              <strong>#{{ item.id }} · {{ item.phase }} · {{ item.model_version }}</strong>
              <span class="small">{{ new Date(item.created_at).toLocaleString() }}</span>
              <span :class="['badge', item.locatable ? 'good' : 'bad']">
                {{ item.locatable ? '有候选' : '不可定位' }}
              </span>
            </button>
          </div>
        </section>
      </aside>
    </main>

    <footer class="footer-note" style="padding:0 1.6rem 1.5rem">
      所有定位结果都绑定模型版本、案例数据版本、拾取集版本和输入哈希；相同输入可重算并解释差异。
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import WaveformPlot from './components/WaveformPlot.vue'
import MapPlot from './components/MapPlot.vue'

const scenarios = ref([])
const scenario = ref(null)
const model = ref(null)
const waveforms = ref(null)
const run = ref(null)
const historyRuns = ref([])
const selectedPickSetId = ref(null)
const selectedCandidateId = ref(null)
const selectedStation = ref(null)
const loading = ref(false)
const locating = ref(false)
const savingRevision = ref(false)
const error = ref('')
const phase = ref('P')
const revealTruth = ref(false)
const fixedDepth = ref('8')
const outlierThreshold = ref(1.5)
const includeFreeDepth = ref(true)
const revisionNote = ref('人工修订拾取')
const revisionRows = ref([])

const selectedPickSet = computed(() =>
  scenario.value?.pick_sets.find((item) => item.id === selectedPickSetId.value) || null
)
const selectedCandidate = computed(() =>
  run.value?.candidates.find((item) => item.id === selectedCandidateId.value) || null
)

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(digits)
}
function statusLabel(status) {
  return { observed: '正常', missing: '缺测', outlier: '离群/剔除', revised: '人工修订' }[status] || status
}
function coverageLabel(rating) {
  return { good: '良好', fair: '一般', poor: '差', insufficient: '不足' }[rating] || rating
}
function coverageClass(rating) {
  return { good: 'good', fair: 'warn', poor: 'bad', insufficient: 'bad' }[rating] || 'warn'
}
function phaseCount(pickSet, phaseName) {
  return pickSet.picks.filter((pick) => pick.phase === phaseName && pick.arrival_time_offset_s != null).length
}
function distanceToTruth(candidate) {
  const dx = candidate.x_km - scenario.value.source_x_km
  const dy = candidate.y_km - scenario.value.source_y_km
  return Math.sqrt(dx * dx + dy * dy)
}

async function loadInitial() {
  try {
    const [modelData, scenarioData] = await Promise.all([api.model(), api.scenarios()])
    model.value = modelData
    scenarios.value = scenarioData
    if (scenarioData[0]) await selectScenario(scenarioData[0].id)
  } catch (err) {
    error.value = err.message
  }
}

async function selectScenario(id) {
  loading.value = true
  error.value = ''
  run.value = null
  waveforms.value = null
  historyRuns.value = []
  try {
    await loadScenario(id)
    const runs = await api.runs(id)
    historyRuns.value = runs
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadScenario(id = scenario.value?.id) {
  scenario.value = await api.scenario(id, revealTruth.value)
  const preferred = scenario.value.pick_sets.find((item) => item.kind === 'raw') || scenario.value.pick_sets[0]
  selectedPickSetId.value = preferred.id
  initRevisionRows()
  await loadWaveforms()
}

function onPickSetChange() {
  initRevisionRows()
  loadWaveforms()
  run.value = null
}

function initRevisionRows() {
  const pickSet = selectedPickSet.value
  if (!pickSet || !scenario.value) return
  revisionRows.value = scenario.value.stations.map((station) => {
    const pick = pickSet.picks.find(
      (item) => item.station_code === station.code && item.phase === phase.value
    )
    return {
      station_code: station.code,
      station_name: station.name,
      arrival_time_offset_s: pick?.arrival_time_offset_s ?? '',
      status: pick?.status === 'missing' ? 'observed' : pick?.status || 'revised',
      missing: !pick || pick.arrival_time_offset_s == null
    }
  })
}

async function loadWaveforms() {
  if (!scenario.value) return
  waveforms.value = await api.waveforms(scenario.value.id, selectedPickSetId.value, phase.value)
}

function onWaveformClick({ station }) {
  selectedStation.value = station
  const row = revisionRows.value.find((item) => item.station_code === station)
  row?.status && (row.status = 'revised')
}

async function saveRevision() {
  if (!scenario.value) return
  savingRevision.value = true
  error.value = ''
  try {
    const payload = {
      base_pick_set_id: selectedPickSetId.value,
      phase: phase.value,
      note: revisionNote.value || '人工修订拾取',
      revisions: revisionRows.value.map((row) => ({
        station_code: row.station_code,
        phase: phase.value,
        arrival_time_offset_s: row.missing ? null : Number(row.arrival_time_offset_s),
        status: row.missing ? 'missing' : row.status,
        note: row.missing ? '人工标记为缺测' : revisionNote.value
      }))
    }
    const result = await api.revise(scenario.value.id, payload)
    await loadScenario(scenario.value.id)
    selectedPickSetId.value = result.pick_set_id
    initRevisionRows()
    await loadWaveforms()
  } catch (err) {
    error.value = err.message
  } finally {
    savingRevision.value = false
  }
}

async function locate() {
  if (!scenario.value || !selectedPickSet.value) return
  locating.value = true
  error.value = ''
  try {
    const payload = {
      pick_set_id: selectedPickSetId.value,
      phase: phase.value,
      fixed_depth_km: fixedDepth.value === '' ? null : Number(fixedDepth.value),
      outlier_threshold_s: Number(outlierThreshold.value),
      include_free_depth: includeFreeDepth.value
    }
    run.value = await api.locate(scenario.value.id, payload)
    selectedCandidateId.value = run.value.selected_candidate_id || run.value.candidates[0]?.id || null
    historyRuns.value = await api.runs(scenario.value.id)
  } catch (err) {
    error.value = err.message
  } finally {
    locating.value = false
  }
}

async function loadRun(id) {
  const fetched = await api.run(id)
  run.value = fetched
  selectedCandidateId.value = fetched.selected_candidate_id || fetched.candidates[0]?.id || null
  selectedPickSetId.value = fetched.pick_set_id
  phase.value = fetched.phase
  fixedDepth.value = fetched.fixed_depth_km == null ? '' : String(fetched.fixed_depth_km)
  scenario.value = await api.scenario(fetched.scenario_id, revealTruth.value)
  initRevisionRows()
  await loadWaveforms()
  run.value = await api.run(id)
  selectedCandidateId.value = run.value.selected_candidate_id || run.value.candidates[0]?.id || null
}

onMounted(loadInitial)
</script>
