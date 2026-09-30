<template>
  <div ref="el" class="plot map"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  stations: { type: Array, required: true },
  truth: { type: Object, default: null },
  candidates: { type: Array, default: () => [] },
  selectedCandidateId: { type: Number, default: null }
})
const el = ref(null)
const initialized = ref(false)

function ellipsePoints(candidate) {
  if (candidate.uncertainty_semi_major_km == null || candidate.uncertainty_semi_minor_km == null) {
    return null
  }
  const angle = ((candidate.uncertainty_rotation_deg || 0) * Math.PI) / 180
  const a = candidate.uncertainty_semi_major_km
  const b = candidate.uncertainty_semi_minor_km
  const pts = []
  for (let i = 0; i <= 80; i += 1) {
    const t = (i / 80) * Math.PI * 2
    const x0 = a * Math.cos(t)
    const y0 = b * Math.sin(t)
    pts.push([
      candidate.x_km + x0 * Math.cos(angle) - y0 * Math.sin(angle),
      candidate.y_km + x0 * Math.sin(angle) + y0 * Math.cos(angle)
    ])
  }
  return pts
}

async function draw() {
  if (!el.value) return
  const data = []

  if (props.stations.length) {
    data.push({
      x: props.stations.map((s) => s.x_km),
      y: props.stations.map((s) => s.y_km),
      text: props.stations.map((s) => `${s.code}<br>${s.name}`),
      mode: 'markers+text',
      type: 'scatter',
      name: '台站',
      marker: { size: 11, color: '#172033', symbol: 'square' },
      textposition: 'top center',
      hovertemplate: '%{text}<br>(%{x:.1f}, %{y:.1f}) km<extra></extra>'
    })
  }

  if (props.truth) {
    data.push({
      x: [props.truth.source_x_km],
      y: [props.truth.source_y_km],
      mode: 'markers+text',
      type: 'scatter',
      name: '已知合成源（教学揭示）',
      text: ['真值'],
      textposition: 'top center',
      marker: { size: 15, color: '#1d8a50', symbol: 'star' },
      hovertemplate: '已知源<br>(%{x:.2f}, %{y:.2f}) km<extra></extra>'
    })
  }

  const selected = props.candidates.find((item) => item.id === props.selectedCandidateId)
  if (selected) {
    data.push({
      x: [selected.x_km],
      y: [selected.y_km],
      mode: 'markers+text',
      type: 'scatter',
      name: '选中候选',
      text: [selected.label],
      textposition: 'top center',
      marker: { size: 16, color: '#d24a4a', line: { color: 'white', width: 2 } },
      hovertemplate: `${selected.label}<br>(%{x:.2f}, %{y:.2f}) km<extra></extra>`
    })
    const ellipse = ellipsePoints(selected)
    if (ellipse) {
      data.push({
        x: ellipse.map((p) => p[0]),
        y: ellipse.map((p) => p[1]),
        mode: 'lines',
        type: 'scatter',
        name: '1σ线性化不确定椭圆',
        line: { color: '#d24a4a', dash: 'dash', width: 1.5 },
        hoverinfo: 'skip',
        fill: 'toself',
        fillcolor: 'rgba(210,74,74,0.08)'
      })
    }
  }

  const others = props.candidates.filter((item) => item.id !== props.selectedCandidateId)
  if (others.length) {
    data.push({
      x: others.map((c) => c.x_km),
      y: others.map((c) => c.y_km),
      mode: 'markers',
      type: 'scatter',
      name: '其他候选解',
      marker: { size: 10, color: '#e8913a' },
      text: others.map((c) => c.label),
      hovertemplate: '%{text}<br>(%{x:.2f}, %{y:.2f}) km<extra></extra>'
    })
  }

  const layout = {
    margin: { l: 52, r: 18, t: 30, b: 46 },
    xaxis: { title: '局部 X (km)', scaleanchor: 'y', gridcolor: '#e7ecf3', zerolinecolor: '#c9d4e2' },
    yaxis: { title: '局部 Y (km)', gridcolor: '#e7ecf3', zerolinecolor: '#c9d4e2' },
    legend: { orientation: 'h', y: -0.18 },
    plot_bgcolor: 'white',
    paper_bgcolor: 'white',
    hovermode: 'closest'
  }
  const config = { responsive: true, displaylogo: false }
  if (!initialized.value) {
    await Plotly.newPlot(el.value, data, layout, config)
    initialized.value = true
  } else {
    await Plotly.react(el.value, data, layout, config)
  }
}

function relayout() {
  if (el.value) Plotly.Plots.resize(el.value)
}
onMounted(() => { draw(); window.addEventListener('resize', relayout) })
onBeforeUnmount(() => { window.removeEventListener('resize', relayout); if (el.value) Plotly.purge(el.value) })
watch(() => [props.stations, props.truth, props.candidates, props.selectedCandidateId], draw, { deep: true })
</script>
