<template>
  <div class="workflow-shell">
    <header class="topbar">
      <div class="topbar-logo">图像匹配<span>工作流</span></div>
      <div class="topbar-divider"></div>
      <div class="topbar-subtitle">AG-UI 生命周期</div>
      <div class="topbar-right">
        <span class="session-badge" :title="`Session ID: ${store.state.sessionId || '—'}`">
          会话: {{ store.displaySessionId() }}
        </span>
        <span class="topbar-progress-label">进度</span>
        <div class="topbar-progress-bar">
          <div class="topbar-progress-fill" :style="{ width: `${store.progressPercent()}%` }"></div>
        </div>
        <span class="topbar-pct">{{ store.progressText() }}</span>
        <button class="btn-topbar" type="button" @click="store.createNewSession">新会话</button>
        <button class="btn-topbar danger" type="button" @click="store.resetCurrentSession">重置</button>
      </div>
    </header>

    <main class="main-layout">
      <section class="cards-container">
        <aside class="cards-sidebar">
          <article
            v-for="step in store.steps"
            :key="step.id"
            :class="cardClass(step.id)"
            @click="$emit('navigate', step.id)"
          >
            <div class="card-header">
              <div class="step-icon-wrap operation">⚙</div>
              <div class="step-info">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-meta-row">
                  <span class="badge badge-kind">{{ step.id }}</span>
                  <span :class="statusBadgeClass(step.id)">{{ statusText(step.id) }}</span>
                  <span v-for="dep in step.dependencies" :key="dep" class="badge badge-operation">{{ dep }}</span>
                </div>
              </div>
            </div>

            <div class="card-body">
              <div class="dependency-box">
                <div v-if="step.dependencies.length === 0" class="no-deps">无依赖</div>
                <div v-for="dep in step.dependencies" :key="dep" class="dep-row">
                  <span class="dep-key">依赖</span>
                  <span class="dep-val">{{ dep }}</span>
                  <span class="badge badge-dep dep-status-text" :class="{ pending: !isCompleted(dep) }">
                    {{ isCompleted(dep) ? '已完成' : '未完成' }}
                  </span>
                </div>
              </div>
            </div>
          </article>
        </aside>

        <section class="node-stage conversation-stage">
          <component :is="activeView" :step-id="activeStepId" class="conversation-step-view" />

          <section class="conversation-panel">
            <div class="conversation-panel-header">
              <div>
                <div class="conversation-kicker">Conversation</div>
                <h3>{{ activeStepTitle }}</h3>
                <p>在这里输入当前步骤的用户内容，并查看各步骤返回的卡片结果。</p>
              </div>
              <span :class="statusBadgeClass(activeStepId)">{{ statusText(activeStepId) }}</span>
            </div>

            <div class="conversation-list">
              <div v-if="conversationEntries.length === 0" class="conversation-empty">
                还没有对话内容。你可以直接发送输入，或等待步骤返回卡片结果。
              </div>

              <article
                v-for="entry in conversationEntries"
                :key="entry.id"
                class="conversation-entry"
                :class="`conversation-entry-${entry.type}`"
              >
                <template v-if="entry.type === 'user'">
                  <div class="conversation-entry-meta">
                    <span class="conversation-role">你</span>
                    <span class="conversation-step-tag">{{ stepTitle(entry.stepId) }}</span>
                  </div>
                  <div class="conversation-bubble user">{{ entry.text }}</div>
                </template>

                <template v-else>
                  <div class="conversation-entry-meta">
                    <span class="conversation-role">步骤卡片</span>
                    <span class="conversation-step-tag">{{ stepTitle(entry.stepId) }}</span>
                  </div>

                  <div class="conversation-bubble card">
                    <div class="conversation-card-title">{{ cardTitle(entry) }}</div>

                    <div v-if="cardRows(entry).length" class="conversation-card-rows">
                      <div
                        v-for="(row, index) in cardRows(entry)"
                        :key="`${entry.id}-${row.name || 'row'}-${index}`"
                        class="conversation-card-row"
                      >
                        <span class="conversation-card-label">{{ row.name || `字段 ${index + 1}` }}</span>
                        <span class="conversation-card-value">{{ row.value }}</span>
                      </div>
                    </div>

                    <pre v-else-if="entry.card" class="conversation-card-json">{{ formatCard(entry.card) }}</pre>

                    <div v-if="cardImage(entry.card)" class="conversation-card-image-wrap">
                      <img :src="cardImage(entry.card)" :alt="stepTitle(entry.stepId)" class="conversation-card-image" />
                    </div>
                  </div>
                </template>
              </article>
            </div>

            <form class="conversation-composer" @submit.prevent="submitConversation">
              <textarea
                v-model="draftInput"
                class="conversation-input"
                rows="3"
                :placeholder="`输入要发送给 ${activeStepTitle} 的内容（可选）`"
              ></textarea>
              <div class="conversation-actions">
                <span class="conversation-hint">当前发送目标：{{ activeStepTitle }}</span>
                <button class="node-action conversation-send" type="submit" :disabled="store.state.runningStep === activeStepId">
                  {{ store.state.runningStep === activeStepId ? '发送中...' : '发送' }}
                </button>
              </div>
            </form>
          </section>
        </section>
      </section>
    </main>
  </div>
