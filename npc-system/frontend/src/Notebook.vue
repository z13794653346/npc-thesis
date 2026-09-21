<script setup lang="ts">
import type { State } from './types'
defineProps<{ state: State }>()
const statusLabels: Record<string, string> = {
  active: '进行中', fulfilled: '已守约', breached: '已失信', returned_late: '已逾期归还',
}
</script>

<template>
  <aside class="panel notebook" aria-label="调查笔记">
    <div class="section-label notebook-title">调查笔记 · 只记录你已获得的信息</div>
    <section aria-label="线索">
      <h3>线索 <small>{{ state.clues.length }} / 3</small></h3>
      <p v-if="!state.clues.length" class="empty compact">还没有取得线索。</p>
      <article v-for="clue in state.clues" :key="clue.id" class="clue">
        <b>{{ clue.title }}</b><p>{{ clue.text }}</p>
        <small>来源：{{ state.npcs.find(n => n.id === clue.source)?.name ?? clue.source }}
          · {{ clue.verified ? '已核验记录' : '未经证实' }}</small>
      </article>
      <p v-if="state.clues.length" class="rule-hint">切换角色后，可在操作区定向转述对方尚未知晓的线索。</p>
    </section>
    <section aria-label="承诺">
      <h3>承诺 <small>{{ state.commitments.length }}</small></h3>
      <p v-if="!state.commitments.length" class="empty compact">尚未作出承诺。</p>
      <div v-for="item in state.commitments" :key="item.id" class="commitment">
        <span aria-hidden="true">●</span><div><p>{{ item.text }}</p>
          <strong class="commitment-status">{{ statusLabels[item.status] ?? item.status }}</strong>
          <small v-if="item.due_round !== null"> · 第 {{ item.due_round }} 轮结束前</small>
        </div>
      </div>
    </section>
    <section aria-label="背包">
      <h3>背包 <small>{{ state.inventory.length }}</small></h3>
      <p v-if="!state.inventory.length" class="empty compact">没有携带物品。</p>
      <p v-for="item in state.inventory" :key="item.id" class="inventory">▧ {{ item.name }}</p>
    </section>
    <section aria-label="协助任务">
      <h3>协助任务</h3>
      <p v-for="task in state.tasks" :key="task.id" class="inventory">
        {{ task.done ? '✓ 已完成' : '○ 待完成' }} · {{ task.title }}
      </p>
    </section>
    <section v-if="state.ending" class="ending" aria-label="调查结果">
      <h3>调查完成</h3><p>{{ state.ending }}</p>
    </section>
  </aside>
</template>
