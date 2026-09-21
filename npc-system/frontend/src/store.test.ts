import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { createApiClient } from './api'
import { useGame } from './store'
import type { Result, State } from './types'

function state(id = 'saved'): State {
  return { id, version: 0, round: 0, scene: { title: '旅店', intro: '' }, npcs: [],
    messages: [], clues: [], inventory: [], commitments: [], tasks: [],
    available_actions: [], ending: null }
}
function storage() {
  const data = new Map<string, string>()
  return { getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value) } }
}

test('reset persists the new session and clears old feedback', async () => {
  const api = createApiClient(async () => new Response(JSON.stringify(state('new'))))
  const saved = storage()
  const game = useGame(api, saved)
  game.state.value = state()
  game.lastResult.value = { status: 'failed' } as Result
  await game.reset()
  assert.equal(saved.getItem('npc-session-id'), 'new')
  assert.equal(game.state.value?.id, 'new')
  assert.equal(game.lastResult.value, null)
})

test('network retry reuses original request id and target NPC', async () => {
  const bodies: Array<{ request_id: string; npc_id: string }> = []
  let disconnected = true
  const api = createApiClient(async (_url, init) => {
    bodies.push(JSON.parse(String(init?.body)))
    if (disconnected) throw new TypeError('offline')
    return new Response(JSON.stringify({ request_id: bodies[0]?.request_id, status: 'completed',
      reply: '已记录', action_result: null, error: null, state: state() }))
  })
  const game = useGame(api, storage())
  game.state.value = state()
  await game.interact('你好')
  assert.equal(game.pending.value, true)
  game.selectedNpc.value = 'mechanic'
  disconnected = false
  await game.retry()
  assert.equal(new Set(bodies.map(body => body.request_id)).size, 1)
  assert.ok(bodies.every(body => body.npc_id === 'owner'))
  assert.equal(game.pending.value, false)
})

test('server failure is visible and messages are filtered by recipient', async () => {
  const s = state()
  s.messages = [{ id: 'a', npc_id: 'owner', speaker: 'player', text: '给店主' },
    { id: 'b', npc_id: 'traveler', speaker: 'npc', text: '旅客的回答' }]
  const api = createApiClient(async () => new Response(JSON.stringify({ request_id: 'r',
    status: 'failed', reply: '缺密钥', state: s, action_result: null,
    error: { code: 'missing', message: '缺密钥' } })))
  const game = useGame(api, storage())
  game.state.value = s
  await game.interact('你好')
  assert.equal(game.error.value, '缺密钥')
  assert.deepEqual(game.messages.value.map(m => m.id), ['a'])
  game.selectedNpc.value = 'traveler'
  assert.deepEqual(game.messages.value.map(m => m.id), ['b'])
})

test('in-progress result remains retryable rather than treated as completed', async () => {
  const api = createApiClient(async () => new Response(JSON.stringify({ request_id: 'r',
    status: 'processing', reply: '处理中', state: state(), action_result: null, error: null }), { status: 202 }))
  const game = useGame(api, storage())
  game.state.value = state()
  await game.interact('你好')
  assert.equal(game.pending.value, true)
})