</template>

<script>
export default {
  name: 'AppShell',
  inject: ['workflowStore'],
  data() {
    return {
      draftInput: '',
    }
  },
  props: {
    activeStepId: {
      type: String,
      required: true,
    },
    activeView: {
      type: Object,
      required: true,
    },
  },
  emits: ['navigate'],
  computed: {
    store() {
      return this.workflowStore
    },
    activeStepTitle() {
      return this.stepTitle(this.activeStepId)
    },
    conversationEntries() {
      const entries = this.store.state.conversationEntries || []
      const hasCardEntry = new Set(entries.filter((entry) => entry.type === 'card').map((entry) => entry.stepId))
      const missingCards = this.store.steps
        .filter((step) => {
          const result = this.store.state.stepResults[step.id]
          return result && result.card && !hasCardEntry.has(step.id)
        })
        .map((step) => ({
          id: `card:${step.id}`,
          type: 'card',
          stepId: step.id,
          card: this.store.state.stepResults[step.id].card,
        }))

      return entries.concat(missingCards)
    },
    completedSteps() {
      return new Set(this.store.state.completedSteps)
    },
  },
  methods: {
    stepTitle(stepId) {
      const step = this.store.steps.find((item) => item.id === stepId)
      return step ? step.title : stepId
    },
    isCompleted(stepId) {
      return this.completedSteps.has(stepId)
    },
    statusText(stepId) {
      const status = this.store.state.stepStatus[stepId]
      if (status === 'locked') {
        return '锁定'
      }
      if (status === 'active') {
        return '就绪'
      }
      if (status === 'running') {
        return '执行中'
      }
      if (status === 'completed') {
        return '完成'
      }
      if (status === 'error') {
        return '错误'
      }
      return '待定'
    },
    statusBadgeClass(stepId) {
      return {
        badge: true,
        'badge-status': true,
        pending: this.store.state.stepStatus[stepId] === 'active',
        'running-badge': this.store.state.stepStatus[stepId] === 'running',
        'error-badge': this.store.state.stepStatus[stepId] === 'error',
      }
    },
    cardClass(stepId) {
      return {
        'step-card': true,
        active: this.activeStepId === stepId,
        running: this.store.state.runningStep === stepId,
        completed: this.store.state.stepStatus[stepId] === 'completed',
        error: this.store.state.stepStatus[stepId] === 'error',
        locked: this.store.state.stepStatus[stepId] === 'locked',
      }
    },
    cardTitle(entry) {
      if (entry.card && entry.card.title) {
        return entry.card.title
      }
      return this.stepTitle(entry.stepId)
    },
    cardRows(entry) {
      return (entry.card && entry.card.rows) || []
    },
    cardImage(card) {
      const rows = (card && card.rows) || []
      const imageUrlRow = rows.find((row) => row.name === 'imageUrl')
      if (imageUrlRow && imageUrlRow.value) {
        return imageUrlRow.value
      }

      const fallbackRow = rows.find((row) => row.name === 'matchedImage')
      return fallbackRow ? fallbackRow.value : ''
    },
    formatCard(card) {
      return JSON.stringify(card, null, 2)
    },
    submitConversation() {
      this.store.submitStep(this.activeStepId, this.draftInput)
      this.draftInput = ''
    },
  },
}
</script>

<style src="../styles/app.css"></style>