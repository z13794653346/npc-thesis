<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import Notebook from './Notebook.vue'
import DebugPanel from './DebugPanel.vue'
import { useGame } from './store'

const game = reactive(useGame())
const text = ref('')
const modelWarning = ref('正在检查模型连接配置……')
const messageBox = ref<HTMLElement | null>(null)
const currentNpc = computed(() => game.state?.npcs.find(n => n.id === game.selectedNpc))
const busy = computed(() => game.loading || game.pending)

onMounted(async () => {
  try {
    const health = await game.loadHealth()
    modelWarning.value = health.model_configured
      ? `真实模型接口已配置：${health.model}（配置存在不代表调用已验证）`
      : '尚未配置真实模型：聊天会提示缺少密钥；下方规则操作仍可使用，不会伪造AI回复。'
  } catch { modelWarning.value = '无法连接后端，请检查服务是否启动。' }
  await game.restore()
})
watch(() => [game.messages.length, game.selectedNpc], async () => {
  await nextTick()
  messageBox.value?.scrollTo({ top: messageBox.value.scrollHeight, behavior: 'smooth' })
})
async function send() {
  if (busy.value || !text.value.trim()) return
  await game.interact(text.value)
  if (!game.error && !game.pending) text.value = ''
}
async function reset() {
  if (confirm('开始新游戏？旧存档会保留，当前页面将切换到新旅程。')) await game.reset()
}
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div><span class="eyebrow">RAINY INN · NPC MEMORY LAB</span>
        <h1>{{ game.state?.scene.title || '第五位住客' }}</h1>
      </div>
      <div class="top-actions">
        <span class="round">第 {{ game.state?.round ?? 0 }} 轮</span>
        <button class="ghost" :disabled="busy" @click="reset">新游戏</button>
      </div>
    </header>
    <p class="notice" role="status">{{ modelWarning }}</p>
    <p v-if="game.error" class="alert" role="alert">{{ game.error }}</p>
    <div v-if="game.pending" class="notice">
      上一请求的结果尚未确认，请查询后再执行新操作。
      <button class="action" :disabled="game.loading" @click="game.retry">查询 / 重试上一请求</button>
    </div>
    <p v-if="game.loading" class="loading" role="status">正在处理，请稍候……</p>

    <section v-if="game.state" class="layout">
      <aside class="panel characters" aria-label="角色选择">
        <div class="section-label">旅店里的人</div>
        <button v-for="npc in game.state.npcs" :key="npc.id" class="character"
          :class="{ active: game.selectedNpc === npc.id }" :aria-pressed="game.selectedNpc === npc.id"
          :aria-label="`选择${npc.name}`" @click="game.selectedNpc = npc.id">
          <span class="avatar" aria-hidden="true">{{ npc.name.slice(0, 1) }}</span>
          <span><b>{{ npc.name }}</b><small>{{ npc.role }}</small></span>
          <em :aria-label="`信任 ${npc.trust}`">{{ npc.trust }}</em>
        </button>
        <p class="scene-intro">{{ game.state.scene.intro }}</p>
        <p class="rule-hint">
          每个人只记得自己的经历。AI只选择已知事实与合法行动，最终台词由程序按依据组织。
        </p>
      </aside>

      <section class="panel conversation" aria-label="角色交互">
        <div class="conversation-head">
          <div><div class="section-label">正在交谈 · {{ currentNpc?.role }}</div>
            <h2>{{ currentNpc?.name }}</h2><p class="character-description">{{ currentNpc?.description }}</p>
          </div>
          <span class="status-dot">信任 {{ currentNpc?.trust }} / 100</span>
        </div>
        <div ref="messageBox" class="messages" role="log" aria-label="对话记录" aria-live="polite">
          <div v-if="!game.messages.length" class="empty">
            雨水敲打着窗。<br>你可以先询问线索，或选择一项行动。
          </div>
          <article v-for="message in game.messages" :key="message.id" class="message" :class="message.speaker">
            <span>{{ message.speaker === 'player' ? '你' : message.speaker === 'npc' ? currentNpc?.name : '程序确认' }}</span>
            <p>{{ message.text }}</p>
          </article>
        </div>
        <form class="composer" @submit.prevent="send">
          <input v-model="text" :disabled="busy" maxlength="2000" aria-label="输入消息"
            placeholder="问问他记得什么……" autocomplete="off">
          <button :disabled="busy || !text.trim()">发送</button>
        </form>
        <div class="action-heading">可执行操作 <small>操作结果由程序校验，不等同角色台词</small></div>
        <div class="action-row">
          <button v-for="action in game.actions" :key="`${action.kind}-${action.target}`"
            class="action" :disabled="busy" @click="game.perform({ kind: action.kind, target: action.target })">
            {{ action.label }}
          </button>
          <span v-if="!game.actions.length" class="muted">暂时没有新操作</span>
        </div>
        <p v-if="game.lastResult?.action_result" class="reply-note" role="status">
          {{ game.lastResult.action_result.ok ? '✓ 操作已执行' : '○ 操作未执行' }}：
          {{ game.lastResult.action_result.message }}
        </p>
      </section>

      <Notebook :state="game.state" />
    </section>
    <p v-else-if="!game.loading" class="empty">未载入存档。可检查服务后刷新，或点击“新游戏”创建存档。</p>
    <DebugPanel v-if="game.debugEnabled && game.state" :key="game.state.id"
      v-model:token="game.debugToken" :read="game.debug" :export-data="game.exportSave" />
    <footer>NPC记忆与信任交互系统 · 本地演示 · 切换角色与阅读页面不消耗行动轮次</footer>
  </main>
</template>
