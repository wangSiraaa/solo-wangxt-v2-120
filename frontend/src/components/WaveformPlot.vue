<template>
  <div ref="el" class="plot waveform"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  traces: { type: Array, required: true },
  selectedStation: { type: String, default: null }
})
const emit = defineEmits(['pick-click'])
const el = ref(null)
const plotInitialized = ref(false)

function colorForPick(pick) {
  if (!pick) return '#9aa4b2'
  if (pick.status === 'outlier') return '#c43c3c'
  if (pick.status === 'missing') return '#b9872a'
  const phase = props.traces.find((trace) => trace.picks.length)?.picks?.[0]?.phase
  if (pick.status === 'revised') return '#1d8a50'
  return phase === 'S' ? '#b45a18' : '#1d66c0'
}

async function draw() {
  if (!el.value || !props.traces.length) return
  const stationGap = 2.8
  const data = []
  const shapes = []
  const annotations = []

  props.traces.forEach((trace, index) => {
    const raw = trace.counts
    const maxAbs = Math.max(...raw.map((value) => Math.abs(value))) || 1
    const step = Math.max(1, Math.floor(raw.length / 2200))
    const times = []
    const values = []
    for (let i = 0; i < raw.length; i += step) {
      times.push(trace.times_s[i])
      values.push((raw[i] / maxAbs) * 0.9 + (props.traces.length - 1 - index) * stationGap)
    }
    const selected = !props.selectedStation || props.selectedStation === trace.station_code
    data.push({
      x: times,
      y: values,
      mode: 'lines',
      type: 'scattergl',
      name: trace.station_code,
      line: { color: selected ? '#26394d' : '#b6c0cc', width: 1.2 },
      text: trace.station_name,
      hovertemplate: `%{fullData.name} · %{x:.2f}s<extra>${trace.station_name}</extra>`
    })
    annotations.push({
      x: 0.2,
      y: (props.traces.length - 1 - index) * stationGap + 1.05,
      xref: 'x',
      yref: 'y',
      text: trace.station_code,
      showarrow: false,
      font: { color: selected ? '#172033' : '#8b97a6', size: 12 }
    })

    trace.picks.forEach((pick) => {
      if (pick.arrival_time_offset_s == null) return
      const y0 = (props.traces.length - 1 - index) * stationGap - 1.15
      const y1 = (props.traces.length - 1 - index) * stationGap + 1.15
      const color = colorForPick(pick)
      shapes.push({
        type: 'line',
        x0: pick.arrival_time_offset_s,
        x1: pick.arrival_time_offset_s,
        y0,
        y1,
        xref: 'x',
        yref: 'y',
        line: { color, width: 2, dash: pick.status === 'revised' ? 'dashdot' : 'solid' }
      })
      data.push({
        x: [pick.arrival_time_offset_s],
        y: [y1],
        mode: 'markers+text',
        type: 'scatter',
        name: `${trace.station_code} ${pick.phase}`,
        text: [pick.phase],
        textposition: 'top center',
        marker: { color, size: 10, symbol: 'triangle-down' },
        hovertemplate: `${trace.station_code} ${pick.phase}<br>%{x:.3f} s<br>${pick.status}<extra></extra>`
      })
    })
  })

  const layout = {
    margin: { l: 44, r: 18, t: 24, b: 38 },
    xaxis: { title: '相对发震时刻 (s)', range: [0, 30], gridcolor: '#e7ecf3' },
    yaxis: { visible: false, zeroline: false },
    hovermode: 'closest',
    shapes,
    annotations,
    plot_bgcolor: 'white',
    paper_bgcolor: 'white',
    legend: { visible: false }
  }
  const config = { responsive: true, displaylogo: false, scrollZoom: true }
  if (!plotInitialized.value) {
    await Plotly.newPlot(el.value, data, layout, config)
    el.value.on('plotly_click', (event) => {
      const point = event.points?.[0]
      if (!point || !point.fullData?.name) return
      const code = point.fullData.name.split(' ')[0]
      const station = props.traces.find((trace) => trace.station_code === code)
      if (station) emit('pick-click', { station: station.station_code, time: point.x })
    })
    plotInitialized.value = true
  } else {
    await Plotly.react(el.value, data, layout, config)
  }
}

function relayout() {
  if (el.value) Plotly.Plots.resize(el.value)
}

onMounted(() => {
  draw()
  window.addEventListener('resize', relayout)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', relayout)
  if (el.value) Plotly.purge(el.value)
})
watch(() => props.traces, draw, { deep: true })
watch(() => props.selectedStation, draw)
</script>
