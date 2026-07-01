<template>
  <AppShell
    :active-step-id="activeStepId"
    :active-view="activeView"
    @navigate="setRoute"
  />
</template>

<script>
import {
  computed,
  defineComponent,
  onBeforeUnmount,
  onMounted,
  provide,
  ref,
} from 'vue'
import AppShell from './components/AppShell.vue'
import { createWorkflowStore } from './store/workflow'
import GetSystemTimeView from './views/GetSystemTimeView.vue'
import SelectImageView from './views/SelectImageView.vue'

const viewMap = {
  GetSystemTime: GetSystemTimeView,
  SelectImage: SelectImageView,
}

export default defineComponent({
  name: 'App',
  components: {
    AppShell,
  },
  setup() {
    const store = createWorkflowStore()
    provide('store', store)
    provide('workflowStore', store)
    store.initialize()

    const currentHash = ref(window.location.hash)

    function normalizeStepId(hash) {
      return hash.replace(/^#\/?/, '')
    }

    function isKnownStep(stepId) {
      return store.steps.some((step) => step.id === stepId)
    }

    const activeStepId = computed(() => {
      const stepId = normalizeStepId(currentHash.value)
      return isKnownStep(stepId) ? stepId : store.steps[0].id
    })

    const activeView = computed(() => viewMap[activeStepId.value] || viewMap.GetSystemTime)

    function setRoute(stepId) {
      const nextHash = `#/${stepId}`
      if (window.location.hash !== nextHash) {
        window.location.hash = nextHash
      }
      currentHash.value = nextHash
    }

    function handleHashChange() {
      currentHash.value = window.location.hash
      if (!isKnownStep(normalizeStepId(currentHash.value))) {
        setRoute(store.steps[0].id)
      }
    }

    onMounted(() => {
      if (!window.location.hash) {
        setRoute(store.steps[0].id)
      }
      window.addEventListener('hashchange', handleHashChange)
    })

    onBeforeUnmount(() => {
      window.removeEventListener('hashchange', handleHashChange)
    })

    return {
      activeStepId,
      activeView,
      setRoute,
    }
  },
})
</script>

<style>
html,
body,
#app {
  min-height: 100%;
}

body {
  margin: 0;
}
</style>
