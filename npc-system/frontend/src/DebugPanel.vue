<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{
  token: string
  read: () => Promise<unknown>
  exportData: () => Promise<unknown>
}>()
const emit = defineEmits<{ 'update:token': [value: string] }>()
const opened = ref(false)
const data = ref<unknown>(null)
const error = ref('')
const loading = ref(false)

async function execute(download = false) {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const result = await (download ? props.exportData() : props.read())
    if (download) {
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = 'npc-session.json'
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } else data.value = result
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '调试请求失败' }
  finally { loading.value = false }
}
</script>

<template>
  <section aria-label="开发调试">
    <button class="debug-toggle" :aria-expanded="opened" @click="opened = !opened">开发调试（包含剧透）</button>
    <div v-if="opened" class="debug">
      <p>以下信息仅供开发与论文验证，不会进入NPC上下文。导出前请检查个人信息。</p>
      <label>调试口令
        <input :value="token" type="password" autocomplete="off" aria-label="调试口令"
          @input="emit('update:token', ($event.target as HTMLInputElement).value)">
      </label>
      <button :disabled="loading || !token" @click="execute()">读取调试记录</button>
      <button :disabled="loading || !token" @click="execute(true)">导出 JSON</button>
      <span v-if="error" role="alert">{{ error }}</span>
      <pre v-if="data">{{ JSON.stringify(data, null, 2) }}</pre>
    </div>
  </section>
</template>
