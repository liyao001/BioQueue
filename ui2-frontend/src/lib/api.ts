export const API_BASE = (import.meta as any).env?.VITE_API_BASE || '/api'
const AUTH_TOKEN = (import.meta as any).env?.VITE_API_TOKEN
const AUTH_SCHEME = (import.meta as any).env?.VITE_API_AUTH_SCHEME || 'Token'

export function buildUrl(path: string): string {
  if (API_BASE.endsWith('/') && path.startsWith('/')) return API_BASE + path.slice(1)
  if (!API_BASE.endsWith('/') && !path.startsWith('/')) return API_BASE + '/' + path
  return API_BASE + path
}

export async function apiGet(path: string, init: RequestInit = {}) {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  }
  if (AUTH_TOKEN) {
    headers['Authorization'] = `${AUTH_SCHEME} ${AUTH_TOKEN}`
  }
  const res = await fetch(buildUrl(path), { credentials: 'include', headers, ...init })
  return res
}

export async function apiPost(path: string, body?: BodyInit, init: RequestInit = {}) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (AUTH_TOKEN) {
    headers['Authorization'] = `${AUTH_SCHEME} ${AUTH_TOKEN}`
  }
  const csrf = getCookie('csrftoken')
  if (csrf) {
    headers['X-CSRFToken'] = csrf
  }
  headers['X-Requested-With'] = 'XMLHttpRequest'
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    credentials: 'include',
    headers,
    body,
    ...init,
  })
  return res
}

export async function apiDelete(path: string, init: RequestInit = {}) {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  }
  if (AUTH_TOKEN) {
    headers['Authorization'] = `${AUTH_SCHEME} ${AUTH_TOKEN}`
  }
  const csrf = getCookie('csrftoken')
  if (csrf) {
    headers['X-CSRFToken'] = csrf
  }
  headers['X-Requested-With'] = 'XMLHttpRequest'
  const res = await fetch(buildUrl(path), {
    method: 'DELETE',
    credentials: 'include',
    headers,
    ...init,
  })
  return res
}

export async function apiPatch(path: string, body?: BodyInit, init: RequestInit = {}) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  }
  if (AUTH_TOKEN) {
    headers['Authorization'] = `${AUTH_SCHEME} ${AUTH_TOKEN}`
  }
  const csrf = getCookie('csrftoken')
  if (csrf) {
    headers['X-CSRFToken'] = csrf
  }
  headers['X-Requested-With'] = 'XMLHttpRequest'
  const res = await fetch(buildUrl(path), {
    method: 'PATCH',
    credentials: 'include',
    headers,
    body,
    ...init,
  })
  return res
}

function getCookie(name: string): string | null {
  const m = document.cookie.match('(?:^|; )' + name.replace(/([.$?*|{}()\[\]\\/+^])/g, '\\$1') + '=([^;]*)')
  return m ? decodeURIComponent(m[1]) : null
}


