export type NpcId = 'owner' | 'mechanic' | 'traveler'
export type Speaker = 'player' | 'npc' | 'system'
export interface Scene { title: string; intro: string }
export interface Npc { id: NpcId; name: string; role: string; description: string; trust: number }
export interface Message { id: string; npc_id: NpcId | null; speaker: Speaker; text: string }
export interface Clue { id: string; title: string; text: string; source: string; verified: boolean }
export interface InventoryItem { id: string; name: string }
export interface Commitment { id: string; npc_id: NpcId; text: string; status: string; due_round: number | null }
export interface Task { id: string; title: string; npc_id: NpcId; done: boolean }
export interface AvailableAction { npc_id: NpcId; kind: string; target?: string; label: string }
export interface State { id: string; version: number; round: number; scene: Scene; npcs: Npc[]; messages: Message[]; clues: Clue[]; inventory: InventoryItem[]; commitments: Commitment[]; tasks: Task[]; available_actions: AvailableAction[]; ending: string | null }
export interface Result { request_id: string; status: 'completed' | 'failed' | 'processing'; reply: string; action_result: { ok: boolean; message: string } | null; state: State; error: { code: string; message: string } | null }
export interface InteractionRequest { request_id: string; npc_id: NpcId; text: string }
export interface ActionRequest { request_id: string; npc_id: NpcId; action: { kind: string; target?: string; evidence_id?: string } }
