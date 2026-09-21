import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { createApiClient } from './api'
test('API client sends the exact interaction contract', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const fetcher: typeof fetch = async (input, init) => { calls.push({ url: String(input), init }); return new Response(JSON.stringify({ id:'s1', version:1, round:0, scene:{title:'',intro:''}, npcs:[], messages:[], clues:[], inventory:[], commitments:[], tasks:[], available_actions:[], ending:null })) }
  const api = createApiClient(fetcher)
  await api.getState('s1'); await api.interact('s1', { request_id:'r1', npc_id:'owner', text:'你好' })
  assert.equal(calls[0]?.url, '/api/sessions/s1'); assert.equal(calls[1]?.url, '/api/sessions/s1/interactions'); assert.equal(JSON.parse(String(calls[1]?.init?.body)).request_id, 'r1')
})

test('conflict reports backend error.message instead of generic HTTP text', async () => {
  const api = createApiClient(async () => new Response(JSON.stringify({
    error: { code: 'state_conflict', message: '状态已更新，请重试。' },
  }), { status: 409 }))
  await assert.rejects(api.interact('s', {request_id:'r', npc_id:'owner', text:'hi'}), /状态已更新/)
})

test('validation error array becomes readable text', async () => {
  const api = createApiClient(async () => new Response(JSON.stringify({
    detail: [{ msg: '文本太长' }],
  }), { status: 422 }))
  await assert.rejects(api.getState('s'), /文本太长/)
})
