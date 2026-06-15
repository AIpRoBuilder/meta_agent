<template>
  <section class="node-page node-page-image">
    <div class="node-panel-header">
      <div>
        <h2>匹配图像</h2>
        <p>根据前一个节点生成的小时值命中预设规则，返回对应图像 URL 与命中状态。</p>
      </div>
      <button
        class="node-action"
        type="button"
        :disabled="busy || !store.isUnlocked(stepId)"
        @click="runCurrentStep"
      >
        {{ busy ? '执行中...' : '重新匹配' }}
      </button>
    </div>

    
  </section>
</template>

<script>
import { createWorkflowStore } from '../store/workflow'
export default {
  name: 'SelectImageView',
  inject: ['workflowStore'],
  props: {
    stepId: {
      type: String,
      default: 'SelectImage',
    },
  },
  computed: {
    store() {
      return this.workflowStore
    },
    busy() {
      return this.store.state.runningStep === this.stepId
    },
  },
  methods: {
    runCurrentStep() {
      this.store.submitStep(this.stepId)
    },
  },
}
</script>

<style src="../styles/select-image.css"></style>