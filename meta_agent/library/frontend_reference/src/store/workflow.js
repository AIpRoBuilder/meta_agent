import { reactive } from 'vue'
import { resetSession, runStep } from '../api/workflow'

export const STEP_METADATA = [
  {
    id: 'GetSystemTime',
    title: '获取当前系统时间，输出格式化时间字符串和小时数值',
    prompt: '获取当前系统时间，输出格式化时间字符串和小时数值',
    dependencies: [],
    services: [],
    inputRequired: false,
    nodeKind: 'operation',
    extData: { type: 'none', desc: 'no need for ext data', inputs_format: {} },
  },
  {
    id: 'SelectImage',
    title: '根据小时值匹配预设图像URL，按规则返回对应图像，如无匹配返回默认图像',
    prompt: '根据小时值匹配预设图像URL，按规则返回对应图像，如无匹配返回默认图像',
    dependencies: ['GetSystemTime'],
    services: [],
    inputRequired: false,
    nodeKind: 'operation',
    extData: { type: 'none', desc: 'no need for ext data', inputs_format: {} },
  },
]

export function createWorkflowStore() {
  const state = reactive({
    sessionId: null,
    stepStatus: {},
    stepResults: {},
    conversationEntries: [],
    completedSteps: [],
    runningStep: null,
    totalSteps: STEP_METADATA.length,
    eventLog: [],
  })

  function resetLocalState() {
    state.stepStatus = {}
    state.stepResults = {}
    state.conversationEntries = []
    state.completedSteps = []
    state.runningStep = null

    STEP_METADATA.forEach((step) => {
      state.stepStatus[step.id] = 'locked'
      state.stepResults[step.id] = null
    })
  }

  function completedSet() {
    return new Set(state.completedSteps)
  }

  function buildSessionId() {
    return `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  }

  function getOrCreateSessionId() {
    let sid = localStorage.getItem('agui_sessionId')
    if (!sid) {
      sid = buildSessionId()
      localStorage.setItem('agui_sessionId', sid)
    }
    return sid
  }

  function addEventLog(type, message) {
    const now = new Date()
    const time = [now.getHours(), now.getMinutes(), now.getSeconds()]
      .map((value) => String(value).padStart(2, '0'))
      .join(':')

    state.eventLog.push({
      id: now.getTime() + Math.random(),
      type,
      time,
      message,
    })
  }

  function upsertConversationEntry(entry) {
    const nextEntries = state.conversationEntries.slice()
    const existingIndex = nextEntries.findIndex((item) => item.id === entry.id)

    if (existingIndex >= 0) {
      nextEntries.splice(existingIndex, 1, entry)
    } else {
      nextEntries.push(entry)
    }

    state.conversationEntries = nextEntries
  }

  function isCompleted(stepId) {
    return completedSet().has(stepId)
  }

  function isUnlocked(stepId) {
    const step = STEP_METADATA.find((item) => item.id === stepId)
    if (!step) {
      return false
    }

    const done = completedSet()
    return step.dependencies.every((depId) => done.has(depId))
  }

  function markCompleted(stepId) {
    if (!stepId) {
      return
    }

    if (!isCompleted(stepId)) {
      state.completedSteps = state.completedSteps.concat(stepId)
    }

    state.stepStatus[stepId] = 'completed'
  }

  function updateUnlocks() {
    STEP_METADATA.forEach((step) => {
      if (state.stepStatus[step.id] === 'locked' && isUnlocked(step.id)) {
        state.stepStatus[step.id] = 'active'
        if (step.nodeKind === 'operation' && !step.inputRequired) {
          submitStep(step.id)
        }
      }
    })
  }

  function handleEvent(event, stepId) {
    const eventStepId = event.stepId || event.stepName || stepId

    if (event.type === 'STEP_STARTED') {
      addEventLog('start', `${eventStepId} 开始执行`)
      return
    }

    if (event.type === 'STEP_FINISHED') {
      markCompleted(eventStepId)
      state.runningStep = null
      addEventLog('finish', `${eventStepId} 已完成`)
      updateUnlocks()
      return
    }

    if (event.type === 'TEXT_MESSAGE_CONTENT') {
      addEventLog('chat', event.content || event.delta || '')
      return
    }

    if (event.type === 'CUSTOM' && event.name === 'step_card') {
      const payload = event.payload || event.value || {}
      const currentStepId = payload.stepId || stepId
      state.stepResults[currentStepId] = {
        card: payload.card,
        derived: payload.derived,
      }
      upsertConversationEntry({
        id: `card:${currentStepId}`,
        type: 'card',
        stepId: currentStepId,
        card: payload.card || null,
      })

      if (payload.isFinal) {
        markCompleted(currentStepId)
        state.runningStep = null
        addEventLog('finish', `${currentStepId} 卡片最终更新`)
        updateUnlocks()
      }
      return
    }

    if (event.type === 'RUN_ERROR') {
      state.stepStatus[stepId] = 'error'
      state.runningStep = null
      addEventLog('error', event.error || '未知错误')
      return
    }

    if (event.type === 'RUN_FINISHED') {
      state.runningStep = null
      addEventLog('info', '运行流结束')
    }
  }

  async function submitStep(stepId, inputValue = '') {
    if (state.runningStep) {
      return
    }

    if (!isUnlocked(stepId) && state.stepStatus[stepId] !== 'error') {
      return
    }

    if (inputValue && inputValue.trim()) {
      state.conversationEntries = state.conversationEntries.concat({
        id: `user:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
        type: 'user',
        stepId,
        text: inputValue.trim(),
      })
    }

    state.runningStep = stepId
    state.stepStatus[stepId] = 'running'
    addEventLog('start', `提交步骤 ${stepId}`)

    try {
      await runStep({ sessionId: state.sessionId, stepId, input: inputValue }, (event) => {
        handleEvent(event, stepId)
      })
    } catch (error) {
      state.stepStatus[stepId] = 'error'
      state.runningStep = null
      addEventLog('error', `步骤 ${stepId} 错误: ${error.message}`)
    }
  }

  async function resetCurrentSession() {
    let nextSessionId = state.sessionId || getOrCreateSessionId()

    try {
      const data = await resetSession(nextSessionId)
      nextSessionId = data.sessionId || nextSessionId
    } catch (_) {
      nextSessionId = buildSessionId()
    }

    state.sessionId = nextSessionId
    localStorage.setItem('agui_sessionId', nextSessionId)
    resetLocalState()
    state.eventLog = []
    addEventLog('info', '会话已重置')
    updateUnlocks()
  }

  async function createNewSession() {
    const sessionId = buildSessionId()
    state.sessionId = sessionId
    localStorage.setItem('agui_sessionId', sessionId)

    try {
      await resetSession(sessionId)
    } catch (_) {
      // Keep local session state even if the backend reset is unavailable.
    }

    resetLocalState()
    state.eventLog = []
    addEventLog('info', '✨ 新会话已创建')
    updateUnlocks()
  }

  function progressText() {
    return `${state.completedSteps.length}/${state.totalSteps}`
  }

  function progressPercent() {
    return state.totalSteps ? Math.round((state.completedSteps.length / state.totalSteps) * 100) : 0
  }

  function displaySessionId() {
    if (!state.sessionId) {
      return '—'
    }
    return state.sessionId.length > 18 ? `${state.sessionId.slice(0, 16)}…` : state.sessionId
  }

  function initialize() {
    state.sessionId = getOrCreateSessionId()
    resetLocalState()
    state.eventLog = []
    addEventLog('info', '会话初始化完成')
    updateUnlocks()
  }

  return {
    state,
    steps: STEP_METADATA,
    initialize,
    submitStep,
    resetCurrentSession,
    createNewSession,
    isUnlocked,
    progressText,
    progressPercent,
    displaySessionId,
  }
}