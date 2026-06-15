<template>
  <section class="node-page node-page-time">
    <div class="node-panel-header">
      <div>
        <h2>获取系统时间</h2>
        <p>读取当前系统时钟，输出格式化时间字符串与小时数值，作为后续图像匹配的依赖输入。</p>
      </div>
      <button class="node-action" type="button" :disabled="busy" @click="runCurrentStep">
        {{ busy ? '执行中...' : '重新执行' }}
      </button>
    </div>

    
  </section>
</template>

<script>
import { createWorkflowStore } from '../store/workflow'
export default {
  name: 'GetSystemTimeView',
  inject: ['workflowStore'],
  props: {
    stepId: {
      type: String,
      default: 'GetSystemTime',
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

<style src="../styles/get-system-time.css"></style>