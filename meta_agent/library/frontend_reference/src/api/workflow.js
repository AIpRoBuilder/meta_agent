export async function runStep(payload, onEvent) {
  const response = await fetch('/api/run-step', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  if (!response.body) {
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  let done = false

  while (!done) {
    const chunk = await reader.read()
    done = chunk.done
    if (done) {
      break
    }

    buffer += decoder.decode(chunk.value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) {
        continue
      }

      const dataStr = line.slice(6).trim()
      if (!dataStr || dataStr === '[DONE]') {
        continue
      }

      onEvent(JSON.parse(dataStr))
    }
  }
}

export async function resetSession(sessionId) {
  const response = await fetch('/api/reset-session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  return response.json()
}