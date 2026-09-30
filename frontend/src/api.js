const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: JSON_HEADERS,
    ...options
  })
  if (!response.ok) {
    let message = `请求失败：${response.status}`
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      // Keep the HTTP status message if the body is not JSON.
    }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

export const api = {
  health: () => request('/api/health'),
  model: () => request('/api/model'),
  scenarios: () => request('/api/scenarios'),
  scenario: (id, revealTruth) =>
    request(`/api/scenarios/${id}?reveal_truth=${revealTruth ? 'true' : 'false'}`),
  waveforms: (scenarioId, pickSetId, phase) => {
    const params = new URLSearchParams({ phase })
    if (pickSetId) params.set('pick_set_id', pickSetId)
    return request(`/api/scenarios/${scenarioId}/waveforms?${params}`)
  },
  revise: (scenarioId, payload) =>
    request(`/api/scenarios/${scenarioId}/revisions`, {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  locate: (scenarioId, payload) =>
    request(`/api/scenarios/${scenarioId}/locate`, {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  runs: (scenarioId) => request(`/api/scenarios/${scenarioId}/runs`),
  run: (id) => request(`/api/runs/${id}`)
}
