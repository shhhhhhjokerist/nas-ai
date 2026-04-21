import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000
})

export async function getJson(url, params = {}) {
  const response = await api.get(url, { params })
  return response.data
}

export async function postJson(url, data = {}) {
  const response = await api.post(url, data)
  return response.data
}

export async function putJson(url, data = {}) {
  const response = await api.put(url, data)
  return response.data
}

export async function deleteJson(url, data = {}) {
  const response = await api.delete(url, { data })
  return response.data
}

export default api
