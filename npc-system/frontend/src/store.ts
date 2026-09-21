import { computed, ref } from 'vue'
import { ApiError, createApiClient } from './api'
import type { ApiClient } from './api'
import type { NpcId, Result, State } from './types'

const savedKey = 'npc-session-id'
type SaveStorage = Pick<Storage, 'getItem' | 'setItem'>

export function useGame(api: ApiClient = createApiClient(), saved: SaveStorage = localStorage) {
  const state = ref<State | null>(null)
  const selectedNpc = ref<NpcId>('owner')
  const loading = ref(false)
  const error = ref('')
  const pending = ref(false)
  const debugToken = ref('')
  const debugEnabled = ref(false)
  const lastResult = ref<Result | null>(null)
  let pendingTask: (() => Promise<Result>) | null = null
  const actions = computed(() => state.value?.available_actions.filter(a => a.npc_id === selectedNpc.value) ?? [])
  const messages = computed(() => state.value?.messages.filter(m => m.npc_id === selectedNpc.value) ?? [])

  function acceptState(next: State) {
    state.value = next
    saved.setItem(savedKey, next.id)
  }
  async function runState(task: () => Promise<State>) {
    if (loading.value || pending.value) return
    loading.value = true
    error.value = ''
    try {
      acceptState(await task())
      lastResult.value = null
      debugToken.value = ''
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '读取存档失败'
    } finally { loading.value = false }
  }
  async function runResult(task: () => Promise<Result>) {
    if (loading.value) return
    loading.value = true
    error.value = ''
    pendingTask = task
    pending.value = true
    try {
      const result = await task()
      acceptState(result.state)
      lastResult.value = result
      pending.value = result.status === 'processing'
      if (result.status === 'failed') error.value = result.error?.message ?? result.reply
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '连接失败，请重试上一请求'
      if (cause instanceof ApiError && cause.status < 500) {
        pending.value = false
        if (cause.result) acceptState(cause.result.state)
      }
    } finally {
      if (!pending.value) pendingTask = null
      loading.value = false
    }
  }
  async function restore() {
    const id = saved.getItem(savedKey)
    if (id) await runState(() => api.getState(id))
    else await newGame()
  }
  async function loadHealth() {
    const health = await api.health()
    debugEnabled.value = health.debug_enabled
    return health
  }
  async function newGame() { await runState(() => api.createSession()) }
  async function reset() {
    const id = state.value?.id
    if (id) await runState(() => api.reset(id))
    else await newGame()
  }
  async function interact(text: string) {
    if (!state.value || !text.trim() || pending.value || loading.value) return
    const id = state.value.id
    const body = { request_id: crypto.randomUUID(), npc_id: selectedNpc.value, text: text.trim() }
    await runResult(() => api.interact(id, body))
  }
  async function perform(action: { kind: string; target?: string }) {
    if (!state.value || pending.value || loading.value) return
    const id = state.value.id
    const body = { request_id: crypto.randomUUID(), npc_id: selectedNpc.value, action: { ...action } }
    await runResult(() => api.action(id, body))
  }
  async function retry() { if (pendingTask) await runResult(pendingTask) }
  async function debug() {
    if (!state.value || !debugToken.value) throw new Error('请输入调试口令')
    return api.debug(state.value.id, debugToken.value)
  }
  async function exportSave() {
    if (!state.value || !debugToken.value) throw new Error('请输入调试口令')
    return api.exportSave(state.value.id, debugToken.value)
  }
  return { state, selectedNpc, loading, error, pending, debugToken, debugEnabled,
    lastResult, actions, messages, restore, loadHealth, newGame, reset, interact,
    perform, retry, debug, exportSave }
}
